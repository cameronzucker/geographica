# Bug Hunt Report

## Scope
Imagery catalog endpoint and inventory tab frontend. Deep analysis of:
- `services/search/main.py` lines 720-823 (catalog endpoint, TMS bounds, delete)
- `frontend/config/index.html` lines 1900-2170 (inventory map, sidebar, selection)
- `docker-compose.yml` search service configuration
- `tests/test_imagery_catalog.py` (to verify test gaps)
- `scripts/tileserver_config.py` (delete flow)

High-risk areas explored first: field name contract between API and frontend, TMS coordinate math, environment variable wiring.

## Bugs

### 1. Frontend uses `src.source_id` but API returns `src.id` — inventory shows empty
**Location:** `frontend/config/index.html:2008,2009,2029,2060,2066,2070,2118,2121,2124,2136,2160`
**Severity:** critical
**Evidence:** The backend `_build_imagery_catalog()` (main.py:772) returns objects with field `"id"`. The inventory tab frontend accesses `src.source_id` throughout — `invSourceColor(src.source_id)`, `'inv-' + src.source_id`, `invHumanName(src.source_id)`, `div.dataset.sourceId = src.source_id`, etc. Since `src.source_id` is `undefined`, every source renders with no name, no color lookup, the map source ID is `'inv-undefined'`, and the delete button sends `DELETE /admin/imagery/undefined`.

Notably, the card-based rendering in the same file (lines 854+) correctly uses `src.id`. The inventory tab code was written separately and used the wrong field name.

**Impact:** The inventory tab appears to work (sources render) but every source shows the wrong name, wrong color, and map layers collide on the same `inv-undefined` key. Delete sends the wrong source_id. Selection/zoom never works because the find loop at line 2160 matches on `source_id` which is always `undefined`.

### 2. Frontend uses `src.file_size_bytes` but API returns `src.size_bytes`
**Location:** `frontend/config/index.html:2085,2122`
**Severity:** significant
**Evidence:** Backend returns `"size_bytes"` (main.py:775). Frontend reads `src.file_size_bytes` for display and delete confirmation. `invFormatSize(undefined)` returns `'--'`, so all sources show `-- · N tiles` instead of actual file size.
**Impact:** File sizes display as `--` for every source. Delete confirmation shows wrong size.

### 3. TMS bounds math produces wrong-hemisphere latitudes
**Location:** `services/search/main.py:725-726`
**Severity:** significant
**Evidence:** `_tile_bounds_tms()` applies the slippy-map Y-to-latitude formula directly to TMS `tile_row` values. TMS uses Y=0 at the bottom (South Pole); slippy maps use Y=0 at the top (North Pole). The conversion requires `slippy_y = (2^z - 1) - tms_y`. Without this flip, a tile at TMS row 157094 at z18 (Maricopa County, AZ, ~+33.6°N) computes as -33.6°S.

Verified:
```
TMS Y=157094 at z18 → code produces lat=-33.62° (wrong)
After flip: slippy Y=105049 → lat=+33.62° (correct)
```

The fix: replace `min_y` and `max_y` with `(n - 1 - max_y)` and `(n - 1 - min_y)` respectively before computing latitude.

**Impact:** Inventory map shows source bounding boxes in the wrong hemisphere. `fitBounds` zooms to the southern ocean instead of the actual coverage area. The test at `test_imagery_catalog.py:49-57` passes because it only checks `-85 <= lat <= 85`, not that the sign is correct.

### 4. `TILESERVER_CONFIG` env var never set — `registered` always False
**Location:** `docker-compose.yml:121-126`, `services/search/main.py:790-795`
**Severity:** minor
**Evidence:** The catalog endpoint reads `TILESERVER_CONFIG` from the environment to determine if a source is registered in TileServer. This variable is never set in docker-compose.yml for the search service, so `ts_config` is always `None` and `registered` is always `False`.
**Impact:** Every source shows "Not registered" in the inventory sidebar, even when it is registered. Cosmetic only — doesn't affect actual tile serving.

## Design Concerns

1. **API field name contract has no shared schema.** The card rendering code and inventory code in the same HTML file use different field names (`id` vs `source_id`, `size_bytes` vs `file_size_bytes`) for the same API response. There is no TypeScript, no shared constants, no JSDoc — the contract is implicit and fragile.

2. **TMS vs slippy Y convention is a known footgun.** The MBTiles spec uses TMS (Y=0 at bottom), while most web mapping libraries use slippy (Y=0 at top). The test for bounds validity checks range but not sign, so hemisphere errors pass silently.

3. **Test for bounds only checks range, not correctness.** `test_catalog_bounds_are_valid_lonlat` verifies `-85 <= lat <= 85` but doesn't verify the coordinates are in the expected hemisphere or even the expected quadrant. A test using known tile coordinates with expected lat/lon output would catch this.
