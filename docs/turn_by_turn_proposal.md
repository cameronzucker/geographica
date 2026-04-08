# Turn-by-Turn Navigation: Technical Proposal

**Date:** 2026-04-07
**Status:** Reviewed (post-adversarial review)
**Author:** Cameron Zucker + Claude

## Executive Summary

Turn-by-turn navigation is fully feasible using the existing Geographica stack with **zero new backend services**. The implementation lives entirely in the frontend JavaScript, consuming the existing GPS WebSocket (1 Hz position updates) and Valhalla route response (maneuvers with shape indices). Estimated addition: ~1000-1200 lines of JS, moderate complexity.

---

## 1. Architecture

### Current Stack (unchanged)

```
GPS Hat (gpsd) --> FastAPI WebSocket (/gps/ws) --> Browser (1 Hz)
Valhalla (/valhalla/route) --> Browser (on-demand)
```

### Proposed Addition (frontend-only)

```
                    +---------------------------+
                    |   NavigationController     |
                    |   (new module in app.js)   |
                    +---------------------------+
                           |          |
              +------------+          +-------------+
              |                                     |
     RouteTracker                          VoiceAnnouncer
     - snap GPS to route                   - Web Speech API
     - track current maneuver              - distance-based triggers
     - detect off-route                    - queue management
     - compute remaining dist/time
     - dead reckoning on stale GPS
```

**No new services, containers, or network endpoints.** The entire navigation engine runs in the browser, driven by the existing GPS WebSocket `onmessage` callback at 1 Hz.

### Remote Client Considerations

On AREDN mesh networks, the browser typically runs on a different device than the Pi (a phone, tablet, or laptop connected to the mesh). This has several implications:

- **GPS data travels over the mesh with latency.** The WebSocket connection between the Pi's GPS service and the client browser adds network delay. The GPS heartbeat timeout (Section 2.6) handles this.
- **Voice plays on the client device.** `speechSynthesis` runs in the client browser, which is correct for a phone user navigating in-vehicle but may be unexpected on a desktop monitoring station. Navigation is designed for the device in the user's hands, not the Pi.
- **Client device capabilities vary.** TTS voice quality, map rendering performance, and screen size all depend on the client. The implementation should degrade gracefully (visual-only fallback, reduced animation).

**Design principle:** Navigation is designed for the device in the user's hands, not the Pi. The Pi is a data server; the client is the navigation device.

### Data Flow

1. User calculates a route (existing `requestRoute()` flow).
2. User taps "Start Navigation" button (new).
3. `NavigationController` stores the decoded polyline coordinates and maneuver list.
4. On each GPS WebSocket message (1 Hz):
   - Snap GPS position to nearest point on route polyline.
   - Determine current segment index and map to current maneuver via `begin_shape_index` / `end_shape_index`.
   - Compute distance remaining to next maneuver.
   - Update the navigation UI (instruction card, distance countdown, ETA).
   - Evaluate voice announcement triggers.
   - Check off-route threshold; if exceeded, trigger reroute.
5. On GPS staleness (no message for 3+ seconds):
   - Extrapolate position along polyline at last-known speed (dead reckoning) for up to 30 seconds.
   - Mark UI as "estimated position."
   - Pause off-route detection.

### State Machine

```
IDLE --> JOINING --> NAVIGATING --> ARRIVED
  ^                    |
  |                    v
  +-------------- REROUTING
```

- **IDLE**: No active navigation. Normal map behavior.
- **JOINING**: Transitional state after "Start Navigation" is pressed. Tolerates up to 200m offset from the route start and attempts to snap to the nearest route segment. Transitions to NAVIGATING once within 50m of the route. Transitions to REROUTING if still >200m after 15 seconds.
- **NAVIGATING**: GPS is being tracked along route. UI shows navigation overlay.
- **REROUTING**: Off-route detected. Automatic Valhalla request from current GPS position to original destination (preserving remaining waypoints). Returns to NAVIGATING on success.
- **ARRIVED**: Geofence-based arrival triggered. Shows arrival notification, returns to IDLE.

---

## 2. Position Tracking Algorithm

### 2.1 Snap GPS to Route (Point-to-Polyline Projection)

The core algorithm projects the GPS position onto the nearest segment of the route polyline. This runs once per second (1 Hz GPS rate).

When two candidate segments are within 10m distance of each other, heading-weighted snap disambiguation is applied. The GPS heading is compared against each segment's bearing, and a penalty is added for misalignment:

```
score = distance + headingPenalty * (1 - cos(headingDiff))
```

where `headingPenalty = 30m`. This resolves ambiguity at parallel roads, highway on/off ramps, and U-turn locations where pure distance is insufficient.

```
function snapToRoute(gpsLng, gpsLat, gpsHeading, routeCoords, searchStartIndex):
    bestScore = Infinity
    bestIndex = searchStartIndex
    bestProjection = null
    candidates = []

    # Only search forward from last known position (+ small lookback)
    startIdx = max(0, searchStartIndex - 3)
    endIdx = min(routeCoords.length - 1, searchStartIndex + 50)

    for i = startIdx to endIdx - 1:
        A = routeCoords[i]      # [lng, lat]
        B = routeCoords[i + 1]  # [lng, lat]

        projection = projectPointOnSegment(gpsLng, gpsLat, A, B)
        dist = haversineDistance(gpsLng, gpsLat, projection.lng, projection.lat)

        candidates.push({ index: i, projection, dist })

    # Sort by distance and apply heading disambiguation for close candidates
    candidates.sort(by dist)
    best = candidates[0]

    if candidates.length > 1 AND candidates[1].dist - best.dist < 10:
        # Ambiguous — use heading to disambiguate
        HEADING_PENALTY = 30  # meters
        for each candidate in candidates where dist < best.dist + 10:
            segBearing = bearing(routeCoords[candidate.index],
                                 routeCoords[candidate.index + 1])
            headingDiff = gpsHeading - segBearing
            candidate.score = candidate.dist +
                HEADING_PENALTY * (1 - cos(headingDiff))
        best = candidate with lowest score

    return {
        segmentIndex: best.index,
        snappedPosition: best.projection,
        distanceFromRoute: best.dist   # meters
    }
```

### 2.2 Point-to-Segment Projection

```
function projectPointOnSegment(px, py, ax, ay, bx, by):
    dx = bx - ax
    dy = by - ay
    lenSq = dx * dx + dy * dy

    if lenSq == 0:
        return { lng: ax, lat: ay, t: 0 }

    t = clamp(((px - ax) * dx + (py - ay) * dy) / lenSq, 0, 1)

    return {
        lng: ax + t * dx,
        lat: ay + t * dy,
        t: t    # fractional position along segment [0,1]
    }
```

**Note:** At the scale of individual road segments (tens of meters), Euclidean projection on lat/lng is sufficiently accurate. Haversine is only needed for the distance measurement, not the projection itself.

### 2.3 Map Segment Index to Current Maneuver

Valhalla maneuvers include `begin_shape_index` and `end_shape_index` fields referencing the decoded polyline array. Mapping is direct:

```
function findCurrentManeuver(segmentIndex, maneuvers):
    for i = 0 to maneuvers.length - 1:
        m = maneuvers[i]
        if segmentIndex >= m.begin_shape_index AND segmentIndex < m.end_shape_index:
            return i
        # Edge case: last maneuver (destination)
        if i == maneuvers.length - 1 AND segmentIndex >= m.begin_shape_index:
            return i
    return 0  # fallback
```

### 2.4 Distance to Next Maneuver

```
function distanceToManeuver(segmentIndex, snappedPoint, targetShapeIndex, routeCoords):
    totalDist = 0

    # Partial distance from snapped point to end of current segment
    totalDist += haversine(snappedPoint, routeCoords[segmentIndex + 1])

    # Full segments between current and target
    for i = segmentIndex + 1 to targetShapeIndex - 1:
        totalDist += haversine(routeCoords[i], routeCoords[i + 1])

    return totalDist  # meters
```

### 2.5 Search Window Optimization

To avoid O(n) polyline search on every GPS tick, the algorithm maintains a `lastSegmentIndex` and only searches a window around it. The forward bias (50 segments ahead vs 3 behind) accounts for normal forward travel while allowing minor GPS jitter or brief backward movement.

**Full-polyline fallback:** If the windowed search produces a best distance > 100m, the algorithm performs a full-polyline search before declaring off-route. This prevents false reroutes at sharp switchbacks, GPS multipath errors, or when the window fails to cover a complex route geometry (e.g., stacked highway interchanges).

### 2.6 GPS Heartbeat Timeout

The client maintains a freshness timer for GPS data. If no WebSocket message is received within 3 seconds, the GPS is treated as stale:

- Navigation updates pause (no snap recalculation).
- A "GPS data delayed" indicator appears in the navigation overlay.
- Dead reckoning engages if conditions are met (see Section 3, Dead Reckoning).
- Off-route detection is suspended.

This is especially important on AREDN mesh networks where GPS data travels from the Pi to the client over a wireless link with variable latency and potential dropouts.

---

## 3. Off-Route Detection and Recovery

### Strategy

```
OFF_ROUTE_THRESHOLD = 50 meters   # distance from route polyline
OFF_ROUTE_COUNT     = 5           # consecutive 1 Hz ticks (5 seconds)
REROUTE_COOLDOWN    = 15 seconds  # minimum time between reroute requests
```

**Algorithm:**

```
on each GPS tick:
    snap = snapToRoute(gpsPos, routeCoords, lastIndex)

    if snap.distanceFromRoute > OFF_ROUTE_THRESHOLD:
        offRouteCounter++
    else:
        offRouteCounter = 0

    if offRouteCounter >= OFF_ROUTE_COUNT:
        if timeSince(lastReroute) > REROUTE_COOLDOWN:
            triggerReroute(gpsPos, originalDestination, remainingWaypoints)
```

### Why 50 meters?

- GPS accuracy on the Waveshare LC2H is typically 2-5 meters CEP with clear sky, degrading to 10-30 meters in urban canyons.
- 50 meters provides adequate margin above worst-case GPS error while catching genuine wrong turns within a few seconds.
- The counter-based approach (5 consecutive ticks) prevents single-sample GPS spikes from triggering unnecessary reroutes.

### Reroute Flow

1. Set state to `REROUTING`. Show "Recalculating..." in the UI.
2. Cancel any in-flight reroute request using `AbortController`. Track a request sequence number; ignore responses with stale sequence numbers that arrive after a newer request was issued.
3. Fire a Valhalla `/route` request from current GPS position to original destination, using the same costing model and options. **Preserve remaining waypoints:** include all unvisited waypoints (those whose via-point index > current leg index) in the Valhalla request.
4. On success: replace route polyline and maneuver list, reset tracking state, return to `NAVIGATING`.
5. On failure (no route found, network error): show error, remain in `REROUTING`, retry on next off-route detection after cooldown.

### Dead Reckoning During GPS Blackouts

When GPS goes stale (no update for 3+ seconds), the navigation engine extrapolates position along the route polyline at the last-known speed:

```
function deadReckon(lastSnappedIndex, lastSnappedPoint, lastSpeed, elapsedSeconds):
    if elapsedSeconds > 30: return null  # max dead reckoning window

    distToTravel = lastSpeed * elapsedSeconds  # meters
    return advanceAlongPolyline(lastSnappedIndex, lastSnappedPoint, distToTravel)
```

- **UI indication:** The position marker changes style (e.g., pulsing outline, dimmed color) and a "GPS signal lost - estimated position" label appears.
- **Off-route detection is suspended** during dead reckoning.
- **Dead reckoning expires after 30 seconds.** Beyond that, the position is too unreliable. The display freezes at the last estimated position until GPS returns.
- When GPS resumes, the snapping algorithm resumes normally from the actual GPS position, discarding the dead-reckoned estimate.

### Geofence-Based Arrival

Arrival is triggered when **both** conditions are met:

1. The GPS position is within 30m of the destination point.
2. The snapped position is on one of the final 3 segments of the route polyline.

This dual-condition approach prevents premature arrival triggers when a route passes near the destination before reaching it (e.g., a route that loops back).

---

## 4. Voice Announcements

### 4.1 Web Speech API Availability

The `window.speechSynthesis` API (Web Speech API) is the only viable option for offline voice on the browser.

**Offline support by platform:**

| Platform | Offline TTS | Notes |
|----------|-------------|-------|
| Chromium (desktop Linux) | Yes | Uses espeak-ng or platform voices. Raspberry Pi OS Chromium ships with espeak-ng. |
| Firefox (Linux) | Partial | Uses speech-dispatcher + espeak-ng if installed. May need `sudo apt install espeak-ng speech-dispatcher`. |
| Chromium (Android) | Yes | Uses Android system TTS (usually Google TTS, but works offline with downloaded voice packs). |
| Safari (iOS/macOS) | Yes | Built-in system voices work offline. |

**For the Pi 5 deployment:** Chromium is the expected browser. Offline TTS works via espeak-ng, which is included in Raspberry Pi OS. Voice quality is robotic but intelligible. Higher-quality voices can be installed (`sudo apt install mbrola mbrola-us1`) but are not required.

**Recommendation:** Use `speechSynthesis` as the primary mechanism. Provide a mute/unmute toggle. No fallback needed since this is the only option without internet.

### 4.2 Announcement Triggers

Distance-based triggers using the Valhalla `verbal_pre_transition_instruction` and `verbal_transition_alert_instruction` fields:

```
ANNOUNCEMENT_THRESHOLDS (driving):
    FAR:    800 meters  (0.5 mi)  "In half a mile, turn right on Main Street"
    MEDIUM: 200 meters  (0.1 mi)  "In 200 meters, turn right on Main Street"  
    NEAR:    50 meters            "Turn right on Main Street"

ANNOUNCEMENT_THRESHOLDS (bicycle):
    FAR:    400 meters
    MEDIUM: 100 meters
    NEAR:    30 meters

ANNOUNCEMENT_THRESHOLDS (pedestrian):
    FAR:    200 meters
    MEDIUM:  50 meters
    NEAR:    20 meters
```

### 4.3 Announcement Queue and Deduplication

```
function announceIfNeeded(distToNextManeuver, currentManeuverIndex, maneuvers):
    maneuver = maneuvers[currentManeuverIndex + 1]  # upcoming maneuver
    if not maneuver: return

    for each threshold in [FAR, MEDIUM, NEAR]:
        if distToNextManeuver <= threshold.distance:
            key = currentManeuverIndex + "-" + threshold.name
            if key not in announcedSet:
                announcedSet.add(key)
                speak(formatAnnouncement(maneuver, threshold, distToNextManeuver))
            break  # only announce closest threshold not yet spoken
```

### 4.4 Voice Text Sources

Valhalla provides pre-formatted voice text in each maneuver:

- `verbal_transition_alert_instruction`: e.g., "In 500 feet, turn right onto Main Street" -- used for FAR/MEDIUM thresholds.
- `verbal_pre_transition_instruction`: e.g., "Turn right onto Main Street" -- used for NEAR threshold.
- `instruction`: Fallback text if verbal fields are missing.

These are ready-to-speak strings. No text generation is needed in the frontend.

### 4.5 Implementation

```
function speak(text):
    if not navigationMuted and window.speechSynthesis:
        utterance = new SpeechSynthesisUtterance(text)
        utterance.rate = 1.0
        utterance.lang = 'en-US'
        
        # Cancel any currently speaking utterance to prevent queue buildup
        speechSynthesis.cancel()
        speechSynthesis.speak(utterance)
```

**Voice priming:** Chromium on Linux sometimes has a bug where `speechSynthesis.speak()` silently fails if called without a prior user gesture. The "Start Navigation" button click handler explicitly primes the audio context:

```
startNavigationButton.addEventListener('click', () => {
    speechSynthesis.speak(new SpeechSynthesisUtterance(''))
    startNavigation()
})
```

This empty utterance unlocks the speech synthesis pipeline before any real announcements are needed.

---

## 5. UI Design

### 5.1 Navigation Overlay (new element, top of map)

When navigation is active, a card overlays the top of the map:

```
+--------------------------------------------------+
|  [Arrow Icon]   Turn right on Main Street         |
|                 0.3 mi                            |
|  [Lane hint]    Use left lane                     |
+--------------------------------------------------+
|  [Secondary]    Then: Slight left on Oak Ave      |
+--------------------------------------------------+
|  12.4 mi remaining  |  ETA 2:35 PM  |  23 min    |
|  [Speed limit: 45 mph]                            |
+--------------------------------------------------+
```

- **Maneuver icon**: SVG arrow matching Valhalla maneuver `type` (straight=0, right=1, left=2, etc.). A set of ~15 icons covers all Valhalla maneuver types.
- **Instruction text**: From `instruction` field.
- **Distance countdown**: Live-updating distance to next maneuver (computed each GPS tick).
- **Lane guidance**: When the Valhalla maneuver includes a `lanes` array, display a text hint such as "Use left lane" or "Use right 2 lanes." Active lanes (those with `active: true` in the array) are summarized into a human-readable string.
- **Next-after-next preview**: When `maneuvers[current+2]` is within 500m of `maneuvers[current+1]`, show a secondary hint row: "Then: [next-next instruction]". This prepares the driver for closely spaced maneuvers (e.g., "Turn right, then immediately turn left").
- **Bottom bar**: Total remaining distance, ETA (current time + remaining seconds), total remaining time.
- **Speed-ratio ETA adjustment**: Compute a rolling ratio of actual GPS speed vs. Valhalla expected speed over a 60-second window. Adjust the remaining time estimate by this ratio so ETA reflects actual driving pace rather than Valhalla's modeled speeds.
- **Speed limit display**: When the current Valhalla maneuver includes `speed_limit` data, display the posted speed limit. Optionally highlight when GPS speed exceeds the limit.

### 5.2 Maneuver Type to Icon Mapping

Valhalla maneuver types that need icons:

| Type | Meaning | Icon |
|------|---------|------|
| 0 | None | Arrow straight |
| 1 | Start | Flag |
| 2 | Start right | Arrow up-right |
| 3 | Start left | Arrow up-left |
| 4 | Destination | Checkered flag |
| 5 | Destination right | Flag right |
| 6 | Destination left | Flag left |
| 7 | Becomes | Arrow straight |
| 8 | Continue | Arrow straight |
| 9 | Slight right | Arrow slight-right |
| 10 | Right | Arrow right |
| 11 | Sharp right | Arrow sharp-right |
| 12 | U-turn right | U-turn right |
| 13 | U-turn left | U-turn left |
| 14 | Sharp left | Arrow sharp-left |
| 15 | Left | Arrow left |
| 16 | Slight left | Arrow slight-left |
| 17 | Ramp straight | Arrow straight |
| 18 | Ramp right | Arrow right |
| 19 | Ramp left | Arrow left |
| 20 | Exit right | Arrow exit-right |
| 21 | Exit left | Arrow exit-left |
| 22 | Stay straight | Arrow straight |
| 23 | Stay right | Arrow slight-right |
| 24 | Stay left | Arrow slight-left |
| 25 | Merge | Arrow merge |
| 26 | Roundabout enter | Roundabout |
| 27 | Roundabout exit | Roundabout |
| 28 | Ferry enter | Ferry |
| 29 | Ferry exit | Ferry |

Inline SVGs (not external files) to ensure offline operation. A single function maps type number to SVG path data.

### 5.3 Map Behavior During Navigation

- **Auto-center**: Map follows GPS position, centered slightly below mid-screen (60/40 split) so more road ahead is visible.
- **Auto-rotate**: Map bearing matches GPS heading for a "heads-up" driving view.
- **Heading speed gate**: Only use GPS heading for map rotation when speed > 3 m/s (~7 mph). Below that threshold, freeze bearing at the last valid heading. This prevents erratic map spinning at stoplights and in parking lots where GPS heading is unreliable.
- **Auto-zoom**: Zoom level adjusts based on speed (higher speed = lower zoom). Suggested: `zoom = clamp(18 - speed_mph / 15, 13, 18)`.
- **User interaction override**: If the user pans or pinches the map, auto-center pauses for 10 seconds, then resumes. A "Re-center" button appears during the pause.
- **Navigation mode performance**: Entering navigation disables 3D terrain rendering and hillshade layers to ensure smooth camera animation on resource-constrained devices. The terrain toggle in the UI is grayed out with a tooltip: "Disabled during navigation." Terrain is automatically re-enabled when navigation ends.
- **Save/restore map state**: On entering navigation, save the current map state: `{center, zoom, pitch, bearing, terrainEnabled}`. On exiting navigation (stop or arrival), restore these saved values so the user returns to their previous view.

### 5.4 Mode Conflict Resolution

The map has multiple systems that want to control the camera. Priority hierarchy (highest first):

1. **Navigation auto-center** -- when navigation is active, the camera follows GPS. This takes priority over all other camera controls.
2. **Manual pan (temporary)** -- user touch/mouse interaction pauses auto-center for 10 seconds. A "Re-center" button appears. After timeout or button press, navigation auto-center resumes.
3. **Overview button** -- temporarily shows the full remaining route, then returns to auto-center.
4. **Free-look camera** -- the existing free-look (terrain exploration) camera mode is **disabled** during navigation. The free-look toggle is hidden or grayed out while navigating.

This hierarchy ensures the navigation camera is never fighting with other camera modes. Manual pan is the only intentional override, and it self-resolves.

### 5.5 Controls

- **Start Navigation** button: Appears in the route panel after a route is calculated. Enters JOINING state. If the route start point is the user's GPS position (start=GPS), auto-offer navigation with a prompt: "Start navigation?"
- **Stop Navigation** button: Replaces "Start Navigation" during active navigation. Returns to IDLE and restores saved map state.
- **Mute/Unmute** button: Toggles voice announcements. Persists in localStorage.
- **Overview** button: Temporarily zooms out to show the full remaining route.

### 5.6 Existing UI Integration

The navigation overlay is a new `<div id="nav-overlay">` positioned above the map with `position: absolute; top: 0; z-index` above the map but below modals. It does not modify the existing sidebar route panel, which continues to show the full maneuver list.

The "Start Navigation" button is added to the route panel after `#export-route-btn`.

---

## 6. Implementation Estimate

### New Code

| Component | Lines (approx) | Complexity |
|-----------|----------------|------------|
| NavigationController (state machine, GPS handler, JOINING state) | 160 | Medium |
| Route snapping (point-to-segment, search window, heading disambiguation) | 120 | Medium |
| Maneuver tracking (index mapping, distance calc, next-next preview) | 80 | Low |
| Off-route detection, reroute with AbortController and waypoints | 100 | Medium |
| Dead reckoning and GPS heartbeat timeout | 60 | Medium |
| Voice announcements (Web Speech API wrapper, priming) | 60 | Low |
| Navigation UI (overlay DOM, instruction card, lane hints, speed limit) | 150 | Low |
| Map behavior (auto-center, auto-rotate, auto-zoom, save/restore, speed gate) | 90 | Medium |
| Maneuver SVG icons (type-to-SVG mapping) | 80 | Low |
| CSS for navigation overlay | 80 | Low |
| ETA speed-ratio calculation | 30 | Low |
| **Total** | **~1010-1200** | **Medium overall** |

### Modified Code

| File | Change | Lines |
|------|--------|-------|
| `app.js` | Hook `updateGPSPosition()` to call NavigationController | ~10 |
| `app.js` | Hook `renderRoute()` to enable "Start Navigation" button | ~5 |
| `app.js` | Store route data (polyline coords, maneuvers) in module state | ~10 |
| `app.js` | Disable free-look camera and terrain during navigation | ~15 |
| `index.html` | Add nav overlay div and Start/Stop/Mute buttons | ~30 |
| `style.css` | Navigation overlay styles | ~80 |

### Utility Functions Already Available

- `decodePolyline()` -- already implemented (line 910 of app.js)
- `haversineDistance()` -- need to add, but `createGeoJSONCircle()` already has the math
- `formatDistance()` -- already implemented

### No New Dependencies

Everything uses built-in browser APIs:
- `speechSynthesis` for voice
- `AbortController` for reroute request cancellation
- `performance.now()` for timing
- `localStorage` for route persistence and mute state
- DOM manipulation (existing pattern throughout app.js)

---

## 7. Risks and Limitations

### 7.1 GPS Accuracy

**Risk:** The Waveshare LC2H GPS hat has ~2-5m accuracy outdoors but can degrade to 30m+ near buildings or under tree cover. Poor accuracy causes jittery snapping and potential false off-route detections.

**Mitigation:** The 5-second off-route counter, the `accuracy` field from the GPS service (available but currently unused for routing), and the 50m threshold together provide adequate buffering. Could additionally skip navigation updates when `accuracy > 40m`.

### 7.2 Tunnels and GPS Blackouts

**Risk:** GPS signal is lost in tunnels, parking garages, and dense urban canyons. The GPS service will report `stale: true`.

**Mitigation:** Dead reckoning extrapolates position along the route polyline at last-known speed for up to 30 seconds (Section 3). UI shows "GPS signal lost - estimated position" indicator. Off-route detection is suspended. When GPS fix returns, the snap algorithm resumes from the actual GPS position.

### 7.3 Web Speech API Quality

**Risk:** espeak-ng voices on Linux are robotic and occasionally hard to understand at speed, especially for street names with unusual pronunciations.

**Mitigation:** This is a known limitation with no offline fix. Higher-quality MBROLA voices can be installed on the Pi. The visual instruction card is the primary guidance mechanism; voice is supplementary.

### 7.4 Valhalla Reroute Latency

**Risk:** Valhalla route calculation on the Pi 5 takes 0.5-3 seconds depending on distance. During reroute, the user has no guidance.

**Mitigation:** Show "Recalculating..." with a spinner. Continue showing the last known instruction. The 15-second reroute cooldown prevents hammering Valhalla with requests during sustained off-route periods (e.g., user intentionally detouring). In-flight reroute requests are cancelled via `AbortController` before issuing a new one.

### 7.5 Map Rotation Performance

**Risk:** Continuous map bearing changes (auto-rotate with heading) may cause jank on MapLibre GL JS with 3D terrain enabled on the Pi 5.

**Mitigation:** Navigation mode disables 3D terrain and hillshade entirely (Section 5.3), eliminating this concern. Use `map.easeTo()` with short duration (200ms) rather than `jumpTo()` for smoother interpolation.

### 7.6 Battery / Power

**Non-risk:** The Pi 5 is mains-powered in the intended AREDN deployment. No battery concerns. Client devices (phones, laptops) on the mesh may have battery constraints, but navigation display updates are lightweight (1 Hz DOM updates + occasional voice).

### 7.7 Multi-Leg Routes / Waypoints

**Risk:** The current route panel supports waypoints (`#add-waypoint-btn` exists in HTML). Navigation must handle multi-leg routes where maneuver shape indices reset per leg.

**Mitigation:** When storing the route, flatten all legs into a single coordinate array and reindex maneuver shape indices to be globally contiguous (the current `renderRoute()` already does `allCoords.concat()` and `allManeuvers.concat()` but does not reindex). Must add shape index offset per leg, and skip duplicate start/end vertices at leg boundaries:

```
offset = 0
for each leg:
    coords = decode(leg.shape)
    if offset > 0:
        coords = coords.slice(1)  # skip duplicate vertex at leg boundary
    for each maneuver in leg:
        maneuver.begin_shape_index += offset
        maneuver.end_shape_index += offset
    offset += coords.length
```

### 7.8 No Offline Speech Synthesis on Some Linux Browsers

**Risk:** Firefox on Linux may not have speech synthesis available without `speech-dispatcher` and `espeak-ng` packages installed.

**Mitigation:** Check `window.speechSynthesis` existence and `speechSynthesis.getVoices().length > 0` at startup. If unavailable, hide the mute button and rely on visual-only navigation. Log a console warning.

---

## 8. Resolved Design Decisions

These were originally open questions, resolved during adversarial review:

1. **Auto-offer navigation when start=GPS:** Yes. When the user sets start=GPS and calculates a route, the UI prompts "Start navigation?" This is the natural UX shortcut for the common case.

2. **Persist active route in localStorage:** Yes. The full Valhalla response, current maneuver index, and navigation state are persisted. On page reload (Pi reboot, browser refresh), navigation can resume from the last known position without recalculating.

3. **Night mode:** Yes, auto-switch. Use system clock with a simple 7 PM - 6 AM window to switch to Dark Matter basemap during navigation. A more sophisticated sunset/sunrise calculation based on GPS latitude/longitude can be added later but is not required for v1.

4. **Speed limit display:** Yes, show it when Valhalla provides `speed_limit` data on the current maneuver. Display in the navigation overlay bottom bar. Highlight (e.g., red text) when GPS speed exceeds the limit.

5. **Arrival radius:** 30m confirmed, combined with geofence-based arrival (must also be snapped to final 3 segments of the route). See Section 3.

---

## 9. Recommendation

**Proceed with implementation.** The feature is entirely frontend-side, uses no new dependencies, and integrates cleanly with the existing GPS and Valhalla services. The core algorithm (point-to-polyline snapping + maneuver index lookup) is well-understood and computationally trivial at 1 Hz on a Pi 5.

Suggested implementation order:

1. Route snapping and maneuver tracking (core algorithm, heading disambiguation)
2. Navigation UI overlay (instruction card, distance, ETA, lane hints)
3. State machine with JOINING state
4. Map auto-center, auto-rotate, speed gate, terrain disable
5. Off-route detection and reroute (with AbortController, waypoint preservation)
6. Dead reckoning and GPS heartbeat timeout
7. Voice announcements (with priming)
8. Maneuver icons
9. Polish (localStorage persistence, night mode, speed limit, next-next preview, speed-ratio ETA, save/restore map state)

Steps 1-5 form a usable MVP. Steps 6-9 are enhancements.

---

## Changelog

### Round 1: Claude Adversarial Review (2026-04-07)

- Section 2.1: Added heading-weighted snap disambiguation for ambiguous segments within 10m
- Section 2.5: Added full-polyline fallback when windowed search distance exceeds 100m
- Section 3: Added speed-based dead reckoning during GPS blackouts (30-second window)
- Section 3: Added geofence-based arrival (30m radius AND final 3 segments)
- Section 4.5: Made voice priming explicit with code example in Start Navigation handler
- Section 5.1: Added next-after-next preview when maneuver+2 is within 500m
- Section 5.1: Added speed-ratio ETA adjustment using 60-second rolling window
- Section 5.1: Added lane guidance text hints from Valhalla `lanes` array
- Section 5.3: Added save/restore map state on navigation enter/exit
- Section 8: Resolved all five open questions with concrete decisions

### Round 2: Codex Review (2026-04-07)

- Section 1: Added Remote Client Considerations section (AREDN mesh latency, client-side voice)
- Section 1: Added JOINING state to state machine (200m tolerance, 50m transition, 15s timeout)
- Section 2.6: Added GPS heartbeat timeout (3-second freshness timer)
- Section 3: Added reroute concurrency control with AbortController and sequence numbers
- Section 3: Reroute now preserves remaining unvisited waypoints
- Section 5.3: Added heading speed gate (freeze bearing below 3 m/s)
- Section 5.3: Navigation mode disables 3D terrain and hillshade for performance
- Section 5.4: Added mode conflict resolution priority hierarchy
- Section 6: Updated line estimate to ~1000-1200 lines
- Section 7.7: Fixed multi-leg boundary handling (skip duplicate vertices, offset maneuver indices)
