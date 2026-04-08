# Bug Hunt Report — Imagery Pipeline & Container (Multi-Pass)

## Scope
Files analyzed:
- `scripts/acquire_imagery.py` (782 lines)
- `frontend/app.js` (lines 80-500, imagery/elevation source definitions and toggle logic)
- `services/search/main.py` (915 lines)
- `tileserver/config.json` (46 lines)
- `nginx/nginx.conf` (136 lines)
- `docker-compose.yml` (192 lines)
- `frontend/config/index.html` (287 lines)
- `scripts/download_elevation.py` (353 lines, cross-sibling comparison)

All five passes performed: contract violations, cross-sibling patterns, failure modes, concurrency, error propagation.

## Bugs

### 1. Frontend hardcodes maxzoom:14, discarding z15-z16 tiles the user has already downloaded
**Location:** `frontend/app.js:96`
**Severity:** critical
**Evidence:** The imagery source is defined as:
```js
map.addSource('imagery', {
  type: 'raster',
  tiles: ['/tiles/data/imagery/{z}/{x}/{y}.jpeg'],
  tileSize: 256,
  maxzoom: 14
});
```
The MBTiles database contains 964K z16 tiles and 261K z15 tiles. TileServer serves them correctly (HTTP 200). The TileJSON at `/tiles/data/imagery.json` reports `maxzoom: 16`. But because the frontend hardcodes `maxzoom: 14`, MapLibre will never request tiles above z14 — it upscales z14 tiles instead.
**Impact:** Users who downloaded z15-z16 data (the admin panel defaults to z0-15, and z0-16 is available) see blurry upscaled imagery at high zoom instead of the crisp detail they waited hours to download. This is the primary reported bug.
**Found in:** Pass 1 — Contract Violations

### 2. MBTiles metadata table has no UNIQUE constraint, causing duplicate rows on every pipeline run
**Location:** `scripts/acquire_imagery.py:341-356`
**Severity:** significant
**Evidence:** The metadata table is created as:
```sql
CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT)
```
Then metadata rows are inserted with:
```sql
INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)
```
`INSERT OR REPLACE` requires a UNIQUE constraint or PRIMARY KEY on the conflicting columns to detect conflicts and replace. Without one, `OR REPLACE` has nothing to conflict on, so every `init_mbtiles` call appends duplicate rows. After N pipeline runs (including resumes), there will be 3*N rows instead of 3. The same bug exists in `download_elevation.py:172-189` with 4 metadata fields.
**Impact:** While TileServer GL typically reads the first matching row and works fine, the MBTiles spec expects unique `name` keys. Tools that read all metadata (GDAL, QGIS, `sqlite3` queries) will see confusing duplicates. The `_read_mbtiles_status` function in `search/main.py` doesn't read metadata so it's unaffected, but any future metadata reads could return wrong values if they don't use `LIMIT 1`.
**Found in:** Pass 1 — Contract Violations

### 3. MBTiles metadata missing minzoom, maxzoom, and bounds — TileServer must scan tiles to discover them
**Location:** `scripts/acquire_imagery.py:348-355`, `scripts/download_elevation.py:180-189`
**Severity:** significant
**Evidence:** The MBTiles spec (1.3) recommends `minzoom`, `maxzoom`, and `bounds` in the metadata table. Neither `init_mbtiles` function writes these. Both scripts know the bbox and zoom range from their arguments but don't persist them. TileServer GL must scan the tiles table or fall back to defaults to infer these values — and it does get them right (the TileJSON response shows `maxzoom: 16`), but this relies on TileServer's heuristic rather than explicit metadata. If TileServer's heuristic changes or a different renderer is used, the zoom range could be wrong.
**Impact:** This is a contributing factor to the maxzoom confusion — the frontend should ideally read the TileJSON endpoint to get the actual maxzoom from TileServer rather than hardcoding it. The missing metadata makes it harder to diagnose the bug since there's no metadata row to compare against.
**Found in:** Pass 2 — Cross-Sibling Pattern Violations

### 4. Elevation `write_pipeline_state` overwrites entire state file; imagery version merges — inconsistent, imagery can lose status
**Location:** `scripts/download_elevation.py:59-70` vs `scripts/acquire_imagery.py:74-96`
**Severity:** minor
**Evidence:** The imagery `write_pipeline_state` reads existing state, merges new fields via `existing.update(state)`, then writes back. The elevation `write_pipeline_state` just overwrites the entire file with the new state dict. This means:
- For imagery: if the search service writes `{"type": "imagery", "estimated_tiles": 5000000}` to `.pipeline-state.json` before the pipeline starts, the pipeline's progress updates will preserve that `type` and `estimated_tiles` field via merge. This is the intended behavior.
- For elevation: the search service's initial state data (type, estimated_tiles) is completely overwritten on the first progress write, losing the `type` field.
The `admin_status` endpoint at `main.py:514` checks `ps.get("type") == "imagery"` before enriching imagery status. But the elevation state file is separate (`.elevation-state.json`), so the missing `type` field doesn't cause a misread — the path already implies the type. However, the `estimated_tiles` field written by the search service IS lost, which means the admin panel's progress percentage for elevation uses only the pipeline's `tiles_total` rather than the search service's pre-computed estimate.
**Impact:** Minor inconsistency. Elevation pipeline progress display may show different total counts than what was estimated in the admin panel.
**Found in:** Pass 2 — Cross-Sibling Pattern Violations

### 5. NGINX has no sub_filter location for imagery.json or elevation.json TileJSON endpoints
**Location:** `nginx/nginx.conf:33-48`
**Severity:** minor (currently not triggered because frontend doesn't fetch these endpoints)
**Evidence:** There is a specific `location /tiles/data/southwest5.json` block with `sub_filter` rules to rewrite internal `tileserver:8080` URLs to external paths. But there are no equivalent blocks for `/tiles/data/imagery.json` or `/tiles/data/elevation.json`. These TileJSON endpoints fall through to the generic `/tiles/` location block (line 44-48), which forwards `Host $http_host` — this means TileServer generates URLs with the external host, so they work. However, the generic block does NOT have `proxy_set_header Accept-Encoding ""` or `sub_filter`, so if TileServer ever generates internal URLs (e.g., if the Host header isn't forwarded correctly, or if TileJSON references cross-data sources), those URLs won't be rewritten.
**Impact:** Currently a latent issue since the frontend hardcodes tile URLs and doesn't fetch TileJSON. If someone fixes bug #1 by using the TileJSON endpoint to dynamically get maxzoom and tile URLs, those URLs could contain unrewritten internal hostnames in edge cases.
**Found in:** Pass 3 — Failure Mode Reasoning

### 6. Disk space estimation is wrong by 1000x — `20 * 1024` is 20 KiB not 20 KB, and the formula is correct but the comment is misleading
**Location:** `services/search/main.py:666`
**Severity:** minor (the math is actually correct despite the misleading comment)
**Evidence:** The formula is `tile_count * 20 * 1024 / (1024 ** 3)`. Breaking this down: `20 * 1024 = 20,480 bytes per tile = 20 KiB`. Then dividing by `1024^3` converts bytes to GiB. The comment says "~20 KB per tile average" which is approximately right (20 KiB ≈ 20.48 KB). The admin panel JS uses the same formula: `count * 20 * 1024 / (1024*1024*1024)`. Both are consistent and the estimate is reasonable. After closer analysis, this is NOT a bug — the formula is correct. Removing from findings.

*(Struck — not a bug upon closer analysis.)*

### 6. (Actual) Pipeline container race: state file written after container starts, but container may write state before search service does
**Location:** `services/search/main.py:794-805`
**Severity:** minor
**Evidence:** In `pipeline_start`, the container is started at line 782 (`client.containers.run(..., detach=True)`), and the state file is written at line 805 (`state_file.write_text(...)`). The pipeline container begins executing immediately on `detach=True`. The imagery pipeline's `write_pipeline_state` merges with existing state via `existing.update(state)`. But if the container's first progress write happens before line 805 executes, the state file won't exist yet and the pipeline creates it with just progress data (no `type`, `estimated_tiles`, etc.). Then line 805 writes the full state, overwriting the pipeline's progress. This is a narrow race window (the pipeline takes seconds to build its tile list before the first write), and in practice Docker container startup + Python boot time makes this extremely unlikely.
**Impact:** Theoretical — extremely narrow race window. If it hit, the first few seconds of progress would be lost, and the `estimated_tiles` field would be briefly missing.
**Found in:** Pass 4 — Concurrency Reasoning

### 7. Concurrent aiosqlite writes from asyncio.gather with no batching lock
**Location:** `scripts/acquire_imagery.py:438-455`
**Severity:** minor
**Evidence:** In `run_direct`, a batch of 2000 tiles is dispatched via `asyncio.gather(*tasks)`. Each `_fetch_tile` coroutine independently calls `await db.execute(INSERT OR REPLACE ...)` twice (once for tiles, once for checkpoint). With 2000 concurrent coroutines all writing to the same `aiosqlite.Connection`, the SQLite writes are serialized by aiosqlite's internal thread, but interleaving can mean the `db.commit()` at line 455 commits a partially-completed batch if some tasks haven't finished their second `db.execute` yet. However, since `asyncio.gather` waits for ALL tasks before returning, the commit at line 455 is only reached after all tasks complete. The same pattern exists in `download_elevation.py:283-300`. This is safe because `asyncio.gather` provides the synchronization barrier.

*(Struck — not a bug upon closer analysis. asyncio.gather provides the barrier.)*

### 7. (Actual) `_parse_zoom` in search/main.py rejects single-zoom values that the pipeline script accepts
**Location:** `services/search/main.py:111-118` vs `scripts/acquire_imagery.py:128-133`
**Severity:** minor
**Evidence:** The pipeline script's `parse_zoom` accepts both `"14"` (single zoom) and `"0-14"` (range). The search service's `_parse_zoom` requires exactly 2 parts from `split("-")`, so `"14"` produces `["14"]` which has length 1, raising ValueError. While the admin panel UI only offers range values like `"0-14"`, a direct API caller could pass a single zoom value that works with the pipeline script but fails at the search service's validation.
**Impact:** Minor API inconsistency. The admin UI always sends ranges, so this doesn't affect normal users.
**Found in:** Pass 5 — Error Propagation

### 8. `write_pipeline_state` in acquire_imagery.py opens tmp file in text mode for fsync, doesn't fsync directory
**Location:** `scripts/acquire_imagery.py:91-93`
**Severity:** minor
**Evidence:** After writing `tmp_path.write_text(json.dumps(existing))`, the code opens the tmp file again for fsync:
```python
with open(tmp_path) as f:
    os.fsync(f.fileno())
```
This opens in text/read mode (`'r'`), which works for fsync on Linux but is semantically odd. More importantly, `os.replace` is atomic on the same filesystem but the directory entry update isn't fsynced. The same pattern exists in `download_elevation.py:66-67`. In practice this doesn't matter — the data is state for a progress monitor, not a financial transaction — but it means a power failure during `os.replace` could lose the state file entirely.
**Impact:** Negligible in practice for a progress-monitoring state file. Power loss would require the pipeline to be restarted anyway, and the checkpoint table in SQLite handles resume.
**Found in:** Pass 5 — Error Propagation

## Design Concerns

### Hardcoded tile URLs bypass TileJSON contract
The frontend hardcodes tile URL templates (`/tiles/data/imagery/{z}/{x}/{y}.jpeg`) and zoom limits instead of fetching the TileJSON endpoint (`/tiles/data/imagery.json`) which TileServer dynamically generates from the actual MBTiles content. This means every time the data changes (new zoom levels, different format, different bounds), the frontend code must be manually updated to match. The TileJSON protocol exists precisely to solve this problem.

### No metadata integrity enforcement in MBTiles
Both pipeline scripts create the `metadata` table without a UNIQUE constraint on `name`, and neither writes the zoom range or bounds even though both are known at runtime. This violates the MBTiles spec and makes the files less portable. A `CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT)` would fix both the duplicate issue and the INSERT OR REPLACE semantics in one change.

### Pipeline state management split across two systems
Pipeline progress state is split between a JSON file on disk (written by the pipeline container) and the Docker container status (queried by the search service). The search service reconciles these in `pipeline_status`, but the reconciliation logic has edge cases — if the container crashes between writing "running" and the search service polling, the state stays "running" until the next poll. The SIGTERM handler sets `_cancel_requested` but the state file update happens at the next batch boundary, not immediately.
