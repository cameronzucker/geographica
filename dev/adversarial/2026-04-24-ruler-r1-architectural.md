# Ruler spec — adversarial review R1: architectural / API soundness

**Reviewer:** Agent cholla, R1
**Spec under review:** `docs/superpowers/specs/2026-04-24-ruler-design.md`
**Lens:** Architectural / API soundness
**Date:** 2026-04-24

## Summary

The spec is well-structured and the IIFE module pattern is the right call.
However, there are **three CRITICAL architectural flaws** that will cause
the implementation to be wrong-out-of-the-gate or break under existing
codebase invariants:

1. The Terrain-RGB decode formula is for **Mapbox encoding** but the
   project's elevation tiles are **Terrarium encoding**. Decoded
   elevations will be off by ~32,000 meters across the entire map.
2. `formatNavDistance` lives in `nav-ui.js`, not `app.js` — so the
   proposed `_appAPI` export from app.js will fail to export it without
   cross-module hoisting that the spec doesn't describe.
3. `useImperial` is a closure-scoped `var` inside the app.js IIFE; the
   existing precedent (`navigation.js:1032`) is to expose it as a
   **live getter** that reads `window._geographicaUseImperial` at call
   time. Snapshot-on-init semantics — which the spec hints at by saying
   "explicit object" of values — would break unit-toggle live-updates.

There are also several MAJOR architectural concerns around state-machine
holes, init/bootstrap ordering, and DOM/CSS-class naming drift. The
data-shape "KMZ-serializable" claim mostly holds; the style-load reattach
pattern claim is loose-but-OK.

Net: the spec needs a focused revision pass on §A "Module layout & data
shape" and §E.3 "Elevation sampling" before plan-writing. The other
sections can be patched in-place from this review's recommended edits.

## Findings

### CRITICAL: Terrain-RGB decode formula is wrong for this codebase

**Spec lines:** §E.3 L181-184.

The spec uses the Mapbox Terrain-RGB decode:
```js
return -10000 + ((r * 65536 + g * 256 + b) * 0.1);   // meters
```

But the project's elevation tiles are **Terrarium-encoded** (Mapzen / AWS
Open Terrain Tiles). Evidence:

- `scripts/download_elevation.py:39` — pulls from
  `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`
- `scripts/download_elevation.py:241` — MBTiles description literally
  says "Terrarium encoding"
- `frontend/app.js:325, 334` — both `addSource` calls set
  `encoding: 'terrarium'`

The two formulas give **different absolute elevations**:

| Encoding | Formula | Sample (R=128, G=0, B=0) |
|---|---|---|
| Mapbox Terrain-RGB | `-10000 + (R*65536 + G*256 + B) * 0.1` | 828.8 m |
| Terrarium | `(R*256 + G + B/256) - 32768` | 0 m |

If shipped as written, every `elevation_m` value will be off by
~32,000 m (with sign and slope structure preserved, so gain/loss
might still look "directionally right" on a sparkline). The headline
**min / max** numbers in the stats grid will be visibly absurd
("min: -31,500 m, max: -30,200 m"). gain / loss will be the only
correct numbers (since they're diff-based and the constant offset
cancels), masking the bug if you only test those two metrics.

**Recommended fix:** Replace §E.3 decode block with:
```js
function elevationFromRGB(r, g, b) {
  // Mapzen / AWS Open Terrain "terrarium" encoding — matches
  // the encoding declared in app.js:325/334 and the source pipeline
  // at scripts/download_elevation.py:39.
  return ((r * 256) + g + (b / 256)) - 32768;
}
```

And add a sanity-check fixture to `test_terrain_rgb.js`: a sample tile
pixel from a known peak (e.g. South Mountain summit at known elevation
~810 m) decoded against this function should round to within ±5 m.
This catches "wrong formula picked from web search" regressions.

---

### CRITICAL: `formatNavDistance` lives in `nav-ui.js`, not `app.js`

**Spec lines:** §A L54 — "collect `useImperial`, `formatRouteDistance`,
`formatNavDistance`, `haversineDistance`, `formatDD` into an explicit
object" *exported by app.js*.

`grep -n "function formatNavDistance"` shows the function is defined at
`frontend/nav-ui.js:800`, not in app.js. Both modules are separate IIFEs —
nav-ui.js cannot reach a closure-scoped function in app.js, and vice
versa. The spec's `window._appAPI` export from app.js cannot include
`formatNavDistance` without one of:

a. Duplicating the function inside app.js (technical debt — two
   sources of truth for nav-distance formatting; a future tweak to one
   silently doesn't propagate to the other).

b. Pre-existing nav-ui.js exposing it on `window` (it doesn't —
   `grep -n "window.*formatNavDistance"` returns nothing across the
   frontend tree). Adding this export is a small extra change to
   nav-ui.js the spec doesn't list.

c. Ruler.js reading it from a separate `window._navAPI` (implies
   creating a second API surface, which somewhat defeats the
   "consolidate into one object" framing).

This is not a hypothetical — without resolving it, ruler.js cannot
implement the headline distance readout per the spec.

**Recommended fix:** Pick one of:
1. **Preferred:** ruler.js reuses `formatRouteDistance` only (it's in
   app.js; close enough semantically — both render meters in the user's
   unit system). Drop `formatNavDistance` from `_appAPI`. Document why
   in §E (formatNavDistance has feet/yards-vs-miles cutover at
   different threshold than route formatter; ruler matches the route
   panel's cutover, not nav UI's).
2. Add a second insertion point to the spec: "**Insertion 2b.** in
   `nav-ui.js`, expose `formatNavDistance` as
   `window._navAPI = { formatNavDistance }`. ruler.js then consumes
   from both `_appAPI` and `_navAPI`."
3. Refactor nav-ui.js's formatNavDistance into a shared
   `frontend/units.js` (largest change; cleanest result; out of scope
   for ruler v1).

This decision has a downstream test impact — `test_unit_format.js`
needs to stub whichever surface ends up exposing the formatter.

---

### CRITICAL: `useImperial` must be a live getter, not a snapshot

**Spec lines:** §A L54 — "collect `useImperial` ... into an explicit
object so ruler.js consumes them as an interface."

`useImperial` at `frontend/app.js:122` is a **module-scope `var` inside
the app.js IIFE**. It cannot be exposed as a value-on-an-object
snapshot without losing the live-update semantics, because:

- The user toggles units via `input[name="units"]` radios at
  `app.js:1086-1103`. The handler at L1089-1090 mutates `useImperial`
  AND the global mirror `window._geographicaUseImperial`.
- The existing precedent for cross-IIFE live consumption is
  `navigation.js:197-201`:
  ```js
  // Reads window._geographicaUseImperial at call time so live changes
  // are observed
  function _geographicaUseImperial() {
    return typeof window !== 'undefined'
      && window._geographicaUseImperial !== false;
  }
  ```
  And `navigation.js:1032` exposes it as a function: `_useImperial:
  _geographicaUseImperial`. **It is called, not read.**

If the spec is implemented literally as
`window._appAPI = { useImperial: useImperial, ... }` snapshotted at init
time, then a user who toggles imperial→metric AFTER the page loads but
BEFORE drawing a measurement will see the ruler render in the OPPOSITE
unit system from the rest of the app. Worse, a user who toggles units
WHILE a measurement is finished will see all readouts (and the
sparkline stats grid) freeze at the pre-toggle units until the
measurement is cleared and redrawn.

**Recommended fix:** Spec §A explicitly require `_appAPI` be a
**live-getter object**:
```js
window._appAPI = {
  useImperial: function () { return useImperial; },          // getter
  haversineDistance: haversineDistance,                       // pure fn
  formatRouteDistance: formatRouteDistance,                   // pure fn
  formatDD: formatDD,                                         // pure fn
  // formatNavDistance handled per the prior CRITICAL finding
};
```

And §A explicitly state: "ruler.js MUST call
`window._appAPI.useImperial()` at every render — never destructure
into a local. Match the navigation.js:1032 precedent." Add a unit-flip
re-render trigger: ruler.js must subscribe to the
`input[name="units"]` change event (or a synthesized
`geographica:units-changed` CustomEvent that app.js dispatches)
and call `renderPanel(state)` on flip. Without this, the cached
`state.totalDistance_m` is fine, but the rendered string isn't.

§F edge-case row addition: "**User toggles imperial / metric after
Finish:** total / per-segment / sparkline-stats all re-render in new
units; data-shape unchanged."

---

### MAJOR: State-machine table doesn't handle "Measure tab is the active tab on page load"

**Spec lines:** §B L84-103.

The state-machine table starts assuming `idle` is already the entry
state when the user lands on the Measure tab. But: the existing
codebase **persists last-active sidebar tab to localStorage** (key
`sidebar-last-tab`, restored at `app.js:4105-4118`). If a user closed
the page with Measure as the active tab, the next page load fires the
restored-tab click handler synchronously **before** the user has had a
chance to interact with the map.

What's the entry state? The spec implies `idle`, which is correct.
But:

a. Does the floating mode banner show? (Spec L146 says banner is
   "visible during drawing/inserting" — so no.) Good — but verify.

b. Is `init()` called on every page load even if Measure tab isn't
   active? Spec §A L42 says "called once during bootstrap." So yes.
   Then the sources / layers are pre-emitted on map style.load
   regardless. Correct, just confirm.

c. Crucially: what happens when the user clicks Layers tab → comes
   back to Measure tab? Per spec L97 "Sidebar tab switched away with
   <2 vertices" → idle. But what about with **0 vertices**? Spec
   doesn't say, but logically it should also → idle / stay-idle. OK,
   this is implied.

d. Tab restored on page load with the prior session's measurement
   gone (since spec is ephemeral per non-goals): user sees an empty
   Measure panel. Spec § doesn't render this state. Need an "empty
   state placeholder" in §C — tested by `test_panel_render.js` row 1
   ("Empty state placeholder") so the test exists, but the spec's §C
   sections list 6 sections that all conditionally render and none
   describe the bare-empty-Measure-tab state's prompt copy.

**Recommended fix:**

1. §B add row: `idle | drawing | First map tap **fires only when the
   Measure tab is currently active** — taps on map while another tab is
   active don't append vertices. Empty-map taps in those tabs continue
   to fire the existing reverse-geocode handler at app.js:1622.`
2. §C add Section 0 (above Mode banner): "**Empty state placeholder.**
   When `vertices.length === 0` AND `status === idle`: render
   `<p class="ruler-empty-prompt">Tap the map to start measuring.</p>`
   inside `#measure-panel`. This is the affordance the user sees when
   they switch to Measure tab on a fresh page."
3. §B add explicit sentinel: "If the page loads with Measure as the
   restored active tab, ruler is in `idle` state with `vertices = []`
   regardless of any prior session — there is NO restoration."

---

### MAJOR: `isActive()` boundary leaves "tap empty map during editing" misclassified

**Spec lines:** §B L99 and L103.

The spec carefully lists `editing | editing | tap empty map → falls
through to existing reverse-geocode handler`. And §B L103 nails the
intent: `isActive()` returns true only for `drawing` + `inserting`,
false for `idle` + `editing`.

But this leaves a real UX hole the spec doesn't address: **what does
the user expect when they tap an empty map area while editing a
measurement?** In every comparable tool (Google Earth, CalTopo,
Avenza), tapping empty map either does nothing or starts a fresh
measurement. The reverse-geocode popup at `app.js:1622` showing up
("Add as route point?") is contextually wrong for someone who's
mid-measurement-edit. They'll be confused.

This is a UX call (not strictly architectural) but the architectural
implication is whether `isActive()` should be true during `editing`
as well — at the cost of the user not being able to drop a route pin
without first explicitly clicking [Clear].

**Recommended fix:**
- Spec resolves the question explicitly. Recommended decision:
  `isActive()` returns true for `drawing` and `inserting` (as written),
  false for `idle` and `editing` — the user CAN use reverse-geocode
  while editing. Document the rationale in §B: "We don't trap
  reverse-geocode behind editing because (a) the editing UI is
  unambiguous (vertex circles visible, Clear button visible), (b) a
  user who wants to add a route pin from the same map view shouldn't
  have to clear their measurement first."
- BUT add an edge case to §F: "**Reverse-geocode popup opens during
  editing:** popup behaves normally; popup buttons trigger
  search/route flows that are orthogonal to ruler state. Closing or
  ignoring the popup leaves the measurement intact."

---

### MAJOR: Style-load reattach pattern doesn't match cited precedent

**Spec lines:** §D L153 — "Sources/layers re-emitted on
`map.on('style.load', ...)` matching the elevation-hillshade pattern at
app.js:319-348."

The cited precedent at `app.js:319-348` is **inside `addPlaceholderSources()`**
(a helper function), which is **called from a single central
`map.on('style.load', ...)` handler at `app.js:143`**. The pattern is:
"register all placeholder sources/layers in one helper, called centrally
on style.load."

Spec L153 phrasing implies ruler.js attaches its OWN
`map.on('style.load')` listener — an **additional** style.load handler
running parallel to the central one. That works, but:

1. Layer-ordering becomes ordering-dependent on listener fire order.
   The central handler at app.js:143 calls `addPlaceholderSources()`
   which calls `_enforceImageryOrder()` (app.js:281-289). If ruler.js
   emits its layers BEFORE the central handler fires, those layers
   get reshuffled when imagery layer order is enforced. If AFTER,
   ruler layers may end up below imagery layers (wrong — spec L128
   says "above all imagery").

2. `style.load` is fired once per `setStyle()` — so multiple
   listeners all fire. But MapLibre's listener-call order is
   insertion order. ruler.js's `init()` is called at bootstrap
   (app.js:4126ish if added next to `initImport`), AFTER `initMap()`
   at L4121 has registered the central style.load handler. So
   ruler's handler fires SECOND. Probably fine — but unspecified.

3. The "re-emit" pattern in the cited block is **idempotent
   (`if (!map.getSource(...)) addSource(...)`)**. Spec §D §D doesn't
   say ruler is idempotent — it says "added on `init`, mutated on
   state changes, removed on `clear`." On style swap, sources DO get
   destroyed (MapLibre wipes them on setStyle). If ruler's
   style.load handler re-emits unconditionally without
   `if (!map.getSource(...))`, that's still fine on first call (when
   map has no ruler sources). But race: if init() runs synchronously
   in bootstrap BEFORE the first `map.on('load')` fires, and the
   spec says ruler emits sources on `init`, and MapLibre throws on
   `addSource` before style load — there's a startup race.

**Recommended fix:**

§D rewrite L153-154:

> **Style-load reattach.** Define an idempotent helper
> `_emitRulerSourcesAndLayers()` inside ruler.js that does
> `if (!map.getSource('ruler-line-source')) addSource(...)` for each
> source, `if (!map.getLayer(...)) addLayer(...)` for each layer.
> Call it from `init()` AFTER awaiting `map.isStyleLoaded()` (or
> deferring via `map.once('load', _emitRulerSourcesAndLayers)`),
> AND register it as an additional `map.on('style.load',
> _emitRulerSourcesAndLayers)` for basemap-toggle / 3D-terrain
> reattach. This matches the *idempotent re-register* shape of
> `addPlaceholderSources` even though it lives in a separate
> handler.

§A clarify the bootstrap ordering: `initRuler()` is called in
`DOMContentLoaded` AFTER `initMap()`, with the actual source/layer
emit deferred until `map` is ready. Specifically the call shape is:

```js
// In app.js DOMContentLoaded (alongside initImport, initAdmin):
if (window._ruler && window._ruler.init) {
  window._ruler.init(map, window._appAPI);
}
// initImport() etc. follow normally.
```

And inside ruler.js `init()`:
```js
function init(map, appAPI) {
  if (initialized) return;       // duplicate-init guard
  initialized = true;
  _map = map; _appAPI = appAPI;
  if (map.isStyleLoaded()) _emitRulerSourcesAndLayers();
  else map.once('load', _emitRulerSourcesAndLayers);
  map.on('style.load', _emitRulerSourcesAndLayers);
  // ...wire DOM events, tab switch listener, etc.
}
```

---

### MAJOR: Missing teardown / re-init contract

**Spec lines:** §A L42-46 — `init`, `isActive`, `clear` only.

`clear` is described as "force-reset; called when Measure tab is left."
But the contract is incomplete:

- Is `clear()` idempotent? (Reasonable but unspecified.)
- After `clear()`, is the module still in `idle` and ready to draw
  again on next tap? (Implied by spec §B but not on the API surface.)
- Can `init()` be called twice? (Spec L42 says "called once" — but
  without guarding, hot-reload during development would double-bind
  listeners.) `voice-picker.js:3` has `if (window.VoicePicker) return`
  — ruler.js should match.
- Is there a `destroy()` for tear-down on hypothetical SPA route
  change? (For Geographica's MPA shape, no — but worth a "Non-goal"
  note so a future v2 doesn't have to retrofit.)
- Does `clear()` cancel in-flight AbortController for elevation
  fetches? (Spec §E.3 step 7 says yes — but the API surface should
  document it: `clear()` is "synchronous full reset including
  cancellation of in-flight elevation sampling.")

**Recommended fix:** §A expand the API documentation:

```js
window._ruler = {
  /**
   * Idempotent module init. Wires DOM + map event listeners,
   * registers placeholder map sources/layers, deferred until map
   * style is loaded. Subsequent calls are no-ops.
   * @param {maplibregl.Map} map  — the live map instance
   * @param {object} appAPI       — the live-getter _appAPI shim
   */
  init: function (map, appAPI) { ... },

  /**
   * @returns {boolean} true while the ruler is consuming map clicks
   *   for vertex placement (states `drawing` and `inserting`); false
   *   in `idle` and `editing` so the existing app.js click handler
   *   at L1622 fires.
   */
  isActive: function () { ... },

  /**
   * Force-reset to `idle`. Cancels any in-flight elevation tile
   * fetches via shared AbortController. Removes vertex markers
   * but leaves the placeholder map sources/layers in place
   * (re-emitted on next style.load). Idempotent — safe to call
   * from multiple unrelated paths (tab switch, page hide,
   * explicit Clear button).
   */
  clear: function () { ... },
};
```

And add an `if (window._ruler) return;` guard at the top of the IIFE
matching voice-picker.js's pattern.

---

### MAJOR: Symbol layer for vertex labels needs `text-font` declaration

**Spec lines:** §D L136 — `ruler-vertex-labels` symbol layer with
`text-field`, `text-size`, `text-offset`, `text-halo-*`, anchor.

**Missing:** `text-font` array. Without it, MapLibre falls back to its
default font stack — but the project's tileserver-served fonts at
`tileserver/fonts-served/` only have **Metropolis** and **Noto Sans**
variants. There's no Open Sans, no Arial. If MapLibre tries to fetch
`Open Sans Regular,Arial Unicode MS Regular/0-255.pbf`, the
tileserver returns 404, MapLibre logs a warning, and the labels render
as blank (or fall back further to the first symbol layer's font in
the basemap style — fragile).

**Recommended fix:** §D L130-136 table, add to `ruler-vertex-labels`
row's Style cell: `'text-font': ['Metropolis Regular', 'Noto Sans Regular']`
(matching the basemap styles' usage, e.g. `darkmatter/style.json:637`).

Open Question 8 ("Are SVG-rendered vertex labels reliable on all
MapLibre versions") thereby resolves to: **yes, as long as the
font-stack matches what the tileserver actually serves**. Spec already
serves `Metropolis Regular` from `tileserver/fonts-served/Metropolis Regular/`.

Cross-check this in the manual ship-gate: "[ ] Vertex labels V1, V2,
V3... visibly render on the map (not blank circles)."

---

### MAJOR: Bootstrap ordering — `initRuler()` must run after `initSidebarTabs()`

**Spec lines:** §A L55 — "`initRuler()` call in the bootstrap sequence
alongside `initImport()` / `initAdmin()`."

Looking at `app.js:4120-4133`:
```js
document.addEventListener('DOMContentLoaded', function () {
  initMap();
  initSidebarTabs();
  initLayerControls();
  initSearch();
  initRouting();
  initImport();
  initGPS();
  initAdmin();
  restoreLastSidebarTab();
  if (window.VoicePicker && ...) { window.VoicePicker.init(); }
  map.on('load', function () { ... });
});
```

`initSidebarTabs()` at L4122 registers the tab `.click` handlers. If
`initRuler()` runs BEFORE that, ruler.js's tab-switch listener (which
needs to know when Measure tab is left → fire `clear()` per spec §F)
attaches to a tab button that hasn't yet been wired by the central
handler — order-dependent and fragile.

`restoreLastSidebarTab()` at L4129 fires `targetTab.click()` to
restore the persisted-active tab. If Measure is the persisted tab and
`initRuler()` hasn't been called yet, the tab-switch event fires
before ruler is ready to handle it — ruler may miss the initial
"Measure tab activated" signal and stay in a weird sub-state.

**Recommended fix:** §A explicitly state ordering:

> `initRuler()` is called in `DOMContentLoaded` AFTER
> `initSidebarTabs()` AND BEFORE `restoreLastSidebarTab()`. This
> ensures (a) tab-switch listeners are wireable, and (b) ruler is
> initialized in time to participate in the persisted-tab restoration.
> Within the `initImport / initGPS / initAdmin` cluster, place
> `initRuler()` between `initAdmin()` and `restoreLastSidebarTab()`
> for chronological clarity.

Updated bootstrap:
```js
initImport();
initGPS();
initAdmin();
if (window._ruler && window._ruler.init) {
  window._ruler.init(map, window._appAPI);
}
restoreLastSidebarTab();
```

(`window._appAPI` itself must be assigned EARLIER in app.js — at
module top level, around the existing `window._geographicaUseImperial`
assignment at L123 — so it's available the moment any IIFE checks for
it.)

---

### MAJOR: Floating mode banner is described inside-vs-outside sidebar — pick one

**Spec lines:** §C L107-108 (sidebar mode banner) and §D L146 (floating
map-overlay banner). Spec says "Inline within the panel; the floating
map-overlay banner is a separate element (§D)." So there are TWO
banners — one inside the sidebar, one floating over the map.

Architectural concerns:

1. Is this two DOM nodes that say the same thing? (Yes — implicitly.
   That's fine but is it intentional?)
2. Spec §F edge case "Sidebar tab switched away during
   drawing/inserting" → editing: the inline-sidebar banner is hidden
   (it's inside `#measure-panel` which gets `.hidden`-ish by tab
   switching). What about the floating banner? It should also hide
   per "→ editing" or "→ idle". §D L146 says "Visible during drawing
   / inserting" — but that's the state predicate, fine.
3. Open Question 5 ("does the ruler banner conflict with `#nav-banner`
   when nav is active?") — `#nav-banner` is INSIDE the
   `#nav-instruction-card` (per `index.html:342`), not at the top of
   the map. So they don't COLLIDE physically. But they conflict
   **semantically** — if a user starts a measurement during
   navigation, both UIs are active. The spec's implicit answer is
   "users won't do this" but doesn't enforce.

**Recommended fix:**

- §C clarify "the inline sidebar banner mirrors the floating banner's
  visibility state. Both render via `renderPanel(state)`'s same
  branch."
- §B add transition: `any | idle | nav-active class added to body
  while ruler is in drawing/inserting` (debatable — but at minimum,
  document the decision).
  - **Recommended decision:** during `body.nav-active`, ruler can
    enter / continue in any state, BUT the floating mode-banner is
    moved 40 px lower in CSS (or hidden, with the inline-sidebar
    banner left as the only mode-indicator). Reason: nav has its own
    top-of-screen UI that's higher priority for safety reasons; ruler
    isn't useful enough to compete.
  - Resolves Open Question 5 with a concrete CSS-positioning
    contract instead of "assume mutually exclusive."
- §F edge case row: "**Ruler activated during nav-active:** ruler
  works; floating mode banner offset to `top: 64px` instead of
  `top: 12px` (matches `#nav-status-bar` / `#nav-banner` real-estate).
  CSS rule: `body.nav-active #ruler-mode-banner { top: 64px; }`."

---

### MAJOR: index.html panel class naming drift

**Spec lines:** §A L51 — "`<div id="measure-panel" class="sidebar-panel hidden">…</div>`".

**Actual codebase:** existing panels use `class="panel"` (active panel
also has `.active`). E.g.
- `index.html:53`: `<div id="layers-panel" class="panel active">`
- `index.html:171`: `<div id="route-panel" class="panel">`
- `index.html:228`: `<div id="import-panel" class="panel">`
- `index.html:243`: `<div id="admin-panel" class="panel">`

The CSS at `style.css` (and the tab-switching code at
`app.js:1158-1160`) uses the `.panel` and `.active` classes. The spec's
proposed `class="sidebar-panel hidden"` would be invisible regardless
of state because no CSS rule targets `.sidebar-panel`, and `.hidden`
would override any active state.

**Recommended fix:** §A L51 — `<div id="measure-panel" class="panel">…</div>`
(no `active` since Measure is not the default tab; no `hidden` —
visibility is controlled by the standard tab handler's
add/remove-`.active` logic).

Update §B references accordingly: when the spec describes "Measure
tab activated → renderPanel runs", the underlying mechanism is
"existing tab-handler at `app.js:1152-1163` adds `.active` to
`#measure-panel`". Ruler's panel doesn't need bespoke visibility CSS.

---

### MINOR: `formatDD` signature in spec doesn't match codebase

**Spec line:** §E.4 L200 — "Reuse `formatDD(value, 'NS' | 'EW')`".

Actual definition at `app.js:3486`:
```js
function formatDD(value, dirs) { ... }
```

Where `dirs` is the string `"NS"` or `"EW"`. Spec is correct but
notation `'NS' | 'EW'` is TypeScript-ish; non-blocking.

**Recommended fix:** none — call it out in this review as
already-correct, contract intact.

---

### MINOR: `state.totalDistance_m` derivation invariant

**Spec lines:** §A L74-77.

The data shape lists `segments`, `totalDistance_m`, and
`elevationProfile` as "Cached/computed; recomputed on any mutation."
But there's no **invariant** stated: e.g. "`totalDistance_m === sum of
segments[*].distance_m` always." Without explicit invariant, future
mutators could update one but not the other.

**Recommended fix:** Add a sentence to §A: "**Invariants:** (1)
`totalDistance_m === segments.reduce((s, x) => s + x.distance_m, 0)`
to within floating-point error. (2) `segments.length ===
max(0, vertices.length - 1)`. (3) When `selectedVertex !== null`,
`0 <= selectedVertex < vertices.length`. (4) `insertSlot.before`,
when populated, satisfies `0 <= insertSlot.before <= vertices.length`.
A single helper `_recompute(state)` is the only path that mutates
segments / totalDistance_m / elevationProfile — all state changes that
mutate vertices MUST call it before notifying the renderer."

This is a small spec addition that cleanly maps to a single
test row in `test_state_machine.js`: "after every transition, all
four invariants hold."

---

### MINOR: KMZ-serializability claim — the data shape works, but explicit test missing

**Spec lines:** §A L58 ("KMZ-serializable, no DOM/MapLibre refs"), §A
L80 ("A separate (NOT serialized) view-state object holds map-marker
handles, listener-cleanup callbacks, and DOM nodes").

Inspection of the canonical state (vertices, segments, totalDistance_m,
elevationProfile, status, selectedVertex, insertSlot) shows it's
JSON-serializable. The non-data view-state is properly siloed in the
spec. Good.

But there's no test asserting this. A future contributor adding a
DOM-ref or MapLibre-ref into `state` would silently break the
KMZ-export path planned for the future *My Places* cycle.

**Recommended fix:** Add a test row to "Unit tests — `frontend/tests/ruler/`":

| File | Coverage |
|---|---|
| `test_state_serialization.js` | `JSON.stringify(state)` succeeds without throwing; `JSON.parse(JSON.stringify(state))` produces a deep-equal object. Run after 5-vertex draw + 1 insert + 1 delete + 1 drag — exercises every mutation path. |

This is a regression-trap that makes the My Places integration spec
write itself.

---

### MINOR: Tap-vs-drag ergonomics: 200ms is reasonable, 5px is borderline tight

**Spec lines:** §D L144 — "5 px AND 200 ms = tap."

5 px on a touchscreen with HiDPI scaling is **less than 1 mm** of
finger jitter. Field testers wearing gloves or in a moving vehicle may
exceed that during a "tap." Open Question 4 asks this directly and
suggests 100/200/300 ms but only varies the time threshold.

**Recommended fix:** make Open Question 4 more concrete. Recommended
default: 8 px AND 250 ms for touch, 5 px AND 200 ms for mouse — most
consumer mapping libs (Leaflet, MapLibre) use 5-10 px for desktop,
10-15 px for touch. Codify the difference and surface as a
`TAP_THRESHOLDS = { mouseDxPx: 5, mouseMs: 200, touchDxPx: 10, touchMs: 250 }`
constant block at the top of ruler.js. Touchscreen users will still
sometimes drag-when-they-meant-to-tap, but the floor is much higher
than 5 px.

---

## Open Questions Resolved by This Review

| # | Question | Lens applies | Resolution |
|---|---|---|---|
| 1 | Cancel in-flight tile fetches when drag starts | Yes — touches AbortController architecture | **Yes, cancel.** A drag is a state mutation. Per the proposed `_recompute(state)` invariant rule above, any mutation aborts the in-flight controller and starts a new sampling run on `mouseup`. Spec § E.3 step 7 already mostly says this; make it explicit for drag-start. |
| 2 | z=12 right for all coverage areas | Partial — data-shape question | Pass — primarily a data-coverage question for R3/R4. From an architecture perspective, z=12 is fine and the spec correctly captures the rationale; recommend the sampling-zoom be a single `SAMPLE_ZOOM = 12` constant at top of ruler.js so future tuning is one-line. |
| 3 | 50-tile cap right for long paths | Pass — UX/perf question for R2 (concurrency) or R4 (perf) |
| 4 | Touch tap-vs-drag threshold | Yes — see MINOR finding above | Resolved per the MINOR finding: 8 px / 250 ms touch, 5 px / 200 ms mouse, surfaced as constants. |
| 5 | Floating banner stacking with #nav-banner | Yes — see MAJOR finding above | Resolved: `body.nav-active` adds `top: 64px` offset to `#ruler-mode-banner`. Both UIs can be active without colliding. |
| 6 | iOS Safari fetch throttling | Pass — mobile/perf for R2 or R3 |
| 7 | Vertex list virtualization | Partial — purely architectural would say "DOM-render up to N=50 inline; if N>50, switch to virtualized list. But N>50 is a Non-goal so just cap at N=50 and document." | Resolved: spec § Non-goals add: "Measurements with >50 vertices. Vertex-list rows are direct DOM elements (no virtualization). Beyond ~50 vertices the panel scroll performance degrades; users planning a 50+ vertex path should split into multiple measurements." |
| 8 | Symbol-layer glyphs reliability | Yes — see MAJOR finding above | Resolved: works as long as `text-font` array is `['Metropolis Regular', 'Noto Sans Regular']` to match the project's served fonts at `tileserver/fonts-served/`. |

## Recommended Spec Changes

In priority order:

1. **§E.3 L181-184** — replace Mapbox decode with Terrarium decode (CRITICAL #1).
2. **§A L54** — fix `_appAPI` shape: drop `formatNavDistance` OR add nav-ui.js export
   point as a 4th insertion to the spec; make `useImperial` a getter (CRITICAL #2 + #3).
3. **§A L42-46** — expand API doc with idempotency, AbortController-cancellation
   contract on `clear()`, and bootstrap-ordering note (MAJOR teardown,
   bootstrap ordering).
4. **§A L51** — change `class="sidebar-panel hidden"` to `class="panel"`
   (MAJOR class drift).
5. **§D L130-136** — add `text-font` to the `ruler-vertex-labels` row
   (MAJOR symbol layer).
6. **§D L153** — rewrite reattach-pattern paragraph with idempotent
   helper + style.load registration shape (MAJOR style-load reattach).
7. **§B add 1-2 transition rows** for "Measure tab restored from prior
   session" and "First map tap requires Measure tab active" (MAJOR
   state machine entry).
8. **§B add explicit Open Question 5 resolution** + §F edge-case row
   for nav-active + ruler-active coexistence (MAJOR floating banner).
9. **§A append "Invariants" subsection** under data shape (MINOR
   invariant).
10. **Testing strategy table append** `test_state_serialization.js` row
    (MINOR KMZ-claim test).
11. **§D L144** — make tap-vs-drag thresholds touch/mouse-aware
    constants (MINOR ergonomics).
12. **Open Question 7 → §Non-goals** — explicitly cap at 50 vertices
    (MINOR).

The first 5 items materially affect what the implementer would
produce. Items 6-8 prevent UX or runtime bugs that won't surface in
unit tests but will in production. Items 9-12 are clean-up that
makes the spec more maintainable and the test suite more thorough.
