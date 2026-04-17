# Concurrency Review: 3-Stage NOAA Pipeline

**Date:** 2026-04-16
**Reviewer:** Claude Opus 4 (concurrency specialist)
**Scope:** `scripts/acquire_imagery.py` run_noaa() lines 1742-2277, `scripts/rasterio_ops.py`
**Pipeline:** 8 async downloaders -> 4 ThreadPoolExecutor reproject workers -> 1 serial merger

---

## ISSUE 1: Default executor contention with reproject_pool (PERFORMANCE / POTENTIAL DEADLOCK)

**File:** `acquire_imagery.py:2153`
**Scenario:** The merger runs `_merge_tile` via `loop.run_in_executor(None, ...)` which uses the asyncio **default** `ThreadPoolExecutor`. The reprojector runs `_reproject_tile` via `loop.run_in_executor(reproject_pool, ...)` using the **named** pool. These are separate pools, so no direct contention there.

However, the default executor has a default max_workers of `min(32, os.cpu_count() + 4)`. On a Pi 5 (4 cores), that is 8 threads. The _merger is supposed to be serial (1 writer), but nothing prevents **multiple** `_merge_tile` calls from being in-flight simultaneously. Here is how:

1. Merger awaits `loop.run_in_executor(None, _merge_tile, ...)` at line 2153.
2. While that future is running in a thread, the event loop is free.
3. But `_merger()` is a simple `while True` loop that `await`s `merge_queue.get()` then `await`s the executor. Because `await` on the executor suspends the coroutine until the thread completes, the merger **does** process items sequentially. This is actually safe.

**Verdict:** NOT a bug. The `await` on `run_in_executor` blocks the coroutine, ensuring serial execution. The default executor is fine for one-at-a-time merge tasks.

**Severity:** N/A (false alarm on initial analysis, confirmed safe)

---

## ISSUE 2: SQLite concurrent writes from merger + checkpoint (DATA CORRUPTION RISK)

**File:** `acquire_imagery.py:2153-2174`
**Scenario:** After `_merge_tile` completes (which opens its own SQLite connection to `output` inside `convert_batch_to_mbtiles` -> `merge_mbtiles`), the merger writes a checkpoint at lines 2165-2174 using a **separate** `stdlib_sqlite3.connect(str(output))` call. These are sequential within `_merger`, so they do not overlap.

However, `_merge_tile` itself at lines 2036-2041 opens **yet another** connection to run `PRAGMA wal_checkpoint(TRUNCATE)`:
```python
with _sql.connect(str(output)) as _c:
    _c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
```

And `merge_mbtiles` at line 622 opens another connection:
```python
dst = sqlite3.connect(str(dst_path))
```

These are all in the same thread (default executor thread) and sequential within `_merge_tile`, so they are safe against each other.

**But**: The checkpoint at lines 2165-2174 runs in the **async event loop thread** (after `await` returns from `run_in_executor`), while a new `_merge_tile` could theoretically be dispatched. Since the merger is serial (see Issue 1), this is safe.

**Real risk:** The `_update_mbtiles_bounds` call at line 2206 and the `sqlite3.connect` at line 2211 in Phase 5 run **after** `asyncio.gather` completes, so the pipeline is done. Safe.

**Verdict:** Sequential access confirmed. NOT a bug for the pipeline itself.

**But note:** `update_progress` -> `write_pipeline_state` -> reads/writes `.pipeline-state.json` from the filesystem. This is called from the event loop thread by `_write_progress()`, which is called from `_downloader` (event loop), `_reprojector` (event loop, after `await`ing thread futures), and `_merger` (event loop). All these are in the same event loop thread, so filesystem access is sequential. Safe.

**Severity:** N/A (confirmed safe)

---

## ISSUE 3: tiles_done read outside counter_lock in _merger (COSMETIC / TOCTOU)

**File:** `acquire_imagery.py:2161-2162`
```python
log.info("[%d/%d] Tile %s done (%d/%d complete)",
         idx + 1, total_tiles, tile_fname,
         tiles_done, total_tiles)
```

This reads `tiles_done` **outside** the `counter_lock` context manager (the lock was released at line 2159). Since `tiles_done` is only ever modified by `_merger` itself (and the merger is serial), this is actually safe -- no other writer.

**Verdict:** Safe because `tiles_done` is only written by `_merger`, which is serial. The lock at line 2158 is technically unnecessary for `tiles_done` (but is needed for `tiles_failed` if we wanted cross-stage reads).

**Severity:** N/A

---

## ISSUE 4: _write_progress() can observe tiles_reprojected > tiles_downloaded (COSMETIC BUG)

**File:** `acquire_imagery.py:1923-1953`
**Scenario:** `_write_progress()` takes a snapshot of counters under `counter_lock`:
```python
def _write_progress():
    with counter_lock:
        dl = tiles_downloaded
        rp = tiles_reprojected
        done = tiles_done
        dl_done = downloads_finished
```

The concern is whether `rp > dl` can ever be observed. Let's trace the counter updates:
- `tiles_downloaded` is incremented at lines 2059 and 2069 under `counter_lock`.
- `tiles_reprojected` is incremented at line 2124 under `counter_lock`.

A tile must be downloaded before it can be reprojected, so `tiles_reprojected <= tiles_downloaded` should always hold **if** counters are updated in order. Since the lock only protects individual increments (not the ordering), let's check:

1. Download completes, `tiles_downloaded` incremented (line 2059/2069).
2. Item put on `reproject_queue`.
3. Reprojector picks it up, dispatches to thread pool.
4. Thread finishes, `tiles_reprojected` incremented (line 2124).

This ordering is guaranteed because the item must flow through the queue. `tiles_reprojected` can never exceed `tiles_downloaded`.

**However**, there is a subtle case: when a download **fails** (returns `None`), the downloader still increments `tiles_downloaded` at lines 2059/2069, and then puts `(idx, dl_fname, None)` on the reproject queue. The reprojector at line 2102-2106 checks `raw_path is None` and forwards `(idx, tile_fname, None)` to the merge queue **without** incrementing `tiles_reprojected`. So `tiles_downloaded` counts failures but `tiles_reprojected` does not. This means `tiles_reprojected < tiles_downloaded` can occur, but never `tiles_reprojected > tiles_downloaded`.

**Verdict:** Counter ordering is sound. No inconsistency bug.

**Severity:** N/A

---

## ISSUE 5: Sentinel (None) race with pending reproject_queue items (POTENTIAL DEADLOCK)

**File:** `acquire_imagery.py:2077, 2092-2131`
**Scenario:** If the downloader crashes (exception in `_downloader`), it never sends the `None` sentinel to `reproject_queue`. The reprojector would block forever on `reproject_queue.get()` at the `await asyncio.wait_for(reproject_queue.get(), timeout=0.5)` call.

**Mitigation already in place:** The reprojector uses `asyncio.wait_for(..., timeout=0.5)`, so it won't block forever. But the loop condition is `while not sentinel_received or pending_futures` -- if the sentinel is never received, `sentinel_received` stays False, so the loop runs indefinitely, polling every 0.5 seconds. The reprojector becomes an infinite no-op loop.

Since `_downloader`, `_reprojector`, and `_merger` all run under `asyncio.gather` at line 2188, if `_downloader` raises an exception, `asyncio.gather` will propagate that exception and cancel the other tasks. **But** `asyncio.gather` with default `return_exceptions=False` will cancel the sibling tasks by cancelling their coroutines. The reprojector sitting in `await asyncio.wait_for(...)` will receive a `CancelledError`, which will propagate and terminate it.

**BUT**: The `_merger` is also under `asyncio.gather`. If the reprojector is cancelled before it sends its `None` sentinel to `merge_queue`, the merger will block on `merge_queue.get()` forever. The merger does NOT use a timeout -- it's a bare `await merge_queue.get()` at line 2137. The `CancelledError` from `asyncio.gather` should also cancel it.

**Verdict:** If `_downloader` raises an exception, `asyncio.gather` cancels all coroutines via `CancelledError`. The sentinels are not needed for crash recovery -- `CancelledError` handles it. **However**, if the downloader catches its own exception internally and returns normally without sending the sentinel (a code bug), then the reprojector loops forever. Currently the downloader has no try/except around the main loop, so an unhandled exception will propagate to gather correctly.

**Severity:** Low. The current design relies on `asyncio.gather`'s cancellation semantics, which are correct. The 0.5s timeout in the reprojector is a nice defense-in-depth but doesn't fully solve the missing-sentinel case (it just avoids a hard deadlock by spinning).

**Recommendation:** Add a `try/finally` in `_downloader` to always send the sentinel:
```python
async def _downloader():
    try:
        # ... existing code ...
    finally:
        with counter_lock:
            downloads_finished = True
        await reproject_queue.put(None)
```
Similarly, add `try/finally` in `_reprojector` to always send the merge_queue sentinel.

---

## ISSUE 6: _cancel_requested is a bare global without memory barrier (RACE CONDITION - LOW RISK)

**File:** `acquire_imagery.py:164, 177, 1961, 1988, 2049, 2065, 2102, 2142`
**Scenario:** `_cancel_requested` is set by the SIGTERM handler (which runs in the main thread) and read by:
- Event loop coroutines (main thread) -- safe, same thread.
- `_reproject_tile` running in `reproject_pool` threads (lines 1988) via `cancel_check=lambda: _cancel_requested`.

In CPython, reading a `bool` global is atomic due to the GIL. The SIGTERM handler sets it in the main thread, and the GIL ensures the reproject thread will see the updated value on its next GIL acquisition. This is **practically safe** in CPython but not guaranteed by the Python language specification. A `threading.Event` would be more correct.

**Verdict:** Works in CPython due to GIL. Would break under a GIL-free Python (PEP 703, free-threaded Python 3.13+).

**Severity:** Low (CPython-safe today, future-proofing concern).

**Recommendation:** Replace `_cancel_requested` with `threading.Event` for correctness:
```python
_cancel_event = threading.Event()
# In signal handler: _cancel_event.set()
# In checks: _cancel_event.is_set()
```

---

## ISSUE 7: reproject_to_mercator num_threads oversubscription (PERFORMANCE / RESOURCE STARVATION)

**File:** `rasterio_ops.py:244`
```python
num_threads=os.cpu_count() or 2,
```

Each `reproject()` call spawns `os.cpu_count()` GDAL internal threads (4 on Pi 5). With `REPROJECT_WORKERS=min(cpu_count, 6, total_tiles)` = 4 workers, that means 4 * 4 = **16 concurrent threads** fighting over 4 CPU cores, plus the event loop thread, plus the default executor thread for merging. This is 18+ threads on 4 cores.

The merger's `convert_batch_to_mbtiles` -> `merge_to_mbtiles` also does CPU-intensive raster operations (`rasterio_merge`, `_rasterize_to_disk`) in the default executor, competing for CPU with the reproject workers.

**Scenario:** On a Pi 5 with 16 GB RAM, this oversubscription causes:
1. Heavy context switching overhead.
2. L2 cache thrashing between threads.
3. Memory pressure: each reproject holds ~1 GB (486 MB source + ~500 MB destination) * 4 workers = ~4 GB, plus merge holding ~1.5 GB = **5.5 GB concurrent raster data**.

**Severity:** Medium (performance degradation, potential OOM on smaller datasets with more tiles).

**Recommendation:** Set `num_threads=1` or `num_threads=2` in `reproject_to_mercator` when called from the pipeline, since the ThreadPoolExecutor already provides parallelism:
```python
def reproject_to_mercator(src_path, dst_path, ..., num_threads=None):
    ...
    reproject(..., num_threads=num_threads or (os.cpu_count() or 2))
```
And call with `num_threads=1` from the pipeline's `_reproject_tile`.

---

## ISSUE 8: merge_mbtiles ATTACH DATABASE not thread-safe for concurrent callers (LATENT BUG)

**File:** `acquire_imagery.py:610-676`
**Scenario:** `merge_mbtiles` uses `ATTACH DATABASE ? AS src` with a hardcoded alias `src`. If two threads were to call `merge_mbtiles` on the same output database simultaneously, they would conflict on the `src` alias. Currently this cannot happen because the merger is serial (Issue 1 confirmed), but this is a latent fragility.

More importantly, `merge_mbtiles` opens a new `sqlite3.connect(str(dst_path))` each time (line 622). SQLite in WAL mode allows concurrent readers but only one writer at a time. If `_merge_tile`'s WAL checkpoint (line 2038-2039) is running when the **next** merge starts, the `sqlite3.connect` would block on the WAL lock. Since the merger is serial, this cannot happen within the pipeline. But Phase 5 code (`_update_mbtiles_bounds`, metadata writes at line 2211) runs after the pipeline, so no conflict.

**Verdict:** Safe due to serial execution. Latent fragility if someone later parallelizes the merger.

**Severity:** Low (latent, not triggerable today).

---

## ISSUE 9: Temporary file collision in staging directory (DATA CORRUPTION)

**File:** `acquire_imagery.py:1981`
```python
warped_path = staging / f"warped_{tile_fname}"
```

And line 1959:
```python
dest = staging / tile_fname
```

If `tile_filenames` contains duplicate filenames (theoretically impossible from the shapefile, but not validated), two concurrent downloads would write to the same `dest` path, corrupting each other's data.

More realistically: if the pipeline is re-run while a previous run's staging files still exist (e.g., after a crash), old `warped_*` files could interfere. The download would overwrite old raw files (fine), but if a reproject starts before the download completes a rewrite, it would read a partially-written file.

**Scenario sequence:**
1. First run crashes after downloading tile A but before reprojecting it. `staging/A.tif` exists.
2. Second run starts. Dedup check at line 2855 only checks `_noaa_checkpoint` in the output MBTiles, not staging files.
3. Download of tile A starts, begins overwriting `staging/A.tif`.
4. Meanwhile, if somehow the reproject queue had a stale reference... this can't actually happen on a fresh run.

**Verdict:** Not triggerable in practice because each run creates fresh download tasks. The staging directory may have leftover files, but they're overwritten atomically by `fetch_to_file` (which writes to the same path). However, `fetch_to_file` does NOT use atomic write-to-temp-then-rename -- it writes directly to `dest` (line 424: `with open(dest, "wb") as f`).

**Severity:** Very low (requires crash + restart + bad timing).

**Recommendation:** Use atomic writes in `fetch_to_file` (write to `.tmp` then rename) or clean staging on startup.

---

## ISSUE 10: reproject_pool.shutdown(wait=False) leaves orphaned threads (RESOURCE LEAK)

**File:** `acquire_imagery.py:2190`
```python
finally:
    reproject_pool.shutdown(wait=False)
```

After `asyncio.gather` completes (or raises), `shutdown(wait=False)` tells the pool to stop accepting new work but does NOT wait for currently-running workers to finish. If the pipeline was cancelled mid-reproject, up to 4 `_reproject_tile` threads could still be running, writing to `warped_*` files in staging, consuming CPU and memory.

These orphaned threads will:
1. Continue writing warped GeoTIFFs (wasted I/O).
2. Hold ~1 GB RAM each (up to 4 GB total).
3. Potentially interfere with cleanup or the next pipeline run.
4. Eventually finish and get garbage collected, but there's no coordination.

**Severity:** Medium (resource waste on cancellation, up to 4 GB memory held by orphaned reproject threads).

**Recommendation:** Use `shutdown(wait=True, cancel_futures=True)` (Python 3.9+) or at minimum `shutdown(wait=True)` with a timeout. The `_cancel_requested` check inside `_reproject_tile` should cause threads to exit relatively quickly (they check between bands), but a 486 MB single-band reproject could take 30+ seconds to reach the cancellation check.

```python
finally:
    reproject_pool.shutdown(wait=True, cancel_futures=True)
```

---

## ISSUE 11: convert_batch_to_mbtiles temp file cleanup in finally block (LATENT BUG)

**File:** `acquire_imagery.py:849-850`
```python
finally:
    temp_path = tif_paths[0].parent / f"{batch_label}.mbtiles"
    temp_path.unlink(missing_ok=True)
```

The `finally` block reconstructs `temp_path` from `tif_paths[0].parent / f"{batch_label}.mbtiles"`. But at line 829, `temp_mbtiles = workdir / f"{batch_label}.mbtiles"` where `workdir = tif_paths[0].parent`. These are the same path, so cleanup is correct.

However, if `merge_to_mbtiles` at line 830 creates temporary tile directories (line 343 in rasterio_ops.py: `tile_dir = output_path.parent / f".tiles_{output_path.stem}"`), those use `output_path` = `temp_mbtiles`, so the tile dir would be in `staging/.tiles_noaa_tile_N`. The `_cleanup_tile_dir` at line 387 in rasterio_ops.py should clean this up, but if `merge_to_mbtiles` throws between tile rendering and cleanup, the `.tiles_*` directory is leaked.

**Severity:** Low (disk space leak, cleaned up on next run or manual cleanup).

---

## ISSUE 12: _write_progress() filesystem write from event loop is blocking (PERFORMANCE)

**File:** `acquire_imagery.py:1923-1953`, `pipeline_progress.py:98-110`

`_write_progress()` calls `update_progress()` which calls `_generic_progress()` which does synchronous filesystem I/O (read JSON, write tmp, fsync, rename). This runs in the **event loop thread**, blocking all async operations (downloads, queue puts/gets) during the write.

On the Pi 5's SATA SSD, `fsync` takes ~0.5-2ms. With progress writes after every download (line 2061, 2071), every reproject completion (line 2125), and every merge (line 2160), that's 3 writes per tile. For 100 tiles: 300 * 2ms = 600ms of event loop blockage.

**Severity:** Low-Medium (sub-second total, but adds latency to download scheduling and queue operations).

**Recommendation:** Debounce `_write_progress()` to write at most once per second, or run it via `run_in_executor`.

---

## ISSUE 13: rasterio thread safety in reproject workers (SAFE BUT WORTH DOCUMENTING)

**File:** `rasterio_ops.py:210-245`

Rasterio uses GDAL internally, which has its own thread-safety model. Key facts:
- GDAL dataset handles are NOT thread-safe (cannot share a dataset between threads).
- Creating new datasets in separate threads is safe (each thread gets its own handle).
- `rasterio.open()` creates a new GDAL dataset handle per call.

In the pipeline, each `_reproject_tile` call in a separate thread opens its own source and destination files. No dataset handles are shared. This is correct.

However, GDAL's `CPLError` state is **thread-local** only since GDAL 2.x with `GDAL_USE_THREAD_LOCAL_ERROR=YES`. Rasterio's bundled GDAL should have this enabled by default. If not, error messages from one thread could leak into another's error state.

**Verdict:** Safe with modern rasterio/GDAL. No action needed.

**Severity:** N/A

---

## ISSUE 14: Queue maxsize backpressure can stall the downloader (DESIGN CONCERN, NOT BUG)

**File:** `acquire_imagery.py:1915-1916`
```python
reproject_queue = asyncio.Queue(maxsize=DOWNLOAD_CONCURRENCY + REPROJECT_WORKERS)
merge_queue = asyncio.Queue(maxsize=REPROJECT_WORKERS)
```

With `DOWNLOAD_CONCURRENCY=8` and `REPROJECT_WORKERS=4`:
- `reproject_queue` maxsize = 12
- `merge_queue` maxsize = 4

If reprojection is slow (as it is -- 486 MB GeoTIFFs take 30-60s each), and download is fast, the `reproject_queue` fills to 12 items. The downloader then blocks at `await reproject_queue.put(...)` (line 2062, 2072). This is **correct** backpressure behavior -- it prevents downloading more files than can be processed, saving disk space.

However, there's a subtle interaction: while the downloader is blocked on `reproject_queue.put()`, it holds the `download_sem` (no, actually, `download_sem` is released after the download completes because it's used in `_download_tile` only). The downloader creates tasks upfront and awaits them, so new downloads can still be in flight via `asyncio.ensure_future`. Let me re-check...

At line 2053, tasks are created eagerly with `asyncio.ensure_future`. At line 2057, when `len(download_tasks) >= DOWNLOAD_CONCURRENCY`, the downloader awaits the oldest task. But `download_sem` limits concurrency to 8. So up to 8 downloads run concurrently. When the downloader blocks on `reproject_queue.put()`, it stops awaiting completed tasks, meaning it stops creating new download tasks. But previously-created tasks that are already running will complete and their results will be ready to be awaited.

The issue: the downloader creates tasks in a loop (line 2048-2053), and only blocks when it reaches `DOWNLOAD_CONCURRENCY` pending tasks. If the reproject queue is full, the downloader blocks at `await reproject_queue.put(...)` while holding a reference to a completed download result. The `download_sem` is released inside `_download_tile`, so the semaphore slot is freed. But the downloaded GeoTIFF sits on disk unconsumed. With 8 concurrent downloads, up to 8 * 486 MB = ~3.9 GB could be sitting in staging.

Add to that the 12 items in `reproject_queue` (but those are just references -- the files are on disk), plus 4 in `merge_queue`, plus 4 being actively reprojected... Maximum staging disk usage:

- 8 raw downloads in flight: 8 * 486 MB = 3.9 GB
- 12 raw files queued for reproject: 12 * 486 MB = 5.8 GB
- 4 being reprojected (raw + warped): 4 * (486 + ~500) MB = 3.9 GB
- 4 warped files in merge queue: 4 * 500 MB = 2.0 GB
- 1 being merged: 500 MB

Total worst case: **~16 GB** of staging files. On a 16 GB RAM system with ~657 GB SSD, this is fine for disk but risky for memory if the OS caches these files.

**Severity:** Low (correct backpressure design, disk usage is manageable).

**Recommendation:** Consider reducing `reproject_queue` maxsize to `REPROJECT_WORKERS + 2` to limit staging disk usage.

---

## ISSUE 15: No error propagation from _reproject_tile thread exceptions (SILENT FAILURE)

**File:** `acquire_imagery.py:2121`
```python
if f_future.done():
    warped = f_future.result()
```

If `_reproject_tile` raises an exception that is NOT caught by its internal try/except (lines 1995-1999), `f_future.result()` will re-raise it in the event loop thread, crashing the `_reprojector` coroutine. This would be caught by `asyncio.gather` and propagate up.

However, `_reproject_tile` has a broad `except Exception` at line 1995 that catches everything and returns `None`. So the future will always complete normally (never raise). A `None` result is forwarded to `merge_queue` and counted as a failure at line 2146. This is correct error handling.

**Verdict:** Safe. Exceptions are caught and converted to None (failure) results.

**Severity:** N/A

---

## SUMMARY TABLE

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | Default executor vs reproject_pool contention | N/A | Confirmed safe (merger is serial via await) |
| 2 | SQLite concurrent writes | N/A | Confirmed safe (all access is serial) |
| 3 | tiles_done read outside lock | N/A | Safe (single writer) |
| 4 | tiles_reprojected > tiles_downloaded | N/A | Cannot happen (queue ordering guarantees) |
| 5 | Missing sentinel on downloader crash | **Low** | asyncio.gather cancellation handles it, but add try/finally for defense-in-depth |
| 6 | _cancel_requested without memory barrier | **Low** | CPython-safe via GIL, not future-proof |
| 7 | reproject num_threads oversubscription | **Medium** | 16+ threads on 4 cores, set num_threads=1 in pipeline |
| 8 | merge_mbtiles ATTACH alias collision | **Low** | Latent, not triggerable today |
| 9 | Staging file collision | **Very Low** | Not triggerable in practice |
| 10 | reproject_pool.shutdown(wait=False) | **Medium** | Orphaned threads waste up to 4 GB RAM on cancel |
| 11 | Temp tile directory leak | **Low** | Disk space leak on exception |
| 12 | Blocking fsync in event loop | **Low-Medium** | ~600ms total blockage per 100 tiles |
| 13 | Rasterio thread safety | N/A | Safe with modern GDAL |
| 14 | Queue backpressure staging disk usage | **Low** | Up to 16 GB staging, manageable |
| 15 | Thread exception propagation | N/A | Correctly handled via try/except |

## RECOMMENDED FIXES (priority order)

### 1. reproject_pool.shutdown(wait=True, cancel_futures=True) [ISSUE 10]
One-line fix, prevents 4 GB memory waste on cancellation.

### 2. Reduce num_threads in reproject_to_mercator [ISSUE 7]
Add a `num_threads` parameter, pass `num_threads=1` from pipeline. Prevents 16-thread oversubscription on 4-core Pi 5.

### 3. Add try/finally sentinel guarantees [ISSUE 5]
Wrap `_downloader` and `_reprojector` in try/finally to always send queue sentinels. Defense-in-depth against future code changes.

### 4. Debounce _write_progress [ISSUE 12]
Rate-limit progress writes to once per second. Reduces event loop blockage.

### 5. Replace _cancel_requested with threading.Event [ISSUE 6]
Future-proofing for free-threaded Python. Low effort, high correctness.
