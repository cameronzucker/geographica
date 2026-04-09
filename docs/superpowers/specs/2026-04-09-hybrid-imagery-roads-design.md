# Hybrid Imagery + Roads Map Mode — Design Spec

**Date:** 2026-04-09
**Status:** Approved
**Scope:** New "hybrid" MapLibre style with aerial imagery base + road/label overlay, activated by existing imagery toggle

## Problem Statement

When aerial imagery is toggled on, roads and labels disappear underneath the raster tiles — making the imagery useless for navigation. Google Maps/Earth hybrid mode solves this by rendering road networks, labels, and boundaries on top of satellite imagery with subtle, non-competing styling. We have all the data (imagery MBTiles + vector basemap MBTiles) — we just need a style that composes them correctly.

## Architecture: Pre-Authored Hybrid Style JSON

Create a new `hybrid/style.local.json` MapLibre style served by TileServer GL. The style uses the imagery raster as its base layer, then overlays ~20-25 curated vector layers (roads, labels, boundaries, rail) from the existing OpenMapTiles source, styled with Google Maps-inspired subtle rendering.

**Why a static style file:**
- Follows existing pattern (positron and darkmatter are both style JSONs)
- Clean, self-contained — easy to iterate on colors
- No runtime JS complexity — just `map.setStyle()`
- TileServer GL serves it with preview for debugging
- The standard MapLibre way to do style composition

## Section 1: Style JSON Layer Stack

Derived from the darkmatter style (already has lighter-on-dark aesthetic closer to hybrid). Remove ~80 fill/background layers, keep ~20-25 navigation layers, add imagery raster base.

**Layer stack (bottom to top):**

### 1. Imagery Raster Base
```json
{
  "id": "imagery-base",
  "type": "raster",
  "source": "imagery",
  "paint": { "raster-opacity": 1.0 }
}
```

### 2. Road Casings (dark outline beneath road fills)
Source-layer: `transportation`
Filter by class: motorway, trunk, primary, secondary, tertiary, minor, service
```
line-color: rgba(0,0,0,0.3)
line-width: [road fill width + 2px] (zoom interpolated)
```

### 3. Road Fills (subtle, semi-transparent)
Source-layer: `transportation`

Google Maps-inspired styling by road class:
| Class | Color | Width (z12) | Min Zoom |
|-------|-------|-------------|----------|
| motorway | `rgba(232,166,62,0.8)` (warm yellow-orange) | 2.5px | z5 |
| trunk | `rgba(232,166,62,0.7)` | 2px | z7 |
| primary | `rgba(255,255,255,0.7)` | 1.5px | z8 |
| secondary | `rgba(255,255,255,0.5)` | 1px | z9 |
| tertiary | `rgba(255,255,255,0.4)` | 0.8px | z11 |
| minor/service | `rgba(255,255,255,0.3)` | 0.5px | z13 |

All widths zoom-interpolated (thicker at higher zoom). The key principle: **imagery is the star, roads provide just enough context for navigation.**

### 4. Rail Lines
Source-layer: `transportation`, filter: `class = rail`
```
line-color: rgba(255,255,255,0.4)
line-width: 1px
line-dasharray: [2, 3]
```

### 5. Boundary Lines
Source-layer: `boundary`
```
line-color: rgba(255,255,255,0.3)
line-width: 1px
line-dasharray: [3, 2]
```
State boundaries only — country boundaries are rare in Western US bbox.

### 6. Road Labels
Source-layer: `transportation_name`
```
text-color: #ffffff
text-halo-color: rgba(0,0,0,0.7)
text-halo-width: 1.5
text-size: 10-12 (zoom interpolated)
text-font: ["Open Sans Regular"] (from shared font PBFs)
```

### 7. Place Labels
Source-layer: `place`
```
text-color: #ffffff
text-halo-color: rgba(0,0,0,0.7)
text-halo-width: 2
text-size: zoom + class dependent (city: 16, town: 13, village: 11)
text-font: ["Open Sans Bold"] for cities, Regular for towns
```

### 8. Water Labels
Source-layer: `water_name`
```
text-color: rgba(255,255,255,0.8)
text-halo-color: rgba(0,0,0,0.5)
text-halo-width: 1.5
text-font: ["Open Sans Italic"]
```

**Total: ~20-25 layers** (vs 100+ in positron/darkmatter).

## Section 2: Frontend Integration — Smart Imagery Toggle

### Current behavior
Imagery checkbox adds a raster overlay on top of the basemap. Roads disappear.

### New behavior
Imagery checkbox triggers a full style swap to/from the hybrid style.

**Toggle ON:**
1. Store current style: `previousStyle = currentStyle`
2. Set `currentStyle = 'hybrid'`
3. Call `map.setStyle(STYLES.hybrid)`
4. `addPlaceholderSources()` runs on `style.load` — all overlays replay (route, imports, search pins, public lands, GPS)

**Toggle OFF:**
1. Set `currentStyle = previousStyle`
2. Call `map.setStyle(STYLES[currentStyle])`
3. All overlays replay via `addPlaceholderSources()`

**Opacity slider:** Controls `raster-opacity` on the `imagery-base` layer within the hybrid style via `map.setPaintProperty('imagery-base', 'raster-opacity', val / 100)`.

**Basemap radio buttons while hybrid is active:**
- Selecting Positron or Dark Matter unchecks the imagery toggle and switches to that style
- The imagery checkbox visually reflects the hybrid state

### Code changes in app.js

Add to STYLES object:
```js
var STYLES = {
  positron:   '/tiles/styles/positron/style.json',
  darkmatter: '/tiles/styles/darkmatter/style.json',
  hybrid:     '/tiles/styles/hybrid/style.json'
};
```

Add state variable:
```js
var previousStyle = 'positron'; // style to restore when imagery is toggled off
```

Modify imagery checkbox handler:
```js
imageryCheckbox.addEventListener('change', function () {
  if (this.checked) {
    previousStyle = currentStyle;
    currentStyle = 'hybrid';
    map.setStyle(STYLES.hybrid);
  } else {
    currentStyle = previousStyle;
    map.setStyle(STYLES[currentStyle]);
  }
  map.once('style.load', function () {
    addPlaceholderSources();
    syncLayerVisibility();
  });
  opacityRow.classList.toggle('visible', this.checked);
});
```

Modify basemap radio handler — if hybrid active, deactivate:
```js
radio.addEventListener('change', function () {
  var imageryCheckbox = document.getElementById('toggle-imagery');
  if (imageryCheckbox && imageryCheckbox.checked) {
    imageryCheckbox.checked = false;
    // opacity row and state cleanup
  }
  previousStyle = this.value;
  currentStyle = this.value;
  map.setStyle(STYLES[currentStyle]);
  map.once('style.load', function () {
    addPlaceholderSources();
    syncLayerVisibility();
  });
});
```

Modify opacity slider — target the hybrid style's imagery-base layer:
```js
opacitySlider.addEventListener('input', function () {
  var val = parseInt(this.value, 10);
  if (currentStyle === 'hybrid' && map.getLayer('imagery-base')) {
    map.setPaintProperty('imagery-base', 'raster-opacity', val / 100);
  } else if (map.getLayer('imagery-layer')) {
    map.setPaintProperty('imagery-layer', 'raster-opacity', val / 100);
  }
});
```

### Critical: addPlaceholderSources hybrid-awareness (adversarial review findings)

**Do NOT remove the imagery-layer code entirely.** It's still needed for non-hybrid modes (user may want imagery overlay without road labels in future). Instead, guard it:

```js
// In addPlaceholderSources: only create imagery-layer when NOT in hybrid mode
// (hybrid style already has its own imagery-base layer)
if (currentStyle !== 'hybrid' && !map.getLayer('imagery-layer')) {
  map.addLayer({ id: 'imagery-layer', type: 'raster', source: 'imagery', ... });
}
```

**syncLayerVisibility must handle both modes:**
```js
// In syncLayerVisibility:
if (currentStyle === 'hybrid') {
  // Imagery is baked into style — don't try to toggle imagery-layer
  // (it doesn't exist in hybrid mode)
} else {
  setLayerVisibility('imagery-layer', imageryChecked);
}
```

**Public lands z-ordering in hybrid mode:** The hybrid style has its own road layers. When `addPlaceholderSources` adds public lands with `before: 'route-line'`, this works because `route-line` is created first in the function. However, public lands should render BELOW the hybrid style's road layers too. The implementation must insert public lands before the hybrid style's first road casing layer (e.g., `before: 'road-motorway-casing'` or whatever the first road layer is named in the hybrid style). Use a defensive check:

```js
var publicLandsAnchor = map.getLayer('route-line') ? 'route-line' : undefined;
// In hybrid mode, insert below roads from the style
if (currentStyle === 'hybrid') {
  // Find the first road layer in the hybrid style to insert before
  var hybridLayers = map.getStyle().layers;
  for (var i = 0; i < hybridLayers.length; i++) {
    if (hybridLayers[i]['source-layer'] === 'transportation') {
      publicLandsAnchor = hybridLayers[i].id;
      break;
    }
  }
}
```

**Opacity slider initial sync:** When switching to hybrid, set the slider value to match `imagery-base`'s initial opacity (100%). When switching back, restore to match `imagery-layer`'s value.

**Use persistent style.load handler:** Replace scattered `map.once('style.load')` calls with a single `map.on('style.load')` handler that always runs `addPlaceholderSources()` + `syncLayerVisibility()`. This prevents race conditions from rapid toggle/basemap clicks.

### What stays the same
- `addPlaceholderSources()` and `syncLayerVisibility()` — already handle style swaps (with the hybrid-awareness fixes above)
- All overlays (public lands, KMZ imports, routes, GPS) — already survive style swaps
- Hillshade and terrain toggles — work independently (elevation sources are NOT entangled with imagery code)

## Section 3: TileServer Configuration

### New style entry in tileserver/config.json

```json
"hybrid": {
  "style": "hybrid/style.local.json",
  "tilejson": {
    "bounds": [-124.8, 31.3, -102.0, 49.0]
  }
}
```

### New directory: tileserver/styles/hybrid/

- `style.local.json` — the hybrid style (~500 lines)
- Sprite files: symlink or copy from positron (same road shield icons)

### Style JSON source references

```json
"sources": {
  "openmaptiles": {
    "type": "vector",
    "url": "mbtiles://{southwest5}"
  },
  "imagery": {
    "type": "raster",
    "url": "mbtiles://{imagery}"
  }
}
```

**Critical (adversarial review finding):** TileServer GL resolves `mbtiles://{name}` against its `config.json` data section for both vector AND raster sources. Do NOT use `local://`, `tiles:[]`, or `tileSize` — TileServer reads tileSize/maxzoom from MBTiles metadata automatically. The `{imagery}` name matches the data entry in config.json.

### Sprites and glyphs

Same as positron/darkmatter:
```json
"sprite": "{styleJsonFolder}/sprite",
"glyphs": "{fontstack}/{range}.pbf"
```

## Section 4: Style Authoring Strategy

1. Copy `darkmatter/style.local.json` as starting point
2. Remove all layers except: transportation (roads), transportation_name (road labels), place (labels), boundary, water_name (~80 layers removed, ~20 kept)
3. Add rail filter to transportation layers (filter: `class = rail`)
4. Insert imagery raster as first layer
5. Restyle kept layers for satellite readability:
   - Road colors → semi-transparent white/warm per class table above
   - Add road casings (dark semi-transparent outlines)
   - All text → white with dark halo
   - Reduce line widths
6. Update sources section to include both `openmaptiles` and `imagery`
7. Test with Playwright visual verification

## Section 5: Visual Verification

After style is authored:

1. Toggle imagery ON, fly to Hoover Dam area, z9 screenshot — road network visible?
2. z12 screenshot — labels readable? road hierarchy clear?
3. z14 screenshot — minor roads, street names legible?
4. Terrain ON — roads render cleanly over 3D?
5. Public lands ON — layers correctly (public lands below roads, above imagery)?
6. Switch to positron with imagery OFF — clean transition back?

**Layer stack in hybrid mode (bottom to top):**
imagery → public lands fill → public lands outline → route → imports → search pins → GPS

## Files Modified

| File | Changes |
|------|---------|
| `tileserver/styles/hybrid/style.local.json` | **NEW** — hybrid style (~500 lines) |
| `tileserver/config.json` | Add `hybrid` style entry |
| `frontend/app.js` | Smart imagery toggle (setStyle swap), STYLES object, opacity slider, hybrid-aware guards in addPlaceholderSources + syncLayerVisibility, persistent style.load handler, public lands z-order anchor |

## Testing Strategy

- Toggle test: imagery ON → hybrid style loads, roads visible over imagery. OFF → previous basemap restores.
- Opacity test: slider controls imagery transparency in hybrid mode
- Basemap switch test: select positron while hybrid active → hybrid deactivates, imagery unchecked
- Style swap survival: all overlays (public lands, imports, route, GPS) persist through toggle
- Visual test: Playwright screenshots at z9, z12, z14 comparing to Google Maps hybrid for road visibility and label readability
- Performance test: hybrid + terrain + public lands simultaneously on Pi 5
- Offline test: hybrid mode works with no internet (all tiles local)
