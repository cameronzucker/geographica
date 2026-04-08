# Bug Hunt Report: GPS Source Switching -- Position Oscillation

## Scope

**Files analyzed:**
- `frontend/app.js` (lines 1267-1530) -- GPS section: `initGPS`, `switchGPSSource`, `connectGPS`, `scheduleGPSReconnect`, `updateGPSPosition`, `setGPSStale`
- `services/gps/main.py` (220 lines) -- Backend GPS WebSocket service, broadcaster
- `frontend/navigation.js` (790 lines) -- Turn-by-turn navigation engine, `GeographicaNav`

**Passes performed:** All five (contract violations, cross-sibling patterns, failure modes, concurrency, error propagation).

---

## Bugs

### 1. Reconnect timer fires unconditionally, re-enabling server GPS while device GPS is active

**Location:** `frontend/app.js:1383-1399`
**Severity:** critical
**Evidence:**

When `switchGPSSource('device')` is called:
1. Line 1307: `gpsWs.close()` closes the WebSocket and sets `gpsWs = null`
2. Closing the WebSocket fires the `onclose` handler at line 1383
3. `onclose` calls `scheduleGPSReconnect()` at line 1386
4. `scheduleGPSReconnect()` (line 1395) fires `connectGPS()` after 5000ms
5. `connectGPS()` (line 1357) has **no guard** checking `gpsSource` -- it unconditionally opens a new WebSocket
6. The new WebSocket's `onmessage` (line 1374) calls `updateGPSPosition(data)` unconditionally -- **no source check**

After 5 seconds, both `watchPosition` and the server WebSocket are feeding `updateGPSPosition()` simultaneously. The marker oscillates between the Pi's GPS coordinates and the device's GPS coordinates at ~1 Hz.

**Impact:** The marker visibly jumps between two locations every second. `window._geographicaGPSData` alternates between device and server data, so the navigation engine (`GeographicaNav.updateGPS`) also receives interleaved positions, causing erratic route snapping, phantom off-route detections, and potentially spurious reroutes.

**Found in:** Pass 1 -- Contract Violations. `switchGPSSource('device')` promises to stop the server GPS, but the auto-reconnect silently re-establishes it.

---

### 2. Reconnect timer is not cancellable -- no stored timer ID

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

The `setTimeout` return value is never stored. There is no `clearTimeout` call anywhere in the GPS section. This means:
- Even if Bug #1 were fixed by adding a `gpsSource` guard in `connectGPS()`, any reconnect timer already in flight from a previous close cannot be cancelled.
- Rapid toggling between server and device could queue multiple reconnect timers, each firing 5 seconds later.

**Impact:** Without a stored timer ID, there is no way to cancel pending reconnections when switching sources. Multiple timers can accumulate if the WebSocket experiences repeated close/error cycles.

**Found in:** Pass 3 -- Failure Mode Reasoning.

---

### 3. `watchPosition` starts before `getCurrentPosition` permission is granted

**Location:** `frontend/app.js:1310-1342`
**Severity:** significant
**Evidence:**

```javascript
// Line 1310: async -- fires permission prompt
navigator.geolocation.getCurrentPosition(
    function () { /* permission granted */ },
    function (err) {
        // ...revert to server...
        gpsSource = 'server';
        connectGPS();
        return;
    }
);

// Line 1324: runs immediately, does NOT wait for the callback above
deviceWatchId = navigator.geolocation.watchPosition( ... );
```

`getCurrentPosition` is async (callback-based). `watchPosition` at line 1324 executes synchronously after `getCurrentPosition` is *called*, not after its callback fires. Two problems:

**(a) If permission is denied:** The `getCurrentPosition` error callback (line 1312) sets `gpsSource = 'server'` and calls `connectGPS()`. But `watchPosition` was already started at line 1324 and stored in `deviceWatchId`. The error callback never calls `clearWatch(deviceWatchId)`. Now both the server WebSocket AND a (broken) device watch are active. The device watch fires repeated errors to its own error handler (line 1338), which calls `setGPSStale(true)` -- fighting the server GPS that's setting `setGPSStale(false)`.

**(b) If permission is pending (browser shows prompt):** `watchPosition` may fail or be held pending while the user hasn't responded to the prompt. If `watchPosition` fires its error callback before the user acts, `setGPSStale(true)` is called even though the server WebSocket was already closed. The GPS badge shows "stale" during a normal permission flow.

**Impact:** Permission denial leaves both sources partially active. The stale indicator flickers. `deviceWatchId` is orphaned and never cleaned up.

**Found in:** Pass 3 -- Failure Mode Reasoning.

---

### 4. WebSocket `onmessage` handler does not check `gpsSource` before calling `updateGPSPosition`

**Location:** `frontend/app.js:1374-1380`
**Severity:** significant (defense-in-depth gap)
**Evidence:**

```javascript
gpsWs.onmessage = function (event) {
    try {
        var data = JSON.parse(event.data);
        updateGPSPosition(data);  // No source check
    } catch (e) {
        console.warn('GPS parse error:', e);
    }
};
```

Neither `onmessage` nor `updateGPSPosition` checks `gpsSource`. If for any reason a WebSocket exists while `gpsSource === 'device'` (which Bug #1 guarantees happens), server data flows directly into the position update pipeline.

A single guard (`if (gpsSource !== 'server') return;`) in `onmessage` would prevent the oscillation even if the reconnect bug fires.

**Impact:** The core data path has no source discrimination, making every reconnect or connection-related bug immediately surface as position oscillation.

**Found in:** Pass 2 -- Cross-Sibling Pattern Violations. The device GPS callback (line 1325) implicitly assumes it's the only source writing to `updateGPSPosition`, but the WebSocket handler makes the same assumption. Neither guards against the other.

---

### 5. `connectGPS()` does not check or close existing WebSocket before creating a new one

**Location:** `frontend/app.js:1357-1367`
**Severity:** minor
**Evidence:**

```javascript
function connectGPS() {
    var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var wsUrl = protocol + '//' + location.host + '/gps/ws';

    try {
        gpsWs = new WebSocket(wsUrl);  // overwrites any existing reference
    } catch (e) { ... }
```

If `gpsWs` already references an open WebSocket (e.g., from rapid toggling or multiple timers), the old connection is silently orphaned -- its `onmessage` still fires because the browser keeps the connection alive, but the variable now points to the new one. The old WebSocket's closure later triggers yet another `scheduleGPSReconnect()`, creating a cascade.

**Impact:** Multiple zombie WebSocket connections can accumulate, each feeding `updateGPSPosition` independently, amplifying the oscillation from two sources to potentially more.

**Found in:** Pass 4 -- Concurrency Reasoning.

---

### 6. `getCurrentPosition` error callback has unreachable `return` after `connectGPS()`

**Location:** `frontend/app.js:1319-1320`
**Severity:** minor (code clarity, not functional)
**Evidence:**

```javascript
function (err) {
    var msg = ...;
    alert(msg);
    document.querySelector('input[name="gpssource"][value="server"]').checked = true;
    gpsSource = 'server';
    connectGPS();
    return;  // <-- unreachable in the sense that nothing follows, but harmless
}
```

The `return` is technically reachable but serves no purpose -- there's no code after it in the callback. More importantly, the callback does NOT call `navigator.geolocation.clearWatch(deviceWatchId)` to clean up the watch that was already started at line 1324. This is the actionable issue (see Bug #3).

**Found in:** Pass 5 -- Error Propagation.

---

## Design Concerns

### No source-awareness in the data pipeline

`updateGPSPosition(data)` is a single funnel for all GPS data with no concept of which source produced it. The `data` object from the server WebSocket and from `watchPosition` have different shapes (server sends `heading`, device sends `coords.heading`; server sends `speed` in m/s, device sends `coords.speed` which may also be m/s but from a different sensor). While the field aliasing in `updateGPSPosition` (`data.lon || data.lng || data.longitude`) papers over some differences, there's no `data.source` field to enable logging, debugging, or guard logic downstream.

### State machine gap: no "transitioning" state

The `gpsSource` variable flips instantly between `'server'` and `'device'`, but the actual transition involves async operations (permission prompt, WebSocket close, reconnect timer). There's no intermediate state like `'switching'` that guards would check. This means the gap between intent (`gpsSource = 'device'`) and reality (server WebSocket still alive for 5+ seconds) is invisible to the rest of the code.

### Navigation engine receives unfiltered interleaved positions

`window._geographicaGPSData` is set on every `updateGPSPosition` call (line 1411). The navigation engine's `updateGPS` method reads this. When two sources interleave, the navigation engine sees the position "teleport" back and forth, which causes:
- Snap position jumps between distant route segments
- `offRouteCount` increments when the "wrong" source position is far from the route
- After `OFF_ROUTE_TICKS` (5) consecutive off-route ticks, a reroute is triggered
- Speed calculations become nonsensical (apparent speed = distance between two different GPS receivers / 1 second)

### Server broadcasts to ALL clients regardless of need

The backend `_broadcaster()` (main.py:164) sends position to every connected WebSocket client at 1 Hz unconditionally. There's no client-side subscription/unsubscription protocol. This means even if the client "doesn't want" server GPS data, the server keeps sending it. The only defense is the client closing the WebSocket, which triggers the reconnect bug.

---

## Summary of Root Cause Chain

The user's reported oscillation is caused by this exact sequence:

1. User selects "on-device GPS"
2. `switchGPSSource('device')` sets `gpsSource = 'device'`
3. `gpsWs.close()` closes the WebSocket (line 1307)
4. `watchPosition` starts feeding device GPS to `updateGPSPosition` (line 1324)
5. WebSocket `onclose` fires, calling `scheduleGPSReconnect()` (line 1386)
6. 5 seconds later, `connectGPS()` opens a new WebSocket (line 1398) -- **no `gpsSource` check**
7. New WebSocket `onmessage` feeds server GPS to `updateGPSPosition` (line 1377) -- **no `gpsSource` check**
8. Both sources now feed the same function at ~1 Hz, causing oscillation

The fix requires **at minimum** two changes:
1. `scheduleGPSReconnect()` / `connectGPS()` must check `gpsSource === 'server'` before reconnecting
2. Store the reconnect timer ID so it can be cancelled when switching to device GPS

A robust fix would also:
3. Add a `gpsSource` guard in `onmessage`
4. Close any existing WebSocket in `connectGPS()` before creating a new one
5. Call `clearWatch(deviceWatchId)` in the `getCurrentPosition` error callback
6. Move `watchPosition` inside the `getCurrentPosition` success callback
