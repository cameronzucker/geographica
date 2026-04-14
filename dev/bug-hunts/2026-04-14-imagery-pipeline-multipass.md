# Bug Hunt Report — Imagery Pipeline Multi-Pass

## Scope
Four Python scripts (~2,930 lines total) analyzed through five focused passes:

- `scripts/acquire_imagery.py` (1228 lines) — Main orchestrator with TNMAccess, direct tile, and M2M modes
- `scripts/acquire_naip.py` (705 lines) — NAIP-specific M2M download via USDA Gateway
- `scripts/acquire_sentinel.py` (601 lines) — Sentinel-2 via Copernicus STAC + OAuth2
- `scripts/download_elevation.py` (417 lines) — Terrain RGB tile download

All five passes performed: contract violations, cross-sibling patterns, failure modes, concurrency, error propagation.

## Bugs

### 1. SIGTERM cannot cancel subprocess.run — process hangs indefinitely
**Location:** `acquire_imagery.py:377-399` (convert_geotiffs_to_mbtiles), `acquire_naip.py:379-393` (convert_jp2_to_geotiff), `acquire_naip.py:410-451` (merge_to_mbtiles), `acquire_sentinel.py:428-450` (run_gdal_composite)
**Severity:** critical
**Evidence:** All four scripts register a SIGTERM handler that sets `_cancel_requested = True`, but `subprocess.run()` blocks the Python process. When GDAL is running (e.g., `gdal_translate` converting a 757-gigapixel mosaic), the SIGTERM handler fires and sets the flag, but Python never returns from `subprocess.run()` to check it. The child GDAL process does not receive the signal because `subprocess.run()` does not forward signals to child processes by default.

In `acquire_imagery.py`, `convert_geotiffs_to_mbtiles` (line 365) has no timeout at all — it calls `subprocess.run(check=True)` with no `timeout` parameter, meaning the GDAL process can run forever. The `acquire_naip.py` version at least sets `timeout=3600` and `timeout=7200`, but the signal forwarding problem remains.
**Impact:** This is the exact bug the user reported: a job stuck "stopping" for over an hour. `docker stop` sends SIGTERM, Python catches it, but `subprocess.run` blocks forever. Docker's 10-second stop timeout passes, Docker sends SIGKILL, potentially corrupting the partially-written MBTiles file.
**Found in:** Pass 1 — Contract Violations (the SIGTERM handler promises graceful shutdown but cannot deliver it during subprocess execution)

---

### 2. convert_geotiffs_to_mbtiles in acquire_imagery.py has no timeout, no GDAL_CACHEMAX, no memory protection
**Location:** `acquire_imagery.py:365-399`
**Severity:** critical
**Evidence:** Unlike its sibling in `acquire_naip.py` (which uses `GDAL_ENV` with `GDAL_CACHEMAX=256`, `GDAL_NUM_THREADS=2`, `nice -n 19`, and per-step timeouts), the `convert_geotiffs_to_mbtiles` in `acquire_imagery.py` calls bare `subprocess.run(["gdalbuildvrt", ...], check=True)` with no environment overrides, no `nice`, no timeout. With the docker-compose 2GB memory limit and GDAL_CACHEMAX=1024 set at container level, GDAL will use 1GB cache by default. But when concatenating 50+ NAIP scenes into a single VRT and translating, the intermediate memory usage can easily exceed the 2GB container limit, triggering OOM kill.

The function is also called from `_convert_and_cleanup` inside `m2m_download_batched` (line 880) via `run_in_executor`, meaning it runs in a thread pool — but `subprocess.run` blocks the thread indefinitely.
**Impact:** OOM kill during GDAL conversion, or indefinite blocking. The 757-gigapixel mosaic scenario is directly caused by this: all scenes are concatenated into one VRT and translated in a single `gdal_translate` call with no memory bounds.
**Found in:** Pass 2 — Cross-Sibling Pattern Violations

---

### 3. Race condition: concurrent aiosqlite writes in run_direct without serialization
**Location:** `acquire_imagery.py:524-544`, `download_elevation.py:314-337`
**Severity:** significant
**Evidence:** In `run_direct`, up to 2000 tasks are launched via `asyncio.gather` (line 569), and each `_fetch_tile` coroutine does `await db.execute(INSERT OR REPLACE ...)` on the same `aiosqlite.Connection`. While aiosqlite serializes actual SQLite calls through a background thread, the interleaving of `await db.execute(tile INSERT)` followed by `await db.execute(checkpoint INSERT)` across multiple concurrent coroutines means a crash between those two awaits loses the tile data but doesn't record the checkpoint — so the tile is re-downloaded on resume (harmless). However, the real issue is that with 2000 concurrent coroutines all awaiting `db.execute`, the aiosqlite internal queue can grow unboundedly, and the commit only happens after the entire batch (line 569: `await asyncio.gather(*tasks)` then `await db.commit()`). If the process crashes mid-batch, up to 2000 tiles of work are lost because they were never committed.

The same pattern exists in `download_elevation.py` at lines 358-364.
**Impact:** On crash or SIGKILL during a batch, up to 2000 tiles (imagery) or 500 tiles (elevation) of downloaded data are lost and must be re-fetched. Not a data corruption bug, but a significant wasted-work bug on the Pi 5's constrained bandwidth.
**Found in:** Pass 4 — Concurrency Reasoning

---

### 4. download_geotiffs reads entire GeoTIFF into memory via resp.read()
**Location:** `acquire_imagery.py:248-250` (fetch_with_retry), called from `acquire_imagery.py:345` (download_geotiffs _get_one)
**Severity:** significant
**Evidence:** `fetch_with_retry` calls `await resp.read()` which loads the entire response body into memory. NAIP GeoTIFFs from M2M can be 500MB-2GB each. With `concurrency=5` (the M2M cap) and a semaphore that only gates the download phase, multiple large files can be held in memory simultaneously. On a Pi 5 with 16GB RAM inside a Docker container with a 2GB memory limit, even a single 2GB GeoTIFF exceeds the container's memory allocation.

Contrast with `acquire_sentinel.py:383-393` which correctly uses streaming download (`resp.content.iter_chunked(1024 * 1024)`) with incremental file writes, bounded at `MAX_FILE_SIZE=5GB`.
**Impact:** Container OOM kill when downloading large NAIP GeoTIFFs. The M2M mode downloads multi-hundred-megabyte files through `fetch_with_retry` which buffers them entirely in memory before writing to disk.
**Found in:** Pass 2 — Cross-Sibling Pattern Violations

---

### 5. Checkpoint write in download_geotiffs is not atomic and not crash-safe
**Location:** `acquire_imagery.py:351`
**Severity:** significant
**Evidence:** `checkpoint_path.write_text(json.dumps(done, indent=2))` writes the checkpoint non-atomically (direct overwrite, no tmp+rename). If the process crashes during this write (or is OOM-killed), the checkpoint file is corrupted (partially written JSON). On restart, `json.loads(checkpoint_path.read_text())` at line 332 will throw `JSONDecodeError` and the entire checkpoint is lost, causing all files to be re-downloaded.

Contrast with all three sibling scripts which use the atomic tmp-file + `os.fsync` + `os.replace` pattern:
- `acquire_naip.py:206-213` (save_checkpoint)
- `acquire_sentinel.py:306-313` (save_checkpoint)
- `download_elevation.py:109-116` (write_pipeline_state)
**Impact:** On crash during any file download, the entire download checkpoint is lost. All previously downloaded files must be re-fetched.
**Found in:** Pass 2 — Cross-Sibling Pattern Violations

---

### 6. UnboundLocalError: tif_paths referenced before assignment on login failure path
**Location:** `acquire_imagery.py:1127-1132`
**Severity:** significant
**Evidence:** In `run_m2m`, if an exception occurs inside the `try` block (lines 1068-1122) after login but before `tif_paths` is assigned at line 1117 (e.g., `m2m_find_naip_dataset` raises, or `m2m_scene_search` raises), the `finally` block at line 1124 runs `m2m_logout` successfully, then execution continues to line 1127: `if _cancel_requested:` ... line 1130: `len(tif_paths)`. Since `tif_paths` was never assigned, this raises `UnboundLocalError`.

Specifically, if `m2m_find_naip_dataset` or `m2m_scene_search` raises a `RuntimeError` (which `m2m_request` raises on all retries exhausted at line 625), the exception propagates out of the `try` block. But the `finally` runs `m2m_logout`, then the exception continues propagating — except it's caught by... nothing. Actually, looking more carefully: the `RuntimeError` from `m2m_request` propagates up through `m2m_find_naip_dataset` → the try block → the finally runs logout → then the exception propagates out of `run_m2m` → out of `asyncio.run` → crash. The `tif_paths` reference at 1127 is only reached if the try block completes normally. So this is only triggered if `_cancel_requested` is set during `m2m_download_batched` AND the function returns normally but before `tif_paths` is assigned — which actually can't happen because `_cancel_requested` is checked inside the loop and `m2m_download_batched` returns `all_paths`.

Wait — re-reading more carefully: the `try/finally` wraps lines 1068-1125. If `m2m_download_batched` at line 1117 itself raises an exception (e.g., `m2m_request` for `download-options` raises after all retries), then `finally` runs logout, then the exception propagates, and lines 1127+ are never reached. So this is NOT a bug for exception paths.

However, if `_cancel_requested` is True AND `m2m_download_batched` returns early (via the `break` at line 893), `tif_paths` IS assigned (to whatever `all_paths` is at that point). So this specific path is actually safe.

**Retracted** — On closer analysis, `tif_paths` is always assigned before the post-try code is reached because exceptions propagate past it.

---

### 6. (Replacement) TNMAccess query_tnm_products builds URL with unencoded query parameters
**Location:** `acquire_imagery.py:308-310`
**Severity:** significant
**Evidence:** The URL is constructed via string concatenation: `TNM_API + "?" + "&".join(f"{k}={v}" for k, v in params.items())`. The `dataset` parameter is `"USDA National Agriculture Imagery Program (NAIP)"` which contains spaces and parentheses. These are not URL-encoded. While many HTTP libraries and servers handle this, the `aiohttp.ClientSession.get()` may normalize the URL, but the parentheses in particular can cause issues with some proxy configurations.

More critically, `fetch_with_retry` is called with the session from `query_tnm_products` which creates its OWN session (line 298), separate from any session the caller might provide. This means `query_tnm_products` creates a new `aiohttp.ClientSession` per call. This is not itself a bug, but the URL encoding issue means the TNMAccess API may return unexpected results or 400 errors for dataset names with special characters.
**Impact:** Potential HTTP 400 from TNMAccess API due to unencoded special characters in the dataset name parameter.
**Found in:** Pass 1 — Contract Violations

---

### 7. acquire_naip.py downloads entire JP2 into memory before writing to disk
**Location:** `acquire_naip.py:350-355`
**Severity:** significant
**Evidence:** `download_county` calls `fetch_with_retry` (which uses `resp.read()` to buffer the entire response in memory), then `dest.write_bytes(data)`. NAIP county JP2 files can be 1-30GB (the `MAX_JP2_SIZE_BYTES` constant is set to 30GB). The validation at line 595 checks the file size AFTER download, not before. Even the HEAD request at line 302-308 only logs the content length but doesn't prevent the download.

The entire file is loaded into Python memory before any size check occurs.
**Impact:** OOM kill when downloading large county JP2 files. Even a single 5GB JP2 will exceed the 2GB Docker container memory limit.
**Found in:** Pass 3 — Failure Mode Reasoning

---

### 8. Sentinel download_scene opens file but closes it implicitly on size-exceeded abort
**Location:** `acquire_sentinel.py:383-393`
**Severity:** minor
**Evidence:** At line 383, `with open(dest, "wb") as f:` opens the file. At line 389-392, when the download exceeds MAX_FILE_SIZE, the code calls `f.close()` explicitly, then `dest.unlink()`. But `f.close()` is redundant since the `with` block will close it — and more importantly, the `return None` at line 393 exits the `with` block, the `async with` semaphore, and the retry loop all at once. The explicit `f.close()` before `dest.unlink()` is fine but the file is left partially written until `dest.unlink()`.

Actually this works correctly. Not a bug.

**Retracted** — The behavior is correct.

---

### 8. (Replacement) acquire_sentinel.py downloads scenes sequentially despite having a semaphore
**Location:** `acquire_sentinel.py:532-552`
**Severity:** minor
**Evidence:** In `run_pipeline`, scenes are downloaded in a sequential `for` loop (line 532: `for i, scene in enumerate(scenes)`), calling `await download_scene(...)` one at a time. The `semaphore = asyncio.Semaphore(args.concurrency)` created at line 529 is never actually used for parallel downloads — it only gates the HTTP request inside each `download_scene` call, but since only one scene is downloading at a time, the semaphore is always immediately available.

Compare with `acquire_imagery.py:357-361` where downloads are parallelized via `asyncio.as_completed(tasks)`.
**Impact:** Sentinel-2 downloads run at 1/concurrency of their intended speed. With `--concurrency 3` (the default), downloads take 3x longer than they should.
**Found in:** Pass 2 — Cross-Sibling Pattern Violations

---

### 9. M2M _m2m_request_and_poll_urls uses hardcoded 30s sleep instead of M2M_POLL_INTERVAL constant
**Location:** `acquire_imagery.py:793`
**Severity:** minor
**Evidence:** The constant `M2M_POLL_INTERVAL = 10` is defined at line 588, but the actual poll loop at line 793 uses `await asyncio.sleep(30)`. The comment says "USGS example uses 30s between polls" but the constant says 10s. The constant is never used anywhere.
**Impact:** Misleading constant. Not a functional bug since 30s is the correct value per USGS guidance, but the dead constant could cause confusion if someone changes it expecting behavior to change.
**Found in:** Pass 1 — Contract Violations

---

### 10. _m2m_request_and_poll_urls remaining count calculation can go negative
**Location:** `acquire_imagery.py:820`
**Severity:** minor
**Evidence:** `remaining = requested_count - len(failed) - len(seen_ids)`. But `requested_count` is already calculated as `len(downloads) - len(failed)` at line 771. So `remaining = len(downloads) - len(failed) - len(failed) - len(seen_ids)` — `failed` is subtracted twice. If there are any failed downloads, `remaining` will be smaller than expected and the loop may exit prematurely (thinking all downloads are ready when some are still preparing).
**Impact:** When some downloads fail in the request phase, the poll loop exits early, potentially missing downloads that are still preparing. The result is fewer downloaded files than available.
**Found in:** Pass 5 — Error Propagation

---

### 11. Non-atomic state file writes create TOCTOU window
**Location:** `acquire_imagery.py:170-198` (update_progress reads then writes state file)
**Severity:** minor
**Evidence:** `update_progress` in acquire_imagery.py performs a three-step operation: (1) call `_generic_progress` to atomically write the state file, (2) read it back with `json.loads(state_path.read_text())`, (3) enrich it and write again via `write_pipeline_state`. Between step 1 and step 2, another process (or the admin panel reading the file) could see an intermediate state. Between step 2 and step 3, another concurrent call to `update_progress` (e.g., from the `_on_file` callback) could overwrite the state file, and the enrichment from the first call would be lost.

This is primarily a concern during M2M batched downloads where `_on_file` callbacks fire from multiple coroutines.
**Impact:** Occasional stale/flickering progress state in the admin panel. Not a data loss bug.
**Found in:** Pass 4 — Concurrency Reasoning

---

### 12. acquire_naip.py concurrency parameter accepted but never used
**Location:** `acquire_naip.py:464,685-686,694`
**Severity:** minor
**Evidence:** `run_pipeline` accepts `concurrency: int = 2` but never passes it to `download_county` or uses it to create a semaphore. Each county is downloaded sequentially in the `for idx, (fips, url_info) in enumerate(downloadable)` loop at line 556. The `--concurrency` CLI argument at line 685 is parsed but has no effect on download parallelism.
**Impact:** The concurrency argument is dead code. Downloads always run sequentially regardless of what value is passed.
**Found in:** Pass 1 — Contract Violations

## Design Concerns

### Shared mutable state for cancellation via module-level globals
All four scripts use `global _cancel_requested` set by a SIGTERM handler. This is inherently fragile because:
- The flag is only checked at loop boundaries, not during long-running operations
- `subprocess.run` blocks for the duration of GDAL operations (minutes to hours), during which the flag cannot be checked
- The SIGTERM handler cannot call `subprocess.terminate()` on the child because it doesn't have a reference to the `Popen` object

A more robust pattern would be to use `subprocess.Popen` directly with the signal handler calling `proc.terminate()` on the child, or to use `subprocess.run` with a `timeout` and check the flag between retries.

### Entire-file-in-memory download pattern
Three of four scripts (acquire_imagery, acquire_naip, download_elevation) use `await resp.read()` which buffers the entire HTTP response in memory. Only acquire_sentinel uses streaming download. For tile downloads (small PNGs), this is fine. For GeoTIFF/JP2 downloads (hundreds of MB to GB), this is dangerous inside a 2GB Docker container.

### VRT-of-all-files conversion pattern
Both `acquire_imagery.py` and `acquire_naip.py` build a single VRT from ALL downloaded GeoTIFFs and translate it in one `gdal_translate` call. For large bboxes (the western US default), this can produce a mosaic of hundreds of files spanning hundreds of gigapixels. The per-batch conversion in M2M mode (`_convert_and_cleanup`) partially mitigates this, but the final conversion pass at line 1144-1153 still processes all remaining files at once, and the TNMAccess mode has no batching at all.
