# Imagery Sources: Sentinel-2 + USDA NAIP Pipeline Design

**Date:** 2026-04-09
**Status:** Approved
**Scope:** Two new imagery acquisition pipelines, generalized progress model, frontend layer toggles

## Problem

The existing imagery pipeline depends entirely on USGS infrastructure through three modes:
- **direct** — tile scraping from USGS cached tile service
- **tnmaccess** — TNMAccess API for NAIP GeoTIFFs
- **m2m** — USGS M2M API for NAIP scenes (requires credentials, complex multi-phase API dance)

The NAIP imagery is also available on AWS S3 (`naip-visualization` bucket), but that bucket is **requester-pays** — meaning AWS credentials and per-GB egress charges are required. This makes it unsuitable for a free, offline-first platform.

We need free, credential-minimal imagery sources that bypass USGS entirely.

## Solution

Two new pipeline sources, both completely free:

1. **Sentinel-2** (European Space Agency / Copernicus) — 10m resolution, global coverage, updated every 5 days. Lower resolution than NAIP but frequently refreshed and useful for regional context, vegetation monitoring, and areas outside US NAIP coverage.

2. **USDA NAIP county mosaics** (USDA Geospatial Data Gateway) — 0.6-1m resolution, same high-quality NAIP data as M2M but delivered as pre-mosaicked county files via direct HTTP download. No USGS middleman, no API dance, no credentials.

Both feed into the existing GDAL → MBTiles conversion path. Each produces a separate MBTiles file. The frontend gets independent layer toggles for each.

## Architecture

### Data flow

```
Admin Console                    Backend (search service)              Pipeline Container
─────────────                    ───────────────────────              ──────────────────
[Start Sentinel-2] ──POST──→    pipeline_start(type="sentinel") ──→  acquire_sentinel.py
                                  • validate bbox, date range              • STAC query
                                  • check Copernicus credentials           • download COGs
                                  • write initial state file               • composite
                                  • launch container                       • → imagery_sentinel.mbtiles

[Start NAIP]       ──POST──→    pipeline_start(type="naip")     ──→  acquire_naip.py
                                  • validate bbox                          • county lookup
                                  • county intersection query              • download mosaics
                                  • show confirmation to admin             • format convert
                                  • launch container                       • → imagery_naip.mbtiles
```

### Key decisions

- **Separate MBTiles files** — `imagery_sentinel.mbtiles` and `imagery_naip.mbtiles`, not merged. TileServer serves them as separate raster sources.
- **Independent frontend layer toggles** — "NAIP Aerial" and "Sentinel-2" as separate checkboxes in the layer switcher. Both only visible when their respective MBTiles file exists.
- **Existing modes preserved** — `direct` and `m2m` remain as "USGS Legacy" in the admin console. Not removed.
- **No hardcoded maxzoom in the frontend** — each layer reads `maxzoom` from TileServer's TileJSON response dynamically. This prevents a repeat of bug B1 where hardcoded `maxzoom: 14` blocked display of higher-resolution tiles that had been downloaded. The MBTiles metadata is the single source of truth for zoom limits. **Implementation requirement:** All new raster sources MUST use MapLibre's TileJSON URL form: `map.addSource('imagery-naip', { type: 'raster', url: '/tiles/data/imagery_naip.json' })`. Do NOT manually specify `tiles`, `maxzoom`, `bounds`, or `tileSize` — let MapLibre parse them from TileJSON. An acceptance test must verify that no imagery source in `app.js` contains a numeric `maxzoom` literal. The existing legacy `imagery` source should also be migrated to this pattern as part of this work.
- **Generalized progress model** — all pipeline scripts use a shared progress module with generic `items_done/items_total/item_unit` fields instead of source-specific fields. **Status values must match existing convention:** use `"completed"` (not `"complete"`), `"running"`, `"error"`, `"cancelled"` to avoid breaking existing frontend/backend consumers.
- **Single pipeline execution slot** — all pipeline types (sentinel, naip, imagery, elevation, osm_poi) share a single execution mutex. Only one pipeline can run at a time. The admin UI greys out all other Start buttons when any pipeline is active, with a tooltip explaining why.

## Sentinel-2 Pipeline

### Script: `scripts/acquire_sentinel.py`

**Dependencies:** `aiohttp`, `aiosqlite`, `tqdm` (already in project) + GDAL CLI tools (already in pipeline container).

### Copernicus STAC API

- **Endpoint:** `https://catalogue.dataspace.copernicus.eu/stac/search`
- **Auth:** OAuth2 token from `https://identity.dataspace.copernicus.eu` (free account registration required)
- **Search:** By bbox, date range, cloud cover percentage
- **Download:** Direct HTTP URLs for Cloud-Optimized GeoTIFF (COG) files

### Phases

| Phase | `item_unit` | Description |
|-------|-------------|-------------|
| `authenticating` | — | Get OAuth2 token from Copernicus identity service |
| `searching` | `scenes` | STAC query with pagination, filter by bbox + date range + cloud cover |
| `downloading` | `scenes` | Download qualifying COG files to staging directory |
| `compositing` | — | GDAL composite: `gdalbuildvrt` with `-srcnodata` for cloud masking, then `gdal_translate` with `-co QUALITY=85`. For multi-scene composite, the VRT stacks scenes chronologically and GDAL's default "last valid pixel wins" behavior fills cloud gaps from earlier scenes. |
| `converting` | — | `gdal_translate -of MBTiles` + `gdaladdo` for overview pyramids |
| `complete` | — | Write final state, cleanup staging directory |

### Admin UI parameters

- **Bbox** — shared minimap with draw-to-select (same UX as existing pipelines)
- **Date range** — start/end date pickers. Default: last 6 months.
- **Max cloud cover** — slider, 0-100%. Default: 20%.
- **Mode** — toggle: "Composite (best quality, slower)" vs "Single best scene (faster)". Default: Composite.

### Credentials

Stored in the existing `/data/credentials.json` alongside M2M credentials:

```json
{
  "m2m_username": "...",
  "m2m_token": "...",
  "copernicus_username": "...",
  "copernicus_password": "..."
}
```

The admin console Settings tab gets a new "Copernicus" credentials section.

### Output

`imagery_sentinel.mbtiles` in `/srv/geographica/data/`.

MBTiles metadata includes `maxzoom` as determined by GDAL from the source resolution (expected: 14 for 10m data). The frontend reads this from TileJSON — never hardcoded.

### OAuth2 token refresh

Copernicus OAuth2 tokens expire after 10 minutes. The script must implement token refresh:
- Store the refresh token from initial authentication
- Before each download batch, check token expiry (with 60s buffer)
- If expired or near-expiry, refresh using the refresh token
- If refresh fails, re-authenticate from scratch

### Search checkpoint

After the STAC query completes, write `searched_scenes.json` to the staging directory with the full list of scene URLs and metadata. On resume (after interruption), load this file and skip the search phase. If the file exists but is older than 24 hours, re-search to pick up any newly available scenes.

### Zoom behavior

10m resolution naturally supports z0-z14. Beyond z14 the pixels are visible. MapLibre upscales z14 tiles at higher zooms (blurry but present). If future Sentinel products provide higher resolution, the only change needed is in the MBTiles metadata — the frontend adapts automatically via TileJSON.

## USDA NAIP Pipeline

### Script: `scripts/acquire_naip.py`

### USDA Gateway endpoint

`https://datagateway.nrcs.usda.gov/GDGHome_DirectDownLoad.aspx`

- No authentication, no API key
- County mosaics organized by state FIPS + county FIPS + year
- Files are compressed (MrSID `.sid` or JPEG2000 `.jp2`)
- Direct HTTP download, resumable

**URL discovery (not construction):** The USDA Gateway endpoint is an ASPX web page, not a documented machine API. Do NOT construct download URLs from inferred path templates. Instead, the `discovering` phase must:
1. Query the USDA Gateway page for each county/state/year combination
2. Parse the response to extract actual download links
3. Validate each link with a HEAD request (check `Content-Type`, `Content-Length`, byte-range support)
4. Prefer JP2 links; skip MrSID-only counties with a warning
5. Cache discovered URLs in a `discovered_urls.json` checkpoint for resume

### Bbox → county resolution

When the user draws a bbox, the backend queries a bundled SQLite database to find all intersecting counties. This provides:

1. A list of counties to download (with names, states, FIPS codes)
2. An estimated download size (based on county area heuristic)
3. A pre-download confirmation step in the admin UI

### Phases

| Phase | `item_unit` | Description |
|-------|-------------|-------------|
| `resolving` | `counties` | Bbox → county intersection lookup (instant, local SQLite) |
| `discovering` | `counties` | Query USDA Gateway for available files per county, resolve download URLs |
| `downloading` | `counties` | Download county mosaics to staging directory, checkpoint per file |
| `converting` | `counties` | GDAL: MrSID/JP2 → GeoTIFF (per county, parallelizable) |
| `merging` | — | `gdalbuildvrt` + `gdal_translate -of MBTiles` + `gdaladdo` |
| `complete` | — | Write final state, cleanup staging directory |

### Pre-download confirmation

Unlike other pipelines that start immediately, the NAIP pipeline shows a confirmation step:

```
Bbox intersects 347 counties across 11 states:
  AZ: 15 counties (Maricopa, Pima, Pinal, ...)
  CA: 58 counties (Los Angeles, San Diego, ...)
  ...
Estimated download: ~142 GB
[Start Download]  [Cancel]
```

This is implemented as a two-step API flow with inline UI (not a modal):
1. `GET /admin/pipeline/naip/counties?bbox=...` — returns matched counties + estimate
2. The pipeline card expands to show the county list and estimated size inline, with "Start Download" and "Cancel" buttons
3. `POST /admin/pipeline/start` with `type="naip"` — starts the actual download (after user clicks "Start Download")

### Format handling

USDA Gateway provides county mosaics in MrSID (`.sid`) or JPEG2000 (`.jp2`) format.

- **JPEG2000** — GDAL handles natively via OpenJPEG. This is the ONLY supported format.
- **MrSID** — requires proprietary Extensis SDK which has NO ARM64 Linux build. MrSID is **not supported** on Pi 5. Counties that only offer MrSID are **skipped with a clear warning** logged and shown in the progress detail: "Skipped: {county_name} (MrSID only, unsupported on ARM64)". Skipped counties are tracked in the state file as `skipped_counties: [{fips, name, reason}]`.

The pipeline container's GDAL installation must include OpenJPEG support (`--with-openjpeg` or equivalent). A startup self-check validates `JP2OpenJPEG` is in `gdalinfo --formats` output and refuses NAIP jobs if missing.

### Processing strategy (memory + disk safety)

**CRITICAL CONSTRAINT:** The pipeline container has a 2 GB memory limit. The Pi 5 has 657 GB free disk but staging files can easily exceed this if held simultaneously. The processing strategy MUST prevent both OOM and disk fill.

**NAIP: per-county streaming conversion**

Do NOT download all counties, then convert all, then merge. Instead, process one county at a time:

1. Download county mosaic (JP2) to staging
2. Convert JP2 → GeoTIFF via `gdal_translate`
3. Convert GeoTIFF → append tiles to MBTiles via `gdal_translate -of MBTiles` (or merge into running VRT)
4. **Delete the JP2 and intermediate GeoTIFF immediately**
5. Move to next county

Peak disk usage = one county's raw + converted size (~5-15 GB) + growing MBTiles output. This keeps disk usage bounded.

For the final MBTiles with overview pyramids: run `gdaladdo` on the already-populated MBTiles after all counties are appended. Use `GDAL_CACHEMAX=256` (not 1024) to stay within the 2 GB container.

**Sentinel-2: spatial chunking**

For large bboxes, do NOT composite all scenes at once. Break into spatial chunks (e.g., 2x2 degree tiles):

1. For each chunk: download overlapping scenes, composite with `gdalbuildvrt` + `gdal_translate`
2. Merge chunk MBTiles into final output
3. Delete chunk staging after merge

Use `GDAL_CACHEMAX=256` and `GDAL_NUM_THREADS=2` to limit resource usage.

**Memory budget for pipeline container:**
- `GDAL_CACHEMAX=256` (256 MB, not 1024)
- `GDAL_NUM_THREADS=2` (leave 2 cores for other services)
- No parallel county conversion (sequential only)
- Process priority: `nice -n 19` and `ionice -c2 -n7` on the pipeline process

**Disk space checks:**
- Pre-flight: reject if `available_space < estimated_total * 0.3` (staging headroom)
- Per-county: check free space before each download; pause with error if < 10 GB free

### Checkpoint/resume

Same pattern as existing pipelines — a JSON checkpoint file tracking which counties have been downloaded and converted. Resume skips completed counties.

### Output

`imagery_naip.mbtiles` in `/srv/geographica/data/`.

MBTiles metadata includes `maxzoom` as determined by GDAL from NAIP source resolution (expected: 17-19 for 0.6-1m data). Frontend reads from TileJSON.

## County Lookup Database

### Build script: `scripts/build_county_index.py`

### Data source

US Census Bureau TIGER/Line county boundary shapefiles:
`https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip`

Free, public domain, ~15MB download. Contains all ~3,200 US counties with polygons, FIPS codes, names, state codes.

### Output: `data/counties.sqlite` (~5MB)

**Committed to the repo** — county boundaries change once per decade (Census redistricting). 5MB is negligible. Guarantees offline-first operation with no build step required.

### Schema

```sql
CREATE TABLE counties (
    fips TEXT PRIMARY KEY,       -- 5-digit FIPS (e.g., "04013" for Maricopa)
    name TEXT NOT NULL,          -- County name
    state_fips TEXT NOT NULL,    -- 2-digit state FIPS
    state_abbr TEXT NOT NULL,    -- "AZ", "CA", etc.
    area_sq_km REAL,            -- For download size estimation
    min_lon REAL, min_lat REAL,  -- Bounding box of county
    max_lon REAL, max_lat REAL
);

CREATE VIRTUAL TABLE counties_rtree USING rtree(
    id,
    min_lon, max_lon,
    min_lat, max_lat
);
```

### Why rtree, not SpatiaLite

SpatiaLite adds a heavy C extension dependency. SQLite's built-in `rtree` module does bbox intersection natively and is compiled into Python's `sqlite3` by default. For our use case (bbox intersects county bbox), this is sufficient. County bboxes slightly over-match compared to precise polygon intersection, meaning a few extra counties at edges — acceptable given county-level granularity.

### Query

```python
def counties_for_bbox(db_path, west, south, east, north):
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT c.fips, c.name, c.state_abbr, c.area_sq_km
        FROM counties c
        JOIN counties_rtree r ON c.rowid = r.id
        WHERE r.max_lon >= ? AND r.min_lon <= ?
          AND r.max_lat >= ? AND r.min_lat <= ?
        ORDER BY c.state_abbr, c.name
    """, (west, east, south, north)).fetchall()
    conn.close()
    return rows
```

### Size estimation heuristic

NAIP county mosaics average ~400 MB per 1,000 sq km. The estimate shown to the admin before download is: `sum(area_sq_km) * 0.4 / 1000` GB. This is a rough guide, not exact.

## Generalized Progress Model

### Shared module: `scripts/pipeline_progress.py`

Replaces the inline `update_progress()` in `acquire_imagery.py` and `write_pipeline_state()` in `download_elevation.py`.

### API

```python
def update_progress(state_path: Path, *,
                    source: str,         # "direct", "m2m", "sentinel", "naip", "elevation"
                    status: str,         # "running", "completed", "error", "cancelled"
                    phase: str = None,   # source-specific phase name
                    items_done: int = 0,
                    items_total: int = 0,
                    item_unit: str = "", # "tiles", "scenes", "counties", "geotiffs"
                    bytes_done: int = 0,
                    bytes_total: int = 0,
                    detail: str,         # REQUIRED. Human-readable context for current operation.
                    error: str = None,
                    bbox: str = None,
                    zoom: str = None):
```

**Note:** `status` uses `"completed"` (not `"complete"`) to match existing frontend/backend consumers. The `detail` field is **required** (not optional) — every progress update must include human-readable context. Examples: "Maricopa County, AZ (2.1 GB)", "batch 2/21", "scene S2B_MSIL2A_20260401 (340 MB)".

### State file format

```json
{
  "source": "naip",
  "status": "running",
  "phase": "downloading",
  "items_done": 142,
  "items_total": 347,
  "item_unit": "counties",
  "bytes_done": 68719476736,
  "bytes_total": 152640913408,
  "detail": "Maricopa County, AZ (2.1 GB)",
  "started_at": "2026-04-09T14:30:00Z",
  "last_updated": "2026-04-09T15:45:12Z",
  "bbox": "-124.8,31.3,-102.0,49.0",
  "error": null
}
```

### Frontend rendering (generic)

The progress renderer reads `source`, `items_done`, `items_total`, `item_unit`, `bytes_done`, `phase`, and `detail` to construct the display. No source-specific rendering logic needed:

```
Title:         "{SOURCE_LABEL}: {phase}"
Progress bar:  items_done / items_total (percentage)
Detail line:   "{items_done}/{items_total} {item_unit} — {bytes_formatted}"
Context line:  "{detail}"
```

Source labels: `{"sentinel": "Sentinel-2", "naip": "NAIP", "direct": "USGS Direct", "m2m": "USGS M2M", "elevation": "Elevation"}`.

Examples:
- "NAIP: Downloading — 142/347 counties — 64.0 GB" + detail: "Maricopa County, AZ (2.1 GB)"
- "Sentinel-2: Downloading — 12/45 scenes — 3.2 GB" + detail: "scene S2B_MSIL2A_20260401"
- "USGS Direct: Downloading — 1,240,000/2,590,000 tiles — 23.5 GB"
- "Sentinel-2: Compositing" + detail: "building cloud-free mosaic (chunk 3/8)"
- "NAIP: Converting" + detail: "building MBTiles pyramids"

**Dashboard banner** also uses the `source` field to prefix the pipeline name, e.g., "NAIP: Downloading 142/347 counties".

### Backward compatibility

During migration, the frontend checks for `items_done` (new format). If absent, falls back to `tiles_done` (old format) for in-progress downloads. The shim is removed once all scripts are migrated.

### Migration of existing scripts

- `acquire_imagery.py` — replace inline `update_progress()` with `from pipeline_progress import update_progress`. Map existing fields: `tiles_done` → `items_done`, `tiles_total` → `items_total`, `geotiffs_downloaded` → `items_done` (during M2M downloading phase), etc.
- `download_elevation.py` — replace inline `write_pipeline_state()` with shared `update_progress()`.

## Backend Route Additions

### New helper function mappings

The following helper functions in `services/search/main.py` must be updated to handle the new types:

| Function | `type="sentinel"` | `type="naip"` |
|----------|-------------------|---------------|
| `_state_file_for_type()` | `.sentinel-state.json` | `.naip-state.json` |
| `_mbtiles_path_for_type()` | `imagery_sentinel.mbtiles` | `imagery_naip.mbtiles` |
| `_script_for_type()` | `/scripts/acquire_sentinel.py` | `/scripts/acquire_naip.py` |

The type validation at `pipeline_start()` line 941 must be updated: `type not in ("imagery", "elevation", "osm_poi", "sentinel", "naip")`.

The `pipeline_cancel()` function must include `"sentinel"` and `"naip"` in its state file iteration loop.

### Copernicus credential validation

`pipeline_start(type="sentinel")` checks that `credentials.json` contains `copernicus_username` and `copernicus_password` keys (fast, local check). Actual OAuth2 validation happens in the pipeline script's `authenticating` phase. If auth fails, the state file is written with `status: "error"` and `error: "Invalid Copernicus credentials — check Settings tab"`.

### County lookup endpoint

`GET /admin/pipeline/naip/counties?bbox=...` — queries `counties.sqlite`, returns:
```json
{
  "counties": [{"fips": "04013", "name": "Maricopa", "state": "AZ", "area_sq_km": 23828}],
  "total_counties": 347,
  "states": ["AZ", "CA", "CO", ...],
  "estimated_gb": 142.3
}
```

### Sentinel-2 pre-download estimation

`GET /admin/pipeline/sentinel/estimate?bbox=...&start_date=...&end_date=...&max_cloud=20` — queries STAC API (or returns cached results), returns:
```json
{
  "scenes": 45,
  "estimated_gb": 8.2,
  "date_range": "2026-01-01 to 2026-04-09",
  "cloud_filter": "≤20%"
}
```

This provides the same pre-download confirmation UX as NAIP. The admin sees scene count and estimated size before committing.

## Admin Console Changes

### Pipeline tab layout

Four pipeline cards. **Cards collapsed by default** showing only header + one-line status (e.g., "NAIP Aerial — not configured"). Click to expand. When any pipeline is running, all other Start buttons are greyed out with tooltip: "Another pipeline is running."

Brief header text at top: "Pipelines run one at a time. Recommended order: imagery first, then elevation, then OSM POIs."

1. **Sentinel-2 Imagery (ESA)** — "10m resolution, global, updated every 5 days, free"
   - Bbox (shared minimap)
   - **Progressive disclosure:** Default view shows only bbox + "Download Sentinel-2 Imagery" button with smart defaults. "Show advanced options" toggle reveals:
     - Date range pickers (default: last 6 months)
     - Cloud cover slider (default: 20%) with inline help: "Lower = clearer images but fewer scenes"
     - Composite/Single toggle (default: composite) with help: "Composite merges multiple scenes to remove clouds"
   - Copernicus credentials required — inline link: "Requires free Copernicus account. [Register at dataspace.copernicus.eu →]"
   - Pre-download estimation: shows scene count + estimated size before starting (via `/admin/pipeline/sentinel/estimate`)

2. **NAIP Aerial Imagery (USDA)** — "0.6-1m resolution, US only, county mosaics, free"
   - Bbox (shared minimap)
   - Pre-download confirmation: county list grouped by state, collapsible per-state with "select all / deselect all"
   - Max-height 300px with overflow-y scroll. Summary always visible above list: "347 counties, ~142 GB — [Start Download]"
   - If > 500 counties, show warning: "Large area — consider a smaller bounding box"
   - No credentials needed

3. **USGS Imagery (Legacy)** — "Direct tile scraping or M2M API"
   - Existing source dropdown (direct/m2m), unchanged

4. **Elevation (Terrain-RGB)** — existing, unchanged

### Settings tab

New "Copernicus Credentials" section alongside existing M2M credentials:
- Username field
- Password field
- Test Connection button
- Direct link: "Register for free at [dataspace.copernicus.eu](https://dataspace.copernicus.eu/)"

### Dashboard banner

Works with generic progress model. Shows whichever pipeline is currently running with phase + progress.

## Frontend Map Changes

### New raster sources

Two new raster tile sources in `app.js`, added to the map when their respective MBTiles file is detected (via TileServer TileJSON endpoint responding successfully):

- `imagery-naip` — from `/data/imagery_naip/{z}/{x}/{y}.jpg`
- `imagery-sentinel` — from `/data/imagery_sentinel/{z}/{x}/{y}.jpg`

Both read `maxzoom` from TileJSON. No hardcoded zoom limits.

### Layer switcher

Two new checkboxes in the layer control panel, with sublabels for disambiguation:
- "NAIP Aerial" + sublabel "(0.6m, US)" — toggles `imagery-naip` source visibility
- "Sentinel-2" + sublabel "(10m, global)" — toggles `imagery-sentinel` source visibility

Each checkbox is only rendered if the corresponding TileJSON endpoint returns a valid response (i.e., the MBTiles file exists and TileServer is serving it). The frontend polls TileJSON endpoints every 30 seconds (or on pipeline state change) to detect newly available sources after pipeline completion.

Existing "Aerial Imagery" toggle renamed to "USGS Legacy" + sublabel "(varies)" for clarity.

**Performance note:** If multiple imagery layers are enabled simultaneously, show a subtle one-line note: "Multiple imagery layers active. Toggle off unused layers for better performance."

### Layer stacking order (bottom to top)

1. Vector basemap (positron/darkmatter)
2. Sentinel-2 raster (if enabled)
3. NAIP raster (if enabled)
4. USGS legacy imagery raster (if enabled)
5. Public lands polygons
6. Routes
7. POI markers, GPS position, KMZ overlays

NAIP on top of Sentinel-2 ensures the higher-resolution source takes priority where both are available.

## TileServer Configuration

Add to `tileserver/config.json` data sources. **IMPORTANT:** Use the correct container mount path (`/srv/data/`, not `/data/` — the TileServer container mounts `./data` to `/srv/data/`):

```json
{
  "imagery_naip": {
    "mbtiles": "/srv/data/imagery_naip.mbtiles"
  },
  "imagery_sentinel": {
    "mbtiles": "/srv/data/imagery_sentinel.mbtiles"
  }
}
```

TileServer GL auto-generates TileJSON endpoints for each, including `maxzoom` from MBTiles metadata.

### Handling missing MBTiles at startup

TileServer GL may fail to start if configured MBTiles files don't exist. Since the new MBTiles are only created after running the pipeline, we need a safe approach:

**Solution:** Do NOT add the entries to `tileserver/config.json` at deployment time. Instead, after a pipeline completes successfully, the search service:
1. Reads the current `config.json`
2. Adds the new data source entry if not already present
3. Writes the updated config
4. Restarts the tileserver container via Docker API: `client.containers.get("geographica-tileserver").restart()`

This ensures TileServer only references MBTiles files that actually exist. The frontend's TileJSON fetch will get 404 for sources not yet in config (layer toggle hidden), and 200 once the pipeline has completed and TileServer has been restarted.

**Cold-start safety:** A fresh deployment with no pipeline outputs will have only the original config entries (openmaptiles, imagery, elevation). The new entries are added dynamically. An integration test must verify: `docker compose up` with no `imagery_naip.mbtiles` or `imagery_sentinel.mbtiles` → TileServer starts healthy.

## NGINX Configuration

Add `sub_filter` rules for the new TileJSON endpoints so that internal Docker hostnames are rewritten to the external-facing URL, matching the existing pattern for imagery and elevation TileJSON.

## Docker Configuration

### Pipeline container

Ensure the pipeline container Dockerfile includes:
- OpenJPEG support in GDAL (for JPEG2000 county mosaics)
- Python `sqlite3` with rtree support (standard in CPython)

### Volume mounts

TileServer service needs read access to the two new MBTiles files. These are already in `/srv/geographica/data/` which is mounted as `/data` in the tileserver container.

## New files

| File | Purpose |
|------|---------|
| `scripts/acquire_sentinel.py` | Sentinel-2 pipeline script |
| `scripts/acquire_naip.py` | NAIP pipeline script |
| `scripts/pipeline_progress.py` | Shared generalized progress module |
| `scripts/build_county_index.py` | One-time county SQLite builder |
| `data/counties.sqlite` | Bundled county boundary rtree database (~5MB) |

## Modified files

| File | Changes |
|------|---------|
| `scripts/acquire_imagery.py` | Refactor to use `pipeline_progress.py` |
| `scripts/download_elevation.py` | Refactor to use `pipeline_progress.py` |
| `services/search/main.py` | Add `sentinel` and `naip` types, county lookup endpoint, Copernicus credentials |
| `frontend/config/index.html` | New pipeline cards, generic progress renderer, county confirmation UI |
| `frontend/app.js` | New raster sources + layer toggles, dynamic maxzoom from TileJSON |
| `tileserver/config.json` | Add `imagery_naip` and `imagery_sentinel` data sources |
| `docker-compose.yml` | Ensure GDAL JP2 support in pipeline container |
| `nginx/nginx.conf` | Add `sub_filter` rules for new TileJSON endpoints |

## Testing strategy

### Unit tests

- `tests/test_pipeline_progress.py` — generic progress model: write/read/merge state file, all field combinations, backward compat shim
- `tests/test_county_lookup.py` — bbox → county intersection: known bboxes, edge cases (bbox spanning state lines, single-county bbox, bbox outside US)
- `tests/test_acquire_sentinel.py` — STAC query construction, scene filtering by cloud cover, composite vs single mode selection
- `tests/test_acquire_naip.py` — county FIPS → download URL construction, checkpoint resume, format preference (JP2 over MrSID)

### Integration tests

- Pipeline start/cancel for each new type via admin API
- County lookup endpoint returns correct results for known bboxes
- Progress state file written correctly during each phase
- TileServer serves new MBTiles sources with correct TileJSON (including maxzoom)

### Manual E2E tests

- Start Sentinel-2 pipeline from admin console with small bbox, verify scenes download and composite
- Start NAIP pipeline from admin console with small bbox (single county), verify county confirmation → download → conversion
- Verify both layers appear in main map layer switcher
- Verify layers toggle independently
- Verify zoom behavior: Sentinel-2 upscales past z14, NAIP renders at full resolution

## Risks and mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| USDA Gateway changes URL structure | NAIP pipeline breaks | Discovery phase parses actual responses, not inferred URL templates. `discovered_urls.json` checkpoint. |
| Copernicus API changes or adds rate limits | Sentinel-2 pipeline breaks or slows | Token bucket rate limiter, exponential backoff + retry on 429/503, STAC version check |
| MrSID files offered without JP2 alternative | Counties skipped | MrSID is unsupported on ARM64. JP2-only. MrSID counties skipped with clear warning in progress detail. |
| County bbox over-matching downloads extra data | Wasted bandwidth/storage | Acceptable trade-off; admin sees county list + state-grouped confirmation before starting |
| NAIP county mosaics are very large (GB each) | Long download times, disk pressure | Per-county streaming: download → convert → append → delete staging. Disk check before each county. |
| Sentinel-2 composite exceeds 2GB container memory | OOM crash | Spatial chunking (2x2 degree), `GDAL_CACHEMAX=256`, sequential processing |
| NAIP merge exceeds disk space | Disk fill crashes entire system | Per-county streaming conversion avoids holding all staging simultaneously. Pre-flight + per-county disk checks. |
| CPU thermal throttling during multi-day GDAL operations | Degraded service performance | `nice -n 19`, `ionice -c2 -n7`, `GDAL_NUM_THREADS=2`, documented expected processing times in admin UI |
| Frontend hardcodes maxzoom for new layers | Blocks future higher-res data display | Mandated: use `map.addSource(..., { url: tilejson_url })`. Acceptance test: no numeric `maxzoom` in any imagery source. Existing legacy source migrated too. |
| Copernicus OAuth2 token expires mid-download | 401 errors during download | Token refresh before each batch; re-authenticate if refresh fails |
| TileServer crash with missing MBTiles at startup | Stack boot failure | Dynamic config: entries added only after pipeline completion + TileServer restart via Docker API |
| Backend helpers route new types to wrong files | Data corruption | Explicit mapping table for state files, mbtiles paths, and scripts per type |

## Adversarial review notes

This spec was reviewed by 5 independent adversarial agents (Haiku, 2x Opus, Codex/GPT-5.4, and a UX specialist). All CRITICAL and HIGH findings have been addressed in this revision. Key finding that all 5 reviewers flagged: **the maxzoom hardcoding risk requires a concrete implementation pattern (TileJSON URL form), not just a policy statement.** The spec now mandates the specific MapLibre addSource pattern and requires an acceptance test.
