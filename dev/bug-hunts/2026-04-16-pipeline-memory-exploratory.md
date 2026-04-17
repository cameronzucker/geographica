# Bug Hunt Report

## Scope
Focused depth-first analysis of the NOAA imagery pipeline's memory management, resource cleanup, and concurrency correctness.

**Files deeply explored:**
- `scripts/acquire_imagery.py` — `run_noaa()` (lines 1742-2280), `merge_mbtiles()` (610-677), `convert_batch_to_mbtiles()` (812-851)
- `scripts/rasterio_ops.py` — `merge_to_mbtiles()` (300-398), `build_overviews()` (646-778), `inpaint_nodata_pixels()` (781-842), `erode_nodata_edges()` (845-929), `reproject_to_mercator()` (194-255), `_rasterize_to_disk()` (426-490)
- `services/search/main.py` — pipeline start/cancel/status endpoints (1150-1580)

**Why these files:** The 3-stage pipeline (download, reproject, merge) is the highest-risk orchestration code. It coordinates asyncio, threading.Lock, ThreadPoolExecutor, and serial SQLite writes. The post-processing functions (inpaint, erode, overviews) operate on the full output database under a 2 GB memory limit.

## Bugs

### 1. inpaint_nodata_pixels loads ALL tile BLOBs into memory at once
**Location:** `scripts/rasterio_ops.py:804-806`
**Severity:** significant
**Evidence:** The function does:
```python
tiles = conn.execute(
    "SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles"
).fetchall()
```
This fetches every tile's JPEG blob into a Python list in one shot. After `build_overviews` runs, the MBTiles file contains tiles at zoom levels 0 through ~14. For a moderately large area (e.g., Maricopa County), this could mean 5,000-50,000 tiles at ~30 KB each = 150 MB - 1.5 GB of JPEG data held simultaneously in Python memory. The pipeline container has a 2 GB `mem_limit`.
**Impact:** OOM kill during the post-processing phase after all tiles have been successfully merged. The pipeline would report success through the merge phase but die during inpainting, leaving the output without nodata cleanup. Worse: the pipeline completed the expensive work (download + reproject + merge + overviews) but the OOM kills it before it can register with TileServer or report completion.

### 2. build_overviews leaks SQLite connection on exception
**Location:** `scripts/rasterio_ops.py:663-778`
**Severity:** significant
**Evidence:** The connection is opened at line 664:
```python
conn = sqlite3.connect(str(mbtiles_path))
```
The `try/except` at lines 663/776 catches exceptions and returns False, but never closes `conn`. The `conn.close()` at line 771 is only reached on the success path. If any exception occurs during overview building (e.g., corrupt JPEG decode, disk full during INSERT), the connection is leaked.
**Impact:** Leaked SQLite connections hold WAL file locks. On the Pi 5 with limited file descriptors, this prevents other operations (TileServer, checkpoint writes) from accessing the MBTiles file until GC eventually collects the connection. More critically, a leaked WAL-mode connection can leave a `-wal` file that grows unbounded, contributing to the very memory pressure that caused the original failure.

### 3. merge_to_mbtiles leaks temporary tile directory on exception
**Location:** `scripts/rasterio_ops.py:343-397`
**Severity:** significant
**Evidence:** The tile directory is created at line 343-344:
```python
tile_dir = output_path.parent / f".tiles_{output_path.stem}"
tile_dir.mkdir(parents=True, exist_ok=True)
```
The cleanup at line 387 (`_cleanup_tile_dir(tile_dir)`) is inside the inner `try` block. If `_rasterize_to_disk` or `_bulk_import_tiles` raises an exception, execution jumps to the `finally` at line 389 (closing datasets), then to the outer `except` at line 395. The `_cleanup_tile_dir` call is never reached.
**Impact:** Each failed merge leaves a `.tiles_noaa_tile_N` directory containing potentially thousands of tile files on disk. In the NOAA pipeline, this is called once per NAIP quad via `convert_batch_to_mbtiles`. If disk errors cause repeated failures, temp directories accumulate. At ~50-150 MB per failed quad, this can exhaust the staging area.

### 4. TileServer layer permanently unregistered after skip-to-postprocess re-run
**Location:** `scripts/acquire_imagery.py:1773,2240`
**Severity:** significant
**Evidence:** At line 1773, the pipeline unconditionally unregisters `imagery_noaa` from TileServer:
```python
if remove_mbtiles_from_config(ts_config, "imagery_noaa"):
    log.info("Temporarily unregistered imagery_noaa from TileServer")
```
At line 2240, re-registration requires `tiles_done > 0`:
```python
if output.exists() and tiles_done > 0 and ts_config_path:
```
When the pipeline is re-run on an already-complete dataset (`skip_to_postprocess=True`), `tiles_done` remains 0 because Phase 4 is skipped entirely. The re-registration condition fails, and the TileServer config permanently loses the `imagery_noaa` source.
**Impact:** Re-running the pipeline (e.g., to rebuild overviews or re-apply erosion/inpainting) removes the imagery layer from TileServer. The user sees their imagery disappear from the map after what appears to be a successful pipeline run. Recovery requires manually editing the TileServer config or running a fresh pipeline with at least one new tile.

### 5. erode_nodata_edges and inpaint_nodata_pixels leak SQLite connections on unhandled exceptions
**Location:** `scripts/rasterio_ops.py:802,861`
**Severity:** minor
**Evidence:** Both functions open SQLite connections without `try/finally`:
```python
conn = sqlite3.connect(str(mbtiles_path))  # line 802, 861
# ... processing ...
conn.close()  # line 839, 929 — only reached on success path
```
In `inpaint_nodata_pixels`, the per-tile processing loop (lines 809-831) has no try/except. If `distance_transform_edt` or numpy indexing raises an unexpected error (e.g., a corrupt JPEG producing an array with wrong dimensions), the exception propagates and `conn.close()` is never called.

In `erode_nodata_edges`, individual tile errors are caught (line 907), but the outer loop and metadata update code (lines 913-926) have no protection.
**Impact:** Same as bug #2 — leaked WAL connections and file handle exhaustion. Less likely to trigger than #2 because the per-tile code paths are simpler, but still reachable via corrupt tile data.

### 6. Partially-opened rasterio datasets leak on list comprehension failure in merge_to_mbtiles
**Location:** `scripts/rasterio_ops.py:322`
**Severity:** minor
**Evidence:** The datasets are opened in a list comprehension:
```python
datasets = [rasterio.open(str(p)) for p in input_paths]
```
If the Nth `rasterio.open()` raises (e.g., corrupt GeoTIFF, permission error), datasets 0 through N-1 are opened but never closed. They are not assigned to any variable that the `finally` block at line 389 can close, because the list comprehension failed and `datasets` was never bound.
**Impact:** In the NOAA pipeline, `merge_to_mbtiles` is called with a single file, so this is effectively unreachable. In other callers that pass multiple files, this would leak file handles. Low practical impact for the current codebase.

## Design Concerns

### Memory-unbounded post-processing against full output database
Both `inpaint_nodata_pixels` and `erode_nodata_edges` operate on the final MBTiles output after all tiles (including overviews) are present. The output database grows proportionally to the number of NAIP quads processed. The post-processing functions load tile data into memory — `inpaint` loads ALL tiles via `fetchall()`, while `erode` loads boundary tiles per zoom level. There is no mechanism to skip post-processing if the output is too large for the container's memory limit. A pagination/cursor-based approach for `inpaint` would bound memory usage regardless of output size.

### ThreadPoolExecutor shutdown(wait=False) leaves orphaned threads holding large allocations
At line 2190, `reproject_pool.shutdown(wait=False)` is called in the `finally` of `asyncio.gather`. If `gather` propagates an exception (e.g., from a failed merger causing CancelledError), reproject threads may still be mid-flight holding 1-2 GB numpy arrays from `rasterio.warp.reproject`. These threads run to completion even after shutdown, meaning peak memory is unpredictable during abnormal termination. Using `shutdown(wait=True)` would be safer but could block indefinitely; using `shutdown(wait=True, cancel_futures=True)` (Python 3.9+) would be the best option.

### No cancel_check in _bulk_import_tiles
The `_bulk_import_tiles` function (line 493-545) walks the entire tile directory and inserts every tile into SQLite without checking `cancel_check`. For a large tile set, this could take significant time during which cancellation is unresponsive. The function is called from `merge_to_mbtiles`, which has cancel checks at other stages but not during bulk import.
