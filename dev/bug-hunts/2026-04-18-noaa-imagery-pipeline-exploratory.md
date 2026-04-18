# Bug Hunt Report — NOAA Imagery Pipeline (Exploratory)

**Date:** 2026-04-18
**Hunter:** Exploratory (depth-first)
**Scope:** `scripts/acquire_imagery.py`, `scripts/rasterio_ops.py`, siblings (`acquire_naip.py`, `acquire_sentinel.py`, `download_elevation.py`) for cross-reference.

## Exploration focus

I went deep on four threads I judged highest-risk:

1. The NOAA 3-stage pipeline (`run_noaa` phases 4+5) — complex coroutine-plus-thread-pool coordination, shared mutable state under a lock, several `finally` blocks feeding sentinels.
2. Cancellation propagation end-to-end — signal handler → global flag → check sites, including during the post-processing tail (overviews / erode / inpaint).
3. `rasterio_ops.reproject_to_mercator` and `_read_tile_from_array` — the new in-process replacements for GDAL CLI, which are where silent data corruption would hide.
4. Sibling scripts to check for bugs that were fixed in `acquire_imagery.py` but left un-backported in `acquire_naip.py` / `acquire_sentinel.py`.

I did not deep-dive `acquire_naip.py` / `acquire_sentinel.py` / `download_elevation.py` or the M2M scene-search / download-options paths; those are lower-risk and already well-covered in prior hunts.

## Bugs

### 1. Pipeline reports `status="completed"` when cancelled during NOAA post-processing

**Location:** `scripts/acquire_imagery.py:2196-2202`, `2207-2300`
**Severity:** SIGNIFICANT

**Evidence:** The NOAA pipeline checks `_cancel_requested` after the 3-stage pipeline (line 2196) and returns early with `status="cancelled"`. But Phase 5 (overviews, erode, inpaint, final WAL checkpoint) has *no cancellation exit*. If SIGTERM arrives after Phase 4 but during Phase 5, control falls through to line 2289:

```python
update_progress(output, "noaa", args.bbox, "n/a",
                reported_done, reported_total, status="completed",
                phase="complete", ...)
```

Contributing factor: neither `rio_erode_nodata_edges` (`rasterio_ops.py:868`) nor `rio_inpaint_nodata_pixels` (`rasterio_ops.py:795`) accepts a `cancel_check` parameter. Once entered, they run to completion no matter what the SIGTERM handler sets. On a 500k-tile dataset these loops can take many minutes.

**Impact:** User clicks cancel in the admin UI. Pipeline quietly keeps running for the full post-processing tail, then writes `completed` to the state file. The search service's reconciliation logic (`services/search/main.py:1511`) then triggers the TileServer restart as if the run finished cleanly. The user's cancel was effectively ignored and the UI receives a misleading "completed" notification.

**Suggested fix:** After each of `_run_gdaladdo_with_metadata_fixup`, `rio_erode_nodata_edges`, `rio_inpaint_nodata_pixels`, re-check `_cancel_requested` and return with `status="cancelled"`. Also thread `cancel_check=lambda: _cancel_requested` into `erode_nodata_edges` / `inpaint_nodata_pixels` and have them break out of their tile loops (not the current run-to-completion loops). A final guard at line 2281 before the `completed` branch would cover the tail.

---

### 2. M2M pipeline reports `status="completed"` when cancelled during overview build

**Location:** `scripts/acquire_imagery.py:1586-1648`
**Severity:** SIGNIFICANT

**Evidence:** In `run_m2m`, the only post-download cancel check is at line 1586 (before the final conversion pass). Overview generation at line 1636-1643 catches `CalledProcessError`/`TimeoutExpired` and just logs a warning:

```python
try:
    run_gdal_subprocess(
        ["gdaladdo", "-r", "average", str(output), "2", "4", "8", "16"],
        timeout=3600,
        cancel_check=lambda: _cancel_requested,
    )
except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
    log.warning("Overview generation failed: %s -- output is still usable", exc)
```

If SIGTERM arrives during `gdaladdo`, `run_gdal_subprocess`'s signal handler kills the child (see `_handle_sigterm` → `os.killpg`). `proc.communicate` returns with non-zero returncode, raising `CalledProcessError`. The `except` catches and just warns. Execution falls through to line 1645 and reports `completed`.

**Impact:** Same user-facing symptom as Bug 1 — cancel click is silently ignored for this mode. M2M runs are typically shorter than NOAA runs, so the window is smaller, but the state-file lie is the same and the TileServer-restart side effect is still triggered.

**Suggested fix:** Re-check `if _cancel_requested: update_progress(status="cancelled"); return` immediately after the overview try/except, before the final completed update at line 1645.

---

### 3. `reproject_to_mercator` leaves partial output on cancellation

**Location:** `scripts/rasterio_ops.py:194-259`
**Severity:** MINOR

**Evidence:** Inside the per-band reproject loop:

```python
with rasterio.open(str(dst_path), "w", **profile) as dst:
    for i in range(1, src.count + 1):
        if cancel_check and cancel_check():
            return False         # <-- dst has partial data from prior bands
        reproject(...)
```

The happy-path `return True` / exception path (`except Exception` at line 255) both clean up, but the mid-band cancel path just `return False`s and leaves `dst_path` on disk containing bands from before the cancel point.

**Impact:** Minimal in practice because the caller (`_reproject_tile` at `acquire_imagery.py:1988`) unlinks `warped_path` when `success` is False. So the partial file is always cleaned up by the caller. This is defensive-programming brittleness, not a field-visible bug. Keeping it because a future caller could miss the cleanup contract.

**Suggested fix:** Add a single cleanup helper on the early-return path:

```python
if cancel_check and cancel_check():
    dst_path.unlink(missing_ok=True)
    return False
```

---

### 4. `_read_tile_from_array` writes data at wrong pixel offset when tile is fully outside raster extent

**Location:** `scripts/rasterio_ops.py:584-650`
**Severity:** SIGNIFICANT

**Evidence:** For an edge tile whose geographic bounds project to pixel indices entirely outside the source array (e.g., `raw_row_start=100`, `raw_row_end=200`, `data.shape[1]=50`), the early-return guard at line 607 (`if full_row_span <= 0`) doesn't fire — full span is still positive. The clamp at lines 611-614 then produces `row_start=49`, `row_end=50`, and `row_end > row_start`, so the "no data" check at line 616 also passes.

Then the destination offset calculation:

```python
dst_row_start = int((row_start - raw_row_start) / full_row_span * tile_size)
# → int((49 - 100) / 100 * 256) = -130
dst_row_end   = int((row_end   - raw_row_start) / full_row_span * tile_size)
# → int((50 - 100) / 100 * 256) = -128
dst_h = max(1, dst_row_end - dst_row_start)  # 2
...
tile[:, dst_row_start:dst_row_start + dst_h, ...] = resized
# → tile[:, -130:-128, ...]   — numpy treats -130 as index 126 in a 256-wide axis
```

Numpy negative-index slicing is *legal* but wrong here: the 1 row of valid data from `data[:, 49:50, ...]` gets placed at rows 126-128 of the tile, in the middle, over a region that should be all-black (no raster coverage there).

**Impact:** Boundary tiles can acquire stray pixel data at geometrically wrong positions. The `_is_empty_tile` check at `_rasterize_to_disk` line 488 won't filter these because they have non-zero data. For NOAA NAIP tiles specifically, `_rasterize_to_disk` derives the tile loop bounds from `bounds_4326` of the raster, so in-bounds tiles are the common case; this fires mainly for tiles computed as "in bounds" via the discrete `_lonlat_to_tile` floor but fully outside after the CRS round-trip (`transform_bounds(WEB_MERCATOR, src_crs, ...)`). Probably rare but produces visible wrong-pixel artifacts at raster edges when it happens.

**Suggested fix:** Guard both ends of the clamp — if either `row_start >= data.shape[1]` or `row_end <= 0` (and symmetrically for cols), return None. Equivalently, return None when `raw_row_end <= 0` or `raw_row_start >= data.shape[1]` before any clamping.

---

### 5. `run_gdal_subprocess` has a signal race between `Popen` and `_child_pid` assignment

**Location:** `scripts/acquire_imagery.py:760-766`
**Severity:** MINOR

**Evidence:**

```python
proc = subprocess.Popen(full_cmd, ..., preexec_fn=os.setsid)
_child_pid = proc.pid       # <-- window 1
try:
    stdout, stderr = proc.communicate(timeout=timeout)
```

If SIGTERM arrives between the Popen return and the `_child_pid = proc.pid` assignment, `_handle_sigterm` reads the stale (None or prior) `_child_pid` and its `if _child_pid:` guard skips the killpg. The subprocess then runs to completion, swallowing the cancel signal until it finishes naturally. Same race exists at line 771/773 where `_child_pid = None` is set — not a problem for killing, but does leave the handler with a stale pid briefly.

**Impact:** Cancellation latency of up to the full GDAL timeout (7200s default, 3600s for overviews). Tight race, unlikely to fire in normal operation, but there's no bound on the window if the runtime pauses scheduling.

**Suggested fix:** After the `Popen` returns and `_child_pid` is set, re-check `cancel_check()`/`_cancel_requested` and issue `os.killpg(os.getpgid(proc.pid), signal.SIGTERM)` if set. Either wrap in a tiny `signal.pthread_sigmask`-style block around the Popen+assignment pair, or just do a one-shot post-assignment cancel check.

---

### 6. `acquire_naip.py` and `acquire_sentinel.py` never adopted the process-group GDAL cancellation fix

**Location:** `scripts/acquire_naip.py:413-435`, `scripts/acquire_sentinel.py:440-473`
**Severity:** SIGNIFICANT

**Evidence:** `acquire_imagery.py` grew a `run_gdal_subprocess` helper (line 732) that wraps `Popen` with `preexec_fn=os.setsid` and a signal-handler-killable process group. The sibling pipelines still use `subprocess.run(..., check=True, capture_output=True)`:

```python
# acquire_naip.py:421-425
subprocess.run(
    cmd, check=True, capture_output=True, text=True,
    env=GDAL_ENV, timeout=3600,
)
```

`subprocess.run` does not create a process group and does not install a signal-forwarding parent. When SIGTERM arrives, `_cancel_requested` is set but the main thread is blocked in `run()` until the child finishes (up to 3600s / 7200s per call). Existing pitfall in `dev/testing-pitfalls.md` describes this exact class but attributes it to a now-removed call site in `acquire_imagery.py`; the sibling scripts still carry the bug.

**Impact:** Cancel click on NAIP or Sentinel modes is ineffective until the current GDAL subprocess exits. For `gdal_translate` on a multi-county NAIP merge or Sentinel composite, this can be many minutes. The admin panel's progress bar freezes on the "cancelling" status until the GDAL call returns.

**Suggested fix:** Extract `run_gdal_subprocess` into a shared module (`scripts/gdal_subprocess.py` is referenced in the testing-pitfalls doc as a planned location) and call it from both sibling scripts.

---

### 7. `_run_gdaladdo_with_metadata_fixup` opens a SQLite connection that is never closed

**Location:** `scripts/acquire_imagery.py:799-811`
**Severity:** MINOR

**Evidence:** Unlike most `sqlite3.connect` call sites in this codebase (which use `with`), this one uses a try/finally and closes on the finally — that's correct. But compare to the pattern at line 2215, 2230, 2246, 2269, 1856, 2170, 2036: they all use `with sqlite3.connect(...) as conn:`. Python's `sqlite3.Connection.__exit__` only commits or rolls back — it does **not** close the connection. The connection is only closed when the reference is freed (CPython refcount drops to 0 when the local goes out of scope).

For most call sites this is harmless — the local goes out of scope immediately. But the per-tile sites in the hot path (line 2036 inside `_merge_tile`, called once per NAIP quad; line 2170 inside `_merger`, also per-quad) open a fresh connection each iteration. In CPython's ref-count regime they're closed promptly, but:

- Under the 494-quad stress test, that's ~988 connection open/close cycles. Each briefly holds a -shm / -wal file handle, contributing to TileServer-vs-pipeline file lock contention.
- If a future change holds a reference (e.g., returns the connection from a helper), the leak becomes real.
- `PRAGMA journal_mode=WAL` is set in `build_overviews` then never reset on failure paths, and these short-lived connections don't explicitly set a journal mode — so the file's current mode is inherited silently.

**Impact:** Not a correctness bug in current CPython (GC catches it), but fragile idiom. Flagging so future reviewers don't re-examine it.

**Suggested fix:** Either switch to the explicit `conn = sqlite3.connect(...); try: ... finally: conn.close()` pattern, or wrap in a `contextlib.closing()` helper that actually closes on exit. No change needed to behavior today.

---

### 8. `filter_tiles_by_bbox` CLI fallback (acquire_imagery.py) fails silently with malformed CSV

**Location:** `scripts/acquire_imagery.py:107-138`
**Severity:** MINOR

**Evidence:** The `ogr2ogr` CSV output parsing at line 128-137 assumes the first line is a header and strips every filename with `.strip('"')`. But:

```python
lines = result.stdout.strip().split("\n")
if len(lines) <= 1:
    return []
# With -select filename, output is: "filename\nfile1.tif\nfile2.tif\n..."
```

If `ogr2ogr` outputs a CR-terminated CSV (Windows line endings on some GDAL builds) or embeds a newline in a filename field (rare but legal CSV), the parser silently mis-parses. More concerning: if `ogr2ogr` logs a warning to stdout (which some GDAL builds do for CRS mismatches), that warning becomes a "filename" and fails the `.endswith(".tif")` test — but silently, no log.

Note the Python-native version in `rasterio_ops.py:122-171` is preferred and avoids this entirely; I mention this CLI-path for completeness because `run_noaa` imports `filter_tiles_by_bbox` from `acquire_imagery.py` (line 1841) not from `rasterio_ops.py`. That's the wrong import — two implementations exist with different names and the ogr2ogr-based one is what the NOAA pipeline actually uses.

**Impact:** Correctly-formed shapefiles parse fine. The field-reported NOAA bug `False blob validation via HEAD on virtual directory paths` in testing-pitfalls suggests this path is exercised on real NOAA data without issue — but a GDAL warning-to-stdout would produce zero matching tiles with no error. The pipeline would then report "No NOAA tiles intersect bbox" and exit.

**Suggested fix:** Switch the NOAA import at line 1841 to use `rasterio_ops.filter_tiles_by_bbox`, which uses fiona/pyshp directly and doesn't parse CLI CSV. The two-implementation split is already a known smell; consolidating on the Python one removes the CLI risk entirely.

---

### 9. Per-quad `_rasterize_to_disk` work is discarded by `build_overviews`

**Location:** `scripts/rasterio_ops.py:693-700`, interaction with `merge_to_mbtiles` at `rasterio_ops.py:304-413`
**Severity:** MINOR (performance, not correctness — but wasted work is worth flagging)

**Evidence:** For each NAIP quad, `convert_batch_to_mbtiles` → `merge_to_mbtiles` → `_rasterize_to_disk` renders tiles from `min_zoom = max_zoom - 4` up through `max_zoom` (typically zooms 13-17 for 1m NAIP). These tiles are all inserted into the MBTiles.

Then at the end of the pipeline, `build_overviews` is called:

```python
max_zoom = row[0]
deleted = conn.execute(
    "DELETE FROM tiles WHERE zoom_level < ?", (max_zoom,)
).rowcount
...
```

This deletes *every* non-max-zoom tile — including the zoom 13-16 tiles that were just rendered per-quad. Those tiles are then rebuilt from the max-zoom tiles via 2x2 averaging in the subsequent loop. The per-quad rendering at min_zoom..max_zoom-1 is entirely wasted.

**Impact:** Not incorrect output — the final MBTiles has correct overviews. But `_rasterize_to_disk` is doing roughly 4× more work than needed per quad. On a 494-quad run, that's measurable cumulative time. Also contributes to SQLite WAL bloat during the run.

**Suggested fix:** Pass `max_zoom_only=True` (or `zoom_range=(max_zoom, max_zoom)`) through `merge_to_mbtiles` when it's being called from the NOAA pipeline. Or have `_compute_zoom_range` return `(max_zoom, max_zoom)` for the NOAA code path and let `build_overviews` generate all overview levels.

---

## Design Concerns (not bugs)

### Final status computed from `tiles_done` alone loses context

`run_noaa` at line 2281 decides between "error" and "completed" based on `tiles_done == 0 and not skip_to_postprocess`. If 1 tile succeeds out of 500, the pipeline reports "completed" with that one tile. `tiles_failed` is logged but not used in the status decision. A partial-failure state (e.g., "completed_partial" or a failure threshold check) would better match what the user sees in the tile output.

### `_noaa_checkpoint` entries survive `erode_nodata_edges`

The checkpoint table records "this quad was merged" but gets no update when `erode_nodata_edges` deletes tiles belonging to that quad. On a subsequent run with an extended bbox, quads that were eroded are skipped (still in the checkpoint). If the user's intent with a re-run was to include those eroded areas, the output silently has gaps.

### TileServer is not unregistered during the run

Comment at line 1772-1777 notes that TileServer management moved to the search service. But TileServer likely keeps the MBTiles open for read during the whole run. That means the final `PRAGMA journal_mode=DELETE` at line 2275 can fail (SQLite requires no other connections to switch out of WAL). The `except Exception: log.warning` at line 2277 swallows this silently, leaving the file in WAL mode with whatever WAL size the pipeline ended with. The search service's follow-up attempt at `services/search/main.py:1526-1527` might also fail for the same reason. Consider pausing TileServer reads for the duration of post-processing, or falling back to closing TileServer's connection explicitly before the journal_mode flip.

### The `download_tasks.pop(0)` FIFO in `_downloader` creates head-of-line blocking

`_downloader` pops the oldest-submitted task and awaits it, rather than awaiting whichever completes first (`asyncio.wait(FIRST_COMPLETED)`). The `download_sem` caps concurrency at 8, so this is correct, but if task 0 is slow (e.g., a quad that takes 5 minutes due to server-side throttling), tasks 1-7 complete but sit waiting to be pushed to `reproject_queue`. Downstream stages starve unnecessarily. Not a bug, but it limits pipeline steady-state throughput to the slowest-in-flight download.

### Progress state file written on every tile merge, blocking on `fsync`

`update_progress` → `_generic_progress` → `_atomic_write_json` involves `f.flush(); os.fsync(f.fileno()); os.replace(...)`. This is called once per merged tile (via `_write_progress` in `_merger`). `fsync` is a blocking syscall that yields no value for the monitoring UI (which polls at seconds-scale anyway). This blocks the event loop on each merge. On a 494-quad run that's hundreds of blocking fsyncs. Batching (e.g., update every N tiles or every T seconds) would reduce event-loop stalls.

## Notes on prior-review overlap

After drafting the above I cross-checked `dev/testing-pitfalls.md`. These pitfalls are either not in the doc or are doc'd but still present:

- **New**: Bug 1 (cancel-ignored in NOAA post-processing)
- **New**: Bug 2 (cancel-ignored in M2M overview)
- **New**: Bug 4 (negative-index placement in `_read_tile_from_array`)
- **New**: Bug 5 (Popen→_child_pid race)
- **New**: Bug 9 (wasted per-quad rasterization)
- **Partially overlapping with existing pitfall**: Bug 6 — the pitfall mentions "subprocess.run blocking signal handlers" as found-and-fixed in `acquire_imagery.py:377-399` and `acquire_sentinel.py:428-451`; the NAIP script was not in that list and the Sentinel script was never actually fixed — only the `acquire_imagery.py` call sites were replaced with `run_gdal_subprocess`. Worth re-confirming.
- **New**: Bug 8 (CSV parser in ogr2ogr-based `filter_tiles_by_bbox`) — the existing pitfall "False blob validation via HEAD" is different.

Bug 3 (partial output on mid-band cancel in `reproject_to_mercator`) is adjacent to the existing "Temporary directory cleanup missing from exception paths" but not the same function.

## Proposed testing-pitfalls additions

If the fix list picks up Bug 1 / Bug 2, add:

> **Cancellation not honored in pipeline tail phases**
> When cancellation is checked only between phases of a multi-phase pipeline but not inside the final post-processing phase (overviews, cleanup, checkpoint flush), SIGTERM during post-processing produces a `completed` status rather than `cancelled`, and downstream consumers (TileServer restart, state reconciliation) behave as if the run succeeded. Tests should inject SIGTERM during every documented phase, not just the primary "doing work" phase, and assert the final state equals `cancelled`.
> *Found in:* `scripts/acquire_imagery.py:2207-2300` (NOAA Phase 5), `scripts/acquire_imagery.py:1636-1648` (M2M overviews).

If the fix list picks up Bug 4, add:

> **Negative numpy slicing masks out-of-bounds tiles as valid**
> When mapping source-raster pixel coordinates to a destination tile via `dst[:, a:a+h, b:b+w] = src`, and `a` or `b` can be negative because the tile is geographically outside the raster extent, numpy's negative-index semantics silently place data at `dst.shape - abs(a)` instead of producing an error or blank tile. Tests should feed a tile whose geographic bounds are entirely outside the source raster and assert the returned tile is None (or fully black), not a tile with a stripe of valid pixels at arbitrary positions.
> *Found in:* `scripts/rasterio_ops.py:584-650` — `_read_tile_from_array` allowed negative `dst_row_start` / `dst_col_start` through to the slice assignment.
