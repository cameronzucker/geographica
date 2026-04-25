# Ruler / measurement tool — design (v2)

**Status:** v2 (post-R1–R4 adversarial review). v1 had 10 CRITICAL findings across 4 reviewers — three were load-bearing (wrong elevation decode formula, wrong z-level resolution claim, broken `useImperial` extraction). v2 corrects all CRITICAL and MAJOR findings inline, keeps the overall design shape (vertex-centric edit model, sidebar tab, ephemeral persistence). v1 git history preserved at commit `a0afd36`.

**Author:** Agent `cholla`, 2026-04-24

**Adversarial review history:**
- R1 (architectural / API soundness, Sonnet): [dev/adversarial/2026-04-24-ruler-r1-architectural.md](../../../dev/adversarial/2026-04-24-ruler-r1-architectural.md) — 3 CRITICAL, 6 MAJOR, 4 MINOR
- R2 (scale / performance, Sonnet): [dev/adversarial/2026-04-24-ruler-r2-scale-performance.md](../../../dev/adversarial/2026-04-24-ruler-r2-scale-performance.md) — 2 CRITICAL, 6 MAJOR, 3 MINOR
- R3 (UX / mobile / a11y, Sonnet): [dev/adversarial/2026-04-24-ruler-r3-ux-mobile-a11y.md](../../../dev/adversarial/2026-04-24-ruler-r3-ux-mobile-a11y.md) — 3 CRITICAL, 8 MAJOR, 5 MINOR
- R4 (robustness / failure modes, Sonnet): [dev/adversarial/2026-04-24-ruler-r4-robustness.md](../../../dev/adversarial/2026-04-24-ruler-r4-robustness.md) — 2 CRITICAL, 8 MAJOR, 6 MINOR
- R5 (Codex cross-validation, gpt-5.4): *pending* — runs against this v2 to catch what the Sonnet rounds missed.

**Visual reference:** mockup at `.superpowers/brainstorm/1827880-1777091427/content/measure-tab-mockup.html` (gitignored). Three states rendered: drawing, editing, inserting.

## Problem

Geographica has no on-map measurement tool. Users who need to know a distance ("how far from here to that summit?", "what's the elevation gain on this traverse?", "what bearing should I point the antenna?") today have to reach for an external tool — Google Earth, CalTopo, a printed sectional, or the back of an envelope. This is a basic-tier GIS competency that every comparable product (Google Earth, CalTopo, Avenza, MapBox Studio, ArcGIS) ships, and AREDN amateur-radio operators specifically use measurement tools as part of routine path-planning, antenna-aiming, and field-navigation workflows.

The lack of a ruler is felt sharply enough that the missing capability has been on the backlog under "things Google Earth does that we don't yet."

## Goals

- Click-to-place vertices on the map; multi-segment paths supported.
- Per-segment and cumulative geodesic distance, formatted in the user's existing imperial/metric preference (read live from `window._geographicaUseImperial`).
- Per-segment **true** bearing in decimal degrees.
- Inline elevation profile (sparkline + min / max / gain / loss) sampled from the existing **Mapzen Terrarium** elevation tiles.
- Vertex-centric edit model after placement: select a vertex → drag to reposition, delete, or insert before/after.
- Touch + mouse parity. Field-readable in sunlight (high-contrast palette via shadow halo + white stroke, not via foreground color contrast).
- WCAG 2.5.5-compliant hit-targets (≥44 px tap area) via invisible expanded hit layer.
- Self-contained `frontend/ruler.js` module — minimal, well-bounded touch to existing `app.js`, `index.html`, and `style.css`.

## Non-goals

- **Persistence / "save measurement".** v1 is purely ephemeral — measurements clear on tab switch, page reload, or "Clear" button. The data shape is kept KMZ-serializable so the future *My Places* cycle (a separate spec) can add save/load/export without refactoring ruler internals.
- **Polygon area** / closed-figure area measurement. Sibling future feature in the same "measurement tools" family.
- **Magnetic bearing** with declination correction. True bearing only.
- **Click-on-segment-line to insert vertex.** Rejected during brainstorming as unintuitive.
- **Hover/tap interactivity on the sparkline itself.** Static; vertex-list-row click is the inspect-a-point path.
- **Antimeridian crossing.** CONUS-only data coverage means no real users hit it. Documented edge-case behavior; not a v1 concern.
- **Concurrent multiple measurements.** One at a time in v1.
- **Reload-state restoration via sessionStorage.** Open Question deferred to a v1.1 follow-up if the post-ship UX surfaces a real need.
- **A WCAG 1.4.11 high-contrast theme toggle.** Out of scope; current colors rely on the shadow-halo + white-stroke architecture for visibility, not foreground-vs-basemap contrast (see §D.4).

## Architecture

### A. Module layout & data shape

**New module:** `frontend/ruler.js` — IIFE pattern (matches `voice-picker.js`, `import-store.js`). Exposes a single `window._ruler` API:

```js
window._ruler = {
  init: function (map) { ... },        // idempotent — second call is a no-op
  isActive: function () { ... },       // true when status ∈ {drawing, inserting}
  clear: function () { ... },          // force-reset; aborts in-flight; resets to idle
  // No teardown(): clear() is the canonical reset path. No external ref to private state.
};
```

**Idempotency contract:** `init(map)` checks an internal `initialized` flag. Second call is a no-op. After `clear()`, the module is still alive — sources/layers removed, listeners cleaned up, but the next state mutation (e.g., user starts a new measurement) is permitted. There is no separate "destroyed" state; the IIFE module lives for the page lifetime.

**Imperial/metric handling — live, not snapshot.** Per R1+R4 finding: spec v1's `_appAPI` extraction was wrong because `useImperial` is a `var` in app.js's IIFE closure, reassigned on toggle (app.js:1089). The codebase already exposes a live mirror at `window._geographicaUseImperial` (set at app.js:123 and kept in sync at 1090, added by commit `7bad09c`). **ruler.js reads `window._geographicaUseImperial` at format time** (each call to render the panel), not at init time. Unit-toggle updates propagate on the next render tick.

**Distance formatting — local, not extracted.** `formatRouteDistance` is in app.js but `formatNavDistance` is in nav-ui.js (R1 verified at nav-ui.js:800). A cross-module extraction is more trouble than it's worth. ruler.js implements its own ~12-line distance formatter that respects `window._geographicaUseImperial`:

```js
function formatRulerDistance(meters) {
  var imperial = window._geographicaUseImperial;
  if (imperial) {
    if (meters < 1609.34) return Math.round(meters * 3.28084) + ' ft';
    return (meters / 1609.34).toFixed(2) + ' mi';
  } else {
    if (meters < 1000) return Math.round(meters) + ' m';
    return (meters / 1000).toFixed(2) + ' km';
  }
}
```

This duplication is ~12 lines vs. the architectural cost of a cross-module API surface. Acceptable.

**Coordinate formatting — reuse `formatDD` from app.js as-is.** Per R4 finding: spec v1 said `33.4500°N`; actual `formatDD` output is `33.45000° N` (5 decimals, space before hemisphere letter). v2 uses whatever `formatDD` actually emits. ruler.js does NOT reimplement; it calls the existing function. To make this work without a cross-module API, app.js attaches `window._formatDD = formatDD;` at the end of its IIFE (one new line). Cleaner than the v1 `_appAPI` extraction.

**Haversine formatting — reuse `haversineDistance` from app.js.** Same pattern: `window._haversineDistance = haversineDistance;` exported at the end of app.js's IIFE.

**Minimal touch to existing files:**

- `frontend/index.html` — add 5th tab button: `<button class="tab-btn" data-panel="measure-panel">Measure</button>`. Add `<div id="measure-panel" class="panel">…</div>` (per existing convention — class is `panel`, NOT `sidebar-panel hidden`; visibility toggled via `.active` class per R1 finding). Add `<script src="ruler.js"></script>`. ~32 added lines.
- `frontend/app.js` — five inserts:
  1. **Mode-flag suppression** at the existing reverse-geocode click handler at L1622 (~3 lines): early-return when `window._ruler && window._ruler.isActive()`.
  2. **Mode-flag suppression** at the layer-specific click handler at L660 (imported-points / imported-lines / imported-polygons) (~3 lines). Per R4 finding: the v1 spec missed this handler; KMZ-pin click during ruler `drawing` mode would double-fire without the bail.
  3. **Mode-flag suppression** at the search-result-circles click handler at L1272 (~3 lines). Same reason.
  4. **`window._formatDD` and `window._haversineDistance` exports** at end of app.js's IIFE (~3 lines).
  5. **`initRuler(map)` call** in the bootstrap sequence — explicitly placed AFTER `initSidebarTabs()` and BEFORE `restoreLastSidebarTab()` (per R1+R4: `restoreLastSidebarTab` at app.js:4105 reads `localStorage.getItem('sidebar-last-tab')` and activates it; ruler must be init-ed before that fires so a Measure-tab restore doesn't bind events to a non-init-ed module).
- `frontend/app.js` — one **edit** (not insert): `VALID_SIDEBAR_PANELS` array at L4103 — append `'measure-panel'`. Per R4 finding: the whitelist silently rejects unknown panels, so without this edit, restore-Measure-tab would fail silently.
- `frontend/style.css` — additions for ruler classes (~80 lines).

**Canonical state object (KMZ-serializable, no DOM/MapLibre refs):**

```js
state = {
  status: 'idle' | 'drawing' | 'editing' | 'inserting',
  selectedVertex: null | int,
  insertSlot: null | { before: int },     // populated only when status === 'inserting'
  vertices: [
    { lng: -112.0700, lat: 33.4500, label: 'V1' },
    // ...
  ],
  // Cached/computed; recomputed on any vertex mutation:
  segments: [{ distance_m, bearing_deg, from, to }],
  totalDistance_m: number,
  elevationProfile: null | {
    samples: [{ distance_m, elevation_m }],   // elevation_m can be null per sample
    minM, maxM, gainM, lossM,
    coverageGaps: [{ from: number, to: number }],   // fractions of total in [0, 1]
    samplingState: 'idle' | 'sampling' | 'done' | 'failed' | 'partial',
    samplingProgress: { tilesFetched: int, tilesTotal: int },
  },
};
```

**Shape invariants:**
- `selectedVertex !== null` ⇒ `status === 'editing'`
- `insertSlot !== null` ⇒ `status === 'inserting'`
- `vertices.length < 2` ⇒ `segments.length === 0` AND `totalDistance_m === 0`
- `elevationProfile === null` during `drawing` (sampling triggers post-Finish)
- `elevationProfile.samplingState === 'sampling'` ⇒ `elevationProfile.samples` may be partial; do not assume final until `samplingState ∈ {done, failed, partial}`

A separate (NOT serialized) view-state object holds map-marker handles, listener-cleanup callbacks, AbortController, generation counter, in-memory tile-pixel LRU cache, and DOM nodes — purely view-layer cruft kept out of the data shape.

### B. State machine

Four explicit states. No timeouts, no implicit transitions.

| From | To | Trigger |
|---|---|---|
| `idle` | `drawing` | First map tap (Measure tab visible AND no measurement in editing) |
| `drawing` | `drawing` | Map tap appends vertex; Backspace pops last (debounced); modifier keys (Ctrl/Shift) suppress placement |
| `drawing` | `editing` | Finish gesture: double-click empty map, Enter key, or `[Finish]` button (only enabled with ≥2 vertices) |
| `drawing` | `idle` | Esc, `[Clear]`, or sidebar tab switched away with <2 vertices |
| `editing` | `editing` | Tap vertex (selects); drag vertex (reposition on `mouseup`); tap empty map → falls through to existing reverse-geocode handler |
| `editing` | `inserting` | `[Insert Before]` or `[Insert After]` clicked on a selected vertex |
| `editing` | `idle` | `[Clear]` or `[+ New measurement]` |
| `inserting` | `editing` | Map tap commits insert at projected segment-point (new vertex selected); OR Esc / banner `[×]` / re-click same Insert button cancels |
| `inserting` | `idle` | `[Clear]` |
| any | `idle` | Sidebar tab switched away with <2 vertices; or page reload |
| `editing` (preserved) | `editing` (resumed) | Sidebar tab switched away with ≥2 vertices THEN switched back: state preserved (data + selection); banners suppressed; resumes in-place |

**Sidebar tab restoration behavior** (R1 finding): `restoreLastSidebarTab()` at [app.js:4105](frontend/app.js#L4105) activates the tab from `localStorage`. If the user's last tab was Measure and they reload, the ruler module is `idle` (page reload clears in-memory state per ephemeral non-goal). The Measure panel renders the empty-state placeholder. This is intentional — no "your last measurement was lost" message, since saving is an explicit My Places follow-up.

**`isActive()` returns `true` for `drawing` and `inserting`, `false` for `idle` and `editing`**. The mode-flag bail at three click handlers (L1622, L660, L1272) suppresses competing handlers during the two states where empty-map / pin clicks have ruler-specific meaning.

### C. Sidebar UI structure

The Measure panel renders into `#measure-panel` (the new 5th tab — added after Admin, using `class="panel"` per existing convention). Six sections, top to bottom, conditionally visible per state:

1. **Mode banner** (visible during `drawing` / `inserting`). Inline within the panel; the floating map-overlay banner is handled in §D.4.
2. **Headline stats:** Total distance in current units, large readout. Hidden when `vertices.length < 2`.
3. **Vertex list** (scrollable, ≥44 px row height for touch, focusable rows for keyboard nav). Each row: `Vn`, lat/lng (via `formatDD` — `33.45000° N, 112.07000° W`), and below it the segment-out-of-this-vertex distance + bearing. Selected vertex gets a 3px orange left border + accent background. Last vertex shows no segment-out line. ARIA: `role="list"` on container, `role="listitem"` per row, `aria-selected="true"` on selected.
4. **Selected-vertex action row** — `[↑ Insert Before] [↓ Insert After] [✗ Delete]`. Visible only when `selectedVertex !== null`. When a vertex IS NOT selected: empty-state copy reads "Tap a vertex on the map or in the list above to edit." (per R3 discoverability finding — no hidden affordance).
5. **Elevation profile** — visible when `vertices.length ≥ 2` AND `samplingState !== 'idle'`. During `samplingState === 'sampling'`, render skeleton sparkline + "Loading elevation… X / Y tiles" counter (per R2 — no perceived freeze). Post-sampling: 250×80 px SVG sparkline with vertex tick marks; selected-vertex draws orange dashed vertical guide line. Below: 2×2 grid of min / max / gain / loss with gain in success-green and loss in danger-pink. Coverage warning badge if gaps > 0%. ARIA: SVG has `role="img"` with `aria-label="Elevation profile, min X feet, max Y feet, gain Z feet, loss W feet"`; the 2×2 stats grid is screen-reader-readable text (no ARIA needed).
6. **Footer controls** — `drawing`: `[↶ Undo] [Clear] [Finish]`; `editing`: `[Clear] [+ New measurement]`; `inserting`: footer hidden.

#### C.6 Keyboard navigation

| Key | Behavior |
|---|---|
| Tab / Shift-Tab | Cycles focus through interactive elements: tab buttons → vertex rows → action buttons → sparkline (focusable for screen-reader-only) → footer buttons |
| Space / Enter on vertex row | Selects that vertex (same as click) |
| Backspace (no input focused) during `drawing` | Pops last vertex |
| Backspace (no input focused) during `editing` with `selectedVertex !== null` | Deletes that vertex |
| Delete (no input focused) | Same as Backspace deletion |
| Esc | Cancels current mode (drawing → idle if empty / editing if ≥2 vertices; inserting → editing; deselects vertex in editing) |
| Enter (no input focused) during `drawing` | Same as `[Finish]` (if ≥2 vertices) |
| ↑ / ↓ on focused vertex row | Moves focus to prev/next row (does NOT change selection — focus and selection are distinct) |

**Critical:** all keyboard handlers check `e.target.tagName !== 'INPUT' && !== 'TEXTAREA' && !e.target.isContentEditable` before treating as ruler-shortcut, to avoid stealing keys from the search input or other text inputs.

#### C.7 Accessibility

- **Vertex list:** `role="list"`, `role="listitem"`, `aria-selected`, `aria-label` per row summarizing distance/bearing.
- **Sparkline:** `role="img"` with `aria-label` summarizing min/max/gain/loss numerically.
- **Mode banner (sidebar inline):** `role="status"` with `aria-live="polite"`.
- **Map mode banner (floating):** see §D.4. Same `role="status"` semantics; `[×]` is a real `<button aria-label="Cancel ruler mode">`.
- **Color contrast disclaimer:** ruler line/vertex foreground colors (`#ffd400` yellow, `#ff7a00` orange) do NOT meet WCAG 1.4.11 (4.5:1) against light basemap fills. Visibility is achieved via the **7px black shadow halo** behind the line and the **2-3 px white stroke** around vertex circles — these provide separation from any underlying basemap regardless of fill color. Color is for identity (yellow = ruler, orange = selection); contrast is from halo geometry. Documented as accepted limitation.
- **Mobile considerations:** Vertex rows ≥44 px (Apple HIG / Material). Action buttons stack full-width on viewport < 480px. Sidebar overlays the map via existing `#sidebar-overlay`.

### D. Map rendering

**Sources** (added on `init`, mutated on state changes, removed on `clear`):
- `ruler-line-source` — GeoJSON `Feature<LineString>`. Empty when no vertices.
- `ruler-vertex-source` — GeoJSON `FeatureCollection<Point>`, one Feature per vertex with `properties: { index, label, selected }`.

**Layers** (added above all imagery, vector tiles, KMZ pins, search pins; below nav UI):

| Layer ID | Type | Style |
|---|---|---|
| `ruler-line-shadow` | line | width 7, color rgba(0,0,0,0.55), line-cap round, line-join round |
| `ruler-line` | line | width 4, color #ffd400, opacity 0.95, line-cap round, line-join round |
| `ruler-vertex-circles` | circle | radius 8, fill #ffd400, stroke 2, stroke-color white |
| `ruler-vertex-circles-selected` | circle | filter `['==', ['get', 'selected'], true]`, radius 11, fill #ff7a00, stroke 3, stroke-color white |
| `ruler-vertex-hit-circles` | circle | radius 22 (i.e. 44 px diameter — WCAG 2.5.5), fill rgba(0,0,0,0), stroke 0; visible only via cursor change on hover |
| `ruler-vertex-labels` | symbol | text-field `{label}`, text-font `['Metropolis Regular']` (per R1 — must specify; tileserver only serves Metropolis + Noto Sans), size 12, offset `[0,-1.4em]`, halo white, anchor bottom |

**Critical clarifications:**
- The hit-circles layer is **visible-but-transparent**, NOT `visibility: 'none'` — MapLibre's hit-test query (`map.queryRenderedFeatures`) ignores layers with `visibility: 'none'`. Setting fill alpha = 0 keeps the layer hit-testable while invisible.
- Layer ordering: `-shadow` → `-line` → `-vertex-circles` → `-vertex-circles-selected` → `-vertex-hit-circles` → `-vertex-labels`. The hit layer goes ABOVE visible vertex circles so its hit area extends fully (otherwise the visible 16-px circle would shadow the 44-px hit area's mouse events).
- Filter expression: MapLibre v3+ requires the explicit `['get', 'selected']` form — the older `['==', 'selected', true]` shorthand is deprecated.

**Style-load reattach** — sources/layers re-emitted via the existing **centralized** `addPlaceholderSources()` function at [app.js:143](frontend/app.js#L143) (per R1: spec v1 was looser than the cited precedent — v2 requires extending the existing centralized hook, NOT spawning a parallel `map.on('style.load')` handler). ruler.js exposes a `_ruler.reattachSources(map)` function that `addPlaceholderSources` calls; this keeps style-load behavior consistent with hillshade and other layers.

#### D.4 Banner placement (floating mode banner)

**Per R3 finding:** spec v1 hand-waved Open Question 5. Resolved here.

`#nav-banner` lives inside `#nav-overlay` at `top: 0; right: 0; z-index: 18` (NOT a top-center floater). The ruler banner is implemented as the **same DOM slot**:

- A new `<div id="ruler-mode-banner" class="hidden">` lives in the same overlay region, positioned `top: 12px; left: 50%; transform: translateX(-50%); z-index: 19;` — above #nav-banner's z-index but below sidebar's z-index of 20. So when sidebar is open, banner is occluded by sidebar (acceptable — user is already looking at sidebar content).
- **Mutual exclusivity rule:** `_ruler.isActive() === true` AND `nav.isActive() === true` simultaneously is acceptable but the ruler banner ALONE shows; nav banner is occluded by ruler banner during ruler-active states. Rationale: ruler is a deliberate-attention task; nav is a passive monitoring task. The user opened the ruler mode; they're attending to it. Nav guidance keeps speaking (TTS, voice prompts) but the visual nav banner yields its position.
- When ruler exits (returns to `idle` or `editing`), `#ruler-mode-banner` is hidden; nav banner re-renders if nav is still active.

**Banner content:** `<div role="status" aria-live="polite"><span>{message}</span><button aria-label="Cancel ruler mode" class="ruler-banner-cancel">×</button></div>`. The cancel `[×]` is a real focusable button.

#### D.5 iOS Safari touch contract

Per R3 finding: v1 hand-waved touch handling. v2 specifies:

1. **Use MapLibre's normalized event API where possible.** `map.on('touchstart', layerId, handler)` instead of raw DOM listeners. MapLibre handles synthetic-mouse-event suppression internally for layer-scoped listeners.
2. **For drag, where MapLibre's API is insufficient, use raw DOM with `passive: false`** explicitly: `canvas.addEventListener('touchstart', handler, { passive: false })`. Without this, `preventDefault()` is silently ignored on iOS, and the synthetic mouse event fires, corrupting the drag state.
3. **`touch-action: manipulation` on the map canvas** prevents the iOS 300ms tap-delay and disables system pinch-zoom on the canvas (MapLibre handles its own pinch). Add as a CSS rule on `.maplibregl-canvas`.
4. **Disable MapLibre `dragPan` on vertex `touchstart`, re-enable on `touchend`** (mirrors mouse behavior).
5. **Tap vs drag thresholds (touch-specific, per R3):** 8px AND 250ms — looser than mouse (5px / 200ms) to accommodate gloved fingers and vehicle jitter.
6. **PWA standalone mode:** ruler must work the same in PWA standalone (added-to-home-screen) as in regular Safari. The manual ship-gate checklist explicitly tests this.
7. **Two-finger pinch never starts a drag** — MapLibre's gesture system handles this; ruler's vertex `touchstart` handler checks `e.touches.length === 1` before claiming the gesture.

#### D.6 Drag-to-reposition detail

**Mouse:** `mousedown` on `ruler-vertex-hit-circles` (NOT `ruler-vertex-circles` — the larger hit area is the click target):
- Capture vertex index, disable `map.dragPan`.
- Enter local "dragging-vertex" sub-state.
- On `mousemove`: update `state.vertices[i]`, **rAF-coalesce the source `setData()` call** (per R2 — 60 fps source updates on a 50-vertex measurement stutter on Pi 5 GPU). Use `requestAnimationFrame` so we emit at most one source update per frame.
- Do NOT recompute distances/bearings during drag (avoids per-frame thrash).
- On `mouseup`: re-enable drag-pan, clear sub-state, run **single recompute** (segments, total, abort prior elevation sampling, re-sample elevation).

**Touch:** equivalent flow via `touchstart` / `touchmove` / `touchend` on the map canvas. `touchmove` is also rAF-coalesced.

**Tap-vs-drag disambiguation:**
- Mouse: `mousedown`→`mouseup` within **5 px AND 200 ms** = tap (selects vertex).
- Touch: `touchstart`→`touchend` within **8 px AND 250 ms** = tap.
- Anything more = drag.

#### D.7 Cursor management

- `drawing` / `inserting`: `crosshair`
- `editing` + hover on `ruler-vertex-hit-circles`: `pointer`
- `editing` + dragging-vertex sub-state: `grabbing`
- All other cases: cursor restored to default

### E. Math

#### E.1 Distance
**Reuse** `haversineDistance(a, b)` from app.js:1923 via `window._haversineDistance` export. Sub-meter accuracy at CONUS scales.

#### E.2 Bearing (true, forward azimuth)
New pure function `bearingDeg(a, b)` in ruler.js — standard great-circle initial-bearing formula, normalized to `[0, 360)`. NOT rhumb-line bearing.

```js
function bearingDeg(a, b) {
  var lat1 = a[1] * Math.PI / 180;
  var lat2 = b[1] * Math.PI / 180;
  var dLng = (b[0] - a[0]) * Math.PI / 180;
  var y = Math.sin(dLng) * Math.cos(lat2);
  var x = Math.cos(lat1) * Math.sin(lat2) -
          Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLng);
  return ((Math.atan2(y, x) * 180 / Math.PI) + 360) % 360;
}
```

#### E.3 Elevation sampling

**Source:** existing `/tiles/data/elevation/{z}/{x}/{y}.png` tiles. Same-origin via nginx — no CORS handling needed.

**CRITICAL FIX (R1+R2+R4 convergent):** v1 used the wrong decode formula. Tiles are **Mapzen Terrarium-encoded** (verified at [app.js:325](frontend/app.js#L325) `encoding: 'terrarium'` and [download_elevation.py:39](scripts/download_elevation.py#L39) `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/`).

```js
function elevationFromRGB(r, g, b) {
  // Mapzen Terrarium decode. NOT Mapbox Terrain-RGB.
  // Reference: https://github.com/tilezen/joerd/blob/master/docs/formats.md
  return (r * 256 + g + b / 256) - 32768;
}
```

A unit test against known reference points (sea level near coastline, Death Valley negative elevation, Mount Whitney) is required to lock this in.

**Sample zoom: z=12.** Per R2 finding, the v1 spec's "9.5 m/px at AZ latitude" claim was wrong (that's z=14). Actual at z=12, lat=33.45° N: ~32 m/px. **Use z=12 because that's the max actual data zoom** — `download_elevation.py:41` defaults to `DEFAULT_ZOOM = "0-12"`. Higher zooms return 404 from the MBTiles. The MapLibre source declares `maxzoom: 14` but that's a request ceiling, not a data ceiling; the underlying MBTiles only contain z=0..12.

**Sampling strategy** (after Finish; not live):

1. **Sample count:** `numSamples = clamp(Math.floor(L_total / 50), 50, 200)` — ~50m sample spacing, capped 50 ≤ N ≤ 200. At z=12 ~32m/px, this oversamples source resolution slightly (good for sparkline rendering).
2. For each fractional position `f ∈ [0, 1]` along cumulative path, compute `[lng, lat]` via linear segment-interpolation. (Tradeoff documented per R2 MINOR: linear-in-lng/lat differs from geodesic-in-arc by sub-meter at typical segment lengths; acceptable since MapLibre renders Mercator-straight lines anyway, so the rendered line and the sampled line agree.)
3. For each sample compute z=12 tile coords + intra-tile pixel offset.
4. Group samples by `(tx, ty)`; fetch each unique tile once, decode in canvas, read all sample pixels.
5. **Concurrent fetch limit: 6** (per R2 — HTTP/1.1 LAN browsers cap at 6 per origin; HTTP/2 multiplexes but artificially throttling matches the LAN ceiling for predictability).
6. **Tile cache:** in-memory LRU, **30-tile cap** (≈7.5 MB for raw RGBA at 256 KB/tile per R2 finding — was 192 KB in v1, but `getImageData` returns 4 bytes/pixel = RGBA, not RGB). Eviction: oldest unused tile when cap reached.
7. **Tile cap for one path: 50 tiles.** Samples beyond → null + "Path too long for full elevation profile" notice. 50 covers a single-state CONUS coverage (e.g., AZ measurement diagonal ~30 tiles at z=12).
8. **Cancellation contract** (per R2+R4 race analysis):
   - Each sampling run holds an `AbortController` and a generation counter.
   - `clear()`, drag-mouseup-triggering-recompute, and any state-mutating action that supersedes the in-flight run **abort the controller AND increment the gen counter**.
   - Gen counter is checked at TWO points: (a) on fetch onload, before pixel decode (saves CPU); (b) before mutating `state.elevationProfile` (catches resolved-but-pending-microtask races).
   - `requestIdleCallback` is NOT used — would expose race surface. All sampling work runs in microtasks chained off the abortable promise.
9. **`samplingState` lifecycle:** `idle` → `sampling` (count tiles, kick off fetches, render skeleton sparkline + counter) → `done` (all tiles fetched and decoded, profile complete) | `partial` (some tiles failed but ≥1 succeeded; show what we have with coverage warning) | `failed` (all tiles failed, e.g., network down; render "Failed to load elevation data — showing distance only").

**Min/max/gain/loss:** computed only on non-null samples; gain/loss skips diffs across coverage gaps and across `null`-bracketing transitions.

#### E.4 Coordinate display
Reuse `formatDD(value, 'NS' | 'EW')` from app.js via `window._formatDD` export. Output: `33.45000° N` (5 decimals, space before hemisphere — per R4 finding the v1 spec mis-described the format).

#### E.5 Insert After / Insert Before — segment projection
Per R3 finding: v1 said "next map tap inserts the new vertex" without constraining placement. v2 specifies:

- Tap during `inserting` state computes the **closest point on the relevant segment** (geodesic projection) to the tap location.
- New vertex is placed at the projected point, NOT at the raw tap location.
- For Insert After Vn, "relevant segment" = Vn → Vn+1; for Insert Before Vn, "relevant segment" = Vn-1 → Vn.
- For Insert Before V1 or Insert After Vlast (the path's endpoints), there is no adjacent segment — in those cases the tap places at the raw tap location (extending the path).

This prevents "tap 1000km off-segment, get a vertex inserted into a logical slot but at a geographically nonsensical location" per R3.

### F. Edge cases (post-R4 expansion)

| Case | Handling |
|---|---|
| Single vertex placed | Sidebar shows V1 row; no Total / sparkline / Finish-enabled. State stays `drawing`. |
| Two consecutive duplicate clicks (within 5 px AND 250 ms) | Debounced — second click ignored. |
| Antimeridian crossing | Out of scope per Non-goals. Code computes correctly via haversine; rendering produces a long horizontal slash. |
| Path entirely outside elevation coverage | Sparkline section: "Elevation data not available for this area." samplingState: `failed`. |
| Partial coverage (some null samples) | Dashed segments where null; coverage warning badge with percentage outside coverage. samplingState: `partial`. |
| Tile fetch error | Per-tile failures don't abort run. Affected samples → null. If ALL tiles fail: samplingState: `failed`. |
| Sidebar tab switched away during drawing/inserting | Treat as Cancel: → `editing` if ≥2 vertices, else `idle`. Preserve data when ≥2; banner hides; cursor restored. |
| Sidebar tab switched away during editing | Preserve full state; resume in-place when tab returns. |
| Page reload mid-measurement | All state lost. By design (ephemeral v1). |
| Drag-vs-tap: mouse | 5 px AND 200 ms threshold |
| Drag-vs-tap: touch | 8 px AND 250 ms threshold |
| Very long path (>50 tiles) | First 50 tiles only; rest → null with notice. |
| Map style-load (basemap toggle / 3D enable) | Sources/layers re-emitted via centralized `addPlaceholderSources()`. |
| Browser missing fetch / Canvas | Distance + bearing always work. Elevation degrades gracefully. |
| Modifier keys held during click | Existing app.js:1624 suppression carries through. |
| Backspace / Delete pressed in a text input | Keyboard handler checks `e.target` tagName/contentEditable. |
| MapLibre terrain enabled (3D) | Renders correctly. Vertex circles auto-project to elevated surface. |
| Multitouch during vertex drag | `touchmove` checks `e.touches.length === 1`; >1 cancels drag. |
| Window minimize → unminimize during sampling | Sampling resumes (browser throttles fetch but doesn't kill). UI updates on resume. |
| User hits very-low-disk-space (Pi or browser) and tile decode fails | Per-tile failure; same path as fetch error. |
| Clock change mid-session | No effect — no time-sensitive comparisons in ruler logic. |
| Two browser tabs open simultaneously | Each holds independent in-memory state. Tile cache is per-tab. No collision. |
| Pipeline writing elevation MBTiles during sampling | Tile fetch may serve stale or partial data; per-tile error path catches. |
| Layer-specific click on KMZ pin / search pin during drawing | Existing handlers at L660 and L1272 bail via `_ruler.isActive()` check. |
| User pinch-zooms during drag | Drag is canceled (`touchmove` `e.touches.length` check); pinch handles normally. |
| Detached drag-mouseup (mouse released outside window) | `mouseup` listener is on `window`, not on the canvas; cleanup fires. |
| Rapid Insert-After / Esc cycle | Each transition is atomic — no orphaned `inserting` state. |
| Vertex placed at exact same lng/lat as an existing vertex | Allowed; produces a zero-length segment with bearing 0°. Not debounced (different from rapid-click debounce). |
| `formatDD` called with NaN | `formatDD` (existing) returns "NaN° N" — accept as a regression visible in tests; ruler doesn't sanitize. |

## Testing strategy

### Unit tests — `frontend/tests/ruler/`
Run: `node --test --test-force-exit frontend/tests/ruler/`.

| File | Coverage |
|---|---|
| `test_geodesy.js` | `haversineDistance` (round-trip, antipodes, zero-length, CONUS-mileage validation); `bearingDeg` (cardinals, reciprocals, AZ→CO USGS reference) |
| `test_terrain_rgb.js` | `elevationFromRGB` decode against pngjs-decoded real Terrarium tile fixture (per R4 — JSDOM doesn't exercise canvas pixel readback, so use pngjs in Node directly). Reference points: sea level (0±1m), Mt. Whitney (~4421m), Death Valley (~-86m). |
| `test_sample_path.js` | `samplePath(vertices, numSamples)` correctness (count, distribution, segment-spanning, degenerate inputs, divide-by-zero protection, segment-projection for Insert After). |
| `test_state_machine.js` | All §B transitions; selectedVertex / insertSlot invariants per state; sidebar-tab-switched-away preservation rules. |
| `test_unit_format.js` | `formatRulerDistance` imperial↔metric flip when `window._geographicaUseImperial` toggles. |
| `test_sparkline.js` | `sparklinePath(samples, width, height)` SVG `points` correctness; min/max → chart top/bottom; coverage gaps split path; empty samples → empty path. |
| `test_segment_projection.js` | `projectPointToSegment(latlng, segStart, segEnd)` correctness — point on segment, point off-side, point past endpoints (clamped). |

### Integration / DOM tests — JSDOM
| Test | Asserts |
|---|---|
| `test_panel_render.js` | Empty state placeholder; vertex list grows on append; `.selected` class on selected row; sparkline shows sampling state machine progression; ARIA attrs present. |
| `test_keyboard.js` | Per §C.6 table; Backspace pops during drawing (not when input focused); Esc cancels insert; Enter finishes; Tab/Space/Delete work; arrow keys move focus only. |
| `test_mode_flag.js` | `_ruler.isActive()` matches state. |

### Source-grep enforcement test (per R4 finding)
A `test_app_js_bail_present.js` file uses regex-grep against the actual `app.js` source to verify the three bail lines are present at L1622, L660, L1272 regions. Pattern matches the overview-incremental enforcement test (`tests/test_overview_write_enforcement.py`). Without this, a future PR could silently remove a bail and JSDOM tests would still pass.

### Manual ship-gate checklist (extended per R4)
Full Playwright is out of scope. Manual checklist before merge:

```
[ ] Open Measure tab → place 5 vertices → see line + circles + sidebar list
[ ] Click Finish → measurement enters editing state; sampling kicks off
[ ] Sampling progress counter shows X/Y tiles; resolves to elevation profile
[ ] Click V3 in sidebar → orange highlight on map AND sparkline guide line
[ ] Click [Insert After] → banner appears; tap on segment between V3/V4 → new vertex placed via projection (not at raw tap point)
[ ] Drag V2 to new location → distances/bearings recompute on drag-end; sampling re-runs
[ ] Click [Delete] on V4 → V4 removed, V5 renumbers to V4
[ ] Switch to Layers tab → measurement preserved (state is editing) → switch back, see same data
[ ] Switch to Layers tab during drawing with 0 vertices → state resets to idle on return
[ ] Switch to Layers tab during drawing with ≥2 vertices → resumes in editing on return
[ ] Click Clear → all gone, idle state
[ ] iOS Safari touch: vertex tap → vertex circle drag → insert flow all work; no 300ms tap delay; pinch-zoom doesn't trigger drag
[ ] iOS Safari PWA standalone (Add to Home Screen): same as above
[ ] Android Chrome touch: same suite
[ ] Gloved fingers (winter glove, photo of test on Pi): vertex tap-target reachable
[ ] HTTPS Tailscale + HTTP LAN: ruler works identically
[ ] Draw across edge of elevation coverage → dashed gap + warning; partial samplingState
[ ] Network unplugged mid-sampling → samplingState: failed; "Failed to load elevation data" message
[ ] 1000-mile path (3 western states) → 50-tile cap kicks in; UI responsive; "Path too long" notice
[ ] Activate nav, then open Measure tab → ruler banner shows; nav voice prompts continue; visual nav banner occluded by ruler banner
[ ] During measurement, toggle imperial↔metric — readouts re-render
[ ] During measurement, toggle basemap (USGS → NAIP) — line and vertices remain visible (style-load reattach)
[ ] Reload Measure-as-last-tab → empty Measure tab opens cleanly; no error
[ ] Backspace during drawing pops last; Backspace in search box does NOT
[ ] Esc during inserting returns to editing; Esc during editing deselects vertex
[ ] Two parallel agents not stepping on each other (no merge conflicts in app.js insertion regions L660, L1272, L1622)
[ ] Color contrast in sunlight on a real Pi tablet — line+halo and vertex+stroke clearly visible against light basemap and over imagery
[ ] Two browser tabs open simultaneously — independent state, no cross-tab interference
[ ] iOS Safari + Voice Over screen reader: vertex list announced as list with selectability; sparkline aria-label read; mode banner announced via aria-live
```

### Pitfalls cross-reference
- [docs/pitfalls/implementation-pitfalls.md](../../pitfalls/implementation-pitfalls.md) — §14 worktree escapes, §15 destructive git (boilerplate)
- [docs/pitfalls/testing-pitfalls.md](../../pitfalls/testing-pitfalls.md) — JSDOM doesn't fully exercise touch or canvas pixel decode; manual checklist + pngjs-based unit test are the explicit gap-closers.

Specific patterns ruler must respect:
- `AbortController` for in-flight tile fetches; generation counter checked pre-decode AND pre-state-mutation.
- No `setInterval` / `setTimeout` references that survive `clear()`.
- Touch events use `passive: false` where `preventDefault()` is required.
- All keyboard handlers check `e.target.tagName` / `isContentEditable` before claiming the key.
- Symbol layers always specify `text-font: ['Metropolis Regular']`.
- Style-load reattach via `addPlaceholderSources()` at app.js:143, NOT a parallel `map.on('style.load')` handler.

## Coordination with parallel agents

Two parallel sessions are touching nav/voice during this cycle (per `dev/adversarial/2026-04-24-nav-voice-followup-*.md` artifacts and recent commits `1e91579`, `d54c111`, `7800ae7`). Ruler's surface area is deliberately disjoint:

- **No edits to** `frontend/navigation.js`, `frontend/nav-ui.js`, `frontend/voice-picker.js`, `frontend/wake-lock.js`, `frontend/silent-video-lock.js`.
- **Five small inserts + one whitelist edit** to `app.js` — all in non-overlapping regions:
  1. Click-handler bail at L1622 (reverse-geocode handler)
  2. Click-handler bail at L660 (KMZ-pin / imported-geometry handler)
  3. Click-handler bail at L1272 (search-result-circles handler)
  4. `window._formatDD` and `window._haversineDistance` exports at end of IIFE
  5. `initRuler(map)` call in bootstrap — explicitly between `initSidebarTabs()` and `restoreLastSidebarTab()`
  6. Edit `VALID_SIDEBAR_PANELS` array at L4103 — append `'measure-panel'`
- **One tab insert** to `index.html` — adds 5th tab button + new `class="panel"` div + `<script src="ruler.js"></script>`.
- **CSS additions** in `style.css` use the `.ruler-` prefix.

If a merge conflict surfaces in any of the 6 app.js insertion points, resolve by relocating the insert to a non-conflicting nearby line; the inserts have no ordering dependencies beyond the bootstrap-sequence constraint (L4 must run between `initSidebarTabs()` and `restoreLastSidebarTab()`).

## Open questions remaining for R5 (Codex cross-validation)

R1-R4 resolved most of v1's open questions. Remaining for R5:

1. **Subtle integration risks** — does Codex find any cross-module coupling we missed? Specifically: does the `window._formatDD` / `window._haversineDistance` export pattern cleanly survive a future app.js refactor that moves these helpers? (Lock pattern: keep them as named module-internal functions in app.js plus the explicit `window.X = X` exports at IIFE end.)
2. **Touch-handling correctness** — Codex with web search may find iOS Safari behaviors we missed (e.g., `dragstart` event interaction, IndexedDB transaction abort during touchmove, MapLibre v5.x specific touch quirks).
3. **Test coverage gap detection** — does the test list miss anything Codex would consider a CI-must-have?
4. **Symbol-layer rendering in offline mode** — does the Metropolis font load offline reliably, or does the AREDN-mesh-no-internet context introduce a font-load failure mode?
5. **The 50-tile cap derivation** — R2 already revised; R5 may have an even tighter recommendation given measured tile sizes.
6. **The state-shape invariants** — are the four invariants in §A complete? (Codex may surface a fifth that v1 readers missed.)

## Scope estimate

Roughly 4–5 days of subagent-driven implementation work (revised from v1's 3–4 days due to expanded surface area: ARIA/keyboard nav, hit-circles layer, segment-projection, sampling-state UI, banner-slot reuse, source-grep enforcement test):

- Phase 0: scaffolding (new file, init wiring, exports, tab DOM, panel class convention, VALID_SIDEBAR_PANELS edit)
- Phase 1: drawing state + state machine + map sources/layers (incl. hit-circles layer)
- Phase 2: vertex-centric edit (select / drag / delete / insert with segment projection)
- Phase 3: elevation sampling (Terrarium decode, LRU cache, AbortController + gen counter, samplingState UI, skeleton sparkline)
- Phase 4: edge cases, ARIA, keyboard nav, banner-slot reuse, error paths
- Phase 5: review loops (≥3 rounds per build-robust-features) + manual ship-gate validation

Detailed task breakdown will be produced by the writing-plans skill after R5.
