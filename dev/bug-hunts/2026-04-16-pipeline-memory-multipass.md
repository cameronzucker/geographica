# Bug Hunt Report — NOAA Pipeline Memory & Correctness

## Scope
Files analyzed:
- `scripts/acquire_imagery.py` — `run_noaa()` (lines 1742-2280), `merge_mbtiles()` (610-677), `convert_batch_to_mbtiles()` (812-851)
- `scripts/rasterio_ops.py` — `merge_to_mbtiles()` (300-397), `build_overviews()` (646-778), `inpaint_nodata_pixels()` (781-842), `erode_nodata_edges()` (845-930), `_rasterize_to_disk()`, `_read_tile_from_array()`, `_bulk_import_tiles()`
- `scripts/pipeline_progress.py` — atomic progress writer
- `scripts/pipeline_security.py` — file validation
- `services/search/main.py` — pipeline start/cancel/status endpoints (1150-1580)

All five passes performed: contract violations, cross-sibling patterns, failure modes, concurrency, error propagation.

## Bugs

### B1: `inpaint_nodata_pixels` loads ALL tile data into memory via fetchall
**Location:** `scripts/rasterio_ops.py:804-806`
**Severity:** critical
**Evidence:** The function calls `conn.execute("SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles").fetchall()` which loads every tile's BLOB data into a Python list. For a typical NOAA output with thousands of tiles at ~20 KB each (JPEG), this is 200+ MB of tile data held in a Python list simultaneously, on top of the per-tile numpy arrays and scipy distance transforms. In a 2 GB container, this competes directly with the overview-building and erosion steps that run immediately before.
**Impact:** OOM kill during post-processing phase. The pipeline completes the expensive download/reproject/merge work successfully, then crashes during the cheap cleanup step, wasting hours of processing. On a 2 GB mem_limit container processing a full state (10,000+ tiles), fetchall loads ~200-400 MB of compressed JPEG blobs into RAM before any processing begins.
**Found in:** Pass 1 — Contract Violations (function says it processes tiles but front-loads all data)

### B2: `build_overviews` leaks SQLite connection on exception
**Location:** `scripts/rasterio_ops.py:663-778`
**Severity:** significant
**Evidence:** The connection is created at line 664 (`conn = sqlite3.connect(...)`) inside a bare `try:` block. The matching `except` at line 776 logs the error and returns `False`, but never calls `conn.close()`. The `conn.close()` at line 771 is inside the happy path only. If any exception occurs between lines 664 and 771 (e.g., during JPEG decode at line 735, or the `INSERT OR REPLACE` at line 755-757 on a full disk), the connection leaks.
**Impact:** Leaked connection holds a WAL lock on the MBTiles file, potentially blocking subsequent operations. In the NOAA pipeline, `build_overviews` is called via `_run_gdaladdo_with_metadata_fixup`, and if it leaks the connection, the subsequent metadata fixup at lines 797-809 could encounter SQLITE_BUSY. On the Pi with limited file descriptors, leaked connections accumulate across retries.
**Found in:** Pass 3 — Failure Mode Reasoning

### B3: `erode_nodata_edges` leaks SQLite connection on exception
**Location:** `scripts/rasterio_ops.py:861-930`
**Severity:** significant
**Evidence:** `conn = sqlite3.connect(str(mbtiles_path))` at line 861 is not in a try/finally block. The `conn.close()` at line 929 is at the function's end, outside any exception handler. If rasterio.MemoryFile throws (corrupted JPEG data), `np.any()` throws (unexpected dtype), or any other exception propagates from the loop body past the inner `except Exception: pass` at lines 907-908 (e.g., from the `conn.execute DELETE` or `conn.commit` at lines 901-910), the connection leaks.
**Impact:** Same as B2 — leaked WAL lock. The `erode_nodata_edges` function is called right after `build_overviews` in the post-processing chain. A leaked connection from either function can cause SQLITE_BUSY for the next function.
**Found in:** Pass 3 — Failure Mode Reasoning

### B4: TileServer not re-registered when `skip_to_postprocess` is True
**Location:** `scripts/acquire_imagery.py:2240`
**Severity:** significant
**Evidence:** At line 1773, `run_noaa` unconditionally unregisters `imagery_noaa` from TileServer config. At line 2240, the re-registration condition is `output.exists() and tiles_done > 0 and ts_config_path`. When `skip_to_postprocess` is True (all quads already processed, re-run for post-processing only), `tiles_done` remains 0 (initialized at line 1883, never incremented because the 3-stage pipeline is skipped). The condition `tiles_done > 0` is False, so TileServer is never re-registered.
**Impact:** After a re-run of the NOAA pipeline (e.g., to reapply overviews/erosion/inpaint after a parameter tweak), the imagery layer silently disappears from TileServer. The user sees no error — the pipeline reports "complete" — but the map loses its imagery layer. Requires manual TileServer config editing to fix.
**Found in:** Pass 1 — Contract Violations

### B5: `merge_to_mbtiles` tile directory not cleaned up when `_rasterize_to_disk` raises
**Location:** `scripts/rasterio_ops.py:344-397`
**Severity:** minor
**Evidence:** `tile_dir` is created at line 344. If `_rasterize_to_disk` (line 348) or `_bulk_import_tiles` (line 377) raises an exception, execution jumps to the `finally` block at line 389 (which only closes rasterio datasets) and then to the `except` at line 395 (which logs and returns False). Neither path calls `_cleanup_tile_dir(tile_dir)`. The cancel paths at lines 358-360 DO clean up, but exception paths don't.
**Impact:** Orphaned tile directories (named `.tiles_{stem}`) accumulate in the data directory after failed merge operations. Each can contain thousands of small files. On the Pi's SSD, this wastes inodes and disk space over multiple retries.
**Found in:** Pass 3 — Failure Mode Reasoning

### B6: `_reprojector` silently drops cancelled tiles without notifying merger
**Location:** `scripts/acquire_imagery.py:2102-2106`
**Severity:** minor
**Evidence:** When `_cancel_requested` is True and `raw_path` is not None (a successfully downloaded tile), the reprojector unlinks the raw file at line 2104 but does NOT push anything to `merge_queue`. It only pushes `(idx, tile_fname, None)` to merge_queue when `raw_path is None` (download failure). For cancelled-but-downloaded tiles, no message reaches the merger. This means `tiles_done + tiles_failed` will not equal `total_tiles` — the cancelled tiles are silently lost from the accounting. However, the merger still terminates because the `None` sentinel at line 2131 is always sent.
**Impact:** The final progress report undercounts total processed tiles. On cancellation, `tiles_done + tiles_failed < total_tiles`, making it impossible to accurately report how many tiles were cancelled vs failed vs completed. Minor because cancellation is an exceptional path, but confusing for debugging.
**Found in:** Pass 4 — Concurrency Reasoning

### B7: `_child_pid` global is not thread-safe
**Location:** `scripts/acquire_imagery.py:165, 179, 749-771`
**Severity:** minor
**Evidence:** `_child_pid` is a module-level global that is read from a signal handler (`_handle_sigterm` at line 179) and written from `run_gdal_subprocess` (lines 763, 769, 771). Signal handlers can fire at any point between any two Python bytecodes. The write at line 763 (`_child_pid = proc.pid`) and reads at line 179 (`if _child_pid`) are not atomic with respect to signals. However, in the NOAA pipeline, `run_gdal_subprocess` is only called from `_run_gdaladdo_with_metadata_fixup` during overview generation (line 1635-1639), which runs in the main thread after the async session closes. Since Python's GIL ensures that simple variable assignments are atomic at the bytecode level, and SIGTERM delivery happens between bytecodes, the worst case is reading a stale PID (None when it should be set, or a set PID when it should be None). Reading None is safe (skip the kill). Reading a stale PID might try to kill an already-exited process, which is handled by the `except (ProcessLookupError, OSError)`.
**Impact:** Theoretical only — no practical race in current usage because `run_gdal_subprocess` is single-threaded and PID assignment is bytecode-atomic.
**Found in:** Pass 4 — Concurrency Reasoning

## Design Concerns

### DC1: Post-processing chain has no gc.collect/malloc_trim between stages
The post-processing runs `_update_mbtiles_bounds` → `build_overviews` → `erode_nodata_edges` → `inpaint_nodata_pixels` in sequence (lines 2204-2236). Each opens the full MBTiles database, but there's no explicit memory release between them. The main pipeline stages (`_merge_tile`, `_reproject_tile`) have careful gc.collect + malloc_trim calls, but the post-processing chain omits this entirely. After `inpaint_nodata_pixels` loads all tile BLOBs via fetchall (B1), that memory sits in the process until Python's GC eventually collects it — which on glibc may never return to the OS without malloc_trim.

### DC2: `reproject_pool.shutdown(wait=False)` leaves threads running
At line 2190, when the pipeline exits (normally or via exception), the ThreadPoolExecutor is shut down with `wait=False`. If a reproject thread is mid-operation with a 486 MB GeoTIFF open in rasterio, it continues running in the background. The container SIGTERM handler will eventually kill it, but there's a window where zombie threads consume CPU and memory after the async event loop has exited. Combined with `wait=False`, any exceptions in those threads are silently lost.

### DC3: Checkpoint write in merger opens concurrent connection to same MBTiles
At lines 2165-2174, after a successful merge, the merger opens a NEW `sqlite3.connect(str(output))` to write the checkpoint table. This connection coexists briefly with any WAL state from the `_merge_tile` call that just completed (which closed its connection but left WAL data). With WAL mode, this is safe for readers, but the `CREATE TABLE IF NOT EXISTS` + `INSERT OR IGNORE` at lines 2168-2173 are writes that could encounter SQLITE_BUSY if the previous connection's WAL checkpoint (line 2039) hasn't finished flushing. The `with` statement auto-commits and closes, which helps, but there's no retry logic for SQLITE_BUSY.

### DC4: `_rasterize_to_disk` allocates a full tile_size x tile_size numpy array per tile
At line 631 in `_read_tile_from_array`, a new `np.zeros((bands, tile_size, tile_size), dtype=data.dtype)` is allocated for every single tile rendered. For 4-band data at uint8, that's 256*256*4 = 256 KB per tile. While individually small, during overview building at high zoom levels, thousands of tiles are rendered in rapid succession without any explicit deallocation. Python's small-object allocator may hold onto these pymalloc arenas rather than returning them to glibc, contributing to gradual memory creep.
