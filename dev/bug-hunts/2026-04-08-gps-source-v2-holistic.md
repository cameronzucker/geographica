# Bug Hunt Report: GPS Source Switching v2 — Server Mode Oscillation

## Scope

Files analyzed in full:
- `frontend/app.js` (all 2627 lines) — GPS source switching, WebSocket connection, `updateGPSPosition`, the entire IIFE
- `frontend/navigation.js` (790 lines) — Turn-by-turn nav engine, `updateGPS` entry point
- `frontend/nav-ui.js` (882 lines) — Nav UI bridge, GPS feed loop reading `window._geographicaGPSData`
- `frontend/index.html` (279 lines) — inline scripts and script loading order
- `services/gps/main.py` (220 lines) — Backend GPS WebSocket service

Also searched all frontend files for any reference to `navigator.geolocation`, `getCurrentPosition`, or `watchPosition`.

Approach: traced every code path that could call `updateGPSPosition()` or write to `window._geographicaGPSData`, and mapped all state transitions in `gpsSource` and `deviceWatchId` to find how two GPS sources could feed the map simultaneously.

## Bugs

### BUG 1: `getCurrentPosition` success callback fires without checking current `gpsSource`, starts `watchPosition` even after user switches back to server mode

**Location:** `frontend/app.js:1317-1339`
**Severity:** significant

**Evidence:**

The `switchGPSSource('device')` flow:

1. Line 1287: Sets `gpsSource = 'device'`
2. Line 1314: Closes the server WebSocket
3. Line 1317: Calls `navigator.geolocation.getCurrentPosition(successCb, errorCb)` — this is **asynchronous**

The success callback at line 1318 **unconditionally** starts `watchPosition` and stores the ID in `deviceWatchId`. There is **no guard** checking whether `gpsSource` is still `'device'` when the callback fires.

Now consider the sequence:
1. User selects "This device" radio button -> `switchGPSSource('device')` runs, sets `gpsSource = 'device'`, closes WebSocket, calls `getCurrentPosition` (async, returns immediately)
2. User quickly selects "Server" radio button -> `switchGPSSource('server')` runs, sets `gpsSource = 'server'`, `deviceWatchId` is still `null` (the `getCurrentPosition` hasn't returned yet), so `clearWatch(null)` is a no-op. Then `connectGPS()` opens the server WebSocket.
3. `getCurrentPosition` success callback fires (now `gpsSource === 'server'`) — starts `watchPosition` anyway, stores the new watch ID in `deviceWatchId`. But nobody will ever clear this watch because the user is in "server" mode and `deviceWatchId` won't be checked again until the next source switch.

**Result:** Both the server WebSocket AND the browser `watchPosition` are feeding `updateGPSPosition()` simultaneously. The map oscillates between the Pi's GPS coordinates and the device's GPS coordinates.

But there's a subtler variant that doesn't even require a rapid toggle:

### BUG 2: On HTTPS with previously-granted geolocation permission, `getCurrentPosition` returns nearly instantly, but the `watchPosition` callbacks have no `gpsSource` guard

**Location:** `frontend/app.js:1320-1333`
**Severity:** critical (this is the primary reported bug)

**Evidence:**

Even in the normal "select server GPS" steady-state flow, the bug can manifest:

1. Page loads. Default is `gpsSource = 'server'`. `initGPS()` at line 1274 calls `connectGPS()` which opens the server WebSocket. The user is on HTTPS, so the browser has a secure context. Geolocation permission was granted in a previous session (sticky permission).

2. User switches to "This device" -> `switchGPSSource('device')` runs. On HTTPS with pre-granted permission, `getCurrentPosition` fires the success callback **almost immediately** (within milliseconds). The success callback starts `watchPosition` (line 1320). The device's GPS starts feeding `updateGPSPosition`.

3. User switches back to "Server" -> `switchGPSSource('server')` runs at line 1286. `gpsSource = 'server'`. At line 1360-1363, `clearWatch(deviceWatchId)` is called. `deviceWatchId` is set to the watch ID, so the watch IS cleared. Then `connectGPS()` starts the server WebSocket.

This path DOES work correctly for a single toggle. But the key issue is in the **`watchPosition` success callback** at lines 1321-1333: it calls `updateGPSPosition(data)` with **no guard** on `gpsSource`. Consider:

- The `watchPosition` callback fires at a high rate
- The `clearWatch` call may not take effect instantly on all browsers (some browsers deliver one more callback after `clearWatch`)
- But more importantly: the `getCurrentPosition` success callback at line 1318 does NOT itself check `gpsSource`. If `getCurrentPosition` is slow (e.g., GPS cold start), and the user switches to server during that wait, the callback will start a new `watchPosition` (overwriting `deviceWatchId`) — and nobody ever clears it.

The `watchPosition` success callback at line 1321 calls `updateGPSPosition(data)` unconditionally. Meanwhile the WebSocket `onmessage` at line 1397-1398 DOES check `if (gpsSource !== 'server') return;` before processing. **But the device GPS path has no equivalent guard.**

This is the asymmetry. The server GPS path guards against stale data (`if (gpsSource !== 'server') return`), but the device GPS `watchPosition` callback at line 1321 does NOT guard against `gpsSource !== 'device'`.

**Impact:** On a remote device accessing via HTTPS (Tailscale), when "Server GPS" is selected:
- If the user had previously selected "Device GPS" and then switched back, the `watchPosition` may still be running (due to the `getCurrentPosition` async race at Bug 1)
- Even if `clearWatch` was called, one final callback may slip through
- Both sources feed `updateGPSPosition()` which writes to `window._geographicaGPSData` and moves the GPS marker. The position oscillates between the Pi's GPS hat position and the remote device's browser position.

### BUG 3: `getCurrentPosition` error callback fallback to server mode creates a reconnect without clearing a potentially-started watch

**Location:** `frontend/app.js:1341-1354`
**Severity:** minor

**Evidence:**

The error callback at line 1341 does attempt to clear a watch at line 1347-1349:
```javascript
if (deviceWatchId !== null) {
    navigator.geolocation.clearWatch(deviceWatchId);
    deviceWatchId = null;
}
```

However, this error callback fires when `getCurrentPosition` itself fails. By definition, if `getCurrentPosition` fails, the success callback never ran, so `deviceWatchId` is still `null` from initialization. The cleanup code is dead — it can never do anything. This is not harmful but indicates the developer was thinking about the race condition without fully solving it.

## Design Concerns

### Missing guard pattern in device GPS callback

The WebSocket `onmessage` handler (line 1397) has a correct guard:
```javascript
if (gpsSource !== 'server') return;
```

The device `watchPosition` callback (line 1321) lacks the symmetric guard:
```javascript
if (gpsSource !== 'device') return;
```

This asymmetry is the root cause. Both GPS data paths should verify that their source mode is still active before feeding data to `updateGPSPosition`.

### Asynchronous `getCurrentPosition` callback without stale-check

The `getCurrentPosition` success callback at line 1318 captures no snapshot of the current state. By the time it fires, `gpsSource` may have changed. The callback should check `if (gpsSource !== 'device') return;` before starting `watchPosition`.

### Recommended fix

Two guards are needed:

1. **In the `getCurrentPosition` success callback** (line 1318), add:
   ```javascript
   if (gpsSource !== 'device') return;
   ```

2. **In the `watchPosition` success callback** (line 1321), add:
   ```javascript
   if (gpsSource !== 'device') return;
   ```

The first guard prevents a stale `getCurrentPosition` response from starting a `watchPosition` after the user has already switched back to server mode. The second guard prevents any lingering `watchPosition` callback from feeding device GPS data when the user is in server mode.
