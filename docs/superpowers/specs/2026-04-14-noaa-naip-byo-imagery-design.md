# NOAA NAIP Download + BYO Imagery Import

**Date:** 2026-04-14
**Status:** Approved (revised after 5-round adversarial review: Opus, Sonnet ×2, Haiku ×2)

## Problem

High-resolution NAIP aerial imagery is difficult to acquire programmatically. The USDA Gateway is down (since April 2026). The USGS National Map ImageServer throttles sustained downloads to ~1 tile/sec. EarthExplorer's bulk download UI requires clicking through 9,000+ pages. Users need a practical path to 0.6m aerial imagery.

## Solution

Two complementary features:

1. **NOAA NAIP automated download** — new `noaa` mode in `acquire_imagery.py`. Downloads 4-band GeoTIFFs from NOAA Digital Coast's Azure Blob Storage (no auth, no throttling, public `wget` access), reprojects to Web Mercator, converts to MBTiles.

2. **BYO GeoTIFF import** — users place GeoTIFFs from any source in an import directory, click "Import" in the admin panel. Converts to MBTiles using the same pipeline. **This is the only fully offline imagery path** — for air-gapped deployments with no internet, BYO import is the way to get custom imagery.

## Design Decisions

1. **NOAA as primary NAIP source** — Azure Blob Storage is unthrottled, no auth, NOAA recommends `wget`. ~3.4 MB/s download speed confirmed.
2. **Batch size = 1 for NOAA** — each NAIP GeoTIFF is ~486 MB. The pipeline container has a 2 GB memory limit. GDAL needs working memory for reprojection + MBTiles conversion. Processing one tile at a time is the only safe option. BYO import uses batch size 5 (user files may be smaller).
3. **Explicit reprojection** — NOAA NAIP GeoTIFFs are UTM NAD83. MBTiles requires EPSG:3857 (Web Mercator). Must `gdalwarp -t_srs EPSG:3857` before `gdal_translate -of MBTiles`. This applies to both NOAA and BYO import (user GeoTIFFs may be any projection).
4. **TileServer config.json must be updated** — TileServer GL v5.5.0 does NOT auto-discover MBTiles. The pipeline must programmatically add entries to `tileserver/config.json` and restart TileServer after import completes.
5. **Upfront estimate with disk check AND download time estimate** — show tile count, raw download size, estimated MBTiles size, available disk, AND estimated download time at measured speed.
6. **Static catalog with validation** — `(state, year)` → blob path. HEAD-request the blob URL before proceeding to fail fast if the path has changed.
7. **Delete-after-import defaults to UNCHECKED** — adversarial review found this is dangerous on partial failure. User must opt in to deletion.
8. **Security: path traversal guards on all user inputs** — layer names sanitized to `[a-z0-9_]`, import directory scanning rejects symlinks, all paths validated with `safe_staging_path()`.
9. **Shapefile cache persists in `/data/noaa_cache/`** — survives container restarts, mounted via the existing `/data` volume.
10. **Multi-state bbox support** — if the user's bbox intersects tiles from multiple catalog states, query all intersecting states.

## NOAA Data Source

```
https://coastalimagery.blob.core.windows.net/digitalcoast/{STATE}_NAIP_{YEAR}_{ID}/
```

| Property | Value |
|----------|-------|
| Auth | None — public Azure blob |
| Throttling | None observed (Azure Blob CDN) |
| Format | 4-band GeoTIFF, UTM NAD83, 0.6m resolution |
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

**Catalog validation:** When a state is selected, HEAD-request the blob directory URL. If it returns 404, show a clear error: "NOAA data path may have changed for this state. Contact support." This prevents silent failures if NOAA reorganizes their blob storage.

### Tile-to-Bbox Filtering

Download the tile index shapefile (small, ~1-5 MB) once per state and cache in `/data/noaa_cache/{STATE}_{YEAR}/`. Use `subprocess.run(["ogr2ogr", ...])` for spatial queries (matches existing patterns in `build_public_lands.py`):

```bash
ogr2ogr -f CSV /dev/stdout /data/noaa_cache/AZ_2021/tile_index.shp \
  -spat west south east north -geom=NO
```

Returns filenames of intersecting tiles. Exact spatial match, no filename parsing.

**Cache persistence:** Shapefiles stored in `/data/noaa_cache/`, which is inside the `/data` volume mount. Survives container restarts and system reboots.

**Multi-state support:** If the user's bbox intersects catalog entries for multiple states (e.g., AZ/NV border), query all intersecting state shapefiles and combine the tile lists. The admin panel shows: "N tiles from AZ + M tiles from NV = P total."

### Pipeline Flow

1. **Select state** → validate catalog entry (HEAD request) → fetch + cache tile index shapefile
2. **Draw bbox** → spatial query against shapefile(s) → list of intersecting tiles
3. **Estimate** → count × ~486 MB raw, estimate compressed MBTiles size, check disk, estimate download time
4. **User confirms** → download tiles one at a time (batch_size=1)
5. **Per tile:** download GeoTIFF → `gdalwarp -t_srs EPSG:3857` → `gdal_translate -of MBTiles` → merge into output → delete raw files
6. **Progress** → structured reporting to admin panel (same as M2M)
7. **Output** → `imagery_noaa.mbtiles`
8. **Post-completion** → update `tileserver/config.json` with new MBTiles entry → restart TileServer

**Retry logic:** Use existing `MAX_RETRIES=3` / `RETRY_BACKOFF=2` pattern from `acquire_imagery.py`. For NOAA blob storage, retry on HTTP 429/5xx with exponential backoff.

**Cancel/resume:** Partial `imagery_noaa.mbtiles` is valid and usable — TileServer will serve whatever tiles have been written. Re-running the pipeline resumes from where it left off via the existing checkpoint mechanism (`merge_mbtiles` uses `INSERT OR REPLACE`).

### Admin Panel Integration

- Add "NOAA NAIP (0.6m, free)" to source dropdown
- When selected: zoom controls hidden (fixed resolution), state dropdown shown, bbox used for filtering
- State dropdown populated from `NOAA_NAIP_CATALOG` keys
- Year shown as label next to state name (e.g., "Arizona (2021)")
- Estimate shows: "N tiles intersect bbox, ~X GB download, ~Y GB final. Estimated time: ~Z hours at 3 MB/s. You have W GB free."
- Decision helper text under dropdown: "Not sure which source? Use NOAA NAIP for 0.6m aerial imagery (free, no login). Use USGS Direct for basic satellite basemap."
- **Bbox spanning multiple states:** if bbox intersects multiple catalog states, show: "Your bbox overlaps AZ and NV. Tiles from both states will be downloaded."

## BYO GeoTIFF Import

### User Flow

1. User places `.tif` files in `/srv/geographica/data/import/` (or one level of subdirectories)
2. Opens admin panel → "Import Custom Imagery" card
3. Card shows: files found (with subdirectory breakdown), total size
4. If non-tif files found (`.jp2`, `.sid`, etc.), show: "Found N .jp2 files — only .tif/.tiff supported. Convert with: `gdal_translate -of GTiff input.jp2 output.tif`"
5. Optional: enters a layer name (default merges into `imagery_custom.mbtiles`)
6. Optional: "Delete source files after import" checkbox (**default: unchecked**)
7. Clicks "Import"
8. Pipeline converts GeoTIFFs in batches of 5: `gdalwarp -t_srs EPSG:3857` → `gdal_translate -of MBTiles` → merge
9. Progress shown in admin panel
10. On completion: update `tileserver/config.json` if new MBTiles file was created → restart TileServer
11. Source files deleted only if checkbox was checked AND full import succeeded

### Output Files

- **No name (default):** `imagery_custom.mbtiles` — all imports merge here
- **Named (e.g., "phoenix drone"):** `imagery_phoenix_drone.mbtiles` — sanitized to `[a-z0-9_]` only, max 32 chars
- **Existing target:** new tiles merge in, existing tiles at same z/x/y overwritten
- **Name collision:** if sanitized name matches an existing file, require explicit overwrite confirmation

### Security

- **Layer name sanitization:** strip everything except `[a-z0-9_]`, lowercase, max 32 chars. Reject names containing `/`, `..`, or null bytes before sanitization.
- **Path traversal:** all file paths validated with `safe_staging_path()` from `pipeline_security.py`. Reject symlinks in import directory (`Path.is_symlink()` + `Path.resolve().is_relative_to(import_dir)`).
- **Filename injection:** use `sanitize_scene_id()` pattern for all user-provided names.
- **Disk space:** re-check `check_disk_space()` immediately before starting pipeline container, not just at estimate time.
- **HTTPS enforcement:** all NOAA URLs must use `https://`. Validate with `validate_url_scheme()` from `build_public_lands.py`.

### Admin Panel Card

Placed below existing pipeline cards:

```
┌─ Import Custom Imagery ──────────────────────────────────────┐
│ Import directory: /srv/geographica/data/import/              │
│ Files found: 12 GeoTIFFs (5.8 GB)              [Refresh]    │
│ ⚠ Also found: 3 .jp2 files (not supported — see note below) │
│                                                              │
│ Layer name: [________________________] (optional)             │
│ □ Delete source files after successful import                │
│                                                              │
│ [Import]                                                     │
│ ░░░░░░░░░░░░░░░░░░░░ 0%                                     │
│                                                              │
│ Note: Place GeoTIFF (.tif) files in the import directory.    │
│ Subdirectories (one level) are scanned. To convert JP2:      │
│ gdal_translate -of GTiff input.jp2 output.tif                │
└──────────────────────────────────────────────────────────────┘
```

### Directory Scanning

- Scan `/data/import/` and one level of subdirectories
- Match `.tif` and `.tiff` extensions (case-insensitive)
- Also report non-tif geospatial files found (`.jp2`, `.sid`, `.img`) with conversion guidance
- Reject symlinks — only regular files
- Report count and total size

### TileServer Integration

TileServer GL v5.5.0 does **NOT** auto-discover MBTiles files. It reads `tileserver/config.json` at startup.

**After any pipeline creates a new MBTiles file:**

1. Read existing `tileserver/config.json`
2. Add a new data source entry for the MBTiles file (if not already present)
3. Write updated config atomically
4. Restart TileServer container: `docker compose up -d --force-recreate tileserver`

**For the frontend:** the existing 30-second TileJSON poll in `app.js` (`_tryAddTileJSONSource`) will pick up the new layer once TileServer restarts with the updated config.

**TileServer restart impact:** brief interruption (~2-5 seconds) for active map users. Tile requests during restart return 502 from NGINX, MapLibre retries automatically. Acceptable tradeoff — this only happens at the end of a multi-hour pipeline, not during active use.

## Testing

### NOAA pipeline (no network)

1. **Tile index spatial filtering** — mock shapefile data, verify correct tiles selected for a bbox
2. **URL construction** — verify `(state, year)` → correct blob URL from catalog
3. **Catalog validation** — mock HEAD request returning 404, verify clear error message
4. **Estimate calculation** — tile count × avg size → correct estimates + time estimate
5. **Reprojection** — verify `gdalwarp -t_srs EPSG:3857` is called before `gdal_translate`
6. **Mocked end-to-end** — mock HTTP returning small GeoTIFF, verify reprojection + MBTiles output
7. **Multi-state bbox** — bbox overlapping two catalog states → tiles from both returned
8. **Retry on 5xx** — mock HTTP 502, verify retry with backoff

### BYO import (no network)

9. **Directory scanning** — temp dir with `.tif`, `.jp2`, and other files → only `.tif` found, `.jp2` reported
10. **Subdirectory recursion** — files in one level of subdirs found, deeper levels ignored
11. **Symlink rejection** — symlink in import dir rejected
12. **Named vs default output** — name → sanitized `[a-z0-9_]` filename, blank → `imagery_custom.mbtiles`
13. **Path traversal** — name `../../etc/passwd` → rejected
14. **Merge behavior** — import into existing MBTiles adds tiles without destroying existing
15. **Batch processing** — 10 files processed in batches of 5

### TileServer integration

16. **Config update** — verify `config.json` gets new entry after pipeline completes
17. **Idempotent** — running import twice doesn't create duplicate config entries

### Manual smoke tests

18. **NOAA small-area** — Arizona, tiny bbox, verify download + reproject + convert
19. **BYO import** — drop small GeoTIFF in import dir, click import, verify in TileServer
20. **Named layer** — import with custom name, verify separate MBTiles + TileServer entry

## What This Does NOT Change

- Existing `direct` mode — untouched
- Existing `m2m` mode — untouched
- Existing `nationalmap` mode — untouched
- `acquire_naip.py` — USDA Gateway pipeline, untouched
- `acquire_sentinel.py` — untouched

## Adversarial Review Findings Incorporated

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | TileServer does NOT auto-discover MBTiles | CRITICAL | Added TileServer config.json update + restart section |
| 2 | No UTM→Web Mercator reprojection | CRITICAL | Added explicit `gdalwarp -t_srs EPSG:3857` step |
| 3 | GeoTIFF batch size must be 1 for NOAA | CRITICAL | Hardcoded batch_size=1 for NOAA, 5 for BYO |
| 4 | Delete-after-import default checked = data loss | HIGH | Changed default to unchecked |
| 5 | Bbox spanning two states — silent missing tiles | HIGH | Added multi-state detection + combined query |
| 6 | Shapefile cache location undefined | HIGH | Specified `/data/noaa_cache/`, persistent volume |
| 7 | Path traversal in import + named layers | HIGH | Added security section with specific guards |
| 8 | No download time estimate | MEDIUM | Added time estimate to admin panel display |
| 9 | JP2 files in import dir — silent "0 found" | MEDIUM | Added non-tif file detection with conversion guidance |
| 10 | Azure retry/backoff missing | MEDIUM | Added retry with existing MAX_RETRIES pattern |
| 11 | BYO import has no batch limit | MEDIUM | Added batch processing (batch_size=5) |
| 12 | Catalog validation — fail fast | MEDIUM | Added HEAD-request validation |
| 13 | Subdirectory recursion unspecified | LOW | Recurse one level, documented |
| 14 | Cancel/resume undocumented | LOW | Documented partial MBTiles is usable |
| 15 | OGR approach unspecified | LOW | Specified subprocess, matching existing patterns |
