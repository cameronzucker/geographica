# Testing Pitfalls

Patterns observed during bug hunts that tests should guard against.

## Exception type mismatches in except clauses
When calling functions that operate on values that could be None, `except (ValueError, TypeError)` is insufficient -- `AttributeError` from calling methods on None (e.g., `None.split(",")`) slips through. Tests should verify error paths with actual None inputs, not just malformed strings.
*Found in:* `services/search/main.py:1175-1181` -- `_parse_bbox(None)` raises AttributeError, not caught by except.

## Resource lifecycle in multi-phase functions
When a function acquires a resource (e.g., Docker client), closes it, then conditionally uses it again later, the closed resource may appear truthy but fail silently. Tests that mock the resource should verify it's called in the right lifecycle phase.
*Found in:* `services/search/main.py:1140,1156` -- Docker client used after close, logs silently lost.

## Duplicate validity checks across layers
When an engine layer validates a value (e.g., heading validity gated at speed >= 3 m/s) but a UI layer re-implements its own weaker validity check (e.g., heading != 0 || speed > 1), the layers disagree. Tests should feed the same edge-case inputs through both layers and assert they agree on validity.
*Found in:* `frontend/navigation.js:516-522` vs `frontend/nav-ui.js:308-310` -- engine and UI use different speed gates for heading validity, causing map rotation at low speeds.

## Consecutive-counter fragility under noisy inputs
When a counter must reach N consecutive ticks to trigger an action but resets to 0 on any single contrary tick, even modest input noise makes the threshold unreachable. Tests should simulate realistic GPS jitter (not clean synthetic data) to verify the counter can actually reach its threshold.
*Found in:* `frontend/navigation.js:577-588` -- off-route detection requires 5 consecutive ticks >50m but resets on any tick <=50m, making rerouting nearly impossible with real GPS noise.

## Polling rate vs counter-based thresholds
When a counter increments per-tick and the threshold assumes a specific tick rate (e.g., "5 consecutive 1 Hz ticks = 5 seconds"), changing the polling interval breaks the timing silently. Tests should assert wall-clock elapsed time at threshold crossings, not just counter values.
*Found in:* `frontend/navigation.js:22,578` -- OFF_ROUTE_TICKS=5 assumes 1 Hz, but `nav-ui.js:295` polls at 500ms, halving the effective timeout and causing double-processing of stale data.

## State consumed on check (announce-once patterns)
When an "announce once" mechanism marks an event as handled before the side effect succeeds, muting/suppressing the side effect still consumes the event. Tests should verify that suppressed events can be re-triggered after the suppression is lifted.
*Found in:* `frontend/navigation.js:341,745` -- `announcedSet` marks thresholds during mute; un-muting doesn't replay them.

## Unrecoverable state on async failure
When an engine transitions to a transient state (e.g., "rerouting") and delegates recovery to an async callback (fetch), but the callback's error handler doesn't reset the state, a network failure leaves the engine stuck permanently. Tests should simulate fetch failures and assert the engine returns to a functional state within a bounded time.
*Found in:* `frontend/nav-ui.js:456-474` -- reroute fetch failure leaves engine in "rerouting" state forever; no timeout or retry resets to "navigating".

## JavaScript truthiness for numeric zero
When `||` is used to provide fallback values for numeric fields, the value `0` is treated as falsy and skipped. For fields where 0 is a valid value (heading=0 means due north, speed=0 means stopped), use explicit null checks instead. Tests should always include 0 as a test input for numeric fields using `||` fallback chains.
*Found in:* `frontend/nav-ui.js:308` -- `data.heading || data.bearing || 0` skips heading=0 (due north).

## Whole-file reads for unbounded downloads
When `await resp.read()` or `resp.content` is used to download files of unknown size, the entire response is buffered in memory before writing to disk. If the file can be arbitrarily large (e.g., multi-GB satellite imagery), this causes OOM kills. Tests should mock the HTTP response with a content-length header exceeding the container memory limit and verify the code uses chunked streaming instead.
*Found in:* `scripts/acquire_imagery.py:248-250` -- `fetch_with_retry` uses `resp.read()` for NAIP GeoTIFFs that can be multiple GB, in a container limited to 2 GB RAM.

## subprocess.run blocking signal handlers
When a SIGTERM handler sets a cancellation flag but the main thread is blocked in `subprocess.run()`, the flag is never checked until the subprocess exits (which may be hours later). Tests should verify that cancellation actually terminates long-running subprocesses within a bounded time, not just that the flag is set correctly.
*Found in:* `scripts/acquire_imagery.py:377-399`, `scripts/acquire_sentinel.py:428-451` -- GDAL subprocess.run blocks indefinitely, making SIGTERM-based cancellation ineffective.

## Overwrite-on-append in multi-pass file creation
When a function creates an output file (e.g., `gdal_translate -of MBTiles`) and is called repeatedly with the same output path, each call overwrites the previous result. If the caller expects incremental accumulation (e.g., batch-by-batch tile addition), only the last call's data survives. Tests should call the function twice with different inputs and verify both inputs' data exists in the output.
*Found in:* `scripts/acquire_imagery.py:366-400` -- `convert_geotiffs_to_mbtiles` called per-batch in M2M mode, each call overwrites the output MBTiles.

## Non-atomic checkpoint writes lose all progress on crash
When a checkpoint file is written via `path.write_text(json.dumps(data))` instead of the atomic tmp+fsync+rename pattern, a crash or OOM-kill during the write produces a partially-written JSON file. On restart, `json.loads()` fails on the corrupt file and the entire checkpoint is lost, forcing a full re-download. Tests should write a checkpoint, simulate a mid-write crash (truncate the file), and verify the loader either recovers the previous checkpoint or handles the corruption gracefully -- not silently discard all progress.
*Found in:* `scripts/acquire_imagery.py:351` -- `checkpoint_path.write_text()` in `download_geotiffs` while sibling scripts (`acquire_naip.py:206-213`, `acquire_sentinel.py:306-313`) all use atomic writes.

## Accepted-but-ignored parameters create false confidence
When a function accepts a parameter (e.g., `concurrency`) in its signature but never uses it internally, callers believe they're controlling behavior that isn't actually variable. Tests should verify that changing the parameter actually changes observable behavior (e.g., number of concurrent connections, timing patterns).
*Found in:* `scripts/acquire_naip.py:464,694` -- `concurrency` parameter accepted by `run_pipeline` and parsed from CLI but never used; downloads always run sequentially.

## Double-subtraction in completion tracking
When a "remaining" count is computed by subtracting failures from a total that was already reduced by failures (e.g., `requested_count = total - failed; remaining = requested_count - failed - completed`), failures are counted twice, causing the loop to exit early. Tests should run scenarios where some items fail and verify that all non-failed items are still collected before exiting.
*Found in:* `scripts/acquire_imagery.py:771,820` -- `requested_count` already excludes failures, then `remaining` subtracts them again, causing premature exit from the download-retrieve polling loop.

## UnboundLocalError from try/finally control flow
When a variable is assigned inside a `try` block and referenced after the corresponding `finally` block, an exception in the `try` block causes the variable to never be assigned. The `finally` block executes (cleanup), then execution continues past `finally` and hits `UnboundLocalError`, masking the original error. Tests should simulate exceptions in the `try` block and verify proper error handling without secondary exceptions.
*Found in:* `scripts/acquire_imagery.py:1117-1130` -- `tif_paths` assigned inside `try`, referenced after `finally` block; any exception in `m2m_download_batched` causes UnboundLocalError.

## Success-path log strings used as completion markers are mode-specific
When reconciliation logic detects pipeline completion by scanning container logs for a string (e.g., "MBTiles written to"), adding new pipeline modes that log different completion messages silently break the detection for those modes. Tests should verify that each mode's completion log string is matched by the reconciliation logic, or the reconciliation logic should use a state file write rather than log scanning.
*Found in:* `services/search/main.py:1383` -- reconciliation checks for "MBTiles written to" but `run_noaa` logs "NOAA pipeline complete: ..." on success; successful NOAA runs are incorrectly marked "interrupted".

## delete-after semantics must be gated on per-file success, not batch success
When a delete-after flag deletes source files based on whether any file in a batch was processed (not whether each specific file was processed), files that failed mid-batch are still deleted. Tests should include batches with mixed success/failure and verify that only successfully-processed source files are deleted.
*Found in:* `scripts/import_imagery.py:177-181` -- `if delete_after and warped_paths:` deletes all source files in the batch if any reprojection succeeded, including those that failed reprojection.

## False blob validation via HEAD on virtual directory paths
When validating Azure Blob Storage accessibility, HEAD requests against virtual directory paths (e.g., `https://account.blob.core.windows.net/container/prefix/`) return 404 because virtual directories are not addressable objects. Tests should mock the HTTP layer and verify the validation request targets an actual blob object or uses the Azure Blob Storage service endpoint, not a virtual directory path.
*Found in:* `scripts/acquire_imagery.py:1562-1571` -- HEAD request to `{blob_base}/` always returns 404 from Azure, blocking all NOAA downloads.

## Call-site-before-implementation: function called before it exists
When a refactor updates call sites to call a new helper function (e.g., `run_gdal_subprocess`) before the helper module is created, the code compiles and imports cleanly but raises `NameError` at runtime. Tests should import and call every public function once (a smoke test) to catch missing definitions before the code reaches production. A minimal `test_imports.py` that imports each script module would have caught this immediately.
*Found in:* `scripts/acquire_imagery.py:607,615,1429` -- `run_gdal_subprocess` called but `scripts/gdal_subprocess.py` never created, crashing NOAA and import pipelines at runtime.

## Validation bypass flags not extended to new modes with similar behavior
When a boolean flag (`is_m2m`) gates expensive or inappropriate validation steps (tile count disk estimate, zoom requirement), adding a new mode with similar properties (NOAA: GeoTIFF-based, no per-tile zoom) without adding a corresponding flag leaves the new mode subjected to validations that are incorrect for it. Tests should verify each mode's validation path independently, including modes that do not require zoom.
*Found in:* `services/search/main.py:1093-1100` -- NOAA mode runs zoom-based tile count disk estimate, producing a false 507 even with adequate disk space.

## API field name contracts not verified end-to-end
When a backend API returns fields under specific names (e.g., `id`, `size_bytes`) and a frontend reads different names (e.g., `source_id`, `file_size_bytes`), the mismatch is invisible to unit tests that only test the backend. The frontend receives real data but reads `undefined` for every field, silently corrupting the display. Tests should assert the exact field names the consumer reads, not just that a response is 200 OK. A single integration test (or even a schema snapshot test) that walks every field the frontend accesses by name would catch this class of bug.
*Found in:* `frontend/config/index.html:2008-2124` vs `services/search/main.py:772-778` -- inventory tab reads `src.source_id`/`src.file_size_bytes` but API returns `src.id`/`src.size_bytes`, causing "no inventory" despite files on disk.

## TMS vs slippy-map Y coordinate convention
When converting tile coordinates to lat/lon, TMS (used by MBTiles) numbers Y=0 at the bottom (South Pole) while slippy maps (used by web mapping libraries and the standard lat/lon conversion formula) number Y=0 at the top (North Pole). Applying the slippy-map formula directly to TMS Y values produces the correct magnitude but wrong hemisphere. Tests that only check range validity (`-85 <= lat <= 85`) pass silently; tests must verify the sign/hemisphere against known tile coordinates.
*Found in:* `services/search/main.py:725-726` -- `_tile_bounds_tms()` uses slippy-map formula on TMS Y values, producing -33.6° instead of +33.6° for Arizona tiles.

## Missing auth dependency on write endpoints allows unauthenticated destructive actions
When some admin endpoints use `dependencies=[Depends(require_config_source)]` and others don't, the ones without it are reachable through any path that proxies to the service — including the public NGINX `/search/` prefix. Tests should verify that every endpoint under `/admin/` that performs a write or deletion returns 403 when called without the required headers, and should test through the NGINX proxy path (not just direct to the service) to catch routing gaps.
*Found in:* `services/search/main.py:801` -- `DELETE /admin/imagery/{source_id}` has no `require_config_source` dependency; reachable at `/search/admin/imagery/{id}` on the public port with no auth.

## CRS-aware unit conversions hardcoded for equatorial/geographic assumptions
When a function converts between coordinate units (e.g., degrees to meters), using a single constant (like 111,320 m/degree) that only holds at the equator or for geographic CRS produces wrong results at other latitudes or for projected CRS where the input is already in meters. Tests should feed the same raster through the function in multiple CRS (geographic, UTM, Web Mercator) and verify that derived values (like zoom levels) are consistent to within 1 unit.
*Found in:* `geographica-companion/pipelines/rasterio_ops.py:408` -- `_compute_zoom_range` multiplies resolution by 111,320 regardless of CRS or latitude; yields wildly wrong zoom for UTM data (already in meters) and moderately wrong zoom at mid-latitudes.

## Success return on zero output silently loses data
When a function returns True/success after producing zero output items (e.g., zero rendered tiles), callers that delete source files on success will destroy input data without producing any output. Tests should feed a minimal input that produces zero output (e.g., an all-nodata raster) and verify the function returns failure, not success.
*Found in:* `geographica-companion/pipelines/rasterio_ops.py:363-381` -- `merge_to_mbtiles` returns True when `_rasterize_to_disk` renders zero tiles; callers delete source GeoTIFFs believing conversion succeeded.

## Resource cleanup in except blocks without finally
When a resource (database connection, file handle, thread pool) is opened inside a `try` block and closed on the happy path, but the `except` handler returns without closing it, any exception leaks the resource. Tests should inject exceptions at each possible failure point and verify resources are closed (e.g., mock `sqlite3.connect` and assert `.close()` was called even when the body raises). This is especially dangerous for SQLite connections with WAL mode, where a leaked connection holds the WAL journal open and prevents checkpointing.
*Found in:* `scripts/rasterio_ops.py:663-778` -- `build_overviews` opens a SQLite connection at line 664, closes it at line 771 (happy path) and 687 (cancel path), but the `except` block at line 776 returns False without closing the connection.

## `fetchall()` on tables with BLOB columns causes unbounded memory usage
When `fetchall()` is used on a query that includes BLOB columns, all BLOBs are materialized into Python memory simultaneously. For MBTiles tables where `tile_data` is a JPEG/PNG BLOB, this means the entire tileset is loaded into RAM. Tests should monitor peak memory usage (via `tracemalloc` or process RSS) when processing large tilesets and assert it stays within the container memory limit. Alternatively, test with a cursor-based iteration pattern to verify streaming works.
*Found in:* `scripts/rasterio_ops.py:804-806` -- `inpaint_nodata_pixels` loads every tile's BLOB into memory via `fetchall()` before iterating; for large NOAA datasets this can exceed the 2 GB container memory limit.

## Unhandled exceptions from `future.result()` in pipeline drain loops
When a concurrent pipeline drains completed futures by calling `f.result()`, any exception from the worker function propagates through `result()` and kills the drain loop. If the drain loop owns a sentinel-forwarding responsibility (sending `None` to the next stage's queue), the downstream stage starves. Tests should submit a worker that raises, then verify the pipeline still completes remaining work and forwards sentinels to all downstream stages.
*Found in:* `scripts/acquire_imagery.py:2122` -- `_reprojector` calls `f_future.result()` without try/except; an exception in `_reproject_tile` (e.g., FileNotFoundError from stat on a deleted file) kills the reprojector, which never sends a sentinel to the merge queue, hanging the merger.

## Finalization guards stale after adding fast-path bypasses
When a long function has setup (acquire resource) and teardown (release resource) gated by a counter (`if tiles_done > 0`), adding a fast-path that skips the main work loop means the counter never increments. Teardown that depended on `tiles_done > 0` silently skips, leaving the resource unreleased. Tests should exercise every named skip/bypass code path and verify that all teardown steps still execute — not just the main path.
*Found in:* `scripts/acquire_imagery.py:2240` -- `run_noaa` unregisters imagery_noaa from TileServer at top, re-registers only when `tiles_done > 0`, but `skip_to_postprocess` path keeps `tiles_done = 0`, permanently removing the layer from TileServer config.

## Temporary directory cleanup missing from exception paths in multi-stage functions
When a function creates a temporary directory in the middle of a multi-stage pipeline (stage 1: create tiles on disk, stage 2: import to SQLite), the `finally` block may only clean up resources from stage 0 (e.g., closing rasterio datasets) without cleaning up the temp directory from stage 1. Tests should inject exceptions at each stage boundary and verify no temp directories remain on disk.
*Found in:* `scripts/rasterio_ops.py:344-397` -- `merge_to_mbtiles` creates `.tiles_{stem}` directory at line 344; if `_rasterize_to_disk` or `_bulk_import_tiles` raises, the `finally` block at line 389 closes datasets but never calls `_cleanup_tile_dir`.
