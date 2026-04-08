# Bug Hunt Report: Imagery Pipeline & Container

## Scope

Files analyzed (all read in full):
- `scripts/acquire_imagery.py` (782 lines) -- USGS imagery download pipeline
- `scripts/download_elevation.py` (353 lines) -- elevation tile pipeline (sibling for comparison)
- `frontend/app.js` (lines 80-145, 385-500 plus targeted grep) -- imagery/elevation source registration
- `frontend/config/index.html` (287 lines) -- admin config panel with pipeline UI
- `services/search/main.py` (915 lines) -- pipeline orchestration, status monitoring
- `tileserver/config.json` (46 lines) -- TileServer GL data sources
- `nginx/nginx.conf` (136 lines) -- reverse proxy with sub_filter rewriting
- `docker-compose.yml` (192 lines) -- all service definitions

Approach: read everything, map the full data flow from pipeline download through MBTiles storage, TileServer serving, NGINX proxy, to MapLibre rendering, then looked for contradictions between adjacent layers.

## Bugs

### 1. Frontend hardcodes maxzoom:14 for imagery source, suppressing z15-z16 tiles
**Location:** `frontend/app.js:96`
**Severity:** significant
**Evidence:** The imagery source is registered with `maxzoom: 14`:
```js
map.addSource('imagery', {
  type: 'raster',
  tiles: ['/tiles/data/imagery/{z}/{x}/{y}.jpeg'],
  tileSize: 256,
  maxzoom: 14
});
```
The MBTiles database contains 964K z16 tiles and 261K z15 tiles. TileServer GL serves them correctly (HTTP 200). The TileJSON at `/tiles/data/imagery.json` correctly reports `maxzoom: 16`. But MapLibre respects the source's `maxzoom` property and will never request tiles above z14. When the user zooms past z14, MapLibre upscales z14 tiles instead of fetching the higher-resolution data that exists.

**Impact:** Users see blurry upscaled imagery at z15-z16 despite having downloaded ~1.2M tiles at those zoom levels (roughly 46% of the total tile count). The disk space and download time for those tiles is entirely wasted.

### 2. MBTiles metadata table has no UNIQUE constraint, causing duplicate rows on re-runs
**Location:** `scripts/acquire_imagery.py:341-356`
**Severity:** minor
**Evidence:** The `init_mbtiles` function creates the metadata table without a unique constraint:
```python
await db.execute(
    "CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT)"
)
```
Then writes metadata with `INSERT OR REPLACE`:
```python
await db.execute(
    "INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)",
    (k, v),
)
```
`INSERT OR REPLACE` only replaces when a UNIQUE or PRIMARY KEY constraint is violated. Without any such constraint, every call appends new rows. After N pipeline runs, the metadata table contains N copies of each key-value pair. Per the issue description, the current database has 9 duplicate rows.

The same pattern exists in `download_elevation.py:172-189` with the identical bug.

**Impact:** TileServer GL and other MBTiles readers typically do `SELECT value FROM metadata WHERE name = ?`, which may return the first match and ignore duplicates, so the serving behavior is unaffected. But the metadata table grows unboundedly, and any tool that reads all metadata rows (e.g., `sqlite3` CLI inspection, QGIS) will show confusing duplicates. If a future pipeline run changed a metadata value (e.g., format from `jpeg` to `png`), both old and new values would coexist, making the "current" value ambiguous depending on query order.

### 3. MBTiles metadata missing minzoom, maxzoom, and bounds entries
**Location:** `scripts/acquire_imagery.py:348-356`
**Severity:** significant
**Evidence:** The MBTiles spec (and TileServer GL's expectations) define several standard metadata keys. The `init_mbtiles` function only writes `name`, `format`, and `type`:
```python
for k, v in [
    ("name", name),
    ("format", "jpeg"),
    ("type", "baselayer"),
]:
```
It omits `minzoom`, `maxzoom`, `bounds`, and `description`. TileServer GL can still discover the actual zoom range by scanning the tiles table, but this requires a table scan. More critically, when these metadata fields are absent, TileServer GL must infer them, and the inferred values may not match what the pipeline actually downloaded.

The elevation pipeline (`download_elevation.py:180-188`) also omits `minzoom`, `maxzoom`, and `bounds`, but at least includes `description`.

**Impact:** Without explicit `maxzoom` in MBTiles metadata, TileServer GL's TileJSON auto-detection works (it reports maxzoom:16 correctly based on tile data), so this is not the root cause of the z16 rendering issue. But it means TileServer must do expensive introspection at startup on a 2.59M-row table, and any partial download (e.g., cancelled at z14 with z15-16 pending) would report an incorrect maxzoom until those tiles arrive.

### 4. Disk space estimate assumes all tiles are imagery-sized (20 KB) even for elevation pipelines
**Location:** `services/search/main.py:665-666`
**Severity:** minor
**Evidence:** The `pipeline_start` endpoint estimates disk usage with a fixed 20 KB per tile:
```python
# Rough estimate: ~20 KB per tile average (measured from USGS imagery)
estimated_size_gb = tile_count * 20 * 1024 / (1024 ** 3)
```
This same calculation runs for both `body.type == "imagery"` and `body.type == "elevation"`. Elevation PNG tiles are typically 5-15 KB, not 20 KB. The estimate overpredicts disk usage for elevation downloads by ~2x.

**Impact:** The disk space check at line 668 (`if disk_free_gb - estimated_size_gb < 10.0`) will reject elevation downloads prematurely when disk is between ~10-20 GB free, even though the actual data would fit. On an 896 GB SSD this is unlikely to matter in practice, but the guard exists precisely for when disk is low.

### 5. Elevation pipeline's write_pipeline_state overwrites state; imagery's merges -- but neither protects against concurrent writes
**Location:** `scripts/download_elevation.py:59-70` vs `scripts/acquire_imagery.py:74-95`
**Severity:** minor
**Evidence:** The elevation pipeline's `write_pipeline_state` does a straight overwrite:
```python
tmp_path.write_text(json.dumps(state))
```
The imagery pipeline's version merges with existing state:
```python
existing = {}
if state_path.exists():
    existing = json.loads(state_path.read_text())
existing.update(state)
tmp_path.write_text(json.dumps(existing))
```
The merge behavior in the imagery version is intentional -- it preserves fields like `estimated_tiles`, `bbox`, `zoom` that were written by the search service when it launched the container. The elevation version discards all of those fields on the first progress write.

**Impact:** For elevation pipelines launched from the admin panel, the state file will lose the `type`, `mode`, `bbox`, `zoom`, `estimated_tiles` fields as soon as the pipeline writes its first progress update. The `pipeline_status` endpoint at `main.py:869-875` tries to recalculate `estimated_tiles` from `bbox` and `zoom`, but those fields are gone. The status page will show tile counts without a meaningful total, making progress tracking impossible for elevation downloads started through the admin UI.

### 6. NGINX has no sub_filter location for imagery.json or elevation.json TileJSON endpoints
**Location:** `nginx/nginx.conf:33-48`
**Severity:** minor (currently no impact, but a latent issue)
**Evidence:** There is a specific `sub_filter` location for `southwest5.json`:
```
location /tiles/data/southwest5.json {
    proxy_pass http://tileserver:8080/data/southwest5.json;
    sub_filter 'http://tileserver:8080/data/' '$scheme://$http_host/tiles/data/';
}
```
But no equivalent for `imagery.json` or `elevation.json`. These TileJSON endpoints would be served through the catch-all `/tiles/` block (line 44-48) which does NOT have `sub_filter`. This means if a client requests `/tiles/data/imagery.json`, the tile URLs in the response will still reference `http://tileserver:8080/data/...` (TileServer's internal hostname) rather than the external proxy URL.

**Impact:** Currently no impact because the frontend hardcodes the tile URL template directly in `app.js` rather than fetching it from TileJSON. But any future change to use TileJSON (which is the correct approach and would solve Bug #1 by inheriting the actual maxzoom from the data) would break because the tile URLs in the TileJSON response would be unreachable from the browser. This is also a trap for third-party clients (e.g., QGIS, ATAK) that might try to discover tile endpoints through TileJSON.

## Design Concerns

### Metadata table schema is non-standard across both pipelines
The MBTiles specification recommends (and most tools expect) `CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT)` or at minimum a UNIQUE constraint on `name`. Both pipelines create the table without any constraint, then use `INSERT OR REPLACE` which semantically becomes a plain `INSERT`. This is a class of bug that silently accumulates corruption over repeated runs. Since both pipelines share this pattern, fixing one without the other will leave the inconsistency.

### Frontend hardcodes tile parameters that should come from TileJSON
The imagery source in `app.js` hardcodes the tile URL template, tileSize, maxzoom, and format. TileServer GL generates a TileJSON response (`/tiles/data/imagery.json`) with all of these parameters auto-detected from the MBTiles data. The frontend should fetch and use TileJSON instead of hardcoding -- this would have prevented Bug #1 entirely, and would automatically adapt to any future changes in the data (different zoom range, different format, different bounds). The NGINX sub_filter gap (Bug #6) would need to be fixed first.

### Pipeline state file race between writer (pipeline container) and reader/writer (search service)
The search service's `pipeline_status` endpoint reads the state file and may rewrite it (e.g., to mark status as "interrupted" at line 848). The pipeline container concurrently writes the state file for progress updates. Both use atomic `os.replace` for the write itself, but the read-modify-write cycle in the imagery pipeline's `write_pipeline_state` is not atomic: between reading the existing state and writing the merged version, the search service could overwrite the file. In practice the search service only writes when it believes the container is dead, so this window is narrow, but it exists.

### Admin panel time estimate divisor is opaque
The admin config panel estimates download time as `count / 680 / 3600` hours (line 212 of config/index.html). The magic number 680 appears to be an empirical tiles-per-second rate, but it is not documented and does not correspond to the configured concurrency. A user selecting "Conservative (10)" concurrency will see the same time estimate as one selecting "Maximum (80)" -- the estimate will be wildly inaccurate at low concurrency settings.
