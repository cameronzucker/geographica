# Bug Hunt Report

## Scope
Analyzed 878 lines across the NOAA NAIP pipeline and BYO import implementation.

**Deep exploration files (high-risk, followed threads):**
- `scripts/acquire_imagery.py` (NOAA mode: ~lines 64-128, 1444-1787, 1836-1861) -- pipeline orchestration, Azure blob integration, external data parsing
- `services/search/main.py` (~lines 81-91, 980-1003, 1038-1331, 1460-1602) -- backend orchestrator, command builder, import endpoints
- `frontend/config/index.html` (~lines 740-777, 1098-1107, 1325-1442, 1596-1641) -- admin panel rendering, source label mapping
- `scripts/import_imagery.py` (full file) -- BYO import pipeline
- `scripts/tileserver_config.py` (full file) -- TileServer config updater

**Adjacent code read for thread-following:**
- `scripts/acquire_imagery.py` lines 585-644 (`convert_batch_to_mbtiles`), 148-269 (`update_progress`), 340-417 (`fetch_to_file`)
- `scripts/pipeline_security.py` (full file) -- `safe_staging_path` and `sanitize_layer_name`
- `docker-compose.yml` (volume mounts for pipeline and tileserver)
- `frontend/app.js` lines 745-750, 3955-3964 (custom layer discovery)

## Bugs

### 1. Frontend hardcodes NOAA source label to "USGS Direct"
**Location:** `frontend/config/index.html:767`
**Severity:** significant
**Evidence:** `renderImageryProgress` normalizes the source field on line 767:
```javascript
normalized.source = d.mode === 'm2m' ? 'm2m' : 'direct';
```
When NOAA mode is active, `d.mode` is `"noaa"` (not `"m2m"`), so it falls through to `"direct"`. `SOURCE_LABELS["direct"]` is `"USGS Direct"` (line 1101). All progress and error messages for NOAA are prefixed with "USGS Direct" instead of "NOAA NAIP".
**Impact:** This is the root cause of the known symptom "USGS Direct failed -- NOAA blob not accessible (HTTP 404)". Users see a confusing "USGS Direct" label for all NOAA pipeline messages.

### 2. Azure Blob Storage HEAD request on directory path returns 404
**Location:** `scripts/acquire_imagery.py:1562-1571`
**Severity:** critical
**Evidence:** The validation phase issues a HEAD request to `blob_base + "/"`:
```python
async with session.head(
    blob_base + "/",
    timeout=aiohttp.ClientTimeout(total=30),
) as resp:
    if resp.status >= 400:
        ...error=f"NOAA blob not accessible (HTTP {resp.status})")
```
`blob_base` is `https://coastalimagery.blob.core.windows.net/digitalcoast/AZ_NAIP_2021_9596`. Azure Blob Storage does not support HEAD requests on virtual directory paths -- it returns 404. The `?restype=container&comp=list` query parameter is needed for container listing, or HEAD must target a specific blob.
**Impact:** NOAA pipeline always fails at validation phase with "NOAA blob not accessible (HTTP 404)" before any actual download begins. The entire NOAA mode is non-functional.

### 3. NOAA tile index fetch assumes HTML directory listing from Azure Blob Storage
**Location:** `scripts/acquire_imagery.py:1478-1501`
**Severity:** critical
**Evidence:** `_noaa_fetch_tile_index` fetches `blob_base + "/"` and parses the response as HTML looking for `href` patterns:
```python
href_pattern = re.compile(r'href=["\']([^"\']*\.(shp|shx|dbf|prj))["\']', re.IGNORECASE)
```
Azure Blob Storage containers don't return HTML directory listings. They return XML via `?restype=container&comp=list` or 404 for bare directory GETs. Even if Bug #2 were fixed, this function would fail to find any shapefile links.
**Impact:** Even if the HEAD validation were bypassed, the tile index fetch would return no results, causing the pipeline to exit with "Failed to fetch NOAA tile index shapefile". The entire tile discovery mechanism is based on incorrect assumptions about Azure Blob Storage behavior.

### 4. TileServer config.json unreachable from pipeline container
**Location:** `scripts/acquire_imagery.py:1762`
**Severity:** significant
**Evidence:** `run_noaa` attempts to update TileServer config at:
```python
config_path = Path(__file__).parent.parent / "tileserver" / "config.json"
```
Inside the pipeline container, `__file__` is `/scripts/acquire_imagery.py`, so `config_path` resolves to `/tileserver/config.json`. But the pipeline container only mounts `./scripts:/scripts:ro` and `./data:/data` (docker-compose.yml lines 209-210). The `./tileserver` directory is NOT mounted, so `config_path.exists()` returns False and the update is silently skipped.
**Impact:** After NOAA download completes, TileServer GL doesn't know about the new `imagery_noaa` MBTiles source. The frontend's `_tryAddTileJSONSource('imagery-noaa', ...)` will 404 forever. Users complete a potentially hours-long NOAA download and the tiles never appear in the map. Manual config.json editing and TileServer restart are required.

### 5. BYO import deletes failed source files when delete_after=True
**Location:** `scripts/import_imagery.py:177-181`
**Severity:** significant
**Evidence:** The delete logic operates at the batch level:
```python
if delete_after and warped_paths:
    for tif in batch:
        if tif.exists():
            tif.unlink()
```
`warped_paths` only contains successfully warped files, but `batch` contains ALL files in the batch. If 1 of 5 files in a batch succeeds but 4 fail reprojection, `warped_paths` is truthy (len=1), and ALL 5 source files are deleted including the 4 that failed.
**Impact:** Users who enable "Delete source files after import" lose files that failed to import, with no way to retry them.

### 6. BYO import progress counter inflated by failed files
**Location:** `scripts/import_imagery.py:183`
**Severity:** minor
**Evidence:** `completed += len(batch)` counts all files in the batch as completed regardless of whether reprojection succeeded:
```python
completed += len(batch)
```
If 3 of 5 files fail, `completed` still advances by 5. Progress is reported to the state file at line 148 using `completed` as `items_done`.
**Impact:** Progress bar shows higher completion percentage than reality. Final "completed" status at line 193-196 reports all files imported when some may have silently failed.

### 7. Backend validation error message is stale for NOAA/nationalmap modes
**Location:** `services/search/main.py:1073`
**Severity:** minor
**Evidence:** The validator accepts four modes but the error message only mentions two:
```python
if not body.mode or body.mode not in ("direct", "m2m", "nationalmap", "noaa"):
    raise HTTPException(status_code=422, detail="mode must be 'direct' or 'm2m'")
```
**Impact:** If a user somehow sends an invalid mode value, they see an error suggesting only 'direct' or 'm2m' are valid, making debugging harder.

### 8. NOAA mode applies wrong disk space estimation and zoom requirement
**Location:** `services/search/main.py:1076,1093-1101`
**Severity:** minor
**Evidence:** Line 1076: `if not is_m2m and not body.zoom:` -- for NOAA mode, `is_m2m` is False, so zoom is required even though NOAA doesn't use zoom levels. Lines 1093-1101: `estimate_tile_count(bbox, zoom_min, zoom_max)` computes web tile counts for the zoom range, then `estimated_size_gb = tile_count * 20 * 1024 / (1024 ** 3)` estimates disk usage based on web tile counts. NOAA downloads ~486 MB GeoTIFFs, not 20 KB web tiles. The estimate is off by orders of magnitude.
**Impact:** The disk space check could falsely reject NOAA starts for small bboxes at high zoom (overestimate) or allow starts that would actually exceed disk space (underestimate at low zoom). The zoom field is also confusingly required for a mode that doesn't use it.

### 9. NOAA "fresh start" (update=false) renames wrong file
**Location:** `services/search/main.py:1159-1165` vs `1210`
**Severity:** minor
**Evidence:** When `body.update` is False, the backend renames the old file: `mbtiles_path = _mbtiles_path_for_type(body.type)` which returns `imagery.mbtiles` for `type="imagery"`. But the NOAA command at line 1210 writes to `imagery_noaa.mbtiles`. So the "fresh start" renames `imagery.mbtiles` (the USGS Direct output) instead of `imagery_noaa.mbtiles`.
**Impact:** Selecting "fresh start" for NOAA mode incorrectly renames the USGS Direct imagery file and doesn't clear the previous NOAA output.

### 10. Successful NOAA runs marked as "interrupted" by status reconciliation
**Location:** `services/search/main.py:1383`
**Severity:** significant
**Evidence:** The status endpoint reconciles dead containers by scanning logs:
```python
elif "MBTiles written to" in (state_data.get("last_logs") or ""):
    new_status = "completed"
else:
    new_status = "interrupted"
```
The NOAA pipeline logs "NOAA pipeline complete: ..." on success (line 1785 of acquire_imagery.py), not "MBTiles written to" (which is only logged by direct and M2M modes at lines 553, 828).
**Impact:** After a successful NOAA download, the status endpoint marks the pipeline as "interrupted" instead of "completed". The admin panel shows a yellow warning instead of a green success indicator.

## Design Concerns

### NOAA tile filenames not validated with safe_staging_path
`scripts/acquire_imagery.py:1636` constructs `staging / tile_filename` where `tile_filename` comes from parsing a remotely-fetched shapefile's CSV output. The `safe_staging_path` function in `pipeline_security.py` was designed for exactly this purpose but is not used. A crafted shapefile could include `../../etc/cron.d/evil.tif` as a tile filename. The risk is low (requires compromising NOAA's Azure Blob Storage) but the security infrastructure exists and isn't being applied.

### Import pipeline has no SIGTERM/cancellation support
`scripts/import_imagery.py` does not set up signal handlers or a `_cancel_requested` flag. It imports `convert_batch_to_mbtiles` from `acquire_imagery`, which checks `acquire_imagery._cancel_requested` -- a flag that is never set in the import process. Docker stop's SIGTERM is ignored, and the container is hard-killed after 30 seconds. Long-running GDAL reprojections of large GeoTIFFs (up to 1 hour per `reproject_geotiff` timeout) will not be interrupted gracefully.

### NOAA catalog is effectively a stub
`NOAA_NAIP_CATALOG` at line 66-69 contains only one entry: `("AZ", 2021)`. The frontend at line 175-177 offers only "Arizona (2021)". The comment says "Additional states to be populated via NOAA Data Access Viewer." This means the NOAA mode is only usable for a single state/year combination.

### Import scan endpoint missing .vrt from other_extensions
`services/search/main.py:1471` has `{".jp2", ".sid", ".img", ".ecw"}` while `import_imagery.py:36` has `{".jp2", ".sid", ".img", ".ecw", ".vrt"}`. The scan endpoint under-counts unsupported geo files.
