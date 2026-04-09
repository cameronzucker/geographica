# KMZ/KML Import Overhaul — Design Spec

**Date:** 2026-04-08
**Status:** Approved
**Scope:** frontend/app.js KMZ/KML import pipeline — icon display, chunked processing, progressive rendering

## Problem Statement

Three interconnected issues with the current KMZ/KML import:

1. **Icons not displayed on map.** KMZ files from sources like USGS USMIN contain informational icons (mine shafts, adits, prospects, quarries) designed for bird's-eye view identification. The current implementation renders all points as uniform 7px pink circles and buries the actual icons inside click-required popup balloons.

2. **Large files freeze the browser.** KMZ files with 40K+ placemarks (e.g., USMIN Arizona: 45,645 placemarks, 2.3MB compressed → 28MB KML) cause the browser tab to become unresponsive during import. The tab eventually recovers, but the browser attempts to kill it.

3. **Post-load performance is excellent and must be preserved.** Once loaded, MapLibre's WebGL rendering handles large datasets efficiently. This is a core competency advantage over Google Earth.

## Reference Data Analysis

Analyzed USGS USMIN KMZ files (Alaska and Arizona samples):

| Property | Alaska | Arizona |
|----------|--------|---------|
| Archive size | 1.3 MB | 2.3 MB |
| KML size (decompressed) | 7 MB | 28 MB |
| Placemarks | 5,739 | 45,645 |
| Points | 4,467 | 43,741 |
| Polygons | 1,275 | 1,971 |
| Unique icon URLs | 15 | 15 |
| Unique icon images | 15 (all 32x32 RGBA PNG, 138-489 bytes each) |
| Embedded images in archive | 0 (icons are external URLs) |
| Style definitions | 120 (normal + highlight pairs) |
| StyleMap definitions | 60 |
| Folders | 29 (county-based) |

Key findings:
- Small icon vocabulary (15 unique images) shared across thousands of placemarks
- Icons are external URLs (`https://mrdata.usgs.gov/images/*.png`), not embedded in the KMZ archive
- Styles use `<StyleMap>` with normal/highlight pairs — toGeoJSON does not resolve these
- Directional variants exist (adit-n, adit-ne, adit-e, etc. — 8 compass directions)
- Total icon atlas memory: ~60KB (negligible)

## Architecture

### Section 1: Icon Extraction & Display

#### Icon Pipeline at Import Time

After JSZip decompresses the KMZ, before feature processing:

1. Scan the KML DOM for all unique `<Icon><href>` values via the style resolution table (see Section 3)
2. For each unique icon URL:
   a. Check if already registered in MapLibre's image registry → skip if so
   b. Check if the URL is a path within the KMZ archive → extract from archive
   c. If external URL: validate URL (see Section 5), attempt HTTP fetch with 5s timeout
   d. Convert fetched image to `HTMLImageElement`, validate dimensions (max 256x256)
   e. Register with `map.addImage(iconId, image)` using URL-derived key
3. Cache loaded icons in session-scoped `Map<url, iconId>`

#### Icon ID Derivation

Each unique icon URL gets a deterministic ID:
1. Extract filename from URL path (e.g., `https://mrdata.usgs.gov/images/adit-n-32.png` → `adit-n-32.png`)
2. Strip extension, replace non-alphanumeric chars with hyphens: `adit-n-32`
3. Prefix: `kmz-icon-adit-n-32`
4. On collision (two different URLs → same ID), append numeric suffix: `kmz-icon-adit-n-32-2`

#### Fallback Symbol Generation

When an icon can't be loaded (offline, 404, timeout, validation failure):

1. Derive abbreviation from KML style name: split on `_` and `-`, take first letter of each significant word (skip "and", "or", "the", "-"), truncate to 2 chars (e.g., `Mine_Shaft` → `MS`, `Open_Pit_Mine` → `OP`, `Gravel_Borrow_Pit` → `GB`)
2. Derive color: simple hash of full style name → map to one of 8 hues (0°, 45°, 90°, 135°, 180°, 225°, 270°, 315° HSL at 60% saturation, 50% lightness)
3. Render 32x32 canvas: filled circle at hashed color, white 2-letter abbreviation centered, 12px bold sans-serif
4. Register with same `kmz-icon-{id}` key as the real icon would have — transparent to the symbol layer

#### Layer Changes

Replace the `imported-points` circle layer with a `symbol` layer:

```
Layer: imported-points (type: symbol)
  icon-image: ['get', '_iconId']
  icon-size: ['get', '_iconScale']    // from KML <scale>, default 1.0
  icon-allow-overlap: true            // preserve dense bird's-eye view
  icon-ignore-placement: true         // don't push other symbols away
```

Features without icons get `_iconId: 'kmz-icon-default'` — a 32x32 canvas-rendered pink circle matching current appearance.

Line and polygon layers remain unchanged (already working correctly with data-driven colors).

#### Mixed Datasets

Single symbol layer handles both icon and non-icon features via data-driven `icon-image`. Every point feature gets an `_iconId` property — either a real icon ID or the default fallback.

### Section 2: Chunked Processing & Progressive Rendering

#### Async Processing Pipeline

`processKMLDoc()` becomes async, broken into stages with `yieldToMain()` between each:

```
yieldToMain() = new Promise(resolve => setTimeout(resolve, 0))
```

**Stage 1 — DOM Parse** (~100ms even for 28MB):
- `new DOMParser().parseFromString(kmlText, 'text/xml')`
- Single synchronous step (fast enough to not need yielding)

**Stage 2 — Style Resolution Table** (see Section 3):
- Walk `<Style>` and `<StyleMap>` elements
- Build `styleTable` and `styleMapTable` lookups
- Single step with yield after

**Stage 3 — Icon Loading** (async, parallel):
- Collect all unique icon URLs from style table
- `Promise.all()` fetch/generate up to 50 icons with 5s individual timeout, 30s phase timeout
- Register all icons with `map.addImage()`
- Progress: "Loading icons... 12/15"

**Stage 4 — GeoJSON Conversion** (single step + yield):
- Call `toGeoJSON.kml(kmlDoc)` once on the full KML document — this is fast even for large files (~200ms for 45K features) because toGeoJSON is a lightweight DOM walk
- toGeoJSON returns a complete FeatureCollection
- `await yieldToMain()` after conversion
- Note: toGeoJSON must run on the full document, not individual placemarks, because it needs document-level `<Style>` context

**Stage 5 — Feature Processing** (batched, yielding):
- Iterate the GeoJSON features array in batches of 500
- Each batch: resolve styles via `styleTable`/`styleMapTable` (Section 3), assign `_iconId`/`_iconScale`/`_importFileId`/`_importFeatureId`/`_folder`, build folder map
- Append processed features to `runningCollection`
- Call `source.setData(runningCollection)` after each batch (progressive map update)
- `await yieldToMain()` between batches
- Progress: "Processing features... 2,500 / 45,645"

**Stage 6 — Finalization** (single step):
- `fitBounds()` on complete feature set
- Call `buildImportLayerUI()` once with complete data (NOT during batching — the layer tree UI needs the full folder/feature inventory)
- Show completion message

#### Progress UI

Repurpose existing `#import-status` element:

- Show progress bar (CSS `width` percentage) and text status
- Updates after each batch
- Import button/drop zone disabled during processing
- Completion message: "Imported 45,645 features (15 icons loaded)" with green success style
- If icons failed: "Imported 45,645 features (12/15 icons loaded, 3 using fallbacks)" with yellow warning

#### File Size Limits

| Limit | Current | New | Rationale |
|-------|---------|-----|-----------|
| `MAX_FILE_SIZE_WARN` | 10 MB | 25 MB | Progress UI makes large files less concerning |
| `MAX_FILE_SIZE_REJECT` | 50 MB | 100 MB | Chunked processing can handle larger files |

### Section 3: Style Resolution & toGeoJSON Integration

#### Pre-process: Build Style Tables

Before calling toGeoJSON, walk the KML DOM:

```
styleTable = {}      // styleId → { iconUrl, scale }
styleMapTable = {}   // styleMapId → { normal: styleId, highlight: styleId }
```

For each `<Style id="X">`: extract `<IconStyle>` → `<Icon>` → `<href>` and `<scale>`.
For each `<StyleMap id="X">`: extract `<Pair>` → `<key>` + `<styleUrl>`.

This is cheap — 60 StyleMaps + 120 Styles in the USMIN case.

#### Post-process: Resolve Features

After `toGeoJSON.kml()` produces GeoJSON, during Stage 4 batched processing:

1. If feature has `properties.styleUrl` (e.g., `#Adit_nStyleMap`):
   - Strip `#` prefix
   - Look up in `styleMapTable` → get normal style ID
   - Look up normal style in `styleTable` → get `iconUrl` and `scale`
2. Else if feature has `properties.icon` (toGeoJSON resolved it directly):
   - Use `properties.icon` as `iconUrl`, scale defaults to 1.0
3. Write to feature:
   - `_iconUrl` → resolved URL
   - `_iconScale` → KML scale value (default 1.0)
   - `_iconId` → matching registered icon ID, or `'kmz-icon-default'`

#### Why Not Modify toGeoJSON

- Vendored third-party library — modifying creates maintenance fork
- Post-processing is simple and handles the specific gap (StyleMap resolution)
- If future toGeoJSON handles this natively, remove the post-processing step

### Section 4: Performance Preservation & Memory Budget

#### What We Preserve

- Direct feature rendering (no clustering) — this is what makes post-load performance excellent
- MapLibre's internal viewport culling — no custom culling code needed
- GPU-accelerated symbol rendering — symbol layer with `icon-image` is as fast as circle layer
- `icon-allow-overlap: true` skips collision detection (actually faster than default)

#### Memory Budget (Pi 5)

| Component | Arizona (worst case) | Notes |
|-----------|---------------------|-------|
| KML string | 28 MB | Released after DOM parse |
| DOM tree | ~40 MB | Released after toGeoJSON |
| GeoJSON FeatureCollection | ~12 MB | Retained for map source |
| Icon atlas | ~60 KB | 15 × 32×32×4 bytes |
| **Peak during import** | **~80 MB** | DOM + partial GeoJSON |
| **Steady state** | **~12 MB** | GeoJSON only |

Multiple imports stack: 3 large files ≈ 36MB steady state. Acceptable within Pi 5's browser allocation.

#### Cleanup on File Remove

Track icon reference counts:
- `iconRefCounts[iconId]++` on import
- `iconRefCounts[iconId]--` on remove
- `map.removeImage(iconId)` when count reaches 0

Prevents texture atlas bloat from repeated import/remove cycles.

#### What We DON'T Add

- No clustering (kills bird's-eye-view density)
- No viewport culling beyond MapLibre's built-in
- No LOD switching (32px icons appropriate at all zoom levels)
- No Web Workers (avoids DOMParser polyfill complexity)

### Section 5: Security Considerations

The import pipeline now fetches external resources directed by untrusted file content. Defenses:

#### URL Validation

- Only allow `http://` and `https://` schemes
- Block `javascript:`, `data:`, `file:`, `blob:` schemes
- Reject URLs targeting localhost, private IP ranges (10.x, 172.16-31.x, 192.168.x), `.local` domains
- Validation runs before any fetch attempt

#### Image Validation

- Fetched response must have `Content-Type` starting with `image/` (`image/png`, `image/jpeg`, `image/gif`)
- Load via `new Image()` → check `naturalWidth` and `naturalHeight` ≤ 256
- If `Image.decode()` fails or dimensions exceed limit, discard and use fallback symbol
- Never inject fetched content as `innerHTML`, SVG source, or any DOM context

#### KML Content Sanitization

- Popup descriptions: existing `textContent` path for non-HTML is safe — preserve it
- HTML descriptions: existing `innerHTML` usage is a known XSS vector — flag for CSO review
- Consider DOMPurify or a strict tag allowlist for HTML descriptions (out of scope for this spec, but noted)

#### Resource Limits

| Limit | Value | Purpose |
|-------|-------|---------|
| Max unique icon fetches per file | 50 | Prevent request flooding from malicious KMZ |
| Per-icon fetch timeout | 5 seconds | Prevent slow-loris |
| Total icon phase timeout | 30 seconds | Fail gracefully, use fallbacks |
| Max image dimensions | 256 × 256 | Prevent memory bombs |
| Max KMZ archive entries scanned | 100 | Prevent zip bomb enumeration |

#### CSO Review Gate

A formal security review (CSO skill) must run against this spec before implementation planning. Specific focus areas:
- Input validation completeness for URL and image handling
- innerHTML usage in KML description popups (pre-existing issue, now higher risk with icon loading)
- Archive extraction safety (zip slip, symlink attacks in KMZ)
- Cross-origin fetch behavior and CORS implications

## Files Modified

| File | Changes |
|------|---------|
| `frontend/app.js` | Icon pipeline, chunked processing, symbol layer, progress UI, style resolution, security validation |
| `frontend/style.css` | Progress bar styles, updated import status styles |
| `frontend/index.html` | No changes expected (existing drop zone and file input sufficient) |
| `frontend/vendor/togeojson.js` | No changes (post-processing approach avoids forking) |

## Testing Strategy

- Unit tests for style resolution table building (mock KML DOM)
- Unit tests for URL validation (scheme, private IP, localhost rejection)
- Unit tests for fallback symbol generation (deterministic abbreviation + color from style name)
- Integration test: import USMIN Alaska KMZ, verify 15 icons registered, 5,739 features on map
- Performance test: import USMIN Arizona KMZ (45K features), verify no browser freeze (responsive throughout), measure total import time
- Regression test: import a simple KML with no icons, verify pink circle fallback still works
- Security test: KMZ with malicious icon URLs (javascript:, data:, localhost), verify all rejected
