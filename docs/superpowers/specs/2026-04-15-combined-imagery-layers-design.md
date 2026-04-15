# Combined Imagery Layers Design

**Date:** 2026-04-15
**Scope:** Remove confusing Hybrid checkbox, auto-show USGS basemap when detail imagery is active, complete paint overrides for all 35 hybrid layers, fix layer stacking order, persist opacity value.

**Revised after 5-round adversarial review** — scope narrowed from full toggle redesign to targeted improvements.

## Problem

### A. Discovery/Activation UX

Users currently see a flat list of imagery toggles with no indication of how they relate to each other:
- "Hybrid" checkbox (full style swap)
- Individual source toggles: NAIP, Sentinel, NOAA, Custom

A user who wants continuous aerial coverage from z0 to z18 has to: (1) know which sources cover which zoom levels, (2) toggle each one on individually, (3) understand that "Hybrid" is different from the overlay toggles. This is expert-level knowledge that shouldn't be required.

### B. Visual Continuity

When multiple overlay sources are active at different zoom ranges, transitions between zoom levels can show:
- Opacity flicker as one source's tiles load and another's don't
- Color/tone shifts between sources (USGS tiles have different color grading than NOAA)
- A moment of "no imagery" between zoom levels if tile loading is slow
- Inconsistent layer stacking when sources overlap geographically

## Design

### Two-Tier Toggle Grouping

Replace the current flat toggle list with two groups in the sidebar Layers panel:

**Basemap section** (existing, no change):
- Radio buttons: Positron / Dark Matter / (Hybrid removed — see below)

**Detail Imagery section** (replaces current overlay toggles):
```
DETAIL IMAGERY
  ☐ NOAA NAIP (0.6m, free)       1.7 GB · Phoenix, Tucson, Flagstaff
  ☐ USGS M2M (1m, API key)       304 MB · SE Arizona
  ☐ National Map (0.6m, throttled) —
  ☐ Custom Import                  —
  ── opacity [====|----] 80% ──
```

Each toggle shows:
- Source name + resolution
- Disk usage from catalog (or "—" if not downloaded)
- Coverage summary (from catalog cluster data, abbreviated)

### Removing the Hybrid Checkbox

The current "Hybrid" checkbox does a full style swap to a pre-built hybrid MapLibre style. This is redundant now that we have dynamic paint overrides. The hybrid behavior (imagery base + white roads + dark label halos) is achieved by:
1. Toggling any detail imagery source ON
2. The paint overrides automatically apply (already implemented in `_updateOverlayImageryState`)
3. Conflicting basemap fills hide (already implemented)

The USGS basemap (z0-14) is always present as the `imagery` TileServer source. When detail imagery is enabled, it becomes the base layer and the detail source paints on top at higher zooms. This IS hybrid mode — no style swap needed.

**Migration:** Remove the Hybrid checkbox. The `imagery-layer` (USGS basemap raster) is always added as a map source. When any detail toggle is checked, the basemap raster becomes visible + paint overrides apply. When all detail toggles are unchecked, the basemap raster hides and paint overrides restore. The opacity slider controls all active imagery layers.

### Layer Stacking Order

Detail imagery sources are added to MapLibre in resolution order (lowest resolution first):
1. USGS basemap raster (`imagery-layer`) — z0-14, 0.5m — always bottom
2. Sentinel-2 (`imagery-sentinel-layer`) — 10m — if present
3. National Map (`imagery-naip-layer`) — 0.6m
4. NOAA NAIP (`imagery-noaa-layer`) — 0.6m with z15-18 overviews
5. USGS M2M (`imagery-m2m-layer`) — 1m but higher zoom (z15-19)
6. Custom (`imagery-custom-layer`) — varies — always top (user's own data wins)

Higher-res/higher-zoom sources paint over lower ones where they overlap. All inserted before `_firstSymbolLayer()` (existing pattern) so road/label layers render on top.

### Visual Continuity

**Tile loading gaps:** MapLibre already handles this via `raster-fade-duration`. Set to 300ms on all imagery layers for smooth cross-fade between zoom levels. When zooming from z14 (USGS) to z15 (NOAA overview), the NOAA tiles fade in as they load while the USGS tiles fade out.

**Color consistency:** Different sources have different color grading. This is inherent to the data and not correctable without image processing. Acknowledge this — it's a known characteristic of multi-source imagery, not a bug.

**Opacity unification:** All active detail imagery layers share the same opacity value from the slider. When the user adjusts opacity, all visible overlay layers update simultaneously (already implemented).

### Paint Override Trigger

The `_updateOverlayImageryState()` function already handles this correctly:
- When any detail imagery is visible → hide basemap fills, apply hybrid paint overrides
- When no detail imagery is visible → restore basemap fills, restore original paint values
- The USGS basemap raster layer (`imagery-layer`) visibility is tied to whether any detail source is active

**Change needed:** Currently the USGS basemap raster is toggled by the Hybrid checkbox. After removing Hybrid, it should be auto-shown whenever any detail imagery toggle is checked (to provide z0-14 base coverage under the detail tiles).

### Catalog-Driven Toggle Population

The sidebar toggles are currently hardcoded in `_updateImageryToggles()`. Change to:
1. Fetch catalog data (already available via `_catalogData` from the Pipelines tab's `fetchCatalog()`)
2. For each source in the catalog, show a toggle with disk size and coverage info
3. Sources not in the catalog but in the static registry (Sentinel, National Map if not downloaded) show as "— Not downloaded" with the toggle still functional (tiles will 404 gracefully)

### What This Changes in the Sidebar

**Current Layers panel structure:**
```
Basemap: Positron / Dark Matter
Aerial Imagery: [Hybrid checkbox]
  opacity slider
  NAIP toggle, Sentinel toggle, NOAA toggle, Custom toggle
Hillshade toggle
3D Terrain toggle + slider
Public Lands toggle + slider + legend
Units, Coordinates, GPS Source
```

**New structure:**
```
Basemap: Positron / Dark Matter
Detail Imagery:
  NOAA NAIP (0.6m) — 1.7 GB · Phoenix, Tucson, Flagstaff
  USGS M2M (1m) — 304 MB · SE Arizona
  National Map (0.6m) — Not downloaded
  Custom Import — Not downloaded
  opacity slider
Hillshade toggle
3D Terrain toggle + slider
Public Lands toggle + legend + slider
Units, Coordinates, GPS Source
```

The "Aerial Imagery" section heading becomes "Detail Imagery". The Hybrid checkbox is removed. The opacity slider moves below the toggle list. When any toggle is checked, the USGS basemap raster automatically shows as the base layer.

## Files Modified

| File | Changes |
|------|---------|
| `frontend/app.js` | Remove Hybrid checkbox handler, update `_updateImageryToggles` for two-tier layout, auto-show basemap raster, layer stacking order, raster-fade-duration |
| `frontend/index.html` | Remove Hybrid checkbox HTML, update section heading |

## What This Does NOT Change

- Backend (no API changes)
- Admin panel
- Paint override logic (already correct)
- Opacity slider behavior (already controls all overlays)
- Navigation overlay styling
- TileServer config or NGINX
- Pipeline or catalog endpoints

## Adversarial Review Findings (5 rounds: Opus, Opus, Opus, Sonnet, Sonnet)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| F1 | Paint overrides only cover 13/35 hybrid layers — railways, boundaries, state labels invisible | High | Add all missing layers to _hybridPaintOverrides |
| F2 | No auto-show for USGS basemap raster when detail toggles activate | High | Add imagery-layer visibility to _updateOverlayImageryState |
| F3 | Layer stacking non-deterministic (async TileJSON fetches) | Medium | Use moveLayer() after sources loaded to enforce order |
| F4 | raster-fade-duration doesn't cross-fade between sources | Medium | Removed claim — tile-on-top is correct behavior |
| F5 | Catalog data doesn't exist in app.js | High | Deferred — catalog-driven toggles are follow-up work |
| F6 | Opacity slider value not persisted for late-loading layers | Medium | Store value, apply on layer add |
| F7 | "Not downloaded" toggles need static registry | Medium | Deferred — keep current behavior (only show available sources) |

## Revised Scope (Post-Adversarial)

Five targeted changes, all in frontend/app.js and frontend/index.html:

1. **Remove Hybrid checkbox** — delete the checkbox, its change handler, and the style swap logic
2. **Auto-show USGS basemap raster** — in _updateOverlayImageryState, toggle imagery-layer visibility when any detail source is active
3. **Complete paint overrides** — add the ~20 missing layers (railways, boundaries, state/country labels) to _hybridPaintOverrides
4. **Fix layer stacking** — after TileJSON sources load, use map.moveLayer() to enforce resolution order
5. **Persist opacity** — store slider value in a variable, apply to layers on add

Catalog-driven toggle population and "Not downloaded" indicators are deferred to a follow-up.
