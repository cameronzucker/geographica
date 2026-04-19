# Bug Hunt Report — 2026-04-18 — NOAA Imagery Pipeline (Holistic)

## Scope

Read fully:

- `scripts/acquire_imagery.py` (2379 LOC) — all five modes (tnmaccess, direct, nationalmap, m2m, noaa), 3-stage NOAA pipeline, merge_mbtiles, overview fixup, bounds update, subprocess helpers.
- `scripts/acquire_naip.py` (765 LOC) — USDA Gateway discovery and JP2→GTiff pipeline.
- `scripts/acquire_sentinel.py` (642 LOC) — Copernicus STAC + OAuth download pipeline.
- `scripts/rasterio_ops.py` (959 LOC) — rasterio helpers: reproject, merge_to_mbtiles, build_overviews, erode_nodata_edges, inpaint_nodata_pixels, _rasterize_to_disk, _read_tile_from_array.
- `scripts/download_elevation.py` (416 LOC) — Terrain-RGB tile download.
- `scripts/pipeline_progress.py`, `scripts/pipeline_security.py` (shared helpers).

Spot-read in `services/search/main.py`: pipeline_start, pipeline_status reconciliation, cancel, TileServer restart handoff (lines ~1440-1615).

Approach: Built a data-flow model of how one NOAA quad travels from Azure blob → staging .tif → warped .tif → temp MBTiles → merged output MBTiles → post-processed (overviews, erode, inpaint) → WAL-checkpointed → read by TileServer. Then walked adjacent mode pipelines (M2M, NAIP, Sentinel, elevation) to compare the same data flow and spot inconsistencies. Then specifically traced cancellation, error, and resume paths through each stage.

## Bugs

### 1. `reproject_to_mercator` accesses a closed rasterio dataset in trailing log.debug

**Location:** `scripts/rasterio_ops.py:250-252`
**Severity:** significant (latent — dormant at INFO, exceptions at DEBUG)
**Evidence:** Line 210 opens `with rasterio.open(str(src_path)) as src:`. The `with` block ends at line 249 (the outer `with` closes when the `reproject()` call returns). Line 250 (`elapsed = ...`) is dedented to the level of `try:` at line 209, so it is **outside** the `with rasterio.open(...) as src:` block. Line 252 then reads `src.width` and `src.height`.

```python
210:        with rasterio.open(str(src_path)) as src:
232:            with rasterio.open(str(dst_path), "w", **profile) as dst:
...
249:                    )
250:        elapsed = time.monotonic() - t0
251:        log.debug("Reproject %s: %dx%d → %dx%d in %.1fs",
252:                  src_path.name, src.width, src.height, width, height, elapsed)
```

Python always evaluates function-call arguments eagerly regardless of the logger level — even if `log.debug` is gated by INFO level, `src.width`/`src.height` are still accessed. After `with rasterio.open(...) as src:` exits, the underlying GDAL dataset is closed. Depending on rasterio version, accessing `.width`/`.height` on a closed dataset either returns stale cached values (silent) or raises `AttributeError`/`RasterioIOError` (caught by the broad `except Exception` at line 255, returning `False`).

**Impact:** At INFO logging (production), tends to succeed silently (cached widths). If the runtime is switched to DEBUG or if rasterio is upgraded to a version that enforces closed-dataset checks, every reproject call will raise inside the `except`, return `False`, and the NOAA pipeline will mark every tile as "reproject failed" even though the output GeoTIFF was written correctly. Latent time-bomb.

**Fix:** Move lines 250-252 inside the `with rasterio.open(...) as src:` block, or capture `src.width` and `src.height` into locals before the outer `with` exits.

---

### 2. Counter updates for failed tiles never write progress — UI "stuck" during failures

**Location:** `scripts/acquire_imagery.py:2149-2151`, `2179-2185`
**Severity:** significant
**Evidence:** In the NOAA `_merger()` coroutine, the single source of truth for state-file updates is `_write_progress()`. It is called on successful merges (line 2164) but deliberately skipped when a tile fails:

```python
2146:  if _cancel_requested or warped_path is None:
2147:      if warped_path:
2148:          warped_path.unlink(missing_ok=True)
2149:      if warped_path is None:
2150:          with counter_lock:
2151:              tiles_failed += 1
2152:      continue    # <-- no _write_progress() call
...
2179:  else:
2180:      with counter_lock:
2181:          tiles_failed += 1
2182:      if _cancel_requested:
2183:          break
2184:      log.warning(...)
                      # <-- no _write_progress() call
```

`_write_progress()` also recomputes the `phase` field from shared counters. With `done == total_tiles` it switches to `converting`; otherwise it picks `downloading`/`reprojecting`/`merging`. If tiles_failed contributes to `total_tiles` but `tiles_done` never reaches total, the frontend sees a "stuck" progress bar (last successful count) for the remainder of the run and an always-`merging` or `downloading` phase, never seeing the end-of-pipeline `converting`/`complete` transition until phase 5 fires its own explicit `update_progress(...)`.

**Impact:** Admin UI and any consumer polling the state file misreport progress when any tile fails. This is worse on partial-failure runs (fraction succeeds) — the user sees the pipeline stop updating and cannot tell if it's hung or actually progressing. The final `update_progress(..., status="completed")` at line 2288 does fix the state, but minutes or hours can elapse between the last successful merge and that final write.

**Fix:** Call `_write_progress()` (or at minimum bump the `items_done` counter for accounting purposes) inside both failure branches.

---

### 3. `merge_mbtiles` overlap detection is a byte-level JPEG compare, causing lossy recomposite on every overlap

**Location:** `scripts/acquire_imagery.py:641-667`
**Severity:** significant (image quality degradation)
**Evidence:** In `merge_mbtiles`, tiles present in both src and dst MBTiles are "composited" only when `s.tile_data != d.tile_data`. But `tile_data` is a JPEG blob; two visually-identical tiles encoded by different runs will virtually always have different bytes (JPEG has non-deterministic quantization in some encoders, plus any metadata jitter). So practically every shared tile triggers the composite path:

```python
641:    cursor = dst.execute("""
642:        SELECT s.zoom_level, s.tile_column, s.tile_row, s.tile_data, d.tile_data
643:        FROM src.tiles s
644:        JOIN tiles d ON ...
647:        WHERE s.tile_data != d.tile_data
648:    """)
```

The composite path decodes both JPEGs, copies src pixels into dst's near-black mask, and re-encodes as JPEG:

```python
660:    merged = _encode_jpeg(dst_arr)
661:    dst.execute("UPDATE tiles SET tile_data = ? ...")
```

When two fully-data tiles overlap (no near-black pixels in dst), the composite is effectively "decode dst, decode src, copy zero pixels, re-encode dst." This loses a JPEG generation on every overlap. For NOAA NAIP with N overlapping quads per edge-tile, the same tile can be decode/re-encoded `N-1` times — cumulative lossy cascade.

**Impact:** At NOAA quad boundaries (4-way corner tiles), image quality degrades progressively as more quads are added. Visible artifacts along quad seams, and quality loss grows with dataset extent.

**Fix:** Use `INSERT OR IGNORE` for the `s.tile_data == d.tile_data` case, and only composite when dst actually contains near-black pixels. E.g., move the black-mask check into the SQL or a pre-filter step: skip composite if dst has no near-black pixels.

---

### 4. NOAA pipeline re-downloads every non-checkpointed tile on resume — no staging cache reuse

**Location:** `scripts/acquire_imagery.py:1953-1974` (`_download_tile`), `1852-1866` (resume logic)
**Severity:** significant
**Evidence:** The resume logic filters out `tile_filenames` already in `_noaa_checkpoint`, but only the checkpoint covers fully-merged tiles. `_download_tile` does not check whether `dest = staging / tile_fname` already exists from an earlier run that was SIGTERM'd after download but before merge:

```python
1956:        dest = staging / tile_fname
1957:        t0 = time.monotonic()
1958:        async with download_sem:
1959:            if _cancel_requested:
1960:                return (tile_fname, None)
1961:            ok = await fetch_to_file(session, url, dest, timeout_s=3600,
                                          max_size=NOAA_MAX_GEOTIFF_SIZE, ...)
```

`fetch_to_file` opens `dest` with `"wb"` which truncates. An existing staging file (say, 486 MB from a crashed earlier run) is silently re-downloaded in full.

**Impact:** For expensive-to-download datasets (NOAA NAIP at ~486 MB/tile), a SIGTERM between download and merge causes a full re-download on resume. On metered connections or slow uplinks (AREDN mesh testing), this is substantial wasted bandwidth. The checkpoint design says "resume-safe," but it only protects re-merging, not re-downloading.

Also: `staging/warped_*.tif` from interrupted reproject runs accumulates on disk indefinitely — no sweep at pipeline start or end.

**Fix:** Before downloading, check `if dest.exists() and dest.stat().st_size > 0 and validate_file_header(dest, "geotiff"):` and skip. Also sweep `staging/warped_*.tif` at pipeline startup (or after successful merges, any warped_ for a merged tile_fname should be unlinked).

---

### 5. TileServer cross-pipeline WAL checkpoint targets the wrong file for non-imagery pipelines

**Location:** `services/search/main.py:1511-1532`
**Severity:** significant (adjacent code; flagging, not deep-dive)
**Evidence:** When a pipeline completes, the search service tries to WAL-checkpoint the output MBTiles and restart TileServer. The candidate list is iterated with `break` on first match:

```python
1513:  output_name = state_data.get("mode", "imagery")
1514:  mbtiles_candidates = [
1515:      f"imagery_{output_name}.mbtiles",
1516:      f"imagery.mbtiles",
1517:      f"elevation.mbtiles",
1518:      f"public-lands.mbtiles",
1519:  ]
1520:  for candidate in mbtiles_candidates:
1521:      mbtiles_file = DATA_DIR / candidate
1522:      if mbtiles_file.exists():
1523:          ...wal_checkpoint...
1524:          break
```

For an **elevation** pipeline, the state file is written by `download_elevation.py` via `_generic_progress(source="elevation", ...)` — no `mode` field is set. `state_data.get("mode", "imagery")` returns `"imagery"` as default. Candidate #1: `imagery_imagery.mbtiles` (doesn't exist). Candidate #2: `imagery.mbtiles` — if that exists from any prior imagery run, it's WAL-checkpointed while `elevation.mbtiles` (the pipeline's actual output) is left with a dirty WAL. TileServer gets restarted either way, but the correct file may still have pending WAL data.

Public lands pipeline has the same issue.

**Impact:** Elevation and public-lands pipelines can complete with an unfinalized WAL, and a stale `imagery.mbtiles` WAL from a previous run may be checkpointed instead. In practice `download_elevation.py` writes to `.elevation-state.json` (not `.pipeline-state.json`), so the reconciliation path may not even be hit for elevation — but public-lands uses `.pipeline-state.json`. Needs verification against each pipeline's state file path.

**Fix:** The candidate list should be driven by the pipeline `type` query parameter (which IS known — `pipeline_status(type=...)`), not by `state_data.get("mode", "imagery")`. Map `type` → mbtiles path via `_mbtiles_path_for_type` which already exists in the same file.

---

### 6. `build_overviews` unconditionally deletes directly-rendered low-zoom tiles

**Location:** `scripts/rasterio_ops.py:693-700`
**Severity:** significant (fidelity regression, silent)
**Evidence:** `build_overviews` deletes all tiles below max_zoom before rebuilding:

```python
695:    deleted = conn.execute(
696:        "DELETE FROM tiles WHERE zoom_level < ?", (max_zoom,)
697:    ).rowcount
```

But in the NOAA pipeline, each NAIP quad's `convert_batch_to_mbtiles` call runs `_rasterize_to_disk` for `min_zoom..max_zoom` (typically z=13..17 for a ~0.6m/px NAIP quad — see `_compute_zoom_range`). Those lower-zoom tiles (13-16) are rendered directly from the source raster at proper sampling. `build_overviews` then deletes those and replaces them with 2×2-averaged downsamples from z=17 — ceding real sampling fidelity for cheap box-averaging.

This is a **generation-loss regression**: a tile at z=14 rendered from 6m/px source pixels is overwritten by (the average of four z=17 tiles that were themselves rendered from 0.6m/px source pixels and compressed to JPEG). The JPEG round-trip and naive box-average gives a noticeably worse image than direct rendering.

**Impact:** NOAA basemap appears softer/blurrier at low zooms than it should. Not a crash — just a quality drop that nobody would notice without an A/B.

**Fix:** Only delete tiles at zoom levels that will be rebuilt, not below `min_rendered_zoom`. Or, since the rasterize step writes zooms min_zoom..max_zoom already, skip `build_overviews` entirely for zooms covered by rasterize, and run it only for z < min_rendered_zoom. Alternatively: `DELETE FROM tiles WHERE zoom_level < ? AND zoom_level NOT IN (SELECT DISTINCT zoom_level FROM tiles WHERE … render-sourced)` — but there's no flag distinguishing rendered-vs-downsampled tiles today.

---

### 7. `_noaa_checkpoint` table is read unconditionally but written only after a successful merge — checkpoint-row loss window still exists

**Location:** `scripts/acquire_imagery.py:2168-2178`
**Severity:** minor
**Evidence:** After `_merge_tile` returns True, the merger opens a new sqlite connection and inserts the tile_filename into `_noaa_checkpoint`:

```python
2169:  import sqlite3 as stdlib_sqlite3
2170:  with stdlib_sqlite3.connect(str(output)) as ckpt_conn:
2171:      ckpt_conn.execute("CREATE TABLE IF NOT EXISTS _noaa_checkpoint ...")
2172:      ckpt_conn.execute(
2173:          "INSERT OR IGNORE INTO _noaa_checkpoint (tile_filename) VALUES (?)", ...
2174:      )
```

The merge itself happens inside `_merge_tile` in a separate sqlite connection that commits before return. Between "merge committed" and "checkpoint row committed" there's a window where:

1. Tile T is merged into `tiles` (committed).
2. SIGTERM kills the process before line 2170 executes.
3. On resume, T is NOT in `_noaa_checkpoint` → pipeline re-downloads and re-merges T.

Re-merging via `INSERT OR IGNORE` doesn't corrupt the dst tiles table, but every overlapping tile goes through the lossy composite path (see Bug #3), causing a quality-regression per retry.

**Impact:** Interrupted-and-resumed NOAA runs cause a small number of tiles to undergo extra JPEG re-encoding. Cumulative over many interruptions. Minor in practice but compounds with Bug #3.

**Fix:** Do the checkpoint INSERT inside the same sqlite connection/transaction used by `merge_mbtiles`, so "tile present" and "tile in checkpoint" commit atomically. Or use a single connection in `_merge_tile` that performs both operations before returning.

---

### 8. `erode_nodata_edges` operates on MIN/MAX row-column bounds and is not idempotent when new data is added

**Location:** `scripts/rasterio_ops.py:897-937`
**Severity:** significant
**Evidence:** `erode_nodata_edges` iteratively strips boundary tiles until all remaining edges meet `min_edge_fill` on every 48-pixel border strip. The "boundary" is determined dynamically per round from `MIN/MAX(tile_column/row)`. The function runs unconditionally on every NOAA post-processing pass — including when the pipeline hits `skip_to_postprocess` (all quads already merged — resume case).

Scenario:
1. Run 1: NOAA AZ 2021, bbox A → erode strips outer ring → `tiles` bounded by a smaller extent.
2. Run 2: NOAA AZ 2021, expanded bbox A' that ADDS quads outside the original extent → merged tiles extend the bounding rectangle. `erode_nodata_edges` sees the new outer ring and evaluates it.

If the new outer ring has legitimately full-edge tiles, they pass (>90% fill). Fine. But if ANY of the new edge tiles has <90% fill on any one of top/bottom/left/right — e.g., because the source bbox sliced part of a NAIP quad that has nodata at the true data boundary — they get deleted. In the *next* iteration of the inner `while removed_this_round > 0` loop, the new boundary is re-evaluated, potentially stripping previously-valid tiles. **The erosion never stops at the original run-1 boundary; it can eat into real imagery added by run 2.**

Also: once a tile is deleted, there is no recovery. A subsequent run with the same bbox won't re-download it (it's not in `_noaa_checkpoint`... wait — it IS in the checkpoint, because erase happens AFTER merge AFTER checkpoint-insert). So the run-2 checkpoint shows T as "done" but the actual tiles table no longer contains it. It's permanently gone from the MBTiles with no way to rebuild without clearing the checkpoint.

**Impact:** Incremental NOAA pipeline runs can progressively delete valid imagery. More severely: the checkpoint says "done" for tiles that were deleted by erosion, so the user's only recovery is to delete the `_noaa_checkpoint` table and re-run from scratch.

**Fix:** (a) Only run erosion on the FIRST pipeline pass for a given output, not on `skip_to_postprocess` resumes. (b) Or record "eroded" tiles separately and don't let `erode_nodata_edges` delete rows that are in `_noaa_checkpoint` — it should only prune tiles that were NEVER valid. (c) Or, move erosion to a different level of MBTiles-generation (e.g., in `merge_mbtiles` per-batch) where it only sees one batch's tiles.

---

### 9. `_update_mbtiles_bounds` computes bounds at max zoom only — hides wrong-hemisphere errors at other zooms

**Location:** `scripts/acquire_imagery.py:681-729`
**Severity:** minor
**Evidence:** The function samples only the max-zoom level to derive the bbox:

```python
689:  row = conn.execute("SELECT MAX(zoom_level) FROM tiles").fetchone()
...
696:  "SELECT MIN(tile_column), MAX(tile_column), MIN(tile_row), MAX(tile_row) "
697:  "FROM tiles WHERE zoom_level = ?", (max_z,)
```

If max-zoom tiles were corrupted (e.g., bad y-flip at rasterize time), the derived bounds will point to the wrong hemisphere and TileServer will advertise the wrong extent. Bounds computation at multiple zoom levels would provide a sanity check.

More importantly: `tms_to_bounds` takes `min_row` and `max_row` in TMS convention. `min_row` is the southernmost row (TMS y=0 is south). The function correctly converts via `y_slippy = n - 1 - y_tms`. The conversion is algebraically correct, but the call pattern:

```python
714:  sw = tms_to_bounds(max_z, min_col, min_row)
715:  ne = tms_to_bounds(max_z, max_col, max_row)
```

assumes `sw[0:2] = (west, south)` and `ne[2:4] = (east, north)`. `tms_to_bounds` returns `(lon_min, lat_min, lon_max, lat_max)`. So `sw[1]` is the southern edge of the sw tile (correct for bbox south) and `ne[3]` is the northern edge of the ne tile (correct for bbox north). OK, this is right.

**Impact:** Not a bug — just notable for the "single-zoom sampling" approach hiding Y-flip bugs elsewhere in the pipeline.

---

### 10. `write_pipeline_state` (old API) uses `.json.tmp` suffix while `pipeline_progress.update_progress` uses `.tmp` — racy if both write the same file

**Location:** `scripts/acquire_imagery.py:196-212` vs `scripts/pipeline_progress.py:99-105`
**Severity:** minor
**Evidence:** Both files use atomic-rename pattern but with DIFFERENT temp-file suffixes:

```python
# acquire_imagery.py write_pipeline_state:
197:    state_path = Path(output_path).parent / ".pipeline-state.json"
198:    tmp_path = state_path.with_suffix(".json.tmp")   # .pipeline-state.json.tmp

# pipeline_progress.py update_progress:
99:     tmp_path = state_path.with_suffix(".tmp")         # .pipeline-state.tmp
```

`Path("x.json").with_suffix(".json.tmp")` → `x.json.tmp` (replaces `.json`). But `state_path` is already `.pipeline-state.json`, so `.with_suffix(".tmp")` → `.pipeline-state.tmp` (removes `.json`), while `.with_suffix(".json.tmp")` → `.pipeline-state.json.tmp`. So the two use different temp paths — safe but inconsistent.

Actual bug: `update_progress` in `acquire_imagery.py` calls `_generic_progress(...)` (which writes via `.tmp`), then reads the state file (`enriched = json.loads(state_path.read_text())`), mutates it, and writes again via `write_pipeline_state` (which uses `.json.tmp`). **Two atomic renames happen in sequence.** If a reader polls between writes, it sees the state WITHOUT the backward-compat fields `tiles_done/tiles_total/rate_per_sec/started_at/etc.` Consumers that depend on those keys get `KeyError` or wrong values.

**Impact:** Frontend polling at high frequency (e.g., 500ms) has a non-trivial chance of hitting the intermediate state and rendering wrong progress. Documented in `testing-pitfalls.md` under "API field name contracts not verified end-to-end," but this is the write-side manifestation.

**Fix:** `update_progress` should build the full merged dict once and write atomically in ONE rename. Don't call `_generic_progress` and then re-read and re-write.

---

### 11. `run_gdal_subprocess` sets `GDAL_CACHEMAX=1024` default, but NOAA pipeline overrides to 64 via env export

**Location:** `scripts/acquire_imagery.py:756-759` vs `scripts/acquire_imagery.py:1756` vs `scripts/acquire_imagery.py:1659-1663`
**Severity:** minor
**Evidence:** Three conflicting defaults:

- Module constant `_NOAA_GDAL_ENV` (line 1659): `GDAL_CACHEMAX=256`
- `run_noaa` sets `os.environ["GDAL_CACHEMAX"] = "64"` (line 1756)
- `run_gdal_subprocess` reads `os.environ.get("GDAL_CACHEMAX", "1024")` (line 757) and uses that

Because `run_noaa` sets the env BEFORE calling `run_gdal_subprocess` (via `_run_gdaladdo_with_metadata_fixup` → rasterio's build_overviews, and the final gdaladdo), the subprocess inherits `GDAL_CACHEMAX=64`. So the `1024` default in `run_gdal_subprocess` is effectively unreachable in NOAA mode. Meanwhile, `_NOAA_GDAL_ENV` defined at module level (256) is **never used anywhere** — dead code.

`run_m2m` also sets `os.environ.setdefault("GDAL_CACHEMAX", "1024")` at line 1500, then calls `run_gdal_subprocess` for the final `gdaladdo`. setdefault means it only sets if not already set — so if a caller from outside set it, m2m inherits the caller's value. Inconsistent with NOAA's hard-override.

**Impact:** Minor. The 1024 default in `run_gdal_subprocess` is dead-code for NOAA. `_NOAA_GDAL_ENV` is entirely dead. Memory settings inconsistent across modes (NOAA uses 64, M2M uses whatever env has or 1024, NAIP subprocess-level uses 256 from its local `GDAL_ENV`).

**Fix:** Define a single `GDAL_ENV_IMAGERY_PIPELINE` constant and use it consistently. Remove the dead `_NOAA_GDAL_ENV`.

---

### 12. Sentinel STAC search has no Authorization header but OAuth is obtained first

**Location:** `scripts/acquire_sentinel.py:263-304`
**Severity:** significant (depends on Copernicus side)
**Evidence:** `stac_search` does not send an `Authorization` header on either POST (first page) or GET (subsequent pages):

```python
273:        async with session.post(url, json=query) as resp:
...
279:        async with session.get(url) as resp:
```

But the pipeline authenticates via OAuth2 first (line 507: `await auth.authenticate(session)`). The token is stored on `auth.access_token` but is only attached to the later `download_scene` requests (line 383: `headers = {"Authorization": f"Bearer {token}"}`). If Copernicus STAC requires auth for search (which it does for some endpoints; anonymous search is rate-limited or geo-restricted), searches will 401 or return truncated results.

**Impact:** Depending on Copernicus server-side policy: searches may silently return fewer results (unauth'd quota), or return 401 (caught at `if resp.status != 200:` line 274, logged as error, break out of pagination with empty results). Either way, pipeline may say "no scenes found" even though data exists.

Also: GET on `next_url` without re-sending the original query body means pagination relies entirely on the server embedding the filter in the link. Most STAC servers do, but if any parameter is dropped (e.g., cloud-cover filter) the client re-filters with `if cloud <= max_cloud` on line 288 — which correctly discards non-matching scenes but stops pagination on `if not features:` (line 298), even though more filtered results might be available on later pages. Pagination can terminate prematurely.

**Fix:** Pass `Authorization: Bearer {access_token}` on every STAC request. Ensure `auth.ensure_valid_token(session)` is called before each request in the pagination loop (search may take long enough for a token to expire).

---

### 13. `acquire_naip.py` `--concurrency` flag is effectively ignored

**Location:** `scripts/acquire_naip.py:599,666-685`
**Severity:** significant (already in testing-pitfalls.md but still present in code)
**Evidence:** The CLI accepts `--concurrency`, the semaphore is created (line 599), but the main loop awaits each county sequentially:

```python
666:        for idx, (fips, url_info) in enumerate(downloadable):
...
677:            tif_path = await _process_county(fips, url_info)  # awaited
```

The semaphore inside `_process_county` (line 614) wraps the download itself, but only one `_process_county` ever runs at a time, so the semaphore is always 0/N free. Concurrent downloads do not happen.

`testing-pitfalls.md` documents this but the fix has not been applied. Keeping it flagged because it's an active performance bug with user-facing CLI surface area.

**Impact:** `--concurrency 3` behaves identically to `--concurrency 1`. NAIP county batches that could run in parallel (different county GeoTIFFs are independent) take 3× longer than advertised.

**Fix:** Use `asyncio.gather(*[_process_county(fips, info) for fips, info in downloadable])` with the semaphore actually limiting concurrency. Or switch to an `asyncio.as_completed` loop. Ensure the checkpoint save is serialized (per-county update inside `_process_county` via a lock, not the outer loop).

---

### 14. `m2m_login`'s API key is not refreshed — long batched runs risk mid-pipeline 401

**Location:** `scripts/acquire_imagery.py:1505-1584`
**Severity:** minor (USGS tokens are ~2h; batched runs <2h in practice, but no guard)
**Evidence:** `run_m2m` logs in once at line 1508 and reuses the `api_key` for `download-options`, `download-request`, `download-retrieve`, and `logout`. There is no token refresh or re-auth logic. For large multi-batch runs (e.g., NAIP coverage of CA+OR at ~500+ scenes, 10+ batches, each with polling of up to 1h per `_m2m_request_and_poll_urls`), total API-call wall time can exceed the token's 2h lifetime.

**Impact:** Long-running M2M jobs can get a 401 on any API call after token expiry; `m2m_request` treats non-200 as `RuntimeError: f"M2M {endpoint} failed: ..."` (line 1068), which propagates out of the try/finally. The pipeline dies mid-download. The pre-signed download URLs themselves don't need the token, so partial downloads aren't lost — but no scene-options/download-request calls can proceed until re-login. The user has to manually re-run.

**Fix:** Wrap `m2m_request` to catch 401, re-login on 401, retry once. Or track token expiry (USGS doesn't publish token-TTL in the login-token response, but you can pre-emptively re-login every 90 minutes).

---

### 15. In `_rasterize_to_disk`, edge-tile destination-region rounding can drop partial tile content

**Location:** `scripts/rasterio_ops.py:626-648`
**Severity:** minor
**Evidence:** The function handles tiles that extend past the source raster edge by computing dst offsets:

```python
626:    dst_row_start = int((row_start - raw_row_start) / full_row_span * tile_size)
627:    dst_col_start = int((col_start - raw_col_start) / full_col_span * tile_size)
628:    dst_row_end = int((row_end - raw_row_start) / full_row_span * tile_size)
629:    dst_col_end = int((col_end - raw_col_start) / full_col_span * tile_size)
630:
631:    dst_h = max(1, dst_row_end - dst_row_start)
632:    dst_w = max(1, dst_col_end - dst_col_start)
```

`int()` truncates toward zero. If a valid-pixel window spans, say, 127.9 rows, `dst_row_end - dst_row_start` could be 127 while the source actually covers 128 rows. One row of valid pixels gets dropped to zero. Same for columns. At `full_row_span = tile_size = 256` and small windows (edge tiles), truncation can lose ~1-2 rows/cols.

Combined with `_is_empty_tile` (line 653: `not np.any(data)`): a tile that SHOULD have had a thin strip of valid pixels at one edge may end up all-zero after truncation (the valid 1-2 rows fell between the truncations), and then `_is_empty_tile` returns True and the tile is skipped entirely.

**Impact:** At NOAA quad edges, very-thin data strips along a boundary can be dropped. Creates visible gaps or 1-2 pixel seams along quad boundaries. Would also contribute to the inpainting step having more black to fill.

**Fix:** Use `math.floor` for start bounds and `math.ceil` for end bounds to preserve fractional rows/cols, then clip to tile_size. Or use explicit bilinear/nearest resampling that handles fractional offsets correctly.

---

## Design Concerns

### A. Two separate "progress writer" paths (old + new)

`acquire_imagery.py:update_progress` writes via `_generic_progress` then RE-OPENS and RE-WRITES the state file via `write_pipeline_state` to add backward-compat fields. That's two atomic renames for one logical state update, and any consumer polling between them sees a partial state. The fix is straightforward (build full dict once, write once) but requires coordinated changes between the pipeline scripts and consumer code expecting the legacy field names.

### B. Three-stage NOAA pipeline uses two separate thread pools with overlapping CPU budgets

`_reprojector` uses a custom `ThreadPoolExecutor` with `max_workers=min(cpu_count, 6, total_tiles)` threads. `_merger` uses the DEFAULT executor (default ~3 threads, shared across the process) for each `_merge_tile` call. On a 4-core Pi with ~6 reproject threads + ~3 merge-executor threads + asyncio event loop + 8 concurrent downloads, the scheduler thrashes. The 494-quad stress test passed, but scaling beyond 16 GB RAM is not a given. Consider consolidating into a single process-wide executor with a max-thread count pegged to `cpu_count`, and tune `DOWNLOAD_CONCURRENCY` separately because downloads are network-bound.

### C. Checkpoint data lives in the output MBTiles file, not a sidecar

`_noaa_checkpoint` is embedded in `imagery_noaa.mbtiles`. If the MBTiles file is deleted manually (user cleans up to reclaim disk), the checkpoint goes with it, which is fine on a full clear. BUT: if a user COPIES the MBTiles to another machine, the checkpoint table comes along — they can't just delete it without rebuilding the MBTiles. And the table is also exposed to any SQL consumer that queries the MBTiles directly. Non-standard tables in MBTiles are tolerated by TileServer but polluted. Consider moving the checkpoint to `staging/noaa_checkpoint.sqlite` or similar sidecar.

### D. TileServer restart authority is split across two processes

The pipeline script does a final `PRAGMA wal_checkpoint(TRUNCATE)` + `PRAGMA journal_mode=DELETE` at line 2266-2278. The search service ALSO does a WAL checkpoint and TileServer restart at line 1511-1543 in services/search/main.py. Both run on completion. On fast pipeline runs where the search service's reconciliation polling hits "just completed" before the pipeline finishes phase 5, the search service's WAL checkpoint runs against a WAL that's actively being written. The coordination relies on container-death detection — but the pipeline keeps running post-processing INSIDE the container even after "final status" is written. Worth verifying there's no race where the search service restarts TileServer before the erode/inpaint steps flush.

### E. The 64 MB GDAL cache is globally set via `os.environ` — leaks into unrelated code

`run_noaa` at line 1756 does `os.environ["GDAL_CACHEMAX"] = "64"` before importing rasterio. Rasterio reads this at module import time and the cache size is locked for the process. Any subsequent in-process GDAL call (e.g., `build_overviews`, `merge_to_mbtiles`) runs with a 64 MB cache. This is intentional, but it's also a side effect that persists for the process lifetime. If the script is ever run with multiple modes in one process (not today, but possible), the first mode's env override wins.

## Items I did NOT flag (noted but determined not-a-bug)

- `_lonlat_to_tile` clamping (`max(0, min(n-1, x))`) at line 579-580: correct.
- TMS↔slippy y-flip in `_update_mbtiles_bounds`: correct.
- `sentinel` pagination `next_url` following without re-POSTing query: correct per STAC spec, but loses rate-limit auth (see Bug #12).
- `asyncio.gather` in `acquire_sentinel` creating all tasks at once: theoretical memory concern but bounded by scene count which is typically small.
- `_reprojector`'s `asyncio.wait_for(..., timeout=0.5)` polling overhead: wasteful but not broken.
- The `num_threads=1` indentation inside `reproject(...)` at `rasterio_ops.py:248`: unusual but syntactically correct — Python doesn't care about indentation inside parens.
