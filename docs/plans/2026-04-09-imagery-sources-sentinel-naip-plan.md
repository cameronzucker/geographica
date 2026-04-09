# Imagery Sources: Sentinel-2 + USDA NAIP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two new free imagery pipelines (Sentinel-2 and USDA NAIP county mosaics) with a generalized progress model, independent frontend layer toggles, and a bundled county lookup database.

**Architecture:** New pipeline scripts (`acquire_sentinel.py`, `acquire_naip.py`) download imagery from Copernicus STAC API and USDA Gateway respectively, process through GDAL, and produce separate MBTiles files. A shared `pipeline_progress.py` module replaces inline progress tracking across all pipeline scripts. The frontend gets independent layer toggles that read maxzoom from TileJSON dynamically.

**Tech Stack:** Python 3 (aiohttp, aiosqlite, tqdm), GDAL CLI, SQLite rtree, MapLibre GL JS, FastAPI, Docker

**Spec:** `docs/superpowers/specs/2026-04-09-imagery-sources-sentinel-naip-design.md`

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `scripts/pipeline_progress.py` | Shared progress tracking: atomic state file writes with generic fields |
| `scripts/pipeline_security.py` | Shared security utils: filename sanitization, magic byte checks, path validation |
| `scripts/build_county_index.py` | One-time script: download TIGER/Line data, build counties.sqlite with rtree |
| `scripts/acquire_sentinel.py` | Sentinel-2 pipeline: STAC search, download COGs, composite, MBTiles |
| `scripts/acquire_naip.py` | NAIP pipeline: county lookup, download JP2, per-county convert, MBTiles |
| `data/counties.sqlite` | Bundled county boundary database (~5MB, committed to repo) |
| `tests/test_pipeline_progress.py` | Tests for generic progress model |
| `tests/test_pipeline_security.py` | Tests for security utilities |
| `tests/test_county_lookup.py` | Tests for bbox to county intersection |
| `tests/test_acquire_sentinel.py` | Tests for Sentinel-2 pipeline logic |
| `tests/test_acquire_naip.py` | Tests for NAIP pipeline logic |

### Modified files
| File | Changes |
|------|---------|
| `scripts/acquire_imagery.py` | Replace inline `update_progress()` + `write_pipeline_state()` with import from `pipeline_progress.py` |
| `scripts/download_elevation.py` | Replace inline `write_pipeline_state()` with import from `pipeline_progress.py` |
| `services/search/main.py` | Add sentinel/naip to helper functions, new endpoints, cancel loop, credential handling |
| `frontend/app.js` | Migrate imagery source to TileJSON URL form, add NAIP/Sentinel-2 layer toggles |
| `frontend/config/index.html` | New pipeline cards, generic progress renderer, Copernicus credentials section |
| `nginx/nginx.conf` | Add sub_filter rules for new TileJSON endpoints |

---

## Task Groups

Tasks are organized into dependency groups. Groups 1-2 are independent and can run in parallel. Group 3 depends on 1. Groups 4-5 depend on 1+3. Group 6 depends on all prior groups.

---

### Task 1: Shared Progress Module (`pipeline_progress.py`)

BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/ (or invoke /test-driven-development)
2. Read docs/pitfalls/testing-pitfalls.md

Follow TDD: write failing test, implement fix, verify green.

**Files:**
- Create: `scripts/pipeline_progress.py`
- Create: `tests/test_pipeline_progress.py`

- [ ] **Step 1: Write failing tests for the progress module**

Create `tests/test_pipeline_progress.py` with these test cases:

1. `test_basic_write` - Writes all required fields (source, status, phase, items_done, items_total, item_unit, detail, last_updated, started_at) to state file
2. `test_merge_preserves_existing_fields` - Pre-write some fields (type, bbox, estimated_tiles), then call update_progress, verify old fields preserved alongside new
3. `test_bytes_tracking` - bytes_done and bytes_total written correctly
4. `test_completed_status_value` - Uses "completed" (not "complete") to match existing consumers
5. `test_error_state` - Error status includes error message field
6. `test_atomic_write_no_corruption` - No .tmp file left behind, valid JSON written
7. `test_bbox_and_zoom_optional` - bbox and zoom are optional; zoom defaults to None when not passed

Use `tempfile.mkdtemp()` for state file paths. Import from `scripts.pipeline_progress`.

Test code for `test_basic_write`:
```python
def test_basic_write(self):
    update_progress(self.state_path,
                    source="naip", status="running", phase="downloading",
                    items_done=5, items_total=100, item_unit="counties",
                    detail="Maricopa County, AZ")
    data = json.loads(self.state_path.read_text())
    assert data["source"] == "naip"
    assert data["status"] == "running"
    assert data["phase"] == "downloading"
    assert data["items_done"] == 5
    assert data["items_total"] == 100
    assert data["item_unit"] == "counties"
    assert data["detail"] == "Maricopa County, AZ"
    assert "last_updated" in data
    assert "started_at" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_pipeline_progress.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.pipeline_progress'`

- [ ] **Step 3: Implement `pipeline_progress.py`**

Create `scripts/pipeline_progress.py` with function:

```python
def update_progress(state_path: Path, *,
                    source: str,
                    status: str,
                    phase: str = None,
                    items_done: int = 0,
                    items_total: int = 0,
                    item_unit: str = "",
                    bytes_done: int = 0,
                    bytes_total: int = 0,
                    detail: str,
                    error: str = None,
                    bbox: str = None,
                    zoom: str = None):
```

Implementation requirements:
- Atomic write via tmp file + `os.replace()` + `os.fsync()`
- Merge new fields into existing state (preserves search service metadata)
- Track `started_at` on first call, `last_updated` on every call
- Only include optional fields (phase, error, bbox, zoom) when not None

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_pipeline_progress.py -v`
Expected: All 7+ tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_progress.py tests/test_pipeline_progress.py
git commit -m "feat: add generalized pipeline progress module"
```

BEFORE marking this task complete:
1. Review your tests against docs/pitfalls/testing-pitfalls.md
2. Verify test coverage of the fix (are error paths tested? edge cases?)
3. Run tests and confirm green

---

### Task 2: Security Utilities (`pipeline_security.py`)

BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/ (or invoke /test-driven-development)
2. Read docs/pitfalls/testing-pitfalls.md

Follow TDD: write failing test, implement fix, verify green.

**Files:**
- Create: `scripts/pipeline_security.py`
- Create: `tests/test_pipeline_security.py`

- [ ] **Step 1: Write failing tests for security utilities**

Create `tests/test_pipeline_security.py` with tests for 4 functions:

`safe_staging_path(staging_dir, filename)`:
- `test_valid_filename` - Returns staging_dir / filename for clean names
- `test_rejects_path_traversal_dotdot` - Raises ValueError for "../etc/passwd"
- `test_rejects_absolute_path` - Raises ValueError for "/etc/passwd"
- `test_rejects_null_bytes` - Raises ValueError for "file\x00.tif"
- `test_rejects_backslash` - Raises ValueError for "..\\etc\\passwd"

`validate_file_header(file_path, expected_format)`:
- `test_valid_geotiff_little_endian` - Returns True for b"II\x2a\x00" header
- `test_valid_geotiff_big_endian` - Returns True for b"MM\x00\x2a" header
- `test_valid_jp2` - Returns True for b"\x00\x00\x00\x0cjP" header
- `test_rejects_wrong_format` - Returns False for HTML content
- `test_rejects_empty_file` - Returns False for empty file

`sanitize_scene_id(scene_id)`:
- `test_valid_scene_id` - Returns unchanged for "S2B_MSIL2A_20260401T123456"
- `test_scene_id_strips_special_chars` - Replaces non-alphanumeric with underscores

`sanitize_fips(fips)`:
- `test_valid_fips` - Returns "04013" unchanged
- `test_fips_rejects_non_numeric` - Raises ValueError for "0401X"
- `test_fips_rejects_wrong_length` - Raises ValueError for "123"

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_pipeline_security.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement `pipeline_security.py`**

Create `scripts/pipeline_security.py` with the 4 functions. Key implementation details:
- `safe_staging_path`: Check for null, "..", "/", "\\" in filename. Then verify `result.resolve().is_relative_to(staging_dir.resolve())`
- `validate_file_header`: Read first N bytes, compare against magic byte signatures
- `sanitize_scene_id`: `re.sub(r"[^a-zA-Z0-9_]", "_", scene_id).strip("_")`
- `sanitize_fips`: `re.match(r"^\d{5}$", fips)` or raise ValueError

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_pipeline_security.py -v`
Expected: All 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_security.py tests/test_pipeline_security.py
git commit -m "feat: add pipeline security utilities"
```

BEFORE marking this task complete:
1. Review your tests against docs/pitfalls/testing-pitfalls.md
2. Verify test coverage (path traversal, null bytes, empty files, wrong format)
3. Run tests and confirm green

---

### Task 3: County Lookup Database

BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/ (or invoke /test-driven-development)
2. Read docs/pitfalls/testing-pitfalls.md
3. Read docs/pitfalls/implementation-pitfalls.md - NOTE Pitfall #1: large data goes to /srv/geographica/data/, but counties.sqlite is small (5MB) and committed to repo per spec.

Follow TDD: write failing test, implement fix, verify green.

**Files:**
- Create: `scripts/build_county_index.py`
- Create: `tests/test_county_lookup.py`
- Create: `data/counties.sqlite` (generated by build script)

- [ ] **Step 1: Write failing tests for county lookup**

Create `tests/test_county_lookup.py`. **IMPORTANT: Use a real in-memory SQLite database with real schema and data. Do NOT mock SQLite (see testing pitfall #1).**

Create a `_create_test_db(db_path)` helper that inserts 5 known counties (Maricopa AZ, Pima AZ, Los Angeles CA, San Diego CA, Clark NV) with their real approximate bounding boxes.

Test cases for `counties_for_bbox(db_path, west, south, east, north)`:
- `test_bbox_covering_phoenix` - Finds Maricopa, not Los Angeles
- `test_bbox_spanning_az_ca` - Finds counties in both states
- `test_bbox_outside_us` - Returns empty list
- `test_single_county_bbox` - Tight bbox around San Diego finds it
- `test_results_ordered_by_state_and_name` - AZ before CA before NV

Test cases for `estimate_download_gb(total_area_sq_km)`:
- `test_estimate_formula` - Maricopa (23828 sq km) estimates ~9.5 GB
- `test_zero_area` - Returns 0.0

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_county_lookup.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement `build_county_index.py`**

Create `scripts/build_county_index.py` with:
- `counties_for_bbox(db_path, west, south, east, north)` - query function using rtree
- `estimate_download_gb(total_area_sq_km)` - heuristic: area * 0.4 / 1000
- `build_database(output_path, shapefile_path=None)` - downloads TIGER/Line and builds SQLite
- CLI entry point with --output and optional --shapefile args

Schema: `counties` table (fips, name, state_fips, state_abbr, area_sq_km, min_lon, min_lat, max_lon, max_lat) + `counties_rtree` virtual table.

Include `STATE_FIPS` dict mapping 2-digit FIPS to state abbreviations.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_county_lookup.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Build the actual `counties.sqlite` and add `.gitattributes`**

Run: `python scripts/build_county_index.py --output data/counties.sqlite`

Add to `.gitattributes`: `data/counties.sqlite binary`

- [ ] **Step 6: Commit**

```bash
git add scripts/build_county_index.py tests/test_county_lookup.py data/counties.sqlite .gitattributes
git commit -m "feat: add county lookup database with rtree spatial index"
```

BEFORE marking this task complete:
1. Review tests against docs/pitfalls/testing-pitfalls.md - uses real SQLite, not mocks (Pitfall #1)
2. Verify counties.sqlite was generated and is reasonable size (~5MB)
3. Run tests and confirm green

---

After Tasks 1-3, review:

After every logical group of tasks:
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues. Then
update your private journal and continue onto the next tasks.

---

### Task 4: Backend Route Additions (`services/search/main.py`)

BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/ (or invoke /test-driven-development)
2. Read docs/pitfalls/testing-pitfalls.md
3. Read docs/pitfalls/implementation-pitfalls.md - NOTE Pitfall #10: Config panel is localhost-only, admin endpoints require X-Config-Source header.

**Files:**
- Modify: `services/search/main.py:893-914` (helper functions), `:937-941` (type validation), `:1245-1253` (cancel loop)

**IMPORTANT:** This task modifies a shared file. No other task should modify `services/search/main.py`.

- [ ] **Step 1: Update `_state_file_for_type()` at line 893**

Current code returns `.pipeline-state.json` for unknown types. Add sentinel and naip cases:
- `"sentinel"` returns `DATA_DIR / ".sentinel-state.json"`
- `"naip"` returns `DATA_DIR / ".naip-state.json"`

- [ ] **Step 2: Update `_mbtiles_path_for_type()` at line 902**

Add:
- `"sentinel"` returns `DATA_DIR / "imagery_sentinel.mbtiles"`
- `"naip"` returns `DATA_DIR / "imagery_naip.mbtiles"`

- [ ] **Step 3: Update `_script_for_type()` at line 909**

Add:
- `"sentinel"` returns `"/scripts/acquire_sentinel.py"`
- `"naip"` returns `"/scripts/acquire_naip.py"`

- [ ] **Step 4: Update type validation in `pipeline_start()` at line 941**

Change allowlist from `("imagery", "elevation", "osm_poi")` to `("imagery", "elevation", "osm_poi", "sentinel", "naip")`

- [ ] **Step 5: Add validation branches for sentinel and naip in `pipeline_start()`**

After the existing `is_m2m` block (~line 948), add:
- `is_sentinel`: require bbox, check Copernicus credentials exist in credentials.json (keys `copernicus_username` and `copernicus_password`)
- `is_naip`: require bbox only (no credentials needed)

- [ ] **Step 6: Add command construction for sentinel and naip**

In the command construction section (~line 1039), add branches:
- Sentinel: `python3 /scripts/acquire_sentinel.py --bbox=... --output /data/imagery_sentinel.mbtiles --staging /data/sentinel_staging` + optional date/cloud/composite args
- NAIP: `python3 /scripts/acquire_naip.py --bbox=... --output /data/imagery_naip.mbtiles --staging /data/naip_staging --counties-db /data/counties.sqlite`

- [ ] **Step 7: Add Copernicus env vars for sentinel**

Pass `COPERNICUS_USERNAME` and `COPERNICUS_PASSWORD` via environment variables to the pipeline container (same pattern as M2M at line 1070-1071). Never mount credentials.json.

- [ ] **Step 8: Update `pipeline_cancel()` at line 1249**

Add `_state_file_for_type("sentinel")` and `_state_file_for_type("naip")` to the cancel loop.

- [ ] **Step 9: Add county lookup endpoint**

Add `GET /admin/pipeline/naip/counties` endpoint that:
- Parses bbox query param to floats
- Queries counties.sqlite via `counties_for_bbox()`
- Enforces max 1000 counties (return 422 if exceeded)
- Returns JSON with counties list, total_counties, states, estimated_gb

- [ ] **Step 10: Add TileServer config update helper**

Add `_register_mbtiles_with_tileserver(client, mbtiles_name, source_id)` that:
- Reads current tileserver/config.json (resolve host path from SCRIPTS_HOST_PATH env var)
- Adds new data source entry if not present
- Restarts tileserver container via Docker API

- [ ] **Step 11: Run existing tests**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/ -v --ignore=tests/test_acquire_sentinel.py --ignore=tests/test_acquire_naip.py`
Expected: All existing tests PASS

- [ ] **Step 12: Commit**

```bash
git add services/search/main.py
git commit -m "feat: add sentinel/naip pipeline types to backend"
```

BEFORE marking this task complete:
1. Review against docs/pitfalls/implementation-pitfalls.md
2. Verify _state_file_for_type returns distinct paths for all 5 types
3. Run tests and confirm green

---

### Task 5: Migrate Existing Scripts to Shared Progress Module

**Depends on:** Task 1 (pipeline_progress.py must exist)

**Files:**
- Modify: `scripts/acquire_imagery.py:74-141`
- Modify: `scripts/download_elevation.py:59-82`

**IMPORTANT:** Maintain backward compatibility. State files must contain BOTH old-format fields (tiles_done, geotiffs_downloaded) AND new-format fields (items_done, items_total).

- [ ] **Step 1: Migrate `acquire_imagery.py`**

Add `from pipeline_progress import update_progress as _generic_progress` at top.

Replace the `update_progress` function body to:
1. Map old params to generic format (tiles_done to items_done for direct mode, geotiffs_downloaded to items_done for M2M downloading phase)
2. Call `_generic_progress()` to write the new-format fields
3. Then re-read the state file and add backward-compat fields (tiles_done, tiles_total, rate_per_sec, mode, geotiffs_downloaded, etc.)

Remove the old standalone `write_pipeline_state()` (lines 74-95) - the shared module handles atomic writes.

- [ ] **Step 2: Migrate `download_elevation.py`**

Add `from pipeline_progress import update_progress as _generic_progress` at top.

Replace `write_pipeline_state()` (lines 59-81) to:
1. Call `_generic_progress()` with mapped params (tiles_done to items_done, source="elevation")
2. Re-read and add backward-compat fields (the old state dict keys)

- [ ] **Step 3: Run existing tests to verify backward compatibility**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/acquire_imagery.py scripts/download_elevation.py
git commit -m "refactor: migrate existing scripts to shared progress module"
```

BEFORE marking this task complete:
1. Verify both old-format (tiles_done) and new-format (items_done) fields are written
2. Run ALL existing tests and confirm green

---

### Task 6: Frontend Dynamic TileJSON Sources + Layer Toggles

BEFORE starting work:
1. Read docs/pitfalls/implementation-pitfalls.md - NOTE Pitfall #9: New frontend features in separate modules. Layer toggles are tightly coupled to map init, so app.js changes are appropriate.
2. Read docs/pitfalls/implementation-pitfalls.md - NOTE Pitfall #11: MapLibre dragRotate pattern. Be aware of existing camera code.

**Files:**
- Modify: `frontend/app.js:155-195` (addPlaceholderSources)
- Modify: `frontend/app.js` (layer toggle section)

**CRITICAL WARNING:** Do NOT hardcode any numeric `maxzoom` value in any imagery source definition. Use `{ url: tilejson_url }` form exclusively.

- [ ] **Step 1: Migrate existing imagery source to TileJSON URL form**

In `addPlaceholderSources()` at line 157-163, replace:
```js
map.addSource('imagery', {
  type: 'raster',
  tiles: ['/tiles/data/imagery/{z}/{x}/{y}.jpeg'],
  tileSize: 256,
  maxzoom: 18
});
```
With:
```js
// CORRECTNESS: Use TileJSON URL form. maxzoom from MBTiles metadata via TileServer.
// Prevents bug B1 where hardcoded maxzoom blocked higher-res tiles.
map.addSource('imagery', {
  type: 'raster',
  url: '/tiles/data/imagery.json'
});
```

- [ ] **Step 2: Add `_tryAddTileJSONSource` helper function**

Add before `addPlaceholderSources`:
- `_availableTileJSON` object to track which sources are available
- `_tryAddTileJSONSource(sourceId, tileJsonUrl, sourceType)` that fetches TileJSON, adds source + layer if successful, calls `_updateImageryToggles()`
- `_firstSymbolLayer()` helper to find insert-before position

- [ ] **Step 3: Call `_tryAddTileJSONSource` for new layers**

At end of `addPlaceholderSources()`, add calls for:
- `_tryAddTileJSONSource('imagery-naip', '/tiles/data/imagery_naip.json', 'raster')`
- `_tryAddTileJSONSource('imagery-sentinel', '/tiles/data/imagery_sentinel.json', 'raster')`

- [ ] **Step 4: Add layer toggle UI with sublabels**

Add `_updateImageryToggles()` and `_makeLayerToggle(layerId, label, sublabel)` functions that:
- Find or create a container div for imagery toggles
- Show toggles only for available sources
- Labels: "USGS Legacy (varies)", "NAIP Aerial (0.6m, US)", "Sentinel-2 (10m, global)"
- Use DOM creation methods (createElement, appendChild), NOT string-based HTML building

- [ ] **Step 5: Add periodic TileJSON polling**

Add `setInterval` every 30 seconds that resets `_availableTileJSON` cache and re-checks for new sources.

- [ ] **Step 6: Verify no numeric maxzoom in imagery sources**

Run: `grep -n "maxzoom.*[0-9]" frontend/app.js | grep -i "imagery"`
Expected: No matches

- [ ] **Step 7: Commit**

```bash
git add frontend/app.js
git commit -m "feat: dynamic TileJSON sources + layer toggles for NAIP/Sentinel-2"
```

BEFORE marking this task complete:
1. Verify NO numeric maxzoom in any imagery addSource call
2. Verify existing imagery layer still works with TileJSON form
3. Verify layer toggles render correctly

---

### Task 7: Admin Console Pipeline Cards + Generic Progress Renderer

BEFORE starting work:
1. Read docs/pitfalls/implementation-pitfalls.md - NOTE Pitfall #10: Config panel is localhost-only.
2. Read docs/pitfalls/implementation-pitfalls.md - NOTE Pitfall #3: NGINX sub_filter only on style JSON and TileJSON.

**Files:**
- Modify: `frontend/config/index.html`

**IMPORTANT:** This is a large file (1152 lines). No other task should modify this file.

- [ ] **Step 1: Add Sentinel-2 pipeline card**

Add new collapsed card with: header ("Sentinel-2 Imagery (ESA)"), status line, bbox shared minimap, progressive disclosure toggle for advanced options (date range pickers, cloud cover slider 0-100% default 20%, composite/single toggle), Copernicus credential check with registration link, pre-download estimation display.

- [ ] **Step 2: Add NAIP pipeline card**

Add new collapsed card with: header ("NAIP Aerial Imagery (USDA)"), bbox shared minimap, county confirmation area (scrollable max-height 300px, grouped by state), summary line ("347 counties, ~142 GB"), start download button, no credentials.

- [ ] **Step 3: Refactor progress renderer to generic model**

Replace source-specific renderers with generic one that reads: source (for label), phase, items_done/items_total (progress bar), item_unit, bytes_done (formatted), detail (context line). Add backward compat: if items_done absent but tiles_done exists, use tiles_done.

- [ ] **Step 4: Add Copernicus credentials section to Settings tab**

After M2M section: username field, password field, test connection button, registration link to dataspace.copernicus.eu.

- [ ] **Step 5: Grey out Start buttons when pipeline running**

Check all state files. If any has status "running", disable all other Start buttons with tooltip.

- [ ] **Step 6: Add header text**

At top of Pipelines tab: "Pipelines run one at a time. Recommended order: imagery first, then elevation, then OSM POIs."

- [ ] **Step 7: Commit**

```bash
git add frontend/config/index.html
git commit -m "feat: admin console pipeline cards for Sentinel-2 + NAIP"
```

BEFORE marking this task complete:
1. Review against docs/pitfalls/implementation-pitfalls.md
2. Verify all 4 pipeline cards render
3. Verify generic progress renderer handles both old and new format

---

### Task 8: NGINX Sub-filter Rules

**Files:**
- Modify: `nginx/nginx.conf`

- [ ] **Step 1: Read existing nginx.conf to find TileJSON sub_filter pattern**

- [ ] **Step 2: Add sub_filter rules for new TileJSON endpoints**

Add location blocks for `/tiles/data/imagery_naip.json` and `/tiles/data/imagery_sentinel.json` following the exact same pattern as existing imagery TileJSON location block. Proxy to tileserver:8080, set Accept-Encoding "", apply sub_filter for hostname rewriting.

- [ ] **Step 3: Commit**

```bash
git add nginx/nginx.conf
git commit -m "feat: add NGINX sub_filter rules for NAIP/Sentinel-2 TileJSON"
```

---

After Tasks 4-8, review:

After every logical group of tasks:
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues. Then
update your private journal and continue onto the next tasks.

---

### Task 9: Sentinel-2 Pipeline Script

BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/ (or invoke /test-driven-development)
2. Read docs/pitfalls/testing-pitfalls.md
3. Read docs/pitfalls/implementation-pitfalls.md - NOTE Pitfall #6: Offline-first design.

**Depends on:** Tasks 1, 2 (pipeline_progress.py and pipeline_security.py)

**Files:**
- Create: `scripts/acquire_sentinel.py`
- Create: `tests/test_acquire_sentinel.py`

- [ ] **Step 1: Write failing tests**

Test cases (use mocked HTTP for API calls, NOT real STAC):
- STAC query parameter construction (bbox, date range, cloud cover filter)
- Scene filtering (max cloud percentage, pagination cap at 100 pages)
- OAuth2 token refresh logic (expired token triggers refresh, uses refresh_token)
- Filename sanitization (deterministic from scene ID: `sentinel_{sanitized_id}.tif`)
- File validation (magic byte check for GeoTIFF before GDAL)
- Search checkpoint save/load (searched_scenes.json)
- Spatial chunk calculation (large bbox split into 2x2 degree chunks)

- [ ] **Step 2: Implement `acquire_sentinel.py`**

Key implementation requirements from spec:
- OAuth2 auth with token refresh (10 min expiry, 60s buffer)
- STAC search: `https://catalogue.dataspace.copernicus.eu/stac/search`
- Pagination cap: max 100 pages
- Download COGs with deterministic filenames
- Spatial chunking for large bboxes (2x2 degree)
- GDAL composite: `gdalbuildvrt` + `gdal_translate -of MBTiles` + `gdaladdo`
- `GDAL_CACHEMAX=256`, `GDAL_NUM_THREADS=2`
- `nice -n 19`, `ionice -c2 -n7` on GDAL subprocesses
- Search checkpoint: `searched_scenes.json` in staging dir
- File validation: magic bytes + size cap (5 GB per scene)
- `# SECURITY: Never set ssl=False or verify_ssl=False`
- Disk check before each download (< 10 GB free means error)
- Progress via `pipeline_progress.update_progress()`
- SIGTERM handler for graceful shutdown

- [ ] **Step 3: Run tests**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_acquire_sentinel.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/acquire_sentinel.py tests/test_acquire_sentinel.py
git commit -m "feat: add Sentinel-2 pipeline script"
```

BEFORE marking this task complete:
1. Review tests - mocked HTTP is OK for API logic tests
2. Verify security: deterministic filenames, magic byte checks, TLS not disabled
3. Run tests and confirm green

---

### Task 10: NAIP Pipeline Script

BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/ (or invoke /test-driven-development)
2. Read docs/pitfalls/testing-pitfalls.md
3. Read docs/pitfalls/implementation-pitfalls.md

**Depends on:** Tasks 1, 2, 3 (pipeline_progress.py, pipeline_security.py, counties.sqlite)

**Files:**
- Create: `scripts/acquire_naip.py`
- Create: `tests/test_acquire_naip.py`

- [ ] **Step 1: Write failing tests**

Test cases:
- County lookup from bbox (use REAL SQLite test DB, per testing pitfall #1)
- USDA Gateway URL discovery (mocked HTTP)
- Format preference (JP2 preferred; MrSID-only county skipped with warning)
- Per-county streaming conversion logic (download, convert, delete cycle)
- Checkpoint save/load for downloaded counties
- Filename sanitization (deterministic: `naip_{fips}.jp2`)
- File validation (magic bytes for JP2)
- Disk space check logic (< 10 GB means error)
- GDAL driver self-check (JP2OpenJPEG availability)
- Skipped counties tracking in state file

- [ ] **Step 2: Implement `acquire_naip.py`**

Key implementation requirements from spec:
- County lookup: `from build_county_index import counties_for_bbox`
- USDA Gateway discovery: parse ASPX page, validate URLs with HEAD, prefer JP2
- Download with deterministic filenames: `naip_{fips}.jp2`
- **Per-county streaming conversion:** download JP2, convert to GeoTIFF, append to MBTiles, DELETE staging files immediately (critical for disk safety)
- JP2-only; skip MrSID counties with warning in progress detail
- GDAL self-check: `gdalinfo --formats` must include JP2OpenJPEG
- `GDAL_CACHEMAX=256`, `GDAL_NUM_THREADS=2`
- `nice -n 19`, `ionice -c2 -n7` on GDAL subprocesses
- Checkpoint per county: `checkpoint.json`
- Discovered URLs cache: `discovered_urls.json`
- File validation: magic bytes + size cap (30 GB per county)
- `# SECURITY: Never set ssl=False or verify_ssl=False`
- Disk check before each county (< 10 GB free means error)
- Progress via `pipeline_progress.update_progress()`
- Track skipped counties: `skipped_counties` list in state file
- SIGTERM handler for graceful shutdown

- [ ] **Step 3: Run tests**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_acquire_naip.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add scripts/acquire_naip.py tests/test_acquire_naip.py
git commit -m "feat: add NAIP pipeline script"
```

BEFORE marking this task complete:
1. Review tests - uses real SQLite for county lookups (pitfall #1)
2. Verify security: deterministic filenames, path validation, TLS enabled
3. Verify per-county streaming: no accumulation of staging files
4. Run tests and confirm green

---

After Tasks 9-10, final review:

After every logical group of tasks:
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues. Then
update your private journal and continue onto the next tasks.

---

### Task 11: Integration Testing + Final Verification

- [ ] **Step 1: Run all unit tests**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Verify no maxzoom regression**

Run: `grep -n "maxzoom.*[0-9]" frontend/app.js | grep -iv "elevation\|terrain\|hillshade\|public"`
Expected: No matches for imagery sources

- [ ] **Step 3: Verify state file paths are distinct**

Check that _state_file_for_type returns unique paths for all 5 types (imagery, elevation, osm_poi, sentinel, naip).

- [ ] **Step 4: Verify security requirements**

Run:
```bash
# S1: No server-provided filenames
grep -rn "url.*split.*/" scripts/acquire_sentinel.py scripts/acquire_naip.py | grep -v "^#"
# S4: No ssl=False
grep -rn "ssl.*False\|verify_ssl.*False" scripts/acquire_sentinel.py scripts/acquire_naip.py
```
Expected: No matches for either

- [ ] **Step 5: Final commit**

```bash
git add -A
git status
git commit -m "feat: complete Sentinel-2 + NAIP imagery pipeline implementation"
```

---

## Execution Recommendation

**Recommended approach: Subagent-Driven Development (Option 1)**

Reasons:
- **Context consumption:** This session has consumed significant context with brainstorming, 5-round adversarial review, and CSO security review. A fresh subagent per task starts clean.
- **Self-containment:** Each task is fully self-contained with exact file paths, code, and test commands. Subagents do not need conversation history.
- **Parallelism:** Tasks 1, 2, and 3 are fully independent and can run as 3 parallel subagents. Tasks 9 and 10 can also run in parallel after Task 4 completes.
- **Risk management:** The riskiest tasks (9, 10: full pipeline scripts) benefit from focused attention rather than being buried in a long session.
- **Review checkpoints:** The plan includes 3 review checkpoints (after tasks 1-3, 4-8, and 9-10) that map naturally to subagent-driven review gates.

Task parallelism map:
- Wave 1: Tasks 1, 2, 3 (all independent)
- Wave 2: Tasks 4, 5 (sequential, depend on Task 1)
- Wave 3: Tasks 6, 7, 8 (can be parallelized, depend on earlier tasks)
- Wave 4: Tasks 9, 10 (can be parallelized, depend on Tasks 1-4)
- Wave 5: Task 11 (final verification, depends on all)
