# Bug Hunt Report — Navigation System (Exploratory)

## Scope

Deeply analyzed three files:
- `frontend/navigation.js` (790 lines) — navigation engine, full read
- `frontend/nav-ui.js` (882 lines) — navigation UI, full read
- `frontend/app.js` — targeted reads of GPS data flow, compass handling, route building
- `frontend/style.css` — nav overlay, sidebar-toggle, search-container z-index and positioning
- `frontend/index.html` — DOM structure and script loading order
- `frontend/stt.js` — mic button creation and positioning

**Why these files:** The navigation engine is the highest-risk code — it coordinates GPS state, route snapping, deviation detection, voice timing, and dead reckoning, all with timing-sensitive external inputs. The UI layer bridges that engine to DOM and MapLibre with its own state machine. The integration point in app.js controls the data flow.

## Bugs

### BUG-1: GPS position centered on screen instead of offset downward — road ahead not visible
**Location:** `frontend/nav-ui.js:336-342`
**Severity:** significant
**Evidence:** The `feedGPS` function calls `map.easeTo({ center: [lng, lat] })` which places the user's GPS position at the center of the viewport. During navigation with pitch=60 and bearing following heading, centering the user dot in the middle means only ~40% of the visible map shows the road ahead. Google Maps, Apple Maps, and every production navigation app offset the user position to the bottom third of the screen so the majority of the viewport shows upcoming road. MapLibre supports this via the `padding` option on `easeTo()` — e.g., `padding: { bottom: 0, top: viewportHeight * 0.4 }` to shift the center point downward.
**Impact:** Users cannot see upcoming turns, exits, or road conditions. In field testing this was reported as "nav icon centered on screen instead of bottom-locked."

### BUG-2: Voice announcements can rapid-fire when GPS jitters near a threshold boundary
**Location:** `frontend/navigation.js:336-368`
**Severity:** significant
**Evidence:** The `checkVoice` function fires an announcement when `distToNext <= thresholds[ti]` and marks it in `announcedSet` by key `nextIdx + "-" + ti`. However, the `announcedSet` is cleared on every reroute (`applyReroute`, line 745) and the entire reset. The real problem is subtler: the system has no **hysteresis** or **minimum distance between announcements**. When GPS jitters in a parking lot or roundabout, the snap point can oscillate between two segments causing `currentManeuverIdx` to jump forward and back. When it jumps forward, `nextIdx` changes, creating a *new* key in `announcedSet` — so the same physical maneuver triggers announcements under different indices. Additionally, at low speeds in roundabouts, the user passes through the far, medium, and near thresholds of multiple short maneuvers in rapid succession, all of which are individually valid but collectively produce a barrage of speech.
**Impact:** "Voice announcements rapid-fire near turns, in parking lots, and roundabouts — extremely annoying" per field reports. The `break` on line 366 prevents multiple announcements *per tick*, but rapid-fire occurs across consecutive 500ms ticks.

### BUG-3: Off-route detection counter resets on a single on-route tick, making reroute nearly impossible to trigger
**Location:** `frontend/navigation.js:577-588`
**Severity:** critical
**Evidence:** The deviation detection requires `OFF_ROUTE_TICKS = 5` *consecutive* ticks where `snap.distanceFromRoute > OFF_ROUTE_THRESHOLD (50m)`. But `offRouteCount` is reset to 0 on line 586 whenever a single tick snaps within 50m. GPS accuracy on consumer devices (and especially the Waveshare LC29H) can easily be +/- 10-15m, meaning a single favorable jitter while actually 60m off-route resets the counter. At 1 Hz ticks, the user must be >50m from the route for 5 consecutive seconds without a single favorable GPS jitter. In practice, with typical GPS noise, this threshold is almost never met — particularly on parallel roads or complex interchanges where the snap algorithm finds a segment within 50m even when the user is on a completely wrong road.
**Impact:** "Route deviation detection doesn't trigger reroutes in practice — user had to manually recalculate." The consecutive-tick requirement with hard reset is too fragile for real-world GPS noise.

### BUG-4: Multi-leg routes produce duplicate junction points, creating zero-length segments
**Location:** `frontend/nav-ui.js:222-233`
**Severity:** significant
**Evidence:** When building route data from a multi-leg trip, `allCoords = allCoords.concat(coords)` concatenates each leg's decoded polyline. In Valhalla, the last point of leg N is the same as the first point of leg N+1 (the waypoint). This creates a zero-length segment at every junction. `segmentDistances[i]` for that segment will be 0, and `projectOntoSegment` will set `t=0` with `dist=0` for any point on that coordinate. The `snapToRoute` function will snap to this degenerate segment, and `distanceToManeuver` calculations using `distanceToCoordIndex` will return incorrect distances because the cumulative distance array has a duplicate entry. The `shapeOffset` is also inflated by the duplicate point, so maneuver `begin_shape_index` / `end_shape_index` values are off-by-one per preceding leg junction.
**Impact:** On multi-waypoint routes, navigation may skip maneuvers near waypoints, or show incorrect distances to upcoming turns after the first waypoint.

### BUG-5: `heading` field in `buildState` always returns `lastValidHeading` regardless of validity
**Location:** `frontend/navigation.js:491`
**Severity:** minor
**Evidence:** Line 491 reads: `heading: headingValid ? lastValidHeading : lastValidHeading`. Both branches of the ternary return the same value. This is clearly a copy-paste error — the false branch should probably return `null` or `0` or a computed bearing from the route geometry. As written, the `headingValid` boolean is set correctly but the `heading` field always carries the last valid heading even when heading is invalid, making the `headingValid` flag partially misleading to consumers.
**Impact:** The UI already checks `headingValid` separately (in `feedGPS` via its own local `headingValid` computation), so the practical impact is limited. But any future consumer of `buildState().heading` that doesn't also check `headingValid` will use stale heading data.

### BUG-6: feedGPS heading validity check is inconsistent with engine's speed gate
**Location:** `frontend/nav-ui.js:308-310` vs `frontend/navigation.js:516-522`
**Severity:** significant
**Evidence:** The navigation engine uses `HEADING_SPEED_GATE = 3` m/s (~6.7 mph) to determine heading validity. But `feedGPS` in nav-ui.js uses a completely different test: `var headingValid = heading !== 0 || speed > 1`. This means:
- A GPS reporting heading=0 (due north) at 0.5 m/s: engine says invalid, UI says invalid (coincidentally correct but wrong reason)
- A GPS reporting heading=0 at 2 m/s: engine says invalid (speed < 3), UI says valid (speed > 1) — **UI rotates map based on heading engine considers unreliable**
- A GPS reporting heading=180 at 0 m/s (stationary): engine says invalid, UI says valid (heading !== 0) — **UI rotates map when stationary**

The UI's `headingValid` drives the `map.easeTo({ bearing })` call, so the map orientation is governed by a looser validity check than the engine uses. This causes the map to spin erratically at low speeds when the GPS chip reports noisy heading values.
**Impact:** Map bearing follows unreliable heading data at walking pace (1-3 m/s), causing disorienting map rotation. The engine correctly gates heading at 3 m/s but the UI ignores this and uses its own weaker check.

### BUG-7: Sidebar toggle and search container overlap nav overlay on mobile
**Location:** `frontend/style.css:661` and `frontend/style.css:77` vs `frontend/style.css:1229`
**Severity:** significant
**Evidence:** The sidebar toggle (`#sidebar-toggle`) has `z-index: 25` and is positioned at `top: 12px; left: 12px`. The search container (`#search-container`) has `z-index: 10` and is positioned at `top: 12px; left: 52px` (56px on desktop). The nav overlay (`#nav-overlay`) has `z-index: 22` and is positioned at `top: 0; left: 0; right: 0`. On mobile, the sidebar toggle sits at z-index 25 above the nav overlay (z-index 22), overlapping it visually. The search container is at z-index 10, below the nav overlay, so it's hidden — but neither is *repositioned* or *hidden* when navigation is active. The nav overlay and the sidebar toggle both occupy the top-left corner of the screen. The mute button inside the nav overlay is at `top: 14px; right: 14px` — potentially overlapping with the mic button in the search container on narrow screens.
**Impact:** "Sidebar hamburger + voice toggle overlap the top nav pane on mobile." The hamburger menu renders on top of the navigation instruction panel. Nothing hides or repositions the sidebar toggle or search bar during active navigation.

### BUG-8: Reroute never fires from JOINING state due to wrong parameter order
**Location:** `frontend/navigation.js:548`
**Severity:** critical
**Evidence:** On line 548, the JOINING state calls `triggerReroute(lat, lng)`. The `triggerReroute` function signature is `function triggerReroute(lat, lng)` on line 596, and it passes them to the callback as `currentLat: lat, currentLng: lng`. Then in nav-ui.js line 435, the reroute handler builds the Valhalla request as `{ lat: info.currentLat, lon: info.currentLng }`. This is internally consistent.

However, on line 582 in the NAVIGATING state's off-route path, `triggerReroute(lat, lng)` is also called — but `lat` and `lng` are defined on lines 511-512 as `var lng = gpsData.longitude` and `var lat = gpsData.latitude`. So both call sites are actually correct.

Wait — re-reading line 548: `triggerReroute(lat, lng)` in the JOINING state. But `lat` and `lng` in `tick()` are defined on lines 511-512. This is correct.

*Retracted — no bug here after careful re-read.*

### BUG-8 (actual): feedGPS polls at 500ms but engine's off-route needs 5 "1 Hz ticks"
**Location:** `frontend/nav-ui.js:295` and `frontend/navigation.js:22`
**Severity:** minor
**Evidence:** The GPS feed interval is 500ms (`setInterval(feedGPS, 500)` on line 295 of nav-ui.js). Each call invokes `nav.updateGPS()` which calls `tick()`. The off-route counter requires `OFF_ROUTE_TICKS = 5` consecutive ticks. The comment on line 22 says "consecutive 1 Hz ticks" but the actual tick rate is 2 Hz (every 500ms). This means off-route detection triggers after 2.5 seconds of continuous off-route, not 5 seconds as the constant name and comment suggest. While this doesn't cause incorrect behavior per se, it interacts with BUG-3: the 2x tick rate means twice as many opportunities for a single favorable GPS jitter to reset the counter, making the consecutive requirement even harder to meet in practice. The design intent was clearly 5 seconds (1 Hz * 5 ticks) but the implementation gives 2.5 seconds.
**Impact:** The off-route timing is half what was designed. Combined with BUG-3's fragile consecutive requirement, this makes rerouting even less likely to trigger.

## Design Concerns

### No cooldown between voice announcements across different maneuvers
The voice system has per-maneuver-per-threshold tracking (`announcedSet`) but no global cooldown. In areas with many closely-spaced maneuvers (roundabouts, parking lots, complex interchanges), the system can legitimately fire announcements for maneuver N's near threshold, then immediately maneuver N+1's far threshold, then N+1's medium threshold — all within seconds. A minimum inter-announcement gap (e.g., 3 seconds) would prevent speech overlap.

### feedGPS reads stale `_geographicaGPSData` on every poll — no freshness check
The `feedGPS` function polls `window._geographicaGPSData` every 500ms but never checks whether the data has changed since the last poll. If the GPS WebSocket stops sending updates, `feedGPS` continues feeding the same stale coordinates to the engine. The engine has its own `GPS_STALE_TIMEOUT` but the UI layer masks it by continuously feeding "fresh" data from a stale source. The `gpsHeartbeatTimer` in feedGPS resets on every poll, not on every new GPS message, so the "GPS signal delayed" banner never shows when GPS data stops updating.

### `totalDistance` derived from Valhalla `summary.length` in display units is fragile
The `buildRouteData` function (nav-ui.js line 238) converts `summary.length` from display units to meters using `window._geographicaUseImperial`. If the user changes their unit preference between route calculation and navigation start, the conversion factor will be wrong. The engine also computes its own `cumulativeDistances` from the polyline, and `remainingDistance` line 176 has a variable `d` that's computed but never used (the function returns `total - atPoint` instead). The `totalDistance` from Valhalla and the sum of `segmentDistances` may disagree due to floating-point differences between Valhalla's server-side computation and the client's haversine calculations, leading to ETA drift.

### No position de-duplication in multi-leg polyline concatenation
As noted in BUG-4, the `buildRouteData` function creates duplicate points at leg boundaries. Beyond the zero-length segment issue, this inflates `shapeOffset` by 1 per additional leg, causing maneuver shape indices to be off-by-one-per-leg. For a 3-waypoint route (2 legs), the second leg's maneuvers would have shape indices shifted by 1 extra point.
