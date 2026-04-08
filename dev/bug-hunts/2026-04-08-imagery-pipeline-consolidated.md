# Imagery Pipeline & Container Bug Hunt — Consolidated Findings

**Date:** 2026-04-08
**Scope:** Imagery download pipeline (acquire_imagery.py), tile serving (TileServer GL + NGINX), frontend rendering (app.js), pipeline orchestration (search/main.py), and admin panel UI (config/index.html). Also covers elevation pipeline (download_elevation.py) for cross-sibling consistency.
**Hunters:** Exploratory, Holistic, Multipass

---

## Confirmed Bugs

### B1. Frontend hardcodes `maxzoom: 14` for imagery source, suppressing z15-z16 tiles
**Consensus:** All three hunters found this (critical, unanimous)
**Location:** `frontend/app.js:96`
**Evidence:** The imagery source is defined with `maxzoom: 14`:
```js
map.addSource('imagery', {
  type: 'raster',
  tiles: ['/tiles/data/imagery/{z}/{x}/{y}.jpeg'],
  tileSize: 256,
  maxzoom: 14
});
```
The MBTiles contains 964K z16 tiles and 261K z15 tiles. TileServer serves them correctly (HTTP 200 verified). TileJSON at `/tiles/data/imagery.json` reports `maxzoom: 16`. MapLibre respects the source `maxzoom` and never requests tiles above z14, upscaling z14 tiles instead.
**Impact:** Users see blurry upscaled imagery at z15-z16 despite downloading ~1.2M tiles at those zoom levels (~46% of total tile count). The admin panel defaults to z0-15 and offers z0-16, so most users will have data they can never see.
**Blast radius:** Single-line change in `frontend/app.js:96`. No other callers.
**Fix approach:** Either change `maxzoom: 14` to `maxzoom: 18` (allowing MapLibre to request up to whatever TileServer has, and overzoom gracefully beyond), or fetch the TileJSON endpoint dynamically and use its reported `maxzoom`. The dynamic approach is better long-term but requires fixing B6 (NGINX sub_filter) first.

### B2. Pipeline orchestrator passes `--mode` to elevation script, which will crash
**Consensus:** Found by Exploratory hunter. Verified by consolidation against actual code.
**Location:** `services/search/main.py:710-712`
**Evidence:** The `pipeline_start` endpoint builds the same command template for both imagery and elevation:
```python
command = [
    "python3", script,
    "--mode", body.mode,
    f"--bbox={body.bbox}",
    f"--zoom={body.zoom}",
    "--concurrency", str(body.concurrency),
    "--output", f"/data/{mbtiles_path.name}",
]
```
`download_elevation.py` has no `--mode` argument (lines 326-347). argparse will exit with `error: unrecognized arguments: --mode direct` and the container crashes immediately.
**Impact:** Elevation pipeline is completely non-functional when started through the admin API. Currently unreachable from the admin UI (hardcodes `type: 'imagery'` at config/index.html:227), but the API endpoint accepts and validates `type: "elevation"`.
**Blast radius:** `services/search/main.py` command building section only. Fix should make command building type-aware.
**Fix approach:** Conditionally include `--mode` only for imagery pipelines: `if body.type == "imagery": command.extend(["--mode", body.mode])`.

### B3. MBTiles metadata table has no UNIQUE constraint — duplicates on every run
**Consensus:** All three hunters found this (significant, unanimous)
**Location:** `scripts/acquire_imagery.py:341`, `scripts/download_elevation.py:172`
**Evidence:** `CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT)` has no PRIMARY KEY or UNIQUE constraint. `INSERT OR REPLACE` degrades to plain `INSERT`, appending duplicates each run. Current imagery database has 9 duplicate metadata rows (3 runs × 3 keys).
**Impact:** TileServer reads first match and works fine. But MBTiles spec violation, confusing for inspection tools (QGIS, GDAL, sqlite3), and future value changes would leave both old and new values coexisting.
**Blast radius:** Both pipeline scripts. One-line schema change each, plus a one-time cleanup of existing databases.
**Fix approach:** Change to `CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT)`. For existing databases, add `DELETE FROM metadata WHERE rowid NOT IN (SELECT MIN(rowid) FROM metadata GROUP BY name)` cleanup.

### B4. M2M download-retrieve polling accumulates duplicate URLs
**Consensus:** Found by Exploratory hunter. Verified by consolidation against actual code.
**Location:** `scripts/acquire_imagery.py:644-669`
**Evidence:** Each poll iteration re-appends ALL currently-available URLs to the list. If 5/10 are available on poll 1 and 10/10 on poll 2, the list contains 15 URLs with 5 duplicates. Downstream `download_geotiffs` creates one async task per URL, and duplicates race to download the same file concurrently before the checkpoint guard fires.
**Impact:** Wasted bandwidth and potential data corruption (concurrent `write_bytes` to same file path). Severity depends on number of poll iterations for large NAIP scene downloads.
**Blast radius:** Only the M2M mode in `acquire_imagery.py`.
**Fix approach:** Track seen URLs in a set: `seen = set()` → `if url and url not in seen: urls.append(url); seen.add(url)`.

### B5. MBTiles metadata missing minzoom, maxzoom, and bounds
**Consensus:** All three hunters found this (significant, unanimous)
**Location:** `scripts/acquire_imagery.py:348-356`, `scripts/download_elevation.py:180-189`
**Evidence:** Neither script writes `minzoom`, `maxzoom`, or `bounds` to the metadata table despite having all three values available from command-line arguments. TileServer must scan the tiles table (2.59M rows) at startup to infer these.
**Impact:** Slower TileServer startup. Reduced MBTiles portability. During partial downloads, TileServer may report incorrect maxzoom. Makes diagnosing issues like B1 harder since there's no metadata to compare against.
**Blast radius:** Both pipeline scripts, a few additional `INSERT` statements each.
**Fix approach:** Add `minzoom`, `maxzoom`, `bounds` to the metadata writes in both `init_mbtiles` functions, computed from the `--zoom` and `--bbox` arguments.

### B6. No NGINX sub_filter for imagery/elevation TileJSON endpoints
**Consensus:** Holistic and Multipass hunters found this. Verified by consolidation.
**Location:** `nginx/nginx.conf:33-48`
**Evidence:** `southwest5.json` has a dedicated `location` block with `sub_filter` URL rewriting. `imagery.json` and `elevation.json` fall through to the generic `/tiles/` block which forwards `Host $http_host` (so TileServer may generate correct external URLs), but lacks `sub_filter` rules to rewrite any cross-data-source references.
**Impact:** Currently latent — the frontend hardcodes tile URLs. But blocks the correct fix for B1 (using TileJSON dynamically) and breaks any third-party client reading TileJSON.
**Blast radius:** `nginx/nginx.conf` — add two location blocks analogous to the southwest5 one.
**Fix approach:** Add `location /tiles/data/imagery.json` and `location /tiles/data/elevation.json` blocks with the same `sub_filter` rules as `southwest5.json`.

### B7. Elevation pipeline `write_pipeline_state` overwrites rather than merges
**Consensus:** All three hunters found this (minor, unanimous)
**Location:** `scripts/download_elevation.py:59-70`
**Evidence:** Imagery pipeline's version reads existing state, merges via `existing.update(state)`, preserving fields written by the search service. Elevation pipeline's version overwrites the entire file, losing `type`, `estimated_tiles`, `bbox`, `zoom` fields.
**Impact:** Admin panel progress display for elevation downloads loses the pre-computed total from the search service. Progress percentage falls back to the pipeline's own `tiles_total`.
**Blast radius:** `scripts/download_elevation.py` only — align with the merge pattern from `acquire_imagery.py`.
**Fix approach:** Copy the merge pattern from `acquire_imagery.py:74-96` into `download_elevation.py:59-70`.

---

## Design Decisions Requiring User Input

### D1. Frontend tile parameter strategy: hardcoded vs TileJSON-dynamic
**Location:** `frontend/app.js:91-97`
**The concern:** The frontend hardcodes tile URL, tileSize, maxzoom, and format for imagery. This is fragile — any change in the downloaded data requires a code change.
**Why this needs a decision:** The "correct" approach is fetching TileJSON and using its values dynamically. But this adds a network request at startup, requires fixing B6 first, and means the imagery layer isn't available until the async fetch completes.
**Options:**
1. **Quick fix:** Change `maxzoom: 14` to `maxzoom: 18` (allows MapLibre to request whatever exists, overzooms gracefully beyond). Simple, zero-risk, immediate.
2. **Dynamic TileJSON:** Fetch `/tiles/data/imagery.json` at startup and configure the source from the response. More robust long-term, but requires fixing B6 and handling the async startup.
3. **Hybrid:** Quick fix now (maxzoom: 18), TileJSON fetch as a follow-up.
**Recommendation:** Option 3. The quick fix unblocks the immediate issue. TileJSON can be a follow-up improvement.

### D2. Admin panel pipeline scope: imagery-only or imagery + elevation
**Location:** `frontend/config/index.html:227` (hardcoded `type: 'imagery'`)
**The concern:** The API supports both imagery and elevation pipelines, but the admin UI only starts imagery downloads. If elevation pipeline API support is maintained, B2 must be fixed.
**Why this needs a decision:** If elevation downloads will always be done via CLI, the API code path could be removed rather than fixed. If the admin panel should support elevation downloads too, both B2 and the UI need changes.
**Options:**
1. **Fix API, don't add UI:** Fix B2 so API callers can start elevation pipelines correctly. Leave UI for later.
2. **Full support:** Fix B2 and add elevation download controls to the admin panel.
3. **Remove elevation from API:** Delete the elevation code path from `pipeline_start` and make it CLI-only.
**Recommendation:** Option 1. The API validation already accepts elevation, so it should work correctly. UI can come later.

---

## False Positives

### FP1. Disk space estimate 1000x error
**Flagged by:** Multipass (initially, then self-corrected)
**Why invalid:** The formula `tile_count * 20 * 1024 / (1024 ** 3)` correctly computes GiB from an assumed 20 KiB per tile. The math is sound. The multipass hunter caught and struck this during analysis.

### FP2. Concurrent aiosqlite writes from asyncio.gather
**Flagged by:** Multipass (initially, then self-corrected)
**Why invalid:** `asyncio.gather` provides the synchronization barrier — `db.commit()` is only reached after all tasks in the batch complete. aiosqlite's internal thread serializes the writes.

---

## Bugs Outside Primary Scope

### O1. Disk space estimate uses 20 KB/tile for both imagery and elevation
**Location:** `services/search/main.py:665-666`
**Blast radius:** Minor — only affects the pre-flight disk check when disk is nearly full.
**Recommendation:** Document for later. On an 896 GB SSD this is unlikely to cause real problems.

### O2. Admin panel time estimate ignores concurrency setting
**Location:** `frontend/config/index.html:212`
**Blast radius:** UI-only, display issue.
**Recommendation:** Fix alongside other admin panel improvements. The formula `count / 680 / 3600` should account for the selected concurrency.

### O3. `_parse_zoom` in search service rejects single-zoom values the pipeline scripts accept
**Location:** `services/search/main.py:111-118`
**Blast radius:** Minor API inconsistency. Admin UI always sends ranges.
**Recommendation:** Document for later.

### O4. Pipeline state file race between container start and state file write
**Location:** `services/search/main.py:782-806`
**Blast radius:** Theoretical — extremely narrow race window during container startup.
**Recommendation:** Document for later. Could be fixed by writing state file before starting container.

### O5. fsync pattern opens file in read mode
**Location:** `scripts/acquire_imagery.py:91-93`, `scripts/download_elevation.py:66-67`
**Blast radius:** Negligible for a progress state file. Works on Linux.
**Recommendation:** Fix alongside B7 if touching that code.

---

## Test Gap Analysis

### B1. Frontend hardcodes maxzoom:14
**Why missed:** No frontend tests exist. The imagery layer behavior at high zoom levels would require either end-to-end browser testing or a unit test that checks the source definition parameters.
**Pitfall coverage:** No testing-pitfalls.md exists yet. One-off — noted in fix plan.
**Catch test:** An E2E test using Playwright that enables the imagery layer, zooms to z16, and verifies tile requests are made above z14 via network interception.

### B2. Pipeline orchestrator passes --mode to elevation script
**Why missed:** No integration tests for the pipeline orchestration API. The command building code path for elevation is only reachable via API, not the admin UI.
**Pitfall coverage:** One-off — the specific bug is an untested code path for a type=elevation API call.
**Catch test:** A unit test for `pipeline_start` that calls with `type="elevation"` and verifies the generated command does not contain `--mode`.

### B3. MBTiles metadata UNIQUE constraint
**Why missed:** The `init_mbtiles` function is called during pipeline runs but there are no tests for the MBTiles schema it creates.
**Pitfall coverage:** One-off.
**Catch test:** A test that calls `init_mbtiles` twice on the same database and asserts `SELECT COUNT(*) FROM metadata` equals the expected number of unique keys.

### B4. M2M polling duplicate URLs
**Why missed:** The M2M download flow has no tests. The polling loop's accumulation behavior requires mocking the download-retrieve endpoint across multiple responses.
**Pitfall coverage:** One-off.
**Catch test:** A test that mocks `download-retrieve` to return overlapping available sets across polls and asserts the final URL list has no duplicates.

### B5. Missing metadata fields
**Why missed:** No MBTiles output validation tests.
**Catch test:** After a small test download, assert metadata contains `minzoom`, `maxzoom`, and `bounds` keys.

### B6. Missing NGINX sub_filter
**Why missed:** No integration tests for NGINX proxy behavior.
**Catch test:** Request `/tiles/data/imagery.json` through the NGINX proxy and verify tile URLs don't contain `tileserver:8080`.

### B7. Elevation state overwrite vs merge
**Why missed:** No tests for pipeline state file behavior.
**Catch test:** Write initial state with `estimated_tiles`, call `write_pipeline_state` with progress data, read state file and assert `estimated_tiles` is still present.

### Testing Pitfalls Updates
- None (no `dev/testing-pitfalls.md` exists yet)

---

## Appendix: Bugs Identified But Not Fixed in This Cycle

### O1. Disk space estimate uses 20 KB/tile for both imagery and elevation
**Location:** `services/search/main.py:665-666`
**Evidence:** Fixed 20 KB/tile estimate is used for both pipeline types. Elevation tiles are typically 5-15 KB, so the estimate overpredicts by ~2x for elevation downloads.
**Why deferred:** On an 896 GB SSD this is unlikely to cause real problems. Only matters when disk is nearly full.
**Recommended fix:** Use type-aware estimate: `avg_size = 20 * 1024 if body.type == "imagery" else 10 * 1024`.

### O2. Admin panel time estimate ignores concurrency setting
**Location:** `frontend/config/index.html:212`
**Evidence:** Formula `count / 680 / 3600` uses fixed 680 tiles/sec rate regardless of selected concurrency (10-80).
**Why deferred:** UI display issue only, doesn't affect actual download behavior.
**Recommended fix:** Scale the rate by concurrency: `var rate = 680 * (concurrency / 80)`.

### O3. `_parse_zoom` in search service rejects single-zoom values
**Location:** `services/search/main.py:111-118`
**Evidence:** Requires exactly 2 parts from `split("-")`, so `"14"` fails. Pipeline scripts accept single values.
**Why deferred:** Admin UI always sends ranges. Minor API inconsistency.
**Recommended fix:** Handle single-zoom: `if len(parts) == 1: return int(parts[0]), int(parts[0])`.

### O4. Pipeline state file race between container start and state file write
**Location:** `services/search/main.py:782-806`
**Evidence:** Container starts at line 782, state file written at line 805. Extremely narrow race window.
**Why deferred:** Docker container startup + Python boot makes this practically unreachable.
**Recommended fix:** Write state file before starting container, then update with container_id after.

### O5. fsync pattern opens file in read mode
**Location:** `scripts/acquire_imagery.py:91-93`, `scripts/download_elevation.py:77-78`
**Evidence:** `open(tmp_path)` opens in read mode for fsync. Works on Linux but semantically incorrect.
**Why deferred:** Works correctly on the target platform (Linux/Pi). Progress state file, not critical data.
**Recommended fix:** Change to `open(tmp_path, 'r+b')` or remove the fsync entirely for a progress file.
