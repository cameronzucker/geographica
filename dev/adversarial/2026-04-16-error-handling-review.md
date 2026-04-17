# Error Handling & Resilience Review — NOAA NAIP Pipeline

**Reviewed:** 2026-04-16  
**Reviewer:** Claude Sonnet 4.6 (adversarial pass)  
**Files:** `scripts/acquire_imagery.py` (`run_noaa`, lines 1742–2280), `scripts/rasterio_ops.py` (`merge_to_mbtiles`, lines 300–397)  
**Scope:** 12+ hour long-running pipeline. Focus on corrupt state, partial files, disk exhaustion, retry gaps, queue stalls, and checkpoint safety.

---

## Summary

9 issues found. 2 are HIGH severity (data corruption / permanent pipeline hang). 4 are MEDIUM (silent data loss, incorrect resume). 3 are LOW (operational nuisance).

---

## Issue 1 — KILL mid-bulk-import leaves `.tiles_*` directories permanently orphaned

**Severity:** HIGH  
**Scenario:** The process is killed with SIGKILL (OOM killer, `kill -9`, Docker hard-stop) while `_bulk_import_tiles` is running inside `merge_to_mbtiles`. SIGTERM is handled gracefully, but SIGKILL cannot be caught.

**What happens:**
`merge_to_mbtiles` creates a per-tile staging directory at `output.parent / f".tiles_{output.stem}"` (e.g., `.tiles_imagery_noaa`) in Stage 1. Stage 2 (`_bulk_import_tiles`) reads from it and imports into the MBTiles. If the process is killed anywhere between tile render start and the `_cleanup_tile_dir` call at line 387, the directory survives on disk indefinitely.

On a large Arizona run (thousands of tiles), this directory can reach 5–15 GB. Because `_cleanup_tile_dir` is inside the `try` block's else path (not a `finally`), any unhandled exception path also bypasses cleanup. Crucially, `merge_to_mbtiles` is called once per NAIP quad (via `convert_batch_to_mbtiles` → `_merge_tile`), so each surviving `.tiles_*` directory is a separate artifact. Over a 12-hour run with 500+ quads and occasional OOM kills, orphaned directories can accumulate and fill the SSD.

**Likelihood over 12 hours:** HIGH. The Pi 5 OOM killer is already a known hazard (memory limits in docker-compose, prior OOM fixes). A SIGKILL from docker or OOM during bulk import is plausible once per run at minimum.

**Impact:** Disk exhaustion on the next run. The `.tiles_*` directory name is deterministic (`output.stem`-based), so on resume it may collide with a new render pass, importing stale tiles from the prior crash.

**Fix:**
Move `_cleanup_tile_dir(tile_dir)` into a `finally` block inside `merge_to_mbtiles`. For SIGKILL, add a startup cleanup sweep in `run_noaa` before the pipeline loop begins:

```python
# At run_noaa startup, clean up any orphaned tile dirs from prior crash
for orphan in data_dir.glob(".tiles_*"):
    if orphan.is_dir():
        log.warning("Cleaning up orphaned tile dir from prior crash: %s", orphan)
        shutil.rmtree(orphan, ignore_errors=True)
```

Also move cleanup into `finally`:
```python
# rasterio_ops.py merge_to_mbtiles — replace current cleanup placement
finally:
    _cleanup_tile_dir(tile_dir)
    for ds in datasets:
        ds.close()
```

---

## Issue 2 — Checkpoint written AFTER commit, but commit can fail silently — tiles double-imported on resume

**Severity:** HIGH  
**Scenario:** `_merger` calls `_merge_tile`, which calls `convert_batch_to_mbtiles` → `merge_to_mbtiles` → `_bulk_import_tiles`. The final `conn.commit()` in `_bulk_import_tiles` (line 542) can raise if the disk fills or the connection drops. This exception propagates up through `merge_to_mbtiles` (caught at line 395, returns `False`) → `_merge_tile` (returns `False`) → `_merger` (increments `tiles_failed`, does NOT write checkpoint).

That path is fine. But consider the partial-commit path: `_bulk_import_tiles` commits every 5000 tiles (line 539) and does a final `conn.commit()` at line 542. If the process is killed after a mid-run `conn.commit()` but before the checkpoint `INSERT` (lines 2165–2174 in `run_noaa`), the tile data is in the MBTiles but the `_noaa_checkpoint` row is absent. On resume, the tile will be re-downloaded, re-reprojected, and re-merged.

This is a correctness issue, not just a performance issue: `merge_mbtiles` uses `INSERT OR IGNORE` for non-overlapping tiles, so re-importing is safe for most tiles. However, the composite path re-runs JPEG decode/encode on edge tiles, and repeated compositing introduces generation loss on JPEG-encoded edge tiles. After N crashes and resumes, boundary tiles will be progressively more compressed.

**Likelihood over 12 hours:** MEDIUM. Partial commits happen every 5000 tiles (~every few minutes on a large run). Any SIGKILL in the window between the last intermediate commit and the checkpoint INSERT loses the checkpoint record.

**Impact:** Redundant reprocessing of already-merged tiles. Progressive JPEG quality degradation at quad boundaries after repeated crashes and resumes.

**Fix:** Write the checkpoint record in the same database transaction as the tile data. Pass the checkpoint write into `_bulk_import_tiles` or wrap checkpoint + commit atomically:

```python
# In _merger, after successful merge_ok, write checkpoint in a single
# atomic write using the same connection that committed tile data.
# The safest approach: move checkpoint insert into merge_mbtiles itself,
# keyed on the tile filename, after the final commit.
```

Alternatively, write the checkpoint inside `_bulk_import_tiles`'s own `conn.commit()` call so they're in the same transaction. The current design with a separate `sqlite3.connect` for the checkpoint is the root cause of the atomicity gap.

---

## Issue 3 — `fetch_to_file` leaves a partial file when Azure returns 429 mid-stream

**Severity:** MEDIUM  
**Scenario:** Azure Blob Storage can return HTTP 200 then close the connection mid-stream (this is distinct from returning 429 as an HTTP status). The `iter_chunked` loop at line 425 raises `aiohttp.ClientError` on connection reset. The exception handler at line 443 correctly deletes `dest` before retry. However, if Azure returns a genuine 429 as an HTTP status code (not mid-stream), the handler at line 435–439 does NOT delete the partial file — there is no partial file in that case because status is checked before streaming begins.

The actual gap: a 503 returned mid-stream (connection reset after 200, before first chunk) leaves an empty 0-byte file at `dest`. On the next attempt, `fetch_to_file` opens the file in `"wb"` mode, which truncates it correctly — so the retry is safe. The validation step `validate_file_header` correctly rejects the 0-byte file if the last retry also fails.

But: if `fetch_to_file` returns `False` after all retries and `dest` still exists (0 bytes from a connection reset on the last attempt that reached `open(dest, "wb")` before failing), then `validate_file_header` is not called (it's only called on `ok=True`). The 0-byte file persists in staging. On the next pipeline resume, `tile_filenames` is filtered by the checkpoint table — since this tile was never successfully merged, it remains in the work queue and will be downloaded again. The 0-byte staging file is silently overwritten. This is safe but wasteful.

**More dangerous case:** If `max_size` is exceeded mid-stream (line 427–432), `f.close()` is called explicitly and `dest.unlink()` removes it. But `f` was opened in a `with` block — calling `f.close()` inside the `with` block doesn't raise, but on the subsequent `with` block exit, Python calls `f.close()` again on an already-closed file object. On CPython this is a no-op, but it's an unintentional double-close.

**Likelihood over 12 hours:** MEDIUM. Azure Blob Storage does rate-limit large downloads; a 12-hour run hitting 500+ files is likely to encounter at least one 429 or mid-stream reset.

**Impact:** Mostly safe — partial files are cleaned up or overwritten. The double-close is a latent bug that could matter on non-CPython or future Python versions.

**Fix:** 
1. Use a temp file with atomic rename to guarantee atomicity: download to `dest.with_suffix(".tmp")`, rename to `dest` only on 200 + full read completion. The `except` block then only needs to clean up the `.tmp` file.
2. Remove the explicit `f.close()` in the `max_size` handler; rely on the `with` block to close cleanly after `return False`.

---

## Issue 4 — Disk full during `_rasterize_to_disk` leaves partial tile dir and blocks merger

**Severity:** MEDIUM  
**Scenario:** `_rasterize_to_disk` writes tiles one at a time with `(z_dir / f"{tms_y}.tile").write_bytes(tile_bytes)`. If the disk fills during this write, `OSError: [Errno 28] No space left on device` propagates up through `_rasterize_to_disk` → `merge_to_mbtiles` (caught at line 395, returns `False`) → `convert_batch_to_mbtiles` (returns `False`) → `_merge_tile` (returns `False`).

`_merge_tile` returns `False` to `_merger` via `run_in_executor`. `_merger` increments `tiles_failed` and logs a warning. The pipeline continues attempting to process the next quad. But the disk is still full, so every subsequent quad also fails immediately with `OSError`. The pipeline runs to "completion" with `tiles_done=0` or very low, reports error, and exits cleanly.

The partial `.tiles_*` directory from the failed quad is NOT cleaned up because `merge_to_mbtiles`'s cleanup path (`_cleanup_tile_dir` at line 387) is inside the `try` block, before the `finally`. When `_rasterize_to_disk` raises `OSError`, the exception propagates to the outer `except Exception` at line 395, bypassing the cleanup call.

Additionally, there is no disk-space preflight check before starting the pipeline. The staging directory (`cache_dir/staging`) is created but its available space is never validated.

**Likelihood over 12 hours:** MEDIUM. A 12-hour run on a Pi 5 with 657 GB available downloading NAIP for a large state (AZ = ~1200 quads × ~300 MB raw = ~360 GB) can feasibly exhaust disk, especially if temp files from prior runs are present.

**Impact:** Silent failure of all remaining tiles. Orphaned partial `.tiles_*` directories survive. On next run, if the user frees disk, orphaned dirs (Issue 1) compound the problem.

**Fix:**
1. Move `_cleanup_tile_dir` to a `finally` block (same fix as Issue 1).
2. Add a disk space preflight in `run_noaa`:
```python
import shutil
free_gb = shutil.disk_usage(data_dir).free / (1024**3)
estimated_gb = total_tiles * NOAA_TILE_SIZE_MB * 3 / 1024  # raw + warped + mbtiles
if free_gb < estimated_gb:
    log.error("Insufficient disk space: %.1f GB free, ~%.1f GB needed", free_gb, estimated_gb)
    sys.exit(1)
```
3. Catch `OSError: [Errno 28]` specifically and set a `disk_full` flag to abort the pipeline immediately instead of grinding through all remaining tiles.

---

## Issue 5 — `_reprojector` exception in `run_in_executor` future is swallowed; merger does not receive sentinel

**Severity:** MEDIUM  
**Scenario:** `_reprojector` calls `loop.run_in_executor(reproject_pool, _reproject_tile, raw_path, tile_fname)`. `_reproject_tile` has a broad `except Exception` that returns `None` on any error (lines 1995–1999). This means a reproject failure produces a `None` return value, not an exception in the future. The `_reprojector` then calls `f_future.result()` (line 2122), which returns `None` (not raises), and correctly puts `(f_idx, f_fname, None)` into `merge_queue`. `_merger` sees `warped_path is None` and increments `tiles_failed`. This path is correct.

However, there is a second scenario: if `_reproject_tile` raises an unhandled exception that escapes the `except Exception` block (e.g., `BaseException` subclasses: `KeyboardInterrupt`, `SystemExit`, or a C extension that raises something unexpected), `f_future.result()` re-raises the exception in the `_reprojector` coroutine. This unhandled exception propagates out of the `_reprojector` coroutine, which causes `asyncio.gather` to cancel the other tasks (`_downloader` and `_merger`). `_merger` is cancelled mid-item, potentially leaving `warped_path` on disk and the current tile uncommitted.

More practically: if the `ThreadPoolExecutor` is shut down while futures are pending (the `finally: reproject_pool.shutdown(wait=False)` at line 2190), outstanding futures raise `concurrent.futures.CancelledError` when awaited. This is a `BaseException` subclass that bypasses the `except Exception` in `_reproject_tile`. The `_reprojector` would then raise `CancelledError` itself, collapsing `asyncio.gather`.

**Likelihood over 12 hours:** LOW-MEDIUM. Normal operation is safe. But if the user sends SIGTERM while reprojection futures are in flight, `shutdown(wait=False)` cancels them, and the error propagation path has a race.

**Impact:** If triggered, `_merger` receives no sentinel (`None`), so `await merge_queue.get()` blocks forever (pipeline hangs, never exits). The process must be killed externally.

**Fix:** Wrap `f_future.result()` in `_reprojector` with a broad exception handler:
```python
try:
    warped = f_future.result()
except Exception as exc:
    log.error("Reproject future raised: %s", exc)
    warped = None
```
Also change `reproject_pool.shutdown(wait=False)` to `reproject_pool.shutdown(wait=True, cancel_futures=True)` (Python 3.9+) or add a timeout, to ensure futures complete or are explicitly cancelled before the sentinel is sent.

---

## Issue 6 — `merge_mbtiles` has no WAL mode set on the destination — concurrent TileServer access can corrupt

**Severity:** MEDIUM  
**Scenario:** `merge_mbtiles` (line 622) opens `dst_path` with `sqlite3.connect(str(dst_path))` without setting `PRAGMA journal_mode=WAL`. The MBTiles spec uses WAL, and `_init_mbtiles` in `rasterio_ops.py` correctly sets WAL (line 46). But if `merge_mbtiles` is the first function to open the database (e.g., fresh first-run), it inherits the default DELETE journal mode.

Even if a prior `_init_mbtiles` call set WAL, `merge_mbtiles` uses `ATTACH DATABASE` to attach the source MBTiles. The attached database (`src`) is opened without WAL. An ATTACH in WAL mode behaves differently from a direct open; SQLite documentation says the journal mode of the attached database is not inherited. A writer to the attached database while TileServer holds a read lock can deadlock.

More concretely: `merge_mbtiles` does `dst.commit()` (line 673) without ever setting WAL on `dst`. If the main connection opened `dst` in DELETE journal mode, this is a full database write lock. Any concurrent TileServer read on the same file returns `SQLITE_BUSY`. TileServer's retry behavior is not documented in this codebase.

The pipeline does unregister the MBTiles from TileServer config at startup (lines 1766–1776), which is the right mitigation. But this protection exists only if `TILESERVER_CONFIG` env var is set — if not set, TileServer may still be reading while merges happen.

**Likelihood over 12 hours:** LOW-MEDIUM. The env var guard is usually effective. But it fails silently if the env var is missing.

**Fix:** Add `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL` at the top of `merge_mbtiles`:
```python
dst = sqlite3.connect(str(dst_path))
dst.execute("PRAGMA journal_mode=WAL")
dst.execute("PRAGMA synchronous=NORMAL")
```

---

## Issue 7 — `_noaa_fetch_tile_index` uses cached shapefile without validating it is complete

**Severity:** LOW  
**Scenario:** `_noaa_fetch_tile_index` (lines 1683–1686) returns any cached `.shp` file without checking the accompanying `.shx`, `.dbf`, or `.prj` files. A crash mid-extraction (e.g., disk full during `zf.extractall`) leaves a partial `.shp` with missing sidecar files. On the next run, the cache check `if shp_files:` at line 1684 finds the partial `.shp` and returns it without re-downloading.

`filter_tiles_by_bbox` (which reads the shapefile via fiona) will then fail on the partial shapefile with a fiona/GDAL error. This is caught upstream only if `filter_tiles_by_bbox` propagates the exception rather than returning an empty list. Looking at the code, `filter_tiles_by_bbox` is called at line 1843 with no exception handler — an exception would propagate to the `async with aiohttp.ClientSession()` block and crash the pipeline with a traceback rather than a clean error message.

**Likelihood over 12 hours:** LOW. Only fails if a prior run crashed during tile index extraction specifically.

**Impact:** Confusing crash on resume: "fiona error reading shapefile" instead of "re-downloading tile index."

**Fix:** Validate that all four required sidecar files exist before returning the cached path:
```python
shp_path = shp_files[0]
stem = shp_path.stem
required = [shp_path.with_suffix(s) for s in (".shp", ".shx", ".dbf")]
if all(p.exists() and p.stat().st_size > 0 for p in required):
    return shp_path
# Partial extraction — clean and re-download
for f in cache_dir.glob(f"{stem}.*"):
    f.unlink(missing_ok=True)
```

---

## Issue 8 — `convert_batch_to_mbtiles` does not clean up `temp_mbtiles` on exception in `merge_mbtiles`

**Severity:** LOW  
**Scenario:** `convert_batch_to_mbtiles` (line 826) creates `temp_mbtiles = workdir / f"{batch_label}.mbtiles"`. It calls `merge_mbtiles(temp_mbtiles, output)` (line 841). If `merge_mbtiles` raises an exception (e.g., `sqlite3.OperationalError` from a corrupt source, which is not caught inside `merge_mbtiles`), the exception propagates to `convert_batch_to_mbtiles`'s `except Exception` at line 845. The `finally` block at line 848 correctly deletes `temp_path`.

Wait — looking again: the `finally` block computes `temp_path = tif_paths[0].parent / f"{batch_label}.mbtiles"`. This is the same as `temp_mbtiles`. So the `finally` does clean up. The issue is that `temp_path` is computed again in the `finally` (it's not the same variable as `temp_mbtiles`), but it resolves to the same file. This is safe but fragile — if `workdir` (from `tif_paths[0].parent`) differs from what `temp_mbtiles` was computed from, the finally may miss the file.

In `_merge_tile` (called from `_merger`), `convert_batch_to_mbtiles` is passed `[warped_path]`. `tif_paths[0].parent` is `staging`. `workdir` is `staging`. `temp_mbtiles` is `staging / f"noaa_tile_{idx}.mbtiles"`. The `finally` `temp_path` is also `staging / f"noaa_tile_{idx}.mbtiles"`. They match. Safe.

But if `batch_label` in the `finally` is derived differently than `temp_mbtiles` was (since it recomputes from the argument), and if someone refactors `convert_batch_to_mbtiles` to use a different directory for `temp_mbtiles`, the cleanup would silently fail. This is a latent maintenance hazard.

**Likelihood over 12 hours:** LOW. Currently safe. Future refactor risk.

**Fix:** Use a single variable for the temp path and reference it in `finally`:
```python
temp_mbtiles = workdir / f"{batch_label}.mbtiles"
try:
    ...
finally:
    temp_mbtiles.unlink(missing_ok=True)
```

---

## Issue 9 — WAL checkpoint in `_merge_tile` opens a second connection while `_merger` connection may still be active

**Severity:** LOW  
**Scenario:** `_merge_tile` (lines 2036–2041) opens a fresh `sqlite3.connect(str(output))` to run `PRAGMA wal_checkpoint(TRUNCATE)`. This happens inside `run_in_executor(None, ...)` (the default thread pool), meaning it runs in a worker thread. Meanwhile, `_merger` itself may be calling `merge_queue.get()` or starting the next `run_in_executor` call.

`_merger` is serialized (one item at a time via `await run_in_executor`), so no two `_merge_tile` calls run concurrently. The separate connection for the WAL checkpoint is opened after `merge_mbtiles` returns (which closes its own connection). So there's no connection overlap in normal operation.

However, `PRAGMA wal_checkpoint(TRUNCATE)` blocks until all readers have finished. If TileServer is reading the MBTiles (because `TILESERVER_CONFIG` env var was not set and TileServer wasn't deregistered), the checkpoint call will block indefinitely inside the thread pool. This blocks the `_merge_tile` future, which blocks `_merger`, which blocks `merge_queue.get()`, which means `_reprojector` eventually fills `merge_queue` (maxsize=REPROJECT_WORKERS) and blocks, which means `reproject_queue` fills (maxsize=DOWNLOAD_CONCURRENCY+REPROJECT_WORKERS) and blocks, which means `_downloader` blocks on `reproject_queue.put`. The pipeline stalls completely with no timeout.

**Likelihood over 12 hours:** LOW. Requires TileServer to be actively reading the file while the checkpoint runs. The deregister logic at startup usually prevents this. The WAL checkpoint is also non-blocking (TRUNCATE mode returns immediately if it can't truncate). Actually, `wal_checkpoint(TRUNCATE)` does return immediately with a busy count rather than blocking — SQLite documentation says it's non-blocking. So the stall scenario is less likely than described, but the second-connection pattern remains a code smell.

**Impact:** If WAL checkpoint does block (e.g., reader doesn't release read lock promptly), full pipeline stall.

**Fix:** Add a timeout to the WAL checkpoint connection and use `PASSIVE` mode (never blocks) instead of `TRUNCATE`:
```python
with _sql.connect(str(output), timeout=5.0) as _c:
    _c.execute("PRAGMA wal_checkpoint(PASSIVE)")
```

---

## Summary Table

| # | Issue | Severity | Likelihood | Impact |
|---|-------|----------|------------|--------|
| 1 | `.tiles_*` dirs not cleaned on SIGKILL | HIGH | HIGH | Disk exhaustion, stale tile import on resume |
| 2 | Checkpoint written after commit — atomicity gap | HIGH | MEDIUM | JPEG quality degradation at quad boundaries |
| 3 | `fetch_to_file` double-close on max_size exceeded | MEDIUM | MEDIUM | Latent Python compatibility bug |
| 4 | Disk full during `_rasterize_to_disk` orphans temp dir | MEDIUM | MEDIUM | Silent failure of all remaining tiles |
| 5 | `BaseException` in reproject future blocks merger forever | MEDIUM | LOW-MED | Pipeline hang requiring external kill |
| 6 | `merge_mbtiles` missing WAL pragma | MEDIUM | LOW-MED | SQLITE_BUSY under concurrent TileServer reads |
| 7 | Cached partial shapefile used without validation | LOW | LOW | Confusing crash on resume |
| 8 | `convert_batch_to_mbtiles` temp path recomputed in finally | LOW | LOW | Latent cleanup miss on refactor |
| 9 | WAL checkpoint on separate connection can block pipeline | LOW | LOW | Full pipeline stall |

---

## Recommended Fix Priority

1. **Issue 1** (orphaned `.tiles_*` dirs) + **Issue 4** (disk full cleanup): Both solved by moving `_cleanup_tile_dir` into a `finally` block in `rasterio_ops.py`. Add startup sweep in `run_noaa`. One-line fix with high impact.

2. **Issue 2** (checkpoint atomicity): Move the `_noaa_checkpoint` INSERT into the same `conn.commit()` that finalizes the tile data, or write checkpoint directly inside `_bulk_import_tiles`. Prevents JPEG degradation on repeated crash/resume cycles.

3. **Issue 5** (reproject future exception propagation): Wrap `f_future.result()` in `try/except` in `_reprojector`. Prevents permanent pipeline hang.

4. **Issue 3** (fetch_to_file double-close): Use temp-file-with-rename pattern. Defensive hygiene.

5. **Issues 6–9**: Low-risk hardening pass.
