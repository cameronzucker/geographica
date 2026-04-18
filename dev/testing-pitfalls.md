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

## Exception swallowing in perf-critical loops masks silent data-quality issues
When a hot loop processes items that may individually fail (e.g. `for tile in cursor: try: ... except: pass`), swallowing exceptions without a counter or log line makes per-item failures invisible. The pipeline reports success, but the output quality degrades in proportion to the failure rate. Tests should feed deliberately-corrupt BLOBs into the loop and assert the count of warnings/errors is non-zero, not just that the function returns success. A single counter variable (`errors += 1`) and a final `log.warning("swallowed N exceptions")` turns silent corruption into an observable signal.
*Found in:* `scripts/acquire_imagery.py:666-667` -- `merge_mbtiles` compositing loop catches all exceptions on decode/encode and silently keeps the existing tile; corruption during merging appears only as visual seams on the rendered map.

## Post-processing order dependencies (erode-before-overview, overview-before-inpaint)
When a multi-step post-processing pipeline mutates shared state (e.g. MBTiles database), the order matters. Running erosion AFTER overview generation leaves overview tiles referencing imagery at max zoom that was eroded away, creating zoom-level coverage gaps (basemap visible at high zoom, imagery visible at low zoom). Tests should assert both the ORDER of operations and the final consistency — no zoom level N can have a tile where zoom N-1's corresponding parent has no children, and vice versa.
*Found in:* `scripts/acquire_imagery.py:2222-2254` -- `run_noaa` calls `_run_gdaladdo_with_metadata_fixup` BEFORE `rio_erode_nodata_edges`, so overview tiles were built from pre-erosion base; after erosion, overview tiles contain imagery over regions where base zoom is now gone.

## Concurrent OAuth token refresh races re-authenticate multiple times
When N concurrent consumers share an auth object and the access token approaches expiry, each caller independently checks `time.monotonic() >= self.expires_at - 60` and calls `refresh()`. Without an `asyncio.Lock`, N simultaneous refresh requests hit the identity endpoint. OAuth providers that rotate refresh tokens on use will invalidate N-1 of the N concurrent refreshes, causing the losers to fall back to full password-grant authentication. Tests should simulate N concurrent `ensure_valid_token()` calls with an about-to-expire token and verify that only ONE refresh HTTP request was made (by counting mocks).
*Found in:* `scripts/acquire_sentinel.py:231-237,380-382` -- `CopernicusAuth.ensure_valid_token` has no lock; `concurrency=3` downloads can trigger 3 simultaneous refresh calls when token expires mid-pipeline.

## Streaming download lacks Content-Length short-read detection
When a streaming download writes bytes to a file via `iter_chunked`, a server that returns HTTP 200 with a valid Content-Length header but then closes the connection cleanly after transmitting only part of the body produces a truncated file with no exception. `fetch_to_file` returns True, magic-byte validation passes (the header is intact), but downstream processing (rasterio reproject) fails on corrupt truncated data. Tests should mock an HTTP response that returns Content-Length=N but body only contains N/2 bytes, and assert fetch_to_file returns False (not True).
*Found in:* `scripts/acquire_imagery.py:416-455` -- `fetch_to_file` does not compare `f.tell()` to `resp.content_length` after iter_chunked completes.

## Attribute access on a closed `with`-managed resource after block exit
When a `with rasterio.open(...) as ds:` block is exited and the code that follows (at the outer `try`/`finally` indent level) still calls `ds.width`, `ds.count`, etc., Python will evaluate those attributes against a closed GDAL dataset. Depending on the rasterio version, this returns stale cached values (silent), raises on attribute access (caught by the enclosing `except Exception`), or returns garbage. Latent bugs like this don't fail today but explode on library upgrades. Tests should assert that trailing log statements and cleanup code reference only values captured into locals *before* the `with` block exits, and should run the pipeline against a rasterio version pinned a minor version above current to flag forward-compat issues. Note: `log.debug(msg, *args)` evaluates `*args` eagerly regardless of log level — trailing debug-logs of closed-dataset attributes are not "disabled" by INFO level.
*Found in:* `scripts/rasterio_ops.py:250-252` -- `reproject_to_mercator` logs `src.width`/`src.height` AFTER the `with rasterio.open(...) as src:` block has exited; under stricter rasterio versions every reproject call will raise inside the log and return False via the enclosing `except Exception`.

## Progress-state updates skipped in failure paths leave the UI "stuck"
When a pipeline has a single "write progress state" function and it's called only on SUCCESS branches, failed items silently change shared counters (e.g., `tiles_failed += 1`) without writing the state file. The admin UI polls the state file and sees the last successful count for minutes or hours until the pipeline's final-phase code explicitly writes a completion status. Users can't tell whether the pipeline is hung or actually making failure progress. Tests should force mid-pipeline failures and assert that the state-file's `items_done + items_failed` equals `items_total` within a bounded polling window, not just after pipeline termination.
*Found in:* `scripts/acquire_imagery.py:2149-2151,2179-2185` -- `_merger()` increments `tiles_failed` on both `warped_path is None` and merge-failure branches without calling `_write_progress()`; the state file's phase/counters stay frozen on the last successful merge.

## Byte-level comparison of lossy-encoded blobs triggers unnecessary recomposite
When deciding whether two tiles "differ," a `WHERE src.tile_data != dst.tile_data` check on JPEG (or any lossy-compressed) blobs will almost always return "different" even when the tiles are visually identical — JPEG encoders introduce non-deterministic byte-level variation. Any downstream "composite" path that decodes, modifies, and re-encodes these blobs will run unnecessarily and accumulate generation-loss on every overlap. Tests should write the SAME raster through the function twice with different call orders and assert the pixel-level output is bitwise identical (not just "approximately the same"), or assert the composite path's "modifications" counter stays at 0 for truly-identical inputs.
*Found in:* `scripts/acquire_imagery.py:641-667` -- `merge_mbtiles` uses `WHERE s.tile_data != d.tile_data` to gate the composite path; this fires on every overlap because JPEG bytes differ, causing lossy re-encoding even when the compositing step copies zero pixels.

## Non-idempotent destructive post-processing on resume
When a post-processing step that DELETES rows (e.g., erosion, filtering) runs on every pipeline invocation — including resume paths where the main work was skipped — a second run evaluates a changed "boundary" and can destroy newly-added data. If the pipeline's checkpoint table says "done" for the deleted rows, recovery requires clearing the checkpoint and re-running from scratch; the data is permanently lost to normal resume. Tests should run the pipeline twice with overlapping-but-expanded inputs and assert that row count grows monotonically — erosion/filtering should never remove rows that were present at the end of the first run.
*Found in:* `scripts/rasterio_ops.py:868-959` -- `erode_nodata_edges` runs unconditionally in `run_noaa`'s phase 5 even on `skip_to_postprocess` (resume). It finds the current MIN/MAX tile-bounds and strips newly-added edge tiles, while the `_noaa_checkpoint` table marks them "done" — so resume runs can destroy previously-valid imagery with no recovery path short of dropping the checkpoint.

## Checkpoint write split from protected-work commit — resume retries protected work
When the checkpoint INSERT runs in a separate SQLite connection/transaction from the work it guards (e.g., "insert tile row → commit → open second connection → checkpoint-insert → commit"), a crash between the two commits leaves the work done but the checkpoint missing. On resume, the pipeline re-runs the protected work, which for idempotent paths (INSERT OR IGNORE) looks like a no-op — but if the protected work has side effects (lossy re-encoding, file deletion, partial progress) each retry compounds them. Tests should simulate SIGKILL between the two commits and verify that either both or neither is persisted.
*Found in:* `scripts/acquire_imagery.py:2157-2178` -- `_merger()` calls `_merge_tile` (which commits its own SQLite transaction), then opens a second connection to insert into `_noaa_checkpoint`. A SIGTERM in between leaves tile merged but unchecked → re-merge on resume runs the lossy-composite path again.

## Callee-chosen output path from ambiguous state field causes cross-pipeline targeting
When one function dispatches "finalization" (WAL checkpoint, cache invalidation, restart) by reading a `mode` or `type` field from shared state and mapping it to a file path, pipelines that forget to set that field get a dangerous default. If the default resolves to an existing-but-unrelated file, the finalization runs on the wrong target. Tests should invoke the dispatch function with every supported pipeline type AND with a missing/empty type field, and assert the target file matches the pipeline's actual output (not some other pipeline's leftovers).
*Found in:* `services/search/main.py:1511-1532` -- on pipeline completion, uses `state_data.get("mode", "imagery")` to build a candidate list and WAL-checkpoints the first existing file. Elevation/public-lands pipelines don't set `mode`, so the default falls through to `imagery.mbtiles` if that exists from a prior run — WAL-checkpointing the wrong file while the pipeline's actual output is left dirty.

## Two-phase state writes expose intermediate fields to consumers
When a progress-writer does `write canonical state` → `read back` → `add backward-compat fields` → `write again`, two atomic-rename operations occur for one logical update. A consumer polling faster than the writer between the two renames sees state WITHOUT the backward-compat fields (tiles_done, rate_per_sec, etc.), potentially rendering zero progress or NaN rates. Tests should poll the state file in a tight loop during pipeline execution and assert every observed state has the full set of expected fields, not just the final one.
*Found in:* `scripts/acquire_imagery.py:279-326` -- `update_progress` calls `_generic_progress` (write #1), then reads the file, injects `tiles_done`/`tiles_total`/`rate_per_sec`/etc., and calls `write_pipeline_state` (write #2). A frontend polling at 500ms during heavy phase transitions can hit write #1 and display missing-field state.

## Resumable-download with unconditional truncate re-fetches every cached item
When a download helper opens the destination file with `"wb"` (always truncates), any caller relying on "if dest.exists() skip this URL" is silently bypassed because the existence check lives in the caller while the truncate happens unconditionally in the helper. A pipeline that SIGTERM'd between download and processing will re-download every cached-but-unprocessed file on resume, even though the bytes are still on disk. Tests should populate the destination path with a good file before calling the fetch helper and assert the helper does not re-request the URL (verify via HTTP mock call counter).
*Found in:* `scripts/acquire_imagery.py:416-455` (fetch_to_file) + `scripts/acquire_imagery.py:1953-1974` (_download_tile) -- `_download_tile` calls `fetch_to_file` without checking if `dest` already exists with valid content; `fetch_to_file` truncates dest on every call. Interrupted NOAA runs re-download hundreds of GB on resume.
