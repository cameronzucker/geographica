# Bug Hunt Report

## Scope

**Primary file:** `frontend/app.js` lines 1267-1560 (GPS section)
**Adjacent files:** `services/gps/main.py`, `frontend/navigation.js`, `frontend/nav-ui.js`

Deep-dived on the GPS source switching logic in `switchGPSSource()`, the `connectGPS()` WebSocket lifecycle, and the `updateGPSPosition()` data path. Traced the async race between `getCurrentPosition` callbacks and user-initiated source switches.

## Bugs

### 1. Race condition: getCurrentPosition success callback fires after switch back to server, starts orphaned watchPosition

**Location:** `frontend/app.js:1317-1355`
**Severity:** critical
**Evidence:**

The exact scenario from the hypothesis is confirmed as a real bug in the code:

1. User selects "device GPS". `switchGPSSource('device')` runs:
   - Line 1287: sets `gpsSource = 'device'`
   - Line 1314: closes WebSocket
   - Line 1317: calls `navigator.geolocation.getCurrentPosition(successCb, errorCb)` -- this is **async**
   - `deviceWatchId` is still `null` at this point

2. User switches back to "server GPS" before the permission prompt resolves. `switchGPSSource('server')` runs:
   - Line 1287: sets `gpsSource = 'server'`
   - Line 1360-1363: checks `if (deviceWatchId !== null)` -- it IS null because the success callback hasn't fired yet. **Nothing is cleared.**
   - Line 1365: calls `connectGPS()`, which opens a new server WebSocket

3. The `getCurrentPosition` success callback (line 1318) fires asynchronously. It does **not** check `gpsSource` before proceeding. It calls `navigator.geolocation.watchPosition()` at line 1320, which:
   - Assigns to `deviceWatchId` (overwriting null)
   - Starts delivering device GPS positions via `updateGPSPosition()` at line 1332

4. Now BOTH sources are active simultaneously:
   - Server WebSocket delivering Pi GPS at 1 Hz via `gpsWs.onmessage` -> `updateGPSPosition()`
   - Browser `watchPosition` delivering device GPS via its callback -> `updateGPSPosition()`

The `gpsWs.onmessage` handler at line 1398 does check `if (gpsSource !== 'server') return;`, which would guard against the inverse problem (server data leaking into device mode). But the device `watchPosition` callback at line 1321 has **no equivalent guard** -- it calls `updateGPSPosition(data)` unconditionally regardless of `gpsSource`.

**Impact:** Position oscillates between server GPS (Pi's location) and device GPS (remote device's location). On a remote device accessing via Tailscale, these could be hundreds of miles apart. The marker jumps wildly, navigation becomes impossible, and the GPS readout flickers between two positions.

### 2. WebSocket onclose fires after switchGPSSource('device') closes it, scheduling a phantom reconnect

**Location:** `frontend/app.js:1314` and `1407-1413`
**Severity:** significant
**Evidence:**

When `switchGPSSource('device')` runs, line 1314 does:
```js
if (gpsWs) { gpsWs.close(); gpsWs = null; }
```

But unlike `connectGPS()` (line 1375), which carefully sets `gpsWs.onclose = null` before calling `.close()`, the close at line 1314 does NOT null out the `onclose` handler. The WebSocket `close` event fires asynchronously. The `onclose` handler at line 1407-1413 checks `if (gpsSource === 'server')` -- at this point `gpsSource` is `'device'` so the reconnect is skipped.

However, this is fragile. If the `close` event is delayed (queued behind a microtask or after a brief network stall), and the user has already switched back to server mode by the time `onclose` fires, then `gpsSource === 'server'` is true and `scheduleGPSReconnect()` fires. This creates a reconnect timer that races with the `connectGPS()` already called by the server switch, potentially opening two WebSocket connections.

Even without the timing edge case: the pattern is inconsistent. `connectGPS()` carefully nulls onclose before closing (line 1375), but `switchGPSSource()` does not (line 1314). This is a correctness defect -- the same cleanup pattern should be applied in both places.

**Impact:** Under the race condition in Bug #1 (user switches device->server quickly), this creates a second WebSocket connection alongside the first. Two WebSockets both feeding `updateGPSPosition()` doubles the update rate and creates redundant network traffic. The `onmessage` guard at line 1398 prevents data corruption, but two connections consume resources unnecessarily.

### 3. getCurrentPosition cannot be cancelled -- no mechanism to abort in-flight geolocation request

**Location:** `frontend/app.js:1317` (getCurrentPosition call) and `1358-1366` (server switch path)
**Severity:** significant
**Evidence:**

The Geolocation API's `getCurrentPosition()` has no cancellation mechanism. Once called at line 1317, it will eventually invoke either the success or error callback -- there is no way to prevent this. When `switchGPSSource('server')` runs at line 1358-1366, it can only clear an existing `watchPosition` via `clearWatch(deviceWatchId)`. It cannot abort the pending `getCurrentPosition`.

This means Bug #1 is **unfixable** by simply adding a `clearWatch` call in the server-switch path. The fix must add a state guard inside the success callback itself:

```js
// line 1318 success callback
function () {
  if (gpsSource !== 'device') return;  // <-- MISSING GUARD
  deviceWatchId = navigator.geolocation.watchPosition(...);
}
```

Without this guard, any fix that only modifies the `switchGPSSource('server')` path will fail because `getCurrentPosition` callbacks are not cancellable.

**Impact:** This is the root cause that makes Bug #1 structurally unfixable without modifying the async callbacks themselves. The error callback at line 1341 has the same problem -- if it fires after a switch to server mode, it calls `alert()`, resets `gpsSource` to `'server'`, and calls `connectGPS()` again, potentially creating a duplicate WebSocket connection.

## Design Concerns

### Asymmetric guards on updateGPSPosition callers

The server WebSocket `onmessage` handler (line 1398) guards with `if (gpsSource !== 'server') return;`, but the device `watchPosition` callback (line 1321) has no equivalent `if (gpsSource !== 'device') return;` guard. Both callers should have symmetric guards to prevent stale data from either source reaching `updateGPSPosition()`.

### No "switching" transitional state

The code uses a simple `gpsSource` string that flips immediately on line 1287, but the actual transition is async (permission prompt, WebSocket connect). A transitional state like `gpsSource = 'switching-to-device'` would make it explicit that neither source should be active during the transition, and both callbacks could check for it.

### Shared mutable state without coordination

`deviceWatchId`, `gpsSource`, and `gpsWs` are all mutated by both synchronous code (user clicking radios) and async callbacks (geolocation, WebSocket events). There is no coordination mechanism (e.g., a monotonic sequence number or a "current operation" token) to let async callbacks detect that they are stale. A simple incrementing counter, checked by each callback, would make all race conditions detectable.
