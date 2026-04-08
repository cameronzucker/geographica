# Turn-by-Turn Navigation: Technical Proposal

**Date:** 2026-04-07
**Status:** Draft / Research
**Author:** Cameron Zucker + Claude

## Executive Summary

Turn-by-turn navigation is fully feasible using the existing Geographica stack with **zero new backend services**. The implementation lives entirely in the frontend JavaScript, consuming the existing GPS WebSocket (1 Hz position updates) and Valhalla route response (maneuvers with shape indices). Estimated addition: ~600-800 lines of JS, moderate complexity.

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
```

**No new services, containers, or network endpoints.** The entire navigation engine runs in the browser, driven by the existing GPS WebSocket `onmessage` callback at 1 Hz.

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

### State Machine

```
IDLE --> NAVIGATING --> ARRIVED
  ^         |
  |         v
  +---- REROUTING
```

- **IDLE**: No active navigation. Normal map behavior.
- **NAVIGATING**: GPS is being tracked along route. UI shows navigation overlay.
- **REROUTING**: Off-route detected. Automatic Valhalla request from current GPS position to original destination. Returns to NAVIGATING on success.
- **ARRIVED**: Final maneuver reached (type 4 = destination). Shows arrival notification, returns to IDLE.

---

## 2. Position Tracking Algorithm

### 2.1 Snap GPS to Route (Point-to-Polyline Projection)

The core algorithm projects the GPS position onto the nearest segment of the route polyline. This runs once per second (1 Hz GPS rate).

```
function snapToRoute(gpsLng, gpsLat, routeCoords, searchStartIndex):
    bestDist = Infinity
    bestIndex = searchStartIndex
    bestProjection = null

    # Only search forward from last known position (+ small lookback)
    startIdx = max(0, searchStartIndex - 3)
    endIdx = min(routeCoords.length - 1, searchStartIndex + 50)

    for i = startIdx to endIdx - 1:
        A = routeCoords[i]      # [lng, lat]
        B = routeCoords[i + 1]  # [lng, lat]

        projection = projectPointOnSegment(gpsLng, gpsLat, A, B)
        dist = haversineDistance(gpsLng, gpsLat, projection.lng, projection.lat)

        if dist < bestDist:
            bestDist = dist
            bestIndex = i
            bestProjection = projection

    return {
        segmentIndex: bestIndex,
        snappedPosition: bestProjection,
        distanceFromRoute: bestDist   # meters
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

If no segment within the window is closer than the off-route threshold, the algorithm falls back to a full polyline search before declaring off-route. This prevents false reroutes at sharp switchbacks or GPS multipath errors.

---

## 3. Off-Route Detection

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
            triggerReroute(gpsPos, originalDestination)
```

### Why 50 meters?

- GPS accuracy on the Waveshare LC2H is typically 2-5 meters CEP with clear sky, degrading to 10-30 meters in urban canyons.
- 50 meters provides adequate margin above worst-case GPS error while catching genuine wrong turns within a few seconds.
- The counter-based approach (5 consecutive ticks) prevents single-sample GPS spikes from triggering unnecessary reroutes.

### Reroute Flow

1. Set state to `REROUTING`. Show "Recalculating..." in the UI.
2. Fire a Valhalla `/route` request from current GPS position to original destination, using the same costing model and options.
3. On success: replace route polyline and maneuver list, reset tracking state, return to `NAVIGATING`.
4. On failure (no route found, network error): show error, remain in `REROUTING`, retry on next off-route detection after cooldown.

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

**Known issue:** Chromium on Linux sometimes has a bug where `speechSynthesis.speak()` silently fails if called without a prior user gesture. Workaround: trigger a silent utterance on the "Start Navigation" button click to prime the audio context.

---

## 5. UI Design

### 5.1 Navigation Overlay (new element, top of map)

When navigation is active, a card overlays the top of the map:

```
+--------------------------------------------------+
|  [Arrow Icon]   Turn right on Main Street         |
|                 0.3 mi                            |
+--------------------------------------------------+
|  12.4 mi remaining  |  ETA 2:35 PM  |  23 min    |
+--------------------------------------------------+
```

- **Maneuver icon**: SVG arrow matching Valhalla maneuver `type` (straight=0, right=1, left=2, etc.). A set of ~15 icons covers all Valhalla maneuver types.
- **Instruction text**: From `instruction` field.
- **Distance countdown**: Live-updating distance to next maneuver (computed each GPS tick).
- **Bottom bar**: Total remaining distance, ETA (current time + remaining seconds), total remaining time.

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
- **Auto-zoom**: Zoom level adjusts based on speed (higher speed = lower zoom). Suggested: `zoom = clamp(18 - speed_mph / 15, 13, 18)`.
- **User interaction override**: If the user pans or pinches the map, auto-center pauses for 10 seconds, then resumes. A "Re-center" button appears during the pause.

### 5.4 Controls

- **Start Navigation** button: Appears in the route panel after a route is calculated. Enters NAVIGATING state.
- **Stop Navigation** button: Replaces "Start Navigation" during active navigation. Returns to IDLE.
- **Mute/Unmute** button: Toggles voice announcements. Persists in localStorage.
- **Overview** button: Temporarily zooms out to show the full remaining route.

### 5.5 Existing UI Integration

The navigation overlay is a new `<div id="nav-overlay">` positioned above the map with `position: absolute; top: 0; z-index` above the map but below modals. It does not modify the existing sidebar route panel, which continues to show the full maneuver list.

The "Start Navigation" button is added to the route panel after `#export-route-btn`.

---

## 6. Implementation Estimate

### New Code

| Component | Lines (approx) | Complexity |
|-----------|----------------|------------|
| NavigationController (state machine, GPS handler) | 120 | Medium |
| Route snapping (point-to-segment, search window) | 80 | Medium |
| Maneuver tracking (index mapping, distance calc) | 60 | Low |
| Off-route detection and reroute | 70 | Medium |
| Voice announcements (Web Speech API wrapper) | 50 | Low |
| Navigation UI (overlay DOM, instruction card, icons) | 120 | Low |
| Map behavior (auto-center, auto-rotate, auto-zoom) | 60 | Low |
| Maneuver SVG icons (type-to-SVG mapping) | 80 | Low |
| CSS for navigation overlay | 60 | Low |
| **Total** | **~700** | **Medium overall** |

### Modified Code

| File | Change | Lines |
|------|--------|-------|
| `app.js` | Hook `updateGPSPosition()` to call NavigationController | ~10 |
| `app.js` | Hook `renderRoute()` to enable "Start Navigation" button | ~5 |
| `app.js` | Store route data (polyline coords, maneuvers) in module state | ~10 |
| `index.html` | Add nav overlay div and Start/Stop/Mute buttons | ~25 |
| `style.css` | Navigation overlay styles | ~60 |

### Utility Functions Already Available

- `decodePolyline()` -- already implemented (line 910 of app.js)
- `haversineDistance()` -- need to add, but `createGeoJSONCircle()` already has the math
- `formatDistance()` -- already implemented

### No New Dependencies

Everything uses built-in browser APIs:
- `speechSynthesis` for voice
- `performance.now()` for timing
- DOM manipulation (existing pattern throughout app.js)

---

## 7. Risks and Limitations

### 7.1 GPS Accuracy

**Risk:** The Waveshare LC2H GPS hat has ~2-5m accuracy outdoors but can degrade to 30m+ near buildings or under tree cover. Poor accuracy causes jittery snapping and potential false off-route detections.

**Mitigation:** The 5-second off-route counter, the `accuracy` field from the GPS service (available but currently unused for routing), and the 50m threshold together provide adequate buffering. Could additionally skip navigation updates when `accuracy > 40m`.

### 7.2 Tunnels and GPS Blackouts

**Risk:** GPS signal is lost in tunnels, parking garages, and dense urban canyons. The GPS service will report `stale: true`.

**Mitigation:** When GPS goes stale, freeze the navigation display at the last known position. Do not trigger off-route detection. Show a "GPS signal lost" indicator. Resume tracking when fix returns.

### 7.3 Web Speech API Quality

**Risk:** espeak-ng voices on Linux are robotic and occasionally hard to understand at speed, especially for street names with unusual pronunciations.

**Mitigation:** This is a known limitation with no offline fix. Higher-quality MBROLA voices can be installed on the Pi. The visual instruction card is the primary guidance mechanism; voice is supplementary.

### 7.4 Valhalla Reroute Latency

**Risk:** Valhalla route calculation on the Pi 5 takes 0.5-3 seconds depending on distance. During reroute, the user has no guidance.

**Mitigation:** Show "Recalculating..." with a spinner. Continue showing the last known instruction. The 15-second reroute cooldown prevents hammering Valhalla with requests during sustained off-route periods (e.g., user intentionally detouring).

### 7.5 Map Rotation Performance

**Risk:** Continuous map bearing changes (auto-rotate with heading) may cause jank on MapLibre GL JS with 3D terrain enabled on the Pi 5.

**Mitigation:** Use `map.easeTo()` with short duration (200ms) rather than `jumpTo()` for smoother interpolation. If performance is poor, disable auto-rotate when 3D terrain is active, or reduce the GPS-driven update rate for bearing to every 3rd tick.

### 7.6 Battery / Power

**Non-risk:** The Pi 5 is mains-powered in the intended AREDN deployment. No battery concerns.

### 7.7 Multi-Leg Routes / Waypoints

**Risk:** The current route panel supports waypoints (`#add-waypoint-btn` exists in HTML). Navigation must handle multi-leg routes where maneuver shape indices reset per leg.

**Mitigation:** When storing the route, flatten all legs into a single coordinate array and reindex maneuver shape indices to be globally contiguous (the current `renderRoute()` already does `allCoords.concat()` and `allManeuvers.concat()` but does not reindex). Must add shape index offset per leg:

```
offset = 0
for each leg:
    for each maneuver in leg:
        maneuver.begin_shape_index += offset
        maneuver.end_shape_index += offset
    offset += decode(leg.shape).length
```

### 7.8 No Offline Speech Synthesis on Some Linux Browsers

**Risk:** Firefox on Linux may not have speech synthesis available without `speech-dispatcher` and `espeak-ng` packages installed.

**Mitigation:** Check `window.speechSynthesis` existence and `speechSynthesis.getVoices().length > 0` at startup. If unavailable, hide the mute button and rely on visual-only navigation. Log a console warning.

---

## 8. Open Questions

1. **Should navigation auto-start when "Use GPS" is set as the start point?** This would be a natural UX shortcut: if the user sets start=GPS and calculates a route, offer to start navigation immediately.

2. **Should we persist the active route in localStorage?** If the browser refreshes mid-navigation (Pi reboot, etc.), the user would need to recalculate. Persisting the Valhalla response and last maneuver index would enable seamless resume.

3. **Night mode:** Auto-switch to Dark Matter basemap during navigation at night? The GPS service could provide a sun-position calculation, or we simply use the system clock.

4. **Speed warning:** Valhalla maneuvers include `speed_limit` on some road segments. Should the navigation UI show a speed warning when GPS speed exceeds the limit?

5. **Arrival radius:** How close to the destination (in meters) should trigger "You have arrived"? Valhalla's final maneuver type (4 = destination) handles this, but the GPS may never land exactly on the destination point. A 30-meter radius seems reasonable.

---

## 9. Recommendation

**Proceed with implementation.** The feature is entirely frontend-side, uses no new dependencies, and integrates cleanly with the existing GPS and Valhalla services. The core algorithm (point-to-polyline snapping + maneuver index lookup) is well-understood and computationally trivial at 1 Hz on a Pi 5.

Suggested implementation order:

1. Route snapping and maneuver tracking (core algorithm)
2. Navigation UI overlay (instruction card, distance, ETA)
3. Map auto-center and auto-rotate
4. Off-route detection and reroute
5. Voice announcements
6. Maneuver icons
7. Polish (localStorage persistence, night mode, speed warnings)

Steps 1-4 form a usable MVP. Steps 5-7 are enhancements.
