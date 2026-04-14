# Navigation Bug Fixes — Design Spec

**Date:** 2026-04-14
**Scope:** 14 confirmed bugs + 1 new feature (global compass button) in the turn-by-turn navigation system
**Files:** `frontend/navigation.js`, `frontend/nav-ui.js`, `frontend/app.js`, `frontend/style.css`
**Bug hunt report:** `dev/bug-hunts/2026-04-14-navigation-consolidated.md`

---

## Summary

Field testing revealed that rerouting rarely triggers, voice announcements rapid-fire near turns, and the navigation UI has layout/positioning issues. A 3-hunter bug hunt identified 14 bugs, most stemming from a core architectural flaw: the UI polls a global GPS variable at 500ms while GPS data arrives at 1Hz, causing double-processing that breaks counters, stale detection, and voice deduplication.

The fixes are ordered by dependency: the GPS feed architecture (B3) must be fixed first since B1, B4, B7, and B13 all depend on correct tick behavior.

---

## Fix 1: Event-Driven GPS Feed (B3)

**Problem:** `nav-ui.js:295` polls `window._geographicaGPSData` every 500ms via `setInterval`. GPS updates arrive at ~1Hz. The engine processes the same data point twice per real fix, breaking all counter-based logic.

**Current architecture:**
```
GPS WebSocket → writes window._geographicaGPSData
setInterval(feedGPS, 500) → reads global → calls nav.updateGPS()
```

**New architecture:**
```
GPS WebSocket → writes window._geographicaGPSData
             → calls window._geographicaGPSCallback(data) if registered
nav-ui.js registers callback on startNavigation(), unregisters on stop
```

**Changes:**

1. **`app.js`** — In the GPS WebSocket `onmessage` handler, after writing to `window._geographicaGPSData`, add:
   ```js
   if (window._geographicaGPSCallback) {
     window._geographicaGPSCallback(window._geographicaGPSData);
   }
   ```

2. **`nav-ui.js`** — Replace:
   - Remove `var gpsFeedInterval` and `startGPSFeed()` function
   - Remove `setInterval(feedGPS, 500)` call in `startNavigation()`
   - Remove `clearInterval(gpsFeedInterval)` in `stopNavigation()`
   - In `startNavigation()`, register the callback:
     ```js
     window._geographicaGPSCallback = feedGPS;
     ```
   - In `stopNavigation()`, unregister:
     ```js
     window._geographicaGPSCallback = null;
     ```
   - New `feedGPS(data)` receives the data directly instead of reading the global. The auto-center `map.easeTo()` call moves here — it fires at 1Hz which is smooth enough (current 500ms is already close).

3. **`navigation.js`** — Update the `updateGPS` JSDoc comment from "Called at ~1 Hz" to "Called on each GPS fix (~1 Hz)". No logic changes needed in the engine itself.

**Do NOT:**
- Remove `window._geographicaGPSData` — other code reads it (GPS badge, initial nav position)
- Change the engine's tick rate expectations — the engine is already designed for 1Hz
- Add a fallback setInterval "just in case" — the callback architecture is simpler and more reliable

---

## Fix 2: Off-Route Detection with Hysteresis (B1)

**Problem:** `navigation.js:577-588` requires 5 consecutive ticks >50m off-route, but resets to 0 on any single tick within 50m. GPS jitter prevents the counter from ever reaching 5.

**Changes in `navigation.js`:**

1. Add new constants:
   ```js
   var OFF_ROUTE_EXIT_THRESHOLD = 35;  // meters — must drop below this to exit off-route
   var OFF_ROUTE_WINDOW = 5;           // rolling window size
   var OFF_ROUTE_MIN_COUNT = 3;        // minimum off-route ticks in window to trigger
   ```

2. Replace `var offRouteCount = 0` with:
   ```js
   var offRouteHistory = [];  // rolling window of booleans
   var inOffRouteState = false;
   ```

3. Replace the off-route detection block (lines 576-587) with:
   ```js
   // Off-route detection with hysteresis
   var offRouteThreshold = inOffRouteState ? OFF_ROUTE_EXIT_THRESHOLD : OFF_ROUTE_THRESHOLD;
   var isOffRoute = snap.distanceFromRoute > offRouteThreshold;

   offRouteHistory.push(isOffRoute);
   if (offRouteHistory.length > OFF_ROUTE_WINDOW) offRouteHistory.shift();

   if (!inOffRouteState && isOffRoute) {
     inOffRouteState = true;
   } else if (inOffRouteState && snap.distanceFromRoute <= OFF_ROUTE_EXIT_THRESHOLD) {
     inOffRouteState = false;
     offRouteHistory = [];
   }

   if (inOffRouteState) {
     var offCount = 0;
     for (var i = 0; i < offRouteHistory.length; i++) {
       if (offRouteHistory[i]) offCount++;
     }
     if (offCount >= OFF_ROUTE_MIN_COUNT && offRouteHistory.length >= OFF_ROUTE_WINDOW) {
       offRouteHistory = [];
       inOffRouteState = false;
       triggerReroute(lat, lng);
       emitUpdate(buildState(snap, false));
       return;
     }
   }
   ```

4. Update `reset()` to clear `offRouteHistory = []; inOffRouteState = false;`

---

## Fix 3: Reroute Recovery (B2)

**Problem:** When the fetch to `/valhalla/route` fails, the engine stays in `state = "rerouting"` permanently. No timeout, no retry, no recovery.

**Changes:**

1. **`navigation.js`** — Add a reroute timeout mechanism:
   ```js
   var REROUTE_TIMEOUT = 10000;  // ms — max time to wait for reroute response
   var rerouteTimeoutId = null;
   ```

   In `triggerReroute()`, after setting `state = "rerouting"`:
   ```js
   rerouteTimeoutId = setTimeout(function () {
     if (state === "rerouting") {
       state = "navigating";
       offRouteHistory = [];
       inOffRouteState = false;
     }
   }, REROUTE_TIMEOUT);
   ```

   In `applyReroute()`, clear the timeout:
   ```js
   if (rerouteTimeoutId) { clearTimeout(rerouteTimeoutId); rerouteTimeoutId = null; }
   ```

   In `reset()`, clear the timeout.

2. **`nav-ui.js`** — Replace the `.catch()` handler in `onReroute()` with retry logic:
   ```js
   var rerouteRetries = 0;
   var MAX_REROUTE_RETRIES = 3;

   // In the .catch handler:
   .catch(function (err) {
     console.error('Reroute failed:', err);
     rerouteRetries++;
     if (rerouteRetries <= MAX_REROUTE_RETRIES) {
       var delay = Math.pow(2, rerouteRetries) * 1000; // 2s, 4s, 8s
       setTimeout(function () {
         // Re-attempt the same reroute fetch
         attemptReroute(body, seq);
       }, delay);
     } else {
       rerouteRetries = 0;
       showBanner('Reroute failed — using current route', 'reroute-failed');
       setTimeout(hideBanner, 5000);
       // Engine timeout will handle state recovery
     }
   });
   ```

   Extract the fetch logic into a separate `attemptReroute(body, seq)` function so it can be called by both the initial `onReroute()` and the retry path.

   Reset `rerouteRetries = 0` in `onReroute()` at the start of each new reroute request.

---

## Fix 4: Voice Announcement Controls (B4)

**Problem:** Announcements rapid-fire near turns (snap oscillation creates fresh `announcedSet` keys), in parking lots (no speed gate), and after reroutes (set cleared entirely).

**Changes in `navigation.js`:**

1. Add constants:
   ```js
   var VOICE_COOLDOWN = 5000;       // ms minimum between announcements
   var VOICE_SPEED_GATE = 2;        // m/s — suppress below this
   ```

2. Add state:
   ```js
   var lastAnnouncementTime = 0;
   ```

3. Modify `announce()` — this is the combined signature that also handles Fix 12 (mute sync). The `key` parameter controls `announcedSet` marking so muted thresholds aren't consumed:
   ```js
   function announce(text, key) {
     if (muted || !text || !onVoiceCb) return false;
     var now = Date.now();
     if (now - lastAnnouncementTime < VOICE_COOLDOWN) return false;
     lastAnnouncementTime = now;
     if (key) announcedSet[key] = true;
     onVoiceCb(text);
     return true;
   }
   ```

   In `checkVoice()`, replace the existing `announcedSet[key] = true; ... announce(text);` pattern with:
   ```js
   if (!announce(text, key)) break;
   ```
   This ensures: (a) cooldown is enforced, (b) muted thresholds are re-checkable on unmute, (c) only one announcement per tick.

4. Add speed gate in `checkVoice()` at the top, but exempt near-maneuver distances so city driving announcements aren't suppressed at traffic lights:
   ```js
   var VOICE_NEAR_ANNOUNCE_DISTANCE = 50; // meters — always announce within this distance
   // Speed gate: suppress below 2 m/s UNLESS within 50m of next maneuver
   if (lastSpeed < VOICE_SPEED_GATE) {
     var nextIdx = currentManeuverIdx + 1;
     if (nextIdx < route.maneuvers.length) {
       var distToNext = distanceToManeuver(snap, nextIdx);
       if (distToNext > VOICE_NEAR_ANNOUNCE_DISTANCE) return;
     } else {
       return;
     }
   }
   ```

5. In `applyReroute()`, instead of `announcedSet = {}`, mark past maneuvers as consumed:
   ```js
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

6. Reset `lastAnnouncementTime = 0` in `reset()`.

---

## Fix 5: GPS Position Offset with Padding (B5)

**Problem:** `map.easeTo({ center: [lng, lat] })` puts GPS at viewport center. Nav overlay covers top ~120-150px. Only ~40% of visible map shows road ahead.

**Changes in `nav-ui.js`:**

1. Add a helper to measure overlay height with hysteresis to prevent flicker when the after-next hint appears/disappears:
   ```js
   var lastNavPaddingTop = 0;
   var PADDING_RECALC_THRESHOLD = 5; // px — ignore changes smaller than this

   function getNavPadding() {
     if (!overlay || overlay.classList.contains('hidden')) return {};
     var measured = overlay.offsetHeight + 20;
     if (Math.abs(measured - lastNavPaddingTop) > PADDING_RECALC_THRESHOLD) {
       lastNavPaddingTop = measured;
     }
     return { top: lastNavPaddingTop };
   }
   ```

   Reset `lastNavPaddingTop = 0` in `stopNavigation()`.

2. Add `padding: getNavPadding()` to all three navigation `map.easeTo()` calls:
   - `startNavigation()` initial easeTo (line ~166)
   - `feedGPS()` auto-center easeTo (line ~336)
   - `recenter()` snap-back easeTo (via feedGPS)

**Do NOT:**
- Use a hardcoded pixel value — overlay height varies with content (after-next hint, status bar collapsed on mobile)
- Add padding outside of navigation mode — normal map browsing should center normally

---

## Fix 6: Heading Truthiness (B6)

**Problem:** `nav-ui.js:308` — `data.heading || data.bearing || 0` treats heading of 0 (north) as falsy.

**Change in `nav-ui.js`:**

Replace line 308:
```js
var heading = data.heading || data.bearing || 0;
```
With:
```js
var heading = data.heading != null ? data.heading : (data.bearing != null ? data.bearing : 0);
```

---

## Fix 7: Unified Heading Validity (B7)

**Problem:** UI computes heading validity independently (`heading !== 0 || speed > 1`) which disagrees with engine's check (`speed >= 3 m/s`). Map spins at walking pace.

**Changes in `nav-ui.js`:**

The auto-center `map.easeTo()` call should use the engine's heading state instead of re-deriving it. After Fix 1 (event-driven GPS), the `onNavUpdate(state)` callback already receives `state.headingValid` and `state.heading` from the engine.

Store the latest engine state:
```js
var lastNavState = null;  // latest state from engine callback

function onNavUpdate(state) {
  lastNavState = state;
  // ... existing UI update logic
}
```

In the auto-center code (inside `feedGPS`), use engine state for bearing:
```js
var bearing;
if (lastNavState && lastNavState.headingValid) {
  bearing = lastNavState.heading;
} else {
  bearing = map.getBearing();  // freeze at current bearing
}
```

Remove the independent `headingValid` computation from `feedGPS`.

---

## Fix 8: Mobile UI Overlap (B8)

**Problem:** `#sidebar-toggle` (z-index 25) and `#search-container` (z-index 10) overlap `#nav-overlay` (z-index 22) on mobile.

**Changes:**

1. **`nav-ui.js`** — In `startNavigation()`, add:
   ```js
   document.body.classList.add('nav-active');
   ```
   In `stopNavigation()`, add:
   ```js
   document.body.classList.remove('nav-active');
   ```

2. **`style.css`** — Add rules. **Do NOT hide search entirely** — users need it for mid-route destination changes. Instead, reposition it below the nav overlay:
   ```css
   body.nav-active #sidebar-toggle {
     top: calc(var(--nav-overlay-height, 100px) + 8px);
   }

   body.nav-active #search-container {
     top: calc(var(--nav-overlay-height, 100px) + 8px);
     left: 52px;
   }
   ```

3. **`nav-ui.js`** — Update a CSS variable when overlay height changes, in `onNavUpdate()`:
   ```js
   document.documentElement.style.setProperty('--nav-overlay-height', overlay.offsetHeight + 'px');
   ```

**Do NOT:**
- Hide the sidebar toggle entirely — users may need settings during navigation
- Change z-index values — the stack is correct for non-navigation mode

---

## Fix 9: Costing Propagation (B9)

**Problem:** `nav-ui.js:246` reads `leg.summary.costing` which doesn't exist in Valhalla responses. Always falls through to `'auto'`. Bike/pedestrian routes get wrong voice thresholds.

**Changes:**

1. **`app.js`** — After `window._geographicaLastTrip = data.trip;` (line ~1850), add:
   ```js
   window._geographicaLastTrip._costing = costing;
   ```
   Where `costing` is already in scope from `document.getElementById('costing-model').value` at line 1783.

2. **`nav-ui.js`** — In `buildRouteData()`, replace line 246:
   ```js
   costing: trip.legs && trip.legs[0] ? (trip.legs[0].summary || {}).costing || 'auto' : 'auto',
   ```
   With:
   ```js
   costing: trip._costing || 'auto',
   ```

---

## Fix 10: buildState Heading No-Op (B10)

**Problem:** `navigation.js:491` — `heading: headingValid ? lastValidHeading : lastValidHeading` — both branches identical.

**Change:** Replace with:
```js
heading: headingValid ? lastValidHeading : null,
```

---

## Fix 11: Multi-Leg Duplicate Coordinates (B11)

**Problem:** `nav-ui.js:222-233` concatenates full coordinate arrays including shared waypoints between legs, creating duplicate points and offset shape indices.

**Change in `buildRouteData()`:**

Replace the leg iteration. **Critical: maneuver shape indices from Valhalla are relative to the full leg shape including the shared point. When we slice(1) to remove the duplicate, we must subtract 1 from each maneuver's indices for that leg:**

```js
trip.legs.forEach(function (leg, i) {
  var coords = decodePolyline(leg.shape);
  var indexAdjust = 0;
  // Skip first point of subsequent legs (shared with previous leg's last point)
  if (i > 0 && coords.length > 0) {
    coords = coords.slice(1);
    indexAdjust = 1; // Valhalla indices are 1 too high for the sliced array
  }
  if (leg.maneuvers) {
    leg.maneuvers.forEach(function (m) {
      var mc = Object.assign({}, m);
      mc.begin_shape_index = (mc.begin_shape_index || 0) - indexAdjust + shapeOffset;
      mc.end_shape_index = (mc.end_shape_index || 0) - indexAdjust + shapeOffset;
      allManeuvers.push(mc);
    });
  }
  allCoords = allCoords.concat(coords);
  shapeOffset += coords.length; // Use sliced length
});
```

---

## Fix 12: Mute State Sync (B12)

**Problem:** `toggleMute()` in `nav-ui.js` doesn't call `nav.setMuted()`. Engine's `announcedSet` marks thresholds as consumed even when muted — un-muting won't replay missed announcements.

**Changes:**

1. **`nav-ui.js`** — In `toggleMute()`, after `muted = !muted`, add:
   ```js
   if (nav && nav.setMuted) nav.setMuted(muted);
   ```

2. **`navigation.js`** — The `announce()` function changes are already specified in Fix 4. The combined `announce(text, key)` signature handles both cooldown (Fix 4) and mute-aware threshold marking (Fix 12). No additional engine changes needed beyond what Fix 4 specifies.

   **Note:** Fix 4 and Fix 12 MUST be implemented together since they both modify `announce()` and `checkVoice()`. They are listed as separate fixes for traceability back to bug IDs but should be a single task in the implementation plan.

---

## Fix 13: GPS Heartbeat Data Freshness (B13)

**Problem:** `nav-ui.js:325-328` resets the heartbeat timer on every `feedGPS()` call, even when GPS data hasn't changed.

**Changes in `nav-ui.js`:**

Add a variable to track the last GPS data signature:
```js
var lastGPSSignature = null;
```

In `feedGPS(data)`, compute a signature and only reset the heartbeat if data changed:
```js
var sig = lat + ',' + lng;
if (sig !== lastGPSSignature) {
  lastGPSSignature = sig;
  clearTimeout(gpsHeartbeatTimer);
  gpsHeartbeatTimer = setTimeout(function () {
    showBanner('GPS signal delayed', 'gps-stale');
  }, GPS_HEARTBEAT_MS);
}
```

Reset `lastGPSSignature = null` in `stopNavigation()` so re-starting navigation doesn't carry stale signature state.

```js
// In stopNavigation():
lastGPSSignature = null;
```

---

## Fix 14: Dead lastGPS Check (B14)

**Problem:** `navigation.js:687,692` — `start()` calls `reset()` which sets `lastGPS = null`, then checks `if (lastGPS)` which is always false.

**Change in `navigation.js`:**

In `start()`, save GPS state before reset:
```js
start: function (routeData) {
  var savedGPS = window._geographicaGPSData;
  reset();
  route = routeData;
  precomputeDistances();
  startStaleChecker();

  if (savedGPS) {
    var lng = parseFloat(savedGPS.lon || savedGPS.lng || savedGPS.longitude);
    var lat = parseFloat(savedGPS.lat || savedGPS.latitude);
    if (!isNaN(lng) && !isNaN(lat)) {
      var snap = snapToRoute(lng, lat, null);
      lastSnap = snap;
      lastGPS = { latitude: lat, longitude: lng, heading: savedGPS.heading || 0, speed: savedGPS.speed || 0 };
      lastGPSTime = Date.now();
      if (snap.distanceFromRoute > JOIN_THRESHOLD) {
        state = "joining";
        joinStartTime = Date.now();
      } else {
        state = "navigating";
      }
      emitUpdate(buildState(snap, false));
      return;
    }
  }

  state = "joining";
  joinStartTime = Date.now();
  emitUpdate(buildState({
    segmentIndex: 0, snappedLng: route.coords[0][0],
    snappedLat: route.coords[0][1], distanceFromRoute: 0,
    alongRouteDistance: 0, t: 0
  }, false));
},
```

---

## Feature: Global Compass Button (D1)

**Problem:** No return-to-north button anywhere. MapLibre's `NavigationControl` compass is disabled because it re-enables `dragRotate` (Pitfall #11).

**Implementation:**

1. **`app.js`** — After adding `NavigationControl` (line ~158), create a custom compass button:
   ```js
   var compassBtn = document.createElement('button');
   compassBtn.id = 'compass-north-btn';
   compassBtn.className = 'map-btn';
   compassBtn.title = 'Reset to north';
   // SVG: circle with N indicator and arrow pointing up
   // Built via DOM API (safe, no innerHTML)
   compassBtn.addEventListener('click', function () {
     map.easeTo({ bearing: 0, duration: 500 });
   });
   document.getElementById('map').appendChild(compassBtn);

   // Rotate the button to show current bearing
   map.on('rotate', function () {
     compassBtn.style.transform = 'rotate(' + (-map.getBearing()) + 'deg)';
   });
   ```

2. **`style.css`** — Position the compass button above MapLibre's zoom controls (which sit at `bottom-right`). Use a high enough `bottom` to clear them on both desktop and mobile:
   ```css
   #compass-north-btn {
     position: absolute;
     bottom: 160px; /* above zoom controls (~120px) + attribution */
     right: 12px;
     z-index: 10;
     width: 36px;
     height: 36px;
     border-radius: 50%;
     transition: transform 0.15s ease-out;
   }

   @media (max-width: 480px) {
     #compass-north-btn {
       bottom: 140px; /* tighter on mobile, zoom controls are smaller */
     }
   }
   ```

3. **`nav-ui.js`** — During navigation, the compass click also pauses auto-center (like manual pan):
   ```js
   // In init(), after caching DOM refs:
   var compassBtn = document.getElementById('compass-north-btn');
   if (compassBtn) {
     compassBtn.addEventListener('click', function () {
       if (active) {
         onManualPan();  // pause auto-center for 10 seconds
       }
     });
   }
   ```

**Do NOT:**
- Use `NavigationControl` with `showCompass: true` — Pitfall #11
- Call `dragRotate.enable()` or `.disable()` — not needed, compass only sets bearing
- Hide the compass during navigation — it's useful to check orientation

---

## Execution Dependencies

The fixes have these ordering constraints:

1. **B3 (GPS feed) MUST be first** — B1, B4, B7, B13 all depend on correct tick behavior
2. **B6 (heading truthiness) before B7 (unified validity)** — B7 builds on correct heading values
3. **B4 (voice) depends on B12 (mute sync)** — the `announce()` function signature changes in both
4. **B10 (buildState no-op) before B7** — B7 uses the heading from buildState
5. All other fixes are independent

Recommended execution order:
1. B3 (GPS feed architecture)
2. B6, B10 (simple fixes, no dependencies)
3. B1 (off-route hysteresis)
4. B2 (reroute recovery)
5. B12, B4 (mute sync then voice controls — share `announce()`)
6. B5 (padding)
7. B7 (unified heading)
8. B8 (mobile overlap)
9. B9 (costing)
10. B11 (multi-leg)
11. B13, B14 (heartbeat, dead check)
12. D1 (compass button)
