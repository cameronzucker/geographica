# NOAA NAIP Download + BYO Imagery Import

**Date:** 2026-04-14
**Status:** Approved (pending catalog population)

## Problem

High-resolution NAIP aerial imagery is difficult to acquire programmatically. The USDA Gateway is down (since April 2026). The USGS National Map ImageServer throttles sustained downloads to ~1 tile/sec. EarthExplorer's bulk download UI requires clicking through 9,000+ pages. Users need a practical path to 0.6m aerial imagery.

## Solution

Two complementary features:

1. **NOAA NAIP automated download** — new `noaa` mode in `acquire_imagery.py`. Downloads 4-band GeoTIFFs from NOAA Digital Coast's Azure Blob Storage (no auth, no throttling, public `wget` access), converts to MBTiles using existing batch pipeline infrastructure.

2. **BYO GeoTIFF import** — users place GeoTIFFs from any source in an import directory, click "Import" in the admin panel. Converts to MBTiles using the same pipeline.

## Design Decisions

1. **NOAA as primary NAIP source** — Azure Blob Storage is unthrottled, no auth, NOAA recommends `wget`. ~3.4 MB/s download speed confirmed.
2. **Batch download-convert-delete** — process N tiles at a time, never more than batch_size × 486 MB staging. Same pattern as M2M pipeline.
3. **Upfront estimate with disk check** — show tile count, raw download size, estimated MBTiles size, and available disk before starting.
4. **Static catalog for state/year → blob path** — NOAA archive updates infrequently. Manual lookup is practical. Ships with Western US states.
5. **BYO imports to `imagery_custom.mbtiles` by default** — optional named layers create separate MBTiles files.
6. **Import via drop directory** — `/srv/geographica/data/import/`. More practical than browser upload for multi-GB files.
7. **Add to existing source dropdown** — "NOAA NAIP" joins Direct/M2M/National Map. Deeper UX redesign deferred.

## NOAA Data Source

```
https://coastalimagery.blob.core.windows.net/digitalcoast/{STATE}_NAIP_{YEAR}_{ID}/
```

| Property | Value |
|----------|-------|
| Auth | None — public Azure blob |
| Throttling | None observed |
| Format | 4-band GeoTIFF, 0.6m resolution |
| Tile size | ~486 MB each (3.75' × 3.75' quad) |
| Organization | Per-state, per-year, with URL list + shapefile index |
| Download speed | ~3.4 MB/s tested |
| Arizona | 7,629 tiles, ~3.6 TB total |
| Phoenix metro | ~512 tiles, ~243 GB |

Each state/year directory contains:
- `urllist_*.txt` — pre-built list of every file URL
- Tile index shapefile — exact geometry for spatial queries
- GeoTIFFs — the actual imagery
- VRT files — pre-built virtual rasters per UTM zone

### State/Year Catalog

Static dict mapping `(state_abbr, year)` → NOAA blob directory name.

```python
NOAA_NAIP_CATALOG = {
    ("AZ", 2021): "AZ_NAIP_2021_9596",
    # Additional states populated during implementation via NOAA Data Access Viewer lookup
}
```

Ships with confirmed Western US states. Adding a new state/year is a one-line dict entry.

### Tile-to-Bbox Filtering

Rather than parsing filenames, download the tile index shapefile (small, ~1-5 MB) once per state and cache it. Use OGR spatial query to find tiles intersecting the user's bbox:

```bash
ogr2ogr -f CSV /dev/stdout tile_index.shp -spat west south east north -geom=NO
```

Returns filenames of intersecting tiles. Exact spatial match, no filename parsing.

### Pipeline Flow

1. **Select state** → fetch + cache tile index shapefile
2. **Draw bbox** → spatial query against shapefile → list of intersecting tiles
3. **Estimate** → count × ~486 MB raw, estimate compressed MBTiles size, check disk
4. **User confirms** → download tiles in batches
5. **Per batch:** download N GeoTIFFs → `convert_batch_to_mbtiles()` → delete raw files
6. **Progress** → structured reporting to admin panel (same as M2M)
7. **Output** → `imagery_noaa.mbtiles`

### Admin Panel Integration

- Add "NOAA NAIP (0.6m, free)" to source dropdown
- When selected: zoom controls hidden (fixed resolution), state dropdown shown, bbox used for filtering
- State dropdown populated from `NOAA_NAIP_CATALOG` keys
- Year shown as label next to state name
- Estimate shows: "N tiles intersect bbox, ~X GB download, ~Y GB final"

## BYO GeoTIFF Import

### User Flow

1. User places `.tif` files in `/srv/geographica/data/import/`
2. Opens admin panel → "Import Custom Imagery" card
3. Card shows: files found, total size
4. Optional: enters a layer name (default merges into `imagery_custom.mbtiles`)
5. Optional: "Delete source files after import" checkbox (default: checked)
6. Clicks "Import"
7. Pipeline converts all GeoTIFFs to MBTiles via `convert_batch_to_mbtiles()`
8. Progress shown in admin panel
9. Source files deleted (if checkbox checked)

### Output Files

- **No name (default):** `imagery_custom.mbtiles` — all imports merge here
- **Named (e.g., "phoenix drone"):** `imagery_phoenix_drone.mbtiles` — sanitized filename
- **Existing target:** new tiles merge in, existing tiles at same z/x/y overwritten

### Admin Panel Card

Placed below existing pipeline cards:

```
┌─ Import Custom Imagery ──────────────────────────┐
│ Import directory: /srv/geographica/data/import/   │
│ Files found: 12 GeoTIFFs (5.8 GB)    [Refresh]   │
│                                                   │
│ Layer name: [________________________] (optional)  │
│ ☑ Delete source files after import                │
│                                                   │
│ [Import]                                          │
│ ░░░░░░░░░░░░░░░░░░░░ 0%                          │
└───────────────────────────────────────────────────┘
```

### Supported Formats

GeoTIFF only (`.tif`, `.tiff`). GDAL handles projection, band count, and bit depth differences. Note in the card: "Place GeoTIFF (.tif) files in the import directory."

### TileServer Discovery

TileServer GL auto-discovers new MBTiles files. The frontend's existing 30-second NAIP/Sentinel availability poll will pick up new custom layers automatically.

## Testing

### NOAA pipeline (no network)

1. **Tile index spatial filtering** — mock shapefile data, verify correct tiles selected for a bbox
2. **URL construction** — verify `(state, year)` → correct blob URL from catalog
3. **Estimate calculation** — tile count × avg size → correct estimates
4. **Mocked end-to-end** — mock HTTP returning small GeoTIFF, verify `convert_batch_to_mbtiles()` produces MBTiles

### BYO import (no network)

5. **Directory scanning** — temp dir with `.tif` and non-tif files, verify only `.tif` found
6. **Named vs default output** — name → sanitized filename, blank → `imagery_custom.mbtiles`
7. **Merge behavior** — import into existing MBTiles adds tiles without destroying existing

### Manual smoke tests

8. **NOAA small-area** — Arizona, tiny bbox, verify download + convert
9. **BYO import** — drop small GeoTIFF in import dir, click import, verify in TileServer

## What This Does NOT Change

- Existing `direct` mode — untouched
- Existing `m2m` mode — untouched
- Existing `nationalmap` mode — untouched
- `acquire_naip.py` — USDA Gateway pipeline, untouched
- `acquire_sentinel.py` — untouched
- TileServer config — auto-discovers new MBTiles
