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
- **No hardcoded maxzoom in the frontend** — each layer reads `maxzoom` from TileServer's TileJSON response dynamically. This prevents a repeat of bug B1 where hardcoded `maxzoom: 14` blocked display of higher-resolution tiles that had been downloaded. The MBTiles metadata is the single source of truth for zoom limits.
- **Generalized progress model** — all pipeline scripts use a shared progress module with generic `items_done/items_total/item_unit` fields instead of source-specific fields.

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

- **JPEG2000** — GDAL handles natively via OpenJPEG. Preferred.
- **MrSID** — requires proprietary GDAL MrSID driver (Extensis/Ceridian SDK). The script prefers JP2 downloads when available and falls back to MrSID only if JP2 is not offered.

The pipeline container's GDAL installation must include OpenJPEG support (`--with-openjpeg` or equivalent).

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
                    status: str,         # "running", "complete", "error", "cancelled"
                    phase: str = None,   # source-specific phase name
                    items_done: int = 0,
                    items_total: int = 0,
                    item_unit: str = "", # "tiles", "scenes", "counties", "geotiffs"
                    bytes_done: int = 0,
                    bytes_total: int = 0,
                    detail: str = "",    # human-readable, e.g. "batch 2/21" or "Maricopa County, AZ"
                    error: str = None,
                    bbox: str = None,
                    zoom: str = None):
```

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

The progress renderer reads `items_done`, `items_total`, `item_unit`, `bytes_done`, and `phase` to construct the display. No source-specific rendering logic needed:

```
Progress bar:  items_done / items_total (percentage)
Detail line:   "{phase}: {items_done}/{items_total} {item_unit} — {bytes_formatted}"
```

Examples:
- "Downloading: 142/347 counties — 64.0 GB"
- "Downloading: 12/45 scenes — 3.2 GB"
- "Downloading: 1,240,000/2,590,000 tiles — 23.5 GB"
- "Compositing: processing cloud-free mosaic..."
- "Converting: building MBTiles pyramids..."

### Backward compatibility

During migration, the frontend checks for `items_done` (new format). If absent, falls back to `tiles_done` (old format) for in-progress downloads. The shim is removed once all scripts are migrated.

### Migration of existing scripts

- `acquire_imagery.py` — replace inline `update_progress()` with `from pipeline_progress import update_progress`. Map existing fields: `tiles_done` → `items_done`, `tiles_total` → `items_total`, `geotiffs_downloaded` → `items_done` (during M2M downloading phase), etc.
- `download_elevation.py` — replace inline `write_pipeline_state()` with shared `update_progress()`.

## Admin Console Changes

### Pipeline tab layout

Four pipeline cards, each independently startable/cancellable:

1. **Sentinel-2 Imagery (ESA)** — "10m resolution, global, updated every 5 days, free"
   - Bbox (shared minimap)
   - Date range pickers (default: last 6 months)
   - Cloud cover slider (default: 20%)
   - Composite/Single toggle (default: composite)
   - Copernicus credentials required (link to Settings tab if not configured)

2. **NAIP Aerial Imagery (USDA)** — "0.6-1m resolution, US only, county mosaics, free"
   - Bbox (shared minimap)
   - Pre-download confirmation: county list + estimated size
   - No credentials needed

3. **USGS Imagery (Legacy)** — "Direct tile scraping or M2M API"
   - Existing source dropdown (direct/m2m), unchanged

4. **Elevation (Terrain-RGB)** — existing, unchanged

### Settings tab

New "Copernicus Credentials" section alongside existing M2M credentials:
- Username field
- Password field
- Test Connection button

### Dashboard banner

Works with generic progress model. Shows whichever pipeline is currently running with phase + progress.

## Frontend Map Changes

### New raster sources

Two new raster tile sources in `app.js`, added to the map when their respective MBTiles file is detected (via TileServer TileJSON endpoint responding successfully):

- `imagery-naip` — from `/data/imagery_naip/{z}/{x}/{y}.jpg`
- `imagery-sentinel` — from `/data/imagery_sentinel/{z}/{x}/{y}.jpg`

Both read `maxzoom` from TileJSON. No hardcoded zoom limits.

### Layer switcher

Two new checkboxes in the layer control panel:
- "NAIP Aerial" — toggles `imagery-naip` source visibility
- "Sentinel-2" — toggles `imagery-sentinel` source visibility

Each checkbox is only rendered if the corresponding TileJSON endpoint returns a valid response (i.e., the MBTiles file exists and TileServer is serving it).

Existing "Aerial Imagery" toggle for USGS legacy source remains.

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

Add to `tileserver/config.json` data sources:

```json
{
  "imagery_naip": {
    "mbtiles": "/data/imagery_naip.mbtiles"
  },
  "imagery_sentinel": {
    "mbtiles": "/data/imagery_sentinel.mbtiles"
  }
}
```

TileServer GL auto-generates TileJSON endpoints for each, including `maxzoom` from MBTiles metadata.

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
| USDA Gateway changes URL structure | NAIP pipeline breaks | URL construction is isolated in `acquire_naip.py`; easy to update |
| Copernicus API changes or adds rate limits | Sentinel-2 pipeline breaks or slows | Token bucket rate limiter, same pattern as existing pipelines |
| MrSID files offered without JP2 alternative | Need proprietary GDAL driver | Script prefers JP2; if only MrSID, log clear error with instructions |
| County bbox over-matching downloads extra data | Wasted bandwidth/storage | Acceptable trade-off; admin sees confirmation with county list before starting |
| NAIP county mosaics are very large (GB each) | Long download times, disk pressure | Checkpoint/resume per county; disk space check before starting |
| Sentinel-2 composite processing is CPU-intensive | Slow on Pi 5 | Pi 5 has 4 cores; GDAL VRT + median composite is not worse than existing GDAL operations |
| Frontend hardcodes maxzoom for new layers | Blocks future higher-res data display | Explicitly prevented: maxzoom always read from TileJSON, never hardcoded |
