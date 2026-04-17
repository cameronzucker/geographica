# Adversarial Memory Review: NOAA Imagery Pipeline

Date: 2026-04-16
Reviewer: Claude (adversarial review)
Symptom: RSS 4.3 GB after only 3 tiles, despite gc.collect() + malloc_trim() + del mosaic

## Executive Summary

The existing mitigations (gc.collect, malloc_trim, del mosaic) address **one** of at
least **10** distinct memory leak vectors. The dominant issue is that
`rasterio_merge()` allocates a full in-memory mosaic (~1.5 GB for a single 486 MB
NAIP quad), and while `del mosaic` frees the Python reference, **concurrent
reprojection threads are also holding similarly large arrays**, and several secondary
leaks compound the problem. After 3 tiles, you have:

- 1 mosaic in `merge_to_mbtiles` (~1.5 GB)
- Up to N concurrent reproject operations (~1-2 GB each in rasterio.warp buffers)
- GDAL block cache (default 5% of RAM = ~800 MB, never configured in rasterio_ops.py)
- Accumulated MemoryFile/tile artifacts from _rasterize_to_disk inner loop
- SQLite fetchall() materializations in merge_mbtiles and post-processing

Total: easily 4-6 GB from structural causes alone.

---

## Finding 1: CRITICAL — GDAL Block Cache Uncapped in rasterio_ops.py

**File:** `scripts/rasterio_ops.py` (entire file -- no GDAL_CACHEMAX set anywhere)
**File:** `scripts/acquire_imagery.py:1659` (_NOAA_GDAL_ENV sets 256 but is never passed to rasterio)

`rasterio_ops.py` calls `rasterio.open()`, `rasterio.warp.reproject()`, and
`rasterio.merge.merge()` without ever setting `GDAL_CACHEMAX`. GDAL's default block
cache is 5% of system RAM. On a 16 GB Pi 5, that is **~800 MB** of GDAL internal
cache that persists across open/close cycles within the same process.

`acquire_imagery.py` line 1659 defines `_NOAA_GDAL_ENV` with `GDAL_CACHEMAX=256`,
but this dict is **only used by `run_gdal_subprocess()`** (line 753-757) for spawning
CLI subprocesses. The rasterio-based functions in `rasterio_ops.py` run in-process
and inherit the default.

**Allocation:** ~800 MB persistent, never freed.
**gc.collect + malloc_trim fixes this?** No. GDAL cache is C-level, invisible to Python GC.

**Fix:** At the top of `rasterio_ops.py` or at the start of `run_noaa()`:
```python
os.environ["GDAL_CACHEMAX"] = "256"  # Must be set BEFORE first rasterio.open()
```
Or via rasterio's API:
```python
from rasterio._env import GDALDataFinder
# Actually, set via env before importing rasterio, or:
import rasterio
rasterio.gdal_version()  # force init
from osgeo import gdal
gdal.SetCacheMax(256 * 1024 * 1024)
```

---

## Finding 2: CRITICAL — rasterio_merge() Mosaic Lives Alongside _rasterize_to_disk Output

**File:** `scripts/rasterio_ops.py:322-352`

The call sequence is:
1. `datasets = [rasterio.open(str(p)) for p in input_paths]` -- opens all GeoTIFFs
2. `mosaic, mosaic_transform = rasterio_merge(datasets)` -- allocates full mosaic
3. `_rasterize_to_disk(mosaic, ...)` -- reads mosaic, creates tile arrays in a loop
4. `del mosaic` + gc.collect + malloc_trim -- tries to free

**Problem:** For a single 486 MB NAIP quad (compressed on disk), the uncompressed
mosaic is approximately:
- 10000 x 10000 pixels x 4 bands x uint8 = ~400 MB (NAIP is 4-band)
- Or 3-band after merge: ~300 MB per band arrangement

But `rasterio_merge()` reads the data as float64 internally for its merge algorithm,
then returns it. The returned array is `float64` by default:
- 10000 x 10000 x 4 bands x 8 bytes = **3.2 GB** for a single quad

Even if rasterio returns uint8 (depends on version/config), the intermediate float64
workspace exists during the merge call.

**Allocation:** 1.5-3.2 GB per tile for the mosaic.
**gc.collect + malloc_trim fixes this?** Partially. `del mosaic` drops the Python
reference, gc.collect handles cycles, malloc_trim returns to OS. But this only
works if no other references to the mosaic exist. See Finding 3.

**Fix:** For single-file merges (which is the common case in NOAA pipeline --
`convert_batch_to_mbtiles([warped_path], ...)`), skip `rasterio_merge` entirely.
When `len(input_paths) == 1`, just open the single file and read directly.
This eliminates the merge copy.

---

## Finding 3: HIGH — mosaic_transform Retains Reference to Mosaic via Closure

**File:** `scripts/rasterio_ops.py:325,349`

```python
mosaic, mosaic_transform = rasterio_merge(datasets)
# ... mosaic is passed to _rasterize_to_disk
tile_count = _rasterize_to_disk(mosaic, mosaic_transform, ...)
del mosaic  # Line 365
```

After `del mosaic`, `_rasterize_to_disk` has already returned so its stack frame
is gone. This is correct. However, `mosaic_transform` is an `Affine` object which
does NOT hold a reference to the mosaic array. This specific vector is NOT a leak.

**Verdict:** False alarm. mosaic_transform is a small object.

---

## Finding 4: CRITICAL — Concurrent Reproject Threads Each Hold Full-Raster Buffers

**File:** `scripts/rasterio_ops.py:209-245` (reproject_to_mercator)
**File:** `scripts/acquire_imagery.py:1918-1921,2111-2113`

The pipeline runs up to `REPROJECT_WORKERS = min(cpu_count, 6)` concurrent
reproject threads. Each `reproject_to_mercator()` call:
1. Opens the source GeoTIFF (~486 MB compressed, ~1.5 GB uncompressed in GDAL cache)
2. Calls `rasterio.warp.reproject()` per band, which allocates:
   - Source block buffer (read from src)
   - Destination block buffer (write to dst)
   - GDAL warp kernel workspace

For a 486 MB NAIP quad with 4 bands at 10000x10000, each reproject holds:
- ~1.5 GB in GDAL block cache reads (shared cache, but contended)
- ~1.5 GB for the destination array

With 4-6 concurrent workers: **6-9 GB peak** in reproject buffers alone.

**Allocation:** ~1.5 GB per concurrent reproject worker.
**gc.collect + malloc_trim fixes this?** No. The allocations are live while the
thread is running. Only freed when the thread completes and rasterio closes the
dataset. The gc.collect in `_reproject_tile` (line 2007) runs AFTER the reproject
finishes, which is correct, but doesn't help with concurrent peak.

**Fix:** Reduce `REPROJECT_WORKERS` to 1 or 2 on a 16 GB system. Currently:
```python
REPROJECT_WORKERS = min(cpu_count, 6, total_tiles)
```
On a Pi 5 (4 cores): `min(4, 6, N)` = up to 4 concurrent reprojects.
4 x 1.5 GB = 6 GB just in reproject buffers. Should be:
```python
REPROJECT_WORKERS = min(2, total_tiles)  # Memory-safe on 16 GB
```

---

## Finding 5: HIGH — _read_tile_from_array Creates 3 Temporary Arrays Per Tile

**File:** `scripts/rasterio_ops.py:568-634`

Inside the tight inner loop of `_rasterize_to_disk`, for every tile:

```python
window_data = data[:, row_start:row_end, col_start:col_end]  # View (free)

# Line 619-626: Two temporary numpy arrays for resize indices
src_rows = np.minimum(...)  # float64 array, ~256 elements
src_cols = np.minimum(...)  # float64 array, ~256 elements

# Line 627: Fancy indexing creates a COPY, not a view
resized = window_data[:, src_rows, :][:, :, src_cols]  # ~192 KB (3x256x256 uint8)

# Line 631: Output tile allocation
tile = np.zeros((bands, tile_size, tile_size), dtype=data.dtype)  # ~192 KB
```

Per tile: ~384 KB + index arrays. For thousands of tiles per quad, these are
created and freed each iteration. Python's small-object allocator should handle
this. BUT:

**The real problem:** `window_data[:, src_rows, :][:, :, src_cols]` performs TWO
fancy-index operations. The first creates an intermediate array of size
`(bands, len(src_rows), full_width)` which could be large if the window spans
the full raster width. For a 10000-pixel-wide source, intermediate is
`3 x 256 x 10000 = 7.3 MB`. Multiplied by thousands of tiles, this creates
massive allocation churn that fragments the heap.

**Allocation:** ~7 MB intermediate per tile, thousands of times per quad.
**gc.collect + malloc_trim fixes this?** malloc_trim helps defragment, but the
churn itself is the problem. glibc's allocator may hold onto the arenas.

**Fix:** Replace the two-step fancy indexing with a single `np.take` or
pre-allocate the resize buffer outside the loop:
```python
# One-step fancy indexing avoids the large intermediate:
resized = window_data[:, src_rows[:, None], src_cols[None, :]]
```
Or better yet, use `scipy.ndimage.zoom` or `cv2.resize` on the window directly.

---

## Finding 6: HIGH — datasets List Keeps All GeoTIFFs Open During Tile Rendering

**File:** `scripts/rasterio_ops.py:322,389-391`

```python
datasets = [rasterio.open(str(p)) for p in input_paths]
try:
    mosaic, mosaic_transform = rasterio_merge(datasets)
    # ... render tiles ... (could take minutes)
    del mosaic
    # ... bulk import ... (more minutes)
finally:
    for ds in datasets:
        ds.close()
```

The datasets list holds open file handles and GDAL dataset objects for the ENTIRE
duration of tile rendering and bulk import. Each open GDAL dataset has its own
block cache entries. For the NOAA pipeline, `convert_batch_to_mbtiles` is called
with `[warped_path]` (one file), so this is 1 dataset -- manageable.

But in M2M mode, `convert_batch_to_mbtiles` can receive multiple files. Each open
dataset consumes GDAL cache slots.

**More importantly:** The datasets are kept open AFTER `rasterio_merge` returns.
The merge has already read all data into `mosaic`. The datasets serve no purpose
after line 325 but are held until the finally block at line 389.

**Allocation:** Per-dataset GDAL overhead, ~50-200 MB depending on cache pressure.
**gc.collect + malloc_trim fixes this?** No. GDAL dataset objects are C-level.

**Fix:** Close datasets immediately after merge:
```python
mosaic, mosaic_transform = rasterio_merge(datasets)
first_crs = datasets[0].crs
# Compute bounds_4326 here...
for ds in datasets:
    ds.close()
datasets = []  # Release list
# Now proceed with tile rendering...
```

---

## Finding 7: HIGH — merge_mbtiles fetchall() Loads ALL Overlapping Tiles Into Memory

**File:** `scripts/acquire_imagery.py:639-646`

```python
overlapping = dst.execute("""
    SELECT s.zoom_level, s.tile_column, s.tile_row, s.tile_data, d.tile_data
    FROM src.tiles s
    JOIN tiles d ON ...
    WHERE s.tile_data != d.tile_data
""").fetchall()
```

This loads ALL overlapping tile pairs into memory at once. Each tile_data BLOB is
a JPEG (~15-50 KB). For a NAIP quad at zoom 12-16, there could be hundreds of
overlapping edge tiles. Two BLOB columns per row:

- 200 overlapping tiles x 2 BLOBs x 30 KB average = ~12 MB

This is modest for one call. BUT `merge_mbtiles` is called once per tile in the
NOAA pipeline (via `convert_batch_to_mbtiles`), and the overlapping set grows as
more tiles are merged. After 50 tiles, the overlap query could return thousands
of rows.

**Allocation:** 12 MB initially, grows to potentially 100+ MB after many merges.
**gc.collect + malloc_trim fixes this?** Yes, if the list goes out of scope.
But the function returns without explicitly deleting `overlapping`.

**Fix:** Use a cursor iterator instead of fetchall():
```python
cursor = dst.execute("""SELECT ...""")
for z, x, y, src_data, dst_data in cursor:
    # process one at a time
```

---

## Finding 8: MEDIUM — inpaint_nodata_pixels fetchall() Loads ALL Tiles Into Memory

**File:** `scripts/rasterio_ops.py:804-808`

```python
tiles = conn.execute(
    "SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles"
).fetchall()
```

This loads EVERY tile (including tile_data BLOBs) from the MBTiles database into
Python memory at once. After processing multiple NAIP quads, the database could
contain tens of thousands of tiles. At ~30 KB average per JPEG tile:

- 10,000 tiles x 30 KB = **300 MB** in the fetchall list
- 50,000 tiles x 30 KB = **1.5 GB** in the fetchall list

This function runs in the post-processing phase (line 2232), by which point the
database could be very large.

**Allocation:** 300 MB to 1.5+ GB depending on tile count.
**gc.collect + malloc_trim fixes this?** Yes, after the function returns, but
during execution this is a huge spike.

**Fix:** Use an iterator with a LIMIT/OFFSET pattern or cursor:
```python
cursor = conn.execute("SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles")
for z, x, y, data in cursor:
    # process one tile at a time
```

---

## Finding 9: MEDIUM — erode_nodata_edges fetchall() for Boundary Tiles

**File:** `scripts/rasterio_ops.py:886-888`

```python
boundary = conn.execute(
    "SELECT tile_column, tile_row, tile_data FROM tiles "
    "WHERE zoom_level=? AND (...)",
    (z, min_col, max_col, min_row, max_row),
).fetchall()
```

Similar to Finding 8 but scoped to boundary tiles at each zoom level. Still loads
all BLOBs for the boundary ring. For a large coverage area, the boundary at max
zoom could be hundreds of tiles.

**Allocation:** ~10-50 MB per zoom level iteration.
**gc.collect + malloc_trim fixes this?** Yes, when the list goes out of scope at
next loop iteration. But multiple zoom levels compound.

**Fix:** Use cursor iteration.

---

## Finding 10: MEDIUM — build_overviews fetchall() for Tile Positions

**File:** `scripts/rasterio_ops.py:692-695`

```python
rows = conn.execute(
    "SELECT DISTINCT tile_column/2, tile_row/2 FROM tiles WHERE zoom_level = ?",
    (parent_z,),
).fetchall()
```

This is positions only (no BLOBs), so memory impact is small (~20 bytes per row).
At max zoom with thousands of tiles, this is ~100 KB. **Low risk.**

**Allocation:** ~100 KB.
**gc.collect + malloc_trim fixes this?** N/A, too small to matter.

---

## Finding 11: MEDIUM — Traceback Objects in Exception Handlers Retain Frame Locals

**File:** `scripts/rasterio_ops.py:251,395`
**File:** `scripts/acquire_imagery.py:1995-1999,845-847`

```python
except Exception as exc:
    log.error("Reproject failed for %s: %s", src_path.name, exc)
```

When an exception is caught with `as exc`, the exception object retains a
reference to `__traceback__`, which in turn references all frame locals in
the traceback chain. If the exception occurred inside `rasterio.warp.reproject()`,
the traceback holds references to the source and destination band arrays.

In CPython, `exc` is deleted when the except block exits (PEP 3110), so this
is typically safe. BUT: if `log.error` internally stores the exception (some
logging handlers do), or if the exception propagates up, the traceback chain
can persist.

**Allocation:** Potentially GB-scale if reproject fails while holding large arrays.
**gc.collect + malloc_trim fixes this?** gc.collect breaks cycles, but the
traceback reference is not a cycle -- it's a direct chain.

**Fix:** Explicitly clear traceback in error handlers:
```python
except Exception as exc:
    log.error("Reproject failed for %s: %s", src_path.name, exc)
    del exc  # Already implicit in CPython, but explicit is safer
```
Or more importantly, ensure `exc` doesn't escape the except block.

---

## Finding 12: LOW — MemoryFile Objects in _encode_jpeg/_encode_png

**File:** `scripts/rasterio_ops.py:89-116`

```python
def _encode_jpeg(array, quality=85):
    with rasterio.MemoryFile() as memfile:
        with memfile.open(...) as dst:
            dst.write(array[:3])
        return memfile.read()
```

The `with` statement correctly closes the MemoryFile. However, rasterio's
MemoryFile uses GDAL's `/vsimem/` virtual filesystem internally. Repeated
creation/destruction of MemoryFiles can fragment GDAL's internal memory pool.

Called thousands of times per tile rendering pass. Each creates a VSIMEM
buffer of ~15-50 KB (JPEG size).

**Allocation:** ~50 KB per call, properly freed. But GDAL vsimem fragmentation
could cause the virtual filesystem to hold onto memory.
**gc.collect + malloc_trim fixes this?** No, vsimem is GDAL-internal.

**Fix:** Low priority. Could reuse a single MemoryFile across calls, but the
current pattern is correct and the per-call overhead is small.

---

## Finding 13: LOW — ThreadPoolExecutor Not Releasing Thread-Local Storage

**File:** `scripts/acquire_imagery.py:1918-1921,2190`

```python
reproject_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=REPROJECT_WORKERS,
    thread_name_prefix="reproject",
)
# ...
finally:
    reproject_pool.shutdown(wait=False)
```

`shutdown(wait=False)` tells threads to finish their current task but doesn't
wait for them. Thread-local storage (including rasterio/GDAL per-thread state)
is not cleaned up until threads actually terminate.

More importantly, `wait=False` means the finally block continues while reproject
threads may still be running, holding their rasterio buffers. If the process
continues to post-processing while threads still hold memory, peak RSS spikes.

**Allocation:** Up to REPROJECT_WORKERS x 1.5 GB if threads haven't finished.
**gc.collect + malloc_trim fixes this?** No. Threads own the memory.

**Fix:** Use `shutdown(wait=True)` or ensure all futures are done before shutdown.

---

## Finding 14: MEDIUM — merge_mbtiles Opens src_data/dst_data MemoryFiles Without Cleanup on Error

**File:** `scripts/acquire_imagery.py:649-665`

```python
for z, x, y, src_data, dst_data in overlapping:
    try:
        with MemoryFile(src_data) as smf, MemoryFile(dst_data) as dmf:
            with smf.open() as sds, dmf.open() as dds:
                src_arr = sds.read()
                dst_arr = dds.read()
        # Compositing...
    except Exception:
        pass  # Keep existing tile on decode error
```

The `with` blocks correctly handle the MemoryFiles. However, `src_arr` and
`dst_arr` (each ~192 KB for a 256x256x3 uint8 tile) survive the with block
and persist until the next loop iteration overwrites them. If the compositing
code after the `with` block raises, the arrays persist until the next iteration.

The bare `except Exception: pass` means errors are silently swallowed. If the
error happens AFTER the MemoryFile blocks but BEFORE the arrays are overwritten,
both arrays persist.

**Allocation:** ~384 KB per failed tile. Minor.
**gc.collect + malloc_trim fixes this?** Yes, trivially.

---

## Finding 15: MEDIUM — _on_batch Closure Retains Reference to `paths` List

**File:** `scripts/acquire_imagery.py:1420-1434,1447-1449`

```python
def _on_file(files_done, files_in_batch):
    if on_batch_complete:
        on_batch_complete(...)

batch_paths = await download_geotiffs(...)

# Background task holds closure over `paths` (which is `batch_paths`)
if batch_paths and output_path:
    pending_conversion = asyncio.create_task(
        _convert_and_cleanup(batch_paths, f"Batch {batch_num}")
    )
```

The `pending_conversion` task holds a reference to `batch_paths` (a list of
Path objects). After conversion, `_convert_and_cleanup` deletes the files
but not the Path objects. The task result (or exception) is stored in the
task object until it's awaited or garbage collected.

**Allocation:** Small (list of Path objects), ~1 KB.
**gc.collect + malloc_trim fixes this?** Yes.

---

## Summary: Priority-Ordered Fix List

| # | Severity | Finding | Est. RSS Impact | gc/malloc_trim helps? |
|---|----------|---------|-----------------|----------------------|
| 1 | CRITICAL | GDAL block cache uncapped in rasterio_ops | ~800 MB persistent | No |
| 4 | CRITICAL | Concurrent reproject workers x 1.5 GB each | ~4-6 GB peak | No |
| 2 | CRITICAL | rasterio_merge float64 mosaic for single files | ~1.5-3.2 GB | Partially |
| 5 | HIGH | _read_tile_from_array intermediate arrays | ~7 MB x thousands = heap frag | Partially |
| 6 | HIGH | datasets held open during tile rendering | ~200 MB wasted | No |
| 7 | HIGH | merge_mbtiles fetchall with BLOBs | ~100 MB growing | Yes |
| 8 | HIGH | inpaint_nodata_pixels fetchall ALL tiles | ~300 MB-1.5 GB | Yes |
| 13 | MEDIUM | ThreadPoolExecutor shutdown(wait=False) | ~1.5 GB x N threads | No |
| 9 | MEDIUM | erode_nodata_edges fetchall boundary tiles | ~10-50 MB | Yes |
| 11 | MEDIUM | Traceback objects retaining frame locals | Potentially GB on error | Partially |
| 14 | MEDIUM | merge_mbtiles error path array retention | ~384 KB per error | Yes |
| 12 | LOW | MemoryFile vsimem fragmentation | Negligible | No |
| 15 | LOW | Task closure retaining batch_paths | ~1 KB | Yes |

## Why 4.3 GB After 3 Tiles

After 3 tiles through the NOAA pipeline:
- GDAL block cache: **800 MB** (Finding 1, never freed)
- 3-4 concurrent reproject workers: **4.5-6 GB** peak (Finding 4)
- Merge mosaic: **1.5 GB** per call, freed between calls but glibc may not return
- _rasterize_to_disk heap fragmentation: **200-500 MB** retained by glibc arenas

The gc.collect + malloc_trim after `del mosaic` helps with the mosaic itself, but
Findings 1 and 4 are the dominant leaks and are **completely unaffected** by
gc.collect/malloc_trim because they are C-level allocations inside GDAL/rasterio.

## Recommended Fix Order

1. **Set GDAL_CACHEMAX=256 before any rasterio import** (Finding 1) -- immediate 800 MB savings
2. **Reduce REPROJECT_WORKERS to 2** (Finding 4) -- immediate 3+ GB peak reduction
3. **Skip rasterio_merge for single-file inputs** (Finding 2) -- 1.5 GB savings per tile
4. **Close datasets immediately after merge** (Finding 6) -- 200 MB savings
5. **Replace fetchall with cursor iteration** (Findings 7, 8, 9) -- prevent post-processing spike
6. **Fix shutdown(wait=True)** (Finding 13) -- prevent overlap between reproject and post-processing
7. **Fix fancy indexing intermediate** (Finding 5) -- reduce heap fragmentation
