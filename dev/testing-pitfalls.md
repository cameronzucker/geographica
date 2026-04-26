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

## Idempotent early-return breaks implicit side-effect contracts
When a function is documented as "idempotent" and adds a guard (`if already_correct: return`), the guard can silently skip side effects that the caller expects to fire even when the primary state is already correct. The common case is polling restart: if a function restores UI state AND implicitly kicks off a polling loop via a synthetic click, the idempotent guard fires on BFCache returns (DOM preserved, state correct), skips the click, and leaves the polling loop dead — while the visual state looks fine. Tests should construct the "already correct + side effect needed" state (e.g., saved-tab matches active-tab but interval is dead) and verify both that the visual state is preserved AND the side effect re-fires.
*Found in:* `frontend/app.js:4129` — `restoreLastSidebarTab`'s `if (targetTab.classList.contains('active')) return` fires on BFCache returns with Admin tab active, skipping the synthetic click that `initAdmin`'s listener uses to restart `setInterval(fetchAdminStatus, ...)`. Admin polling stays dead despite the spec §4.3 guarantee.

## Resumable-download with unconditional truncate re-fetches every cached item
When a download helper opens the destination file with `"wb"` (always truncates), any caller relying on "if dest.exists() skip this URL" is silently bypassed because the existence check lives in the caller while the truncate happens unconditionally in the helper. A pipeline that SIGTERM'd between download and processing will re-download every cached-but-unprocessed file on resume, even though the bytes are still on disk. Tests should populate the destination path with a good file before calling the fetch helper and assert the helper does not re-request the URL (verify via HTTP mock call counter).
*Found in:* `scripts/acquire_imagery.py:416-455` (fetch_to_file) + `scripts/acquire_imagery.py:1953-1974` (_download_tile) -- `_download_tile` calls `fetch_to_file` without checking if `dest` already exists with valid content; `fetch_to_file` truncates dest on every call. Interrupted NOAA runs re-download hundreds of GB on resume.

## Multi-layer enum values diverge silently (UI dropdown vs env template vs consumer)
When one set of strings flows through three owners (a UI picker, a generated config file, and a consumer like nginx or docker-compose), each owner can be updated independently and drift. The "catch-all else" branch in the consumer silently ignores unknown enum values, so the UI and config can assert values the consumer never understood. Tests should enumerate every legal UI enum value, pass it through the generator, and feed it to a consumer shim that asserts on unknown values. A single round-trip test per enum value would catch this class of "TLS mode says self-signed, nginx runs HTTP" drift.
*Found in:* `setup/static/index.html:42-48` offers `self-signed|existing|external`, `.env.example:7` documents `tls-published|tls-standard`, `nginx/entrypoint.sh:5-54` only understands `https|tailscale`. All three sets of strings are disjoint except for `http`, and the silent-else in nginx masks the mismatch.

## Orchestrator loops that iterate steps without invoking subprocess
When a pipeline orchestrator defines `on_output` handlers inside a for-loop but never passes them to `run_command` (or the equivalent subprocess runner), each iteration runs in milliseconds and broadcasts "step complete" with no work done. Tests should assert that each PIPELINE_STEPS entry triggers at least one subprocess call to the runner during a full _run_pipeline execution — not just that the final state is "done". A mock on `run_command` that records calls and asserts `call_count == len(PIPELINE_STEPS)` would catch this immediately.
*Found in:* `setup/main.py:458-519` -- `_run_pipeline` iterates PIPELINE_STEPS, defines `on_output` inside the loop, but never calls `runner.run_command`. Pipeline "completes" in milliseconds with zero downloads.

## Fire-and-forget async save from UI that silently swallows server errors
When a save endpoint can return a validation error (400) and the UI caller does `api('POST', ...).catch(console.error)` without any user-facing surface, the user proceeds to the next wizard step believing their config persisted. Tests should assert the UI either awaits the save before navigation, OR displays a visible error when the save rejects — a 400 response from POST /api/config with the caller swallowing the rejection is a user-invisible failure. The fix is either `await saveConfig()` with a try/catch that blocks navigation on error, or to refactor save into a sync validation step before the POST.
*Found in:* `setup/static/setup.js:500-509` (saveConfig) and `:511-528` (saveCredentials) -- both functions return an unawaited promise with silent `.catch(console.error)`, called from `nextStep` which synchronously advances.

## Hardcoded dev-machine paths as docker-compose env defaults
When a service needs the host path of a sibling directory (e.g. `./scripts` on the host, for bind-mounting into a sub-container spawned via the Docker socket), the default value should derive from a known-anchor directory (like the compose file's own directory) or be left empty with a runtime error. Hardcoding a user-specific path like `/home/administrator/Code/geographica/scripts` means the default "works on the author's machine" and fails silently for every other user (the bind mount either fails or mounts an empty directory). Tests should run the compose file in CI from a non-author path and assert that services can still invoke their Docker-socket-spawned subprocesses, or that the service fails with a clear error instead of a silent broken mount.
*Found in:* `docker-compose.yml:125` -- `SCRIPTS_HOST_PATH: "${SCRIPTS_HOST_PATH:-/home/administrator/Code/geographica/scripts}"`. The default embeds the author's home path; any other user's pipeline-launch from the admin panel silently fails.

## String-prefix path allowlists permit sibling-with-same-prefix
When a security allowlist uses `any(path.startswith(p) for p in ALLOWED_PREFIXES)` with prefix strings like `/srv`, paths like `/srvattacker/malicious` pass the check because Python `startswith` doesn't enforce a path-boundary. Tests should include positive cases like `/srvattacker/whatever`, `/homeroot/x`, `/mntfoo`, and assert they're REJECTED, not accepted. The fix is to normalize prefixes with a trailing slash (`"/srv/"`) and match `p == prefix.rstrip("/") or p.startswith(prefix)` — or use `Path(p).is_relative_to(Path(prefix))` on 3.9+.
*Found in:* `setup/config.py:286-292` -- `validate_path` uses `startswith` against `("/srv", "/mnt", "/media", "/home")` with no boundary check. `/srvattacker/malicious` validates as True.

## UI message promises behavior the code doesn't implement
When a UI string says "values pre-filled from existing config" but the code only sets the `existing` boolean flag without parsing and applying the config values, the message is actively misleading. Tests should assert that when the UI displays the "pre-filled" hint, the form fields contain values sourced from the existing config file (not from detection defaults). A UI-integration test that writes a .env with non-default values, launches the wizard, and asserts the form reflects the .env would catch this.
*Found in:* `setup/static/setup.js:263-265` + `setup/main.py:184` -- UI shows "Existing .env found - values pre-filled" whenever `os.path.exists(ENV_PATH)` is True, but no code reads and parses the existing .env into form fields. All fields come from auto-detection and hardcoded defaults, so proceeding overwrites the existing .env with default values.

## Substring matching on status strings false-positives on "(un)healthy" variants
When checking a free-form status string for a keyword (e.g., `"healthy" in status`) where the containing string may itself contain the negation of the keyword (e.g., `"Up 2 days (unhealthy)"`), Python's substring `in` operator matches positively — `"healthy" in "unhealthy"` is True. Tests should enumerate every real status string the consumer may encounter (running-healthy, running-unhealthy, running-starting, Up N seconds without health, Exited) and assert the classification logic produces the correct bucket for each. A tabular test with ~8 status-string fixtures covers the entire decision tree.
*Found in:* `setup/main.py:549-552` -- `all_healthy = all("healthy" in (s.get("Health", "") or s.get("Status", "")) for s in services)` treats `"Up 2 days (unhealthy)"` as healthy because "healthy" appears as a substring of "unhealthy".

## Pydantic request models silently drop fields the client sends
When the frontend sends extra fields (e.g., `base_imagery_zoom`) that aren't in the backend's Pydantic request model, Pydantic discards them silently (default behavior without `extra="forbid"`). The endpoint succeeds, the user's choice is lost. Tests should diff the set of keys the frontend sends at each POST call site against the fields declared in the matching Pydantic model, and fail if the frontend sends a key the backend doesn't accept. Alternatively, set `model_config = ConfigDict(extra="forbid")` on request models so unknown fields raise 422.
*Found in:* `setup/static/setup.js:32,182,951` (sets `config.base_imagery_zoom`) + `setup/main.py:155-159` (StartRequest has no zoom field) -- user's zoom-slider value never reaches the backend; silently discarded.

## Preflight/fix registries with parallel keys that drift
When a "check" list and a "fix" list use the same set of string keys, the mapping between them must be 1:1 or documented. If one side has keys the other lacks (e.g., preflight checks `python3` but fix has only `python3-venv`), the UI presents a fix button that the backend rejects. Tests should compute `set(PREFLIGHT_CHECK_NAMES) ^ set(FIX_REGISTRY_KEYS)` and fail if the set-difference is non-empty (or explicitly document every asymmetric key).
*Found in:* `setup/main.py:39-62` -- PREFLIGHT_CHECKS keys `{docker, docker-compose, python3, gdal-bin, osmium-tool, gpsd, wget, curl, git}` vs FIX_REGISTRY keys `{docker, docker-compose, python3-venv, gdal-bin, osmium-tool, gpsd, wget, curl, unzip}`. Any mismatched key renders a Dead-End Install button.

## Deque/list iteration during async-concurrent mutation raises at runtime
When a coroutine iterates a shared `collections.deque` (e.g., to replay buffered events to a newly-connected WebSocket client) while another coroutine or subprocess-output callback appends to the same deque, Python raises `RuntimeError: deque mutated during iteration`. Tests should simulate WebSocket reconnect during active output streaming and assert the ws handler doesn't die mid-iteration. The fix is to snapshot via `list(deque)` before iterating.
*Found in:* `setup/main.py:411-414` -- `for event in progress_buffer:` in ws_progress iterates the shared deque while the pipeline's `on_output` callback (line 506) concurrently appends. Reconnect during active output crashes the WS handler.

## Subprocess orphan: grandchildren survive wizard shutdown
When a FastAPI app uses `asyncio.create_subprocess_exec` without `start_new_session=True`/`preexec_fn=os.setsid`, and a SIGTERM handler attempts to clean up children by signaling only direct PIDs, intermediate shells (`bash script.sh`) die but grandchildren (`openssl`, `gdal_translate`) persist, reparented to init. Tests should spawn a subprocess chain and assert that after `shutdown_children()`, `pgrep -f <grandchild>` returns empty. The fix is `start_new_session=True` + `os.killpg(pgid, SIGTERM)`.
*Found in:* `setup/runner.py:121-127,150-156` -- `run_command` spawns with default process group; `shutdown_children` signals direct children only.

## TOCTOU in async endpoints — check-then-mutate across await points
When a FastAPI handler reads `state["running"]`, checks it, then schedules a background task via `asyncio.create_task(...)` and only THEN sets the flag to True (or sets it inside the spawned coroutine), two concurrent requests both pass the check before either writes. Tests should fire N concurrent POSTs to the gating endpoint and assert exactly one task ran (and the others returned 409). Fix: set the flag synchronously under an `asyncio.Lock` INSIDE the handler, before scheduling any task.
*Found in:* `setup/main.py:446-455` — /api/start TOCTOU allows concurrent pipelines.

## Split state across engine, UI globals, and map sources
When a feature's "current state" (e.g., the active route) is represented in three independent places — an engine module's internal variables, a `window._global`, and a MapLibre source/layer — a mutation path that updates only one of them produces silent desync. Tests should assert that after any state-changing action (reroute, apply, clear), all three representations agree: engine snapshot matches `window._*`, and `map.getSource(id)._data` reflects the engine's shape.
*Found in:* `frontend/nav-ui.js:500-515` — `attemptReroute` updates the engine via `nav.applyReroute(...)` but never updates `map.getSource('route')` or `window._geographicaLastTrip`, leaving the map showing the OLD route for the remainder of navigation.

## MapLibre padding: N pixels ≠ N pixels of center offset
When code treats `padding: { top: N }` as "push the marker/center down by N pixels," the visible center is actually offset by `N/2` (padding is an inset, the center is at `(vh + top - bottom) / 2`). Tests that assert "GPS marker at 80% of viewport" with a top-only padding will fail regardless of N unless bottom is also constrained. Fix: encode the intended percentage (e.g., `top = 0.6*vh + overlayH, bottom = 0`) and derive the pixel values from it.
*Found in:* `frontend/nav-ui.js:768-775` — `getNavPadding` returns `{ top: overlay_height + 20 }`, which puts the GPS marker at ~58% of viewport instead of the intended 80%.

## MapLibre `easeTo` property persistence — the "padding leak"
When one code path calls `map.easeTo({ padding: {...} })` and another code path later calls `map.easeTo({ center: x, zoom: y })` without passing padding, MapLibre keeps the previous padding. This leaks state across feature boundaries (e.g., nav session sets padding; everything after nav inherits it). Tests should assert that after `leaveMode()`, subsequent `easeTo`/`flyTo` calls produce the same screen position as they would in a fresh session. Fix: explicitly pass zeroed `padding` when restoring default view.
*Found in:* `frontend/nav-ui.js:549-559` — `restoreMapState` restores center/zoom/pitch/bearing but omits padding, leaving nav-mode padding set on the map object for the rest of the session.

## Tiered-threshold voice announcements: 3 fires every time above speed gate
When an "announce at N distance thresholds, break on first success per tick, rely on subsequent ticks to catch later thresholds" pattern is combined with a cooldown shorter than the time between threshold crossings at typical speed, you always announce N times. Tests should simulate real-world speeds across the threshold range and assert the EMPIRICALLY observed announcement count matches the DESIGN INTENT (not just that the code reaches all thresholds). Fix: reduce thresholds, or make the cadence speed-adaptive (e.g., "announce when time-to-maneuver crosses 30s" not "when distance crosses 200m").
*Found in:* `frontend/navigation.js:42-46,362-391` — `VOICE_THRESHOLDS.auto = [800, 200, 50]` with 5s cooldown produces 3 announcements per maneuver at every driving speed above 2 m/s.

## CSS stacking with mixed `!important` overrides and custom buttons
When MapLibre's `!important` rule for `.maplibregl-ctrl-bottom-right { bottom: Xpx }` coexists with custom `position: absolute; bottom: Ypx; right: 12px;` buttons, collisions are not visible in the CSS itself — they only appear by computing each element's `bottom` + `height` range and checking for overlap against every other element in the same right-edge column. Tests should enumerate every element with `position: absolute; right: <small>px` and assert their y-ranges don't overlap at all supported breakpoints. Fix: maintain a single source-of-truth stack ordering comment in CSS naming every element and its bottom value per breakpoint.
*Found in:* `frontend/style.css:1436-1439,1673-1688` — `#nav-recenter-btn` (bottom:120) overlaps `#compass-north-btn` (bottom:140) at the ≤480px breakpoint; both sit near the MapLibre zoom ctrl (bottom:26, ~68px tall).

## Lossy adapter functions drop fields needed for retry/reroute
When a function converts a rich external API response (e.g., Valhalla trip) into a reduced internal shape for a different subsystem (nav engine), any fields the ORIGINATOR of the request will need again later — waypoints, costing_options, user preferences — must survive the conversion. A minimal/clean engine-facing shape that drops these fields quietly breaks any retry path that needs to reconstruct the original request. Tests should assert that after `buildX(original) -> internal`, enough information is preserved on `internal` (or its origin) to construct an equivalent request to the one that produced `original`.
*Found in:* `frontend/nav-ui.js:268-276` — `buildRouteData` hard-codes `remainingWaypoints: []` and omits `costing_options`, so the reroute fetch in `onReroute` reconstructs a simpler request that drops user waypoints and preferences.

## Polling interval decoupled from source rate causes duplicate state machine ticks
When a `setInterval(feedEngine, 500)` loop feeds an engine that keeps a tick-count-based history window (e.g., "3-of-5 consecutive off-route ticks"), and the underlying data source only updates at 1 Hz, half the ticks deliver duplicate data. The engine's history window fills in wall-clock time proportional to `window * pollInterval`, not `window * sourceInterval`, halving the intended debounce duration. Tests should mock the data source at its actual rate (1 Hz GPS), poll at the UI rate (2 Hz), and assert that the engine's threshold-based transitions fire at the expected WALL-CLOCK time — not the expected tick count.
*Found in:* `frontend/nav-ui.js:326-349` — `feedGPS` calls `nav.updateGPS` every 500ms regardless of whether `window._geographicaGPSData` actually changed; with a 1 Hz GPS source, the 5-tick off-route window triggers reroutes at ~2.5s instead of 5s.

## Polyline leg-stitching: index-adjust formulas mishandle the shared first point
When concatenating multiple Valhalla legs and stripping the shared first point of each non-initial leg, maneuver indices are adjusted via `(index - 1) + shapeOffset`. Maneuvers with `begin_shape_index = 0` (the "depart" maneuver of each leg) become `-1 + shapeOffset`, which points into the PREVIOUS leg's last segment. Tests should feed a 2-leg trip (e.g., a route with one waypoint) through the leg-stitching logic and assert that every maneuver's `begin_shape_index` in the output is `>= 0` and that the first maneuver of every leg starts exactly at the boundary index (not 1 before it). Fix: `Math.max(0, index - indexAdjust) + shapeOffset`.
*Found in:* `frontend/nav-ui.js:244-262` — `buildRouteData` subtracts `indexAdjust=1` without clamping, causing the first maneuver of legs 2+ to claim ownership of the final segment of the prior leg; voice/icon for next-leg turns fire one segment early on multi-waypoint routes.

## Trigger-threshold constants must be validated against their downstream rounding bucket
When a voice/UI system has two co-dependent constants — a trigger threshold (the distance at which a prompt fires) and a rounding function (how that distance is formatted for the user) — the trigger value must land in the rounding bucket that represents the INTENDED user-facing distance. If the trigger fires at 75m and the format function rounds 75m (246ft) to 200ft (the nearest-100ft bucket covers 150-249ft), the prompt says "200 feet" every time the trigger fires, regardless of actual user proximity. Tests should assert that `format(triggerThreshold)` produces the expected spoken string — not just that the trigger fires at the right distance. This also reveals when a floor/ceiling constant shifts by even one bucket boundary (e.g., lowering `VOICE_DISTANCE_FLOOR` from 75 to 45 keeps it in the "100 feet" bucket) and changes the user experience dramatically.
*Found in:* `frontend/navigation.js:52-56` + `:226` — `VOICE_DISTANCE_FLOOR.auto = 75m` triggers near-tier fires at 75m = 246ft, which `Math.round(246/100)*100 = 200` formats as "In 200 feet." Reducing the floor to ≤ 45.7m places it in the "100 feet" bucket (150ft threshold = 45.7m). The two constants (floor + rounding granularity) must be tested together; neither is obviously wrong in isolation.

## Idempotent guards that prevent implicit side-effect restart on lifecycle events
When a restore function uses an "already active — skip" idempotent guard to prevent double-clicks,
the guard also prevents implicit restarts of side-effects that were killed during background
(e.g., polling intervals). If the spec says "the side-effect is restarted implicitly by the
synthetic click," that claim is only true when the guard DOESN'T fire — i.e., when the target
is not already active. On BFCache returns where DOM is preserved and the target IS already
active, the guard fires an early return, and the polling/side-effect is never restarted. Tests
should simulate a BFCache-style return (call the pageshow/visibilitychange handler with the
target element already `.active`) and assert that any side-effects that were killed during
background (e.g., cleared intervals) are restarted.
*Found in:* `frontend/app.js:4129` — Admin polling `setInterval` is not restarted on BFCache
return when Admin tab is already `.active`; the idempotent guard returns before `targetTab.click()`
fires the `initAdmin` handler that would call `clearInterval` + `setInterval`. The spec §4.3
claimed "handled implicitly" but only analyzed the tab-discard path (HTML default Layers ≠ Admin)
— not the BFCache path (DOM preserved, Admin already active → guard fires).

## Browser lifecycle event ordering is the opposite of what intuition suggests
`pageshow` fires AFTER `DOMContentLoaded` on a normal first-load (order: parse → DOMContentLoaded → load → pageshow). Guards written as "skip if readyState is loading because pageshow fires before DOMContentLoaded" are based on a false premise. The guard is still correct (readyState is 'loading' during mid-parse visibilitychange, which needs guarding), but structural tests that only verify the guard's presence cannot catch a guard whose stated reason is wrong. Add a comment or test that verifies the ACTUAL reason for the guard (e.g., "user opens page as background tab, visibilitychange fires mid-parse").
*Found in:* `frontend/app.js:4295` — comment incorrectly states "first-load fires pageshow BEFORE DOMContentLoaded." Pageshow fires after DOMContentLoaded on first load; the guard's real protection is the background-tab mid-parse scenario (visibilitychange fires while readyState is still 'loading').

## NaN-guard pattern: `x <= 0` does NOT catch NaN; use `!(x > 0)` instead
In JavaScript, `NaN <= 0` is `false` (all NaN comparisons return false), so an "early return if non-positive" guard written as `if (x <= 0) return` silently passes NaN through. Downstream comparisons (`NaN <= threshold`) are also false, which may suppress behavior entirely without error — the silent failure mode. The correct NaN-inclusive guard is `if (!(x > 0)) return` (the `!(>=)` form used in `formatDistancePrefix` is equally safe). Tests should feed NaN directly into any guard that gates safety-critical logic (voice announcements, off-route detection thresholds, distance comparisons) and assert the guarded block is NOT entered.
*Found in:* `frontend/navigation.js:482` — `if (distToNext <= 0) return` guard in `checkVoice` silently passes NaN distToNext, then suppresses both voice tiers because `NaN <= ttmPair[1]` and `NaN <= floor` both evaluate to false. Contrast with the correctly-written guard at `navigation.js:223`: `if (!(meters >= DISTANCE_PREFIX_CUTOFF_METERS) || !isFinite(meters)) return ''`.
