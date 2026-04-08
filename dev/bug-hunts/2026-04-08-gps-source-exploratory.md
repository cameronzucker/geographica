# Bug Hunt Report: GPS Source Switching -- Position Oscillation

## Scope

Deep exploration of the GPS source-switching logic in `frontend/app.js` (lines 1267-1455), with thread-following into:
- `services/gps/main.py` -- server-side WebSocket broadcaster
- `frontend/nav-ui.js` -- turn-by-turn navigation GPS consumer
- `frontend/navigation.js` -- navigation engine state machine

Primary focus: the interaction between `switchGPSSource()`, `connectGPS()`, `scheduleGPSReconnect()`, and `updateGPSPosition()` -- the four functions that control which GPS source feeds the map marker.

## Bugs

### 1. WebSocket onclose triggers reconnect even when user switched to device GPS

**Location:** `frontend/app.js:1383-1386` (onclose handler) and `frontend/app.js:1395-1400` (scheduleGPSReconnect)
**Severity:** critical
**Evidence:**

When the user switches to device GPS:
1. Line 1286: `gpsSource = 'device'`
2. Line 1307: `gpsWs.close(); gpsWs = null;` -- closes the WebSocket, setting the variable to null
3. The `onclose` handler (line 1383) was already bound to the *WebSocket object itself*, not the `gpsWs` variable. Setting `gpsWs = null` does not prevent `onclose` from firing on the old WebSocket instance.
4. The `onclose` handler fires asynchronously: calls `setGPSStale(true)` (incorrectly marking device GPS as stale) and `scheduleGPSReconnect()`.
5. `scheduleGPSReconnect()` (line 1395) unconditionally calls `connectGPS()` after 5 seconds -- it does NOT check whether `gpsSource === 'server'`.
6. `connectGPS()` (line 1357) also has no `gpsSource` guard -- it unconditionally opens a new WebSocket and registers an `onmessage` handler that calls `updateGPSPosition()`.
7. Result: after exactly 5 seconds, BOTH `watchPosition` AND the server WebSocket are simultaneously feeding `updateGPSPosition()`, causing the marker to oscillate between the device's location and the Pi's location at ~1 Hz.

**Impact:** The position marker jumps back and forth between two locations on every connected secondary device. The turn-by-turn navigation engine (`nav-ui.js:298-314`) polls `window._geographicaGPSData` every 500ms, so it receives alternating positions -- this would cause the off-route detector to trigger false reroutes (50m threshold at `navigation.js:21`), and the snap-to-route algorithm to fail as the position jumps between two distant points.

### 2. scheduleGPSReconnect uses fire-and-forget setTimeout with no cancellation mechanism

**Location:** `frontend/app.js:1395-1400`
**Severity:** significant
**Evidence:**

```javascript
function scheduleGPSReconnect() {
    setTimeout(function () {
      console.log('GPS: attempting reconnect...');
      connectGPS();
    }, GPS_RECONNECT_MS);
  }
```

The `setTimeout` return value is never stored. There is no `gpsReconnectTimer` variable anywhere in the file. This means:
- Even if Bug #1 were partially fixed by adding a `gpsSource` check inside `connectGPS()`, any already-scheduled reconnect timer cannot be cancelled.
- If the WebSocket has transient connection issues before the user switches sources, multiple reconnect timers can stack up (each `onclose` schedules a new one, and each failed `connectGPS` schedules another via its own `catch` at line 1364-1366).

**Impact:** Multiple simultaneous WebSocket connections can be opened, or reconnection behavior becomes unpredictable. The stacking problem exists independently of the source-switching bug.

### 3. getCurrentPosition error callback does not clear watchPosition

**Location:** `frontend/app.js:1310-1322` (getCurrentPosition error callback) and `frontend/app.js:1324` (watchPosition)
**Severity:** significant
**Evidence:**

The code flow when switching to device GPS:
1. Line 1310: `getCurrentPosition()` fires asynchronously (for permission prompt)
2. Line 1324: `watchPosition()` runs synchronously, immediately registering a watch and storing the ID in `deviceWatchId`
3. If the user denies permission, the `getCurrentPosition` error callback runs (line 1312-1321):
   - Sets `gpsSource = 'server'`
   - Calls `connectGPS()` to restart server GPS
   - Does NOT call `navigator.geolocation.clearWatch(deviceWatchId)`
   - Does NOT set `deviceWatchId = null`

The `watchPosition` call at line 1324 already executed before the async error callback. In most browsers, if the user denies permission for `getCurrentPosition`, the `watchPosition` error handler (line 1338) will also fire with a permission error -- but this is browser-dependent behavior and not guaranteed to fire synchronously or at all. Even if it does fire, it only calls `setGPSStale(true)` -- it does NOT clear the watch.

**Impact:** After permission denial, `deviceWatchId` holds a reference to an active (but erroring) watch. When the user later switches back to server GPS, `clearWatch(deviceWatchId)` at line 1349 will work -- but until then, the error callback at line 1338-1340 fires repeatedly, calling `setGPSStale(true)` and overriding the server GPS's non-stale state. The stale indicator flickers.

### 4. WebSocket onclose marks device GPS as stale

**Location:** `frontend/app.js:1383-1386`
**Severity:** minor
**Evidence:**

When the user intentionally closes the WebSocket to switch to device GPS (line 1307), the `onclose` handler fires and calls `setGPSStale(true)` at line 1385. This marks the GPS as stale even though device GPS is about to (or already is) providing valid positions. The stale state persists until the next `updateGPSPosition()` call from `watchPosition` sets it back.

**Impact:** Brief UI flash of "GPS signal lost" immediately after switching to device GPS, even when the device has a valid fix. Minor UX annoyance that confuses users into thinking the switch failed.

## Design Concerns

### No source-awareness in the data pipeline

`updateGPSPosition()` (line 1406) and `window._geographicaGPSData` (line 1411) have no concept of which source provided the data. There is no way for downstream consumers (navigation engine, UI) to distinguish between server GPS and device GPS data, or to detect that both are writing simultaneously. A `source` field in the data object would enable defensive checks.

### Implicit coupling between WebSocket lifecycle and GPS source state

The WebSocket's `onclose`/`onerror` handlers and the `scheduleGPSReconnect` function operate as an autonomous reconnection loop that is completely independent of the `gpsSource` state variable. This is the root architectural issue -- the reconnection logic was designed assuming the WebSocket is the only GPS source, and the device GPS feature was bolted on without integrating the reconnection guard.

### connectGPS() does not close existing WebSocket before opening new one

`connectGPS()` at line 1357-1393 creates a new WebSocket at line 1362 and assigns it to `gpsWs`, but never checks if `gpsWs` already holds an open connection. If called while a connection is active (e.g., from a stacked reconnect timer), the old WebSocket is orphaned -- its `onclose` handler still references the old instance and will fire later, potentially triggering yet another reconnect cycle.
