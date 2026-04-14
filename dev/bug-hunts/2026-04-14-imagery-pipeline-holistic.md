# Bug Hunt Report

## Scope

Analyzed the complete imagery acquisition pipeline: `scripts/acquire_imagery.py` (1228 lines), `scripts/acquire_naip.py` (705 lines), `scripts/acquire_sentinel.py` (601 lines), `scripts/download_elevation.py` (417 lines), plus the `setup/runner.py` orchestrator and `docker-compose.yml` resource constraints.

Read all four scripts end-to-end, then traced data flow from API calls through download to GDAL conversion, focusing on signal handling, resource management, error propagation, and the batched download architecture.

## Bugs

### 1. SIGTERM cannot stop subprocess.run — pipeline hangs indefinitely on cancel

**Location:** `scripts/acquire_imagery.py:377-399`, `scripts/acquire_naip.py:379-393`, `scripts/acquire_sentinel.py:428-451`
**Severity:** critical
**Evidence:** All three scripts set `_cancel_requested = True` in a SIGTERM handler, but every GDAL invocation uses `subprocess.run()` which blocks the Python thread. The cancel flag is never checked because Python never returns from the `subprocess.run` call. In `acquire_imagery.py`, `convert_geotiffs_to_mbtiles` calls `subprocess.run` three times sequentially (gdalbuildvrt, gdal_translate, gdaladdo) with no timeout on any of them (unlike `acquire_naip.py` which at least has `timeout=3600`). When converting a VRT built from 50+ concatenated NAIP scenes, `gdal_translate` can run for hours. The SIGTERM from `docker stop` is caught by the Python handler but the child `gdal_translate` process never receives it.

**Impact:** The known issue: a job stuck "stopping" for over an hour. `docker stop` sends SIGTERM, Python catches it and sets the flag, but `subprocess.run` blocks indefinitely. After Docker's 10-second grace period, Docker sends SIGKILL to the Python process, which may leave partial MBTiles files, orphaned VRT files, and no checkpoint update. The pipeline container becomes unkillable without `docker kill`.

### 2. GeoTIFF downloads loaded entirely into memory via resp.read()

**Location:** `scripts/acquire_imagery.py:248-250` (fetch_with_retry), `scripts/acquire_imagery.py:346` (download_geotiffs uses fetch_with_retry)
**Severity:** critical
**Evidence:** `fetch_with_retry()` does `return await resp.read()` which reads the entire HTTP response into memory. NAIP GeoTIFFs from M2M can be hundreds of megabytes to several gigabytes each. The download_geotiffs function at line 350 calls `dest.write_bytes(data)`, meaning the entire file is buffered in Python memory before writing. With the pipeline container limited to 2 GB RAM (docker-compose.yml line 217), downloading even a single large NAIP scene could OOM the container.

Contrast with `acquire_sentinel.py:383-393` which correctly uses `resp.content.iter_chunked(1024 * 1024)` for streaming downloads with a running size check.

**Impact:** OOM kill of the pipeline container when downloading large NAIP scenes via M2M or TNMAccess mode. The container has a 2 GB memory limit, and NAIP county mosaics can easily exceed 1 GB each.

### 3. M2M batched conversion overwrites output MBTiles on every batch

**Location:** `scripts/acquire_imagery.py:366-400` (convert_geotiffs_to_mbtiles), called from `scripts/acquire_imagery.py:880`
**Severity:** significant
**Evidence:** `convert_geotiffs_to_mbtiles` runs `gdal_translate -of MBTiles ... str(vrt_path) str(output)` which creates a new MBTiles file each time. In the M2M batched pipeline, `_convert_and_cleanup` at line 879 calls this function for each batch. Batch 2's conversion will overwrite the MBTiles file created by batch 1's conversion. Only the last batch's tiles survive.

Then at line 1144-1152, any remaining unconverted tifs get a "final conversion pass" which again overwrites the file. The pipelined architecture (download batch N+1 while converting batch N) makes this worse — each batch's conversion result is destroyed by the next.

**Impact:** For multi-batch M2M downloads (>50 scenes), only the final batch's imagery appears in the output MBTiles. All earlier batches' tiles are silently lost.

### 4. acquire_naip.py downloads entire JP2 files into memory

**Location:** `scripts/acquire_naip.py:351-356` (download_county calls fetch_with_retry, then dest.write_bytes)
**Severity:** significant
**Evidence:** Same pattern as bug #2. `fetch_with_retry` at line 141 does `return await resp.read()` loading the entire JP2 into memory. NAIP JP2 files can be up to 30 GB (the MAX_JP2_SIZE_BYTES constant at line 50). The timeout is 1200 seconds (20 minutes). Even with the Pi 5's 16 GB RAM, downloading a multi-GB JP2 entirely into memory while other services are running risks OOM.

**Impact:** Memory exhaustion when downloading large county JP2 files, especially on the Pi 5 where other services consume significant RAM.

### 5. UnboundLocalError on tif_paths when M2M download-options/request/poll fails

**Location:** `scripts/acquire_imagery.py:1117-1130`
**Severity:** significant
**Evidence:** The M2M pipeline at line 1117 assigns `tif_paths = await m2m_download_batched(...)`. This is inside a `try/finally` block (line 1068/1124) that always calls `m2m_logout`. After the finally, line 1127 checks `if _cancel_requested:` and references `tif_paths` at line 1130. If `m2m_download_batched` raises an exception (e.g., M2M API returns an error, network failure during download-options), the `finally` block runs `m2m_logout`, then execution continues to line 1127 where `tif_paths` is not defined, causing `UnboundLocalError`.

Similarly, `scenes` at line 1130 could be undefined if the exception occurs before line 1081.

**Impact:** When M2M API calls fail during the download phase, the pipeline crashes with `UnboundLocalError` instead of reporting the actual error. The M2M logout still happens (good), but the error message is lost.

### 6. Sentinel-2 GDAL conversion has no timeout and no signal forwarding

**Location:** `scripts/acquire_sentinel.py:428-451` (run_gdal_composite)
**Severity:** significant
**Evidence:** Three `subprocess.run` calls with no `timeout` parameter. Unlike `acquire_naip.py` which sets `timeout=3600` for gdal_translate, the Sentinel pipeline has no timeout at all. Combined with the SIGTERM-cannot-reach-subprocess issue (bug #1), a slow GDAL conversion in the Sentinel pipeline is completely unkillable.

Additionally, the cancel check at line 569 (`if _cancel_requested`) happens BEFORE `run_gdal_composite` is called at line 576, and the next cancel check at line 583 happens AFTER. There is no cancel check during the (potentially hours-long) GDAL conversion.

**Impact:** Sentinel-2 GDAL conversion cannot be cancelled and has no timeout. A conversion of many scenes could run indefinitely.

### 7. acquire_naip.py concurrency parameter is accepted but never used

**Location:** `scripts/acquire_naip.py:685-686` (argparse), `scripts/acquire_naip.py:694-700` (asyncio.run call)
**Severity:** minor
**Evidence:** The `--concurrency` argument is parsed at line 685 and passed to `run_pipeline` at line 699. The `run_pipeline` function accepts `concurrency: int = 2` at line 463, but never uses it. Downloads happen one county at a time in a sequential `for` loop (line 556). The concurrency parameter is dead code.

**Impact:** Users who pass `--concurrency 4` expecting parallel county downloads get sequential behavior instead. Not a correctness bug per se, but violates the documented contract.

### 8. download_geotiffs checkpoint is not atomic

**Location:** `scripts/acquire_imagery.py:352`
**Severity:** minor
**Evidence:** Inside `download_geotiffs`, the checkpoint file is written with `checkpoint_path.write_text(json.dumps(done, indent=2))`. This is not atomic — if the process is killed during the write, the checkpoint file will be corrupted (partial JSON). Contrast with the atomic write pattern used elsewhere (write to .tmp, fsync, os.replace) in `acquire_naip.py:208-214` and `acquire_sentinel.py:306-312`.

**Impact:** If the process is killed during a checkpoint write in the TNMAccess or M2M download phase, the checkpoint file is corrupted and all downloads restart from scratch.

### 9. Sentinel-2 scene deduplication across chunks is missing

**Location:** `scripts/acquire_sentinel.py:499-507`
**Severity:** minor
**Evidence:** When the bbox is split into chunks by `compute_chunks`, each chunk is searched independently via `stac_search`. Results are accumulated with `scenes.extend(chunk_scenes)` at line 507. Sentinel-2 scenes near chunk boundaries will appear in multiple chunk search results. There is no deduplication by scene ID before downloading. Each duplicate scene will be downloaded, taking extra time and disk space.

The `download_scene` function does skip if the file already exists on disk (via `safe_staging_path`), but only after the semaphore is acquired and the auth token is validated — wasting API rate limit budget.

**Impact:** Duplicate downloads at chunk boundaries waste bandwidth and disk space. For large bounding boxes split into many chunks, this could be significant.

## Design Concerns

### Batch-level conversion is architecturally flawed for MBTiles

The M2M pipeline's approach of converting each batch independently to MBTiles (bug #3) is fundamentally incompatible with how `gdal_translate -of MBTiles` works — it creates a fresh file each time. MBTiles is an SQLite database with a fixed schema; appending tiles from subsequent batches would require either: (a) a merge step that combines multiple MBTiles files, or (b) converting all GeoTIFFs at the end in one pass. The current pipelined architecture (convert batch N while downloading batch N+1) silently destroys previous batches' output.

### No disk space checks in acquire_imagery.py (TNMAccess/M2M modes)

Unlike `acquire_naip.py` (line 573, `check_disk_space`) and `acquire_sentinel.py` (line 351-354), the main `acquire_imagery.py` script never checks disk space before downloading files in either TNMAccess or M2M mode. The `download_geotiffs` function downloads files until the disk is full, at which point writes will fail with opaque OS errors.

### subprocess.run without process group management

All four scripts use `subprocess.run` for GDAL operations but never set `start_new_session=False` or use `preexec_fn` for process group management. When running inside Docker, SIGTERM from `docker stop` goes to PID 1 (Python), but GDAL child processes are in the same process group. The SIGTERM signal handler in Python catches the signal and sets a flag, but `subprocess.run` masks the signal from reaching Python's control flow. Using `subprocess.Popen` with explicit signal forwarding to children would allow graceful cancellation.

### Memory-unbounded file accumulation in staging directories

In the M2M pipeline, `_convert_and_cleanup` (line 873) is designed to delete GeoTIFFs after conversion, but if conversion fails (line 887-889), it logs a warning and keeps the raw files. There is no limit on how many failed-conversion files accumulate in staging. On the 896 GB SSD with NAIP scenes at potentially GBs each, staging could consume all available space.
