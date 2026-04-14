# Imagery Pipeline Bug Hunt — Consolidated Findings

**Date:** 2026-04-14
**Scope:** Imagery acquisition pipeline — `scripts/acquire_imagery.py`, `scripts/acquire_naip.py`, `scripts/acquire_sentinel.py`, `scripts/download_elevation.py`
**Hunters:** Exploratory, Holistic, Multipass

---

## Confirmed Bugs

### B1. SIGTERM cannot stop GDAL subprocesses — pipeline hangs indefinitely on cancel
**Consensus:** All three hunters
**Location:** `acquire_imagery.py:377-399`, `acquire_naip.py:379-393`, `acquire_sentinel.py:428-451`
**Evidence:** All scripts register SIGTERM handlers setting `_cancel_requested = True`, but `subprocess.run()` blocks the Python thread. Python never returns from `subprocess.run()` to check the flag. Docker's 10-second stop timeout passes, then SIGKILL fires, potentially corrupting the output MBTiles file.
**Impact:** User-reported "stuck stopping for over an hour." The only escape is SIGKILL which risks data corruption.
**Blast radius:** All four scripts use this pattern. Fix requires replacing `subprocess.run` with `subprocess.Popen` + signal forwarding or process group management.
**Fix approach:** Use `subprocess.Popen` with `preexec_fn=os.setsid` to create a process group. In the SIGTERM handler, send SIGTERM to the process group via `os.killpg`. Add a timeout to all GDAL calls.

### B2. convert_geotiffs_to_mbtiles overwrites output MBTiles on every batch call
**Consensus:** All three hunters
**Location:** `acquire_imagery.py:366-400`, called from line 880
**Evidence:** `gdal_translate -of MBTiles` creates a new file each time. The M2M pipelined architecture calls `convert_geotiffs_to_mbtiles` per batch, so each batch's MBTiles output overwrites the previous. Only the last batch survives.
**Impact:** For a 20,869-scene download (418 batches × 50), batches 1-417 are silently destroyed. Only batch 418's 19 scenes end up in the output.
**Blast radius:** `acquire_imagery.py` only (M2M mode). TNMAccess mode calls it once at the end. acquire_naip.py has its own conversion function.
**Fix approach:** Either (a) accumulate all TIF paths and convert once at the end, or (b) use `gdal_translate` to write to a temp MBTiles per batch, then merge with `gdalwarp -of MBTiles` or tile-level SQLite INSERT.

### B3. GeoTIFF downloads loaded entirely into memory (OOM risk)
**Consensus:** All three hunters
**Location:** `acquire_imagery.py:248-250` (`fetch_with_retry` uses `resp.read()`), `acquire_naip.py:351` (same)
**Evidence:** `return await resp.read()` loads entire HTTP response into memory. NAIP county JP2 files can be hundreds of MB to 30GB. Container has 2GB memory limit. With concurrency=3-5, multiple files loading simultaneously will OOM.
**Impact:** Container gets OOM-killed on large scenes. Only `acquire_sentinel.py:383-393` correctly uses `iter_chunked()` for streaming.
**Blast radius:** `acquire_imagery.py` and `acquire_naip.py`. Fix requires streaming download to disk.
**Fix approach:** Replace `resp.read()` with `async for chunk in resp.content.iter_chunked(64*1024)` writing to a temp file, similar to `acquire_sentinel.py`'s pattern.

### B4. UnboundLocalError masks original exception in run_m2m
**Consensus:** Exploratory and Holistic
**Location:** `acquire_imagery.py:1117-1130`
**Evidence:** `tif_paths` is assigned at line 1117 inside the `try` block. If `m2m_download_batched` raises, the `finally` block runs `m2m_logout` at line 1125, then execution falls to line 1127 where `tif_paths` is referenced but undefined, causing `UnboundLocalError` instead of the actual error.
**Impact:** The real error is hidden behind a confusing `UnboundLocalError`. Debugging is much harder.
**Blast radius:** `acquire_imagery.py` only.
**Fix approach:** Initialize `tif_paths = []` before the `try` block.

### B5. Sentinel token not refreshed during retry loop
**Consensus:** Exploratory
**Location:** `acquire_sentinel.py:357-410`
**Evidence:** OAuth2 token is obtained once before the retry loop. If a download fails and retries after backoff delays, the token may have expired (typical Copernicus token TTL is 10 minutes). Retries use the stale token, causing 401 failures.
**Impact:** Downloads that need retries after ~10 minutes all fail with 401.
**Blast radius:** `acquire_sentinel.py` only.
**Fix approach:** Check token expiry before each retry. Refresh if within 60 seconds of expiry.

### B6. Non-atomic checkpoint writes
**Consensus:** Exploratory and Multipass
**Location:** `acquire_imagery.py:352`
**Evidence:** Uses `checkpoint_path.write_text(json.dumps(done))` instead of the atomic tmp+fsync+rename pattern. A crash or SIGKILL during write corrupts the JSON, losing all download progress.
**Impact:** Partial checkpoint file on crash means entire download restarts from scratch.
**Blast radius:** `acquire_imagery.py` only. `acquire_naip.py` and `acquire_sentinel.py` use atomic patterns.
**Fix approach:** Write to `checkpoint_path.with_suffix('.tmp')`, fsync, then rename.

### B7. Sentinel downloads run sequentially despite semaphore
**Consensus:** Multipass
**Location:** `acquire_sentinel.py:532-552`
**Evidence:** Sequential `for` loop with `await download_scene()` inside. The concurrency semaphore exists but has no effect because tasks are never concurrent — they're awaited one by one.
**Impact:** Download time is N× longer than it needs to be.
**Blast radius:** `acquire_sentinel.py` only.
**Fix approach:** Use `asyncio.gather` with semaphore, similar to `acquire_imagery.py`'s download pattern.

### B8. Double subtraction of failures in M2M polling remaining count
**Consensus:** Exploratory and Multipass
**Location:** `acquire_imagery.py:771,820`
**Evidence:** `requested_count` already excludes `len(failed)` (set on line ~760), but `remaining = requested_count - len(failed) - len(seen_ids)` subtracts failures again. This can cause `remaining` to go negative or reach 0 prematurely, exiting the poll loop before all downloads are ready.
**Impact:** Some downloads never get retrieved from M2M. Silently skipped.
**Blast radius:** `acquire_imagery.py` only.
**Fix approach:** Remove the double subtraction: `remaining = requested_count - len(seen_ids)`.

### B9. TNMAccess GDAL calls have no timeout
**Consensus:** Exploratory and Holistic
**Location:** `acquire_imagery.py:377-399`
**Evidence:** The three `subprocess.run` calls for gdalbuildvrt, gdal_translate, and gdaladdo have no `timeout` parameter. Unlike `acquire_naip.py` which uses `timeout=3600`. A stuck GDAL process blocks forever.
**Impact:** Compounds B1 — even without SIGTERM, a GDAL hang blocks indefinitely.
**Blast radius:** `acquire_imagery.py` only.
**Fix approach:** Add `timeout=3600` (1 hour) to all subprocess calls, consistent with `acquire_naip.py`.

### B10. M2M_POLL_INTERVAL constant is dead code
**Consensus:** Multipass
**Location:** `acquire_imagery.py:588,793`
**Evidence:** `M2M_POLL_INTERVAL = 10` is defined but actual sleep uses hardcoded `30`. Misleading for anyone reading the constant.
**Impact:** Minor — polling is slower than intended but functional.
**Blast radius:** Single file.
**Fix approach:** Use the constant instead of hardcoded value.

### B11. acquire_naip.py concurrency parameter accepted but unused
**Consensus:** Holistic and Multipass
**Location:** `acquire_naip.py:464,694`
**Evidence:** `--concurrency` CLI argument is parsed but never referenced. Downloads always run sequentially.
**Impact:** Performance — downloads take N× longer than intended.
**Blast radius:** `acquire_naip.py` only.
**Fix approach:** Use `asyncio.Semaphore(concurrency)` with `asyncio.gather` for parallel downloads.

---

## Design Decisions Requiring User Input

### D1. Monolithic VRT conversion vs incremental tile merge
**Location:** `acquire_imagery.py:366-401`
**The concern:** Building one VRT from all GeoTIFFs and converting at once creates a single gigapixel mosaic that takes hours and exceeds container memory.
**Why this needs a decision:** The fundamental conversion approach is broken for large bboxes. Two options:
**Options:**
1. **Tile-level merge**: Convert each GeoTIFF to MBTiles individually, then merge tile rows via SQLite INSERT into the output MBTiles. Much lower memory, interruptible, but more complex.
2. **Batch-level merge with append**: Convert each batch to a temp MBTiles, then append tiles to the main MBTiles via SQLite. Middle ground — works with current batch architecture.
3. **Convert once at end**: Accumulate all TIFs, build one VRT, convert once with memory-constrained GDAL. Simplest but still hits the gigapixel problem for large bboxes.
**Recommendation:** Option 2 — batch-level merge with SQLite append. Fits the existing pipelined batch architecture, keeps memory bounded, and allows the conversion to be interrupted between batches.

---

## False Positives

### FP1. aiosqlite batch commit race condition
**Flagged by:** Multipass
**Why invalid:** The commit-after-gather pattern means tiles are committed atomically per batch. If the process dies mid-batch, those tiles are lost but the checkpoint tracks which tiles succeeded — they'll be re-downloaded on retry. Not a correctness bug, just a design tradeoff for performance.

---

## Bugs Outside Primary Scope

### O1. Sentinel cancelled runs don't clean staging files
**Location:** `acquire_sentinel.py:554-570`
**Blast radius:** Disk space accumulation only, no data corruption.
**Recommendation:** Document for later.

---

## Test Gap Analysis

### B1. SIGTERM cannot stop subprocesses
**Why missed:** No tests exercise signal handling. The SIGTERM handler was tested manually during development but the interaction with `subprocess.run` blocking was never verified.
**Pitfall coverage:** New pitfall — "subprocess.run blocks signal handling"
**Catch test:** Mock subprocess.run with a long sleep, send SIGTERM, assert process terminates within 10 seconds.

### B2. MBTiles overwrite per batch
**Why missed:** Tests for M2M progress (`test_m2m_progress.py`) mock the download and conversion functions. They never test whether the output file contains tiles from ALL batches.
**Pitfall coverage:** Covered by existing pitfall #1 (mocking what should be tested) — the conversion was mocked away.
**Catch test:** Create 2 batches of test GeoTIFFs, convert each, assert output MBTiles contains tiles from both batches.

### B3. Memory-unbounded downloads
**Why missed:** Tests use small fixture files. No test simulates large file downloads.
**Pitfall coverage:** One-off — specific to streaming vs buffering choice.
**Catch test:** Mock a 100MB HTTP response, verify download doesn't exceed 1MB resident memory.

### B4. UnboundLocalError
**Why missed:** Tests don't exercise the error path where m2m_download_batched raises.
**Pitfall coverage:** Covered by pitfall #1 — tests only cover happy path.
**Catch test:** Mock m2m_download_batched to raise, verify the original exception propagates (not UnboundLocalError).

### Testing Pitfalls Updates
- Added: "subprocess.run blocks signal handlers — use Popen for interruptible processes" (generalizable)
