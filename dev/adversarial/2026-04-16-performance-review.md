# Performance Review: NOAA NAIP Pipeline
**Date:** 2026-04-16  
**Reviewer:** Performance specialist (adversarial)  
**Baseline:** 494 tiles @ ~0.7 tiles/min on Pi 5 (4 cores, 16 GB RAM, SATA SSD, ~3 MB/s per Azure stream)

---

## Executive Summary

At 0.7 tiles/min for a 486 MB GeoTIFF → ~1,100 z17 JPEG tile pipeline, the bottleneck is **the merge stage** — specifically `rasterio_merge()` loading the full warped GeoTIFF into RAM and then `_rasterize_to_disk()` executing the tile extraction loop serially. The pipeline is **CPU-bound in the merge stage, not download-bound**, even though it looks concurrent. The 3-stage architecture (download → reproject → merge) is sound but the serial merger serializes the entire pipeline in practice. A series of targeted fixes could plausibly achieve **3-5× throughput without a rewrite**.

---

## Bottleneck Identification

### What the pipeline actually does per NAIP quad

1. **Download** (async, 8 concurrent): ~160s per 486 MB quad at 3 MB/s
2. **Reproject** (ThreadPoolExecutor, ≤4 workers): gdalwarp equivalent via rasterio, writes compressed GeoTIFF back to disk. For a 486 MB TIFF reprojected with Lanczos, this is ~60-120s on Cortex-A76
3. **Merge** (serial, 1 worker): `convert_batch_to_mbtiles` → `merge_to_mbtiles` → `rasterio_merge` (loads full warped GeoTIFF into RAM, ~1.5 GB numpy array) → `_rasterize_to_disk` (iterates ~1,100 tiles serially in Python) → `_bulk_import_tiles` (sequential SQLite inserts). This is the wall.

### Where time is actually going

At steady state with 4 reproject workers:
- Downloads complete fast (8 concurrent × 3 MB/s = 24 MB/s peak, ~20s per quad at saturation)
- Reprojection runs 4-at-a-time; each ~90s → pipeline outputs a warped quad every ~22s at saturation
- **Merge is serial and takes ~700-900s per quad** (0.7 tiles/min × ~540 tiles avg = ~770s per quad)

The merger is **35-40× slower than the reprojector output rate**. The reproject_queue and merge_queue fill immediately and both become blocked on the serial merger. At steady state, 3 of the 4 reproject workers are idle waiting for merge_queue to drain.

---

## Finding 1: `rasterio_merge()` — Full-Array Load Is the Worst Bottleneck

**Location:** `rasterio_ops.py:325`, called from `merge_to_mbtiles()`

**Problem:**
```python
mosaic, mosaic_transform = rasterio_merge(datasets)
```
This loads the **entire reprojected GeoTIFF** into a single numpy array in RAM. For a NAIP quad at 1 m/pixel resolution over a 10×10 km quad, the warped GeoTIFF is ~1.5 GB (3 bands × uint8 × ~22,000×22,000 pixels). This:
- Consumes 1.5 GB RAM per merge call (only 4 GB container limit, swap pressure is real)
- Has no streaming path — the entire array must be resident before a single tile can be rendered
- Blocks the event loop thread (run via `loop.run_in_executor(None, _merge_tile, ...)`) for the full duration

**Streaming alternative:** Since the warped GeoTIFF is already written to disk as a tiled GeoTIFF with 256×256 blocks (the `blockxsize=256, blockysize=256` profile in `reproject_to_mercator`), you can open it with rasterio and read only the window corresponding to each tile using `src.read(window=window)`. No mosaic needed for a single-input merge — the single warped file IS the mosaic.

The `merge_to_mbtiles` function is called with `[warped_path]` (a list of one file). `rasterio_merge` with one dataset is just a full read. This entire array-load step is unnecessary for the single-file case.

**Fix:** When `len(input_paths) == 1`, skip `rasterio_merge` entirely. Instead open the file, read each tile window on demand, encode, write. This is a streaming approach with O(1) memory instead of O(N).

**Estimated speedup:** 2-3× on the merge stage alone (eliminates the 1.5 GB allocation + deallocation + GC cycle that currently precedes tile rendering). Also eliminates most swap pressure.

**Memory reduction:** ~1.5 GB per concurrent merge call. Critical on a 4 GB container.

**Implementation complexity:** Low-Medium. The tile bounds → window calculation already exists in `_read_tile_from_array` logic; just open the rasterio dataset directly instead of passing the numpy array.

---

## Finding 2: `_rasterize_to_disk()` — Purely Serial Python Tile Loop

**Location:** `rasterio_ops.py:426-490`

**Problem:**
```python
for zoom in range(min_zoom, max_zoom + 1):
    for tx in range(x_min, x_max + 1):
        for ty in range(y_min, y_max + 1):
            tile_data = _read_tile_from_array(data, transform, tile_bounds_src, TILE_SIZE)
            tile_bytes = encode_fn(tile_data, quality)
            (z_dir / f"{tms_y}.tile").write_bytes(tile_bytes)
```

For ~1,100 tiles at z17 plus overviews at z13-z16, this is a pure Python triple-nested loop with no parallelism. Each iteration:
- Calls `transform_bounds` (CRS math)
- Calls `_read_tile_from_array` (numpy slicing + manual bilinear resize via integer indexing)
- Calls `_encode_jpeg` (rasterio MemoryFile round-trip for JPEG encoding)
- Creates directories and writes files

The numpy "resize" in `_read_tile_from_array` uses fancy integer indexing (`src_rows`, `src_cols`) rather than `scipy.ndimage.zoom` or `cv2.resize`. This is correct but slower than native C resize and also allocates a new array per tile.

**Fix A:** Parallelize the tile loop with `concurrent.futures.ThreadPoolExecutor`. The tiles are independent. Even with GIL contention, the `_encode_jpeg` call goes into GDAL's C layer (releases GIL), and file writes release GIL. A 4-worker pool here would allow ~3× throughput improvement on tile rendering with no algorithmic change.

**Fix B:** Replace `_encode_jpeg` (rasterio MemoryFile) with `libjpeg-turbo` via `turbojpeg` (PyTurbojpeg). A 256×256 JPEG encode via turbojpeg takes ~0.5ms vs ~2-5ms via rasterio's MemoryFile path (which allocates a full virtual dataset, writes headers, flushes). At 1,100 tiles this saves ~2-5s per quad.

**Fix C:** Replace the manual resize in `_read_tile_from_array` with `cv2.resize` or `PIL.Image.resize`, both of which call optimized SIMD C kernels. Current code does fancy-indexing nearest-neighbor which is correct but unoptimized.

**Estimated speedup (A alone):** 2-3× on tile rendering phase (from ~400s to ~150s for 1,100 tiles).  
**Estimated speedup (A+B+C):** 4-5× on tile rendering.  
**Memory reduction (A):** Neutral. (B) Slight — fewer MemoryFile allocations.  
**Implementation complexity:** Low (A), Low (B+C).

---

## Finding 3: `_rasterize_to_disk()` Writes to Filesystem, Then `_bulk_import_tiles` Re-reads — Extra I/O Round-Trip

**Location:** `rasterio_ops.py:342-387` and `rasterio_ops.py:493-545`

**Problem:** The current architecture writes ~1,100 JPEG files to `{stem}/.tiles_*/z/x/y.tile`, then reads them all back in `_bulk_import_tiles` to INSERT into SQLite. Each JPEG file is ~15-25 KB, so 1,100 files ≈ 15-25 MB of data written and re-read. On a 400 MB/s SATA SSD this is only ~0.1s of I/O, but there are 1,100 `open()` + `write()` + `close()` + `open()` + `read()` + `close()` syscall pairs plus 1,100 `mkdir -p` calls (for new directories).

The reason for the two-phase design (stated in the comment) is "no lock contention." But the merge stage is already serial — only one merger runs at a time (single thread via `loop.run_in_executor(None, _merge_tile, ...)`). Lock contention is not an issue.

**Fix:** Write tiles directly to SQLite in `_rasterize_to_disk` (renamed to `_rasterize_to_mbtiles`). Open a single SQLite connection with WAL mode before the loop, use an `executemany` with a 500-tile batch, commit every 500 tiles. This eliminates:
- 1,100 filesystem `write_bytes` calls
- 1,100 filesystem `read_bytes` calls in bulk import  
- 1,100 directory `mkdir` calls
- The entire cleanup pass (`shutil.rmtree`)

The only reason to keep the filesystem stage would be if parallelizing tile rendering with multiple concurrent merge workers — but that requires fixing Finding 7 first.

**Estimated speedup:** 5-15% (the I/O is fast on SSD but syscall overhead for 2,200 file ops adds up). More importantly, eliminates ~500 MB of temp directory writes that age through the page cache.

**Memory reduction:** Neutral on peak, but reduces page cache pressure during pipeline.

**Implementation complexity:** Low. The connection is already opened in `_bulk_import_tiles`; just pass it into the render loop.

---

## Finding 4: `merge_mbtiles()` — `fetchall()` Loads All Overlapping Tiles into RAM

**Location:** `acquire_imagery.py:639-646`

**Problem:**
```python
overlapping = dst.execute("""
    SELECT s.zoom_level, s.tile_column, s.tile_row, s.tile_data, d.tile_data
    FROM src.tiles s
    JOIN tiles d ON ...
    WHERE s.tile_data != d.tile_data
""").fetchall()
```

`fetchall()` materializes all overlapping tile BLOB data into Python RAM simultaneously. For boundary quads with many overlapping tiles, each JPEG tile is ~20 KB, and if there are 500 overlapping edge tiles this loads 10 MB of JPEG data — modest, but then the subsequent loop does 500 sequential JPEG decode → composite → re-encode → UPDATE cycles without any batching.

**The deeper problem:** The composite loop re-encodes every overlapping tile as JPEG. This means a JPEG → numpy → JPEG cycle with quality loss at each boundary merge pass. After N pipeline runs (resuming), boundary tiles are re-encoded N times.

**Fix A:** Replace `fetchall()` with `fetchmany(100)` or use a cursor iterator to stream overlapping tiles rather than loading all at once.

**Fix B:** Consider whether `INSERT OR IGNORE` + composite is the right merge strategy at all. Since each NAIP quad is processed separately, overlapping tiles only appear at quad boundaries (typically a thin strip). A spatial JOIN on tile coordinates is already efficient. The main win from batching is avoiding the 10 MB+ all-at-once load.

**Fix C:** Track a `_noaa_composite_quality_pass` counter and cap JPEG re-encodes to avoid quality degradation. Or use a lossless intermediate (PNG) for boundary tiles.

**Estimated speedup:** Small (5-10%) on the merge step itself. Fix C prevents long-term quality degradation.

**Memory reduction:** Modest (peak load during composite phase), but avoids pathological cases with thousands of overlapping tiles.

**Implementation complexity:** Very low (A is 1-line change), Low (B), Medium (C).

---

## Finding 5: `reproject_to_mercator()` — Thread Contention from `num_threads=os.cpu_count()`

**Location:** `rasterio_ops.py:244`

**Problem:**
```python
reproject(
    ...
    num_threads=os.cpu_count() or 2,  # = 4 on Pi 5
)
```

There are up to 4 reproject workers in the ThreadPoolExecutor (`REPROJECT_WORKERS = min(cpu_count, 6, total_tiles)` = 4 on Pi 5). Each calls `reproject()` with `num_threads=4`. This means up to **16 GDAL worker threads** competing for 4 cores simultaneously. GDAL's threading is at the warp kernel level — these aren't async, they're real OS threads that the scheduler has to context-switch between.

In practice this causes:
- Cache thrashing (each thread brings different data pages into L2/L3 cache)
- Lock contention inside GDAL's memory allocator
- CPU scheduler overhead from 16 competing threads on 4 cores

**Fix:** Set `num_threads=1` or `num_threads=2` inside `reproject_to_mercator` since the caller's ThreadPoolExecutor already provides parallelism at the file level. One thread per GDAL worker × 4 workers = full CPU utilization without oversubscription.

Alternatively: set `REPROJECT_WORKERS=2` and `num_threads=2` inside for the same total, which uses fewer threads and may reduce context-switching overhead.

**Estimated speedup:** 10-30% on reproject throughput (reduced context-switch overhead and better cache locality per core).

**Memory reduction:** Neutral on peak, but less allocator pressure.

**Implementation complexity:** Trivial (change one constant).

---

## Finding 6: `erode_nodata_edges()` and `inpaint_nodata_pixels()` — Serial Pass Over All Tiles

**Location:** `rasterio_ops.py:781-930`

**Problem:** Both functions fetch tile data serially and process one tile at a time:

`inpaint_nodata_pixels`:
```python
tiles = conn.execute("SELECT ... FROM tiles").fetchall()  # loads ALL tile BLOBs
for z, x, y, data in tiles:
    with rasterio.MemoryFile(data) as mf: ...
    _, nearest = distance_transform_edt(black, ...)
    conn.execute("UPDATE tiles ...")
```

`fetchall()` on the entire tiles table loads ALL JPEG blobs into RAM simultaneously. For a final dataset with 500,000 tiles at 20 KB each, that's 10 GB — which would immediately OOM the 4 GB container. Even at the 494-quad scale, at ~540 z17 tiles/quad, this is 267,000 tiles × 20 KB = 5.3 GB. This is an OOM bomb at scale.

`erode_nodata_edges` has the same pattern but only on boundary tiles, so its `fetchall` is bounded by the perimeter count — less catastrophic but still unbounded.

**Fix for `inpaint_nodata_pixels`:** Process in zoom-level batches. Within each zoom level, use a cursor with `fetchmany(1000)` to stream tiles rather than loading everything at once. The `distance_transform_edt` operates per-tile (256×256), so no cross-tile state is needed. This makes memory O(batch_size) instead of O(total_tiles).

**Parallelization of inpaint:** Since `distance_transform_edt` is independent per tile, it can be parallelized with a ThreadPoolExecutor over the cursor results. The DB update still needs to be serialized (or use `executemany`), but the expensive scipy call is fully parallel.

**Parallelization of erode:** The boundary identification is inherently iterative (each round checks the new boundary after removal), but the JPEG decode + edge analysis within each round can be parallelized since tiles are independent.

**Estimated speedup (streaming):** Eliminates OOM risk entirely. Makes the post-processing step viable at scale.  
**Estimated speedup (parallelism):** 3-4× on tile analysis (scipy `distance_transform_edt` on 256×256 arrays is ~2ms; 4 workers on 267,000 tiles saves ~2.5 hours vs serial).  
**Memory reduction:** Critical. Drops from O(N tiles) to O(batch_size). Required fix, not optional.  
**Implementation complexity:** Low-Medium.

---

## Finding 7: Merge Stage Cannot Overlap With Reproject — Serial by Design

**Location:** `acquire_imagery.py:2133-2181` (`_merger`) and `acquire_imagery.py:2153`

**Problem:**
```python
merge_ok = await loop.run_in_executor(None, _merge_tile, warped_path, idx)
```

The merger uses the **default executor** (not `reproject_pool`) with `maxsize=REPROJECT_WORKERS` on the merge queue. This means only one merge runs at a time — intentional for SQLite write safety. But this also means:

1. The entire `merge_to_mbtiles` call (including `rasterio_merge` + `_rasterize_to_disk`) is the "critical section" that all tiles must pass through sequentially
2. The reproject stage finishes quads faster than the merger can process them, so the reproject queue fills and blocks the downloader

At 4 reproject workers and a serial merger that's 10-15× slower, the effective parallelism is 1.0 regardless of the upstream pipeline width.

**Fix:** Separate the tile rendering from the SQLite write. `_rasterize_to_disk` writes to the filesystem (or to an in-memory buffer list) — this part CAN be parallelized because it doesn't touch SQLite. Then `_bulk_import_tiles` is the true serial section (SQLite write lock). With this split:

- Run `_rasterize_to_disk` in the reproject pool (CPU-bound, runs concurrently with downloads and other renders)
- Queue rendered tile lists for a serial `_bulk_import_tiles` worker
- The serial SQLite writer is now I/O-bound at ~400 MB/s SSD speed, not CPU-bound

This transforms the pipeline from effectively serial (limited by merge) to actually parallel (limited by reproject throughput or download throughput).

**Estimated speedup:** 3-5× end-to-end (allows 4 concurrent tile renders instead of 1).

**Memory reduction:** Slight increase (multiple tile lists in memory) but no rasterio_merge arrays since each render handles one file.

**Implementation complexity:** High. Requires restructuring the 3-stage pipeline into a 4-stage pipeline and managing the tile-list queue between render and import stages.

---

## Finding 8: GDAL_CACHEMAX=1024 MB — Misconfigured for This Workload

**Location:** `docker-compose.yml:216`, `acquire_imagery.py:755`

**Problem:** The pipeline container has a 4 GB memory limit. GDAL_CACHEMAX=1024 MB means GDAL's block cache alone can consume 25% of the container's limit. However, the NOAA pipeline does NOT use GDAL CLI tools — it uses rasterio's Python API, which has its OWN internal GDAL block cache separate from any environment variable inherited from docker-compose. The `_NOAA_GDAL_ENV` in `acquire_imagery.py:1657-1661` sets GDAL_CACHEMAX=256 but this dict is only used in `run_gdal_subprocess()` for CLI tools — it does NOT affect rasterio's internal GDAL instance.

There is also a contradiction: the `_NOAA_GDAL_ENV` dict (lines 1657-1661) is defined but not actually applied to the rasterio environment. Setting `GDAL_CACHEMAX` only affects GDAL CLI subprocesses; rasterio reads `GDAL_CACHEMAX` from the process environment at import time.

**Fix A:** Set `os.environ["GDAL_CACHEMAX"] = "256"` at the start of `run_noaa()` before any rasterio imports. This actually affects rasterio's cache.

**Fix B:** Call `gdal.SetCacheMax(256 * 1024 * 1024)` explicitly after import. This is the reliable way.

**Fix C:** For the tile-rendering workload, GDAL's block cache provides no benefit (we're reading from numpy arrays or single-file sequential scans). Setting it to 64 MB would free 960 MB for numpy arrays, which is the actual bottleneck.

**Estimated speedup:** Indirect. Freeing 960 MB from GDAL's cache reduces swap pressure, which is the stated constraint.

**Memory reduction:** Up to 960 MB freed for actual pipeline use.

**Implementation complexity:** Trivial (one line of code).

---

## Finding 9: `_encode_jpeg()` — rasterio MemoryFile Overhead Per Tile

**Location:** `rasterio_ops.py:89-101`

**Problem:**
```python
def _encode_jpeg(array: np.ndarray, quality: int = 85) -> bytes:
    with rasterio.MemoryFile() as memfile:
        with memfile.open(driver="JPEG", ...) as dst:
            dst.write(array[:3])
        return memfile.read()
```

Every tile encode:
1. Allocates a `rasterio.MemoryFile` (a vsimem:// buffer in GDAL's memory)
2. Opens it as a virtual GDAL dataset
3. Writes 3 bands of 256×256 uint8 (196 KB raw)
4. Closes the dataset (flushes JPEG headers + compressed data)
5. Reads the compressed bytes back out
6. Deallocates the MemoryFile

For 1,100 tiles this is 1,100 GDAL dataset open/close cycles. Each open/close involves GDAL driver registration checks and memory allocation/deallocation. The MemoryFile is a heap allocation tracked by GDAL's vsimem layer.

**Fix:** Replace with `io.BytesIO` + `PIL.Image` (which uses libjpeg) or `turbojpeg` (TurboJPEG direct API). Both are 3-5× faster for small JPEG encodes:
```python
from PIL import Image
import io

def _encode_jpeg(array: np.ndarray, quality: int = 85) -> bytes:
    img = Image.fromarray(np.moveaxis(array[:3], 0, -1))  # CHW → HWC
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, subsampling=0)
    return buf.getvalue()
```

PIL is available (`Pillow` is a transitive dependency of many rasterio wheels). `turbojpeg` requires an additional install but gives ~2-5ms vs ~10-20ms per tile encode.

**Estimated speedup:** 15-25% on the tile render phase. At 1,100 tiles and ~15ms/encode, switching to PIL saves ~8-12s per quad.

**Memory reduction:** Slight (no GDAL vsimem allocation per tile).

**Implementation complexity:** Low (5-line change).

---

## Finding 10: `_read_tile_from_array()` — No Proper Bilinear Resampling

**Location:** `rasterio_ops.py:568-634`

**Problem:** The resize step uses integer-indexed nearest-neighbor:
```python
src_rows = (np.arange(dst_h) * (window_data.shape[1] / dst_h)).astype(np.intp)
src_cols = (np.arange(dst_w) * (window_data.shape[2] / dst_w)).astype(np.intp)
resized = window_data[:, src_rows, :][:, :, src_cols]
```

This is nearest-neighbor resampling. For downscaling from ~200 source pixels to 256 output pixels (z17 rendering at 1 m/pixel NAIP) this is adequate. But for overview tiles (z13-z16, where 4,096 source pixels map to 256 output pixels), nearest-neighbor produces aliased imagery — jagged edges on roads, rivers, and structures.

The Lanczos reproject step already produces high-quality EPSG:3857 GeoTIFFs, but the subsequent tile extraction degrades them with NN resampling.

**Fix:** Replace with `cv2.resize(..., interpolation=cv2.INTER_AREA)` (area averaging, best for downscaling) or `scipy.ndimage.zoom`. For the common case where source and dest are close in size (z17 tiles), even INTER_LINEAR is fine. `cv2` is optional but `scipy` is already a dependency.

This does not affect throughput significantly but fixes output quality for overview zoom levels.

**Estimated speedup:** Neutral on speed (scipy.ndimage.zoom is similar speed to the current numpy indexing for small arrays). May be slightly slower. Tradeoff is quality.

**Memory reduction:** Neutral.

**Implementation complexity:** Low.

---

## Finding 11: Downloader Sequentially Awaits Oldest Task First

**Location:** `acquire_imagery.py:2056-2062`

**Problem:**
```python
if len(download_tasks) >= DOWNLOAD_CONCURRENCY:
    oldest_idx, oldest_fname, oldest_task = download_tasks.pop(0)
    dl_fname, dl_path = await oldest_task  # waits for OLDEST, not FASTEST
```

The downloader issues `DOWNLOAD_CONCURRENCY=8` concurrent downloads but waits for them in FIFO order. If tile 1 is slow (e.g. 600 MB at 2 MB/s = 300s) and tiles 2-8 complete in 60s, tiles 2-8 sit in `download_tasks` idle, not feeding the reproject queue, while we wait for tile 1.

The standard pattern is `asyncio.as_completed()` or `asyncio.wait(..., return_when=FIRST_COMPLETED)`.

**Fix:** Use `asyncio.as_completed(tasks)` to feed the reproject queue from whichever download finishes first.

**Estimated speedup:** Significant when tile sizes vary widely (which they do — coastal quads differ from inland). In the worst case (one 600 MB tile stalling 7 fast ones), this saves 5-7 × the difference in download times. At 3 MB/s and 50-600 MB range, this can save 10-30 min on a 494-tile run.

**Memory reduction:** Neutral.

**Implementation complexity:** Low-Medium (requires tracking idx→fname mapping separately since as_completed loses ordering).

---

## Finding 12: `convert_batch_to_mbtiles` → `merge_mbtiles` — Double Temp File Write

**Location:** `acquire_imagery.py:826-850`

**Problem:** For each warped NAIP quad, the pipeline:
1. Writes rendered tiles to `.tiles_*/z/x/y.tile` filesystem (1,100 files)
2. Bulk-imports those into a temp `{batch_label}.mbtiles` file
3. ATTACHes the temp MBTiles to the main output and INSERTs tiles
4. Deletes the temp MBTiles

Steps 2 and 3 write the same JPEG data twice to SQLite: once to the temp file, once to the main file. For 1,100 tiles × 20 KB = 22 MB per quad, this is 22 MB × 2 × 494 quads = 21 GB of unnecessary SSD writes over a full run (not I/O-bound at 400 MB/s, but it adds up and ages out page cache).

**Fix:** Write directly to the output MBTiles in `_bulk_import_tiles` using `INSERT OR IGNORE` (non-overlapping tiles) plus a separate compositing pass. Eliminate the temp MBTiles entirely. The `merge_mbtiles` ATTACH pattern exists because it was originally assumed the bulk import would be concurrent, but it's serial.

**Estimated speedup:** 5-10% end-to-end (eliminates half the SQLite write volume).

**Memory reduction:** Neutral on peak.

**Implementation complexity:** Low-Medium (requires moving compositing logic into the render phase).

---

## Priority Matrix

| # | Finding | Speedup Estimate | Memory Savings | Complexity | Fix First? |
|---|---------|-----------------|----------------|------------|-----------|
| 1 | Stream tiles from GeoTIFF instead of rasterio_merge full-load | 2-3× merge | 1.5 GB | Low-Med | **YES** |
| 2A | Parallelize `_rasterize_to_disk` tile loop | 2-3× render | Neutral | Low | **YES** |
| 5 | Fix `num_threads` oversubscription in reproject | 10-30% reproject | Neutral | Trivial | **YES** |
| 8 | Fix GDAL_CACHEMAX (doesn't affect rasterio) | Indirect (swap) | 960 MB | Trivial | **YES** |
| 6 | Stream `inpaint`/`erode` with fetchmany (OOM fix) | Eliminates OOM | Critical | Low-Med | **YES (safety)** |
| 9 | Replace `_encode_jpeg` MemoryFile with PIL | 15-25% render | Slight | Low | Yes |
| 11 | Use `as_completed` in downloader | 10-30 min on long runs | Neutral | Low-Med | Yes |
| 7 | 4-stage pipeline (render parallel, import serial) | 3-5× end-to-end | Slight increase | High | After 1+2 |
| 3 | Write tiles directly to SQLite (skip filesystem) | 5-15% merge | Neutral | Low | After 7 |
| 4 | Stream `merge_mbtiles` overlapping tiles | 5-10% merge | Modest | Very Low | Yes |
| 12 | Eliminate temp MBTiles double-write | 5-10% overall | Neutral | Low-Med | After 7 |
| 10 | Fix tile resampling quality (INTER_AREA) | Quality only | Neutral | Low | Later |

---

## Recommended Fix Order

### Phase 1 — Quick wins, no architecture change (1 day)
1. `os.environ["GDAL_CACHEMAX"] = "64"` at top of `run_noaa()` — frees 960 MB
2. Change `reproject()` `num_threads` from `os.cpu_count()` to `max(1, os.cpu_count() // REPROJECT_WORKERS)` — eliminates oversubscription
3. Fix `inpaint_nodata_pixels` to use `fetchmany(1000)` instead of `fetchall()` — eliminates OOM risk
4. Replace `_encode_jpeg` with PIL — 15-25% faster tile rendering

### Phase 2 — Streaming single-file merge (1-2 days)
5. In `merge_to_mbtiles`, detect `len(input_paths) == 1` and bypass `rasterio_merge`. Instead open the single file and stream tile windows. This eliminates the 1.5 GB array allocation and makes merge memory O(1). **This is the single highest-impact change.**

### Phase 3 — Parallelize tile rendering (1-2 days)
6. Add a `ThreadPoolExecutor(max_workers=4)` inside `_rasterize_to_disk` for the inner tile loop. Tiles are fully independent. Requires thread-safe directory creation (`exist_ok=True` already there) and collecting results.

### Phase 4 — Pipeline restructure (2-3 days)
7. Split `_merge_tile` into `_render_tile` (runs in reproject pool) and `_import_tile` (serial SQLite writer). This allows concurrent rendering for multiple warped quads while maintaining SQLite write safety.

---

## Expected Outcome

Phases 1-3 alone should move throughput from **0.7 tiles/min to ~2.5-3.5 tiles/min** (3.5-5×), bringing a 494-tile run from ~700 minutes to ~140-200 minutes. Phase 4 could further improve to 5-8 tiles/min if reproject is the bottleneck.

The merge stage will go from being the bottleneck to being fast enough that reprojection (or download) limits throughput — which is the correct steady-state for this architecture.
