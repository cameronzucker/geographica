# Navigation Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Fix 14 confirmed navigation bugs and add a global compass button, addressing field-reported issues with rerouting, voice announcements, GPS positioning, and mobile UI layout.

**Architecture:** Event-driven GPS feed replaces polling; hysteresis-based off-route detection; voice cooldown + speed gate; padding-based map offset; custom compass button avoiding Pitfall #11.

**Tech Stack:** Vanilla JS (IIFEs), MapLibre GL JS, Web Speech API, Valhalla routing

**Design spec:** `docs/superpowers/specs/2026-04-14-navigation-bug-fixes-design.md`
**Bug hunt report:** `dev/bug-hunts/2026-04-14-navigation-consolidated.md`

---

## File Structure

| Action | File | Tasks |
|--------|------|-------|
| Modify | `frontend/app.js` (3904 lines) | T1 (GPS callback), T8 (costing), T12 (compass) |
| Modify | `frontend/navigation.js` (790 lines) | T2 (B6/B10/B14), T3 (B1), T4 (B2), T5 (B4+B12) |
| Modify | `frontend/nav-ui.js` (882 lines) | T1 (GPS feed), T4 (B2), T5 (B4+B12), T6 (B5), T7 (B7), T8 (B9), T9 (B11), T10 (B13), T11 (B8), T12 (compass) |
| Modify | `frontend/style.css` (1553 lines) | T11 (B8), T12 (compass) |

---

## Dependency Graph

```
T1 (B3 GPS feed) ──┬── T3 (B1 off-route)
                    ├── T5 (B4+B12 voice+mute)
                    ├── T7 (B7 unified heading) ← T2 (B6, B10)
                    └── T10 (B13 heartbeat)

T2 (B6, B10, B14) ── T7 (B7)
T3 (B1) ── T4 (B2 reroute recovery)
All others: independent
```

**Execution order:** T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10 → T11 → T12

---

## Task 1: GPS Feed Architecture (B3)

**Files:** `frontend/app.js`, `frontend/nav-ui.js`
**Why first:** B1, B4, B7, B13 all depend on correct 1Hz tick behavior. The current 500ms polling double-processes GPS data.

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD where testable. For browser-only UI code, verify manually.

### Step 1: Add GPS callback dispatch in app.js

- [ ] **Step 1a: Add callback invocation after GPS data write**

In `frontend/app.js`, find the `updateGPSPosition()` function. At line 2278, after `window._geographicaGPSData = data;`, add the callback dispatch:

```js
// line 2278 (existing):
window._geographicaGPSData = data;

// ADD after line 2278:
if (window._geographicaGPSCallback) {
  window._geographicaGPSCallback(window._geographicaGPSData);
}
```

### Step 2: Replace polling with callback in nav-ui.js

- [ ] **Step 2a: Remove gpsFeedInterval and startGPSFeed()**

In `frontend/nav-ui.js`, remove the polling infrastructure:

Remove lines 291-296 (the `gpsFeedInterval` variable and `startGPSFeed()` function):
```js
// REMOVE:
var gpsFeedInterval = null;

function startGPSFeed() {
  if (gpsFeedInterval) clearInterval(gpsFeedInterval);
  gpsFeedInterval = setInterval(feedGPS, 500);
}
```

- [ ] **Step 2b: Register callback in startNavigation()**

In `frontend/nav-ui.js`, in `startNavigation()` at line 158, replace:
```js
// Start GPS feed loop
startGPSFeed();
```
With:
```js
// Register for GPS callbacks (event-driven, not polling)
window._geographicaGPSCallback = feedGPS;
```

- [ ] **Step 2c: Unregister callback in stopNavigation()**

In `frontend/nav-ui.js`, in `stopNavigation()`, replace the timer cleanup block at lines 205-208:
```js
clearTimeout(autoCenterTimer);
clearTimeout(gpsHeartbeatTimer);
if (gpsFeedInterval) clearInterval(gpsFeedInterval);
gpsFeedInterval = null;
autoCenterPaused = false;
```
With:
```js
clearTimeout(autoCenterTimer);
clearTimeout(gpsHeartbeatTimer);
window._geographicaGPSCallback = null;
autoCenterPaused = false;
```

- [ ] **Step 2d: Update feedGPS() to accept data parameter**

In `frontend/nav-ui.js`, update `feedGPS()` at line 298. Change the function signature and remove the global read:

Replace lines 298-303:
```js
function feedGPS() {
  if (!active || !nav) return;

  var data = window._geographicaGPSData;
  if (!data) return;
```
With:
```js
function feedGPS(data) {
  if (!active || !nav) return;

  if (!data) {
    data = window._geographicaGPSData;
    if (!data) return;
  }
```

Note: The fallback to `window._geographicaGPSData` is kept so `recenter()` at line 575 (which calls `feedGPS()` with no args) continues to work.

### Step 3: Update engine JSDoc

- [ ] **Step 3a: Update JSDoc comment in navigation.js**

In `frontend/navigation.js`, at line 720-722, update the comment:

Replace:
```js
/**
 * Feed a GPS update into the engine. Called at ~1 Hz.
 * gpsData: { latitude, longitude, heading, speed, timestamp }
 */
```
With:
```js
/**
 * Feed a GPS update into the engine. Called on each GPS fix (~1 Hz).
 * gpsData: { latitude, longitude, heading, speed, timestamp }
 */
```

### Step 4: Verify

- [ ] **Step 4a: Manual verification**

1. Open the app in a browser with GPS active
2. Start navigation on a route
3. Verify GPS position updates appear at ~1Hz (not 2Hz)
4. Verify recenter button still works (calls feedGPS with no args)
5. Verify stopping navigation unregisters the callback

**Do NOT:**
- Remove `window._geographicaGPSData` -- other code reads it (GPS badge, initial nav position)
- Change the engine's tick rate expectations -- the engine is already designed for 1Hz
- Add a fallback setInterval "just in case" -- the callback architecture is simpler and more reliable

### Commit

- [ ] Commit with message: `fix(nav): replace GPS polling with event-driven callback (B3)`

BEFORE marking this task complete:
1. Verify all changes match the spec exactly
2. Test manually if browser-only code
3. Run any existing tests to verify no regression

---

## Task 2: Simple Fixes (B6, B10, B14)

**Files:** `frontend/nav-ui.js` (B6), `frontend/navigation.js` (B10, B14)
**Why grouped:** Three trivial, independent fixes with no cross-dependencies.

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD where testable. For browser-only UI code, verify manually.

### Step 1: Fix heading truthiness (B6)

- [ ] **Step 1a: Fix heading falsy-zero bug in nav-ui.js**

In `frontend/nav-ui.js`, at line 308, replace:
```js
var heading = data.heading || data.bearing || 0;
```
With:
```js
var heading = data.heading != null ? data.heading : (data.bearing != null ? data.bearing : 0);
```

This fixes Pitfall #10 (JS truthiness for numeric zero). When heading is 0 (north), the `||` operator skips it because `0` is falsy.

### Step 2: Fix buildState heading no-op (B10)

- [ ] **Step 2a: Fix identical branches in buildState**

In `frontend/navigation.js`, at line 491, replace:
```js
heading: headingValid ? lastValidHeading : lastValidHeading,
```
With:
```js
heading: headingValid ? lastValidHeading : null,
```

### Step 3: Fix dead lastGPS check (B14)

- [ ] **Step 3a: Save GPS state before reset in start()**

In `frontend/navigation.js`, replace the `start` function at lines 685-712:
```js
start: function (routeData) {
  reset();
  route = routeData;
  precomputeDistances();
  startStaleChecker();

  // Determine initial state based on last known GPS
  if (lastGPS) {
    var snap = snapToRoute(lastGPS.longitude, lastGPS.latitude, null);
    lastSnap = snap;
    if (snap.distanceFromRoute > JOIN_THRESHOLD) {
      state = "joining";
      joinStartTime = Date.now();
    } else {
      state = "navigating";
    }
  } else {
    // No GPS yet — enter joining and wait
    state = "joining";
    joinStartTime = Date.now();
  }

  emitUpdate(buildState(lastSnap || {
    segmentIndex: 0, snappedLng: route.coords[0][0],
    snappedLat: route.coords[0][1], distanceFromRoute: 0,
    alongRouteDistance: 0, t: 0
  }, false));
},
```
With:
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

### Step 4: Verify

- [ ] **Step 4a: Manual verification**

1. B6: Start navigation heading exactly north (0 degrees) -- verify heading is reported as 0, not falling through to bearing
2. B10: Check that `getState().heading` returns `null` when heading is invalid (low speed), not `lastValidHeading`
3. B14: Start navigation with GPS active -- verify initial snap uses current GPS position, not `null`

### Commit

- [ ] Commit with message: `fix(nav): heading truthiness, buildState heading, dead lastGPS check (B6, B10, B14)`

BEFORE marking this task complete:
1. Verify all changes match the spec exactly
2. Test manually if browser-only code
3. Run any existing tests to verify no regression

---

## Task 3: Off-Route Hysteresis (B1)

**Files:** `frontend/navigation.js` only
**Depends on:** Task 1 (correct 1Hz ticks)

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD where testable. For browser-only UI code, verify manually.

### Step 1: Add hysteresis constants

- [ ] **Step 1a: Add new constants after existing OFF_ROUTE_THRESHOLD**

In `frontend/navigation.js`, after line 22 (`var OFF_ROUTE_TICKS = 5;`), add:
```js
var OFF_ROUTE_EXIT_THRESHOLD = 35;  // meters -- must drop below this to exit off-route
var OFF_ROUTE_WINDOW = 5;           // rolling window size
var OFF_ROUTE_MIN_COUNT = 3;        // minimum off-route ticks in window to trigger
```

### Step 2: Replace state variables

- [ ] **Step 2a: Replace offRouteCount with rolling window state**

In `frontend/navigation.js`, at line 129, replace:
```js
var offRouteCount = 0;
```
With:
```js
var offRouteHistory = [];  // rolling window of booleans
var inOffRouteState = false;
```

### Step 3: Replace off-route detection block

- [ ] **Step 3a: Replace the off-route detection logic**

In `frontend/navigation.js`, replace lines 576-587 (the off-route detection block in the `tick()` function):
```js
// Off-route detection
if (snap.distanceFromRoute > OFF_ROUTE_THRESHOLD) {
  offRouteCount++;
  if (offRouteCount >= OFF_ROUTE_TICKS) {
    offRouteCount = 0;
    triggerReroute(lat, lng);
    emitUpdate(buildState(snap, false));
    return;
  }
} else {
  offRouteCount = 0;
}
```
With:
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

### Step 4: Update reset()

- [ ] **Step 4a: Clear hysteresis state in reset()**

In `frontend/navigation.js`, in the `reset()` function at line 660, replace:
```js
offRouteCount = 0;
```
With:
```js
offRouteHistory = [];
inOffRouteState = false;
```

### Step 5: Update applyReroute()

- [ ] **Step 5a: Clear hysteresis state in applyReroute()**

In `frontend/navigation.js`, in `applyReroute()` at line 744, replace:
```js
offRouteCount = 0;
```
With:
```js
offRouteHistory = [];
inOffRouteState = false;
```

### Step 6: Verify

- [ ] **Step 6a: Manual verification**

1. Drive normally on route -- verify no false reroute triggers
2. Deliberately go off-route by 60m+ -- verify reroute triggers after ~5 seconds (3 of 5 ticks)
3. GPS jitter near route edge (~50m) -- verify single jitter spikes don't reset the counter entirely

### Commit

- [ ] Commit with message: `fix(nav): off-route detection with hysteresis window (B1)`

BEFORE marking this task complete:
1. Verify all changes match the spec exactly
2. Test manually if browser-only code
3. Run any existing tests to verify no regression

---

## Task 4: Reroute Recovery (B2)

**Files:** `frontend/navigation.js`, `frontend/nav-ui.js`
**Depends on:** Task 3 (off-route hysteresis variables)

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD where testable. For browser-only UI code, verify manually.

### Step 1: Add reroute timeout in navigation.js

- [ ] **Step 1a: Add timeout constants and state**

In `frontend/navigation.js`, after the `REROUTE_COOLDOWN` constant (line 23), add:
```js
var REROUTE_TIMEOUT = 10000;  // ms -- max time to wait for reroute response
```

After the `rerouteSeq` variable (line 131), add:
```js
var rerouteTimeoutId = null;
```

- [ ] **Step 1b: Set timeout in triggerReroute()**

In `frontend/navigation.js`, in `triggerReroute()` at line 600, after `state = "rerouting";` (line 600), add:
```js
rerouteTimeoutId = setTimeout(function () {
  if (state === "rerouting") {
    state = "navigating";
    offRouteHistory = [];
    inOffRouteState = false;
  }
}, REROUTE_TIMEOUT);
```

- [ ] **Step 1c: Clear timeout in applyReroute()**

In `frontend/navigation.js`, in `applyReroute()`, at the beginning of the function body (after the stale seq check at line 739), add:
```js
if (rerouteTimeoutId) { clearTimeout(rerouteTimeoutId); rerouteTimeoutId = null; }
```

- [ ] **Step 1d: Clear timeout in reset()**

In `frontend/navigation.js`, in `reset()`, add before `stopStaleChecker()`:
```js
if (rerouteTimeoutId) { clearTimeout(rerouteTimeoutId); rerouteTimeoutId = null; }
```

### Step 2: Add retry logic in nav-ui.js

- [ ] **Step 2a: Add retry state variables**

In `frontend/nav-ui.js`, in the STATE section (near line 20), add:
```js
var rerouteRetries = 0;
var MAX_REROUTE_RETRIES = 3;
```

- [ ] **Step 2b: Extract fetch logic into attemptReroute()**

In `frontend/nav-ui.js`, refactor `onReroute()`. Replace the `fetch('/valhalla/route', ...)` block (lines 456-474) by extracting it into a separate function:

After the `onReroute()` function, add:
```js
function attemptReroute(body, seq) {
  fetch('/valhalla/route', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  .then(function (res) { return res.json(); })
  .then(function (data) {
    if (data.trip && nav) {
      var newRouteData = buildRouteData(data.trip);
      if (newRouteData) {
        rerouteRetries = 0;
        nav.applyReroute(newRouteData, seq);
        hideBanner();
      }
    }
  })
  .catch(function (err) {
    console.error('Reroute failed:', err);
    rerouteRetries++;
    if (rerouteRetries <= MAX_REROUTE_RETRIES) {
      var delay = Math.pow(2, rerouteRetries) * 1000; // 2s, 4s, 8s
      setTimeout(function () {
        attemptReroute(body, seq);
      }, delay);
    } else {
      rerouteRetries = 0;
      showBanner('Reroute failed \u2014 using current route', 'reroute-failed');
      setTimeout(hideBanner, 5000);
      // Engine timeout will handle state recovery
    }
  });
}
```

- [ ] **Step 2c: Update onReroute() to use attemptReroute()**

In `frontend/nav-ui.js`, in `onReroute()`, replace the fetch block (lines 456-474):
```js
fetch('/valhalla/route', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body)
})
.then(function (res) { return res.json(); })
.then(function (data) {
  if (data.trip && nav) {
    var newRouteData = buildRouteData(data.trip);
    if (newRouteData) {
      nav.applyReroute(newRouteData, seq);
      hideBanner();
    }
  }
})
.catch(function (err) {
  console.error('Reroute failed:', err);
  // Banner stays visible; engine will retry after cooldown
});
```
With:
```js
rerouteRetries = 0;
attemptReroute(body, seq);
```

### Step 3: Verify

- [ ] **Step 3a: Manual verification (Pitfall #9 -- unrecoverable async state)**

1. Go off-route to trigger reroute
2. Block network (disconnect) -- verify reroute retries with exponential backoff (2s, 4s, 8s)
3. After 3 failed retries, verify "Reroute failed" banner appears
4. After 10s engine timeout, verify state returns to "navigating" (not stuck in "rerouting")
5. Reconnect network, go off-route again -- verify reroute works normally

### Commit

- [ ] Commit with message: `fix(nav): reroute recovery with timeout + retry (B2)`

BEFORE marking this task complete:
1. Verify all changes match the spec exactly
2. Test manually if browser-only code
3. Run any existing tests to verify no regression

---

## Task 5: Voice Announcements + Mute Sync (B4 + B12)

**Files:** `frontend/navigation.js`, `frontend/nav-ui.js`
**Combined per spec:** Both modify `announce()` and `checkVoice()`. Must be implemented together.

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD where testable. For browser-only UI code, verify manually.

### Step 1: Add voice constants and state in navigation.js

- [ ] **Step 1a: Add voice cooldown and speed gate constants**

In `frontend/navigation.js`, after the `NEXT_AFTER_NEXT_DISTANCE` constant (line 44), add:
```js
var VOICE_COOLDOWN = 5000;       // ms minimum between announcements
var VOICE_SPEED_GATE = 2;        // m/s -- suppress below this
var VOICE_NEAR_ANNOUNCE_DISTANCE = 50; // meters -- always announce within this distance
```

- [ ] **Step 1b: Add voice state variable**

In `frontend/navigation.js`, after the `announcedSet` variable (line 147), add:
```js
var lastAnnouncementTime = 0;
```

### Step 2: Rewrite announce() with cooldown + mute-aware key marking

- [ ] **Step 2a: Replace announce() function**

In `frontend/navigation.js`, replace the `announce()` function at lines 317-320:
```js
function announce(text) {
  if (muted || !text || !onVoiceCb) return;
  onVoiceCb(text);
}
```
With:
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

### Step 3: Add speed gate and update checkVoice()

- [ ] **Step 3a: Add speed gate at top of checkVoice()**

In `frontend/navigation.js`, in `checkVoice()` after the null guard at line 327-328, add the speed gate:

After:
```js
if (!route || !route.maneuvers) return;
```
Add:
```js
// Speed gate: suppress below 2 m/s UNLESS within 50m of next maneuver
if (lastSpeed < VOICE_SPEED_GATE) {
  var nextCheckIdx = currentManeuverIdx + 1;
  if (nextCheckIdx < route.maneuvers.length) {
    var distCheck = distanceToManeuver(snap, nextCheckIdx);
    if (distCheck > VOICE_NEAR_ANNOUNCE_DISTANCE) return;
  } else {
    return;
  }
}
```

- [ ] **Step 3b: Update announcement pattern in checkVoice()**

In `frontend/navigation.js`, in the `checkVoice()` threshold loop (lines 336-367), replace the announcement pattern. Change:
```js
if (announcedSet[key]) continue;

if (distToNext <= thresholds[ti]) {
  announcedSet[key] = true;

  var text;
  if (ti < 2) {
    // Far or medium: use alert instruction
    text = m.verbal_transition_alert_instruction || m.instruction;
  } else {
    // Near: use pre-transition instruction
    text = m.verbal_pre_transition_instruction || m.instruction;

    // Next-after-next: if maneuver[current+2] is close, append it
    var afterIdx = nextIdx + 1;
    if (afterIdx < route.maneuvers.length) {
      var distBetween = distanceToManeuver(
        { segmentIndex: m.begin_shape_index, t: 0 }, afterIdx
      );
      if (distBetween <= NEXT_AFTER_NEXT_DISTANCE) {
        var afterM = route.maneuvers[afterIdx];
        text += ", then " + (afterM.instruction || "");
      }
    }
  }

  announce(text);
  break; // Only one announcement per tick
}
```
With:
```js
if (announcedSet[key]) continue;

if (distToNext <= thresholds[ti]) {
  var text;
  if (ti < 2) {
    // Far or medium: use alert instruction
    text = m.verbal_transition_alert_instruction || m.instruction;
  } else {
    // Near: use pre-transition instruction
    text = m.verbal_pre_transition_instruction || m.instruction;

    // Next-after-next: if maneuver[current+2] is close, append it
    var afterIdx = nextIdx + 1;
    if (afterIdx < route.maneuvers.length) {
      var distBetween = distanceToManeuver(
        { segmentIndex: m.begin_shape_index, t: 0 }, afterIdx
      );
      if (distBetween <= NEXT_AFTER_NEXT_DISTANCE) {
        var afterM = route.maneuvers[afterIdx];
        text += ", then " + (afterM.instruction || "");
      }
    }
  }

  if (!announce(text, key)) break;
}
```

Key change: `announcedSet[key] = true` is removed from this block (now handled inside `announce()` via the `key` parameter). The `break` is now conditional on `announce()` returning false (cooldown hit), ensuring muted thresholds are re-checkable on unmute.

### Step 4: Fix reroute announced set clearing

- [ ] **Step 4a: Preserve past maneuver thresholds in applyReroute()**

In `frontend/navigation.js`, in `applyReroute()`, replace:
```js
announcedSet = {};
```
With:
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

### Step 5: Reset voice state in reset()

- [ ] **Step 5a: Add lastAnnouncementTime reset**

In `frontend/navigation.js`, in `reset()`, add after `announcedSet = {};`:
```js
lastAnnouncementTime = 0;
```

### Step 6: Sync mute state from UI to engine (B12)

- [ ] **Step 6a: Call engine setMuted in toggleMute()**

In `frontend/nav-ui.js`, in `toggleMute()` at line 607, after `muted = !muted;`, add:
```js
if (nav && nav.setMuted) nav.setMuted(muted);
```

### Step 7: Verify

- [ ] **Step 7a: Manual verification**

1. Drive toward a turn -- verify only one announcement per 5 seconds (cooldown)
2. Stop in a parking lot near a turn -- verify no announcements below 2 m/s (speed gate)
3. Stop within 50m of a turn -- verify announcement still fires despite low speed (near-maneuver exemption)
4. Mute voice, pass a turn threshold, unmute -- verify the threshold fires again on unmute
5. Trigger reroute -- verify past maneuver announcements are preserved, future ones are cleared

### Commit

- [ ] Commit with message: `fix(nav): voice cooldown, speed gate, mute-aware thresholds (B4, B12)`

BEFORE marking this task complete:
1. Verify all changes match the spec exactly
2. Test manually if browser-only code
3. Run any existing tests to verify no regression

---

## Task 6: GPS Position Padding (B5)

**Files:** `frontend/nav-ui.js` only

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD where testable. For browser-only UI code, verify manually.

### Step 1: Add padding helper

- [ ] **Step 1a: Add getNavPadding() function**

In `frontend/nav-ui.js`, in the STATE section (after line 29 `var GPS_HEARTBEAT_MS = 3000;`), add:
```js
var lastNavPaddingTop = 0;
var PADDING_RECALC_THRESHOLD = 5; // px -- ignore changes smaller than this
```

Add the helper function after the `clamp()` function (after line 704):
```js
function getNavPadding() {
  if (!overlay || overlay.classList.contains('hidden')) return {};
  var measured = overlay.offsetHeight + 20;
  if (Math.abs(measured - lastNavPaddingTop) > PADDING_RECALC_THRESHOLD) {
    lastNavPaddingTop = measured;
  }
  return { top: lastNavPaddingTop };
}
```

### Step 2: Add padding to easeTo calls

- [ ] **Step 2a: Add padding to startNavigation() easeTo**

In `frontend/nav-ui.js`, in `startNavigation()`, at the `map.easeTo()` call (lines 166-173), add padding:

Replace:
```js
map.easeTo({
  center: [lng, lat],
  zoom: 17,
  pitch: 60,
  bearing: gps.heading || 0,
  duration: 800
});
```
With:
```js
map.easeTo({
  center: [lng, lat],
  zoom: 17,
  pitch: 60,
  bearing: gps.heading || 0,
  duration: 800,
  padding: getNavPadding()
});
```

- [ ] **Step 2b: Add padding to feedGPS() easeTo**

In `frontend/nav-ui.js`, in `feedGPS()`, at the auto-center `map.easeTo()` call (lines 336-343), add padding:

Replace:
```js
map.easeTo({
  center: [lng, lat],
  bearing: bearing,
  zoom: zoom,
  pitch: 60,
  duration: 500
});
```
With:
```js
map.easeTo({
  center: [lng, lat],
  bearing: bearing,
  zoom: zoom,
  pitch: 60,
  duration: 500,
  padding: getNavPadding()
});
```

### Step 3: Reset padding in stopNavigation()

- [ ] **Step 3a: Reset lastNavPaddingTop**

In `frontend/nav-ui.js`, in `stopNavigation()`, add in the cleanup section:
```js
lastNavPaddingTop = 0;
```

### Step 4: Verify

- [ ] **Step 4a: Manual verification**

1. Start navigation -- verify GPS dot is pushed down from center by overlay height
2. Resize the after-next hint (drive toward a "then turn right" maneuver) -- verify padding adjusts smoothly
3. Stop navigation -- verify normal map centering returns (no padding)

**Do NOT:**
- Use a hardcoded pixel value -- overlay height varies with content
- Add padding outside of navigation mode -- normal map browsing should center normally

### Commit

- [ ] Commit with message: `fix(nav): offset GPS position below nav overlay with padding (B5)`

BEFORE marking this task complete:
1. Verify all changes match the spec exactly
2. Test manually if browser-only code
3. Run any existing tests to verify no regression

---

## Task 7: Unified Heading Validity (B7)

**Files:** `frontend/nav-ui.js` only
**Depends on:** Task 2 (B6 heading truthiness, B10 buildState heading null)

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md (especially Pitfall #11 -- duplicated logic)
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD where testable. For browser-only UI code, verify manually.

### Step 1: Store engine state

- [ ] **Step 1a: Add lastNavState variable**

In `frontend/nav-ui.js`, in the STATE section (near line 20), add:
```js
var lastNavState = null;  // latest state from engine callback
```

- [ ] **Step 1b: Store state in onNavUpdate()**

In `frontend/nav-ui.js`, in `onNavUpdate()` at line 350, add as the first line after `if (!active) return;`:
```js
lastNavState = state;
```

### Step 2: Use engine heading in auto-center

- [ ] **Step 2a: Replace independent heading computation in feedGPS()**

In `frontend/nav-ui.js`, in `feedGPS()`, replace the auto-center block (lines 331-343):
```js
// Auto-center map if not paused
if (!autoCenterPaused) {
  var speedMps = speed || 0;
  var zoom = clamp(18 - speedMps * 0.15, 14, 18);
  var bearing = headingValid ? heading : map.getBearing();

  map.easeTo({
    center: [lng, lat],
    bearing: bearing,
    zoom: zoom,
    pitch: 60,
    duration: 500
  });
}
```
With:
```js
// Auto-center map if not paused
if (!autoCenterPaused) {
  var speedMps = speed || 0;
  var zoom = clamp(18 - speedMps * 0.15, 14, 18);
  var navBearing;
  if (lastNavState && lastNavState.headingValid) {
    navBearing = lastNavState.heading;
  } else {
    navBearing = map.getBearing();  // freeze at current bearing
  }

  map.easeTo({
    center: [lng, lat],
    bearing: navBearing,
    zoom: zoom,
    pitch: 60,
    duration: 500,
    padding: getNavPadding()
  });
}
```

Note: This replaces the independent `headingValid` computation (`heading !== 0 || speed > 1`) with the engine's `state.headingValid` (which uses `speed >= 3 m/s`). This eliminates Pitfall #11 (duplicated logic). The `padding: getNavPadding()` is included since Task 6 adds it.

- [ ] **Step 2b: Remove the now-unused independent headingValid line**

In `frontend/nav-ui.js`, in `feedGPS()`, the line at 310 is no longer needed:
```js
var headingValid = heading !== 0 || speed > 1;
```
Remove this line entirely. The `heading` variable (line 308, fixed in Task 2/B6) is still used for feeding to the engine at line 316.

### Step 3: Reset lastNavState in stopNavigation()

- [ ] **Step 3a: Clear lastNavState**

In `frontend/nav-ui.js`, in `stopNavigation()`, add:
```js
lastNavState = null;
```

### Step 4: Verify

- [ ] **Step 4a: Manual verification**

1. Walk at 1 m/s with GPS heading -- verify map does NOT rotate (engine's 3 m/s gate)
2. Drive at 5 m/s -- verify map rotates to follow heading
3. Stop from driving speed -- verify map freezes at last bearing instead of spinning

### Commit

- [ ] Commit with message: `fix(nav): use engine heading validity instead of independent check (B7)`

BEFORE marking this task complete:
1. Verify all changes match the spec exactly
2. Test manually if browser-only code
3. Run any existing tests to verify no regression

---

## Task 8: Costing Propagation (B9)

**Files:** `frontend/app.js`, `frontend/nav-ui.js`

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD where testable. For browser-only UI code, verify manually.

### Step 1: Store costing on trip object in app.js

- [ ] **Step 1a: Add _costing to trip object**

In `frontend/app.js`, at line 1850, after `window._geographicaLastTrip = data.trip;`, add:
```js
window._geographicaLastTrip._costing = costing;
```

The `costing` variable is already in scope from line 1783: `var costing = document.getElementById('costing-model').value;`

### Step 2: Read costing from trip object in nav-ui.js

- [ ] **Step 2a: Fix costing in buildRouteData()**

In `frontend/nav-ui.js`, in `buildRouteData()` at line 246, replace:
```js
costing: trip.legs && trip.legs[0] ? (trip.legs[0].summary || {}).costing || 'auto' : 'auto',
```
With:
```js
costing: trip._costing || 'auto',
```

### Step 3: Verify

- [ ] **Step 3a: Manual verification**

1. Select "bicycle" costing, calculate a route, start navigation
2. Check voice announcement thresholds -- verify bicycle thresholds [400, 100, 30] are used, not auto [800, 200, 50]
3. Select "pedestrian" costing, repeat -- verify pedestrian thresholds [200, 50, 20]

### Commit

- [ ] Commit with message: `fix(nav): propagate costing model to navigation engine (B9)`

BEFORE marking this task complete:
1. Verify all changes match the spec exactly
2. Test manually if browser-only code
3. Run any existing tests to verify no regression

---

## Task 9: Multi-Leg Duplicate Coordinates (B11)

**Files:** `frontend/nav-ui.js` only

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD where testable. For browser-only UI code, verify manually.

### Step 1: Fix leg coordinate concatenation

- [ ] **Step 1a: Skip shared waypoints and adjust maneuver indices**

In `frontend/nav-ui.js`, in `buildRouteData()`, replace the leg iteration at lines 222-234:
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
With:
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

### Step 2: Verify

- [ ] **Step 2a: Manual verification**

1. Create a multi-waypoint route (A -> B -> C)
2. Start navigation -- verify no duplicate coordinates at waypoint B
3. Verify maneuver instructions fire at correct positions (not offset by duplicate points)
4. Verify the route polyline renders correctly on the map

### Commit

- [ ] Commit with message: `fix(nav): remove duplicate waypoint coords in multi-leg routes (B11)`

BEFORE marking this task complete:
1. Verify all changes match the spec exactly
2. Test manually if browser-only code
3. Run any existing tests to verify no regression

---

## Task 10: GPS Heartbeat Data Freshness (B13)

**Files:** `frontend/nav-ui.js` only
**Depends on:** Task 1 (event-driven GPS feed)

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD where testable. For browser-only UI code, verify manually.

### Step 1: Add GPS signature tracking

- [ ] **Step 1a: Add signature variable**

In `frontend/nav-ui.js`, in the STATE section (near line 20), add:
```js
var lastGPSSignature = null;
```

### Step 2: Update heartbeat logic in feedGPS()

- [ ] **Step 2a: Only reset heartbeat when GPS data actually changes**

In `frontend/nav-ui.js`, in `feedGPS()`, replace the heartbeat block (lines 324-328):
```js
// GPS heartbeat -- reset timer
clearTimeout(gpsHeartbeatTimer);
gpsHeartbeatTimer = setTimeout(function () {
  showBanner('GPS signal delayed', 'gps-stale');
}, GPS_HEARTBEAT_MS);
```
With:
```js
// GPS heartbeat -- only reset timer when position actually changes
var sig = lat + ',' + lng;
if (sig !== lastGPSSignature) {
  lastGPSSignature = sig;
  clearTimeout(gpsHeartbeatTimer);
  gpsHeartbeatTimer = setTimeout(function () {
    showBanner('GPS signal delayed', 'gps-stale');
  }, GPS_HEARTBEAT_MS);
}
```

### Step 3: Reset signature in stopNavigation()

- [ ] **Step 3a: Clear lastGPSSignature**

In `frontend/nav-ui.js`, in `stopNavigation()`, add:
```js
lastGPSSignature = null;
```

### Step 4: Verify

- [ ] **Step 4a: Manual verification**

1. Start navigation, stay stationary -- after 3 seconds of identical GPS data, verify "GPS signal delayed" banner appears
2. Start moving -- verify banner disappears when position changes
3. Stop and restart navigation -- verify no stale signature carried over

### Commit

- [ ] Commit with message: `fix(nav): GPS heartbeat checks data freshness, not just receipt (B13)`

BEFORE marking this task complete:
1. Verify all changes match the spec exactly
2. Test manually if browser-only code
3. Run any existing tests to verify no regression

---

## Task 11: Mobile UI Overlap (B8)

**Files:** `frontend/nav-ui.js`, `frontend/style.css`

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD where testable. For browser-only UI code, verify manually.

### Step 1: Add nav-active body class

- [ ] **Step 1a: Add class in startNavigation()**

In `frontend/nav-ui.js`, in `startNavigation()`, after `active = true;` (line 144), add:
```js
document.body.classList.add('nav-active');
```

- [ ] **Step 1b: Remove class in stopNavigation()**

In `frontend/nav-ui.js`, in `stopNavigation()`, after `active = false;` (line 181), add:
```js
document.body.classList.remove('nav-active');
```

### Step 2: Update CSS variable for overlay height

- [ ] **Step 2a: Set --nav-overlay-height in onNavUpdate()**

In `frontend/nav-ui.js`, in `onNavUpdate()`, at the end of the function (before the closing brace), add:
```js
document.documentElement.style.setProperty('--nav-overlay-height', overlay.offsetHeight + 'px');
```

### Step 3: Add CSS rules for nav-active state

- [ ] **Step 3a: Add nav-active repositioning rules**

In `frontend/style.css`, at the end of the file (after line 1553), add:
```css

/* ----- Navigation Active — Reposition overlapping elements ----- */
body.nav-active #sidebar-toggle {
  top: calc(var(--nav-overlay-height, 100px) + 8px);
}

body.nav-active #search-container {
  top: calc(var(--nav-overlay-height, 100px) + 8px);
  left: 52px;
}
```

### Step 4: Verify

- [ ] **Step 4a: Manual verification**

1. On mobile viewport (480px width), start navigation
2. Verify sidebar toggle button is below nav overlay, not overlapping
3. Verify search bar is below nav overlay, not overlapping
4. Verify search bar is still usable (not hidden)
5. Stop navigation -- verify elements return to normal positions
6. On desktop, verify no visual change (nav overlay doesn't overlap these elements at wider widths)

**Do NOT:**
- Hide the sidebar toggle entirely -- users may need settings during navigation
- Change z-index values -- the stack is correct for non-navigation mode

### Commit

- [ ] Commit with message: `fix(nav): reposition sidebar/search below nav overlay on mobile (B8)`

BEFORE marking this task complete:
1. Verify all changes match the spec exactly
2. Test manually if browser-only code
3. Run any existing tests to verify no regression

---

## Task 12: Global Compass Button (D1)

**Files:** `frontend/app.js`, `frontend/nav-ui.js`, `frontend/style.css`

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md (especially Pitfall #11 -- dragRotate)
Follow TDD where testable. For browser-only UI code, verify manually.

### Step 1: Create compass button in app.js

- [ ] **Step 1a: Add compass button after NavigationControl**

In `frontend/app.js`, after line 158 (`map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');`), add the compass button:

```js
// Custom compass button (avoids Pitfall #11 -- NavigationControl compass re-enables dragRotate)
var compassBtn = document.createElement('button');
compassBtn.id = 'compass-north-btn';
compassBtn.className = 'map-btn';
compassBtn.title = 'Reset to north';
// Build SVG compass icon via DOM API (no innerHTML)
var compassNS = 'http://www.w3.org/2000/svg';
var compassSvg = document.createElementNS(compassNS, 'svg');
compassSvg.setAttribute('viewBox', '0 0 24 24');
compassSvg.setAttribute('width', '20');
compassSvg.setAttribute('height', '20');
compassSvg.setAttribute('fill', 'none');
compassSvg.setAttribute('stroke', 'currentColor');
compassSvg.setAttribute('stroke-width', '2');
compassSvg.setAttribute('stroke-linecap', 'round');
compassSvg.setAttribute('stroke-linejoin', 'round');
// North arrow
var compassArrow = document.createElementNS(compassNS, 'polygon');
compassArrow.setAttribute('points', '12,2 15,10 12,8 9,10');
compassArrow.setAttribute('fill', '#f38ba8');
compassArrow.setAttribute('stroke', '#f38ba8');
compassSvg.appendChild(compassArrow);
// South arrow
var compassSouth = document.createElementNS(compassNS, 'polygon');
compassSouth.setAttribute('points', '12,22 9,14 12,16 15,14');
compassSouth.setAttribute('fill', 'currentColor');
compassSouth.setAttribute('stroke', 'currentColor');
compassSvg.appendChild(compassSouth);
// Circle
var compassCircle = document.createElementNS(compassNS, 'circle');
compassCircle.setAttribute('cx', '12');
compassCircle.setAttribute('cy', '12');
compassCircle.setAttribute('r', '10');
compassSvg.appendChild(compassCircle);
// N label
var compassN = document.createElementNS(compassNS, 'text');
compassN.setAttribute('x', '12');
compassN.setAttribute('y', '6');
compassN.setAttribute('text-anchor', 'middle');
compassN.setAttribute('font-size', '5');
compassN.setAttribute('fill', '#f38ba8');
compassN.setAttribute('stroke', 'none');
compassN.textContent = 'N';
compassSvg.appendChild(compassN);
compassBtn.appendChild(compassSvg);
compassBtn.addEventListener('click', function () {
  map.easeTo({ bearing: 0, duration: 500 });
});
document.getElementById('map').appendChild(compassBtn);

// Rotate the button to show current bearing
map.on('rotate', function () {
  compassBtn.style.transform = 'rotate(' + (-map.getBearing()) + 'deg)';
});
```

### Step 2: Style the compass button

- [ ] **Step 2a: Add compass button CSS**

In `frontend/style.css`, at the end of the file (after the nav-active rules added in Task 11), add:
```css

/* ----- Compass Button ----- */
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

### Step 3: Integrate with navigation auto-center

- [ ] **Step 3a: Compass click pauses auto-center during navigation**

In `frontend/nav-ui.js`, in `init()`, after the manual pan event listeners (after line 93: `map.on('wheel', onManualPan);`), add:
```js
// Compass click pauses auto-center during navigation
var compassBtn = document.getElementById('compass-north-btn');
if (compassBtn) {
  compassBtn.addEventListener('click', function () {
    if (active) {
      onManualPan();  // pause auto-center for 10 seconds
    }
  });
}
```

### Step 4: Verify

- [ ] **Step 4a: Manual verification**

1. Verify compass button appears above zoom controls on desktop
2. Rotate the map -- verify compass button rotates to show current bearing
3. Click compass -- verify map returns to north (bearing 0)
4. On mobile (480px), verify compass button position adjusts
5. Start navigation, rotate map via compass click -- verify auto-center pauses for 10 seconds
6. Verify compass does NOT re-enable dragRotate (Pitfall #11)

**Do NOT:**
- Use `NavigationControl` with `showCompass: true` -- Pitfall #11
- Call `dragRotate.enable()` or `.disable()` -- not needed, compass only sets bearing
- Hide the compass during navigation -- it's useful to check orientation

### Commit

- [ ] Commit with message: `feat(nav): add global compass button for return-to-north (D1)`

BEFORE marking this task complete:
1. Verify all changes match the spec exactly
2. Test manually if browser-only code
3. Run any existing tests to verify no regression

---

## Post-Implementation Checklist

- [ ] All 14 bug fixes (B1-B14) implemented
- [ ] 1 feature (D1) implemented
- [ ] All commits have descriptive messages
- [ ] Run `python -m pytest tests/ -v` from repo root to verify no backend regression
- [ ] Manual smoke test: start navigation, drive a route, trigger reroute, mute/unmute voice, check compass, check mobile layout
- [ ] No `let` or `const` introduced -- all new code uses `var` per codebase style
- [ ] No `innerHTML` used -- all DOM construction via DOM API
- [ ] No `dragRotate.enable()` calls added -- Pitfall #11
