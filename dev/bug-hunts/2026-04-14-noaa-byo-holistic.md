# Bug Hunt Report — NOAA NAIP Pipeline + BYO Import (Holistic)

## Scope

Files read in full before analysis:
- `scripts/acquire_imagery.py` — all NOAA additions: `noaa_blob_base_url`, `noaa_cache_dir`, `filter_tiles_by_bbox`, `_noaa_fetch_tile_index`, `run_noaa`, argparse additions; plus existing helpers `convert_batch_to_mbtiles`, `merge_mbtiles`, `fetch_to_file`, `fetch_with_retry`, `update_progress`, M2M pipeline
- `scripts/import_imagery.py` — entire new file
- `scripts/tileserver_config.py` — entire new file
- `scripts/pipeline_security.py` — `sanitize_layer_name` addition
- `services/search/main.py` — NOAA mode + import endpoints (`pipeline_start`, `pipeline_import`, `import_scan`, `pipeline_cancel`)
- `frontend/config/index.html` — NOAA UI, BYO import card, `renderImageryProgress`, `SOURCE_LABELS`, `renderGenericProgress`
- `frontend/app.js` — layer discovery (`_tryAddTileJSONSource` calls)
- `tileserver/config.json` — volume path conventions
- `docker-compose.yml` — volume mounts for tileserver and pipeline
- `docs/plans/2026-04-14-imagery-pipeline-fixes-plan.md` — task 1.1 context

Approach: Read everything first, then traced call chains and data flows to find where invariants break.

---

## Bugs

### B1 — `run_gdal_subprocess` called but never defined or imported (NameError)
**Location:** `scripts/acquire_imagery.py:607`, `scripts/acquire_imagery.py:615`, `scripts/acquire_imagery.py:1429`
**Severity:** critical
**Evidence:** `convert_batch_to_mbtiles` (lines 607, 615) and `run_m2m`'s overview step (line 1429) call `run_gdal_subprocess(...)`. This function is not defined anywhere in `acquire_imagery.py` and is not imported at the top of the file. The plan at `docs/plans/2026-04-14-imagery-pipeline-fixes-plan.md:31-33` describes creating it in `scripts/gdal_subprocess.py`, but that file does not exist. Searching the entire codebase confirms `run_gdal_subprocess` is only referenced, never defined.
**Impact:** Every call to `convert_batch_to_mbtiles` raises `NameError: name 'run_gdal_subprocess' is not defined`.
- In `run_noaa` (line 1725): the NameError is uncaught in the tile processing loop and propagates up through `run_noaa`, crashing the entire NOAA pipeline process.
- In `import_imagery.py` (line 167, via import): the NameError is uncaught in `run_import`, crashing the BYO import process; the `.import-state.json` state file stays "running" forever.
- In `run_m2m`'s `_convert_and_cleanup` closure (line 1125): the NameError is caught by `except Exception` (line 1137), so M2M doesn't crash but every batch conversion silently fails, producing an empty MBTiles.

---

### B2 — NOAA HEAD validation returns 404 from Azure Blob Storage
**Location:** `scripts/acquire_imagery.py:1562-1571`
**Severity:** critical (this is the known symptom)
**Evidence:** The validation step issues `HEAD https://coastalimagery.blob.core.windows.net/digitalcoast/AZ_NAIP_2021_9596/`. Azure Blob Storage REST API does not serve virtual directory URLs. A HEAD to a non-existent blob path returns HTTP 404. There is no blob object at `AZ_NAIP_2021_9596/` — that string is a prefix, not a real path. The code at line 1566 correctly detects `resp.status >= 400` and calls `update_progress(... error=f"NOAA blob not accessible (HTTP {resp.status})")`. This produces the known symptom.
**Impact:** Every NOAA pipeline run fails immediately at the validation phase with "NOAA blob not accessible (HTTP 404)" before any tiles are downloaded.

---

### B3 — `renderImageryProgress` hardcodes `source = 'direct'` for non-M2M modes (NOAA shown as "USGS Direct")
**Location:** `frontend/config/index.html:767`
**Severity:** significant (this is the other half of the known symptom)
**Evidence:** Line 767: `normalized.source = d.mode === 'm2m' ? 'm2m' : 'direct';` — the ternary assigns `'direct'` for any mode that is not `'m2m'`, including `'noaa'`, `'nationalmap'`, and `'direct'`. When the NOAA pipeline reports an error, `d.mode === 'noaa'`, so `normalized.source = 'direct'`. In `renderGenericProgress` (line 1192): `completedEl.textContent = (sourceLabel || 'Download') + ' failed' + ... + d.error`. With `SOURCE_LABELS['direct'] = 'USGS Direct'` (line 1101), the error banner reads "USGS Direct failed — NOAA blob not accessible (HTTP 404)" instead of "NOAA NAIP failed".
**Impact:** The user sees "USGS Direct failed" even when NOAA mode is running. Any other non-M2M mode (nationalmap, noaa) also appears as "USGS Direct" in status/error messages.

---

### B4 — NOAA mode subjected to zoom-based tile count disk space check, causing false 507
**Location:** `services/search/main.py:1093-1100`
**Severity:** significant
**Evidence:** NOAA mode sets `is_m2m = False` (line 1049) since `body.mode != 'm2m'`. The block at line 1093 (`if not is_m2m:`) runs for NOAA, calling `estimate_tile_count(bbox, zoom_min, zoom_max)` with whatever zoom the frontend sends (the zoom field value is always submitted by the frontend at line 1424, since `!isM2M` is true for NOAA). For a western-US bbox at zoom 0-14, this estimates millions of tiles × 20 KB = hundreds of GB. The check at line 1097 (`if disk_free_gb - estimated_size_gb < 10.0`) then raises HTTP 507, blocking NOAA from starting even on a nearly-empty disk.
**Impact:** NOAA pipeline start is blocked with "Insufficient disk space" 507 error even when there is adequate space, because the tile count estimate is meaningless for the GeoTIFF-based NOAA pipeline. NOAA downloads ~486 MB per quad, not per tile.

---

### B5 — TileServer config written with wrong container path in `run_noaa`
**Location:** `scripts/acquire_imagery.py:1764`
**Severity:** significant
**Evidence:** Line 1764: `container_mbtiles = f"/data/{output.name}"`. In the TileServer GL container (see `docker-compose.yml:9-10`), `./tileserver` is mounted as `/data` and `./data` is mounted as `/srv/data`. The existing config.json entries for imagery and elevation use `/srv/data/imagery.mbtiles` and `/srv/data/elevation.mbtiles`. The `import_imagery.py` counterpart (line 188) correctly uses `f"/srv/data/{output_path.name}"`. But `run_noaa` writes `/data/{output.name}`, pointing into the tileserver config directory instead of the data directory.
**Impact:** The TileServer config entry added by `run_noaa` references a non-existent path, so the NOAA MBTiles is never served by TileServer GL even after a successful pipeline run.

---

### B6 — `_noaa_fetch_tile_index` uses wrong URL format for Azure Blob Storage listing
**Location:** `scripts/acquire_imagery.py:1479-1484`
**Severity:** significant
**Evidence:** Line 1479: `index_url = f"{blob_base}/"`. Fetching this URL from Azure Blob Storage returns either a 404 (no such blob) or an empty page, not an HTML listing with `href` links to `.shp/.shx/.dbf/.prj` files. Azure Blob containers with public anonymous read access serve XML via `?restype=container&comp=list&prefix=...`, not HTML directory indexes. The HTML parser at lines 1491-1501 would find no matches, causing `found_files` to be empty, the `.shp` check at line 1503 to fail, and `_noaa_fetch_tile_index` to return `None`.
**Impact:** Even if B2 were fixed (HEAD validation bypassed), Phase 2 (tile index fetch) would immediately fail with "No .shp file found in NOAA blob listing", aborting the pipeline.

---

### B7 — `delete_after` in `import_imagery.py` deletes all batch source files even when some reprojections failed
**Location:** `scripts/import_imagery.py:177-181`
**Severity:** significant
**Evidence:** Lines 147-158: `reproject_geotiff` is called for each file in `batch`; failures are skipped and the file is not added to `warped_paths`. Line 177: `if delete_after and warped_paths:` — if at least one reprojection succeeded, ALL files in `batch` are deleted (line 178: `for tif in batch`). Files that failed reprojection are deleted without being successfully converted to MBTiles. The caller loses their source data with no recourse.
**Impact:** With `delete_after=True`, a partially-failed batch (some files corrupt, some valid) will delete the corrupt source files along with the valid ones. The user loses the corrupt source files permanently without having successfully imported them.

---

### B8 — `pipeline_cancel` does not update the import state file
**Location:** `services/search/main.py:1422-1428`
**Severity:** minor
**Evidence:** The cancel loop at lines 1422-1428 iterates over state files for `"imagery"`, `"elevation"`, `"osm_poi"`, `"sentinel"`, `"naip"` — but not `"import"`. The import state file (`.import-state.json`) is not updated to "cancelling". The container still receives SIGTERM (line 1451), but the state file remains "running" until the pipeline status reconciliation runs.
**Impact:** After cancelling an import pipeline, the import progress card in the admin UI continues to show "running" until the next `fetchAll()` poll reconciles the dead container. The "cancelling" animation does not display for import jobs.

---

### B9 — `raw_path` in `run_noaa` uses untrusted filename directly, no path traversal check
**Location:** `scripts/acquire_imagery.py:1636-1637`
**Severity:** minor
**Evidence:** Line 1636: `raw_path = staging / tile_filename`. The `tile_filename` value comes from the NOAA shapefile attribute via `filter_tiles_by_bbox`. The `safe_staging_path` function from `pipeline_security.py` is available and used in `acquire_naip.py` (line 31 import). `run_noaa` does not use it. If the shapefile has a filename with path separators (e.g., `../../../etc/passwd`), the constructed path escapes the staging directory. Additionally, if `tile_filename` contains a subdirectory component (e.g., `subdir/file.tif`), `staging / tile_filename` creates a nested path whose parent directory doesn't exist, causing `fetch_to_file` to raise `FileNotFoundError` (uncaught in the NOAA tile loop), crashing the pipeline.
**Impact:** Crash if tile filenames from shapefile contain path components. Theoretical path traversal if shapefile is malicious.

---

## Design Concerns

**Azure Blob Storage URL conventions:** The NOAA pipeline assumes Azure blob "directory" URLs behave like HTTP file servers with HTML index pages. Azure serves either XML listings (with `?restype=container&comp=list`) or 404 for virtual directory paths. Both the HEAD validation (B2) and the tile index fetch (B6) use the wrong URL pattern. The correct approach is to use the Azure Blob Storage REST API listing endpoint or pre-enumerate filenames in `NOAA_NAIP_CATALOG`.

**Missing `run_gdal_subprocess` (B1):** The implementation plan (`docs/plans/2026-04-14-imagery-pipeline-fixes-plan.md`) describes creating `scripts/gdal_subprocess.py` as Step 1.1. Call sites in `acquire_imagery.py` were updated to call `run_gdal_subprocess` before the helper was implemented. The partial state means the code compiles but crashes at runtime. Future refactors that update call sites before implementing helpers need an automated check (e.g., a test that imports the module) to catch this.

**NOAA mode not excluded from M2M-style validation bypass:** The `is_m2m` flag gates several validation/estimation steps (zoom required, disk estimate, zoom written to state file). NOAA mode has similar properties to M2M (no per-tile zoom concept, different size model), but no `is_noaa` guard was added. As NOAA and similar GeoTIFF-based modes are added, the boolean flag approach will require adding more guards throughout the validation path.

**`renderImageryProgress` source label (B3):** The function unconditionally maps `mode != 'm2m'` to `source = 'direct'`. This was correct when only `direct` and `m2m` existed. Adding `noaa` and `nationalmap` modes required updating this mapping but didn't. A lookup table (`mode → source label`) would be safer than a binary ternary.
