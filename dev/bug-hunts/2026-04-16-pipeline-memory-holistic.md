# Bug Hunt Report

## Scope
Analyzed the NOAA imagery pipeline end-to-end, focusing on memory leaks, resource cleanup, concurrency correctness, SQLite connection management, and data integrity.

**Files read in full:**
- `scripts/acquire_imagery.py` (2358 lines) — `run_noaa()`, `merge_mbtiles()`, `convert_batch_to_mbtiles()`, full 3-stage pipeline
- `scripts/rasterio_ops.py` (930 lines) — `merge_to_mbtiles()`, `build_overviews()`, `inpaint_nodata_pixels()`, `erode_nodata_edges()`, `reproject_to_mercator()`, `_rasterize_to_disk()`, `_read_tile_from_array()`
- `scripts/pipeline_progress.py` (110 lines)
- `scripts/pipeline_security.py` (125 lines)
- `services/search/main.py` lines 1150-1580 (pipeline start/cancel/status endpoints)

**Approach:** Read everything, built a mental model of the 3-stage concurrent pipeline (download → reproject → merge), then traced every resource allocation (SQLite connections, rasterio datasets, numpy arrays, file handles, thread pools) through every code path including cancellation and exception paths.

## Bugs

### 1. `build_overviews` leaks SQLite connection on exception
**Location:** `rasterio_ops.py:663-778`
**Severity:** significant
**Evidence:** The connection is opened at line 664 (`conn = sqlite3.connect(...)`) inside a `try` block. On the happy path, `conn.close()` is called at line 771. On cancellation, `conn.close()` is called at line 687. But the `except Exception` handler at line 776 catches errors and returns `False` *without ever closing `conn`*. There is no `finally` block.
```python
try:
    conn = sqlite3.connect(str(mbtiles_path))   # line 664
    conn.execute("PRAGMA journal_mode=WAL")
    ...
    conn.close()                                  # line 771 (happy path only)
    return True
except Exception as exc:
    log.error("build_overviews failed: %s", exc)
    return False                                  # conn never closed!
```
**Impact:** If `build_overviews` fails (e.g., corrupt tile data, disk full, JPEG decode error), the SQLite connection is leaked. On Pi 5 with 2 GB container memory limit, this holds WAL journal locks and file descriptors open. The WAL file cannot be checkpointed by subsequent operations. Over multiple retries or pipeline restarts, leaked connections accumulate. This is particularly problematic because `build_overviews` reads *every tile* from the database — the connection will hold a large page cache.

### 2. `inpaint_nodata_pixels` loads entire tile database into memory via `fetchall()`
**Location:** `rasterio_ops.py:804-806`
**Severity:** significant
**Evidence:** Line 804-806:
```python
tiles = conn.execute(
    "SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles"
).fetchall()
```
This loads every tile's BLOB data into Python memory at once. For a NOAA pipeline with hundreds of tiles at multiple zoom levels (including overviews just built), each JPEG tile is ~20-60 KB. With 5000+ tiles, this is 100-300 MB of JPEG blobs held simultaneously in a Python list, on top of the decoded numpy arrays being processed in the loop. In a 2 GB container, this can push past the memory limit.
**Impact:** OOM kill during post-processing phase. The pipeline processes all tiles successfully through the 3-stage pipeline, builds overviews, then crashes during inpaint — losing the post-processing work. The tiles are still usable but have visible black seams.

### 3. `erode_nodata_edges` also loads tile BLOBs for all boundary tiles per iteration
**Location:** `rasterio_ops.py:882-887`
**Severity:** minor
**Evidence:** Line 882-887 fetches `tile_data` BLOBs for all boundary tiles at each zoom level in each erosion iteration:
```python
boundary = conn.execute(
    "SELECT tile_column, tile_row, tile_data FROM tiles "
    "WHERE zoom_level=? AND ("
    "  tile_column=? OR tile_column=? OR tile_row=? OR tile_row=?)",
    (z, min_col, max_col, min_row, max_row),
).fetchall()
```
While less severe than inpaint (only boundary tiles, not all tiles), this still loads all boundary tile BLOBs into memory. For large datasets, boundaries can include hundreds of tiles.
**Impact:** Contributes to peak memory during post-processing, compounding with any residual memory from prior stages.

### 4. `merge_mbtiles` compositing loads all overlapping tile BLOBs into memory
**Location:** `acquire_imagery.py:639-646`
**Severity:** minor (per-call), but **significant** cumulatively
**Evidence:** Line 639-646:
```python
overlapping = dst.execute("""
    SELECT s.zoom_level, s.tile_column, s.tile_row, s.tile_data, d.tile_data
    FROM src.tiles s
    JOIN tiles d ON ...
    WHERE s.tile_data != d.tile_data
""").fetchall()
```
This fetches *two* BLOB columns (source and destination tile data) for every overlapping tile into a Python list. While each individual call processes one NAIP quad's worth of overlap, the `s.tile_data != d.tile_data` comparison forces SQLite to read and compare every byte of every overlapping tile. SQLite BLOB comparison is O(n) in BLOB size, creating significant I/O pressure.
**Impact:** The BLOB comparison in the WHERE clause means SQLite must fully materialize both BLOBs to compare them. For tiles that happen to be identical (e.g., a quad was re-processed), this is wasted work. More importantly, `fetchall()` holds all matched pairs in memory simultaneously — for quads with many overlapping edge tiles, this is dozens of JPEG pairs (~2-4 MB total per call, but called once per NAIP quad, ~682 times for Phoenix).

### 5. `_reprojector` does not catch exceptions from `f_future.result()` — unhandled exception kills pipeline
**Location:** `acquire_imagery.py:2122`
**Severity:** significant
**Evidence:** Line 2120-2126:
```python
for f_idx, f_fname, f_future in pending_futures:
    if f_future.done():
        warped = f_future.result()  # Can raise!
        with counter_lock:
            tiles_reprojected += 1
        _write_progress()
        await merge_queue.put((f_idx, f_fname, warped))
```
`f_future.result()` re-raises any exception from `_reproject_tile`. While `_reproject_tile` has a top-level try/except that returns `None` on error, there are edge cases where it could still raise: (a) `raw_path.stat()` at line 1983 raises if the file was deleted between download and reproject (race with cancellation cleanup); (b) the `import gc` could theoretically fail in a memory-pressure scenario. If `f_future.result()` raises, the exception propagates out of `_reprojector()`, which is one of three coroutines in `asyncio.gather()`. This kills the gather, but the `_downloader` and `_merger` coroutines are also cancelled. The `_merger` sentinel (`None` on merge_queue) is never sent, so any already-reprojected tiles in the merge queue are lost.

More concretely: `_reproject_tile` at line 1983 does `raw_size = raw_path.stat().st_size / (1024 * 1024)` *before* the try/except block:
```python
def _reproject_tile(raw_path, tile_fname):
    import gc
    warped_path = staging / f"warped_{tile_fname}"
    t0 = time.monotonic()
    raw_size = raw_path.stat().st_size / (1024 * 1024)  # OUTSIDE try/except
    log.debug(...)
    try:
        success = rio_reproject_to_mercator(...)
```
If `raw_path` doesn't exist (e.g., disk full prevented download, or the file was cleaned up), `raw_path.stat()` raises `FileNotFoundError`, which escapes `_reproject_tile` entirely, then escapes `f_future.result()`, crashing the `_reprojector`.

**Impact:** A single missing or deleted file kills the entire pipeline. All in-flight work is lost. The pipeline reports "cancelled" or crashes silently.

### 6. Cancellation in `_downloader` skips sentinel, starving `_reprojector` and `_merger`
**Location:** `acquire_imagery.py:2064-2067`
**Severity:** minor (mitigated by gather cancellation, but still a correctness issue)
**Evidence:** Lines 2064-2067:
```python
for idx, fname, task in download_tasks:
    if _cancel_requested:
        task.cancel()
        continue    # skips putting result on reproject_queue
```
When cancellation is requested during the drain loop, remaining tasks are cancelled via `task.cancel()`, but no result is ever put on `reproject_queue` for those tasks. The `_reprojector` will never see these items. Then at line 2077, the sentinel `None` is sent, so `_reprojector` exits. But now `tiles_downloaded` counter is stale — it doesn't account for the cancelled tasks. The progress counter shows fewer downloaded than actual.

However, more importantly: `task.cancel()` on already-running asyncio tasks may raise `CancelledError` when awaited. Since these tasks are `ensure_future`'d and not awaited after cancel, the `CancelledError` becomes an "unhandled task exception" warning. This pollutes logs but doesn't crash.

**Impact:** Minor: incorrect progress counter during cancellation, log noise from unhandled CancelledError.

### 7. `_merge_tile` WAL checkpoint races with `_merger` checkpoint write
**Location:** `acquire_imagery.py:2036-2041` and `acquire_imagery.py:2166-2174`
**Severity:** minor
**Evidence:** `_merge_tile` runs in `loop.run_in_executor(None, ...)`. At its end (line 2036-2041), it opens a new SQLite connection and runs `PRAGMA wal_checkpoint(TRUNCATE)`. This returns, executor completes, control returns to `_merger`. Then `_merger` at line 2166 opens *another* SQLite connection and writes to `_noaa_checkpoint` table. These are serialized (the await ensures it), so there's no race on the SQLite file itself.

However, the `PRAGMA wal_checkpoint(TRUNCATE)` at line 2039 forces a full WAL write-back. If the WAL was already large from the `merge_mbtiles` operation, this checkpoint operation itself performs significant I/O. Immediately after, the checkpoint table write at line 2166 creates *new* WAL entries, undoing the truncation. This checkpoint-then-write pattern means the WAL is truncated and immediately re-grown on every single tile — unnecessary I/O churn.

**Impact:** Wasted I/O on every tile merge. Each WAL truncate + immediate re-write costs ~50-100ms of unnecessary SSD writes per tile. Over 682 tiles, that's 34-68 seconds of pure overhead. Not a correctness bug, but a performance drain and SSD wear concern on the Pi's SATA SSD.

## Design Concerns

### Memory pressure during post-processing is the primary remaining OOM vector

The 3-stage pipeline has been well-hardened with gc.collect() + malloc_trim after each stage. But post-processing (overviews → erode → inpaint) runs sequentially with no memory reclamation between stages. `build_overviews` reads every tile at every zoom level (individual queries, not fetchall, so OK). Then `erode_nodata_edges` loads boundary tile BLOBs. Then `inpaint_nodata_pixels` loads ALL tile BLOBs via `fetchall()`. If any of these stages has residual memory from prior stages (e.g., unreleased numpy arrays from the merge loop), the cumulative pressure could exceed the 2 GB container limit.

**Recommendation:** `inpaint_nodata_pixels` should iterate with a cursor instead of `fetchall()`, processing and committing in batches. Add `gc.collect()` + `malloc_trim()` between post-processing stages.

### SQLite connection handling inconsistency across the codebase

Some functions use `with sqlite3.connect(...) as conn:` (context manager, auto-commit on exit), while others use manual `conn = sqlite3.connect(...)` with explicit `conn.close()` in a `finally` (sometimes) or not (see bug #1). The `with` pattern is safer but only provides auto-commit, not auto-close — `conn` stays open until GC. The codebase should standardize on a pattern that guarantees close, like:
```python
conn = sqlite3.connect(...)
try:
    ...
finally:
    conn.close()
```
or a dedicated context manager.

### `reproject_pool.shutdown(wait=False)` leaves threads running after pipeline exit

At line 2190, `reproject_pool.shutdown(wait=False)` is called in the `finally` block. If `asyncio.gather` was cancelled (e.g., by an exception in one of the three coroutines — see bug #5), reproject threads may still be running, writing to the staging directory. These orphaned threads hold GeoTIFF files open and consume memory. Since this runs in a Docker container with `mem_limit="2g"`, the orphaned threads compete with whatever cleanup runs next. Using `wait=True` with a timeout, or `cancel_futures=True` (Python 3.9+), would be safer.

### `_handle_sigterm` modifies `_cancel_requested` from signal handler — not thread-safe with counter_lock

The signal handler at line 168 sets `_cancel_requested = True`. This global is read (without the lock) by `_download_tile`, `_reproject_tile`, `_merge_tile`, and `_merger`. The variable is written from the signal handler thread context and read from multiple threads. In CPython, this is safe due to the GIL for simple boolean assignment, but it's a fragile pattern that would break under a free-threaded Python runtime. Not a bug today, but a design fragility.
