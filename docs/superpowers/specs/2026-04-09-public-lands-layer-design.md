# Public Lands Mapping Layer — Design Spec

**Date:** 2026-04-09
**Status:** Approved
**Scope:** New vector tile overlay layer showing color-coded public land boundaries (BLM, USFS, NPS, etc.)

## Problem Statement

Public land mapping is critical for amateur radio operators and outdoorsmen but poorly integrated into most mobile mapping software. Users rely on third-party solutions like OnX. BLM and other agencies publish land boundary data freely, but it's not rendered in Geographica's basemap tiles because the OpenMapTiles Planetiler profile drops `boundary=protected_area` polygons that don't match its narrow rendering filters (national parks and nature reserves only). Large BLM areas appear blank.

## Architecture: Vector Tile Overlay

A separate `public-lands.mbtiles` vector tile set generated from the USGS PAD-US (Protected Areas Database) dataset, served as a new TileServer GL data source. The frontend renders it as a togglable semi-transparent fill overlay with color-coded agency shading, independent of the basemap style.

**Why this approach:**
- Pre-rendered vector tiles = excellent performance (same paradigm as basemap)
- Independent of basemap style — works over positron, darkmatter, or any future style
- Togglable with opacity control
- Semi-transparent fills drape correctly over MapLibre 3D terrain
- PAD-US is the authoritative data source (what OnX and commercial products use)

## Section 1: Data Pipeline

### Data Source: PAD-US 4.0

USGS Protected Areas Database of the United States. Contains every public land parcel with standardized owner/manager categories, GAP status codes, and designation types.

- **Download:** PAD-US 4.0 Combined Fee GeoPackage from USGS ScienceBase
- **Size:** ~2GB download for CONUS
- **Layer:** `PADUS4_0Combined_Proclamation_Marine_Fee_Designation_Easement` (Fee layer — fee-simple ownership)
- **Key fields:**
  - `Mang_Name` — managing agency (BLM, USFS, NPS, FWS, etc.)
  - `Des_Tp` — designation type (National Forest, Wilderness Area, National Monument, etc.)
  - `GAP_Sts` — GAP conservation status (1-4)
  - `Unit_Nm` — unit name (e.g., "Lake Mead National Recreation Area")
  - `Loc_Nm` — location name
  - `State_Nm` — state

### Agency Classification

Map PAD-US `Mang_Name` values to display categories:

| PAD-US Mang_Name | Display Category | Fill Color | Outline Color |
|---|---|---|---|
| BLM | BLM | `#f5deb3` (wheat) | `#c8a870` |
| USFS | National Forest | `#228b22` (forest green) | `#1a6b1a` |
| NPS | National Park | `#006400` (dark green) | `#004d00` |
| FWS | Fish & Wildlife | `#008080` (teal) | `#006666` |
| DOD | Military | `#8b4545` (red-gray) | `#6b3535` |
| USBR | Bureau of Reclamation | `#4682b4` (steel blue) | `#366fa0` |
| TRIB / BIA | Tribal / BIA | `#cd853f` (peru) | `#a0682f` |
| `Mang_Type='STAT'` | State Trust | `#d2691e` (chocolate) | `#a34f1a` |
| Any with `Des_Tp` containing "Wilderness" | Wilderness | `#800080` (purple) | `#660066` |
| All other federal | Other Federal | `#a9a9a9` (dark gray) | `#808080` |

**Classification priority order:**
1. If `Des_Tp` contains "Wilderness" → Wilderness (regardless of agency — wilderness areas within national forests get distinct purple)
2. Match `Mang_Name` against known federal agencies (BLM, USFS, NPS, FWS, DOD, USBR, TRIB, BIA)
3. If `Mang_Type = 'STAT'` → State Trust (catches all state agency codes without hardcoding each: SDNR, SFISH, SLAND, SPARK, SFWD, SOTH, SBOE, etc.)
4. All remaining → Other Federal

**Tribal lands note:** PAD-US includes tribal lands under `Mang_Name = TRIB` or `BIA`, but coverage is incomplete — many tribal nations have not consented to inclusion. Large Western US tribal areas (Navajo Nation ~71,000 sq km, Tohono O'odham, Fort Apache, etc.) may be partially mapped. The legend should include a disclaimer: "Tribal boundaries may be incomplete."

**Military land note:** DOD boundaries are publicly available data (they appear on USGS topo maps). The legend should note "Military — restricted access" to prevent users from assuming these areas are accessible public land.

### Pipeline Script: `scripts/build_public_lands.py`

New Python script following the pattern of `build_poi_index.py` and `acquire_imagery.py`:

**Arguments:**
- `--bbox` — bounding box (default: Western US `-124.8,31.3,-102.0,49.0`)
- `--output` — output MBTiles path (default: `/srv/geographica/data/public-lands.mbtiles`)
- `--padus-url` — PAD-US download URL (default: USGS ScienceBase URL)
- `--cache-dir` — directory for downloaded/intermediate files (default: `/srv/geographica/data/padus_cache/`)
- `--sample` — if set, use the sample bbox for quick testing

**Steps:**
1. Download PAD-US GeoPackage to cache dir (with retry-with-backoff; Range resume if server supports it)
2. Auto-detect the Fee/Combined layer name: run `ogrinfo padus.gpkg` and match pattern `PADUS*Fee*` or `PADUS*Combined*`. Fail with clear error if no match (PAD-US version may have changed). Verify output is non-empty after clipping.
3. Clip and reproject with ogr2ogr: `ogr2ogr -clipsrc {bbox} -t_srs EPSG:4326 -f GeoJSON clipped.geojson padus.gpkg {detected_layer}` — PAD-US is published in NAD83 (EPSG:4269); explicit WGS84 reprojection ensures Tippecanoe gets correct coordinates.
4. Classify features using ogr2ogr SQL (avoids loading entire GeoJSON into Python memory): `ogr2ogr -sql "SELECT Unit_Nm AS name, Mang_Name AS agency, Des_Tp AS designation, Mang_Type, CASE WHEN Des_Tp LIKE '%Wilderness%' THEN 'Wilderness' WHEN Mang_Name IN ('BLM') THEN 'BLM' WHEN Mang_Name IN ('USFS') THEN 'USFS' WHEN Mang_Name IN ('NPS') THEN 'NPS' WHEN Mang_Name IN ('FWS') THEN 'FWS' WHEN Mang_Name IN ('DOD') THEN 'DOD' WHEN Mang_Name IN ('USBR') THEN 'USBR' WHEN Mang_Name IN ('TRIB','BIA') THEN 'Tribal' WHEN Mang_Type = 'STAT' THEN 'State' ELSE 'Other' END AS category FROM {layer}" ...` This avoids the Python GeoJSON memory bottleneck entirely.
5. Run Tippecanoe: `tippecanoe -o {output} -Z0 -z14 -l public_lands --coalesce-smallest-as-needed --simplification=10 --detect-shared-borders -pk clipped_classified.geojson`
6. Verify output: check MBTiles has expected zoom levels and non-zero tile count
7. Report: tile count, file size, categories found, total features

**Dependencies:** ogr2ogr (GDAL), tippecanoe, Python 3

**Tippecanoe flags explained:**
- `-Z0 -z14` — zoom levels 0-14 (matching basemap)
- `-l public_lands` — layer name in the vector tiles
- `--coalesce-smallest-as-needed` — merge the smallest adjacent same-category polygons at low zooms to reduce tile size. **Do NOT use `--drop-densest-as-needed`** — that drops entire polygons, causing BLM areas composed of many small cadastral polygons to disappear at low zoom.
- `--simplification=10` — simplify polygon vertices at low zoom (10 = moderate simplification). This reduces vertex count without dropping entire features.
- `--detect-shared-borders` — prevents gaps between adjacent polygons when simplifying shared boundaries
- `-pk` — no tile size limit (preserves all feature properties for click popups; accept larger tiles)
- **Do NOT use `--extend-zooms-if-still-dropping`** — contradicts `maxzoom: 14` on the MapLibre source

**CRS note:** PAD-US is published in NAD83 (EPSG:4269). The ~1m difference from WGS84 is invisible at render zoom but the `-t_srs EPSG:4326` ensures correctness for Tippecanoe.

**Overlapping polygons:** PAD-US contains overlapping features (e.g., wilderness areas inside national forests). Classification adds a `sort_key` field (Wilderness=1, NPS=2, USFS=3, etc.) and Tippecanoe's `-pk` preserves it. The frontend uses `fill-sort-key: ['get', 'sort_key']` to render wilderness on top. At semi-transparent opacity, overlapping zones will appear slightly darker — this is acceptable and matches how OnX renders the same data.

**Memory and performance guidance:**
- **Full Western US build:** Tippecanoe requires 4-6GB free RAM for the full dataset. The ogr2ogr SQL classification avoids Python memory overhead. **Recommend running with Docker services stopped** (`docker compose stop`) or building on an x86 machine and copying the MBTiles to the Pi.
- **Sample build (NW Arizona bbox):** Runs fine on Pi 5 with services active (~50MB intermediate data).
- **Expected build time:** Sample: 2-5 minutes. Full Western US: 30-90 minutes on Pi 5, 5-15 minutes on x86.

**Host execution note:** This script runs on the host, NOT via `docker compose run pipeline`. Tippecanoe is a compiled C++ binary that must be installed on the host (or built from source on ARM64). This is the only pipeline script with this constraint — all others run in the pipeline Docker container.

### Sample Pipeline for Visual Testing

Before running full Western US, generate a sample for NW Arizona / Hoover Dam region:

**Sample bbox:** `[-115.5, 35.5, -113.5, 36.5]`

This area contains:
- Lake Mead NRA (NPS, dark green)
- Extensive BLM land west of Kingman (wheat)
- State Trust checkerboard south of I-40 (chocolate)
- Wilderness areas: Warm Springs, Mt. Tipton (purple)
- Small USFS parcels (forest green)

Run: `python scripts/build_public_lands.py --sample --output /srv/geographica/data/public-lands.mbtiles`

## Section 2: TileServer GL Integration

Add `publiclands` data source to `tileserver/config.json`:

```json
"data": {
  "southwest5": { "mbtiles": "southwest5.mbtiles" },
  "elevation": { "mbtiles": "/srv/data/elevation.mbtiles" },
  "imagery": { "mbtiles": "/srv/data/imagery.mbtiles" },
  "publiclands": { "mbtiles": "/srv/data/public-lands.mbtiles" }
}
```

TileServer GL automatically serves vector tiles at `/tiles/data/publiclands/{z}/{x}/{y}.pbf`. No style changes to positron or darkmatter style files.

## Section 3: Frontend Layer Integration

### Source and Layers

In `addPlaceholderSources()` (frontend/app.js), **AFTER the `imported-points` layer is created** (critical — the `before` parameter references a layer that must already exist):

**Source:**
```js
map.addSource('public-lands', {
  type: 'vector',
  tiles: [window.location.origin + '/tiles/data/publiclands/{z}/{x}/{y}.pbf'],
  maxzoom: 14
});
```

**Fill layer** (semi-transparent, color-coded by category):
```
Layer: public-lands-fill (type: fill)
  source: public-lands
  source-layer: public_lands
  paint:
    fill-color: ['match', ['get', 'category'],
      'BLM', '#f5deb3', 'USFS', '#228b22', 'NPS', '#006400',
      'FWS', '#008080', 'DOD', '#8b4545', 'USBR', '#4682b4',
      'Tribal', '#cd853f', 'State', '#d2691e', 'Wilderness', '#800080',
      '#a9a9a9']
    fill-opacity: 0.3
    fill-sort-key: ['get', 'sort_key']   // Wilderness on top of forest, etc.
  before: 'imported-points'  // MUST be added AFTER imported-points exists in addPlaceholderSources
```

**Outline layer** (boundary lines):
```
Layer: public-lands-outline (type: line)
  source: public-lands
  source-layer: public_lands
  paint:
    line-color: ['match', ['get', 'category'],
      'BLM', '#c8a870', 'USFS', '#1a6b1a', 'NPS', '#004d00',
      'FWS', '#006666', 'DOD', '#6b3535', 'USBR', '#366fa0',
      'Tribal', '#a0682f', 'State', '#a34f1a', 'Wilderness', '#660066',
      '#808080']
    line-width: 1
    line-opacity: 0.6
  before: 'imported-points'
```

**Layer insertion:** Both layers inserted BELOW imported features and search pins, ABOVE the basemap. This ensures KMZ imports and search results render on top of public land shading.

### Toggle UI

In `frontend/index.html`, add to the layer controls panel alongside imagery/hillshade/terrain:

```html
<label><input type="checkbox" id="toggle-public-lands"> Public Lands</label>
<input type="range" id="public-lands-opacity" min="0" max="100" value="50">
```

**Toggle logic in `initLayerControls()`:**
- Checkbox toggles visibility of both `public-lands-fill` and `public-lands-outline`
- Opacity slider: value 0-100 maps to fill-opacity `val / 100 * 0.6`. Default slider value = 50 (produces 0.3, matching layer default). Outline opacity coupled: `val / 100 * 0.8`.
- **Layer `fill-opacity` in the addLayer call must be `0.3`** (matching slider default 50). No UX jump on first slider touch.
- Layers default to hidden (checkbox unchecked) — user opts in

**Style swap restoration in `syncLayerVisibility()`:**
Explicitly restore public lands state after style swap (following imagery toggle pattern):
1. Read `#toggle-public-lands` checked state → set layer visibility
2. Read `#public-lands-opacity` slider value → apply fill-opacity and line-opacity via `setPaintProperty`

### Click Interaction

**Dedicated click handler:** Register `map.on('click', 'public-lands-fill', ...)` showing popup:
- **Title:** Unit name (e.g., "Lake Mead National Recreation Area")
- **Subtitle:** Managing agency + designation type (e.g., "NPS — National Recreation Area")
- **Category badge:** Colored dot matching the fill color

**Generic click handler exclusion:** Add `'public-lands-fill'` to the `queryRenderedFeatures` layer array in the generic click handler (line ~1103). Without this, clicking a public land polygon fires BOTH the dedicated popup AND a reverse geocode. The dedicated handler fires first (MapLibre dispatches layer-specific before generic), then the exclusion prevents the generic handler from also firing.

### Terrain Interaction

MapLibre's `fill` layers drape correctly over 3D terrain mesh automatically. Semi-transparency (0.3 default) ensures elevation hillshading shows through. No special handling needed — tested in MapLibre GL JS with raster-dem terrain + fill layers.

## Section 4: Visual Verification via Playwright Browser

After sample tile generation, verify the rendering visually:

1. Navigate Playwright to running Geographica at `http://localhost:8093`
2. Enable the Public Lands toggle via UI interaction
3. Fly to test area: center `[-114.5, 36.0]`, zoom 9
4. Screenshot with public lands overlay visible
5. Visual comparison: verify BLM (wheat), NPS (dark green), USFS (forest green), State Trust (chocolate), Wilderness (purple) all rendering correctly relative to known landmarks (Hoover Dam, Kingman, Lake Mead)
6. Zoom to 12-13, screenshot for boundary precision
7. Toggle terrain exaggeration on, screenshot to verify no clipping/fighting
8. Switch to darkmatter basemap, screenshot to verify overlay works on dark style
9. Adjust colors if needed (MapLibre paint property change only, no re-tiling)

## Section 5: Legend UI

Compact legend in the layer controls panel, visible when Public Lands toggle is enabled:

```
  ■ BLM          ■ Nat'l Forest
  ■ Nat'l Park   ■ Fish & Wildlife
  ■ Military*    ■ Bur. of Reclamation
  ■ Tribal†      ■ State Trust
  ■ Wilderness   ■ Other Federal
```
\* Restricted access
† Boundaries may be incomplete

Layout: `display: grid; grid-template-columns: 1fr 1fr` with 10 items (5 rows x 2 cols, no orphan).

- 12x12px colored squares next to category labels
- Two-column layout to save vertical space
- Hidden when toggle is off (CSS visibility tied to checkbox state)
- Catppuccin Mocha dark theme styling consistent with existing UI

## Files Modified

| File | Changes |
|------|---------|
| `scripts/build_public_lands.py` | **NEW** — PAD-US download, classification, Tippecanoe tile generation |
| `tileserver/config.json` | Add `publiclands` data source |
| `frontend/app.js` | Public lands source/layers in addPlaceholderSources, toggle logic, click popup, syncLayerVisibility |
| `frontend/index.html` | Public Lands checkbox, opacity slider, legend HTML |
| `frontend/style.css` | Legend styles, toggle interaction |

## Dependencies

- **ogr2ogr** (GDAL) — for GeoPackage clipping. Install: `apt install gdal-bin` or `pip install GDAL`
- **Tippecanoe** — for vector tile generation. Not available as an apt package on ARM64/Raspberry Pi. Must be built from source: `git clone https://github.com/felt/tippecanoe.git && cd tippecanoe && make -j4 && sudo make install`. Requires `libsqlite3-dev` and `zlib1g-dev`. Alternatively, run tile generation on an x86 machine and copy the MBTiles file to the Pi.
- Both must be installed on the Pi 5 before running the pipeline

## Storage Estimate

| Component | Size |
|-----------|------|
| PAD-US GeoPackage (cached) | ~2 GB |
| Clipped GeoJSON (intermediate, deleted after) | ~200 MB |
| public-lands.mbtiles (final) | ~50-200 MB |
| **Total new permanent storage** | **~50-200 MB** |

Negligible relative to imagery (53 GB) and elevation (119 GB).

**Scope note:** This pipeline is scoped to the Western US bbox. Alaska and Hawaii are excluded from the default configuration. PAD-US covers both, but the basemap tiles (`southwest5.mbtiles`) do not — the public lands overlay would render with no basemap underneath. The `--bbox` parameter can be adjusted for other regions if basemap tiles are generated for them.

## Testing Strategy

- Pipeline test: run with `--sample` bbox, verify MBTiles output has expected layers and zoom levels
- Frontend test: verify toggle shows/hides layers, opacity slider works, style swap preserves state
- Visual test: Playwright screenshots of Hoover Dam area against known maps
- Performance test: enable public lands + terrain + hillshade simultaneously, verify smooth pan/zoom on Pi 5
- Click test: click on a public land polygon, verify popup shows correct name/agency/designation
