# National Map NAIP Imagery Source

**Date:** 2026-04-14
**Status:** Approved

## Problem

The USDA Geospatial Data Gateway (`datagateway.nrcs.usda.gov`) has been officially unavailable since April 3, 2026. The existing NAIP pipeline (`acquire_naip.py`) depends entirely on this gateway for county-level JP2 mosaics. The existing tile scraper (`direct` mode) maxes out at ~z15 from `USGSImageryOnly/MapServer`. Users need 0.6m NAIP aerial imagery at z15-z18 with no external dependencies.

## Solution

Add a `nationalmap` mode to `acquire_imagery.py` that fetches NAIP 0.6m aerial imagery as 256x256 JPEG tiles from the USGS National Map ImageServer, writing them directly into MBTiles. Same architecture as the existing `direct` mode — different URL template, same tile-grid loop, checkpoint resume, and MBTiles output.

## Design Decisions

1. **JPEG-direct to MBTiles** — no GeoTIFF intermediate. The ImageServer renders 256x256 JPEGs on demand. MBTiles stores JPEG blobs. No GDAL conversion needed, 4x less bandwidth than GeoTIFF, zero compute overhead.
2. **Add mode to existing script** — `nationalmap` joins `direct` and `m2m` in `acquire_imagery.py`. The tile-grid logic, checkpoint system, progress reporting, and cancellation are reused via a parameterized URL builder.
3. **Keep USDA Gateway pipeline** — `acquire_naip.py` stays untouched for when the gateway returns. The National Map mode is an alternative, not a replacement.
4. **Separate output file** — `imagery_naip.mbtiles` to avoid conflicts with `imagery.mbtiles` (direct scraper). TileServer already discovers and serves optional `imagery_naip` as an overlay layer.

## Data Source

```
https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer/exportImage
  ?bbox={west},{south},{east},{north}
  &bboxSR=4326
  &size=256,256
  &imageSR=4326
  &format=jpgpng
  &f=image
```

- Free, no authentication
- No rate limiting observed at 10 concurrent requests
- ~0.8s per tile sequential, parallelizable
- 0.3m native resolution (effective through z18-z19)
- Returns 256x256 JPEG (~15 KB/tile)
- Coverage: CONUS, most recent NAIP year per state

**Validated:** 10 concurrent 200 OK responses in <1s, 256x256 JPEG output confirmed, Phoenix area imagery verified.

## Zoom Range

| Zoom | Pixel size | NAIP quality | Notes |
|------|-----------|-------------|-------|
| 0-14 | >10m | Excellent | Overlaps with `direct` mode — skip or warn |
| 15-16 | 5-10m | Excellent | Sweet spot — fills gap above direct mode's z15 ceiling |
| 17-18 | 1-2m | Good | Full NAIP detail, large tile counts |
| 19+ | <0.5m | Upscaled | Diminishing returns — warn user |

**Default zoom for `nationalmap` mode:** `15-18`

**Tile count estimates for Western US (`-124.8,31.3,-102.0,49.0`):**

| Range | Tiles | ~Size at 15 KB/tile |
|-------|-------|-------------------|
| z15 only | ~450K | ~6.5 GB |
| z15-16 | ~2.2M | ~33 GB |
| z15-18 | ~37M | ~555 GB |

z15-16 for the full Western US is practical on the Pi's SSD. z17-18 should be constrained to a smaller bbox (single state or metro area).

## Changes to `acquire_imagery.py`

### URL builder function

```python
NATIONALMAP_EXPORT_URL = (
    "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/"
    "ImageServer/exportImage"
)

def nationalmap_tile_url(z: int, x: int, y: int) -> str:
    """Convert z/x/y to an ImageServer exportImage URL for that tile's bbox."""
    n = 2 ** z
    west = x / n * 360 - 180
    east = (x + 1) / n * 360 - 180
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return (
        f"{NATIONALMAP_EXPORT_URL}?bbox={west},{south},{east},{north}"
        f"&bboxSR=4326&size=256,256&imageSR=4326&format=jpgpng&f=image"
    )
```

### Parameterize `run_direct()`

The existing `_fetch_tile()` inner function hardcodes `USGS_TILE_URL.format(z=z, x=x, y=y)`. Refactor to accept a `url_fn` parameter:

```python
async def run_direct(args, url_fn=None):
    if url_fn is None:
        url_fn = lambda z, x, y: USGS_TILE_URL.format(z=z, x=x, y=y)
    # ... rest unchanged, _fetch_tile uses url_fn(z, x, y) ...
```

National Map mode calls: `run_direct(args, url_fn=nationalmap_tile_url)`

### Mode routing

```python
parser.add_argument("--mode", choices=["tnmaccess", "direct", "m2m", "nationalmap"], ...)

# In main:
if args.mode == "nationalmap":
    if not args.zoom:
        args.zoom = "15-18"  # default for National Map
    asyncio.run(run_direct(args, url_fn=nationalmap_tile_url))
```

### Output file

National Map mode writes to the path specified by `--output`. The orchestrator in `main.py` will pass `--output /data/imagery_naip.mbtiles`.

### Concurrency

Default concurrency for `nationalmap`: 20 (vs 100 for `direct`). The ImageServer renders on demand rather than serving pre-cached tiles, so lower concurrency is respectful. User can override via `--concurrency`.

## Changes to `services/search/main.py`

### Pipeline start validation

Add `nationalmap` to mode validation:

```python
if body.type == "imagery" and body.mode not in ("direct", "m2m", "nationalmap"):
    raise HTTPException(...)
```

### Container command

```python
if body.mode == "nationalmap":
    command = [
        "python3", "/scripts/acquire_imagery.py",
        "--mode", "nationalmap",
        f"--bbox={body.bbox}",
        f"--zoom={body.zoom}",
        f"--output=/data/imagery_naip.mbtiles",
        f"--concurrency={body.concurrency or 20}",
    ]
```

### MBTiles path

Hardcode the output path in the container command builder (see above). Don't change `_mbtiles_path_for_type()` — that function maps pipeline *types* to output files, and `nationalmap` is a *mode* within the `imagery` type. The command builder already specifies `--output=/data/imagery_naip.mbtiles` explicitly.

## Changes to Admin Panel UI

### Source dropdown

Add third option to `#cfg-source`:

```html
<option value="nationalmap">National Map NAIP (0.6m, no auth)</option>
```

### Contextual help text

When `nationalmap` is selected:
- Zoom dropdown defaults to `15-18`, enabled (user can override)
- Zoom note: "National Map NAIP is most useful at z15-z18. Below z15, use USGS Direct. Above z18, imagery is upscaled."
- Estimate shows tile count + GB (reuse existing `estimateTiles()`)
- Concurrency field hidden or defaults to 20
- M2M credentials warning hidden
- Source label in progress display: `"National Map NAIP"`

### NAIP card note

Add a note to the NAIP collapsible card body:

> "USDA Gateway is currently unavailable (since April 2026). For NAIP imagery, use **National Map NAIP** in the Imagery section above."

### SOURCE_LABELS

```javascript
var SOURCE_LABELS = {
    sentinel: 'Sentinel-2',
    naip: 'NAIP',
    direct: 'USGS Direct',
    m2m: 'USGS M2M',
    nationalmap: 'National Map NAIP',
    elevation: 'Elevation'
};
```

## Testing

### Unit tests (no network)

1. **`nationalmap_tile_url()` math** — verify z/x/y → bbox → URL for known tile coordinates. Test z=0 (whole world), z=15 (typical), z=18 (max useful). Verify bbox values match standard web mercator tile grid.
2. **Mode routing** — verify `--mode nationalmap` sets default zoom to `15-18` and calls `run_direct` with the correct URL builder.
3. **Zoom default** — verify National Map mode defaults to `15-18` when no `--zoom` specified, but respects explicit `--zoom` override.

### Integration test (mocked HTTP)

4. **End-to-end with mocked responses** — mock `aiohttp` to return a 256x256 JPEG blob for any URL matching the ImageServer pattern. Run a 2x2 tile bbox. Verify: tiles land in MBTiles at correct TMS-flipped coordinates, checkpoint is written, metadata has correct bounds/zoom, progress callback fires.

### Manual smoke test (live)

5. **Tiny bbox, z15 only** — `--bbox "-112.1,33.4,-112.0,33.5" --zoom 15-15 --mode nationalmap` (~10-20 tiles). Verify output MBTiles opens in TileServer and shows NAIP aerial imagery.

## What This Does NOT Change

- `acquire_naip.py` — USDA Gateway county mosaic pipeline, untouched
- `direct` mode — existing tile scraper, untouched
- `m2m` mode — existing M2M pipeline, untouched
- `acquire_sentinel.py` — Sentinel-2 pipeline, untouched
- TileServer config — already auto-discovers `imagery_naip.mbtiles`
- Frontend main app — NAIP/Sentinel toggle already exists
