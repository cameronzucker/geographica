# Bug Hunt Report — Imagery Pipeline (Exploratory)

**Date:** 2026-04-14
**Hunter:** Exploratory depth-first analysis
**Model:** Claude Opus 4.6

## Scope

Deeply analyzed all four pipeline scripts and their coordination layer:

- `scripts/acquire_imagery.py` (1228 lines) — Main orchestrator, M2M/TNM/direct modes
- `scripts/acquire_naip.py` (705 lines) — NAIP county mosaic pipeline
- `scripts/acquire_sentinel.py` (601 lines) — Sentinel-2 Copernicus pipeline
- `scripts/download_elevation.py` (417 lines) — Terrain RGB tile download
- `setup/runner.py` (157 lines) — Subprocess executor with SIGTERM forwarding
- `scripts/pipeline_progress.py`, `scripts/pipeline_security.py` — Shared utilities
- `docker-compose.yml` — Pipeline container config (2GB memory limit)

**Exploration strategy:** Started with signal handling (known issue), then followed threads into GDAL subprocess management, then examined batch/checkpoint logic for state corruption, then async patterns for resource leaks.

## Bugs

### 1. SIGTERM cannot stop GDAL subprocesses — pipeline hangs indefinitely on cancel

**Location:** `scripts/acquire_imagery.py:377-392` (convert_geotiffs_to_mbtiles), `scripts/acquire_naip.py:379-394` (convert_jp2_to_geotiff), `scripts/acquire_naip.py:410-438` (merge_to_mbtiles), `scripts/acquire_sentinel.py:428-451` (run_gdal_composite)
**Severity:** critical
**Evidence:** All four scripts register a SIGTERM handler that sets `_cancel_requested = True`. However, every GDAL operation uses `subprocess.run()` which blocks the Python process until the child completes. When SIGTERM arrives during a `subprocess.run()` call:

1. Python's signal handler fires and sets the flag
2. But `subprocess.run()` does NOT return — it waits for the child process to exit
3. The child (`gdal_translate`, `gdaladdo`, `gdalbuildvrt`) never receives SIGTERM because Python doesn't forward it
4. The cancel flag is never checked because Python is blocked in `subprocess.run()`

The `setup/runner.py` sends SIGTERM to pipeline children via `shutdown_children()`, but this only targets the Python process, not its GDAL grandchildren. The Python process catches SIGTERM (sets flag) but can't act on it.

**Impact:** This is the exact bug causing the user's "job stuck stopping for over an hour" report. A `gdal_translate` converting a 757-gigapixel VRT mosaic will run for hours with no way to interrupt it. `docker stop` sends SIGTERM, waits 10s, then sends SIGKILL — but SIGKILL to the Python process may leave orphaned GDAL processes.

### 2. VRT mosaic concatenates ALL scenes before conversion — unbounded memory and time

**Location:** `scripts/acquire_imagery.py:366-401` (convert_geotiffs_to_mbtiles)
**Severity:** critical
**Evidence:** The `convert_geotiffs_to_mbtiles()` function builds a single VRT from ALL GeoTIFFs, then runs a single `gdal_translate` to convert the entire mosaic to MBTiles at once:

```python
def convert_geotiffs_to_mbtiles(tif_paths: list[Path], output: Path):
    # ...
    subprocess.run(
        ["gdalbuildvrt", str(vrt_path)] + [str(p) for p in tif_paths],
        check=True,
    )
    subprocess.run(
        ["gdal_translate", "-of", "MBTiles", ...
         str(vrt_path), str(output)],
        check=True,
    )
```

For 50 NAIP scenes (the known incident), this creates a 757-gigapixel mosaic. `gdal_translate` must process this entire raster, which can take hours and will exceed the 2GB container memory limit (`docker-compose.yml:217`). There's no `GDAL_CACHEMAX` env set for TNMAccess mode (unlike M2M which sets it on line 1042), and even the M2M mode's 1024MB GDAL cache exceeds half the 2GB container limit.

Note: `acquire_naip.py:397-438` (merge_to_mbtiles) has the same pattern — concatenate all GeoTIFFs into one VRT, then single `gdal_translate`.

**Impact:** Memory exhaustion, OOM kill, or hours-long uninterruptible conversion for any moderately-sized download.

### 3. M2M pipelined conversion calls convert_geotiffs_to_mbtiles which OVERWRITES the output MBTiles each batch

**Location:** `scripts/acquire_imagery.py:873-889` (_convert_and_cleanup), `scripts/acquire_imagery.py:366-401` (convert_geotiffs_to_mbtiles)
**Severity:** critical
**Evidence:** The M2M batched pipeline creates a background task per batch to convert and cleanup:

```python
async def _convert_and_cleanup(paths, batch_label):
    async with convert_sem:
        await asyncio.get_event_loop().run_in_executor(
            None, convert_geotiffs_to_mbtiles, paths, output_path
        )
```

But `convert_geotiffs_to_mbtiles` runs `gdal_translate -of MBTiles ... str(vrt_path) str(output)` — this creates a NEW MBTiles file from the VRT, overwriting whatever was there before. So each batch's conversion destroys the output of all previous batches.

Batch 1 converts 50 scenes to imagery.mbtiles. Batch 2 converts the next 50 scenes to imagery.mbtiles, overwriting batch 1's data entirely. Only the LAST batch's scenes survive in the output file.

Then at the end (`acquire_imagery.py:1144-1153`), any remaining GeoTIFFs get a "final conversion pass" which AGAIN overwrites the output file with only the remaining files.

**Impact:** For multi-batch M2M downloads, only the last batch's imagery is retained. All earlier batches are silently lost.

### 4. download_geotiffs reads entire file into memory via resp.read()

**Location:** `scripts/acquire_imagery.py:345-346`
**Severity:** significant
**Evidence:** In `_get_one()` inside `download_geotiffs()`:

```python
async with sem:
    data = await fetch_with_retry(session, url)
# ...
dest.write_bytes(data)
```

`fetch_with_retry()` calls `await resp.read()` which loads the entire response body into memory. NAIP GeoTIFFs can be 1-5 GB each. With concurrency=5 (the parameter used in download_geotiffs), this could require 5-25 GB of RAM simultaneously, far exceeding the 2GB container limit.

The same `fetch_with_retry` pattern is used by `acquire_naip.py:351` (`download_county()`), where county JP2 files can also be multi-GB.

Compare with `acquire_sentinel.py:383-393` which correctly uses streaming `resp.content.iter_chunked(1024 * 1024)`.

**Impact:** OOM kills when downloading large NAIP scenes. The container has only 2GB memory.

### 5. acquire_naip.py download_county reads entire JP2 into memory

**Location:** `scripts/acquire_naip.py:351-356`
**Severity:** significant
**Evidence:** Same pattern as Bug #4:

```python
data = await fetch_with_retry(session, url_info["url"])
if data is None:
    return None
dest.write_bytes(data)
```

County JP2 files can be 10-30 GB (the `MAX_JP2_SIZE_BYTES` constant is 30 GB). The file is loaded entirely into Python memory before writing to disk. The container has 2GB memory.

**Impact:** Will always OOM for any real NAIP county download. The size validation on line 595-599 checks `jp2_path.stat().st_size` AFTER writing the file to disk, but the memory limit will be hit during `resp.read()` before the file is even written.

### 6. Sentinel download_scene token obtained before semaphore — stale token under contention

**Location:** `scripts/acquire_sentinel.py:357-359`
**Severity:** significant
**Evidence:**

```python
async with semaphore:
    token = await auth.ensure_valid_token(session)
    headers = {"Authorization": f"Bearer {token}"}
```

The token is obtained inside the semaphore, which is correct. However, the retry loop on line 361-410 does NOT refresh the token between retry attempts. If the first attempt fails with a 429 or 5xx and the retry happens after a backoff delay, the token could have expired by then (tokens last 600s, but with 3 retries at exponential backoff plus a 1200s download timeout, the token could be 30+ minutes old).

**Impact:** Retry attempts may fail with 401 if the token expired during backoff, causing unnecessary scene download failures.

### 7. M2M download-retrieve polling checks wrong variable for completion

**Location:** `scripts/acquire_imagery.py:820`
**Severity:** significant
**Evidence:**

```python
remaining = requested_count - len(failed) - len(seen_ids)
if remaining <= 0:
    break
```

`requested_count` is computed as `len(downloads) - len(failed)` on line 771. Then `remaining` subtracts `len(failed)` AGAIN:

```python
requested_count = len(downloads) - len(failed)  # line 771
# ...
remaining = requested_count - len(failed) - len(seen_ids)  # line 820
```

This double-subtracts `len(failed)`, meaning `remaining` will reach 0 (and break out of the polling loop) while there are still `len(failed)` downloads unaccounted for. This causes the polling loop to exit prematurely when there are failures, which is actually the desired behavior (stop waiting for things that failed). However, the calculation is misleading — if `failed` is empty (common case), the math is correct. The bug manifests only when `failed` is non-empty AND there are still preparing downloads: it stops polling too early, before all preparing downloads have resolved.

Wait — re-reading more carefully: `remaining` here represents "how many downloads are we still waiting for." With the double subtraction, if 5 downloads, 1 failed, 3 seen: `remaining = (5-1) - 1 - 3 = 0`, but we should be waiting for 1 more (5 - 1 failed - 3 seen = 1 remaining). So this IS a real bug that exits the polling loop one download early per failure.

**Impact:** When some downloads in a batch fail, the polling loop exits early, potentially missing downloads that are still preparing. Those downloads' URLs are never collected.

### 8. Checkpoint file in download_geotiffs is not atomically written

**Location:** `scripts/acquire_imagery.py:352`
**Severity:** minor
**Evidence:**

```python
done[url] = str(dest)
checkpoint_path.write_text(json.dumps(done, indent=2))
```

Unlike every other checkpoint write in the codebase (which uses the tmp+fsync+replace pattern), this checkpoint is written directly via `write_text()`. If the process crashes mid-write (power loss, OOM kill), the checkpoint file will be corrupt/truncated, and ALL download progress is lost on resume.

**Impact:** Crash during download phase loses all checkpoint state, causing re-download of all files on resume.

### 9. TNMAccess mode subprocess.run calls have no timeout

**Location:** `scripts/acquire_imagery.py:377-400` (convert_geotiffs_to_mbtiles)
**Severity:** significant
**Evidence:**

```python
subprocess.run(
    ["gdalbuildvrt", str(vrt_path)] + [str(p) for p in tif_paths],
    check=True,
)
subprocess.run(
    ["gdal_translate", "-of", "MBTiles", ...
     str(vrt_path), str(output)],
    check=True,
)
subprocess.run(
    ["gdaladdo", "-r", "average", str(output), "2", "4", "8", "16"],
    check=True,
)
```

None of these have `timeout=` parameters. Compare with `acquire_naip.py:379` which has `timeout=3600` and `acquire_naip.py:420` with `timeout=7200`. The `acquire_sentinel.py:428-451` also has no timeouts on its GDAL calls.

**Impact:** GDAL processes in TNMAccess and Sentinel modes can run forever with no timeout enforcement, compounding Bug #1.

### 10. Sentinel pipeline skips GDAL conversion when cancelled AFTER aiohttp session closes

**Location:** `scripts/acquire_sentinel.py:554-560`
**Severity:** minor
**Evidence:**

```python
    # (inside async with aiohttp.ClientSession())
    ...

if not downloaded_files:   # <-- OUTSIDE the async with block
    ...
    return

if _cancel_requested:      # <-- checked here
    ...
    return

# --- Composite ---
update_progress(output, "compositing", ...)

if _cancel_requested:      # <-- and again here, redundantly
    ...
    return
```

The cancel check at line 560-562 and 568-570 is correct but the check at 568-570 is dead code — if `_cancel_requested` was True at line 560, execution would have already returned. The real issue: between lines 554 and 560, if cancellation is requested, the downloaded files are on disk but no cleanup happens. The staging directory accumulates uncleaned TIF files across cancelled runs.

**Impact:** Disk space leak from accumulated staging files across cancelled Sentinel runs. Not a correctness bug, but a resource leak.

### 11. run_m2m references tif_paths in finally-adjacent code when exception occurs

**Location:** `scripts/acquire_imagery.py:1127-1130`
**Severity:** significant
**Evidence:**

```python
    try:
        # ...
        tif_paths = await m2m_download_batched(...)
    finally:
        await m2m_logout(session, api_key)

if _cancel_requested:
    log.info("Cancellation requested after downloads — skipping conversion")
    update_progress(output, "m2m", args.bbox, "n/a",
                    len(tif_paths), len(scenes), ...)
```

If `m2m_download_batched` raises an exception (e.g., RuntimeError from `m2m_request` after all retries fail), the `finally` block logs out, then execution falls through to line 1127, which references `tif_paths` — but `tif_paths` was never assigned because the exception occurred before the assignment. This causes an `UnboundLocalError: local variable 'tif_paths' referenced before assignment`, masking the original error.

**Impact:** Any exception during M2M download phase causes a secondary `UnboundLocalError`, hiding the root cause and preventing proper error reporting to the state file.

### 12. M2M batch conversion runs convert_geotiffs_to_mbtiles in executor without GDAL_ENV

**Location:** `scripts/acquire_imagery.py:878-881`
**Severity:** minor
**Evidence:**

```python
await asyncio.get_event_loop().run_in_executor(
    None, convert_geotiffs_to_mbtiles, paths, output_path
)
```

`convert_geotiffs_to_mbtiles` (line 366) calls `subprocess.run` without setting `env=GDAL_ENV`. It inherits the default process environment. The M2M pipeline sets `GDAL_CACHEMAX` via `os.environ.setdefault` on line 1042, but `convert_geotiffs_to_mbtiles` doesn't pass any env to subprocess, so it inherits whatever the process env is — which DOES include the setdefault from line 1042 since os.environ is global.

Actually, this is NOT a bug — `subprocess.run` without `env=` inherits `os.environ` which includes the `GDAL_CACHEMAX` set on line 1042. However, the TNMAccess path (`run_tnmaccess`, line 403) calls `convert_geotiffs_to_mbtiles` WITHOUT setting `GDAL_CACHEMAX` first, meaning GDAL uses its default cache size (which can be large and cause OOM in the 2GB container).

**Impact:** TNMAccess mode GDAL operations run without memory bounds, risking OOM in the container.

## Design Concerns

### Monolithic VRT-to-MBTiles conversion is the root design flaw

All three download pipelines (TNMAccess, M2M, NAIP) follow the same pattern: download all files, concatenate into one VRT, convert the entire thing in a single `gdal_translate` call. This creates a single point of failure with unbounded time and memory requirements. The M2M pipeline attempted to fix this with per-batch conversion, but the underlying `convert_geotiffs_to_mbtiles` function overwrites the output each time (Bug #3).

The correct approach would be per-tile or per-scene conversion to MBTiles with an append/merge strategy (e.g., using `gdal_translate` with `-co APPEND_SUBDATASET=YES` or merging at the SQLite level).

### No process group management for GDAL subprocesses

The signal handling architecture assumes Python can act on cancellation by checking a flag between operations. But GDAL subprocesses can run for hours, during which Python is blocked. The fix requires either:
- Using `subprocess.Popen` with process groups and `os.killpg()` in the signal handler
- Or using `asyncio.create_subprocess_exec` instead of `subprocess.run`

### Memory-unbounded downloads via fetch_with_retry

`fetch_with_retry` loads entire responses into memory (`resp.read()`). This is the default download mechanism for TNMAccess and NAIP pipelines. Only Sentinel-2 uses streaming downloads. All pipelines should use chunked/streaming downloads for large files.

### Checkpoint format inconsistency

Three different checkpoint formats are used across the four scripts:
- `download_geotiffs`: `{url: path}` dict, non-atomic write
- `acquire_naip`: `{completed_counties, skipped_counties, discovered_urls}` dict, atomic write
- `acquire_sentinel`: raw scene list, atomic write with age expiry
- `download_elevation`: SQLite `_checkpoint` table

This inconsistency increases the risk of checkpoint-related bugs and makes resume logic harder to reason about.
