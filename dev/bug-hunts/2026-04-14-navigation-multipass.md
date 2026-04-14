# Bug Hunt Report -- Navigation System Multi-Pass Analysis

## Scope
Files analyzed:
- `frontend/navigation.js` (790 lines) -- navigation engine
- `frontend/nav-ui.js` (882 lines) -- navigation UI
- `frontend/app.js` (~2800 lines) -- integration point (nav-relevant sections)
- `frontend/index.html` -- DOM structure
- `frontend/style.css` -- nav-related CSS

All five passes performed: contract violations, cross-sibling patterns, failure modes, concurrency, error propagation.

## Bugs

### 1. GPS position centered on screen instead of offset downward -- map shows equal road behind and ahead
**Location:** `frontend/nav-ui.js:336-342`
**Severity:** significant
**Evidence:** The `feedGPS` function calls `map.easeTo({ center: [lng, lat], ... })` which places the GPS position at the geometric center of the viewport. Every turn-by-turn navigation app (Google Maps, Waze, Apple Maps) offsets the GPS icon toward the bottom third of the screen so the user sees more road ahead. MapLibre's `easeTo` supports a `padding` option (e.g., `padding: { top: 200 }` or `centerOffset`) that would shift the effective center downward. Without this, at pitch 60 the user sees as much road behind them as ahead, which is disorienting and defeats the purpose of heads-up navigation.
**Impact:** User cannot see upcoming turns and road ahead; the nav view is functionally broken for real driving. Confirmed by field report #3.
**Found in:** Pass 1 -- Contract Violations

### 2. Off-route detection requires 5 consecutive ticks but GPS feed runs at 500ms, not 1Hz -- doubles required off-route time
**Location:** `frontend/nav-ui.js:295` (feed interval) vs `frontend/navigation.js:22` (OFF_ROUTE_TICKS = 5, comment says "consecutive 1 Hz ticks")
**Severity:** significant
**Evidence:** The engine comment on line 22 says `OFF_ROUTE_TICKS = 5; // consecutive 1 Hz ticks` -- implying 5 seconds of off-route detection. But `nav-ui.js` line 295 sets `gpsFeedInterval = setInterval(feedGPS, 500)` -- calling `updateGPS` at 2 Hz, not 1 Hz. This means off-route detection triggers after only 2.5 seconds of real time instead of the designed 5 seconds. However, the more critical issue is the interaction with the cooldown: `REROUTE_COOLDOWN = 15000` ms is fine at 1 Hz but at 2 Hz the counter accumulates faster. The real problem is that the `feedGPS` function reads `window._geographicaGPSData` which is a cached object from the WebSocket -- if the GPS WebSocket sends at 1 Hz, the 500ms polling means half the ticks re-process the same GPS position. Since the snap result is deterministic for the same input, this means the off-route counter increments twice per actual GPS update, halving the designed detection window.
**Impact:** Off-route detection is actually 2.5 seconds instead of the designed 5 seconds, causing premature reroute triggers -- or, if GPS is near the threshold, the duplicate ticks with identical position cause the counter to reach 5 in 2.5s. This explains field report #1 (reroutes not triggering) only if the counter is being RESET by intermediate on-route readings. The real field failure is more likely bug #3 below.
**Found in:** Pass 1 -- Contract Violations

### 3. Off-route counter resets to zero on ANY on-route tick, even when alternating between on/off route
**Location:** `frontend/navigation.js:577-588`
**Severity:** critical
**Evidence:** The off-route detection logic:
```javascript
if (snap.distanceFromRoute > OFF_ROUTE_THRESHOLD) {
  offRouteCount++;
  if (offRouteCount >= OFF_ROUTE_TICKS) { ... }
} else {
  offRouteCount = 0;  // <-- full reset
}
```
Combined with bug #2 (500ms polling of 1Hz GPS), every other tick re-processes the same GPS position. If the user is off-route but their raw GPS jitters around the 50m threshold, a single tick below 50m resets the counter entirely. This is the classic "consecutive tick" fragility -- there is no hysteresis. The counter should use a higher threshold for resetting (e.g., must be <30m to reset) or use a sliding window instead of consecutive-only counting.

More critically: in real GPS conditions with 5-15m accuracy, a user 55m off-route will have GPS readings that oscillate between 40m and 70m from the route polyline. The counter never reaches 5 because every sub-50m reading resets it. This directly explains field report #1: "Route deviation detection doesn't trigger reroutes in practice."
**Impact:** Rerouting essentially never triggers for users who are marginally off-route (50-80m). Only massive deviations (>50m + GPS accuracy margin) consistently trigger reroutes.
**Found in:** Pass 3 -- Failure Mode Reasoning

### 4. Voice announcements can rapid-fire on re-snap after brief off-route excursion
**Location:** `frontend/navigation.js:336-368`
**Severity:** significant
**Evidence:** The `announcedSet` tracks which announcements have been made using keys like `"maneuverIdx-thresholdIdx"`. But after a reroute (`applyReroute`, line 745), `announcedSet` is cleared: `announcedSet = {};`. If the user goes slightly off-route, triggers a reroute, and the new route has maneuvers at similar indices and distances, all three threshold announcements (far, medium, near) fire in rapid succession on the first tick because `distToNext` is already below all three thresholds.

The `break` on line 365 prevents more than one announcement per tick, but each subsequent 500ms tick fires the next threshold. At 500ms intervals, a user approaching a turn will hear three announcements in 1.5 seconds. This explains field report #2: "Voice announcements rapid-fire near turns."
**Impact:** After reroute, three voice announcements fire within 1.5 seconds. Also occurs on initial navigation start if the user is already close to the first maneuver.
**Found in:** Pass 1 -- Contract Violations

### 5. Voice announcements fire during dead reckoning with no distance-rate gating
**Location:** `frontend/navigation.js:627-629`
**Severity:** minor
**Evidence:** `deadReckonTick()` calls `checkVoice(drSnap)` on every stale-checker tick (1 second interval). During dead reckoning, the extrapolated position advances along the route at the last known speed. If GPS goes stale near a maneuver, dead reckoning will march through the maneuver, firing announcements for a turn the user may or may not be approaching. There is no suppression of voice during dead reckoning mode.
**Impact:** Phantom voice announcements when GPS signal is temporarily lost near a turn.
**Found in:** Pass 3 -- Failure Mode Reasoning

### 6. Multi-leg route creates duplicate coordinates at leg boundaries
**Location:** `frontend/nav-ui.js:222-233`
**Severity:** minor
**Evidence:** When building route data from a multi-leg trip, the code does `allCoords = allCoords.concat(coords)` for each leg. Valhalla's encoded polyline for each leg includes the start and end points. For multi-leg trips, the last point of leg N is the same as the first point of leg N+1 (the waypoint). This creates a zero-length segment in `segmentDistances` (distance = 0). The `projectOntoSegment` function handles `lenSq === 0` by setting `t = 0`, but the `shapeOffset` uses `coords.length` which counts the duplicate. This means maneuver `begin_shape_index` values for subsequent legs are shifted by +1 per preceding leg boundary, potentially misaligning maneuvers with their actual polyline positions.
**Impact:** On multi-waypoint routes, maneuver alignment may be off by 1-N indices, causing wrong turn instructions to display for the wrong location.
**Found in:** Pass 2 -- Cross-Sibling Pattern Violations

### 7. `heading` variable in `feedGPS` shadows the outer-scope `heading` parameter
**Location:** `frontend/nav-ui.js:334`
**Severity:** significant
**Evidence:** In `feedGPS()`:
```javascript
var heading = data.heading || data.bearing || 0;
var speed = data.speed || 0;
var headingValid = heading !== 0 || speed > 1;
// ...
var bearing = headingValid ? heading : map.getBearing();
```
Line 334 declares `var bearing = headingValid ? heading : map.getBearing();`. This `bearing` variable shadows the `heading` value (which was already extracted on line 308). The real issue is: `headingValid` is computed as `heading !== 0 || speed > 1`. This means if the GPS reports heading=0 (north) and speed=0.5 (slow), `headingValid` is `false` -- even though heading 0 is a perfectly valid heading (due north). The check should be `heading != null && heading !== undefined` or use a dedicated validity flag from the GPS data.

Additionally, when `headingValid` is false, the code falls back to `map.getBearing()` -- the current map bearing. But if the user was previously heading east (bearing 90) and stops, the map stays at bearing 90 forever, showing a rotated map to a stationary user.
**Impact:** When traveling due north at low speed, the map bearing falls back to the previous map bearing instead of using the correct heading of 0. When stopped, the map remains rotated to the last bearing indefinitely.
**Found in:** Pass 1 -- Contract Violations

### 8. `setMuted` in engine not synced with UI mute state
**Location:** `frontend/navigation.js:757-759` and `frontend/nav-ui.js:606-612`
**Severity:** minor
**Evidence:** The `toggleMute()` function in `nav-ui.js` updates the local `muted` variable and `localStorage`, but never calls `nav.setMuted(muted)` on the engine. The engine has its own `muted` flag that gates `announce()`. Since `onVoice` callback is always called (the engine's `muted` flag starts as `false` and is never set), voice goes through the callback to `onVoice()` in nav-ui.js, where it's gated by the UI's `muted` check. So the muting works from the UI side -- but the engine still evaluates `checkVoice` and marks announcements as "announced" in `announcedSet` even when muted. If the user unmutes mid-navigation, they will have missed announcements that were silently consumed.
**Impact:** Announcements marked as delivered even when muted. Unmuting mid-route won't replay missed announcements (user misses "in 800 meters, turn right" because they were muted at 800m, and only hears the 50m announcement).
**Found in:** Pass 5 -- Error Propagation

### 9. `triggerReroute` receives (lat, lng) but stores them as (currentLat, currentLng) -- parameter order inconsistency
**Location:** `frontend/navigation.js:596-612`
**Severity:** significant
**Evidence:** The `triggerReroute` function signature is `function triggerReroute(lat, lng)` and correctly maps to `currentLat: lat, currentLng: lng`. But on line 548 in the JOINING state: `triggerReroute(lat, lng)` -- where `lat` is actually `gpsData.latitude` (correct). On line 583: `triggerReroute(lat, lng)` -- where `lat = gpsData.latitude` and `lng = gpsData.longitude` (correct).

HOWEVER, in `nav-ui.js` line 435: `locations.push({ lat: info.currentLat, lon: info.currentLng })` -- this creates a Valhalla location with `lon` key. The Valhalla API expects `lon` (not `lng`), so this is actually correct. No bug here on closer inspection.

**RETRACTED** -- This is not a bug. The parameter names are consistent and the Valhalla API format is correct.

### 10. Sidebar toggle (z-index 25) overlaps nav overlay (z-index 22) on mobile
**Location:** `frontend/style.css:661` and `frontend/style.css:1229`
**Severity:** significant
**Evidence:** The `#sidebar-toggle` hamburger button has `z-index: 25` (line 661), positioned at `top: 12px; left: 12px`. The `#nav-overlay` has `z-index: 22` and spans `top: 0; left: 0; right: 0`. On mobile, both are visible simultaneously. The sidebar toggle sits on top of the nav overlay's left edge, overlapping the maneuver icon (`#nav-icon`, which is 40x40px with 14px padding, starting at the left edge). The CSS comment says "Above sidebar overlay (19) and nav overlay (15)" but the nav overlay is actually z-index 22, not 15 -- the comment is stale.

The `#search-container` at `z-index: 10` is below the nav overlay (22), so it's hidden during navigation. But the sidebar toggle at z-index 25 pokes through, overlapping the instruction area.
**Impact:** On mobile, the hamburger menu button overlaps the navigation instruction panel, partially obscuring the maneuver icon. Confirms field report #4.
**Found in:** Pass 2 -- Cross-Sibling Pattern Violations

### 11. No return-to-north / compass button during navigation
**Location:** `frontend/app.js:158` and `frontend/nav-ui.js:330-343`
**Severity:** significant
**Evidence:** `NavigationControl` is instantiated with `showCompass: false` (app.js:158) to prevent Pitfall #11 (compass re-enables dragRotate). During navigation, the map is rotated to follow GPS heading (bearing parameter in `easeTo`). When the user manually pans (`onManualPan`), auto-centering pauses for 10 seconds and a recenter button appears. But there is no way to return the map to north-up orientation. The recenter button (`recenter()`) calls `feedGPS()` which re-centers on GPS position with the current heading-based bearing -- it does not reset bearing to 0.

The user has no way to temporarily view the map in north-up orientation during navigation. Google Maps provides a compass tap to toggle between north-up and heading-up modes.
**Impact:** Users cannot orient themselves using cardinal directions during navigation. Must stop navigation to get a north-up view. Confirms field report #5.
**Found in:** Pass 1 -- Contract Violations

### 12. `remainingDistance` computes the answer two different ways, uses only one, leaving dead code
**Location:** `frontend/navigation.js:174-180`
**Severity:** minor
**Evidence:**
```javascript
function remainingDistance(segIndex, t) {
  if (!segmentDistances) return 0;
  var d = segmentDistances[segIndex] * (1 - t);  // partial segment -- UNUSED
  var total = cumulativeDistances[route.coords.length - 1];
  var atPoint = cumulativeDistances[segIndex] + segmentDistances[segIndex] * t;
  return total - atPoint;
}
```
The variable `d` on line 176 computes the partial distance remaining in the current segment but is never used. The function returns `total - atPoint` which is correct. The `d` variable is dead code, likely a remnant from an earlier implementation. Not a correctness bug, but confusing.
**Impact:** No runtime impact; dead code that could confuse maintainers.
**Found in:** Pass 1 -- Contract Violations

### 13. `buildState` always returns `lastValidHeading` regardless of `headingValid` flag
**Location:** `frontend/navigation.js:491`
**Severity:** minor
**Evidence:**
```javascript
heading: headingValid ? lastValidHeading : lastValidHeading,
```
Both branches of the ternary return `lastValidHeading`. The `headingValid` flag is available as a separate field. This is technically correct (the heading value IS the last valid heading either way) but the conditional is a no-op that suggests a copy-paste error. The `else` branch probably intended to return `null` or `0` to indicate "no reliable heading."
**Impact:** The `headingValid` field in state correctly indicates reliability, but consumers must check `headingValid` rather than relying on `heading` being null/0 for invalid headings. If any consumer doesn't check `headingValid` and uses `heading` directly, they get stale heading data.
**Found in:** Pass 1 -- Contract Violations

### 14. GPS feed polls cached data -- no deduplication of identical GPS updates
**Location:** `frontend/nav-ui.js:298-315`
**Severity:** significant
**Evidence:** `feedGPS()` runs every 500ms and reads `window._geographicaGPSData`. This global is set by the GPS WebSocket handler in `app.js` (line 2278). If the WebSocket delivers at 1 Hz, the 500ms polling means every other call to `feedGPS` processes the identical GPS data object. The engine's `tick()` function runs the full pipeline: snap-to-route, off-route check (incrementing counter), voice check, state emission, and speed recording.

Processing the same GPS position twice means:
1. `offRouteCount` increments twice per real GPS update (bug #3 amplified)
2. `speedHistory` records duplicate entries, distorting the speed ratio and ETA
3. Two `onUpdate` callbacks fire per real GPS update, causing unnecessary DOM updates
4. The `map.easeTo()` call runs twice with identical parameters, causing animation jank

There is no timestamp check or deduplication in either `feedGPS` or `updateGPS`.
**Impact:** All engine calculations are distorted by processing duplicate GPS data. Off-route detection, ETA, and voice timing all operate at double-speed relative to real GPS updates.
**Found in:** Pass 4 -- Concurrency Reasoning

### 15. Reroute failure leaves engine stuck in "rerouting" state permanently
**Location:** `frontend/nav-ui.js:456-474` and `frontend/navigation.js:557-560`
**Severity:** critical
**Evidence:** When the engine enters `state = "rerouting"` (line 600 of navigation.js), the `onRerouteCb` fires and `nav-ui.js` makes a `fetch('/valhalla/route', ...)` call. If this fetch fails (network error, Valhalla down, offline), the `.catch` handler logs the error but does NOT reset the engine state back to "navigating". The engine stays in "rerouting" state indefinitely.

In "rerouting" state (navigation.js lines 557-560):
```javascript
if (state === "rerouting") {
  emitUpdate(buildState(snap, false));
  return;  // <-- no off-route detection, no voice, just position updates
}
```

The comment in nav-ui.js line 473 says "Banner stays visible; engine will retry after cooldown" -- but there is NO retry mechanism. The engine only triggers reroutes from the "navigating" state. Once in "rerouting", the engine emits position updates but never re-attempts the reroute. The user is stuck with "Recalculating..." banner forever, with no way to recover except stopping and restarting navigation.
**Impact:** Any reroute failure (common in offline/mesh network conditions) permanently breaks navigation. The user sees "Recalculating..." forever. This is especially bad for this platform's offline-first design where Valhalla may be unreachable.
**Found in:** Pass 3 -- Failure Mode Reasoning

### 16. `start()` calls `snapToRoute` after `reset()` which cleared `lastGPS`
**Location:** `frontend/navigation.js:685-705`
**Severity:** minor
**Evidence:** In `start()`:
```javascript
reset();        // sets lastGPS = null
route = routeData;
precomputeDistances();
startStaleChecker();
if (lastGPS) {  // always false -- reset() just set it to null
```
The `lastGPS` check on line 693 will always be false because `reset()` on line 686 sets `lastGPS = null`. The code always falls through to the `else` branch (line 701), entering "joining" state. The initial snap to determine if the user is already on-route never runs.

The first GPS update after `start()` via `updateGPS()` sets `lastGPS` and calls `tick()`, which will transition from "joining" to "navigating" if within 50m. So the user always sees a brief "Joining route..." banner even when they're standing on the route start.
**Impact:** Navigation always starts in "joining" state with a brief flash of "Joining route..." banner, even when the user is at the route start. Minor UX glitch but indicates the intended "skip joining if already on route" logic is dead code.
**Found in:** Pass 3 -- Failure Mode Reasoning

### 17. `feedGPS` heading=0 treated as falsy, defaulting to 0 anyway
**Location:** `frontend/nav-ui.js:308`
**Severity:** minor
**Evidence:**
```javascript
var heading = data.heading || data.bearing || 0;
```
If `data.heading` is `0` (due north), the `||` operator treats it as falsy and falls through to `data.bearing || 0`. This is a JavaScript truthiness bug -- heading 0 is a valid value meaning "due north." Should use `data.heading != null ? data.heading : (data.bearing != null ? data.bearing : 0)` or similar null-coalescing.
**Impact:** When heading is exactly 0 (north), the code may use `data.bearing` instead. If `data.bearing` is also 0 or absent, the result is still 0, so in most cases this is harmless. But if `data.bearing` contains a different value than `data.heading`, the wrong heading is used for due-north travel.
**Found in:** Pass 5 -- Error Propagation

## Design Concerns

### Lack of GPS data deduplication between WebSocket producer and polling consumer
The architecture of `app.js` writing to `window._geographicaGPSData` and `nav-ui.js` polling it at 500ms creates a fundamental timing mismatch. The engine assumes 1Hz input but gets 2Hz with duplicates. A better design would have the GPS WebSocket directly call `nav.updateGPS()` when navigation is active, or at minimum include a timestamp/sequence number for deduplication.

### No hysteresis in off-route detection
The binary threshold (>50m = off-route, <=50m = on-route) with full counter reset creates a dead zone where GPS noise prevents detection. A proper implementation would use separate thresholds for entering and exiting off-route state (e.g., >50m to start counting, must be <30m to reset counter).

### Reroute error handling assumes network reliability
The reroute flow has no timeout, no retry, and no fallback. For an offline-first platform designed to run on AREDN mesh networks (where connectivity is intermittent), this is a critical architectural gap. The engine should have a reroute timeout that returns to "navigating" state after N seconds, allowing the off-route detection to trigger a fresh reroute attempt.

### Voice announcement state leaked across reroutes
The `announcedSet` being wiped on reroute means all thresholds fire again. A better design would seed `announcedSet` with any maneuvers the user is already past or at, based on the initial snap position on the new route.

### Map bearing during navigation has no "north-up" toggle
The heading-up view with no escape hatch means users lose cardinal direction awareness. The recenter button could toggle between heading-up and north-up modes as a simple fix.
