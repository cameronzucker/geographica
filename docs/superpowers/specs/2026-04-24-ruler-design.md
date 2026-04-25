# Ruler / measurement tool — design (v1)

**Status:** v1 (pre-adversarial review)
**Author:** Agent `cholla`, 2026-04-24
**Adversarial review:** *pending* — 5 rounds planned with at least one Codex round per the `build-robust-features` discipline. Transcripts will land under `dev/adversarial/2026-04-24-ruler-r{1..5}-*.md` before the implementation plan is written.

**Visual reference:** mockup at `.superpowers/brainstorm/1827880-1777091427/content/measure-tab-mockup.html` (gitignored). Three states rendered: drawing (3 vertices in progress), editing (5 vertices, V3 selected), inserting (Insert After armed, ghost preview). Open the file directly in a browser, or restart the brainstorm server with `scripts/start-server.sh --project-dir /home/administrator/Code/geographica`.

## Problem

Geographica has no on-map measurement tool. Users who need to know a distance ("how far from here to that summit?", "what's the elevation gain on this traverse?", "what bearing should I point the antenna?") today have to reach for an external tool — Google Earth, CalTopo, a printed sectional, or the back of an envelope. This is a basic-tier GIS competency that every comparable product (Google Earth, CalTopo, Avenza, MapBox Studio, ArcGIS) ships, and AREDN amateur-radio operators specifically use measurement tools as part of routine path-planning, antenna-aiming, and field-navigation workflows.

The lack of a ruler is felt sharply enough that the missing capability has been on the backlog under "things Google Earth does that we don't yet."

## Goals

- Click-to-place vertices on the map; multi-segment paths supported.
- Per-segment and cumulative geodesic distance, formatted in the user's existing imperial/metric preference.
- Per-segment **true** bearing in decimal degrees.
- Inline elevation profile (sparkline + min / max / gain / loss) sampled from the existing Terrain-RGB elevation tiles.
- Vertex-centric edit model after placement: select a vertex → drag to reposition, delete, or insert before/after.
- Touch + mouse parity. Field-readable in sunlight (high-contrast palette).
- Self-contained `frontend/ruler.js` module — minimal, well-bounded touch to existing `app.js`, `index.html`, and `style.css`.

## Non-goals

- **Persistence / "save measurement".** v1 is purely ephemeral — measurements clear on tab switch, page reload, or "Clear" button. The design carefully keeps the data shape KMZ-serializable so the future *My Places* cycle (a separate spec) can add save/load/export without refactoring ruler internals.
- **Polygon area** / closed-figure area measurement. Sibling future feature in the same "measurement tools" family. Different math (geodesic polygon area), different UX (tap-first-vertex-to-close, or explicit "Close polygon" button), different design questions. Out of scope for ruler v1.
- **Magnetic bearing** with declination correction. True bearing only; declination is the operator's responsibility. Adding magnetic later is a 10-line follow-up if requested, but requires bundling a World Magnetic Model coefficient grid.
- **Click-on-segment-line to insert vertex.** Rejected during brainstorming as unintuitive; conflicts with map-pan; users don't think to try it.
- **Hover/tap interactivity on the sparkline itself.** v1 sparkline is static; vertex-list-row click is the path to inspect a specific point. Defer interactive chart to v2 if usage signals demand.
- **Antimeridian crossing** (-180/+180 longitude wrap). CONUS-only data coverage means no real users hit it. Code computes correctly via haversine but renders the line as a long horizontal slash; acceptable until coverage expands.
- **Concurrent multiple measurements.** One measurement at a time in v1 to keep the vertex-centric edit model unambiguous.

## Architecture

### A. Module layout & data shape

**New module:** `frontend/ruler.js` — IIFE pattern (matches `voice-picker.js`, `import-store.js`). Exposes a single `window._ruler` API:

```js
window._ruler = {
  init: function (map, appAPI) { ... },  // called once during bootstrap
  isActive: function () { ... },         // true when status ∈ {drawing, inserting}
  clear: function () { ... },            // force-reset; called when Measure tab is left
};
```

**Minimal touch to existing files:**

- `frontend/index.html` — add 5th tab button + `<div id="measure-panel" class="sidebar-panel hidden">…</div>` skeleton + `<script src="ruler.js"></script>`. ~32 added lines.
- `frontend/app.js` — three insertions:
  1. **Mode-flag suppression** at the existing click handler at L1622 (~3 lines): early-return when `window._ruler && window._ruler.isActive()`.
  2. **`window._appAPI` export** (~10 lines): collect `useImperial`, `formatRouteDistance`, `formatNavDistance`, `haversineDistance`, `formatDD` into an explicit object so ruler.js consumes them as an interface rather than hoisting from globals.
  3. **`initRuler()` call** in the bootstrap sequence alongside `initImport()` / `initAdmin()` (~1 line).
- `frontend/style.css` — additions for `.ruler-vertex-row`, `.ruler-sparkline`, `.ruler-stats`, `.ruler-banner`, `.ruler-mode-banner-floating`, vertex marker styles. ~80 lines.

**Canonical state object (KMZ-serializable, no DOM/MapLibre refs):**

```js
state = {
  status: 'idle' | 'drawing' | 'editing' | 'inserting',
  selectedVertex: null | int,
  insertSlot: null | { before: int },   // populated only when status === 'inserting'
  vertices: [
    { lng: -112.0700, lat: 33.4500, label: 'V1' },
    // ...
  ],
  // Cached/computed; recomputed on any mutation:
  segments: [{ distance_m, bearing_deg, from, to }],
  totalDistance_m: number,
  elevationProfile: null | {
    samples: [{ distance_m, elevation_m }],
    minM, maxM, gainM, lossM,
    coverageGaps: [{ from, to }],   // fractions of total
  },
};
```

A separate (NOT serialized) view-state object holds map-marker handles, listener-cleanup callbacks, and DOM nodes — purely view-layer cruft kept out of the data shape.

### B. State machine

Four explicit states. No timeouts, no implicit transitions. Edges:

| From | To | Trigger |
|---|---|---|
| `idle` | `drawing` | First map tap (after Measure tab visible AND not currently editing a finished measurement) |
| `drawing` | `drawing` | Map tap appends vertex; Backspace pops last; modifier keys (Ctrl/Shift) suppress placement |
| `drawing` | `editing` | Finish gesture: double-click empty map, Enter key, or `[Finish]` button (only enabled with ≥2 vertices) |
| `drawing` | `idle` | Esc, `[Clear]`, or sidebar tab switched away with <2 vertices |
| `editing` | `editing` | Tap vertex (select); drag vertex (reposition on `mouseup`); tap empty map → falls through to existing reverse-geocode handler (no ruler-specific behavior) |
| `editing` | `inserting` | `[Insert Before]` or `[Insert After]` clicked on a selected vertex |
| `editing` | `idle` | `[Clear]` or `[+ New measurement]` |
| `inserting` | `editing` | Map tap commits insert (new vertex selected); OR Esc / banner `[×]` / re-click same Insert button cancels |
| `inserting` | `idle` | `[Clear]` |
| any | `idle` | Sidebar tab switched away with <2 vertices; or page reload (state lost) |

**Drawing mode** is the only state where empty-map clicks append vertices. **Editing** allows vertex selection (tap to select), drag-to-reposition, delete, and insert-before/after triggers; empty-map clicks fall through to the existing reverse-geocode handler at app.js:1622 (intentional — nothing to do with the ruler in editing mode).

**Inserting** is a deliberate, explicit, mode-scoped intermediate state: triggered by the user clicking [Insert Before] or [Insert After] on a selected vertex. The next map tap commits the insert and returns to `editing` with the new vertex selected. Esc, "×" on the floating banner, or re-clicking the same Insert button cancels and returns to `editing`.

**The critical isActive() boundary:** `isActive()` returns `true` for `drawing` and `inserting`, `false` for `idle` and `editing`. The mode-flag check at app.js:1622 specifically suppresses the reverse-geocode / "add as route point" popup during the two states where empty-map clicks have ruler-specific meaning.

### C. Sidebar UI structure

The Measure panel renders into `#measure-panel` (the new 5th tab — added after Admin). Six sections, top to bottom, conditionally visible per state:

1. **Mode banner** (visible during `drawing` / `inserting` only). Inline within the panel; the floating map-overlay banner is a separate element (§D).
2. **Headline stats:** Total distance in current units, large readout. Hidden when `vertices.length < 2`.
3. **Vertex list** (scrollable, ≥44 px row height for touch): each row shows `Vn`, lat/lng (decimal degrees with hemisphere suffix per existing `formatDD`), and below it the segment-out-of-this-vertex distance + bearing. Selected vertex gets a 3px orange left border + accent background. Last vertex shows no segment-out line.
4. **Selected-vertex action row** — `[↑ Insert Before] [↓ Insert After] [✗ Delete]`. Visible only when `selectedVertex !== null`.
5. **Elevation profile** — visible when `vertices.length ≥ 2` AND sampling has completed (post-Finish; not live during drawing). 250×80 px SVG sparkline with vertex tick marks on x-axis; selected-vertex draws a vertical guide line. Below: 2×2 grid of min / max / gain / loss with gain in success-green and loss in danger-pink. Coverage warning badge if gaps > 0%.
6. **Footer controls** — `drawing`: `[↶ Undo] [Clear] [Finish]`; `editing`: `[Clear] [+ New measurement]`; `inserting`: footer hidden.

**Visibility transition rules** are documented in the brainstorm conversation and implemented as a single `renderPanel(state)` function — no scattered `.style.display` toggles. Single source of truth.

**Mobile considerations:**
- Vertex rows ≥44 px (Apple HIG / Material). Action buttons stack full-width on viewport < 480px.
- Sidebar overlays the map via existing `#sidebar-overlay` machinery — no new responsive logic.

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
| `ruler-vertex-circles-selected` | circle | filter `['==', 'selected', true]`, radius 11, fill #ff7a00, stroke 3, stroke-color white |
| `ruler-vertex-labels` | symbol | text-field `{label}`, size 12, offset `[0,-1.4em]`, halo white, anchor bottom |

Layer ordering matters: `-shadow` below `-line` so the line sits on the shadow halo for sunlight contrast. The two vertex circle layers share the same source; toggling `selected` on a single feature re-classifies it in MapLibre's filter step in microseconds — no source re-emit.

**Drag-to-reposition (mouse):** `mousedown` on `ruler-vertex-circles` → disable `map.dragPan`, capture vertex index, enter local "dragging-vertex" sub-state. `mousemove` updates `state.vertices[i]` and re-emits source data WITHOUT recomputing distances/bearings (avoids per-frame thrash). `mouseup` re-enables drag-pan, clears sub-state, runs single recompute (segments, total, re-sample elevation).

**Drag-to-reposition (touch):** equivalent flow via `touchstart` / `touchmove` / `touchend` on the map canvas, hit-tested against `ruler-vertex-circles` at touchstart.

**Tap-vs-drag disambiguation:** `mousedown`/`touchstart` followed by `mouseup`/`touchend` within 5 px AND 200 ms = tap (selects vertex). Anything more = drag.

**Floating mode banner** (`<div id="ruler-mode-banner">`, NOT inside sidebar): top-center of map, semi-transparent dark background, white text. Visible during `drawing` / `inserting`. Has close `[×]` returning to `editing` (or `idle` if 0 vertices). Styled to not stack with `#nav-banner`.

**Cursor management:**
- `drawing` / `inserting`: `crosshair`
- `editing`: hover on `ruler-vertex-circles` → `pointer` (existing pattern at app.js:653-656)
- All other states: cursor restored

**Style-load reattach:** Sources/layers re-emitted on `map.on('style.load', ...)` matching the elevation-hillshade pattern at app.js:319-348. Survives basemap toggles and 3D-terrain enable/disable.

### E. Math

#### E.1 Distance
**Reuse** `haversineDistance(a, b)` from app.js:1923-1933 via `window._appAPI`. Sub-meter accuracy at CONUS scales; precision well below the UI's one-decimal display.

#### E.2 Bearing (true, forward azimuth)
New pure function `bearingDeg(a, b)` in ruler.js — standard great-circle initial-bearing formula, normalized to `[0, 360)`. NOT rhumb-line bearing — for short segments at CONUS latitudes the difference is < 0.5°/100 km and great-circle matches what GPS receivers / antenna-pointing software show.

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

**Source:** existing `/tiles/data/elevation/{z}/{x}/{y}.png` Terrain-RGB tiles. Same-origin via nginx — no CORS handling needed.

**Decode** (Mapbox Terrain-RGB standard):
```js
function elevationFromRGB(r, g, b) {
  return -10000 + ((r * 65536 + g * 256 + b) * 0.1);  // meters
}
```

**Sampling strategy** (after Finish; not live):
1. `numSamples = clamp(Math.floor(L_total / 50), 50, 200)` — ~50m sample spacing, capped 50 ≤ N ≤ 200.
2. For each fractional position `f ∈ [0, 1]` along cumulative path, compute `[lng, lat]` via linear segment-interpolation.
3. For each sample compute z=12 tile coords + intra-tile pixel offset.
4. Group samples by `(tx, ty)`; fetch each unique tile once, decode in-canvas, read all sample pixels.
5. Concurrent fetch limit: 8. Per-session in-memory tile cache (≈6 MB for 30 tiles).
6. 50-tile hard cap on pathological inputs; samples beyond → null + "Path too long for full elevation profile" notice.
7. **Cancellation:** all fetches share a single `AbortController` per sampling run. `clear()` and any state mutation that supersedes the in-flight run aborts the controller; in-flight pixel-decode work checks a generation counter before mutating `state.elevationProfile`. No orphan promises can land samples into a stale state.

**Why z=12:** ~9.5 m/px at AZ latitude. 200 samples on a 50-mile path = ~400m spacing → oversampling source resolution, every sample reads a real pixel. Higher zooms 16× the tile count for sub-pixel improvement that a 80-px sparkline can't render.

**Min/max/gain/loss:** computed only on non-null samples; gain/loss skips diffs across coverage gaps.

#### E.4 Coordinate display
Reuse `formatDD(value, 'NS' | 'EW')` from app.js. Output: `33.4500°N, 112.0700°W`. 4-decimal precision = ~11 m at CONUS latitudes.

### F. Edge cases

| Case | Handling |
|---|---|
| Single vertex placed | Sidebar shows V1 row; no Total / sparkline / Finish-enabled. State stays `drawing`. |
| Two consecutive duplicate clicks (within 5 px AND 250 ms) | Debounced — second click ignored; prevents accidental zero-length segment from a fat-finger double-tap. |
| Antimeridian crossing | Out of scope per Non-goals. Code computes correctly; rendering produces a long horizontal slash. Adversarial review will flag; deferral accepted. |
| Path entirely outside elevation coverage | Sparkline section: "Elevation data not available for this area." No min/max/gain/loss numbers. |
| Partial coverage (some null samples) | Dashed segments where null; coverage warning badge with percentage outside coverage. |
| Tile fetch error | Per-tile failures don't abort run. Affected samples → null. If ALL tiles fail: "Failed to load elevation data — showing distance only." |
| Sidebar tab switched away during drawing/inserting | Treat as Cancel: → `editing` if ≥2 vertices, else `idle`. Preserve data when ≥2; banner hides; cursor restored. |
| Page reload mid-measurement | All state lost. By design (ephemeral v1). |
| Drag-vs-tap on vertex | 5 px AND 200 ms threshold (mousedown→mouseup). Touch: `touchmove` between start/end = drag; bare touch = tap. |
| Very long path (100+ tiles) | First 50 tiles only; rest → null with notice. |
| Map style-load (basemap toggle / 3D enable) | Sources/layers re-emitted on `map.on('style.load')`. |
| Browser missing fetch / Canvas | Distance + bearing always work. Elevation degrades gracefully ("not available"). |
| Modifier keys held during click | Existing app.js:1624 suppression carries through — Ctrl/Shift + click does not place vertex. |
| Backspace pressed in a text input | Keyboard handler checks `e.target.tagName !== 'INPUT' && !== 'TEXTAREA'` before treating as undo. |
| MapLibre terrain enabled (3D) | Renders correctly. Vertex circles auto-project to elevated surface; line follows ground; profile sampled at z=12 regardless of terrain state. |

## Testing strategy

### Unit tests — `frontend/tests/ruler/`
Pattern from `frontend/tests/wake-lock/` and `frontend/tests/voice-picker/`. Run: `node --test --test-force-exit frontend/tests/ruler/`.

| File | Coverage |
|---|---|
| `test_geodesy.js` | `haversineDistance` (round-trip, antipodes, zero-length, CONUS-mileage validation); `bearingDeg` (cardinals, reciprocals, AZ→CO USGS reference) |
| `test_terrain_rgb.js` | `elevationFromRGB` decode fixtures (sentinel value, mid-gray, negative-elevation boundary) |
| `test_sample_path.js` | `samplePath(vertices, numSamples)` correctness (count, distribution, segment-spanning, degenerate inputs, divide-by-zero protection) |
| `test_state_machine.js` | All §B transitions; selectedVertex / insertSlot invariants per state |
| `test_unit_format.js` | imperial↔metric flip propagates through ruler readouts |
| `test_sparkline.js` | `sparklinePath(samples, width, height)` SVG `points` correctness; min/max → chart top/bottom; coverage gaps split path; empty samples → empty path |

### Integration / DOM tests — JSDOM
| Test | Asserts |
|---|---|
| `test_panel_render.js` | Empty state placeholder; vertex list grows on append; `.selected` class on selected row; sparkline appears post-sampling |
| `test_keyboard.js` | Backspace pops during drawing (not when input focused); Esc cancels insert; Enter finishes; arrows are no-ops |
| `test_mode_flag.js` | `_ruler.isActive()` matches state; mock app.js handler is suppressed during drawing/inserting |

### Manual ship-gate checklist
Full Playwright is out of scope (none in repo per START.md). Manual checklist before merge:

```
[ ] Open Measure tab → place 5 vertices → see line + circles + sidebar list
[ ] Click Finish → measurement enters editing state
[ ] Click V3 in sidebar → orange highlight on map AND sparkline
[ ] Click [Insert After] → banner appears
[ ] Tap map between V3/V4 → new vertex inserted with correct numbering
[ ] Drag V2 to new location → distances/bearings recompute on drag-end
[ ] Click [Delete] on V4 → V4 removed, V5 renumbers to V4
[ ] Switch to Layers tab → return → state preserved
[ ] Click Clear → all gone, idle state
[ ] iOS Safari (touch only): vertex tap, drag, insert all work
[ ] HTTPS Tailscale + HTTP LAN: ruler works identically
[ ] Draw across edge of elevation coverage → dashed gap + warning
[ ] 1000-mile path (3 western states) → sample cap kicks in; UI responsive
[ ] Two parallel agents not stepping on each other (no merge conflicts in app.js click handler region)
```

### Pitfalls cross-reference
Plan-writing step will explicitly cross-reference:
- [docs/pitfalls/implementation-pitfalls.md](../../pitfalls/implementation-pitfalls.md) — §14 worktree escapes (boilerplate; ruler isn't using worktrees), §15 destructive git (boilerplate)
- [docs/pitfalls/testing-pitfalls.md](../../pitfalls/testing-pitfalls.md) — JSDOM doesn't fully exercise touch; manual checklist is the explicit gap-closer

Specific patterns ruler must respect:
- `AbortController` for in-flight tile fetches when user clears mid-sample (no orphan promises mutating state after clear)
- No `setInterval` / `setTimeout` references that survive `clear()` — listener cleanup must be exhaustive
- Touch events must call `e.preventDefault()` to suppress synthetic mouse events on iOS

## Coordination with parallel agents

Two parallel sessions are touching nav/voice during this cycle (per `dev/adversarial/2026-04-24-nav-voice-followup-*.md` artifacts and recent commits `1e91579`, `d54c111`, `7800ae7`). Ruler's surface area is deliberately disjoint:

- **No edits to** `frontend/navigation.js`, `frontend/nav-ui.js`, `frontend/voice-picker.js`, `frontend/wake-lock.js`, `frontend/silent-video-lock.js`.
- **Three small, focused inserts** to `app.js` — all in non-overlapping regions:
  1. Click-handler bail at L1622 (existing reverse-geocode handler — likely untouched by nav/voice work)
  2. `window._appAPI` export (new ~10-line block at module top, near other globals)
  3. `initRuler()` call in bootstrap sequence (alongside other `init*()` calls)
- **One tab insert** to `index.html` — adds a 5th tab button + new panel skeleton; doesn't perturb existing tab DOM.
- **CSS additions** in `style.css` use the `.ruler-` prefix so there's no class-name collision with nav.

If a merge conflict surfaces in any of the 3 app.js insertion points, the resolution is straightforward: relocate the insert to a non-conflicting line; the inserts have no ordering dependencies on each other.

## Open questions for adversarial review

1. **Should we cancel in-flight elevation tile fetches** when the user starts dragging a vertex? (Otherwise stale samples could land in `state.elevationProfile` after the recompute is queued. Spec says recompute is on drag-end, so probably fine — but worth a flag.)
2. **Is z=12 the right sample zoom** for all coverage areas? (The Geographica elevation MBTiles cover z=0..14. Higher zooms have less coverage. Lower zooms may give imprecise gain/loss for short hikes.)
3. **Long-path performance:** is 50-tile cap right? Does the user really need an elevation profile for a 500-mile path, or should we degrade to "summary stats only" sooner?
4. **Touch drag responsiveness:** is the 200ms tap-vs-drag threshold right for gloved fingers in vehicles? (vs. 100ms / 300ms / pixel-only)
5. **Floating banner stacking:** does the ruler banner conflict with `#nav-banner` when nav is active? (Likely yes — the spec assumes nav-active and ruler-active are mutually exclusive in practice, but no enforcement.)
6. **iOS Safari fetch** of large numbers of PNG tiles: any throttling we should anticipate? (Mitigated by 8-concurrent + cache, but worth asking.)
7. **Should the vertex list be virtualized** for very long paths (50+ vertices)? Likely not for v1 since users won't realistically place that many — but Codex round may probe this.
8. **Are SVG-rendered vertex labels** (`ruler-vertex-labels` symbol layer) reliable on all MapLibre versions in use? Symbol layers require glyph configuration; we may need to provide a glyph font URL in the style.

## Scope estimate

Roughly 3–4 days of subagent-driven implementation work, broken into:
- Phase 0: scaffolding (new file, init wiring, `_appAPI` export, tab DOM)
- Phase 1: drawing state + state machine + map sources/layers
- Phase 2: vertex-centric edit (select / drag / delete / insert)
- Phase 3: elevation sampling + sparkline rendering
- Phase 4: edge cases, error paths, cleanup
- Phase 5: review loops + manual ship-gate validation

Detailed task breakdown will be produced by the writing-plans skill after the adversarial review.
