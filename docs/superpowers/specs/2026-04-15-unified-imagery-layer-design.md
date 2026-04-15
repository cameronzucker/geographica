# Unified Imagery Layer Design

**Date:** 2026-04-15
**Scope:** z15-z17 gap fix, imagery catalog endpoint, dynamic hybrid road styling

## Problem

Three related issues with the imagery subsystem:

1. **z15-z17 gap:** USGS basemap covers z0-z14. NOAA NAIP covers z18 only. Zooming from z14 drops to vector-only at z15-z17, then jumps to aerial at z18.
2. **No inventory visibility:** Users can't see what imagery they have, at what zoom levels, for what areas. TileServer metadata is written once at creation time and may not reflect actual tile data (especially after gdaladdo adds overview tiles).
3. **Roads unreadable over imagery:** When overlay imagery (NOAA, NAIP, etc.) is toggled on over positron/darkmatter basemap, roads and labels retain their dark-on-light styling, making them invisible against aerial photos.

## Architecture Decision: Separate Sources (Option C)

Each imagery source remains its own MBTiles file served as its own TileServer layer. Users see per-source toggles and can manage sources independently. Layer stacking order in MapLibre handles overlap (higher-res source renders on top). No composite tile endpoint or merged MBTiles.

Rationale: This is a power-user GIS tool. Source provenance and independent management matter more than a simplified single-toggle experience.

## Component 1: Fix Existing gdaladdo + Add Metadata Fixup

### Existing gdaladdo (bug fix, not new code)

`run_noaa()` already calls `gdaladdo -r average <output> 2 4 8 16` at `acquire_imagery.py:1843`. This generates overview tiles at z17, z16, z15, z14 from the z18 source data. **The overview generation already works.** Two bugs prevent it from being useful:

1. **Not cancellable:** Uses `subprocess.run()` instead of `run_gdal_subprocess()`. A SIGTERM during the 2-hour overview generation leaves the child process running until Docker force-kills the container.
2. **No metadata fixup:** After gdaladdo adds z15-z17 tiles, the MBTiles `metadata` table still says `minzoom=18` (written by `gdal_translate` during the per-tile conversion step). TileServer reads this metadata at startup and reports it as TileJSON. MapLibre trusts TileJSON and never requests tiles at z15-z17, so the gap persists despite the tiles existing.

### Fix 1: Replace subprocess.run with run_gdal_subprocess

Change the existing gdaladdo call at line 1843 from `subprocess.run()` to `run_gdal_subprocess()`, which handles process group management and cancel checking.

### Fix 2: Add metadata fixup after gdaladdo

After gdaladdo completes successfully, update the MBTiles metadata table:

```sql
UPDATE metadata SET value = (SELECT MIN(zoom_level) FROM tiles) WHERE name = 'minzoom';
UPDATE metadata SET value = (SELECT MAX(zoom_level) FROM tiles) WHERE name = 'maxzoom';
```

The `minzoom` row exists because `merge_mbtiles()` copies metadata from the first batch's temp MBTiles (line 589-591, `INSERT OR IGNORE`), and `gdal_translate` writes minzoom/maxzoom when creating the temp file.

### Fix 3: Add cancel guard between gdaladdo and metadata fixup

```python
if _cancel_requested:
    return  # Don't fixup metadata on partial overviews
```

If gdaladdo is killed mid-write, the MBTiles may have partial overview tiles. The metadata fixup should not run in this case — better to leave metadata at z18 (understating coverage) than to report z15 when those tiles are incomplete.

### TileServer Restart

After metadata fixup, TileServer must restart to pick up the new metadata. The pipeline already triggers this via `docker restart geographica-tileserver` at the end of a run.

## Component 2: Imagery Catalog Endpoint

### Endpoint

`GET /admin/imagery/catalog`

Scans `/srv/geographica/data/imagery*.mbtiles` and for each file queries the actual `tiles` table:

```sql
SELECT zoom_level, COUNT(*) as tile_count,
       MIN(tile_column) as min_x, MAX(tile_column) as max_x,
       MIN(tile_row) as min_y, MAX(tile_row) as max_y
FROM tiles GROUP BY zoom_level
```

### Response Format

```json
{
  "sources": [
    {
      "id": "imagery",
      "file": "imagery.mbtiles",
      "size_bytes": 26843545600,
      "modified": "2026-04-15T10:30:00Z",
      "registered": true,
      "zoom_levels": [
        {
          "zoom": 0,
          "tile_count": 1,
          "bounds_lonlat": [-124.8, 31.3, -102.0, 49.0]
        },
        {
          "zoom": 14,
          "tile_count": 89234,
          "bounds_lonlat": [-124.8, 31.3, -102.0, 49.0]
        }
      ]
    },
    {
      "id": "imagery_noaa",
      "file": "imagery_noaa.mbtiles",
      "size_bytes": 1744748544,
      "modified": "2026-04-14T22:27:00Z",
      "registered": true,
      "zoom_levels": [
        {
          "zoom": 15,
          "tile_count": 2800,
          "bounds_lonlat": [-112.0, 31.87, -109.74, 34.0]
        },
        {
          "zoom": 18,
          "tile_count": 153931,
          "bounds_lonlat": [-112.0, 31.87, -109.74, 34.0]
        }
      ]
    }
  ]
}
```

### Bounds Conversion

Tile coordinates (column/row) are in TMS scheme. Convert to lon/lat bounds for the frontend:

```python
import math

def tile_bounds_tms(z, min_x, max_x, min_y, max_y):
    """Convert TMS tile range to lon/lat bounds.

    MBTiles uses TMS y-axis (origin at bottom-left). GDAL's MBTiles driver
    follows this convention for raster tiles. Verify with:
      SELECT tile_row FROM tiles WHERE zoom_level=18 LIMIT 1
    and compare against expected latitude.
    """
    n = 2 ** z
    lon_min = min_x / n * 360 - 180
    lon_max = (max_x + 1) / n * 360 - 180
    # TMS: y=0 is at the bottom (south), max_y is at the top (north)
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * min_y / n))))
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (max_y + 1) / n))))
    return [lon_min, min(lat_min, lat_max), lon_max, max(lat_min, lat_max)]
```

### Performance

The GROUP BY query on the primary key index takes ~1-2 seconds for 154K tiles. For the 25 GB basemap imagery (millions of tiles), it may take longer. Caching strategy:

- Cache catalog in memory on first request
- Invalidate when a pipeline completes (pipeline sends a signal or writes a timestamp file)
- `Cache-Control: max-age=60` header for the frontend

### Registration Check

The `registered` field indicates whether the source is in `tileserver/config.json`. An unregistered source exists on disk but isn't being served. The admin UI can offer a "Register" button that adds it to TileServer config and restarts.

### SQLite Concurrency

The catalog endpoint reads MBTiles files that TileServer is also reading and that pipelines may be writing. Open connections in read-only mode to avoid locking conflicts:

```python
sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
```

If a pipeline is actively writing (merging tiles), the query may encounter `SQLITE_BUSY`. The 5-second timeout handles this gracefully — return partial results or skip the busy file with a note in the response.

### Placement

New route in `services/search/main.py`, under the `/admin/` prefix. Uses `pathlib.glob()` to find MBTiles files and `sqlite3` to query each.

## Component 3: Dynamic Hybrid Paint Overrides

When overlay imagery is visible over positron or darkmatter basemap, apply hybrid-style paint properties to make roads and labels readable against aerial photos.

### Override Table

A static array in `app.js` mapping basemap layer IDs to their hybrid paint values. Derived from `tileserver/styles/hybrid/style.local.json`. Covers roads (line-color), road casings (line-color), labels (text-color, text-halo-color, text-halo-width), and motorways (amber line-color).

**Paint property types:** Verified that `line-color` is always a simple string value in both positron and hybrid. `line-width` is always a zoom-dependent expression (stops array) in both styles. The override table must store full expression objects for `line-width`, not simple numbers. `setPaintProperty()` accepts both formats, so this works as long as the override value matches the expected type.

**Layer ID compatibility:** Positron, darkmatter, and hybrid share the same layer IDs for road and label layers. Two tunnel layers (`tunnel_motorway_casing`, `tunnel_motorway_inner`) exist in positron but not darkmatter or hybrid. Override logic should check `map.getLayer(id)` before calling `setPaintProperty()` to handle missing layers gracefully.

### Toggle Logic

In `_updateOverlayImageryState()`:

**When any overlay imagery becomes visible (`anyVisible` transitions false -> true):**
1. Snapshot current paint values for all layers in the override table via `map.getPaintProperty()`
2. Store snapshot in module-level `_savedBasemapPaint`
3. Apply hybrid paint values via `map.setPaintProperty()`

**When all overlay imagery is hidden (`anyVisible` transitions true -> false):**
1. Restore saved paint values from `_savedBasemapPaint`
2. Clear the snapshot

### Edge Cases

**Style switch while overlay active:** The `style.load` event fires when the user switches basemaps (positron <-> darkmatter). This resets all paint properties. The `style.load` handler must check if overlay imagery is still active and re-apply overrides with a fresh snapshot of the new style's paint values.

**Hybrid mode:** When the user is in full hybrid mode (the "Hybrid" checkbox), the overlay paint overrides are not needed because the hybrid style already has the correct paint properties. Skip overrides when `currentStyle === 'hybrid'`.

### Reversibility

If the visual result is poor, the override table values can be tuned or the entire feature disabled by removing the setPaintProperty calls. The snapshot/restore pattern ensures no permanent state changes to the basemap style.

## Files Modified

| File | Changes |
|------|---------|
| `scripts/acquire_imagery.py` | Fix existing gdaladdo (cancel support) + add metadata fixup in `run_noaa()` |
| `services/search/main.py` | Add `GET /admin/imagery/catalog` endpoint (read-only SQLite, busy handling) |
| `frontend/app.js` | Paint override table (with expressions), snapshot/restore in `_updateOverlayImageryState()`, `style.load` re-apply, catalog-driven source discovery |

## What This Does NOT Change

- Service stack (no new containers)
- TileServer (stays dumb, serves MBTiles)
- NGINX routing (no new location blocks)
- Separate MBTiles per source (option C preserved)
- Existing overlay toggle and opacity slider behavior

## Adversarial Review Findings (5 rounds: Opus, Haiku, Sonnet, Opus, Haiku)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| F1 | gdaladdo already exists at line 1843 — spec proposed duplicate | High | Spec rewritten: fix existing call, don't add new one |
| F2 | Existing gdaladdo uses subprocess.run, not cancellable | High | Spec updated: replace with run_gdal_subprocess |
| F3 | No metadata fixup after gdaladdo — minzoom stays z18 | High | Already in spec, placement corrected |
| F4 | TMS bounds math inverted lat_min/lat_max | Medium | Saved by min/max safety net; added comment |
| F5 | Frontend hard-codes source IDs (hyphen) vs catalog (underscore) | Medium | Spec updated: catalog drives discovery |
| F6 | Paint line-width uses expressions, not simple values | Medium | Spec updated: override table stores full expressions |
| F7 | No cancel guard between gdaladdo and metadata fixup | Medium | Spec updated: explicit cancel check |
| F8 | Catalog should open MBTiles read-only with busy timeout | Medium | Spec updated: ?mode=ro, timeout=5 |
| F9 | Tunnel layers in positron but not darkmatter | Low | Check map.getLayer() before setPaintProperty |
| F10 | gdaladdo memory on 1.7 GB MBTiles | Low | Benchmarked: 0 MB additional, peak set by gdalwarp |

## Future Work (Not In Scope)

- Admin panel inventory map UI (consumes catalog endpoint — separate subsystem)
- Pipeline admin page redesign (separate subsystem)
- NOAA catalog population for other Western US states
- Composite tile endpoint (deferred — layer stacking is sufficient)
