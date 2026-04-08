# Bug Hunt Report — GPS Source Switching

## Scope
Files analyzed:
- `frontend/app.js` lines 1-50 (state vars), 1267-1530 (GPS section)
- `frontend/navigation.js` (full file, 790 lines)
- `frontend/nav-ui.js` lines 155-175, 295-315 (GPS feed into nav engine)
- `services/gps/main.py` (full file, 220 lines)

Approach: Read all source files involved in the GPS data flow end-to-end — from hardware GPS hat through gpsd, through the WebSocket service, through the frontend WebSocket client and Geolocation API, through the shared `updateGPSPosition()` function, and into the navigation engine. Then traced all state transitions in `switchGPSSource()`, `connectGPS()`, and `scheduleGPSReconnect()`.

## Bugs

### 1. WebSocket reconnect ignores gpsSource — causes position oscillation
**Location:** `frontend/app.js:1383-1386` (onclose handler), `frontend/app.js:1395-1400` (scheduleGPSReconnect), `frontend/app.js:1357` (connectGPS)
**Severity:** critical
**Evidence:**

When the user switches to device GPS, `switchGPSSource('device')` at line 1307 calls `gpsWs.close()`. This fires the `onclose` handler at line 1383:

```js
gpsWs.onclose = function () {
  console.log('GPS WebSocket closed');
  setGPSStale(true);
  scheduleGPSReconnect();   // <-- fires unconditionally
};
```

`scheduleGPSReconnect()` at line 1395 calls `connectGPS()` after 5 seconds:

```js
function scheduleGPSReconnect() {
  setTimeout(function () {
    console.log('GPS: attempting reconnect...');
    connectGPS();   // <-- no guard on gpsSource
  }, GPS_RECONNECT_MS);
}
```

`connectGPS()` at line 1357 creates a new WebSocket unconditionally — there is no `if (gpsSource !== 'device') return;` guard. The new WebSocket's `onmessage` at line 1374 calls `updateGPSPosition(data)` unconditionally — no source check.

Result: 5 seconds after switching to device GPS, the server WebSocket silently reconnects. Both `watchPosition` (device) and the WebSocket (server) now feed `updateGPSPosition()` simultaneously at ~1 Hz each, causing the map marker to oscillate between two geographic positions.

**Impact:** The GPS marker jumps back and forth between the Pi's location and the phone's location every ~500ms. During turn-by-turn navigation, `nav-ui.js:298` feeds `window._geographicaGPSData` to the navigation engine at 500ms intervals, so the nav engine receives alternating positions — triggering spurious off-route detections and reroutes.

---

### 2. Scheduled reconnect timer is not cancellable — races with manual source switches
**Location:** `frontend/app.js:1395-1400` (scheduleGPSReconnect)
**Severity:** significant
**Evidence:**

The reconnect timer is a bare `setTimeout` whose ID is never stored:

```js
function scheduleGPSReconnect() {
  setTimeout(function () {
    console.log('GPS: attempting reconnect...');
    connectGPS();
  }, GPS_RECONNECT_MS);
}
```

There is no `gpsReconnectTimer` variable and no `clearTimeout()` anywhere in the codebase. This means:

1. If the WebSocket connection fails on creation (line 1363-1367), `scheduleGPSReconnect()` is called. If it fails again on the next attempt, another timer is scheduled. Multiple concurrent timers can stack up.
2. When switching to device GPS, `gpsWs.close()` triggers `onclose` which schedules a reconnect. Even if a `gpsSource` guard were added to `connectGPS()`, any timer scheduled *before* the user switches back to server GPS would become a zombie.
3. Rapid toggling between server and device could schedule multiple reconnect timers that all fire, creating multiple overlapping WebSocket connections.

**Impact:** Timer accumulation under flaky network conditions. Multiple WebSocket connections to the same endpoint, wasting bandwidth on a mesh network where bandwidth is precious.

---

### 3. getCurrentPosition and watchPosition race — device GPS starts before permission is confirmed
**Location:** `frontend/app.js:1310-1342`
**Severity:** minor
**Evidence:**

```js
// Line 1310: async — doesn't block
navigator.geolocation.getCurrentPosition(
  function () { /* permission granted */ },
  function (err) {
    // ...revert to server GPS...
    gpsSource = 'server';
    connectGPS();
    return;
  }
);

// Line 1324: executes immediately, doesn't wait for getCurrentPosition
deviceWatchId = navigator.geolocation.watchPosition(
  function (pos) { updateGPSPosition(data); },
  // ...
);
```

`watchPosition()` at line 1324 runs synchronously, before `getCurrentPosition()` has resolved. If the user denies permission in the `getCurrentPosition` prompt, the error handler at line 1312 sets `gpsSource = 'server'` and calls `connectGPS()`. But `deviceWatchId` was already set — `clearWatch()` is never called in this error path. The `watchPosition` may still be pending/active.

In the denial case:
- `gpsSource` is set to `'server'`
- `connectGPS()` restarts the WebSocket
- But `deviceWatchId` still holds the watch ID from line 1324 — it is not cleared
- If the browser later delivers a position (some browsers grant one-time access before showing the persistent prompt), both sources feed `updateGPSPosition()`

**Impact:** After permission denial, a zombie `watchPosition` listener may remain registered. On most browsers this is inert (the error callback fires for watchPosition too), but the leaked watch ID means `switchGPSSource('server')` will try to `clearWatch()` a watch that already errored — harmless but indicates the logic is unsound.

---

### 4. updateGPSPosition has no source discrimination — any caller moves the marker
**Location:** `frontend/app.js:1406-1455`
**Severity:** significant (design amplifier for Bug #1)
**Evidence:**

`updateGPSPosition(data)` does not check `gpsSource` or which caller invoked it:

```js
function updateGPSPosition(data) {
  var lng = parseFloat(data.lon || data.lng || data.longitude);
  var lat = parseFloat(data.lat || data.latitude);
  if (isNaN(lng) || isNaN(lat)) return;
  window._geographicaGPSData = data;   // <-- any source overwrites the global
  // ... moves marker, updates status ...
}
```

This function is called from two places:
1. `gpsWs.onmessage` (line 1377) — server GPS
2. `watchPosition` callback (line 1336) — device GPS

Neither caller tags the data with its source. The function has no way to reject updates from the "wrong" source. Even if Bug #1's reconnect is fixed, any future code path that accidentally calls `updateGPSPosition()` will silently hijack the marker position and the navigation engine's GPS feed (via `window._geographicaGPSData`).

**Impact:** The lack of source gating makes the oscillation bug trivially easy to reintroduce and makes it impossible to debug which source is active by inspecting `_geographicaGPSData`.

## Design Concerns

### No single source of truth for active GPS mode
The `gpsSource` variable is the intended authority, but nothing enforces it. The WebSocket `onmessage` handler and the `watchPosition` callback both unconditionally call `updateGPSPosition()`. The variable is checked in exactly zero places in the data path — only in `switchGPSSource()` for UI revert logic. A correct design would have either:
- `connectGPS()` and `scheduleGPSReconnect()` check `gpsSource` before proceeding
- `updateGPSPosition()` accept a source tag and reject mismatched updates
- Both (defense in depth)

### WebSocket lifecycle has no centralized cleanup
The WebSocket is created in `connectGPS()`, closed in `switchGPSSource()`, and reconnected by `scheduleGPSReconnect()` via a fire-and-forget `setTimeout`. There is no reconnect timer ID stored anywhere, so there is no way to cancel pending reconnects. A `gpsReconnectTimerId` variable with `clearTimeout()` in both `switchGPSSource()` and `connectGPS()` would prevent timer stacking.

### Navigation engine receives unsanitized oscillating positions
`nav-ui.js:298` polls `window._geographicaGPSData` every 500ms and feeds it to `GeographicaNav.updateGPS()`. The navigation engine's off-route detection (`navigation.js:577`) counts consecutive ticks where `distanceFromRoute > 50m`. When positions alternate between two locations (one on-route from the Pi, one potentially off-route from the phone), the counter resets to 0 every other tick, preventing reroute but causing the UI to flicker between on-route and off-route states. If both positions happen to be far from the route (phone in a different city, Pi has no fix), the counter reaches threshold and triggers spurious reroutes.
