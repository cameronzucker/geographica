# Bug Hunt Report — Navigation System (Holistic)

## Scope

Files analyzed:
- `frontend/navigation.js` (790 lines) — Navigation engine
- `frontend/nav-ui.js` (882 lines) — Navigation UI
- `frontend/app.js` (relevant sections: map init, routing, GPS, camera controls)
- `frontend/index.html` — DOM structure
- `frontend/style.css` — Nav-related CSS

Approach: Read all source files completely, then reasoned about cross-file interactions, state machine transitions, GPS data flow, and UI/map integration.

## Bugs

### 1. GPS feed runs at 2 Hz but engine expects 1 Hz — off-route counter triggers at half the intended delay

**Location:** `nav-ui.js:295` (gpsFeedInterval = 500ms), `navigation.js:22` (OFF_ROUTE_TICKS = 5)

**Severity:** critical

**Evidence:** The GPS feed interval in `nav-ui.js` is set to 500ms:
```js
gpsFeedInterval = setInterval(feedGPS, 500);
```
But the navigation engine's off-route detection is designed around 1 Hz GPS ticks. The constant `OFF_ROUTE_TICKS = 5` with the comment "consecutive 1 Hz ticks" means the engine expects 5 seconds of continuous off-route before triggering a reroute. At 500ms feed rate, the counter reaches 5 after only 2.5 seconds.

However — and this is why it paradoxically *doesn't* trigger reroutes in practice — `feedGPS()` reads from `window._geographicaGPSData`, which is a shared global updated by the WebSocket handler. At 500ms polling, the *same* GPS data is fed to the engine twice per GPS update. This means `snapToRoute` produces the same snap result twice, but `offRouteCount` increments on both calls if the snap is off-route. The counter hits 5 in 2.5s instead of 5s.

But there's a worse interaction: when the GPS WebSocket is delivering at its native 1 Hz rate, the 500ms poll means that *between* real GPS updates, the engine re-processes stale data. If the stale data happens to snap on-route (because the vehicle hasn't moved), `offRouteCount` resets to 0 on the second tick, making it nearly impossible to accumulate 5 consecutive off-route ticks. The user must be off-route for a sustained period where both the "real" and "stale" ticks snap off-route — effectively requiring the GPS to be >50m off-route for the entire 2.5s window without any position jitter bringing it back. This explains the field report that "route deviation detection doesn't trigger reroutes in practice."

**Impact:** Off-route detection is fundamentally broken. The 2x feed rate either triggers too fast (if GPS updates at 2Hz+) or effectively never triggers (if GPS updates at 1Hz, because alternate ticks re-process stale data that resets the counter when the snap result fluctuates near the threshold).

---

### 2. Voice announcements fire on every 500ms tick within threshold distance — rapid-fire near turns

**Location:** `navigation.js:336-367` (checkVoice), `nav-ui.js:295` (500ms feed)

**Severity:** critical

**Evidence:** The `checkVoice` function uses `announcedSet` to track which announcements have fired, keyed by `maneuverIdx + "-" + thresholdIndex`. This correctly prevents *the same threshold* from firing twice. However, the `break` at line 365 only breaks out of the threshold loop — it doesn't prevent the *next* tick (500ms later) from checking the same maneuver again.

The real problem is that when `feedGPS()` runs at 500ms and the vehicle is in a parking lot, roundabout, or near a turn, the snap position can oscillate between segments. When it oscillates, `currentManeuverIdx` changes, and `checkVoice` computes `nextIdx = currentManeuverIdx + 1` — which may point to different maneuvers on alternate ticks. Each new `nextIdx` value has a fresh `announcedSet` key, so the announcement fires again.

Additionally, after a reroute via `applyReroute` (line 745), `announcedSet` is cleared (`announcedSet = {}`), so all thresholds fire again for the new route — including thresholds the user has already passed through. If the reroute re-routes along a similar path, the user hears duplicate announcements immediately.

**Impact:** Voice announcements rapid-fire near turns, in parking lots, and after reroutes. Matches the field report exactly.

---

### 3. Map centers GPS position in screen center — nav overlay covers the road ahead

**Location:** `nav-ui.js:336-343` (feedGPS auto-center)

**Severity:** significant

**Evidence:** The `map.easeTo()` call in `feedGPS` centers the GPS position at the map's geometric center:
```js
map.easeTo({
  center: [lng, lat],
  bearing: bearing,
  zoom: zoom,
  pitch: 60,
  duration: 500
});
```
No `padding` parameter is used. The nav overlay (`#nav-overlay`) sits at `top: 0; left: 0; right: 0` and occupies roughly 120-150px at the top of the screen. Since the map center is the geometric center of the full viewport, the GPS position appears roughly in the middle of the *visible* area below the overlay — or even partially behind it. The road ahead (which is above the center point when bearing-locked) is largely hidden behind the nav instruction card.

Google Maps and every major navigation app solve this by offsetting the center downward (using `padding: { top: N }` in MapLibre) so the GPS dot appears in the lower third of the screen, showing the road ahead above it.

**Impact:** The user cannot see the road ahead during navigation. The GPS dot is centered on the full viewport, and the nav overlay covers the top portion where the upcoming road should be visible. This matches the field report "nav icon centered on screen instead of bottom-locked."

---

### 4. Sidebar toggle (z-index 25) renders on top of nav overlay (z-index 22) — UI overlap on mobile

**Location:** `style.css:661` (`#sidebar-toggle` z-index 25), `style.css:1229` (`#nav-overlay` z-index 22)

**Severity:** significant

**Evidence:** The sidebar toggle hamburger button is at `z-index: 25; top: 12px; left: 12px`. The nav overlay is at `z-index: 22; top: 0; left: 0; right: 0`. The hamburger button renders on top of the nav instruction panel. The search container is at `z-index: 10; top: 12px; left: 56px` — below the nav overlay, so it's hidden, but the STT mic button (dynamically appended inside `#search-box`) shares this z-index.

On mobile (768px breakpoint), the search container expands to `width: calc(100vw - 64px)` starting at `left: 52px`, and the nav overlay spans the full width. The hamburger sits at top-left, overlapping the nav icon area. There's no CSS rule to hide or reposition `#sidebar-toggle` during navigation.

**Impact:** On mobile, the hamburger menu overlaps the nav instruction panel. The user can accidentally open the sidebar when trying to interact with the nav UI. This matches the field report "sidebar hamburger + voice toggle overlap the top nav pane on mobile."

---

### 5. `heading` field in buildState always returns `lastValidHeading` regardless of `headingValid` flag

**Location:** `navigation.js:491`

**Severity:** minor

**Evidence:**
```js
heading: headingValid ? lastValidHeading : lastValidHeading,
```
Both branches of the ternary return `lastValidHeading`. The intent was clearly to return `null`, `0`, or some fallback when heading is invalid. The `headingValid` flag is properly tracked but the state object ignores it. The UI can check `headingValid` separately, but the `heading` field itself is always the last valid heading, even when the vehicle is stopped and heading is unreliable.

**Impact:** The map bearing during navigation continues using a stale heading when the vehicle stops. The map won't snap to the fallback bearing behavior (e.g., route bearing or north-up) because the engine always reports the last valid heading as the current heading, even when `headingValid` is false.

---

### 6. `costing` field extracted from wrong location in Valhalla trip response

**Location:** `nav-ui.js:246`

**Severity:** significant

**Evidence:**
```js
costing: trip.legs && trip.legs[0] ? (trip.legs[0].summary || {}).costing || 'auto' : 'auto',
```
Valhalla's trip response does not include `costing` in `leg.summary`. The costing model is in the *request*, not the response. The `(trip.legs[0].summary || {}).costing` will always be `undefined`, so this always falls through to `'auto'`.

This means the voice announcement thresholds (`VOICE_THRESHOLDS`) are always the `auto` thresholds (800/200/50m), even for bicycle (400/100/30m) or pedestrian (200/50/20m) routes. Bicycle and pedestrian users get announcements way too early — 800m away for a pedestrian turn that should be announced at 200m.

**Impact:** Voice thresholds are always the driving thresholds regardless of travel mode. Pedestrians hear "turn left in 800 meters" when walking, and bicycle users get announcements at driving distances. This compounds with Bug #2 to make voice announcements especially annoying for non-driving modes.

---

### 7. Reroute sends lat/lng in wrong parameter order — Valhalla gets coordinates swapped

**Location:** `navigation.js:604` (triggerReroute), `nav-ui.js:435` (onReroute)

**Severity:** critical

**Evidence:** In `navigation.js`, `triggerReroute` is called with `(lat, lng)`:
```js
// Line 548: triggerReroute(lat, lng);
// Line 596: function triggerReroute(lat, lng) {
```
The reroute callback object is built as:
```js
{ currentLat: lat, currentLng: lng, ... }
```
But the callers at lines 548 and 583 pass the arguments correctly as `triggerReroute(lat, lng)`. However, look at the tick function — at line 583:
```js
triggerReroute(lat, lng);
```
where `lat` and `lng` are defined at lines 510-511:
```js
var lng = gpsData.longitude;
var lat = gpsData.latitude;
```
This is correct. But at line 548 in the joining state:
```js
triggerReroute(lat, lng);
```
This also references the same variables, so it's also correct.

Wait — actually the function signature and the callback are fine. Let me re-examine the onReroute handler in nav-ui.js:
```js
locations.push({ lat: info.currentLat, lon: info.currentLng });
```
Valhalla expects `lat` and `lon` — this is correct. **False alarm on the parameter order.**

Actually, upon re-reading, the ordering is correct throughout. I'll retract this finding.

---

### 7. (Revised) Multi-leg routes produce duplicate coordinates at leg boundaries

**Location:** `nav-ui.js:222-234` (buildRouteData)

**Severity:** minor

**Evidence:** In `buildRouteData`, coordinates from each leg are concatenated:
```js
allCoords = allCoords.concat(coords);
shapeOffset += coords.length;
```
When a route has multiple legs, the last coordinate of leg N is the same point as the first coordinate of leg N+1 (the waypoint). This creates a duplicate coordinate in `allCoords`. The `shapeOffset` is set to the full concatenated length, but the maneuver `begin_shape_index` and `end_shape_index` from Valhalla are relative to each leg's shape, not the concatenated shape. The offset adjustment:
```js
mc.begin_shape_index = (mc.begin_shape_index || 0) + shapeOffset;
mc.end_shape_index = (mc.end_shape_index || 0) + shapeOffset;
```
adds `shapeOffset` before the current leg's coords are concatenated (shapeOffset is updated *after* the maneuver loop). Wait — actually `shapeOffset += coords.length` is after the concat. Let me re-read:

```js
trip.legs.forEach(function (leg) {
  var coords = decodePolyline(leg.shape);
  if (leg.maneuvers) {
    leg.maneuvers.forEach(function (m) {
      var mc = Object.assign({}, m);
      mc.begin_shape_index = (mc.begin_shape_index || 0) + shapeOffset;
      mc.end_shape_index = (mc.end_shape_index || 0) + shapeOffset;
      allManeuvers.push(mc);
    });
  }
  allCoords = allCoords.concat(coords);
  shapeOffset += coords.length;
});
```

The maneuver indices are offset by `shapeOffset` *before* `allCoords` is extended and `shapeOffset` is updated. For leg 0, `shapeOffset = 0` — correct. For leg 1, `shapeOffset = leg0.coords.length` — correct. But the duplicate point at the boundary means the indices for leg 1 maneuvers are off by 1 (pointing one coordinate too late). For a 2-leg route, the first maneuver of leg 2 will point to the duplicate waypoint instead of the actual first shape coordinate of that leg.

**Impact:** For multi-leg routes (routes with intermediate waypoints), maneuver indices for leg 2+ are off by one per previous leg boundary. This causes the wrong segment to be associated with maneuvers, leading to incorrect distance-to-maneuver calculations and potentially skipped or early voice announcements. Single-destination routes (the common case) are unaffected.

---

### 8. No compass / return-to-north button during navigation — and no way to reset bearing

**Location:** `app.js:158`, `nav-ui.js:560-576`, `style.css:661`

**Severity:** significant

**Evidence:** The `NavigationControl` is initialized with `showCompass: false` to avoid Pitfall #11 (compass re-enables dragRotate). During navigation, the map bearing is locked to GPS heading via `feedGPS`. When the user manually pans (triggering `onManualPan`), the recenter button appears — but recentering via `recenter()` calls `feedGPS()` which restores the GPS-bearing view. There is no way for the user to:

1. Reset the map to north-up orientation outside of navigation
2. During navigation, temporarily view a north-up orientation (the recenter auto-resumes after 10s anyway)

The Pitfall #11 workaround correctly disables dragRotate and removes compass, but no replacement north button is provided. The `recenter` button during navigation only restores GPS-bearing, it doesn't offer a north-up toggle.

**Impact:** Users have no way to orient the map to north. Outside navigation, right-click/shift-click orbit is the only way to rotate, but there's no reset-to-north button. During navigation, there's no north-up option at all. This matches the field report "return-to-north button missing."

---

### 9. `muted` state desynchronized between engine and UI

**Location:** `nav-ui.js:606-612` (toggleMute), `navigation.js:757` (setMuted)

**Severity:** minor

**Evidence:** The UI's `toggleMute` function updates the local `muted` variable and saves to localStorage, but never calls `nav.setMuted()`. The engine has its own `muted` flag set via `setMuted()`, but it is never called from the UI. The engine's `announce()` function checks the engine's `muted` flag, and the UI's `onVoice()` callback also checks the UI's `muted` flag.

Since `onVoice` in the UI is the voice callback registered with the engine, and the engine calls `onVoiceCb(text)` which reaches `onVoice` in nav-ui.js, the flow is: engine `announce()` checks engine `muted` -> if not muted, calls `onVoiceCb(text)` -> UI `onVoice()` checks UI `muted`. The engine's `muted` is never set to `true` because `nav.setMuted()` is never called, so the engine always passes announcements through. The UI's `onVoice` then checks UI's `muted` flag and suppresses speech if muted.

This works by accident — both paths would need to be false for speech to play. But the engine still runs all the announcement logic (string construction, `announcedSet` tracking) even when muted. More importantly, `announcedSet` marks thresholds as announced even when the UI suppresses speech. If the user un-mutes, they won't hear announcements for thresholds that were already "announced" while muted.

**Impact:** When the user mutes and then un-mutes during navigation, they won't hear announcements for maneuver thresholds that were crossed while muted. The announcements are silently consumed and marked as "done" even though the user never heard them.

---

### 10. `feedGPS` shadows outer `bearing` variable name — uses function parameter logic incorrectly

**Location:** `nav-ui.js:331-334`

**Severity:** minor

**Evidence:**
```js
function feedGPS() {
  // ...
  var heading = data.heading || data.bearing || 0;
  var speed = data.speed || 0;
  var headingValid = heading !== 0 || speed > 1;
  // ...
  var bearing = headingValid ? heading : map.getBearing();
  
  map.easeTo({
    center: [lng, lat],
    bearing: bearing,
    // ...
  });
}
```
The `headingValid` check `heading !== 0 || speed > 1` considers heading=0 as invalid unless speed >1. But a GPS heading of exactly 0 (due north) is perfectly valid when the vehicle is moving. The `data.heading || data.bearing || 0` expression also treats heading=0 as falsy, falling through to `data.bearing` or `0`. If the GPS reports heading=0 (due north) and no bearing field, this correctly resolves to 0, but then `headingValid` is `false` unless `speed > 1`. This means if speed is exactly 1 m/s heading due north, `headingValid` is false and the map won't track the GPS heading — it will use `map.getBearing()` instead.

Note this is a different heading validity check than the engine's (`gpsSpeed >= HEADING_SPEED_GATE` where HEADING_SPEED_GATE=3). The UI and engine disagree on when heading is valid.

**Impact:** Heading due north at low speed (<=1 m/s) is treated as invalid by the UI but may be valid per the engine. The map bearing and engine bearing disagree, causing visual inconsistency between the map rotation and the engine's route-following logic.

## Design Concerns

### Double-tick GPS architecture
The 500ms polling interval reading from a shared global that updates at 1Hz creates a fundamental impedance mismatch. The engine processes the same data point twice per GPS fix, causing counters (offRouteCount) and announcement checks to run at unexpected rates. The correct approach would be event-driven: the GPS WebSocket handler should push updates directly to the engine, not have a polling timer read from a shared global.

### No announcement suppression for rapid segment changes
The engine has no mechanism to suppress announcements when the vehicle is stationary or moving very slowly (parking lots, rest stops). `checkVoice` runs unconditionally on every tick regardless of speed. A speed gate on announcements would prevent the rapid-fire issue in parking lots.

### Missing `padding` parameter in all navigation map updates
All three `map.easeTo()` calls in the navigation flow (startNavigation, feedGPS, restoreMapState) omit the `padding` parameter. MapLibre's padding offsets the effective center of the map, which is how navigation apps show "road ahead." This is a consistent architectural gap, not a one-off omission.

### State machine allows JOINING -> REROUTING but reroute response puts state to NAVIGATING
When `triggerReroute` fires from the JOINING state (line 548), the state transitions to `rerouting`. When the reroute response arrives, `applyReroute` sets state to `navigating` unconditionally (line 749), skipping the JOINING phase entirely for the new route. This could be correct (the reroute starts from current position) but is undocumented and could surprise maintainers.
