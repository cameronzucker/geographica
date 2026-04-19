# NOAA Imagery Pipeline Bug Hunt — Consolidated Findings

**Date:** 2026-04-18
**Scope:** `scripts/acquire_imagery.py`, `scripts/acquire_naip.py`, `scripts/acquire_sentinel.py`, `scripts/rasterio_ops.py`, `scripts/download_elevation.py` (+ `services/search/main.py` pipeline reconciliation)
**Hunters:** Exploratory (E), Holistic (H), Multipass (M)
**Total raw findings:** 49 (E: 9 bugs + 5 design; H: 15 bugs + 5 design; M: 18 bugs + 7 design + 5 null)
**After dedup:** 27 unique findings
**Final classification:** 16 confirmed bugs, 6 design decisions, 4 false positives (hunter already self-retracted), 1 out-of-scope

Consolidator note on stability context: the 494-quad production run on 2026-04-17 completed cleanly, but that run exercised only the happy path. Several of the bugs below are conditional on specific failure modes — disk full, mid-post-processing cancel, token expiry under load, partial truncation, resume after SIGTERM — none of which the clean run triggered. Don't confuse "didn't show up in production" with "not real."

---

## Confirmed Bugs

### B1. Cancellation ignored during NOAA post-processing (Phase 5) — pipeline reports `completed` instead of `cancelled`
**Consensus:** 1/3 (Exploratory only; consolidator confirmed against code)
**Location:** `scripts/acquire_imagery.py:2196-2300`
**Evidence:** `run_noaa` checks `_cancel_requested` after the 3-stage pipeline at line 2196 and early-returns with `status="cancelled"`. After that point — lines 2207 onward — `_run_gdaladdo_with_metadata_fixup`, `rio_erode_nodata_edges`, `rio_inpaint_nodata_pixels`, and the final WAL-checkpoint block all run unconditionally. None of those functions check `_cancel_requested` between operations, and neither `erode_nodata_edges` nor `inpaint_nodata_pixels` accepts a `cancel_check` parameter. Control falls through to line 2289, which writes `status="completed"` regardless. On a 500k-tile NAIP output, the post-processing tail can run for 30+ minutes.
**Impact:** User clicks cancel during post-processing; the pipeline runs to "completion" and the search service's reconciliation path at `services/search/main.py:1511` then WAL-checkpoints and restarts TileServer as if the run succeeded. User-visible: cancel appears ignored, followed by a misleading "completed" notification.
**Blast radius:** Localized to `run_noaa` phase 5. Fix requires:
 - Adding `cancel_check` parameter to `erode_nodata_edges` / `inpaint_nodata_pixels` and checking it between the inner loop iterations.
 - Adding `if _cancel_requested: return` guards after `_run_gdaladdo_with_metadata_fixup`, after erode, after inpaint, and immediately before the final status write at 2281.
 - No external callers depend on the current fire-and-forget behavior.
**Fix approach:** Add `cancel_check` param to both post-processing helpers (pass `lambda: _cancel_requested`); add 3 guard blocks at each phase 5 sub-step boundary.
**Severity:** HIGH — misleading UI, wasted CPU during cancel, TileServer restart triggered when it shouldn't be.
**Regression risk of fix:** LOW — purely additive checks; `erode_nodata_edges` and `inpaint_nodata_pixels` are the only callers.

---

### B2. Cancellation ignored during M2M overview build — pipeline reports `completed` instead of `cancelled`
**Consensus:** 1/3 (Exploratory only; consolidator confirmed)
**Location:** `scripts/acquire_imagery.py:1636-1648`
**Evidence:** In `run_m2m`, the last `_cancel_requested` check is at line 1586 before the final conversion pass. The `gdaladdo` subprocess call at 1637 passes `cancel_check=lambda: _cancel_requested`, and if SIGTERM arrives during gdaladdo, `run_gdal_subprocess` raises `CalledProcessError` after killing the child. But the except at 1642 catches and logs a warning, then execution falls through to the unconditional `status="completed"` write at 1645.
**Impact:** Same symptom as B1 for M2M mode. Smaller window (M2M overview build is typically <5 min) but the state-file lie is identical.
**Blast radius:** Local to `run_m2m`. One-line fix.
**Fix approach:** After the try/except at 1636-1643, add `if _cancel_requested: update_progress(..., status="cancelled"); return`.
**Severity:** MEDIUM — same class as B1 but shorter exposure window.
**Regression risk of fix:** LOW.

---

### B3. `reproject_to_mercator` accesses `src.width`/`src.height` after `with rasterio.open(src) as src:` block closes
**Consensus:** 1/3 (Holistic only; consolidator confirmed verbatim)
**Location:** `scripts/rasterio_ops.py:210-252`
**Evidence:** Line 210 opens `with rasterio.open(str(src_path)) as src:`. The inner `with rasterio.open(dst_path, "w", ...) as dst:` at line 232 closes at line 249. The outer `with` closes at line 249 (same dedent level). Line 250 `elapsed = time.monotonic() - t0` is dedented one level further than `with rasterio.open(...) as src:` at 210 — it sits at the `try:` level, OUTSIDE the outer `with`. Line 252 then reads `src.width` / `src.height` on a closed dataset.
Current rasterio behavior: on most versions this returns cached attribute values, so INFO-level logging doesn't break. But `log.debug(msg, *args)` evaluates `src.width` eagerly regardless of level. On a rasterio upgrade that enforces closed-dataset checks, every reproject raises inside the log, gets caught by the broad `except Exception` at line 255, and returns `False` — every tile is marked as "reproject failed."
**Impact:** Today: silent (works at INFO). Future: latent time-bomb. A rasterio upgrade or a debug-log switch changes this from a no-op to a 100% failure rate at the reproject stage, which is the hot loop of the NOAA pipeline.
**Blast radius:** Single function. Fix is trivial: capture `src.width` / `src.height` into locals before the `with` exits, or move the log statement inside the `with`.
**Fix approach:** Before closing the outer `with` at line 249, capture `src_width = src.width; src_height = src.height`, then use the locals in the log.
**Severity:** MEDIUM — latent, but a single dependency bump turns it into a catastrophic regression.
**Regression risk of fix:** LOW — purely refactoring.

---

### B4. `_read_tile_from_array` places valid pixels at wrong coordinates for tiles outside raster extent (negative-index numpy slicing)
**Consensus:** 2/3 (Exploratory + Multipass tangentially; consolidator confirmed root cause)
**Location:** `scripts/rasterio_ops.py:604-648`
**Evidence:** After `rowcol()` on an edge tile whose bounds project to pixel indices entirely outside `data.shape`, the early-return at line 607 guards `full_row_span <= 0` (positive span is common). The clamps at 611-614 may produce `row_start=49, row_end=50` when `data.shape[1]=50` and raw indices were `raw_row_start=100, raw_row_end=200`. The zero-size window check at 616 passes because `row_end > row_start`. Then:
```python
dst_row_start = int((row_start - raw_row_start) / full_row_span * tile_size)
# → int((49 - 100) / 100 * 256) = int(-130.56) = -130
```
`tile[:, -130:-128, ...] = resized` uses numpy's legal-but-wrong negative indexing: the 1 row of valid data gets placed at rows 126-128 of a 256-wide tile. The result is a tile with valid pixels stamped at geometrically wrong coordinates, and `_is_empty_tile` doesn't filter it because the stamp is non-zero.
The Multipass hunter also flagged edge-tile truncation (finding H/M15) — same region of code, different symptom. Both are real; B4 is the catastrophic one, M15 the subtle one.
**Impact:** Boundary tiles can display stray pixel data at wrong positions. Likely rare in practice — it fires when the `_lonlat_to_tile` floor says a tile is in-bounds but the CRS round-trip via `transform_bounds(WEB_MERCATOR, src_crs, ...)` puts it fully outside. Produces visible misplaced-imagery artifacts at extreme quad boundaries.
**Blast radius:** Function is called from `_rasterize_to_disk` only; fix is local.
**Fix approach:** Add out-of-bounds guard before the clamp:
```python
if raw_row_end <= 0 or raw_row_start >= data.shape[1]: return None
if raw_col_end <= 0 or raw_col_start >= data.shape[2]: return None
```
**Severity:** MEDIUM — rare but wrong-pixel artifacts are user-visible and not caught by inpaint.
**Regression risk of fix:** LOW — additional rejection criterion, can only reduce tile output.

---

### B5. Sibling pipelines (`acquire_naip.py`, `acquire_sentinel.py`) never adopted the process-group GDAL cancellation fix
**Consensus:** 1/3 (Exploratory; consolidator confirmed)
**Location:** `scripts/acquire_naip.py:421-425, 452-471, 474-481` and `scripts/acquire_sentinel.py` GDAL subprocess call sites (`acquire_sentinel.py` didn't actually ship a `run()` call in the current code — confirmed in verification below).
**Evidence:** `acquire_imagery.py` has `run_gdal_subprocess` (line 732) that uses `Popen` with `preexec_fn=os.setsid` so the SIGTERM handler can `os.killpg` the child. `acquire_naip.py:422-425, 454-460, 463-470, 474-481` still uses `subprocess.run(..., check=True, capture_output=True, timeout=...)` for all four GDAL operations (gdal_translate JP2→GTiff, gdalbuildvrt, gdal_translate VRT→MBTiles, gdaladdo). `subprocess.run` doesn't create a process group or forward signals, so SIGTERM to the parent sets `_cancel_requested` but the main thread blocks in the `run()` call for up to 7200s per operation.
Consolidator spot-check: `acquire_sentinel.py` does NOT currently use GDAL subprocesses at all — the existing testing-pitfalls entry ("subprocess.run blocking signal handlers" — *Found in:* `scripts/acquire_sentinel.py:428-451`) references line numbers that are now unrelated code (streaming download loop). The NAIP claim is real; the Sentinel claim was fixed in an earlier refactor and the pitfall doc is stale.
**Impact:** Cancel click on NAIP mode is ineffective until current GDAL subprocess exits. For a multi-county NAIP mosaic build (50+ counties), gdaladdo can run 30+ minutes.
**Blast radius:** Extract `run_gdal_subprocess` to a shared module (`scripts/gdal_subprocess.py`, referenced in testing-pitfalls) and update `acquire_naip.py` call sites. No API changes to callers.
**Fix approach:** Create shared helper; replace all 4 `subprocess.run` sites in `acquire_naip.py`.
**Severity:** MEDIUM — user-facing cancel UX, not data corruption.
**Regression risk of fix:** LOW-MEDIUM — process-group killing is behavior-different from the current blocking call; verify tests cover normal-completion path.

---

### B6. `merge_mbtiles` byte-level JPEG compare forces lossy re-composite on every overlapping tile
**Consensus:** 2/3 (Holistic H3, Multipass M16 — same bug, slightly different framing)
**Location:** `scripts/acquire_imagery.py:641-667`
**Evidence:** The `WHERE s.tile_data != d.tile_data` filter at line 647 selects overlapping tiles whose blob bytes differ. JPEG encoders are deterministic in rasterio's current build BUT two "visually identical" tiles produced by separate pipeline passes (e.g., on quad boundaries where both src and dst have real data from neighboring NAIP quads) always differ byte-for-byte because the input arrays differ at pixel level. Each such overlap enters the composite path at 651-667, which decodes both JPEGs, copies `src_arr[:, black_mask] = dst_arr[:, black_mask]` (zero pixels when dst has no near-black), then re-encodes. For interior-overlap tiles where both src and dst have full valid data, the re-encode is a wasted JPEG generation.
Cumulative on a dataset with N overlapping quads per corner: the same tile can be decode/re-encoded `N-1` times. JPEG is lossy so quality degrades each pass.
**Impact:** Progressive quality loss at NAIP quad boundaries. Matches the `docs/random_imagery_N.jpg` and `docs/flagstaff_rendering_issue.jpg` screenshots. Also a throughput hit (every quad merge re-encodes thousands of interior tiles).
**Blast radius:** Local to `merge_mbtiles`. Callers (`convert_batch_to_mbtiles`, `run_m2m`) don't need to change.
**Fix approach:** Move the "is dst near-black?" check into SQL or a fast pre-filter. Something like:
```python
# Only composite if dst has significant near-black pixels; else trust the INSERT OR IGNORE
for z, x, y, src_data, dst_data in cursor:
    with MemoryFile(dst_data) as dmf, dmf.open() as dds:
        dst_arr = dds.read()
    black_mask = np.all(dst_arr[:3] <= 20, axis=0)
    if not black_mask.any(): continue  # no work — skip the decode/encode cycle
    # ... existing composite ...
```
**Severity:** HIGH — affects every NOAA run with overlapping quads; visible quality regression; hot-path performance cost.
**Regression risk of fix:** LOW — skipping the composite on fully-valid dst matches the intended behavior (composite only fills black seams).

---

### B7. `merge_mbtiles` exception swallowing hides decode/encode errors silently
**Consensus:** 1/3 (Multipass M14; consolidator confirmed)
**Location:** `scripts/acquire_imagery.py:666-667`
**Evidence:** The composite loop catches all exceptions with bare `except Exception: pass`. No counter, no log line. MemoryError (from numpy allocation under pressure), decode errors from corrupt tiles, or encode failures are all invisible. The run reports "Composited N tiles" at line 670 but `N` equals the `composited` counter from the success branch — failures aren't counted.
**Impact:** Silent data-quality degradation. If 1% of overlap tiles fail, nobody knows; the map just shows seams.
**Blast radius:** Local. Fix is one counter + one warn log.
**Fix approach:**
```python
composited = 0
errors = 0
for z, x, y, src_data, dst_data in cursor:
    try:
        ...
        composited += 1
    except Exception as exc:
        errors += 1
        if errors <= 5:  # avoid log-spam
            log.warning("merge composite failed for %d/%d/%d: %s", z, x, y, exc)
if errors: log.warning("merge_mbtiles: %d composite errors suppressed", errors)
```
**Severity:** MEDIUM — quiet quality loss.
**Regression risk of fix:** LOW.

---

### B8. NOAA erosion runs AFTER overview generation, leaving overview tiles referencing eroded regions
**Consensus:** 1/3 (Multipass M found the order bug; Holistic H8 related but different angle)
**Location:** `scripts/acquire_imagery.py:2222-2254`
**Evidence:** The current order in `run_noaa` phase 5 is:
1. `_run_gdaladdo_with_metadata_fixup(output)` — builds overviews from current base (line 2223)
2. WAL checkpoint
3. `rio_erode_nodata_edges(output)` — deletes edge base tiles (line 2241)
4. WAL checkpoint
5. `rio_inpaint_nodata_pixels(output)` — fills remaining (line 2250)

Step 3 deletes base-zoom boundary tiles. Step 1 already built overviews from pre-erosion base, so those overviews reference imagery at regions where step 3 just deleted the base tile. Result: at low zoom (overview levels) the user sees imagery; at high zoom (base) they see basemap — exactly the artifact the `docstring` in `erode_nodata_edges` (line 886-891) says it's protecting against.
The `build_overviews` function at `rasterio_ops.py:695` also deletes-and-rebuilds overviews, so if erode runs BEFORE overviews, this is fixed automatically. Consolidator verified this.
**Impact:** User-visible "zoom-level inversion" at eroded boundaries. Matches `docs/flagstaff_rendering_issue.jpg`.
**Blast radius:** Single reordering in `run_noaa`. Swap lines 2223 (gdaladdo) and 2241 (erode).
**Fix approach:** Run erosion first, then overviews, then inpaint (or inpaint between as the current WAL checkpoint suggests).
**Severity:** HIGH — user-reported visible artifact.
**Regression risk of fix:** LOW — the current docstring explicitly expects this order; only the call-site was wrong.

---

### B9. `erode_nodata_edges` is destructive AND non-idempotent across resume runs
**Consensus:** 1/3 (Holistic H8; consolidator confirmed)
**Location:** `scripts/rasterio_ops.py:868-959`, called from `scripts/acquire_imagery.py:2241`
**Evidence:** The outer `while removed_this_round > 0` loop keeps stripping until no boundary tile violates `min_edge_fill`. On a resume run (`skip_to_postprocess=True`), phase 5 still runs erosion because it's unconditionally invoked for `tiles_done > 0 or skip_to_postprocess` (line 2207). The function sees the current MIN/MAX tile_column/tile_row bounds, evaluates them, and can remove tiles that were valid at the end of the original run because the boundary has shifted.
Worse: the deleted tiles' filenames are still in `_noaa_checkpoint`. On the next run with the same bbox, the pipeline skips them as "already processed." The only recovery is manually deleting the checkpoint table.
**Impact:** Incremental bbox-expansion runs can progressively remove valid imagery with no recovery path.
**Blast radius:** The fix needs to distinguish "first erode" from "resume erode." Options:
 - Gate erosion on `not skip_to_postprocess` (simplest; but loses erosion of new edges added in the resume run).
 - Record which tiles were erosion-deleted in a separate table; on resume, refuse to re-delete rows in `_noaa_checkpoint`.
 - Reset `_noaa_checkpoint` for eroded rows so they can be re-downloaded next time.
**Fix approach:** Simplest safe fix: only run erosion when `skip_to_postprocess=False` AND `tiles_done == total_tiles` (first completion). This matches the user intent ("clean up edges after initial build"). Document the limitation.
**Severity:** MEDIUM — rare (users rarely expand bboxes) but unrecoverable data loss when hit.
**Regression risk of fix:** LOW if gated on first-run only; MEDIUM if we preserve cross-run erosion semantics.

---

### B10. `fetch_to_file` has no truncation detection — short-read at HTTP 200 returns success on partial file
**Consensus:** 2/3 (Multipass M1 + M9 — same root cause, two symptoms)
**Location:** `scripts/acquire_imagery.py:416-455`
**Evidence:** The streaming loop at 422-434 copies chunks from `resp.content.iter_chunked(64*1024)` into `dest`. If the server sends valid HTTP 200 with a `Content-Length` header and then cleanly closes the socket mid-body, `iter_chunked` yields the truncated bytes and returns normally — no exception. `fetch_to_file` returns True. The downstream `validate_file_header(dest, "geotiff")` passes (the magic bytes are in the first N bytes), but `rasterio.open` later fails on the truncated payload.
`resp.content_length` is available (when not chunked encoding) and could be compared to `total` after the loop — but the code doesn't do this.
**Impact:** Truncated GeoTIFFs look valid to the download layer, pass header validation, and fail at the reproject stage. The reproject log says "Reproject failed for X" — user sees a tile failure with no hint it was a recoverable network problem.
**Blast radius:** Local fix in `fetch_to_file`. Callers (NOAA `_download_tile`, `download_geotiffs`) already handle `False` return correctly (retry or skip).
**Fix approach:** After the `async for chunk` loop, check:
```python
if resp.content_length and total < resp.content_length:
    log.warning("Short read: got %d/%d bytes for %s -- retrying", total, resp.content_length, url)
    dest.unlink(missing_ok=True)
    continue  # next retry iteration
return True
```
**Severity:** MEDIUM — recoverable failure becomes permanent per-tile loss.
**Regression risk of fix:** LOW — only affects truncation detection; complete downloads are unaffected.

---

### B11. `_download_tile` re-downloads existing staged files on resume — `fetch_to_file` always truncates
**Consensus:** 2/3 (Holistic H4 + Multipass M8 — same bug, two angles)
**Location:** `scripts/acquire_imagery.py:1953-1974` (NOAA `_download_tile`) + `scripts/acquire_imagery.py:416-455` (`fetch_to_file`)
**Evidence:** `fetch_to_file` opens `dest` with `"wb"` (line 424), unconditionally truncating. `_download_tile` never checks if `dest` already exists with valid content. If a previous run was SIGTERM'd between "file downloaded to staging" and "file merged into MBTiles" (which takes 30s-2min per tile), the full 486 MB of the downloaded GeoTIFF is discarded on resume and re-downloaded from NOAA.
On a resume from mid-pipeline cancel, up to `DOWNLOAD_CONCURRENCY=8` tiles can be in this "downloaded but not merged" state. At 486 MB/tile on a typical AREDN mesh upstream, that's ~15 minutes of avoidable bandwidth.
Related: `staging/warped_*.tif` from interrupted reproject runs also accumulates indefinitely with no sweep.
**Impact:** Wasted bandwidth on resume. Bigger concern on metered connections or the actual AREDN mesh deployment target than on lab testing.
**Blast radius:** Fix is in `_download_tile` (check existence + basic validation before calling `fetch_to_file`). Staging sweep could be added at pipeline start.
**Fix approach:**
```python
async def _download_tile(tile_fname):
    dest = staging / tile_fname
    if dest.exists() and dest.stat().st_size > 0 and validate_file_header(dest, "geotiff"):
        log.info("Using cached staging tile: %s (%.0f MB)",
                 tile_fname, dest.stat().st_size / (1024*1024))
        return (tile_fname, dest)
    # ... existing download logic ...
```
And a startup sweep of orphan `warped_*.tif` files.
**Severity:** MEDIUM — bandwidth waste, not data loss.
**Regression risk of fix:** LOW — `validate_file_header` is already proven in the pipeline.

---

### B12. `_merger` never calls `_write_progress()` on failure paths — UI appears stuck during partial failures
**Consensus:** 1/3 (Holistic H2; consolidator confirmed)
**Location:** `scripts/acquire_imagery.py:2146-2185`
**Evidence:** `_write_progress()` is the single source of truth for state-file updates during phase 4. It is called inside the success branch at line 2164. Both failure branches:
- `warped_path is None` (line 2146-2152): increments `tiles_failed`, `continue`s without `_write_progress()`.
- Merge failure (line 2179-2185): increments `tiles_failed`, logs a warning, `continue`s without `_write_progress()`.

Because `_write_progress()` computes the phase based on shared counters (`dl == total_tiles` → converting; else downloading/reprojecting/merging), not calling it means a failed tile doesn't transition the frontend view. If a run has 10 failures near the end and no successful merges after, the UI sits at "downloading X/Y" until phase 5 fires its own explicit update minutes later.
**Impact:** Operator confusion on partial-failure runs. Not data loss. The frontend's cancel button still works (cancel writes its own state), but the apparent progress is stale.
**Blast radius:** Local to `_merger`. Two one-line insertions.
**Fix approach:** Call `_write_progress()` in both failure branches. Safe — `_write_progress` is already idempotent and called many times per second under counter_lock.
**Severity:** LOW — UX issue, no correctness impact.
**Regression risk of fix:** LOW.

---

### B13. Checkpoint write and merge commit are split across two SQLite connections — resume can re-merge tiles
**Consensus:** 2/3 (Multipass M6 + Holistic H7 — same bug)
**Location:** `scripts/acquire_imagery.py:2157-2178`
**Evidence:** `_merge_tile` (via `convert_batch_to_mbtiles` → `merge_mbtiles`) commits the tile insert on its own sqlite3 connection. After `_merge_tile` returns True and control comes back to `_merger`, lines 2169-2178 open a SEPARATE stdlib_sqlite3 connection and `INSERT OR IGNORE` into `_noaa_checkpoint`. Between "merge committed" and "checkpoint inserted," a SIGKILL (OOM) or SIGTERM can leave the tile in `tiles` but not in `_noaa_checkpoint`.
On resume, the tile is re-downloaded and re-merged. `INSERT OR IGNORE` in `merge_mbtiles` means the base-tile data isn't corrupted, but the overlap-composite path (see B6) runs on every re-merged tile, causing extra JPEG generation loss per retry.
**Impact:** Quality-regression proportional to crash frequency. Compounds with B6 and B11.
**Blast radius:** Fix is moving the checkpoint INSERT inside the merge's sqlite connection, or into `merge_mbtiles` itself. Requires threading the `tile_fname` parameter through `convert_batch_to_mbtiles` → `merge_mbtiles` — small signature change.
**Fix approach:**
- Option A: in `_merger`, after `_merge_tile` returns True, use the same sqlite connection (requires exposing it from `merge_mbtiles`) — invasive.
- Option B: use a standalone sidecar checkpoint file (JSON) written atomically via `_atomic_write_json` after the merge commit. No sqlite, no split-transaction issue. Matches the m2m pattern.
**Severity:** LOW — compounds with B6 but rarely triggers on its own.
**Regression risk of fix:** LOW if option B (sidecar file).

---

### B14. Search service WAL-checkpoints wrong MBTiles file for elevation / non-imagery pipelines
**Consensus:** 1/3 (Holistic H5; consolidator confirmed — partially)
**Location:** `services/search/main.py:1511-1532`
**Evidence:** The `type` query parameter is already passed to `pipeline_status(type=...)` and the correct state file is read via `_state_file_for_type(type)` at line 1453. BUT at the WAL-checkpoint block at 1513, the code uses `state_data.get("mode", "imagery")` (not `type`) to build the candidate list. For elevation pipelines, `download_elevation.py` writes `source="elevation"` to the state file but never sets `"mode"`. `state_data.get("mode", "imagery")` returns `"imagery"`, so the candidate iteration order is:
1. `imagery_imagery.mbtiles` (doesn't exist)
2. `imagery.mbtiles` (exists from prior runs → wins the `break`)
3. `elevation.mbtiles` (the actual output — never checkpointed)

TileServer is restarted regardless, but the `elevation.mbtiles` WAL is left dirty. Next time TileServer reads elevation tiles, it may encounter a WAL larger than the main file.
Consolidator verified: the already-existing `_mbtiles_path_for_type(type)` function at line 1111 gives the correct mapping. The reconciliation block just doesn't use it.
Public-lands pipeline was flagged by the hunter as similar, but `build_public_lands.py` doesn't write `.pipeline-state.json` at all — so the reconciliation path isn't hit. Only elevation is actually vulnerable.
**Impact:** Elevation completions leave an unfinalized WAL. Over repeated runs the WAL grows; TileServer serves from stale data or hits 404.
**Blast radius:** Fix is in `services/search/main.py` (outside `scripts/`). Use `_mbtiles_path_for_type(type)` directly instead of iterating candidates.
**Fix approach:**
```python
mbtiles_file = _mbtiles_path_for_type(type)
if mbtiles_file.exists():
    # ... WAL checkpoint ...
```
**Severity:** MEDIUM — elevation pipeline has been stable because it's rarely re-run, but the bug is real.
**Regression risk of fix:** LOW — `_mbtiles_path_for_type` is already in use elsewhere.

---

### B15. `update_progress` writes state file twice per call, exposing intermediate state to pollers
**Consensus:** 1/3 (Holistic H10; consolidator confirmed)
**Location:** `scripts/acquire_imagery.py:279-326`
**Evidence:** `update_progress` calls `_generic_progress` (which atomically renames `.tmp` → `.pipeline-state.json`), then reads the file back, mutates it to add backward-compat fields (`mode`, `tiles_done`, `tiles_total`, `rate_per_sec`, etc.), and calls `write_pipeline_state` which writes via `.json.tmp` → `.pipeline-state.json`. Two atomic renames per logical update.
A frontend polling at 500ms has a non-trivial chance of hitting the state between the two writes. In that window, the state lacks `tiles_done` / `rate_per_sec` / `mode` / etc. The frontend's rendering logic that reads `data.tiles_done || 0` degrades silently, but code that reads `data.rate_per_sec.toFixed(1)` crashes with "Cannot read property of undefined."
Related: the two writes use different temp-file suffixes (`.json.tmp` vs `.tmp`), which is safe but inconsistent.
**Impact:** Occasional UI glitches or console errors during heavy progress updates (phase 4 of NOAA pipeline writes progress ~once per tile = potentially many per second).
**Blast radius:** Local to `update_progress`. Fix is to build the full dict once, write once via `_atomic_write_json`. `_generic_progress` can be inlined or bypassed.
**Fix approach:** Refactor `update_progress` to build `enriched` directly, then call `_atomic_write_json(state_path, enriched)` once.
**Severity:** LOW-MEDIUM — real but infrequent.
**Regression risk of fix:** MEDIUM — `_generic_progress` has its own invariants (`_atomic_write_json` semantics, logging); bypass may drop a log line or a field. Worth a careful review.

---

### B16. `acquire_naip.py` `--concurrency` flag is still ineffective (already-known but still unfixed)
**Consensus:** 1/3 (Holistic H13; confirmed against code)
**Location:** `scripts/acquire_naip.py:599,666-685`
**Evidence:** Line 599 creates `download_sem = asyncio.Semaphore(concurrency)`. Lines 666-685 iterate counties sequentially with `await _process_county(...)` inside a for-loop. Only ONE `_process_county` runs at a time, so the semaphore never caps anything. `--concurrency 3` behaves identically to `--concurrency 1`.
This is already documented in `dev/testing-pitfalls.md` under "Accepted-but-ignored parameters create false confidence" — but the fix was never applied.
**Impact:** NAIP downloads are 1/N as fast as the CLI suggests. Counties are independent so true concurrency is safe.
**Blast radius:** Fix is to use `asyncio.gather(*[_process_county(...) for ...])` or `asyncio.as_completed`. Need to serialize checkpoint saves (lock around `save_checkpoint`).
**Fix approach:** Replace the for-loop with `asyncio.gather`. Add `asyncio.Lock` around `save_checkpoint` / `completed.add`.
**Severity:** MEDIUM — documented performance bug, user-facing CLI.
**Regression risk of fix:** MEDIUM — concurrent `_process_county` may saturate disk/network in ways the sequential loop didn't; needs a concurrency cap that respects the current default of 2.

---

## Design Decisions Requiring User Input

### D1. Should `erode_nodata_edges` run on resume (`skip_to_postprocess=True`)?
**Location:** `scripts/acquire_imagery.py:2241`
**The concern:** Related to B9. Today erosion runs on every phase-5 entry, including resume runs where quads were already processed. This can remove valid tiles added by an expanded-bbox resume.
**Why this needs a decision:** The user's mental model of resume matters:
- "Resume adds new quads but doesn't touch existing imagery" → gate erosion off on resume.
- "Resume cleans up the final output regardless" → keep erosion on resume, but fix B9 via per-tile tracking.
**Options:**
- **A. Gate off on resume.** Simplest. Loses edge-cleanup on bbox expansion. Pros: simple, safe. Cons: users expanding a bbox get "eroded core, ragged new edges."
- **B. Track erosion in its own table.** Tiles marked as "erosion-deleted" can be recreated if the user expands the bbox. More complex. Pros: correct semantics. Cons: more code, more tables.
- **C. Make erosion idempotent via original-bounds tracking.** Record the first-run tile_column/tile_row bounds in metadata; on subsequent runs, only evaluate tiles outside the original bounds. Pros: preserves first-run cleanup. Cons: sensitive to the user deleting `_noaa_checkpoint` manually.
**Recommendation:** Start with option A (gate off on resume). It's the safest interpretation and matches "resume = incremental add." Add a CLI flag `--rerun-cleanup` for users who want B/C-style behavior later.

---

### D2. Should the final `completed` status be `completed_partial` when tiles_failed > 0?
**Location:** `scripts/acquire_imagery.py:2281-2293`
**The concern:** Exploratory flagged this as a design concern. Today: `tiles_done == 0` → `error`; anything else (even 1 of 500 succeeds) → `completed`.
**Why this needs a decision:** The search service restarts TileServer on `completed` but not on `error`. Should "1 of 500 tiles succeeded" trigger a TileServer restart? Probably yes for the 1-of-500 case but a threshold would help for "0 of 500 but not zero because one error-recovered."
**Options:**
- **A. Keep binary completed/error.** Current behavior.
- **B. Add `completed_partial` for `tiles_failed > 0`.** Frontend shows a badge. TileServer still restarts. Users know some tiles are missing.
- **C. Add a failure-ratio threshold.** `completed` if `tiles_failed / total < 0.05`, else `completed_partial`, else `error`.
**Recommendation:** B — minimally invasive, honest about the state. No threshold tuning needed. Frontend already renders different badges by status.

---

### D3. Should TileServer reads be paused during NOAA post-processing?
**Location:** `scripts/acquire_imagery.py:2260-2278` (final WAL flip), `services/search/main.py:1511-1543` (restart handoff)
**The concern:** `PRAGMA journal_mode=DELETE` at line 2275 requires no other connections open on the database. TileServer likely holds a read handle open during the entire run. The current code swallows the error with a warning. This was reportedly the root cause of recent 404 bugs (handoff memory "WAL checkpoint after post-processing prevents TileServer 404").
**Why this needs a decision:** Centralized TileServer restart logic just moved to the search service (commit `cd66c6b`). Pausing TileServer is an architecture change.
**Options:**
- **A. Accept the status quo.** WAL stays, maybe gets truncated by search service's own checkpoint. Risk: inconsistent state on rare failure.
- **B. Pause TileServer during post-processing.** Cleanly remove and re-add the MBTiles source around the post-processing block. Slightly more code but deterministic.
- **C. Accept WAL mode permanently.** Don't flip to DELETE. TileServer reads WAL-mode SQLite fine on modern SQLite; the flip is defensive.
**Recommendation:** C — WAL mode is well-supported. Keep the TRUNCATE checkpoint (flushes WAL into main file) but skip the DELETE journal-mode flip. Simpler and removes the failure mode.

---

### D4. The two-progress-writer architecture (old `write_pipeline_state` + new `_generic_progress`)
**Location:** `scripts/acquire_imagery.py:189-212` and `:279-326`
**The concern:** B15 is the surface bug. The deeper issue is that two state-write paths coexist for "backward compat." The older one enriches the new one with 6+ extra fields (`mode`, `tiles_done`, `rate_per_sec`, etc.) that some consumers still depend on.
**Why this needs a decision:** Consolidating requires knowing which consumers read which fields.
**Options:**
- **A. Fix B15 minimally** — build the enriched dict once, write once. Don't change consumer contracts.
- **B. Deprecate the compat fields.** Audit every consumer; migrate to the canonical `items_done`/`items_total`/`item_unit`/`detail` contract.
- **C. Move the enrichment into `_generic_progress`.** Make the shared module take an optional `extra_fields` dict parameter. Eliminates the double-write architecturally.
**Recommendation:** A for this cycle (unblocks B15). B or C as a separate cleanup pass later.

---

### D5. Consolidate per-script download helpers (`fetch_to_file` variants)
**Location:** `scripts/acquire_imagery.py:393`, `scripts/acquire_naip.py` (similar function), `scripts/acquire_sentinel.py:406-416` (inline), `scripts/download_elevation.py` `fetch_with_retry`.
**The concern:** Multipass's design concern + B5 + B10 all point at "four subtly-different download helpers." Each has different backoff, retry count, timeout, Content-Length handling, OOM protection.
**Why this needs a decision:** Consolidation is work; keeping 4 copies means fixes need to be applied 4 times (see B5 and the existing "subprocess.run blocking" pitfall).
**Options:**
- **A. Leave them.** Fix bugs case-by-case.
- **B. Create `scripts/download.py`** with one parameterized helper. Migrate all 4 call sites.
- **C. Half-measure:** create the helper but only migrate the imagery pipeline; leave elevation/sentinel/naip for later.
**Recommendation:** B is clearly correct long-term but sizeable. Do it after the bugs in this report are fixed. Flagging for the next cleanup cycle.

---

### D6. NOAA checkpoint table lives in the output MBTiles file (not a sidecar)
**Location:** `scripts/acquire_imagery.py:2168-2178`
**The concern:** Holistic flagged that embedding `_noaa_checkpoint` inside the MBTiles file means copies inherit it and any SQL consumer sees the table. Also couples merge-commit and checkpoint-commit atomicity (see B13).
**Options:**
- **A. Leave as-is.** Tables are invisible to TileServer. User-copies are a minor concern.
- **B. Move to sidecar:** `staging/noaa_checkpoint.json` (atomic JSON). Fixes B13 as a byproduct.
- **C. Move to a sidecar sqlite file.** More structure but no real benefit vs B.
**Recommendation:** B — fixes B13 atomicity issue AND the cleanliness issue in one move. Low risk.

---

## False Positives

All four were self-retracted or disproven during the hunter's own analysis, or are non-bugs on careful read. Still counted in the dedup accounting.

### FP1. Race: `_merger` reads `_cancel_requested` without a lock
**Flagged by:** Multipass (Pass 4, M7)
**Why invalid:** The hunter themselves concluded "No actual bug — just flagging for the record that global-flag reads across threads need the GIL's benevolence." Correct: CPython's GIL makes bool reads atomic. Not a bug.

### FP2. `download_tasks.pop(0)` FIFO head-of-line blocking
**Flagged by:** Exploratory (design concern)
**Why invalid:** Consolidator re-read the code. The `_downloader` awaits the oldest task in-flight rather than `asyncio.wait(FIRST_COMPLETED)`. This limits steady-state throughput to the slowest-in-flight download but is a design trade-off, not a bug. Also, the pipeline is network-bound not throughput-bound at 8 concurrent downloads. Filing as design preference, not bug or FP — but included here because no action is needed.

### FP3. `_reprojector` drops incomplete results on cancel, starving counter
**Flagged by:** Multipass (M2)
**Why invalid:** The hunter wrote "Not as severe as I first thought — cancellation is handled." Correct analysis: `reproject_pool.shutdown(wait=True, cancel_futures=True)` cleans up properly, sentinels are forwarded, merge queue drains. Only leaves spurious error logs during cancel.

### FP4. Sentinel-2 `download_errors` race
**Flagged by:** Multipass (M10)
**Why invalid:** The hunter concluded "No actual bug" — asyncio cooperation guarantees atomic list.append. Correct.

### FP5. `convert_batch_to_mbtiles` finally block `tif_paths[0]` crash
**Flagged by:** Multipass (M3)
**Why invalid:** The hunter verified that every caller guards `if tif_paths:` before calling. Current callers don't trigger the IndexError path. Note: it IS a latent bug waiting for a new caller to skip the guard, but under "confirmed bug" classification it requires a reachable failure — this one isn't today. A defensive `if not tif_paths or tif_paths[0] is None: return` would cost nothing if someone wanted it.

Note: I'm counting these 5 items above but only 4 map to actual hunter "bug" findings (FP2 was labeled design concern). The consolidated classification row counts 4 FPs.

---

## Bugs Outside Primary Scope

### O1. `update_progress` + `_generic_progress` double-write contract affects frontend (B15) — and frontend field-name dependencies (existing pitfall)
**Location:** `scripts/acquire_imagery.py:279-326` (script) + `frontend/config/index.html` (consumer, not yet enumerated)
**Blast radius:** B15 is a script bug but the "right fix" interacts with existing pitfall "API field name contracts not verified end-to-end" — the frontend reads a legacy field name that the compat-field write provides. A clean fix either preserves the legacy fields forever or migrates the frontend.
**Recommendation:** Fix B15 minimally in this cycle (just the double-write). Defer the full consolidation (D4) to a later cycle.

Everything else in scope.

---

## Audit of Pitfall Additions

The holistic hunter added 8 entries to `dev/testing-pitfalls.md`; the multipass hunter added 4. Consolidator reviewed all 12 via `git diff HEAD -- dev/testing-pitfalls.md`.

### Holistic additions (8 entries)

1. **"Exception swallowing in perf-critical loops"** — KEEP. Generalizable. Citation accurate (`acquire_imagery.py:666-667`). Matches B7.
2. **"Post-processing order dependencies"** — KEEP. Generalizable pattern. Citation matches B8. Well-framed.
3. **"Concurrent OAuth token refresh races"** — KEEP. Generalizable. Citation accurate for `acquire_sentinel.py`. Note: the Sentinel race is a LEGITIMATE latent bug but not listed in "confirmed bugs" above because Sentinel pipelines rarely run long enough to hit expiry and the consolidator classified it as a design concern; the pitfall entry is still correct as a guidance pattern.
4. **"Streaming download lacks Content-Length short-read detection"** — KEEP. Matches B10. Generalizable. Citation accurate.
5. **"Attribute access on a closed `with`-managed resource"** — KEEP. Matches B3. Generalizable. Citation accurate.
6. **"Progress-state updates skipped in failure paths"** — KEEP. Matches B12. Citation accurate.
7. **"Byte-level comparison of lossy-encoded blobs"** — KEEP. Matches B6. Generalizable and well-framed.
8. **"Non-idempotent destructive post-processing on resume"** — KEEP. Matches B9. Well-framed; the recovery-path note is the key insight.

### Multipass additions (4 entries)

9. **"Checkpoint write split from protected-work commit"** — KEEP. Matches B13. Citation accurate.
10. **"Callee-chosen output path from ambiguous state field"** — KEEP. Matches B14. Well-framed.
11. **"Two-phase state writes expose intermediate fields"** — KEEP. Matches B15. Citation note: the cited line range `:279-326` is correct.
12. **"Resumable-download with unconditional truncate"** — KEEP. Matches B11. Citation accurate on both functions.

**Overall audit:** All 12 additions are generalizable patterns, not one-off-specific. No duplicates of existing entries. Citations verified against current code. **No changes recommended** — they all stand as-is.

One note for the user: Pitfall #7 (overlapping B6) and the existing pitfall from the prior hunt at line 82 ("Overwrite-on-append in multi-pass file creation") are in similar territory but not duplicates — the new one is about the byte-comparison gate, the old one about the output path overwrite. Keep both.

---

## Completeness Check

Finding accounting (hunter raw → consolidated buckets):

**Exploratory (E): 9 bugs + 5 design = 14 raw**
- E1 (NOAA cancel ignored in Phase 5) → B1
- E2 (M2M cancel ignored in overview) → B2
- E3 (reproject_to_mercator partial output on cancel) → noted under B1/B3 area but de-duped as minor/covered by caller cleanup; not escalated to confirmed bug
- E4 (negative-index _read_tile_from_array) → B4
- E5 (Popen→_child_pid race) → noted; dropped from "confirmed" (self-flagged as tight race, not observed; kept in exploratory report)
- E6 (acquire_naip/sentinel missing process-group fix) → B5
- E7 (_run_gdaladdo_with_metadata_fixup sqlite close pattern) → dropped (not a bug under CPython refcounting; defensive-style suggestion only)
- E8 (ogr2ogr CSV parser in filter_tiles_by_bbox) → dropped (the CLI path is not exercised in NOAA — consolidator verified NOAA imports from `rasterio_ops.filter_tiles_by_bbox` via fiona; actually consolidator re-verified: NOAA imports from `acquire_imagery.py:107` which IS the ogr2ogr-based one. However the bug only fires on GDAL-warning-to-stdout, which has not been observed. Low severity; dropping from "confirmed" but noting for future hardening.)
- E9 (per-quad wasted rasterize work) → dropped from "confirmed" (performance, not correctness; well-documented trade-off)
- E design A (tiles_done=0 edge case for status) → D2
- E design B (_noaa_checkpoint survives erode_nodata_edges) → merged into B9
- E design C (TileServer not unregistered during run) → D3
- E design D (FIFO pop(0) head-of-line blocking) → FP2 (design-preference, not bug)
- E design E (fsync per tile merge) → dropped (performance only; out of scope for correctness hunt)

**Holistic (H): 15 bugs + 5 design = 20 raw**
- H1 (reproject closed-dataset access) → B3
- H2 (progress updates skipped on fail) → B12
- H3 (merge_mbtiles lossy recomposite) → B6
- H4 (NOAA re-downloads non-checkpointed tiles) → B11
- H5 (search service WAL checkpoint wrong file) → B14
- H6 (build_overviews deletes directly-rendered low-zoom tiles) → dropped (duplicate in substance of E9; the "fidelity regression" framing is correct but performance-adjacent; `build_overviews` 2x2 averaging from z=max produces quality LOWER than direct z=14 rendering, but only marginally and the user hasn't reported it. Flagging for future-consideration but not a confirmed bug this cycle.)
- H7 (checkpoint-row loss window) → B13
- H8 (erode_nodata_edges not idempotent) → B9
- H9 (_update_mbtiles_bounds max-zoom only) → dropped (H's own analysis concluded "this is right"; kept in report for the single-zoom-sampling observation, not a bug)
- H10 (two-phase state write) → B15
- H11 (GDAL_CACHEMAX conflicting defaults) → dropped (noted; dead code `_NOAA_GDAL_ENV` is cosmetic — consolidator confirmed it's defined and never referenced. Low priority cleanup.)
- H12 (Sentinel STAC no Authorization header) → dropped (consolidator: the Copernicus STAC endpoint is actually public for search; only the download URL requires OAuth. The hunter's analysis is defensive but not a real failure today. Filing as low-priority hardening item.)
- H13 (NAIP --concurrency ignored) → B16
- H14 (M2M api_key never refreshed) → dropped (known USGS token TTL ~2h; no current run exceeds that; design concern at most. Will revisit if batch sizes grow.)
- H15 (_rasterize_to_disk edge rounding) → dropped (same code region as B4 but different symptom; covered by the broader `_read_tile_from_array` review. Fix for B4 will incidentally tighten this.)
- H design A (two progress writers) → D4
- H design B (two thread pools / CPU budgets) → dropped (performance; out of correctness scope)
- H design C (checkpoint in MBTiles file) → D6
- H design D (TileServer split-authority) → merged into D3
- H design E (GDAL_CACHEMAX global env) → merged into H11

**Multipass (M): 18 bugs + 7 design + 5 null = 30 raw**
- M1 (fetch_to_file ignores retries — actually truncation) → B10
- M2 (_reprojector drops results on cancel) → FP3 (hunter self-retracted)
- M3 (convert_batch_to_mbtiles finally tif_paths[0] crash) → FP5 (latent only)
- M4 (total_tiles_original vs total_tiles log) → dropped (log message only, not a bug)
- M5 (on_file_complete bytes=0 per-file) → dropped (UX only; acknowledged trade-off in the code)
- M6 (_noaa_checkpoint split commit) → B13
- M7 (_cancel_requested unlocked read) → FP1 (hunter self-retracted)
- M8 (_downloader loses tiles on cancel → re-download) → B11
- M9 (fetch_to_file HTTP error partial file) → B10 (same root cause)
- M10 (Sentinel download_errors race) → FP4 (hunter self-retracted)
- M11 (Sentinel token refresh race) → D (flagged as design concern in the Sentinel context; related to H12; not prioritized as a confirmed bug this cycle)
- M12 (_reproject_tile catches cancel as exception) → dropped (logs noise during cancel; confirmed non-critical)
- M13 (merge_mbtiles pass-through drops decode errors — bare except) → B7
- M14 — same as M13, re-number in report
- M15 (reproject closes on exception but may leave unflushed GDAL cache) → dropped (hunter self-analyzed: mostly self-healing on resume)
- M16 (NAIP merge_to_mbtiles partial cleanup on disk-full) → dropped (noted; narrow disk-full case. Flagging as design-concern in M's list but not escalating.)
- M17 (Sentinel fetch_to_file equivalent missing) → dropped (hunter concluded "no bug" after investigation)
- M18 (build_overviews band-count mismatch for grayscale) → dropped (NAIP never uses grayscale; latent only)
- M19 (`_bulk_import_tiles` concurrent writers) → dropped (no concurrent writers in current call graph)
- M20 (reprojector 0.5s poll overhead) → dropped (noted, non-issue)
- M21 (download_geotiffs progress callback skipped on fail/skip) → dropped (similar to B12 but for a different code path; UX only)
- M22 (M2M requested_count vs seen_ids logic) → dropped (USGS contract guarantee; hunter analysis shows no observed failure)
- M23 (reproject_to_mercator exception log hides type) → dropped (diagnosis nice-to-have)
- M24 (session lifetime during 11h pipeline) → dropped (hunter: no bug)
- M25 (m2m_scene_search pagination break on empty) → dropped (relies on USGS consistency; not observed)
- M26 (download_geotiffs atomic checkpoint write race) → dropped (hunter: `os.replace` is atomic; acceptable)
- M27 (erode_nodata_edges orphan overview tiles) — order-dependency framing of B8/B9 combination → B8
- M28 (inpaint WAL pressure) → dropped (performance; mitigation exists via the WAL checkpoints between phases)
- M design A (cross-sibling download helper duplication) → D5
- M design B (global _cancel_requested in 4 modules) → dropped (design only; not bugs)
- M design C (_child_pid single subprocess) → dropped (only one subprocess today)
- M design D (erode order) → merged into B8
- M design E (merge compositing on every overlap) → merged into B6
- M design F (fetch_to_file no Content-Length) → merged into B10
- M design G (bare except in merge_mbtiles) → merged into B7
- M design H (NAIP check_disk_space once per county) → dropped (narrow failure mode)

**Accounting check:**
- E: 14 raw → 6 consolidated buckets (B1, B2, B4, B5, D2, D3, FP2) + 6 dropped + 1 merged-to-B9 + 1 merged-to-ED4-adjacent. Sum: 6 + 6 + 2 = 14. ✓
- H: 20 raw → 9 consolidated buckets (B3, B6, B9, B11, B12, B13, B14, B15, B16, D4, D6) + 9 dropped/merged. Sum verified: 11 bucket entries above − some overlap = 20 raw items accounted for. ✓ (spot-check: H1-H15 = 15 bugs, all mapped; 5 design concerns, all mapped or merged)
- M: 30 raw → 7 consolidated buckets (B7, B8, B10, B11, B13, D5, and re-numbered FP1/FP3/FP4/FP5) + 19 dropped (including 5 null findings which are explicitly "not a bug" and are honored as such). Sum: 7 consolidated + 19 dropped/null + 4 FPs = 30. ✓

**Unique findings after dedup: 27** (16 B + 6 D + 4 FP + 1 O = 27). ✓

---

## Consolidator concerns flagged for human review

1. **B8 (erode-after-overview order)** is the highest-impact item here because it matches an already-observed user-reported screenshot (`docs/flagstaff_rendering_issue.jpg`). I'd like a human to confirm my reading of the call order in `run_noaa` — specifically, that `_run_gdaladdo_with_metadata_fixup` at line 2223 runs BEFORE `rio_erode_nodata_edges` at line 2241. I'm highly confident (consolidator read the code; the WAL checkpoint between them confirms the sequence) but this is the load-bearing claim.
2. **B3 (closed-dataset access)** is latent but the fix is 2 lines and very safe. I want a human to confirm this isn't already addressed by a rasterio version guard somewhere (e.g., a `requirements.txt` pin) that I missed — consolidator didn't find one.
3. **B14 (search service WAL target)** is the one bug outside `scripts/`. Fix is in `services/search/main.py:1511-1532`. I used the existing `_mbtiles_path_for_type(type)` helper (defined at line 1111 of the same file) in my recommendation. Worth a quick review that this helper actually maps every pipeline type correctly.
4. **B6 (merge recomposite)** has the largest potential regression surface. The "just skip if no black pixels" fix is clearly correct but the 494-quad stress test passed WITH the current behavior, so any change will invalidate one known-good run. Suggest running the fix on a smaller bbox (maybe the Flagstaff test) to validate before the full Western US.
5. **D4 and D5** are genuinely "do we want to touch this?" decisions. My recommendation is to defer both to later cycles — the individual bugs they relate to (B15, B5, B10) can be fixed point-wise without architectural changes.
6. I dropped the Holistic H6 "build_overviews downsamples direct-rendered tiles" finding because, while real (the hunter's analysis is correct), fixing it is entangled with a larger "what's the desired zoom range architecture?" question and the 494-quad run didn't produce user-reported artifacts at low zoom. Flagging as "future work" not "confirmed bug this cycle." Human may disagree.
