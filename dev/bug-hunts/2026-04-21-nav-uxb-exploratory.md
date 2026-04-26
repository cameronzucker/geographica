# Bug Hunt Report — Turn-by-Turn Nav UX (Exploratory)

**Date:** 2026-04-21
**Scope:** `frontend/navigation.js`, `frontend/nav-ui.js`, `frontend/style.css` (nav-related), `frontend/app.js` route/compass/renderRoute, `frontend/index.html` nav overlay markup.
**Methodology:** Depth-first exploration starting at the nav engine state machine (highest risk — voice, reroute, off-route detection), then bridging layer, then CSS/layout.

## Scope recap

Explored deeply:
- Navigation engine state machine (IDLE/JOINING/NAVIGATING/REROUTING/ARRIVED)
- Voice announcement logic (`VOICE_THRESHOLDS`, `checkVoice`, `announce`, cooldown)
- Reroute path: engine `triggerReroute` → nav-ui `onReroute` → `attemptReroute` → `applyReroute`
- GPS feed loop and auto-center padding (`feedGPS`, `getNavPadding`, `saveMapState` / `restoreMapState`)
- Multi-leg polyline stitching (`buildRouteData` slicing + index adjustment)
- CSS stacking of bottom-right map buttons across breakpoints
- Route rendering path in `app.js` (`renderRoute`, `route` GeoJSON source)

Scanned but did not go deep:
- Maneuver-icon SVG builder (visual only, no correctness impact)
- Formatting helpers (`formatNavDistance`, `formatDuration`)
- `decodePolyline` (two copies in nav-ui.js and app.js — verified equivalent)

---

## Confirmed Bugs

### B1 — Voice announcements fire ~3× per turn because there are three thresholds, not two

**Location:** `frontend/navigation.js:42-46` (VOICE_THRESHOLDS) and `frontend/navigation.js:362-390` (checkVoice loop).
**Severity:** significant
**Evidence:**
```js
var VOICE_THRESHOLDS = {
  auto:       [800, 200, 50],   // far, medium, near
  bicycle:    [400, 100, 30],
  pedestrian: [200,  50, 20]
};
```
`checkVoice` iterates all three and fires each as the user approaches. The `VOICE_COOLDOWN = 5000ms` added in commit 1761508 only suppresses two announcements that cross thresholds within 5s of each other. At typical driving speeds (20 m/s = 45 mph) the 800→200 m crossing takes ~30 s and 200→50 m takes ~7.5 s — both well outside the 5 s cooldown, so all three fire.
**Impact:** User hears 3 voice prompts per turn. First (800 m) is far too distant to be actionable; last two (200 m, 50 m) feel redundant.
**Fix approach:**
- Drop to two thresholds: auto `[300, 50]`, bicycle `[150, 30]`, pedestrian `[75, 20]`. These are the alert + pre-transition distances.
- Remove the `ti < 2` / `else` branch in `checkVoice`. Map threshold 0 to `verbal_transition_alert_instruction` (alert) and threshold 1 to `verbal_pre_transition_instruction` (near-turn, include "then"). If only one threshold fits the geometry (very short street), the single announcement still fires on the near threshold.
- Preserve the `VOICE_SPEED_GATE` + `VOICE_NEAR_ANNOUNCE_DISTANCE` logic unchanged.

### B2 — After reroute the blue route line on the map never updates

**Location:** `frontend/nav-ui.js:500-532` (attemptReroute success path) and `frontend/app.js:383-404` (the `route` map source).
**Severity:** critical
**Evidence:** On successful Valhalla reroute, `attemptReroute` calls `nav.applyReroute(newRouteData, seq)` which updates the engine's internal `route` but NEVER updates the map `route` source. The `route` GeoJSON source is only set via `renderRoute(trip)` in `app.js:2114-2142`, which is called from the initial fetch path at line 2094. There is no call site for `renderRoute` in nav-ui.js.

Secondary fallout in the same location:
- `lastRouteCoords` (`app.js:2128`) is stale → the spatial-search corridor query in `search/` uses the pre-reroute polyline.
- `window._geographicaLastTrip` / `lastRouteTrip` (`app.js:2091-2093`) still holds the pre-reroute trip → export directions, "resume nav" button, etc. all see the stale route.
- The sidebar turn-by-turn `<ul id="route-directions">` (built in `app.js:2179-2192`) never updates.

**Impact:** User deviates, engine reroutes, new voice instructions match the new route — but the blue line on the map still points down the old one. Visual/cognitive mismatch; tester said map "looked stuck."
**Fix approach:**
1. Export `renderRoute` (or a new `updateRouteDisplay(trip)` helper) to `window._geographicaRenderRoute`.
2. In `attemptReroute` success handler, after successful Valhalla fetch, call `window._geographicaRenderRoute(data.trip)` before `nav.applyReroute`. This updates `lastRouteTrip`, `lastRouteCoords`, the `route` source data, and the directions list all in one place.
3. Do NOT let `renderRoute` refit the bounds when called during active nav — guard with `if (!active)` or pass a flag. Otherwise the map jumps out of heads-up view.

### B3 — GPS icon sits at ~60% from top of viewport, not ~80% ("bottom third") during nav

**Location:** `frontend/nav-ui.js:768-775` (`getNavPadding`), `frontend/nav-ui.js:549-559` (`restoreMapState`).
**Severity:** significant
**Evidence:**
```js
function getNavPadding() {
  if (!overlay || overlay.classList.contains('hidden')) return {};
  var measured = overlay.offsetHeight + 20;
  ...
  return { top: lastNavPaddingTop };
}
```
MapLibre's `easeTo({padding:{top:X}})` places the map center at the vertical midpoint of the usable area *below* the top padding. With overlay ≈ 140 px and viewport ≈ 700 px: center lands at `(140+20 + 700)/2 ≈ 430 px`, i.e. `430/700 ≈ 61%` from the top — nowhere near the "bottom 1/3" Google-Maps style behaviour the tester expects.

The correct math for placing the center at fraction f from the top of the viewport is:
`padding.top = viewportH * (2f - 1) + overlayH` (keeping overlay from covering the marker).
For f=0.80 and a 700 px viewport: top ≈ 560 px, which is much larger than the current ~160 px.

**Related sub-bug — padding is never cleared after nav ends.** `restoreMapState`:
```js
map.easeTo({
  center: savedMapState.center,
  zoom: savedMapState.zoom,
  pitch: savedMapState.pitch,
  bearing: savedMapState.bearing,
  duration: 800
});
```
No `padding: {top:0, bottom:0, left:0, right:0}`. MapLibre retains whatever padding was set during nav; panning after nav ends feels "off" because the internal center is still biased downward. `saveMapState` also fails to capture pre-nav padding, so if the app ever sets padding elsewhere it would be destroyed.

**Impact:** The turn-ahead area above the GPS puck is too small; drivers lose the context they need to prepare for upcoming turns. Post-nav map feels subtly miscentered until the user zooms or resizes.
**Fix approach:**
1. Change `getNavPadding` to target a fraction of the map height (not the overlay height). Use the map container's `offsetHeight`:
   ```js
   var mapEl = map.getContainer();
   var mapH = mapEl.offsetHeight;
   var overlayH = overlay.offsetHeight;
   var desiredFraction = 0.78;  // GPS at 78% from top ≈ bottom-1/4
   var topPadding = Math.max(overlayH + 20, Math.round(mapH * (2 * desiredFraction - 1)));
   return { top: topPadding, bottom: 0, left: 0, right: 0 };
   ```
2. In `restoreMapState`, add `padding: {top:0,bottom:0,left:0,right:0}` to the `easeTo` call so post-nav map behaviour is clean.
3. Capture `map.getPadding()` (if set elsewhere) in `saveMapState` and restore it; or document that the app doesn't use padding outside of nav and the hard-zero is safe.

### B4 — `#nav-recenter-btn` overlaps `#compass-north-btn` on mobile (≤480 px)

**Location:** `frontend/style.css:1436-1439` (nav-recenter-btn) and `frontend/style.css:1673-1688` (compass-north-btn).
**Severity:** significant
**Evidence:**

| Breakpoint | Button         | `bottom` | Height | Y range    |
|------------|----------------|---------:|-------:|-----------:|
| Desktop    | nav-recenter   | 120 px   | 36 px  | 120–156    |
| Desktop    | compass-north  | 160 px   | 36 px  | 160–196    |
| ≤480 px    | nav-recenter   | 120 px   | 36 px  | 120–156    |
| ≤480 px    | compass-north  | 140 px   | 36 px  | **140–176** → **16 px overlap with recenter 120–156** |

(The scope doc claimed compass was at 140 px on desktop — it's actually 160 px on desktop; only the ≤480 px override at line 1686 drops it to 140 px. The overlap is mobile-only.)

Neither button has a `transition` that would change its position. Neither has `z-index` overrides; both inherit `z-index:10` from `.map-btn`. In a direct overlap the one rendered later in the DOM wins — `nav-recenter-btn` is declared later in HTML, so it paints on top, but either way it's visually broken.

**Impact:** Tester reported both buttons visibly overlapping during mobile nav. Touch targets also stack → unreliable tapping.
**Fix approach:**
- The user's desired stacking order is: **recenter above compass**, compass pushed **down**. Maintain zoom control at bottom≈26 px (stops at ~106 px).
- Proposed breakpoints (with 8 px gaps):
  - Desktop: compass bottom=120 (120–156), recenter bottom=168 (168–204). Gap to zoom: 14 px.
  - ≤480 px: compass bottom=114 (114–150), recenter bottom=162 (162–198). Gap to zoom: 8 px.
- Give both buttons an explicit `z-index: 11` for safety (above zoom control).
- Add a `@media (max-width: 480px)` rule for `#nav-recenter-btn` so it tracks the compass offset.
- Consider hiding `#center-gps-btn` (left-side) during nav since `nav-recenter-btn` already serves that purpose; today both appear and can confuse. (Not part of the reported bug but worth flagging.)

---

## Additional Confirmed Bugs (not in the reported four)

### B5 — After reroute, all intermediate waypoints are silently dropped

**Location:** `frontend/nav-ui.js:268-276` (`buildRouteData`) and `frontend/nav-ui.js:470-498` (`onReroute`).
**Severity:** critical (for multi-stop trips)
**Evidence:**
`buildRouteData` hard-codes `remainingWaypoints: []`:
```js
return {
  coords: allCoords,
  maneuvers: allManeuvers,
  summary: summary,
  totalDistance: distMeters,
  totalTime: summary.time || 0,
  costing: trip._costing || 'auto',
  remainingWaypoints: []          // <-- always empty
};
```
Engine's `triggerReroute` passes `route.remainingWaypoints || []` through to `onRerouteCb` (`navigation.js:652`). `onReroute` then reconstructs the Valhalla body as `[current GPS, ...info.remainingWaypoints, original destination]` — with `remainingWaypoints` always empty, it becomes `[current GPS, destination]`. Any intermediate stops the user entered are erased.
**Impact:** User has A → waypoint B → waypoint C → D. They deviate between A and B, reroute fires, the new route goes directly from current position to D, skipping B and C. Silent data loss with no UI indication.
**Fix approach:**
- In `buildRouteData`, take an `inputLocations` argument (or read from `trip.locations`) and compute which waypoints are still ahead of the user. Cleanest: pass `window._geographicaLastTrip.locations` into `buildRouteData` and store `locations.slice(1, -1)` as `remainingWaypoints`.
- On subsequent reroutes, filter out waypoints the user has already passed. Proxy: `alongRouteDistance` to the waypoint's nearest point on the OLD polyline — keep those ahead of `snap.alongRouteDistance`.
- Minimal fix to stop data loss (can be shipped quickly): in `onReroute`, read waypoints directly from `lastTrip.locations.slice(1, -1)` and include them unconditionally. Accept the edge case that users get routed back through a waypoint they already passed (rare; better than silently skipping).

### B6 — Reroute request drops `costing_options` (avoid_highways, bicycle type, etc.)

**Location:** `frontend/nav-ui.js:488-492`.
**Severity:** significant
**Evidence:** The reroute body is:
```js
var body = {
  locations: locations,
  costing: info.costing || 'auto',
  directions_options: { units: window._geographicaUseImperial ? 'miles' : 'kilometers' }
};
```
`costing_options` (set at `app.js:2072`) is never carried. If the user enabled "avoid highways" or selected a specific bicycle type, the reroute sends a default-profile request.
**Impact:** Reroute may route user onto avoided road types or with incorrect bike/ped profile. Not catastrophic but undermines user's routing preferences.
**Fix approach:**
- Engine's `triggerReroute` should include `costing_options` in the info payload (grab it from `route.costingOptions` if set during `buildRouteData`).
- `buildRouteData` should accept and store `costingOptions` (pull from `_geographicaLastTrip._costingOptions` or store at fetch time).
- `onReroute` includes `costing_options: info.costingOptions` in the fetch body when present.

### B7 — `feedGPS` ticks the engine every 500 ms regardless of whether GPS changed

**Location:** `frontend/nav-ui.js:326-349`.
**Severity:** significant
**Evidence:**
```js
gpsFeedInterval = setInterval(feedGPS, 500);
...
if (nav && nav.updateGPS) {
  nav.updateGPS({ latitude, longitude, heading, speed, accuracy, timestamp });
}
// ... then later ...
var sig = lat + ',' + lng;
if (sig !== lastGPSSignature) { /* heartbeat reset */ }
```
The `sig` check gates only the heartbeat timer; `nav.updateGPS` is called unconditionally. If the GPS source updates at 1 Hz (gpsd default for LC29H) but the UI polls at 2 Hz, half the ticks feed duplicate data. Each tick calls `snapToRoute`, `findManeuverForSegment`, and — critically — `offRouteHistory.push(isOffRoute)`.

With `OFF_ROUTE_WINDOW = 5` and `OFF_ROUTE_MIN_COUNT = 3`, the reroute trigger fires after 3-of-5 off-route ticks within a 5-tick window. At 2 Hz tick with 1 Hz GPS, this is effectively ~2.5 s of genuine off-route time, not the intended 5 s (`OFF_ROUTE_WINDOW` × 1 s).

**Impact:**
1. Premature reroutes — users brushing a route edge (brief GPS noise, lane change, parked car) can trigger reroutes at half the expected time budget.
2. Double CPU load on snap/projection math for no new information.
3. Voice `announcedSet` gating is unaffected (key-based, not count-based), so B1 is not compounded.

**Fix approach:**
- Option A (minimal): in `feedGPS`, only call `nav.updateGPS` when `sig !== lastGPSSignature`. Move the signature update to happen whether or not the heartbeat is reset. Interval can stay at 500 ms for responsive heartbeat but engine ticks only on actual updates.
- Option B (cleaner): the `gps` service already pushes via WebSocket. Subscribe to a "gps-updated" event (already dispatched somewhere in app.js) rather than polling. Avoids the whole duplicate-tick problem.
- Either way, make sure the first-ever tick after nav start isn't dropped — compare against a sentinel like `null`, not string `'null,null'`.

### B8 — Multi-leg trips: start maneuver of legs 2+ gets `begin_shape_index = -1 (+ shapeOffset)`

**Location:** `frontend/nav-ui.js:244-262` (buildRouteData leg stitching).
**Severity:** minor-to-significant (only affects multi-waypoint trips)
**Evidence:**
```js
if (i > 0 && coords.length > 0) {
  coords = coords.slice(1);
  indexAdjust = 1;
}
if (leg.maneuvers) {
  leg.maneuvers.forEach(function (m) {
    var mc = Object.assign({}, m);
    mc.begin_shape_index = (mc.begin_shape_index || 0) - indexAdjust + shapeOffset;
    mc.end_shape_index = (mc.end_shape_index || 0) - indexAdjust + shapeOffset;
```
Valhalla emits `begin_shape_index: 0` for the start maneuver of every leg (this is the "continue on X" or "depart" maneuver). For leg i>0, after the `-indexAdjust` subtraction that becomes `-1`, then `+shapeOffset` gives `shapeOffset - 1` — which points into the LAST segment of the previous leg. `findManeuverForSegment` then matches leg i's start maneuver while the user is still on leg i-1's final segment.
**Impact:** On multi-waypoint routes, as the user arrives at a waypoint, the next leg's "depart" maneuver becomes current one segment too early. Voice announcements and the maneuver icon appear prematurely. Also interacts with B5 (waypoints already broken on reroute).
**Fix approach:**
- Clamp the adjusted begin index to 0:
  ```js
  mc.begin_shape_index = Math.max(0, (mc.begin_shape_index || 0) - indexAdjust) + shapeOffset;
  ```
- `end_shape_index` typically has values ≥1 so the subtraction is safe there, but add the same clamp for defense.

### B9 — Arrival speech can be cut off by `stopNavigation` 3 s later

**Location:** `frontend/nav-ui.js:465-468` (`onArrival`) and `frontend/nav-ui.js:202` (`stopNavigation` calls `speechSynthesis.cancel()`).
**Severity:** minor
**Evidence:**
```js
function onArrival() {
  onVoice('You have arrived at your destination.');
  setTimeout(stopNavigation, 3000);
}
...
function stopNavigation() {
  ...
  if (speechAvailable) speechSynthesis.cancel();
```
The arrival text takes ~1.5-2 s to speak in most TTS engines, so 3 s is usually enough. On slow engines / long custom phrasings / first-time speech (engine warmup), the announcement can be truncated.
**Impact:** Occasional "You have arrived at your destina..." cutoff.
**Fix approach:** Listen for the `end` event on the arrival utterance and call `stopNavigation` from there (with a fallback setTimeout of 6-8 s).

---

## Suspicious but not confirmed

### S1 — In-flight reroute cannot be cancelled if user recovers

**Location:** `frontend/navigation.js:580-584` (rerouting state is a dead zone).
**Behaviour:** Once the engine enters "rerouting", no tick transitions back to "navigating" except via `applyReroute` or the 10 s `REROUTE_TIMEOUT`. If the user swerves off and immediately returns to the original route, the reroute request is still in flight and will clobber the good route when it returns.
**Why not confirmed:** User will usually be happy with either the old or new route since both reach the destination. But the UX is subtly wrong (and engineers debugging reroutes will find it surprising).
**Possible fix:** In `tick` while rerouting, if `snap.distanceFromRoute <= OFF_ROUTE_EXIT_THRESHOLD` for N ticks, bump `rerouteSeq` (invalidating the pending response) and transition back to "navigating".

### S2 — `muted` flag is not synced from UI to engine at nav start

**Location:** `frontend/nav-ui.js:141-193` (startNavigation) and `frontend/navigation.js:727-766` (engine start / reset).
**Behaviour:** nav-ui.js loads `muted` from localStorage at init. Engine's `muted` defaults to false. On `nav.start(routeData)`, `reset()` does NOT reset `muted` (correct — preserves last user action), but `startNavigation` also doesn't call `nav.setMuted(muted)`. So the engine can be out of sync with the UI for the first nav session after page load. UI gates speech anyway, so user doesn't hear anything — but the engine still marks `announcedSet[key]` inside `announce()` for voice calls that get silently dropped downstream. On unmute mid-turn, the "far" prompt won't replay.
**Why not confirmed:** Requires a specific sequence (mute, reload, start nav, unmute near turn) to observe the dropped prompt.
**Possible fix:** In `startNavigation` after `nav.start(routeData)`, call `nav.setMuted(muted)`.

### S3 — `applyReroute` preserves announcements for maneuver index 0 of the new route

**Location:** `frontend/navigation.js:801-809`.
**Code:**
```js
lastIndex = 0;
currentManeuverIdx = 0;
// Clear only forward maneuvers' thresholds
var newSet = {};
for (var key in announcedSet) {
  var idx = parseInt(key.split('-')[0]);
  if (idx <= currentManeuverIdx) {
    newSet[key] = true;
  }
}
announcedSet = newSet;
```
After reroute, `currentManeuverIdx` is reset to 0, so "keep announcements with idx ≤ 0" just preserves old-route maneuver 0's entries (which mean nothing for the new route's maneuver 0). The effect is ~= clear-all, which is correct behaviour. Comment is misleading; net behaviour is benign.
**Why not confirmed:** The resulting behaviour is accidentally correct. Code is just confusing. Recommend simply `announcedSet = {}` after reroute for clarity.

---

## Root-cause notes + proposed fixes for the four reported bugs

| Bug | Root cause (one line) | Proposed minimal fix |
|-----|-----------------------|----------------------|
| B1 (3× voice)   | `VOICE_THRESHOLDS` has three tiers; `VOICE_COOLDOWN=5s` can't suppress when crossings are seconds apart. | Reduce to 2 tiers (e.g. auto `[300, 50]`) and update `checkVoice` text-selection branch. |
| B2 (route line stale post-reroute) | `attemptReroute` success never calls `renderRoute` — only engine state updates. | Expose `renderRoute` via `window._geographicaRenderRoute` and call it from `attemptReroute` before `nav.applyReroute`, gated so it doesn't re-fit bounds while `active`. |
| B3 (GPS not in bottom 1/3) | `getNavPadding` returns `overlay+20` which yields ~61% viewport placement; should target map height. Also `restoreMapState` leaks padding. | Compute top padding from map container height targeting fraction ~0.78. Explicitly zero padding in `restoreMapState.easeTo`. |
| B4 (recenter/compass overlap on mobile) | `#nav-recenter-btn` bottom=120 and `#compass-north-btn` bottom=140 (mobile) overlap by 16 px. No mobile-specific rule for recenter. | Reshuffle stack: compass below (bottom 114–120), recenter above (bottom 162–168). Give both `z-index: 11`. Add `@media (max-width: 480px)` rule for `#nav-recenter-btn`. |

---

## Summary table

| ID | Title | Severity | Reported? | File:Line |
|----|-------|---------:|:---------:|-----------|
| B1 | 3× voice announcements per turn | significant | yes (#1) | navigation.js:42-46, 362-390 |
| B2 | Map route line not refreshed on reroute | critical | yes (#2) | nav-ui.js:500-532 + app.js:2114-2142 |
| B3 | GPS puck at ~60% from top, padding leaks post-nav | significant | yes (#3) | nav-ui.js:768-775, 549-559 |
| B4 | Recenter/compass overlap on mobile ≤480px | significant | yes (#4) | style.css:1436-1439, 1673-1688 |
| B5 | Intermediate waypoints dropped on reroute | critical | no | nav-ui.js:268-276, 470-498 |
| B6 | Reroute drops `costing_options` | significant | no | nav-ui.js:488-492 |
| B7 | `feedGPS` ticks engine every 500ms on duplicate GPS | significant | no | nav-ui.js:326-349 |
| B8 | Multi-leg stitching: start maneuver index = -1 offset | minor/sig | no | nav-ui.js:244-262 |
| B9 | Arrival speech can be cut off by 3s stopNavigation timer | minor | no | nav-ui.js:465-468 |
| S1 | No way to cancel in-flight reroute when user recovers | design | no | navigation.js:580-584 |
| S2 | UI `muted` not synced to engine at nav start | minor | no | nav-ui.js:141-193 |
| S3 | `applyReroute` announce-set clear logic misleading | cosmetic | no | navigation.js:801-809 |

## Design concerns (not bugs, patterns that invite bugs)

1. **Route state is tracked in three places** — the `route` GeoJSON source (app.js), `window._geographicaLastTrip` (app.js), and the engine's internal `route` (navigation.js). B2/B5 happen because updates to one don't propagate to the others. Consolidate behind a single "route change" event that updates all three in lockstep (or make `renderRoute` the single source of truth and have nav-ui call it).

2. **Waypoint metadata dies at the nav-ui boundary** — `buildRouteData` is lossy: it drops `remainingWaypoints`, `costing_options`, and leaves `summary` in display units only. A reroute needs to recompute an equivalent Valhalla request, so all fields that describe the original request must survive the boundary.

3. **MapLibre padding is not treated as part of saved map state.** `saveMapState` / `restoreMapState` save center/zoom/pitch/bearing but not padding, yet nav actively mutates padding. Any saved-state pattern that doesn't include padding will have the leak bug.

4. **Feed loop interval is unrelated to the GPS source rate.** The 500 ms poll-on-window-var pattern works for display (heartbeat UI) but not for state machines with history windows. Either drive the engine from the actual GPS event, or dedupe inside `feedGPS`.

5. **No test harness for the nav engine.** The nav engine is pure JS with no DOM deps — it would be cheap to unit-test in jsdom or Node (it's attached to `window.GeographicaNav` but that's trivially mockable). B1, B5, B7, B8 would all be caught by a ~50-line test that scripts a synthetic GPS track against a fixed route and asserts maneuver/voice/reroute outcomes.
