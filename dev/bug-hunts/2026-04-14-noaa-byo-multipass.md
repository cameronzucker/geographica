# Bug Hunt Report

## Scope

Files analyzed:
- `scripts/acquire_imagery.py` — NOAA additions: `NOAA_NAIP_CATALOG`, `noaa_blob_base_url`, `noaa_cache_dir`, `filter_tiles_by_bbox`, `_noaa_fetch_tile_index`, `run_noaa`, argparse
- `scripts/import_imagery.py` — BYO GeoTIFF import pipeline (entire file)
- `scripts/tileserver_config.py` — `add_mbtiles_to_config` (entire file)
- `scripts/pipeline_security.py` — `sanitize_layer_name` addition
- `services/search/main.py` — NOAA mode + import endpoints (`pipeline_start`, `pipeline_import`, `import_scan`)
- `frontend/config/index.html` — NOAA UI + BYO import card + `renderImageryProgress`
- `frontend/app.js` — layer discovery

Adjacent code reviewed:
- `scripts/acquire_imagery.py` existing code: `convert_batch_to_mbtiles`, `merge_mbtiles`, `update_progress`, `fetch_to_file`
- `scripts/pipeline_progress.py` (via usage)
- `tileserver/config.json`
- `docker-compose.yml`

Passes performed: Pass 1 (Contract Violations), Pass 2 (Cross-Sibling Pattern Violations), Pass 3 (Failure Mode Reasoning), Pass 4 (Concurrency Reasoning), Pass 5 (Error Propagation).

---

## Bugs

### BUG 1 — NOAA HEAD validation always returns HTTP 404 (the known symptom root cause)

**Location:** `scripts/acquire_imagery.py:1562-1571`
**Severity:** Critical
**Evidence:**
```python
async with session.head(
    blob_base + "/",
    timeout=aiohttp.ClientTimeout(total=30),
) as resp:
    if resp.status >= 400:
        ...
        error=f"NOAA blob not accessible (HTTP {resp.status})"
        sys.exit(1)
```
`blob_base` is `https://coastalimagery.blob.core.windows.net/digitalcoast/AZ_NAIP_2021_9596`. Azure Blob Storage does not support HEAD requests against virtual directory paths ending with `/`. The request goes to `https://coastalimagery.blob.core.windows.net/digitalcoast/AZ_NAIP_2021_9596/` which does not correspond to any blob object. Azure returns 404 for this. This causes an immediate pipeline failure before any work is done.

The HEAD check was intended to validate that the blob container is accessible, but the URL pattern `{blob_base}/` is not a valid addressable resource in Azure. The index HTML listing (needed for the next phase) is fetched from the same URL in `_noaa_fetch_tile_index`, which uses `fetch_with_retry` — that function does NOT fail on 404 from `fetch_with_retry` since 404 is logged as a skip, so the HEAD-then-index approach is doubly wrong.

**Impact:** The NOAA pipeline always fails at Phase 1 with "NOAA blob not accessible (HTTP 404)" for every state/year. No downloads ever occur.
**Found in:** Pass 1 — Contract Violations

---

### BUG 2 — `run_gdal_subprocess` called but never defined

**Location:** `scripts/acquire_imagery.py:607, 615, 1429`
**Severity:** Critical
**Evidence:**
```python
# line 607
run_gdal_subprocess(
    ["gdalbuildvrt", str(vrt_path)] + [str(p) for p in tif_paths],
    timeout=600,
    cancel_check=lambda: _cancel_requested,
)
```
`run_gdal_subprocess` is called in `convert_batch_to_mbtiles` (lines 607, 615) and in `run_m2m` (line 1429 for `gdaladdo`), but it is never defined anywhere in `acquire_imagery.py` or in any module imported by it. Searching the entire `scripts/` directory confirms no definition exists.

**Impact:** Every call to `convert_batch_to_mbtiles` raises `NameError: name 'run_gdal_subprocess' is not defined`. This crashes the M2M pipeline during conversion, the NOAA pipeline during tile conversion (`run_noaa` calls `convert_batch_to_mbtiles` at line 1725), and the overview-building step of M2M (line 1429). The BYO import pipeline is also affected since `import_imagery.py` calls `convert_batch_to_mbtiles` at line 167.
**Found in:** Pass 1 — Contract Violations

---

### BUG 3 — UI labels NOAA failures as "USGS Direct failed"

**Location:** `frontend/config/index.html:767`
**Severity:** Significant
**Evidence:**
```javascript
normalized.source = d.mode === 'm2m' ? 'm2m' : 'direct';
```
`renderImageryProgress` sets the source label to `'direct'` for all non-M2M modes, overwriting whatever `d.source` contains from the state file. For NOAA, the state file has `source: "noaa"` and `mode: "noaa"`, but `renderImageryProgress` unconditionally maps all non-m2m modes to `'direct'`. `SOURCE_LABELS['direct']` = `'USGS Direct'`, so the error message shows "USGS Direct failed — NOAA blob not accessible (HTTP 404)" instead of "NOAA NAIP failed".

This is the direct cause of the known symptom. The same incorrect label affects nationalmap mode too (shows "USGS Direct" instead of "National Map NAIP").

**Impact:** Error and status messages for NOAA and nationalmap pipelines are misattributed, confusing users who have selected a different mode than what is shown.
**Found in:** Pass 2 — Cross-Sibling Pattern Violations

---

### BUG 4 — Backend rejects NOAA pipeline start due to missing zoom validation

**Location:** `services/search/main.py:1072-1077`
**Severity:** Significant
**Evidence:**
```python
if body.type in ("imagery", "elevation"):
    if not body.mode or body.mode not in ("direct", "m2m", "nationalmap", "noaa"):
        raise HTTPException(status_code=422, detail="mode must be 'direct' or 'm2m'")
    ...
    if not is_m2m and not body.zoom:
        raise HTTPException(status_code=422, detail="zoom is required for imagery/elevation")
```
Two issues:
1. The mode validation error message says "mode must be 'direct' or 'm2m'" even though `"nationalmap"` and `"noaa"` are valid. A future mis-typed mode gets a misleading error.
2. The zoom check `if not is_m2m and not body.zoom:` does not exclude NOAA. However, the frontend does send a zoom value even for NOAA (line 1423-1424: `if (!isM2M) { body.zoom = zoomEl.value; }`), so the server won't reject it. But zoom is then used in `estimate_tile_count` (line 1094) which runs an incorrect disk space estimate for NOAA (NOAA doesn't download tiles — it downloads ~486 MB GeoTIFFs). A 0-14 zoom estimate over a large bbox could produce a false "Insufficient disk space" 507 error blocking the NOAA pipeline.

**Impact:** When the current bbox+zoom combination results in an estimated size that exceeds free disk (even though NOAA storage needs are calculated differently), NOAA pipeline start is incorrectly blocked with a 507 error. The error message for invalid modes is stale/misleading.
**Found in:** Pass 1 — Contract Violations

---

### BUG 5 — TileServer config path wrong inside pipeline container

**Location:** `scripts/acquire_imagery.py:1762`
**Severity:** Significant
**Evidence:**
```python
config_path = Path(__file__).parent.parent / "tileserver" / "config.json"
```
`__file__` is `/scripts/acquire_imagery.py` inside the pipeline container. `.parent` = `/scripts`. `.parent.parent` = `/`. So `config_path` = `/tileserver/config.json`. The pipeline container mounts `./scripts:/scripts:ro` and `./data:/data` — there is no `/tileserver` mount. `config_path.exists()` is always False, so the `add_mbtiles_to_config` call is always silently skipped.

**Impact:** After a successful NOAA download, `imagery_noaa` is never added to TileServer's `config.json`. The new imagery layer is not served by TileServer and cannot be displayed on the map without manual config intervention.
**Found in:** Pass 3 — Failure Mode Reasoning

---

### BUG 6 — TileServer config path inconsistency: `/data/` vs `/srv/data/`

**Location:** `scripts/acquire_imagery.py:1764` vs `tileserver/config.json:16-23`
**Severity:** Significant
**Evidence:**
```python
# run_noaa (acquire_imagery.py:1764)
container_mbtiles = f"/data/{output.name}"
added = add_mbtiles_to_config(config_path, "imagery_noaa", container_mbtiles)
```
```json
// tileserver/config.json
"elevation": { "mbtiles": "/srv/data/elevation.mbtiles" },
"imagery": { "mbtiles": "/srv/data/imagery.mbtiles" }
```
Existing entries in `config.json` use `/srv/data/` as the prefix. The NOAA addition uses `/data/`. TileServer GL resolves relative paths against `options.paths.root` = `/data`, but absolute paths are used as-is. Using `/data/` would resolve to the correct file inside TileServer's container, while existing entries use `/srv/data/`. This inconsistency means the NOAA entry would resolve differently from other entries — and since the existing entries demonstrably work (production is running), the new `/data/` prefix may point to the wrong location in TileServer's container environment.

Contrast with `import_imagery.py:188`: `f"/srv/data/{output_path.name}"` — correctly uses the same prefix as existing entries.

**Impact:** Even if BUG 5 were fixed, the imagery_noaa entry in config.json would use a different path prefix than working entries, likely causing TileServer to fail to serve NOAA tiles.
**Found in:** Pass 2 — Cross-Sibling Pattern Violations

---

### BUG 7 — `delete_after` deletes source files whose reprojection failed

**Location:** `scripts/import_imagery.py:177-181`
**Severity:** Significant
**Evidence:**
```python
for wp in warped_paths:
    if wp.exists():
        wp.unlink()

if delete_after and warped_paths:
    for tif in batch:      # iterates ALL tif files in the batch
        if tif.exists():
            tif.unlink()
```
`warped_paths` contains only files that were successfully reprojected. If some files in the batch failed reprojection (e.g., 4 out of 5), `warped_paths` is still truthy (1 element). The `delete_after` block then iterates `batch` — which contains ALL 5 source files — and deletes them all. The 4 that failed reprojection and were not imported are permanently deleted.

**Impact:** Users who specify `--delete-after` (or check "delete after import" in the UI) lose source GeoTIFF files that were never imported due to reprojection failures. Data loss with no warning.
**Found in:** Pass 3 — Failure Mode Reasoning

---

### BUG 8 — "MBTiles written to" completion marker absent for NOAA: container exit incorrectly marked as "interrupted"

**Location:** `services/search/main.py:1383` vs `scripts/acquire_imagery.py:1785`
**Severity:** Significant
**Evidence:**
```python
# pipeline_status reconciliation (main.py:1383)
elif "MBTiles written to" in (state_data.get("last_logs") or ""):
    new_status = "completed"
else:
    new_status = "interrupted"
```
```python
# run_noaa success log (acquire_imagery.py:1785)
log.info("NOAA pipeline complete: %d/%d tiles processed (%d failed) → %s",
         tiles_done, total_tiles, tiles_failed, output)
```
The reconciliation logic looks for the string "MBTiles written to" in container logs to distinguish "completed" from "interrupted". This string is written by `run_direct` (line 828) and `run_m2m` (line 1441), but `run_noaa` logs a different completion message that does not contain "MBTiles written to". If the container exits before `update_progress` writes the completed state to the state file (or if the state file write fails), the admin panel permanently shows "NOAA NAIP interrupted" for a successful run.

**Impact:** Successful NOAA runs may display as "interrupted" in the admin panel, causing users to believe something went wrong and potentially re-running the pipeline.
**Found in:** Pass 2 — Cross-Sibling Pattern Violations

---

### BUG 9 — `pipeline_cancel` does not handle NOAA state file

**Location:** `services/search/main.py:1422-1437`
**Severity:** Minor
**Evidence:**
```python
for state_file in [
    _state_file_for_type("imagery"),   # .pipeline-state.json
    _state_file_for_type("elevation"),
    _state_file_for_type("osm_poi"),
    _state_file_for_type("sentinel"),
    _state_file_for_type("naip"),
    # "noaa" is missing — but noaa uses "imagery" type's state file
]:
```
NOAA pipelines write progress to `.pipeline-state.json` (same as `type="imagery"`) and the `"imagery"` state file IS included in the cancel loop. This is technically correct. However the cancel loop uses `pipeline_cancel` which marks state as "cancelling", but `_state_file_for_type("imagery")` maps to `.pipeline-state.json` only when called with "imagery". Since NOAA uses the imagery state file, cancel will work — but only if the state file was created with `type: "imagery"` (which it is, per `pipeline_start`). This is actually correct but fragile — if the type/mode coupling is ever changed, cancellation breaks silently.

**Impact:** No immediate bug, but the coupling between NOAA mode and imagery state file is implicit and undocumented, making future changes risky.
**Found in:** Pass 3 — Failure Mode Reasoning

---

### BUG 10 — `_noaa_fetch_tile_index` silent failure if `fetch_with_retry` returns 404

**Location:** `scripts/acquire_imagery.py:1481-1484`
**Severity:** Minor
**Evidence:**
```python
index_data = await fetch_with_retry(session, index_url, timeout_s=60)
if index_data is None:
    log.error("Failed to fetch NOAA blob listing from %s", index_url)
    return None
```
`fetch_with_retry` only retries on status codes 429, 500, 502, 503, 504. For 404, it logs "HTTP 404 for ... – skipping" and returns `None`. The `_noaa_fetch_tile_index` then logs "Failed to fetch NOAA blob listing" without including the HTTP status code. The error message doesn't distinguish between a network failure and a 404 (wrong URL). If `fetch_with_retry` is ever changed to treat 404 differently, this code would break silently.

Note: This phase is never reached due to BUG 1 (HEAD validation fails first), but if BUG 1 is fixed, BUG 10 may surface.

**Impact:** Error messages in index-fetch phase are vague, making diagnosis harder.
**Found in:** Pass 5 — Error Propagation

---

### BUG 11 — `shp_extensions` declared but unused in `_noaa_fetch_tile_index`

**Location:** `scripts/acquire_imagery.py:1490`
**Severity:** Minor
**Evidence:**
```python
shp_extensions = {".shp", ".shx", ".dbf", ".prj"}
href_pattern = re.compile(r'href=["\']([^"\']*\.(shp|shx|dbf|prj))["\']', re.IGNORECASE)
```
`shp_extensions` is defined but never referenced. The pattern is hardcoded inline. No functional impact — dead code.

**Impact:** None (dead code).
**Found in:** Pass 1 — Contract Violations

---

### BUG 12 — Naive CSV split in `filter_tiles_by_bbox` breaks on embedded commas

**Location:** `scripts/acquire_imagery.py:123`
**Severity:** Minor
**Evidence:**
```python
cols = line.split(",")
```
ogr2ogr CSV output can include quoted fields with embedded commas. For example, a description field `"AZ, Maricopa"` would produce `cols` that splits incorrectly. The column index `fname_idx` would then point to the wrong column for subsequent rows. NOAA shapefile filenames are unlikely to contain commas, but the parser is fragile.

**Impact:** If any CSV row has a quoted field with a comma appearing before the filename column, all rows after that point parse with wrong column offsets, returning empty filename list.
**Found in:** Pass 1 — Contract Violations

---

## Design Concerns

**NOAA catalog is hardcoded with only one entry.** `NOAA_NAIP_CATALOG` has a single entry: `("AZ", 2021): "AZ_NAIP_2021_9596"`. The UI only presents AZ as an option in the dropdown. The state selector in the frontend shows only Arizona. Adding any other state requires code changes in two places (catalog dict + HTML option). The catalog comment `# Additional states to be populated via NOAA Data Access Viewer` acknowledges this but provides no mechanism for the operator to add states without editing the Python source.

**`run_noaa` processes tiles serially with no resume support.** Unlike M2M (which has a checkpoint file), NOAA processes each tile sequentially with no persisted checkpoint. If the container is killed mid-run (e.g., OOM, SIGKILL), the entire tile list is re-downloaded on restart. At ~486 MB per tile, this could waste hours of work.

**`convert_batch_to_mbtiles` catches `subprocess.CalledProcessError` but not `NameError`.** BUG 2 (`run_gdal_subprocess` undefined) causes a `NameError` at the start of `convert_batch_to_mbtiles`. The function's `try/except` catches `subprocess.CalledProcessError` and `subprocess.TimeoutExpired` but not `NameError`. The `NameError` propagates up through `run_noaa` and `run_import`, leaving temp files uncleaned in the `finally` block (since `vrt_path` and `temp_mbtiles` are never created, their `.exists()` calls will be False — so cleanup is safe, but the error reporting is poor).

**`import_imagery.py` always completes "successfully" even if all batches fail.** If every batch conversion fails (e.g., due to BUG 2), `run_import` still calls `_generic_progress(..., status="completed")` at line 193. The function has no check for `success` across all batches. An operator would see "Import complete" in the admin panel for a run that produced zero tiles.
