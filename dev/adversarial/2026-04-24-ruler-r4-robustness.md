# Ruler spec — adversarial round 4: robustness / failure modes / testing gaps

**Reviewer:** agent `cholla`
**Date:** 2026-04-24
**Lens:** robustness, failure modes, edge case enumeration, test coverage realism
**Spec under review:** `docs/superpowers/specs/2026-04-24-ruler-design.md` (v1, commit `a0afd36`)
**Status:** spec is structurally sound but contains **two ship-blockers grounded in actual codebase facts** (wrong elevation decode formula; broken `useImperial` snapshot capture), plus a long tail of major edge-case omissions. Plan-writing should not proceed until C1 and C2 are resolved in the spec.

---

## Summary

- **2 CRITICAL** — would ship a broken feature on day one. Both grounded in greppable codebase facts, not theory.
  - **C1:** Spec's `elevationFromRGB` decode formula is for **Mapbox Terrain-RGB**, but the existing tiles are **Terrarium-encoded** (verified: `app.js:325` `encoding: 'terrarium'`; `download_elevation.py:39` source URL). Every elevation readout would be off by ~10000m baseline + scale factor. Sparkline numbers would be nonsense.
  - **C2:** Spec collects `useImperial` into `window._appAPI` as a value, but `useImperial` is a **closure-captured `var`** at `app.js:122` mutated by the toggle handler at `app.js:1089`. A snapshot copied into `_appAPI` at init time will be stale forever. Ruler would show miles even after the user flipped to metric.
- **8 MAJOR** — meaningful UX degradation, false-passing tests, or under-tested surface area.
- **6 MINOR** — nits, naming drift, missing entries.
- **3 open questions** that the spec should answer before plan-writing, otherwise the plan author has to make these calls under-informed.

The edge case table at §F has 14 entries; this review surfaces ~25 additional cases the spec misses, several of which produce silent wrong-output rather than visible errors. The §"Testing strategy" section names 6 unit + 3 integration tests but leaves three high-value paths uncovered: the elevation-decode contract under Terrarium, the `_appAPI` cross-tab unit-toggle propagation, and the layer-stacking interaction with KMZ pin click handlers.

---

## Findings

### CRITICAL

#### C1 — Elevation decode formula targets the wrong tile encoding (CONFIRMED IN CODEBASE)

**Severity:** CRITICAL — would ship a feature whose entire elevation readout is numerically wrong.

**Spec location:** §E.3, lines 180-184.

```js
function elevationFromRGB(r, g, b) {
  return -10000 + ((r * 65536 + g * 256 + b) * 0.1);  // meters
}
```

This is the **Mapbox Terrain-RGB** decoder. But the actual tiles in `/srv/geographica/data/elevation.mbtiles` are **Terrarium-encoded** (Mapzen / Terrain Tiles AWS Open Data format). Two independent confirmations:

- `frontend/app.js:325` and `:334` both declare `encoding: 'terrarium'` on the elevation sources.
- `scripts/download_elevation.py:39` sources tiles from `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png` and `:238` registers the metadata as `("name", "elevation_terrarium")`.

The Terrarium decode is:
```js
function elevationFromRGB(r, g, b) {
  return (r * 256 + g + b / 256) - 32768;  // meters
}
```

Applied to a real CONUS pixel at ~1500m elevation:
- Terrarium-correct: ~1500m
- Spec's formula: ~10460m + (pixel-specific delta) — wrong by an order of magnitude

Min/max/gain/loss would all be wildly wrong. Beta testers would notice within their first measurement.

**Why the spec went off the rails:** Mapbox Terrain-RGB is the canonical "raster DEM with PNG encoding" reference and is a copy-paste hazard. The spec author appears to have inserted the Mapbox formula without verifying the dataset.

**Required spec fix:**
1. Replace the decode formula with the Terrarium variant.
2. Add `test_terrain_decode.js` (rename from `test_terrain_rgb.js`) that asserts `elevationFromRGB(0, 128, 0) === -32512` (sentinel low), `elevationFromRGB(128, 0, 0) === 0` (sea level), and `elevationFromRGB(135, 79, 192) === 1871.75` (an actual CONUS-mountain pixel — pick a real one from a downloaded tile and freeze it).
3. Add a comment in ruler.js linking to `app.js:325` so future maintainers see the contract: "elevation tiles are Terrarium per the source declaration; if `encoding:` ever changes, update this decoder in lockstep."
4. Cross-reference in implementation-pitfalls.md: add "§16 Terrain-RGB vs Terrarium are not interchangeable; Geographica uses Terrarium."

#### C2 — `useImperial` is a closure variable, not a module-scoped global; copying it into `_appAPI` produces a permanent stale snapshot (CONFIRMED IN CODEBASE)

**Severity:** CRITICAL — feature ships looking-correct on first load and silently desyncing thereafter.

**Spec location:** §A, line 54: "collect `useImperial`, `formatRouteDistance`, `formatNavDistance`, `haversineDistance`, `formatDD` into an explicit object."

**Codebase reality** (`app.js:122`, `:1089`):
```js
// L122 — inside the IIFE that wraps app.js
var useImperial = true;

// L1089 — inside the unit-radio change handler
useImperial = (this.value === 'imperial');
window._geographicaUseImperial = useImperial;
```

`useImperial` is a `var` captured by the surrounding IIFE closure. The toggle handler reassigns the closure-local variable *and* mirrors it onto `window._geographicaUseImperial` (added by recent commit `7bad09c` for nav). If `_appAPI` is built as `{ useImperial: useImperial, ... }` once at bootstrap, ruler reads a frozen `true` forever.

The spec's open-question #1 hand-waves at unit-flip propagation ("`useImperial` flips, the spec says ruler readouts re-render"), but the actual *mechanism* isn't specified, and the obvious mechanism (object literal) is broken.

**Required spec fix — pick one:**

1. **Getter pattern (least intrusive):**
   ```js
   window._appAPI = {
     get useImperial() { return useImperial; },
     formatRouteDistance: formatRouteDistance,
     // ...
   };
   ```
2. **Use the existing `window._geographicaUseImperial` mirror.** Already lives, already tested by nav. Ruler reads `window._geographicaUseImperial` directly and skips the `useImperial` field on `_appAPI`.
3. **CustomEvent broadcast.** Existing `units` radio handler dispatches `geographica:units-changed`; ruler subscribes and re-renders. More explicit than a getter; matches the existing `geographica:sidebar` event pattern at `app.js:1186`.

**Required test:** `test_unit_format.js` must spin a JSDOM instance, toggle the `units` radio, and assert that the ruler readout text changes from "12.3 mi" to "19.8 km" *without* a panel re-mount. The spec lists this test but doesn't say what it asserts; without an explicit re-render mechanism, the test would either pass-by-accident (full re-mount) or fail silently (mock that bypasses the closure issue).

**Cross-reference:** This is exactly the kind of bug that testing-pitfalls.md §11 ("Duplicated logic across modules") catches. If both nav and ruler each hold their own copy of `useImperial`, they'll drift. Single source of truth = `window._geographicaUseImperial` (or a getter that proxies it).

---

### MAJOR

#### M1 — Layer-specific click handlers are NOT suppressed by the L1622 bail; KMZ-pin and search-pin clicks during `drawing` mode produce double-fires

**Severity:** MAJOR — direct UX bug, easy to reproduce.

**Spec location:** §B "The critical isActive() boundary" (line 103) and §A.2.1 (line 53). Both describe a single-point bail at `app.js:1622`.

**Codebase reality:** there are **at least 3 click handlers** that fire on map taps, only one of which is the L1622 generic handler:

- `app.js:660` — `map.on('click', layerId, ...)` for each of `imported-points`, `imported-lines`, `imported-polygons`, `imported-polygon-outlines`. These open KMZ feature popups.
- `app.js:1272` — `map.on('click', 'search-result-circles', ...)` for search-result pins.
- `app.js:1622` — generic `map.on('click', ...)` for reverse-geocode popup.

In MapLibre, layer-specific handlers fire *in addition to* the generic handler when a feature is at the click point — the generic handler suppresses itself via `queryRenderedFeatures` (L1628-1632), but the layer-specific handlers run unconditionally.

Concrete failure: user has a KMZ track loaded with pins. They open Measure tab. They tap on an imported point. Result: KMZ popup opens AND a vertex is placed at that pin's lng/lat. Double-fire, exactly the kind of "what's happening?" UX the spec is trying to avoid.

**Required spec fix:** the suppression must be applied at every click handler that could conflict, not just L1622. Cleanest approach: a top-level `map.on('click', function(e) { if (window._ruler.isActive()) e.preventDefault(); /* or stop propagation */ })` registered with capture-phase priority. But MapLibre's event model doesn't support standard DOM capture; the right pattern is for each layer handler to consult `window._ruler.isActive()` — meaning **3 additional insertion points in app.js**, not 1. Spec needs to enumerate them.

Alternatively, ruler could install its own layer ABOVE the imported/search layers and *capture* the click before MapLibre dispatches to them. But MapLibre dispatches to all layers under the click point; layer ordering doesn't help.

**Coordination implication:** §"Coordination with parallel agents" claims "3 small, focused inserts" to app.js. Reality is 3 (suppression points) + `_appAPI` export + `initRuler()` call = **5+ inserts**. Spec should be honest about this so merge-conflict surface is correctly assessed.

#### M2 — `restoreLastSidebarTab()` whitelist will silently swallow Measure tab persistence

**Severity:** MAJOR — feature works but loses tab-persistence guarantee that other panels have.

**Spec location:** §F edge case row "Sidebar tab switched away during drawing/inserting" (treats as Cancel) — but no edge case for "user's last session was on Measure, reload, did the tab restore?"

**Codebase reality** (`app.js:4103`):
```js
var VALID_SIDEBAR_PANELS = ['layers-panel', 'route-panel', 'import-panel', 'admin-panel'];
```

This is a hardcoded whitelist. If a user's last action is opening Measure and then reloading the page, `restoreLastSidebarTab()` would silently fall through to default (Layers) because `'measure-panel'` isn't whitelisted.

**Required spec fix:** add `'measure-panel'` to the whitelist as a 6th insertion point in app.js. Add a manual checklist row: "Open Measure tab, place 2 vertices, reload page → returns to Measure tab (panel empty per ephemeral non-goal, but tab is correct)."

#### M3 — Concurrent state mutations during in-flight elevation sampling: race surface is wider than spec acknowledges

**Severity:** MAJOR — `clear()` correctness is load-bearing for §F; current spec covers tile-fetch abort but not all the queue states.

**Spec location:** §E.3.7 — "all fetches share a single `AbortController`...generation counter before mutating `state.elevationProfile`."

**Race surface the spec addresses (3):** `clear()` mid-fetch; state-mutation supersedes; generation-counter check before mutation.

**Race surface the spec does NOT address (5+):**

1. **Drag-mouseup recompute fires WHILE prior recompute is mid-decode.** Spec says recompute on `mouseup`; spec also says in-flight pixel-decode work checks generation counter. But canvas `drawImage` + `getImageData` are *synchronous and CPU-blocking*. Two consecutive drags 100ms apart could queue 2 sampling runs; if the first decode is mid-loop when the second mouseup fires, the new generation counter increments but the first decode keeps running and eventually returns. Generation check at the END of the decode is fine, but the spec doesn't say *where* in the decode the check happens.

2. **`clear()` during drag-mouseup pending.** User starts dragging V2; `mousedown` captures vertex. Hardware glitch / OS event drop / user releases off-canvas — `mouseup` event never fires. User clicks `[Clear]`. State resets. User starts new measurement. Now original drag's `mouseup` finally arrives (queued in browser somehow, or user reactivates window). Mutates `state.vertices[2]` of the new measurement. Spec doesn't address detached drag state.

3. **Style-load reattach DURING in-flight elevation fetch.** User starts measurement, hits Finish, sampling kicks off. Mid-sampling, user toggles 3D terrain or basemap. `style.load` fires; spec says sources/layers re-emit. Does the in-flight elevation request complete and update sparkline? The new style might not have rendered yet. Generation counter likely covers this but the spec doesn't say `style.load` increments the generation.

4. **Two parallel drag attempts (multitouch).** User has two fingers on the map. First finger touchstart on V2. Second finger touchstart on V3. Both enter "dragging-vertex" sub-state simultaneously. Spec's drag handling assumes single drag (capture vertex index → update on move → recompute on end). Two pointers competing for the same `state.vertices` slot: pinch-zoom canceling, broken vertex positions, possible duplicate insertions.

5. **Tab-switch-away during inserting.** Spec says "treat as Cancel" but doesn't say what happens to a click-event that's mid-flight (`mousedown` fired, sidebar tab clicked before `mouseup`). The vertex commit might happen after the state has already transitioned to `editing` from the tab switch. Out-of-order events.

**Required spec fix:** explicit table of guaranteed invariants:
- Drag sub-state CLEARED on any state transition (covers detached mouseup and tab-switch).
- Generation counter incremented on: `clear()`, every `mouseup`, every state transition, `style.load`, every `clear()`-equivalent (Esc, tab-switch).
- Multitouch on vertex layer → first touch wins, subsequent touch IGNORED until first ends.
- Click-event in-flight during state transition → `mouseup` after transition is no-op.

**Manual checklist additions:**
- "Drag V2, release outside the canvas (off the right edge of viewport) → vertex returns to original position OR commits at last `mousemove` lng/lat (specify which); state machine returns to `editing`."
- "Two fingers simultaneously on V2 and V3 → pick first-down winner; second is ignored, no state corruption."

#### M4 — Tap-vs-drag threshold (5 px AND 200 ms) is fragile under realistic conditions

**Severity:** MAJOR — flaky tests; likely to misclassify actual user inputs.

**Spec location:** §D, line 144.

Issues:
- **5 px on a hi-DPI touch device is ~0.7mm of skin movement.** Gloved users in vehicles (the AREDN field-ops audience!) routinely produce 8-15 px of jitter on a clean tap. Their taps will register as drags, vertex won't select. This is mentioned obliquely in spec §"Open questions" #4 but no resolution offered.
- **200 ms is on the edge of double-click detection range.** Browsers fire `dblclick` on two `click`s within ~500 ms. If user does a sub-200ms tap-then-tap (common when retrying after a missed select), the second event might be a synthetic `dblclick` rather than a `click`, and the spec doesn't say what handles `dblclick` in `editing` state. (`drawing` uses dblclick to finish — what does dblclick do in `editing`?)
- **Threshold is symmetric for mouse and touch but should not be.** Mouse: 5px / 200ms is fine. Touch (especially gloved): probably 12 px / 250 ms. iOS Safari already coalesces fast taps via touch-event normalization; thresholds need to be touch-aware.

**Required spec fix:**
- Specify separate thresholds: `MOUSE_TAP_PX = 5, MOUSE_TAP_MS = 200, TOUCH_TAP_PX = 12, TOUCH_TAP_MS = 250` (numbers cited as starting points; final values from manual checklist).
- Specify `dblclick` behavior in every state, not just `drawing`.
- Test: `test_drag_disambiguation.js` — fire `mousedown` then `mouseup` at thresholds (4px/199ms = tap; 5px/200ms = boundary → specify which side wins; 6px/201ms = drag). 4 boundary cases + 4 mid-region cases.

#### M5 — Test environment doesn't exercise the canvas pixel-decode path; regression risk is real

**Severity:** MAJOR — exactly the JSDOM-doesn't-cover-real-rendering pitfall called out in `testing-pitfalls.md`.

**Spec location:** §"Testing strategy" — "JSDOM doesn't fully exercise touch; manual checklist is the explicit gap-closer."

Realistic regression risk: future PR refactors `elevationFromRGB` (e.g., adds bounds checks for malformed PNG bytes), introduces an off-by-one. JSDOM tests pass because they unit-test the decode formula in isolation with known inputs. Manual checklist isn't a regression gate — it's a release gate. PRs ship freely without exercising the path.

The JSDOM tests can't:
- Fetch a real elevation tile and decode it (no canvas pixel access).
- Verify the in-canvas `drawImage` → `getImageData` round-trip (JSDOM stubs `getContext('2d')` to a no-op).
- Catch CORS misconfigs (same-origin claim is empty in JSDOM).

**Required spec fix:**
1. Add a Node-side test that decodes a real PNG using `pngjs` or similar (npm install for tests only — already pattern in use; check `frontend/tests/voice-picker/_fixtures.js`). Fixture: 3 captured tiles (sea-level, 1500m mountain, NULL/transparent edge). Asserts: decode produces expected elevations within tolerance.
2. Add a `test_canvas_decode_fallback.js` that mocks `Image` to fire `error` instead of `load` and asserts the sample becomes `null`.
3. Document explicitly in spec §"Testing strategy": "JSDOM does NOT exercise the elevation pipeline end-to-end. The PNG-decode test (using pngjs) is the regression gate; the manual checklist is the deployment gate. Do not delete or skip the PNG-decode test."

#### M6 — `formatDD` precision claim contradicts code; spec writes `33.4500°N` but the function produces `33.45000° N`

**Severity:** MAJOR — implementation will diverge from spec.

**Spec location:** §A canonical state object (lines 66, 200) — "4-decimal precision = ~11 m at CONUS latitudes."

**Codebase reality** (`app.js:3489`): `return abs.toFixed(5) + '° ' + dir;`

Two divergences:
- 5 decimals, not 4 (~1.1 m at CONUS, not 11 m).
- A space between digit and degree sign (`° ` not `°`).
- A space between value and direction (`° N` not `°N`).

These are minor visually but the spec uses `33.4500°N` as the canonical example, which would not match what users see. Implementer following spec verbatim might either:
- Re-implement formatDD with 4-decimals (defeats the "reuse formatDD" promise; introduces a 2nd format).
- Use the existing 5-decimal formatDD and quietly produce different output than spec.
- Add a custom formatter that splits the difference.

**Required spec fix:** match codebase. State `33.45067° N, 112.07000° W` (5 decimals, with spaces). Adjust the §F edge case row "Single vertex placed" if it shows the format. Add test: `test_coordinate_format.js` asserts ruler-formatted output equals `formatDD(...)` output exactly.

#### M7 — Banner-stacking with `#nav-banner` is hand-waved; rule needs to be explicit

**Severity:** MAJOR — visual collision is high-probability.

**Spec location:** §"Open questions" #5: "the spec assumes nav-active and ruler-active are mutually exclusive in practice, but no enforcement."

In practice, *they are not mutually exclusive*. User can be navigating to a destination AND want to measure how far is the next dirt road from the highway. Both are top-of-screen, semi-transparent, no z-index defined in spec.

Beyond stacking, the visibility rule itself is fragile: if user enters Measure, draws 3 vertices, switches to nav-active mode by tapping a search result and hitting "Navigate", what happens to ruler banner? Spec doesn't say.

**Required spec fix:** explicit rule.
- Suggested: "If `document.body.classList.contains('nav-active')` is true, ruler floating banner uses a **bottom** anchor instead of top." OR "ruler banner explicitly stacks BELOW nav banner with `top: 56px` (height of nav banner + 8px gap); both visible."
- Test: `test_banner_stacking.js` — set body class `nav-active`, init ruler, enter `drawing`, assert banner element doesn't overlap nav banner per `getBoundingClientRect`.
- Manual checklist: "Start navigation, then open Measure tab, then start drawing → both banners visible, no visual overlap."

#### M8 — `test_mode_flag.js` is mock-based; no test proves the ACTUAL `app.js:1622` handler bails

**Severity:** MAJOR — the entire integration boundary the spec rests on is untested.

**Spec location:** §"Testing strategy" / Integration tests / `test_mode_flag.js` — "mock app.js handler is suppressed during drawing/inserting."

The spec's mode-flag bail at `app.js:1622` is the load-bearing mechanism for the entire feature. A mock-based test asserts only that "if a fake handler that calls `_ruler.isActive()` first behaves correctly, ruler suppresses appropriately." It does NOT prove that the *real* handler at `app.js:1622` actually contains the bail call.

A future PR could refactor the handler, drop the bail line, and 100% of tests still pass.

**Required spec fix:**
1. Add a test that runs the real `app.js` source through JSDOM-vm (matching the pattern in `frontend/tests/voice-picker/cross-tab-sync.test.mjs:11` — `fs.readFileSync(... 'app.js')` + `vm.runInContext`). Asserts that the click handler at L1622-ish *contains a syntactic check* for `window._ruler.isActive()` — either by string-match or by parsing the function body into AST.
2. Alternatively, add a grep-based enforcement test (matching the pattern at recent commit `b8a76a1` `test(overview): grep-based enforcement — no raw tile writes outside wrappers`):
   ```js
   const APP_JS = fs.readFileSync(path.join(__dirname, '../../app.js'), 'utf-8');
   test('app.js click handler bails when ruler is active', () => {
     // Match the click handler's first ~5 statements
     const m = APP_JS.match(/map\.on\('click', function \(e\) \{[\s\S]{0,200}?_ruler/);
     assert(m, 'click handler missing _ruler.isActive() bail');
   });
   ```
3. ALSO verify the same for `imported-points` and `search-result-circles` handlers per M1.

---

### MINOR

#### MIN1 — Test file naming convention drift

Existing tests use `<topic>.test.mjs` (voice-picker) or `<topic>.test.js` (wake-lock). Spec uses `test_<topic>.js` (Python-style). Drift; not a bug. Pick one. Codebase pattern is `<topic>.test.mjs`; spec should use it.

#### MIN2 — `test_terrain_rgb.js` filename misleading

Per C1, the tile encoding is Terrarium not Terrain-RGB. File should be `test_terrain_decode.js` or `terrain-decode.test.mjs` to match the actual data format.

#### MIN3 — `samplePath` "divide-by-zero protection" mentioned in test list but not in spec body

§"Testing strategy" lists `test_sample_path.js` covering "divide-by-zero protection" but §E.3 doesn't describe what divide-by-zero edge case exists. Likely: total path length 0 (two duplicate vertices). Spec should either describe the edge case or remove the test row.

#### MIN4 — Sparkline coverage-gap rendering edge case missing

What happens if FIRST sample has elevation but SECOND is null? Path starts with a coverage gap. Or LAST sample is null? Sparkline tail is dashed. These render-edge cases are easy to break and not explicit in spec or tests.

#### MIN5 — Backspace handler scope

§F row "Backspace pressed in a text input" — spec says check `e.target.tagName !== 'INPUT' && !== 'TEXTAREA'`. But `contenteditable` divs (used by some MapLibre popups for editable text) won't be caught. Also, the navigation search bar at `#search-container` uses an `<input>` — already caught — but also: are there hidden inputs like the address-search field that should suppress?

Better pattern: `e.target.matches('input, textarea, [contenteditable=true], select')`.

#### MIN6 — Pitfalls cross-reference is sparse

§"Pitfalls cross-reference" mentions §14 (worktrees, irrelevant), §15 (destructive git, irrelevant), and JSDOM/touch (relevant). Misses:
- testing-pitfalls.md §10 "JS truthiness for numeric zero" — `vertices[0].lng || fallback` would skip 0. Bearings, distances, elevations all hit zero values. Use `value != null ? value : fallback`.
- testing-pitfalls.md §11 "Duplicated logic across modules" — direct hit on C2 (`useImperial`).
- implementation-pitfalls.md §11 "MapLibre dragRotate handler escape" — if ruler ever needs to suppress CTRL+drag rotation during vertex placement (CTRL+click is suppressed per §F, but is CTRL+DRAG also suppressed?), must respect the documented `_handlersById` deletion pattern.

---

## Edge-case enumeration the spec misses (10+ as requested)

These are concrete failure scenarios. Not all need to be in the spec table, but ALL deserve a one-line "handled" or "deferred — accepted" disposition.

| # | Scenario | Likely current behavior (per spec) | Required behavior |
|---|---|---|---|
| E1 | User has hardware mouse + touchscreen, pinches with fingers WHILE clicking with mouse during `drawing` | Vertex placement competes with pinch-zoom; possible duplicate vertex | Mouse click during multitouch → no-op (block during pinch) |
| E2 | User opens 2 browser tabs to Geographica, both have measurements in flight, both write to the same `localStorage` (none yet — but `sidebar-last-tab` collides) | Tab-state mismatch on reload | Document: ruler is per-tab, no persistence; explicit no-op |
| E3 | Pipeline is mid-write to `elevation.mbtiles` (WAL file `elevation.mbtiles-wal` exists RIGHT NOW); ruler fetches a tile that was just rotated | Tile request returns a partial PNG or 500 → null sample | Spec already handles per-tile fail. But: does TileServer GL respect WAL? Confirm with a test. Also: spec should reference implementation-pitfalls.md §8 (SQLite WAL mode for concurrent access). |
| E4 | User minimizes browser mid-sampling, returns 10 minutes later | `AbortController` doesn't fire on minimize; fetches stay in-flight or get throttled to 1Hz by browser power-saver; eventually resolve | Already handled by generation counter, but spec should explicitly call out background-throttling as a non-issue. |
| E5 | Disk fills up mid-sampling; tile fetch returns 500 | Per-tile fail handled; "All failed → distance only" | Already handled. |
| E6 | User's system clock changes mid-session (NTP sync, manual, DST) | No clock-dependent logic in spec — should be safe | Add explicit invariant: ruler does NOT use `Date.now()` in any code path that affects state. (If it does, surface it.) |
| E7 | Measurement on basemap A, user toggles to imagery (style B) DURING a drag | `style.load` fires; sources re-emit; drag sub-state... cleared? Lost? | Spec must say: any in-flight drag is committed-or-canceled at `style.load`. (Recommend: cancel; vertex returns to pre-drag position.) |
| E8 | MapLibre cache-evicts the tile ruler is currently sampling from (under memory pressure, e.g., user zoomed wildly) | Spec uses its own per-session cache → orthogonal to MapLibre's cache → safe | Already handled. Mention explicitly in spec to head off confusion. |
| E9 | Decimal-only bearing readouts vs. accessibility (dyslexia, screen-readers) | "Bearing 047°" vs "Bearing 47" — spec doesn't specify ARIA labels, screen-reader text | Add: `aria-label="Bearing 47 degrees"` on bearing readouts. |
| E10 | User reloads page DURING `inserting` mode | All state lost; page returns to default tab (which is NOT measure per M2); insert-banner is gone | Already handled (ephemeral by design); but loud "Saving... no, never mind" UX needs spec language. |
| E11 | User taps the floating mode banner's `[×]` while `inserting` AND a vertex is mid-tap | Race: banner click registers, state goes to `editing`, then map tap arrives, no longer in `inserting` so map tap falls to default reverse-geocode | Spec needs: "during the 200ms tap-vs-drag window, banner taps are blocked." |
| E12 | User has slow network (cellular fallback); 8-concurrent fetches each take 5s; user clicks Clear at 3s | `AbortController` aborts all 8 in-flight; new run starts when next Finish fires | Already handled. Add manual checklist row: "Throttle network to Slow 3G via DevTools, draw 5 vertices, hit Finish, hit Clear at 3s → no console errors, no leaked promises." |
| E13 | User Esc-cancels insert, then Esc again immediately | First Esc: `inserting → editing`. Second Esc: `editing → ?`. Spec §B doesn't list `editing → idle` via Esc | Spec must clarify: Esc in `editing` is no-op (or returns to `idle` only with explicit confirm). |
| E14 | User drags V2 onto V3 (overlapping coordinates) | `state.vertices[1]` and `state.vertices[2]` have ~identical lng/lat; segment 2 has distance ~0; bearing is undefined (lat1==lat2, lng1==lng2 → atan2(0,0)=0) | `bearingDeg` returns 0 silently; UI shows "0.0 mi, 0°"; user assumes broken. Add explicit "vertex too close to previous" debounce or hide segment row for sub-meter segments. |
| E15 | User pastes coordinates into an input (theoretical future: lat/lng entry) — currently N/A | N/A | Out of scope for v1. Note for v2. |
| E16 | Path goes through a polar-projection tile boundary (e.g., near Yellowstone where elevation tile grid quantizes oddly at z=12) | Per-tile decode independent; should be safe | Already handled (z=12 is uniform globally). |
| E17 | `formatDD` on exactly 0°N (equator) | Returns `0.00000° N` (not `S`). Off-CONUS so unreachable in practice | Already handled implicitly. |
| E18 | `formatDD` at 180°E vs -180°E (antimeridian) | Both produce `180.00000° E` and `180.00000° W` respectively — sign-dependent. Confusing for users. | Out of scope per spec non-goals. Document in §F. |
| E19 | User holds Backspace key during `drawing` | Auto-repeat → pops 1 vertex per OS-repeat-rate (~30Hz). Could empty array in 200ms. Final state: `idle` (since drawing → idle if <2 vertices). | Spec doesn't address. Add: debounce Backspace to 1 pop per 250ms; OR ignore key auto-repeat (`e.repeat`). |
| E20 | iOS rubber-band scroll on a measurement-tab tap | iOS may interpret pan-gesture-on-canvas as bounce-scroll if `touch-action` not set | Add CSS: `#map { touch-action: none; }` (likely already set globally — verify and add if not). |
| E21 | User double-taps an existing vertex in `editing` mode | Spec says tap-to-select, drag-to-move, but no double-click semantic in `editing` | Spec must specify (edit?, delete?, no-op?). Recommend: no-op to avoid surprise. |
| E22 | Map is rotated 30° (compass not north-up) when user drags vertex | Drag math uses `e.lngLat`; compass rotation is purely visual; should work | Already handled. Add manual checklist row. |
| E23 | User has terrain enabled, vertex is on a steep slope, drag-to-reposition under terrain | `e.lngLat` in 3D-terrain mode is the projection of click onto the elevated surface; vertex follows that lng/lat at ground level (not elevation). Sparkline re-samples at z=12. | Already handled per §F row. But: visual offset between where user dragged TO and where vertex appears (because vertex is at z=0 on the terrain-deformed surface) — could feel off. Manual checklist row. |
| E24 | A "Finish" gesture (Enter / dblclick / button) with EXACTLY 1 vertex | Spec: Finish only enabled with ≥2 vertices. But Enter is keyboard — does the keyboard handler check vertex count? | Yes per spec, but explicit test: `test_keyboard.js` should assert Enter with 1 vertex is no-op. |
| E25 | DevTools open during sampling, console.error fires for an unrelated reason | Should be no-op for ruler | Already safe. Mention. |

---

## Open questions resolved (or surfaced for resolution)

| Question | Spec OQ # | Resolution |
|---|---|---|
| Cancel in-flight elevation fetches on drag-start? | OQ1 | YES. Generation counter + AbortController. Also: increment generation on every state transition (M3.4). |
| z=12 sample zoom universally appropriate? | OQ2 | YES for CONUS Terrarium. Add explicit assertion in test that elevation MBTiles `maxzoom >= 12` (already declared `maxzoom: 14` in app.js:324). Future "z=12 unavailable" → fall back to `min(12, source maxzoom)`. |
| 50-tile cap appropriate? | OQ3 | Yes for v1. Manual checklist exercises it. No additional spec change needed, but: spec should specify what "Path too long" UI looks like (banner? inline notice? color?). |
| Tap-vs-drag threshold for gloved fingers? | OQ4 | Per M4: split into mouse (5px/200ms) and touch (12px/250ms). Defer final tuning to manual checklist. |
| Floating banner stacking with nav banner? | OQ5 | Per M7: explicit rule. Cannot defer. |
| iOS Safari fetch throttling? | OQ6 | Mitigated by 8-concurrent + per-session cache. Add manual checklist row exercising large path on iOS. |
| Vertex list virtualization? | OQ7 | Defer. Hard cap: 50 vertices. Reject placement beyond. Add explicit edge case row. |
| MapLibre symbol-layer glyph reliability? | OQ8 | **Test in JSDOM is impossible.** Add to manual checklist: "Place 5 vertices on positron AND on hybrid AND on darkmatter → labels visible on all 3." |

---

## Recommended spec changes (summary)

### Must-fix before plan-writing (CRITICAL — 2 items)

1. **Replace `elevationFromRGB` with Terrarium decoder** (C1). Verify against a real downloaded tile. Add `pngjs`-based regression test.
2. **Specify `useImperial` propagation mechanism** (C2): getter pattern OR `window._geographicaUseImperial` consumption OR CustomEvent. Single source of truth. Test.

### Should-fix in spec (MAJOR — 8 items)

3. Enumerate ALL click handlers needing `_ruler.isActive()` bails (M1). Update §"Coordination with parallel agents" insertion-count claim.
4. Add `'measure-panel'` to `VALID_SIDEBAR_PANELS` whitelist (M2).
5. Expand race-surface invariant table (M3): drag sub-state cleared on transitions; multitouch first-down wins; click-event in-flight no-op after transition.
6. Split tap-vs-drag thresholds for mouse vs touch (M4); specify dblclick behavior in every state.
7. Add Node-side `pngjs` decode test as the elevation-pipeline regression gate (M5).
8. Match `formatDD` codebase reality: 5 decimals, with spaces (M6).
9. Specify banner-stacking rule with nav banner (M7); add unit + manual test.
10. Add real-source `app.js` regex/AST test that the bail line exists (M8).

### Nice-to-have (MINOR — 6 items)

11. Match test file naming to codebase (`<topic>.test.mjs`) (MIN1).
12. Rename `test_terrain_rgb.js` → `test_terrain_decode.js` (MIN2).
13. Document divide-by-zero edge case (MIN3) or remove from test list.
14. Specify sparkline coverage-gap rendering at start/end (MIN4).
15. Broaden Backspace input-suppression check to include `contenteditable` and `select` (MIN5).
16. Expand pitfall cross-references to include testing-pitfalls.md §10, §11 and implementation-pitfalls.md §11 (MIN6).

### Edge-case dispositions (25 items — see table)

Each of E1-E25 needs one of: (a) added to §F with handling; (b) explicitly deferred to v2 with rationale; (c) called out as already-handled-by-existing-mechanism with the mechanism named.

### Manual checklist additions (concrete)

Add these rows to the §"Manual ship-gate checklist":

```
[ ] Throttle network to Slow 3G; draw 5 vertices, hit Finish, hit Clear at ~3s into elevation fetch → no console errors
[ ] Drag V2, release outside the canvas → vertex returns to pre-drag position; state == editing
[ ] Place 50 vertices (hard cap) → 51st placement attempt is rejected with notice
[ ] Toggle units imperial→metric while a measurement is on screen → all readouts update without panel re-mount
[ ] Start nav, then open Measure tab, then enter drawing → both banners visible, no overlap
[ ] On iOS Safari + on hybrid style: place 5 vertices → labels visible on map
[ ] Open Measure tab as last action, reload page → tab restored to Measure
[ ] Compass rotated 30°, drag vertex → vertex tracks cursor correctly
[ ] Terrain 3D enabled, place vertex on a steep slope → vertex appears at clicked lng/lat (offset acceptable)
[ ] Two measurements: place 5 vertices, click Clear, immediately place 5 more → no leaked vertex from first measurement
[ ] Open DevTools, throw an unrelated console.error during sampling → ruler completes without aborting
[ ] Hold Backspace key during drawing → does NOT empty entire vertex array in 200ms (debounced or e.repeat-aware)
[ ] User has KMZ pins loaded; tap on a pin during drawing → vertex is placed; KMZ popup does NOT also open
```

---

**Recommendation to controller:** spec is *almost* plan-ready, but C1 and C2 are concrete, codebase-grounded ship-blockers — both would survive plan-writing and bite during implementation. The plan author needs the Terrarium decoder spelled out and the `useImperial` propagation mechanism nailed down before they can write task descriptions. The 8 MAJOR items are tractable in spec text and should be added, otherwise the plan author makes these decisions silently. The 25 edge cases can be triaged at plan-writing time *if* the spec is annotated with one-line dispositions for each.

— `cholla`
