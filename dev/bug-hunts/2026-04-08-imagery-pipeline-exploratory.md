# Bug Hunt Report: Imagery Pipeline & Container (Exploratory)

## Scope

**Depth-first exploration** of the imagery pipeline data flow: from download through MBTiles storage, TileServer serving, NGINX proxy, to MapLibre rendering. Files explored deeply:

- `scripts/acquire_imagery.py` (782 lines) -- all three download modes, MBTiles schema, progress state
- `services/search/main.py` (915 lines) -- pipeline orchestration, command building, state reconciliation
- `frontend/app.js` (lines 80-145) -- imagery/elevation source registration with hardcoded maxzoom
- `frontend/config/index.html` (287 lines) -- admin panel pipeline UI
- `scripts/download_elevation.py` (353 lines) -- sibling comparison for consistency bugs
- `tileserver/config.json` (46 lines) -- TileServer data source references
- `nginx/nginx.conf` (136 lines) -- sub_filter rewriting for TileJSON endpoints
- `docker-compose.yml` (192 lines) -- service definitions and volume mounts

**Why these were high-risk:** The pipeline orchestrator in `main.py` builds command-line arguments for two different scripts (`acquire_imagery.py` and `download_elevation.py`) with different argument schemas. The M2M download flow has complex multi-stage async polling. The frontend-to-TileServer integration involves hardcoded values that can silently diverge from the actual data.

**Cross-reference with previous hunt (2026-04-08):** Several bugs from the previous round (FD leak, state overwrite, cancel not updating state, tile estimate mismatch) have been fixed. This report focuses on new findings and re-validated existing ones.

## Bugs

### 1. Frontend hardcodes maxzoom:14 for imagery source, suppressing z15-z16 tiles
**Location:** `frontend/app.js:96`
**Severity:** critical
**Evidence:** The imagery source is registered with `maxzoom: 14`:
```js
map.addSource('imagery', {
  type: 'raster',
  tiles: ['/tiles/data/imagery/{z}/{x}/{y}.jpeg'],
  tileSize: 256,
  maxzoom: 14
});
```
The MBTiles contains 2.59M tiles including 964K at z16 and 261K at z15. TileServer GL serves these correctly (HTTP 200). The TileJSON at `/tiles/data/imagery.json` correctly reports `maxzoom: 16`. But MapLibre respects the source `maxzoom` and never requests tiles above z14. When the user zooms past z14, MapLibre upscales z14 tiles instead of fetching the higher-resolution data that exists.

**Impact:** Users see blurry upscaled imagery at z15-z16 despite having spent hours downloading ~1.2M tiles at those zoom levels (~46% of total tile count). The disk space and bandwidth for those tiles are entirely wasted. The admin panel defaults to z0-15 and offers z0-16, so most users will have higher-zoom data that is never displayed.

---

### 2. Pipeline orchestrator passes `--mode` to elevation script, which will crash
**Location:** `services/search/main.py:710-712`
**Severity:** critical
**Evidence:** The `pipeline_start` endpoint builds the command for BOTH imagery and elevation pipelines with the same template:
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
The `--mode` argument is always included regardless of `body.type`. But `download_elevation.py` has no `--mode` argument in its argument parser (lines 326-347). It only accepts `--bbox`, `--zoom`, `--output`, and `--concurrency`. When argparse encounters `--mode direct`, it will raise `error: unrecognized arguments: --mode direct` and the script will exit with code 2 immediately.

The admin panel currently hardcodes `type: 'imagery'` (config/index.html line 227), so this bug is unreachable from the browser UI. But the API endpoint accepts `type: "elevation"` and the code explicitly validates it at line 647. Any API caller requesting an elevation pipeline download will get a container that crashes immediately on startup.

**Impact:** Elevation pipeline is completely non-functional when started through the admin API. The container will exit with an error, and the state file will remain in "running" status until the next status poll reconciles it to "interrupted".

---

### 3. MBTiles metadata table has no UNIQUE constraint -- INSERT OR REPLACE appends duplicates
**Location:** `scripts/acquire_imagery.py:341-356`, `scripts/download_elevation.py:172-189`
**Severity:** significant
**Evidence:** The metadata table is created without any constraint:
```python
await db.execute(
    "CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT)"
)
```
Then metadata is written with `INSERT OR REPLACE`:
```python
await db.execute(
    "INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)",
    (k, v),
)
```
`INSERT OR REPLACE` only triggers the "replace" behavior when a UNIQUE or PRIMARY KEY constraint is violated. Without any such constraint, every `init_mbtiles()` call appends 3 new rows (imagery) or 4 new rows (elevation). After N pipeline runs (including resumes, which call `init_mbtiles` on startup), the metadata table has 3*N or 4*N rows respectively. The current imagery database has 9 duplicate rows (3 runs).

The MBTiles spec expects `name` to be unique. The table should be:
```sql
CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT)
```

**Impact:** TileServer GL reads the first match per key and works fine. But any tool inspecting metadata (QGIS, GDAL, sqlite3) sees confusing duplicates. If a future run changed a value, both old and new would coexist, making the "current" value query-order-dependent.

---

### 4. M2M download-retrieve polling accumulates duplicate URLs
**Location:** `scripts/acquire_imagery.py:644-669`
**Severity:** significant
**Evidence:** The polling loop for `download-retrieve` accumulates available URLs:
```python
urls = []
for label in labels:
    for attempt in range(M2M_POLL_MAX_ATTEMPTS):
        resp = await m2m_request(session, "download-retrieve", {
            "label": label,
        }, api_key=api_key)
        data = resp.get("data", {})
        available = data.get("available", [])
        requested = data.get("requested", [])

        for item in available:
            url = item.get("url")
            if url:
                urls.append(url)

        if not requested:
            break
```
On each poll iteration, ALL currently-available URLs are re-appended to the `urls` list. If 5 out of 10 downloads are available on poll 1, and all 10 are available on poll 2, the `urls` list will contain: 5 URLs from poll 1 + 10 URLs from poll 2 = 15 URLs, but only 10 are unique. The 5 that were available on both polls are duplicated.

The downstream `download_geotiffs()` function (line 261) creates one async task per URL: `tasks = [_get_one(session, u) for u in urls]`. Duplicate URLs produce duplicate tasks. The `_get_one` function has a checkpoint guard (`if url in done and dest.exists(): return`), but multiple concurrent tasks for the same URL race to download simultaneously because the checkpoint is only checked at the start and hasn't been written yet. This means:
1. Wasted bandwidth downloading the same file multiple times
2. Concurrent `dest.write_bytes(data)` calls to the same file (deterministic filename via SHA256) -- on Linux, one write will "win" but intermediate states could produce a corrupted file if the writes interleave

**Impact:** Wasted bandwidth and potential data corruption for M2M pipeline downloads. The severity depends on how many poll iterations occur before all downloads are ready. For large scenes that take minutes to prepare, many iterations will accumulate many duplicates.

**Fix:** Track seen URLs in a set and only append new ones:
```python
seen_urls = set()
for item in available:
    url = item.get("url")
    if url and url not in seen_urls:
        urls.append(url)
        seen_urls.add(url)
```

---

### 5. MBTiles metadata missing minzoom, maxzoom, and bounds entries
**Location:** `scripts/acquire_imagery.py:348-356`, `scripts/download_elevation.py:180-189`
**Severity:** significant
**Evidence:** The `init_mbtiles` function only writes `name`, `format`, and `type` (imagery) or those plus `description` (elevation). It omits `minzoom`, `maxzoom`, and `bounds`, despite having all three values available from the command-line arguments at the time of initialization. The zoom range is known from `args.zoom` and the bounds from `args.bbox`.

The MBTiles spec (1.3) recommends these fields. TileServer GL can discover them by scanning the tiles table, but this requires scanning up to 2.59M rows at startup. More critically, the absence of explicit metadata makes it harder to diagnose issues like Bug #1 -- there is no metadata row to compare against the frontend's hardcoded value.

**Impact:** Slower TileServer GL startup (must scan tiles table). Reduced portability to other MBTiles readers. Makes the zoom range invisible to inspection tools. During partial downloads, TileServer may report an incorrect maxzoom that doesn't match the intended final range.

---

### 6. Elevation pipeline's write_pipeline_state overwrites rather than merges, losing API metadata
**Location:** `scripts/download_elevation.py:59-70` vs `scripts/acquire_imagery.py:74-96`
**Severity:** minor
**Evidence:** The imagery pipeline's `write_pipeline_state` merges with existing state:
```python
existing = json.loads(state_path.read_text())
existing.update(state)
```
The elevation pipeline's version does a flat overwrite:
```python
tmp_path.write_text(json.dumps(state))
```
When the search service starts an elevation pipeline, it writes `type`, `mode`, `bbox`, `zoom`, `estimated_tiles` to `.elevation-state.json`. The first progress write from the elevation script overwrites all of that with just `status`, `tiles_done`, `tiles_total`, `rate_per_sec`.

**Impact:** Elevation pipeline progress display loses `estimated_tiles` from the API's pre-computed estimate. The `pipeline_status` endpoint tries to recalculate it from `bbox` and `zoom` at lines 869-875, but those fields are also gone. Progress percentage will be based only on the pipeline's `tiles_total` field.

---

### 7. Admin panel time estimate uses fixed rate regardless of concurrency setting
**Location:** `frontend/config/index.html:212`
**Severity:** minor
**Evidence:** The time estimate formula is:
```js
var hours = (count / 680 / 3600).toFixed(1);
```
The magic number 680 is a fixed tiles-per-second rate. But the admin panel has a concurrency selector (10, 20, 50, 80) that directly affects actual download speed. A user selecting "Conservative (10)" will see the same time estimate as one selecting "Maximum (80)", despite an ~8x difference in actual throughput.

**Impact:** Misleading time estimates. Users selecting lower concurrency for USGS server politeness will get a time estimate that's wildly optimistic.

## Design Concerns

### Frontend should use TileJSON instead of hardcoded tile parameters
The imagery source in `app.js` hardcodes the tile URL template, tileSize, maxzoom, and format. TileServer GL generates a TileJSON response at `/tiles/data/imagery.json` with all of these parameters auto-detected from the MBTiles data. If the frontend fetched TileJSON and used its values, Bug #1 would have been impossible. The NGINX sub_filter gap (no rewriting for `imagery.json`) would need to be fixed first, or the fetch should go to `/tiles/data/imagery.json` through the generic `/tiles/` location block which passes `Host $http_host` (meaning TileServer generates external URLs correctly).

### Pipeline command building should be type-aware
The `pipeline_start` endpoint (main.py:710-717) builds a single command template for both imagery and elevation scripts, despite the scripts having different argument schemas. The imagery script accepts `--mode` (direct/m2m/tnmaccess), while the elevation script has no mode concept -- it always downloads from AWS S3. This tight coupling between orchestrator and scripts means adding arguments to one script can break the other.

### M2M polling loop lacks idempotent URL accumulation
The download-retrieve polling pattern should use a set to track already-seen URLs. The current list-append pattern is fragile and accumulates duplicates proportional to the number of poll iterations. This is a systemic pattern risk -- any similar polling loop that accumulates items from successive responses needs deduplication.

### MBTiles schema should match the spec
Both pipelines should use `CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT)` and should write `minzoom`, `maxzoom`, and `bounds` from the known runtime parameters. This is a one-line schema change plus a few additional metadata inserts. The current approach silently diverges from the MBTiles spec and causes downstream confusion.
