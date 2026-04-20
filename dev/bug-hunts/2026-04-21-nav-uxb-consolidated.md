---
name: Nav UX Beta-Bug Consolidated Findings (2026-04-21)
description: Triangulated bug-hunt report across 3 hunters targeting 4 reported turn-by-turn nav bugs + surfaced 10 additional issues
---

# Nav UX Bug Hunt — Consolidated Findings

**Date:** 2026-04-21
**Scope:** Turn-by-turn navigation UX — [frontend/navigation.js](../../frontend/navigation.js), [frontend/nav-ui.js](../../frontend/nav-ui.js), nav-relevant CSS in [frontend/style.css](../../frontend/style.css), route/compass/control surface of [frontend/app.js](../../frontend/app.js), button markup in [frontend/index.html](../../frontend/index.html)
**Hunters:** Exploratory, Holistic, Multipass — all three completed and reported. Reports preserved at sibling paths `2026-04-21-nav-uxb-{exploratory,holistic,multipass}.md`.
**Motivation:** 4 beta-tester reports where prior fixes (commits `1761508`, `018adcf`, `8b37aae`, `da0b0a0`) did not land the intended UX.

---

## Confirmed Bugs

### B1. Voice announces 3× per turn; first too far, last two redundant

**Consensus:** All three hunters (primary for each).
**Location:** [frontend/navigation.js:42-46](../../frontend/navigation.js#L42-L46), [frontend/navigation.js:362-390](../../frontend/navigation.js#L362-L390)
**Evidence:**
```js
var VOICE_THRESHOLDS = {
  auto:       [800, 200, 50],
  bicycle:    [400, 100, 30],
  pedestrian: [200,  50, 20]
};
```
`VOICE_COOLDOWN = 5000` (commit 1761508) cannot suppress any of the three tiers because at driving speed the threshold crossings (800m→200m, 200m→50m) are ≥5s apart. Every turn fires three times. Texts at ti=0 and ti=1 both use `verbal_transition_alert_instruction` (the 200m one is near-identical to the 800m one — that's the "redundant" perception).
**Impact:** Voice-prompt fatigue in driving mode; user reports match exactly.
**Blast radius:** Self-contained. Next-after-next-maneuver branch is gated on `ti === 2` → needs to switch to `ti === thresholds.length - 1` when tier count changes.
**Fix approach:** Reduce `auto` to `[500, 50]`, `bicycle` to `[200, 30]`, `pedestrian` to `[75, 20]`. Change `ti < 2` / `ti === 2` branches to `ti === thresholds.length - 1`. Also: `VOICE_COOLDOWN = 5000` stays as belt-and-suspenders.

---

### B2. Reroute leaves the map polyline, sidebar directions, and `_geographicaLastTrip` stale

**Consensus:** All three hunters — flagged as the most severe reported bug.
**Location:** [frontend/nav-ui.js:500-532](../../frontend/nav-ui.js#L500-L532), [frontend/app.js:2114-2142](../../frontend/app.js#L2114-L2142), [frontend/app.js:2139-2142](../../frontend/app.js#L2139-L2142)
**Evidence:** `attemptReroute` calls `nav.applyReroute(newRouteData, seq)` — engine-side only. It never:
- Calls `map.getSource('route').setData(...)` with new polyline
- Updates `window._geographicaLastTrip` or `lastRouteTrip`
- Updates `lastRouteCoords` (used by spatial-search corridor queries)
- Rebuilds the `#route-directions` list

The "active route" is represented in four places — engine `route`, `window._geographicaLastTrip`, map GeoJSON source `'route'`, and the sidebar `<ol>`. `applyReroute` touches one of four. **Split-state bug.**
**Impact:** User deviates → turn-by-turn directions reroute correctly, but the blue line on the map keeps showing the original route. Users think the nav is broken.
**Blast radius:** Needs an exportable `renderRoute` (or a helper) reachable from nav-ui.js. Must be gated to skip `fitBounds` during active nav (don't zoom out on the user mid-drive). `lastRouteCoords` update is independent but cheap — include it for corridor-search correctness.
**Fix approach:** Expose `window._geographicaRenderRoute(trip, { refitBounds: !active })` and have `attemptReroute` call it on success *before* `nav.applyReroute`. Also update `window._geographicaLastTrip = data.trip; window._geographicaLastTrip._costing = info.costing;`.

---

### B3. GPS marker renders at ~60% from top of viewport, not bottom 1/3 (~80%)

**Consensus:** All three hunters.
**Location:** [frontend/nav-ui.js:725-733](../../frontend/nav-ui.js#L725-L733) (`getNavPadding`), [frontend/nav-ui.js:549-559](../../frontend/nav-ui.js#L549-L559) (`restoreMapState`)
**Evidence:**
```js
function getNavPadding() {
  if (!overlay || overlay.classList.contains('hidden')) return {};
  var measured = overlay.offsetHeight + 20;
  ...
  return { top: lastNavPaddingTop };
}
```
MapLibre's `padding` is an **inset**, not an offset — the map's effective center is at `(top + (H - bottom))/2`. With `top ≈ 150-200px` and `H = 900px`, center lands at `(150 + 900)/2 = 525` (~58% from top). To place the marker at fraction `f` of the map container height, the math is `top - bottom = H * (2f - 1)`.

**Sub-bug (Holistic A1 + Exploratory B3 sub + Multipass U-2):** `restoreMapState`'s `easeTo` does not pass `padding`. MapLibre retains the last-used padding, so post-nav fitBounds and flyTo calls inherit the ~160px top offset for the rest of the session. This explains why users sometimes see routes displayed off-center after ending nav.

**Impact:** Drivers can't see enough of what's ahead of them; offscreen upcoming turns. Also poisons post-nav map state.
**Blast radius:** Viewport-proportional formula needs to target ~78%-from-top consistently across viewport heights and handle overlay=0 on first frame (Multipass P3-5). `restoreMapState` fix is self-contained.
**Fix approach:** Target 78% from top → `top = mapH * 0.56 + overlayH`. Use `map.getContainer().clientHeight` (not `window.innerHeight`, which includes browser chrome). Also explicit `padding: { top: 0, bottom: 0, left: 0, right: 0 }` in `restoreMapState`.

---

### B4. Recenter button overlaps compass button on mobile; wrong stack order on desktop

**Consensus:** All three hunters — mobile overlap unanimous; desktop "4px gap, wrong semantic order" unanimous.
**Location:** [frontend/style.css:1436-1439](../../frontend/style.css#L1436-L1439), [frontend/style.css:1673-1688](../../frontend/style.css#L1673-L1688)
**Evidence:**
- Desktop: `#nav-recenter-btn` bottom:120 (extends 120–156), `#compass-north-btn` bottom:160 (160–196). 4px gap. Recenter is BELOW compass — opposite of user's stated preference.
- Mobile (≤480px): compass bottom:140 (140–176). Recenter unchanged at 120 (120–156). **16px vertical overlap, z-index collision.**

User's stated preference: recenter (steering-wheel / target icon) above compass, compass pushed lower.
**Impact:** On mobile the two buttons mask each other; on desktop they don't overlap but are backwards.
**Blast radius:** CSS-only. Need to re-verify scale-bar and zoom-control (MapLibre) positions at `bottom-right` don't crash into the new stack. MapLibre default zoom controls are at top-right by default (see [app.js:222-224](../../frontend/app.js#L222-L224) for the scale control; no NavigationControl is visible here — verify).
**Fix approach:** Single stack, consistent order both breakpoints:
```css
#compass-north-btn { bottom: 120px; right: 12px; z-index: 11; }
#nav-recenter-btn  { bottom: 170px; right: 12px; z-index: 11; }
@media (max-width: 480px) {
  #compass-north-btn { bottom: 100px; }
  #nav-recenter-btn  { bottom: 150px; }
}
```
Recenter is above compass both breakpoints; 14px gap between the two 36px buttons.

---

### B5. Multi-stop reroutes silently skip all intermediate waypoints

**Consensus:** Exploratory (B5, flagged critical), Multipass (U-1, flagged critical).
**Location:** [frontend/nav-ui.js:275](../../frontend/nav-ui.js#L275) — `buildRouteData` hardcodes `remainingWaypoints: []`.
**Evidence:** `route.remainingWaypoints` is used by `triggerReroute` → `onRerouteCb` → `attemptReroute` to build the `locations: [...]` array for the Valhalla call. It's always `[]` because `buildRouteData` initializes it to empty. The engine has no other code path that populates it. So multi-stop trips (A → B → C → D) on deviation get rerouted directly to D.
**Impact:** Silent data loss on multi-stop routes. User plans A→B→C→D, deviates at A→B, gets rerouted to D skipping B and C.
**Blast radius:** Need to extract intermediate waypoints from the original Valhalla trip locations. [frontend/app.js:2080-2100](../../frontend/app.js#L2080-L2100) already has `locations` in the request body (start, intermediates as `{type: 'through'}`, end). They're preserved in `data.trip.locations` or in `_geographicaLastTrip.locations`. Reroute path can pull from there.
**Fix approach:** In `buildRouteData`, extract `remainingWaypoints` from `trip.locations` (skip first and last, which are current start and end). In `onReroute` callback ([nav-ui.js:470-498](../../frontend/nav-ui.js#L470-L498)), filter out any waypoints the driver has already passed. MVP: pass all through-locations; driver bypasses are the driver's problem.

---

### B6. `costing_options` dropped on reroute

**Consensus:** Exploratory (B6).
**Location:** [frontend/nav-ui.js:488-492](../../frontend/nav-ui.js#L488-L492)
**Evidence:** The reroute body contains only `locations`, `costing`, `directions_options`. The original user request at [app.js:2059-2075](../../frontend/app.js#L2059-L2075) supports `costing_options` (e.g. `avoid_highways`, `use_ferry`, bicycle types) — but that's not passed to the engine, so reroutes use Valhalla defaults.
**Impact:** User picks "avoid highways" for routing preference, deviates, reroute puts them back on the highway.
**Blast radius:** Need to preserve `costing_options` through `buildRouteData` → engine `route` → `onRerouteCb` → `attemptReroute` body. Four touchpoints but all shallow.
**Fix approach:** Add `costingOptions` field to the route payload; engine passes it through to reroute callback; nav-ui includes it in the reroute request body.

---

### B7. `feedGPS` ticks the engine every 500ms on duplicate GPS data, halving hysteresis window

**Consensus:** Exploratory (B7).
**Location:** [frontend/nav-ui.js:326-349](../../frontend/nav-ui.js#L326-L349)
**Evidence:**
```js
gpsFeedInterval = setInterval(feedGPS, 500);

function feedGPS() {
  if (!active || !nav) return;
  var data = window._geographicaGPSData;
  if (!data) return;
  ...
  // Feed to engine -- UNCONDITIONAL
  nav.updateGPS({ latitude: lat, ... });

  // Heartbeat guard -- only resets on signature change
  var sig = lat + ',' + lng;
  if (sig !== lastGPSSignature) {
    lastGPSSignature = sig;
    ...
  }
}
```
With GPS source at ~1 Hz and interval at 2 Hz, engine receives each GPS reading twice. Engine's off-route hysteresis (`OFF_ROUTE_WINDOW = 5` ticks, `OFF_ROUTE_MIN_COUNT = 3`) is designed to debounce over ~5 seconds at 1 Hz — but fills in ~2.5s at the faster rate. Reroutes fire ~2× faster than intended.
**Impact:** Premature reroutes on GPS jitter; false reroutes while stopped at lights (accumulating stale off-route ticks faster than the window clears).
**Blast radius:** Move `nav.updateGPS(...)` inside the signature-change guard. Simple. But: also changes `checkVoice` tick rate — need to verify that doesn't cause voice-cooldown interactions.
**Fix approach:** Only call `nav.updateGPS` on signature change OR when heading/speed delta is significant. Preserve the 500ms interval for heartbeat/UI-driven effects.

---

### B8. Padding leaks across nav sessions via MapLibre camera property persistence

**Consensus:** Holistic (A1), Exploratory (B3 sub), Multipass (U-2).
**Location:** [frontend/nav-ui.js:549-559](../../frontend/nav-ui.js#L549-L559)
**Evidence:** `restoreMapState` passes `center, zoom, pitch, bearing, duration` but no `padding`. MapLibre preserves the most recently applied padding value, so post-nav `fitBounds` calls inherit the ~160px top inset until the next reload.
**Impact:** Routes displayed after nav exit look off-center; non-nav map state is subtly broken.
**Fix approach:** Add `padding: { top: 0, bottom: 0, left: 0, right: 0 }` to the restore `easeTo`.

**Merged with B3 for execution** — single `getNavPadding` + padding-cleanup story.

---

### B9. `applyReroute` does not reset `lastAnnouncementTime`; `announcedSet` filter is a no-op

**Consensus:** Holistic (A2+A3), Multipass (U-5), Exploratory (S3 flagged as suspicious then confirmed).
**Location:** [frontend/navigation.js:791-818](../../frontend/navigation.js#L791-L818)
**Evidence:**
```js
applyReroute: function (routeData, seq) {
  ...
  lastIndex = 0;
  currentManeuverIdx = 0;
  ...
  var newSet = {};
  for (var key in announcedSet) {
    var idx = parseInt(key.split('-')[0]);
    if (idx <= currentManeuverIdx) {  // currentManeuverIdx just reset to 0
      newSet[key] = true;             // preserves only "0-*" keys from OLD route
    }
  }
  announcedSet = newSet;
  ...
}
```
Two issues:
1. `currentManeuverIdx` is set to 0 *before* the filter — so the filter keeps keys for maneuver 0 of the **old** route. Those keys may or may not match the new route's maneuver 0. Comment says "Clear only forward maneuvers' thresholds" but code keeps backward.
2. `lastAnnouncementTime` is not reset. A reroute immediately after an announcement can suppress the new route's first announcement for up to 5s.

**Impact:** Voice behaves unpredictably immediately post-reroute — first announcement of the new route may be skipped, or re-firing of the OLD maneuver 0 key.
**Fix approach:** `announcedSet = {}; lastAnnouncementTime = 0;`

---

### B10. `lastRerouteTime` not cleared when engine reroute timeout fires

**Consensus:** Holistic (A4).
**Location:** [frontend/navigation.js:640-646](../../frontend/navigation.js#L640-L646)
**Evidence:** When the 10s `REROUTE_TIMEOUT` fires (engine gave up), the engine resets state to `navigating` but does not clear `lastRerouteTime`. The 15s `REROUTE_COOLDOWN` stays active, so users remain unable to trigger a new reroute for another 5 seconds (10s timeout + 5s cooldown overhang).
**Impact:** Drivers stay off-route up to 20s instead of 15s when the first reroute fails.
**Fix approach:** Set `lastRerouteTime = 0` inside the `setTimeout` callback at [navigation.js:640-646](../../frontend/navigation.js#L640-L646). Also null `rerouteTimeoutId`.

---

### B11. Reroute receives Valhalla 200-with-error as a silent no-op

**Consensus:** Multipass (U-8, P3-3).
**Location:** [frontend/nav-ui.js:506-515](../../frontend/nav-ui.js#L506-L515)
**Evidence:** `if (data.trip && nav) { ...apply... }` — if Valhalla returns 200 with `{error: "..."}` (no trip field), the branch is skipped silently. Banner stays at "Recalculating...", retry never fires (because no `.catch`), engine eventually times out at 10s.
**Impact:** 10s of a stuck banner, ambiguous failure surface.
**Fix approach:** Explicitly branch on `!data.trip` or `data.error`, log it, decrement to the retry/failure path.

---

### B12. In-flight reroute fetches and retry setTimeouts survive `stopNavigation`

**Consensus:** Multipass (U-9), Exploratory (part of design concerns).
**Location:** [frontend/nav-ui.js:500-532](../../frontend/nav-ui.js#L500-L532), [frontend/nav-ui.js:195-231](../../frontend/nav-ui.js#L195-L231)
**Evidence:** `stopNavigation` clears `autoCenterTimer`, `gpsHeartbeatTimer`, and `gpsFeedInterval`. It does NOT:
- Capture/clear setTimeout IDs from the reroute retry loop
- Abort in-flight fetch via AbortController
- Reset `rerouteRetries` counter

A user who triggers a reroute, then stops nav, then starts nav again within 8s (retry delay ≤ 8s) sees the old retry fire and attempt to `nav.applyReroute(...)` on the new engine session — protected by `data.trip && nav` guard but still fires bandwidth + console errors.
**Impact:** Minor — defense-in-depth. State leak between sessions.
**Fix approach:** Capture setTimeout IDs in a module-level array; `stopNavigation` clears them all and resets `rerouteRetries = 0`. Optional: AbortController on the fetch.

---

### B13. Multi-leg maneuver at `begin_shape_index === 0` indexes into previous leg

**Consensus:** Exploratory (B8).
**Location:** [frontend/nav-ui.js:244-262](../../frontend/nav-ui.js#L244-L262)
**Evidence:**
```js
if (i > 0 && coords.length > 0) {
  coords = coords.slice(1);
  indexAdjust = 1;
}
if (leg.maneuvers) {
  leg.maneuvers.forEach(function (m) {
    mc.begin_shape_index = (mc.begin_shape_index || 0) - indexAdjust + shapeOffset;
```
For leg i > 0 with `indexAdjust = 1`, a maneuver with `begin_shape_index = 0` becomes `-1 + shapeOffset = shapeOffset - 1`, which points into the previous leg's final segment.
**Impact:** First-maneuver-of-subsequent-leg voice/icon fires one segment early. Cosmetic rather than functional but visible on multi-stop routes. Low severity.
**Fix approach:** `Math.max(0, (mc.begin_shape_index || 0) - indexAdjust) + shapeOffset`, similarly for end_shape_index.

---

## Design Decisions Requiring User Input

### D1. Voice cadence redesign — thresholds vs. time-to-maneuver

**The concern:** Both Multipass and Exploratory flagged that distance-threshold voice logic is a design dead-end. At 60 mph, 800m→200m is ~22 seconds; at 15 mph, it's ~90s. Google Maps uses TTM (time-to-maneuver): announce at 30s and 3s regardless of speed.
**Why this needs a decision:** TTM is a ~50-line redesign (compute seconds-to-maneuver from current speed). Threshold tuning is a 3-line fix. TTM is arguably the right answer; thresholds are good enough for v1.
**Options:**
- **(a) Tune thresholds now** — `auto: [500, 50]`, `bicycle: [200, 30]`, `pedestrian: [75, 20]`. Ships today. Closes B1.
- **(b) Redesign to TTM** — announce at 30s TTM and 3s TTM, computed from `nm.distanceTo / lastSpeed`. Better UX. Larger change; more test surface.
- **(c) Hybrid** — ship (a) now; file (b) as v2.
**Recommendation:** **(c) Hybrid.** Sam's established pattern is "ship the fix, file the redesign." TTM work belongs in a separate plan with its own adversarial review.

### D2. Reroute button strategy: dedicated `renderRoute` export vs. single active-route setter

**The concern:** B2's split-state bug (route lives in 4 places) is a design smell. Multipass U-1 and Exploratory design concerns both called out the lack of a `setActiveRoute(trip)` unifier.
**Why this needs a decision:** Minimal fix is to export `window._geographicaRenderRoute` and call it from the reroute path. A broader refactor would introduce a `setActiveRoute(trip, { refitBounds })` that owns all 4 state slots and is the sole entry point. The broader refactor eliminates a class of bugs; the minimal fix closes B2.
**Options:**
- **(a) Minimal export** — expose `renderRoute` with optional `refitBounds` param. B2 closes in ~10 lines.
- **(b) Introduce `setActiveRoute`** — funnel all four state updates (engine, global, map source, sidebar) through one function. Larger diff; catches future bugs.
**Recommendation:** **(a) Minimal export for this cycle.** Add the refactor (b) as a documented follow-up. Ship value, not churn.

### D3. Scope for B5 (waypoints dropped) — fix now or defer?

**The concern:** Exploratory + Multipass both flagged this as critical. But beta testers may not yet be using multi-stop routes much (the feature is present but subtle — wpContainer in [app.js:2211](../../frontend/app.js#L2211)). Fix requires touching `buildRouteData` signature and the reroute path — coupled to B2's fix.
**Why this needs a decision:** It's a silent data-loss bug. If testers aren't using multi-stop routes, deferring is safe. If they are, it's a must-fix.
**Options:**
- **(a) Fix in this cycle** — couple to B2's changes; adds ~20 lines. Low risk of regression because the reroute path is already being touched.
- **(b) Defer to a dedicated plan** — separate fix + separate test coverage.
**Recommendation:** **(a) Fix now.** The reroute path is open surgery this cycle; doing B5 alongside is cheap. Deferring risks another beta screenshot next week.

### D4. Scope for B12 (in-flight fetch not cancelled on stop) — fix now or defer?

**The concern:** Defense-in-depth. The `data.trip && nav` guard makes this mostly benign. But it's a pattern that will bite us later.
**Options:**
- **(a) Fix with AbortController + setTimeout tracking** — ~15 lines.
- **(b) Defer.**
**Recommendation:** **(a) Fix now** — cheap, aligns with the reroute-path changes for B2/B5.

---

## False Positives / Low-Priority Signal

### FP1. Multipass U-4 — `_geographicaUseImperial` race → distance 1.6× wrong

**Flagged by:** Multipass (U-4).
**Why downgraded:** Requires the user to toggle units *between* `/valhalla/route` response arriving and `buildRouteData` running. Valhalla returns `summary.length` in the unit the request specified. `app.js:1089-1090` updates both local `useImperial` and global `_geographicaUseImperial` synchronously on radio change. The race window is the `~30ms` between fetch resolution and `buildRouteData`. Extremely narrow.
**Reality:** Pre-existing, low-severity. Document as a future cleanup. The proper fix is reading `summary.units` from the Valhalla response rather than the global.

### FP2. Multipass U-3 — First-frame easeTo uses raw heading at zero speed

**Flagged by:** Multipass (U-3).
**Why downgraded:** On nav start with the vehicle stationary, the startNavigation easeTo at [nav-ui.js:183-191](../../frontend/nav-ui.js#L183-L191) uses `gps.heading || 0`. `gps.heading` at rest is genuinely stale/invalid. But this is a one-shot initial bearing — the subsequent `feedGPS` tick corrects it via `lastNavState.headingValid` check at [nav-ui.js:366-370](../../frontend/nav-ui.js#L366-L370). Duration is 800ms; 500ms tick rate corrects within 2 ticks.
**Reality:** Observable (brief initial rotation wobble) but not a user-reported bug. Document as minor.

### FP3. Holistic A7 — DR fires voice announcements

**Flagged by:** Holistic (A7).
**Why downgraded:** `DEAD_RECKON_MAX = 30000` (30s). At 30 m/s, DR can extrapolate ~900m — plausibly past a turn. But the voice has already fired its final tier at 50m before DR kicked in (GPS goes stale → DR starts), so the announce set already has those keys. Low-priority.
**Reality:** Theoretically reachable with pathological GPS drop timing. Documented risk.

### FP4. Holistic A5 — Dead CSS variable write

**Flagged by:** Holistic (A5).
**Why downgraded:** Technically dead code (no selector reads `--nav-overlay-height`). Removing it is a cleanup. Not a correctness bug. Include in fix cycle as a 1-line cleanup if touching `onNavUpdate`; otherwise defer.

### FP5. Multipass U-13 — `speechSynthesis.cancel()` before `speak()`

**Flagged by:** Multipass (U-13).
**Why downgraded:** The cancel-then-speak pattern is correct when announcements are time-sensitive (e.g., "turn RIGHT now" needs to interrupt "in 200 meters turn right"). Side effect: truncated mid-utterance on repeat. The B1 threshold reduction eliminates most of the repetition, making this non-issue by B1 fix.

### FP6. Multipass U-14 / P1-6 — Muted preference not synced to engine on start

**Flagged by:** Multipass.
**Why downgraded:** Looked at `startNavigation` — `nav.setMuted(muted)` is not called explicitly, but engine's `muted` defaults to `false`. On first announcement, `onVoice` callback in nav-ui.js:456 checks `muted` before calling `speechSynthesis.speak`. So the UI-side mute protects the user from hearing it; engine "announces" but UI swallows. Engine's `announcedSet` still gets updated — which means if the user unmutes mid-route, they miss the pre-announcement-set maneuver's prompts. **Upgraded to a confirmed bug: B14.**

---

### B14. Initial mute state not propagated to engine on nav start (upgraded from FP6)

**Consensus:** Multipass (P1-6, originally noted). Verified on re-read.
**Location:** [frontend/nav-ui.js:141-193](../../frontend/nav-ui.js#L141-L193) (`startNavigation`), [frontend/navigation.js:820-823](../../frontend/navigation.js#L820-L823) (`setMuted`).
**Evidence:** `startNavigation` never calls `nav.setMuted(muted)`. Engine defaults to `muted = false`. Even though `onVoice` in UI guards on UI-side `muted`, the engine still populates `announcedSet` on every "fire." If user unmutes mid-drive, upcoming announcements for already-passed thresholds are silenced.
**Fix approach:** In `startNavigation` after `nav.start(routeData)`, add `nav.setMuted(muted);`.

---

## Bugs Outside Primary Scope / Pre-Existing

### O1. `observeRouteAvailability` couples to `#export-route-btn` visibility

**Location:** [frontend/nav-ui.js:121-135](../../frontend/nav-ui.js#L121-L135)
**Blast radius:** If the export button is removed/restyled, nav start button breaks.
**Recommendation:** Document. Not a user-reported bug.

### O2. `syncUnits` updates local `useImperial` only, not `window._geographicaUseImperial`

**Location:** [frontend/nav-ui.js:112-115](../../frontend/nav-ui.js#L112-L115)
**Blast radius:** Comment says "synced from app.js unit radios" but global stays stale if someone only triggers the nav-ui listener path. In practice app.js:1090 is the authoritative setter.
**Recommendation:** Minor cleanup, defer.

---

## Test Gap Analysis

*Completing this before writing the fix plan so tests land with fixes per TDD discipline.*

### B1. Voice 3× per turn

**Why missed:** No automated tests exist for `frontend/navigation.js`. The engine is pure JS and trivially jsdom-testable, but Geographica's nav test coverage is zero as of this audit (per Exploratory hunter's finding). The `VOICE_THRESHOLDS` value has never had a regression test.
**Pitfall coverage:** Covered in principle by `dev/testing-pitfalls.md` Pitfall #5 (tiered-threshold voice, which the holistic hunter added in Phase 2). Application gap: no nav engine tests exist to encode it.
**Catch test:** Synthetic GPS track + fixed 2-maneuver route; assert announcement count per maneuver equals 2 across 3 speed regimes (city/highway/walking).

### B2. Route polyline not updated on reroute

**Why missed:** No tests exercise the `onReroute` → `attemptReroute` → `applyReroute` lifecycle against a real MapLibre source. JS-only nav tests (Multipass suggestion) would catch "applyReroute called without accompanying renderRoute," but JSDom lacks MapLibre.
**Pitfall coverage:** `dev/testing-pitfalls.md` Pitfall #1 — split state across engine/UI globals/map sources. New pitfall (holistic added).
**Catch test:** Integration test: start nav with a 2-leg route, simulate off-route GPS, assert `map.getSource('route')._data.geometry.coordinates` changed after reroute resolves.

### B3. Padding math

**Why missed:** Only manual visual inspection. No test on `getNavPadding` return values.
**Pitfall coverage:** Pitfall #2 — MapLibre padding-as-inset math. New pitfall (holistic added).
**Catch test:** Unit test on `getNavPadding()` with fixed overlay height + viewport height; assert returned `top` produces the desired on-screen position via the padding formula.

### B4. Button overlap

**Why missed:** No CSS regression testing. Visual-only QA.
**Pitfall coverage:** Pitfall #5 — CSS stacking with mixed !important (new).
**Catch test:** Playwright snapshot at 375px and 1280px widths during active nav; assert no `getBoundingClientRect` intersection between `#nav-recenter-btn` and `#compass-north-btn`.

### B5. Waypoints dropped

**Why missed:** Hardcoded `remainingWaypoints: []` is the kind of "TODO stub that shipped" bug that unit tests on `buildRouteData` would have caught if any existed.
**Pitfall coverage:** New pitfall to add — "lossy adapter functions that initialize fields to defaults should assert or log when the caller's data was non-empty."
**Catch test:** Unit test on `buildRouteData` with a 3-location trip; assert `remainingWaypoints.length === 1`.

### B6-B14

**Why missed:** All boil down to "zero tests exist for the nav engine." Addressing this wholesale is out of scope for this fix cycle but should be filed.
**Pitfall coverage:** Mixed. Several map to new pitfalls added by the holistic hunter in Phase 2.

### Testing Pitfalls Updates

The holistic hunter wrote 5 entries to [dev/testing-pitfalls.md](../../dev/testing-pitfalls.md) in Phase 2:
1. Split state across engine/UI globals/map sources
2. MapLibre padding-as-inset math
3. easeTo property persistence
4. Tiered-threshold voice announce-N-times pattern
5. CSS stacking with mixed !important + custom buttons

This consolidation adds one more candidate (for B5):
6. **Lossy adapters** — when a function copies/transforms data with "TODO / placeholder / empty initializer" fields, it should assert or log if the caller's source data was non-empty. Hardcoded `remainingWaypoints: []` shipped because no caller test asserted the output.

*(Will add in Phase 6 if not already covered.)*

---

## Summary Table

| ID  | Bug                                                 | Severity  | Fix complexity | Consensus |
|-----|-----------------------------------------------------|-----------|----------------|-----------|
| B1  | Voice 3× per turn                                   | high      | small (3-liner)| 3/3       |
| B2  | Reroute doesn't update map polyline                 | critical  | medium         | 3/3       |
| B3  | GPS padding math wrong (+ session leak)             | high      | small          | 3/3       |
| B4  | Recenter/compass button overlap                     | medium    | tiny           | 3/3       |
| B5  | Multi-stop reroutes drop intermediate waypoints     | critical  | medium         | 2/3       |
| B6  | `costing_options` dropped on reroute                | medium    | small          | 1/3       |
| B7  | `feedGPS` 2 Hz double-ticks engine                  | medium    | tiny           | 1/3       |
| B8  | Padding leaks post-nav (merged into B3)             | medium    | tiny           | 3/3       |
| B9  | `applyReroute` announcedSet + lastAnnouncementTime  | medium    | tiny           | 3/3       |
| B10 | `lastRerouteTime` not cleared on timeout            | medium    | tiny           | 1/3       |
| B11 | Valhalla 200-with-error silent                      | medium    | small          | 1/3       |
| B12 | In-flight fetches survive `stopNavigation`          | low       | small          | 2/3       |
| B13 | Multi-leg `begin_shape_index=0` index bug           | low       | tiny           | 1/3       |
| B14 | Initial mute state not propagated to engine         | low       | tiny           | 1/3       |

**Counts: 14 confirmed + 4 design decisions + 6 false positives / low-priority + 2 out-of-scope = 26 findings accounted for from 3 hunter reports.**
