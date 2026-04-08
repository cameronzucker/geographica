# Bug Hunt Report — GPS Source Switching v2, Server-Mode Oscillation

## Scope

**Files analyzed:**
- `frontend/app.js` — GPS section (lines 1267-1566), globals (lines 40-57)
- `frontend/navigation.js` — full file (790 lines)
- `frontend/nav-ui.js` — full file (882 lines)
- `services/gps/main.py` — full file (220 lines)

**All five passes performed.** Findings below.

---

## Bugs

### 1. getCurrentPosition success callback does not check gpsSource before starting watchPosition — stale async callback starts device GPS after user switched to server

**Location:** `frontend/app.js:1317-1339`
**Severity:** critical
**Found in:** Pass 4 — Concurrency

**Evidence:**

The `switchGPSSource('device')` function calls `navigator.geolocation.getCurrentPosition()` asynchronously (line 1317). The success callback at line 1318 unconditionally starts `watchPosition` and stores the ID in `deviceWatchId`:

```javascript
navigator.geolocation.getCurrentPosition(
  function () {
    // Permission granted — start continuous watch
    deviceWatchId = navigator.geolocation.watchPosition(
      function (pos) {
        var data = { ... };
        updateGPSPosition(data);   // <-- NO gpsSource check
      },
      ...
    );
  },
  ...
);
```

The success callback never checks whether `gpsSource` is still `'device'` at the time it fires.

**Race sequence:**

1. User switches to "device". `gpsSource = 'device'`. WebSocket closed. `getCurrentPosition` queued.
2. User switches back to "server" before the callback fires. `gpsSource = 'server'`. Code runs `clearWatch(deviceWatchId)` — but `deviceWatchId` is still `null` (watchPosition hasn't started yet), so `clearWatch(null)` is a no-op.
3. The `getCurrentPosition` success callback fires (permission was already granted on HTTPS/Tailscale — no prompt, near-instant callback). It unconditionally calls `watchPosition`. `deviceWatchId` is now set to a valid ID.
4. Device GPS positions flow through `updateGPSPosition()` unchecked.
5. Meanwhile, the server WebSocket also sends positions through `updateGPSPosition()` (gpsSource is 'server', so the onmessage guard passes).
6. The map marker oscillates between the device's GPS location and the Pi's GPS location.
7. Nobody ever calls `clearWatch` on this orphaned watch — `deviceWatchId` holds the ID, but the next switch-to-server will clear it *if* the user toggles again. Until then, it runs forever.

**Impact:** This is the exact regression reported. On a remote device accessing via HTTPS (Tailscale), `navigator.geolocation` is available and permission may already be granted. Selecting "server GPS" after briefly touching "device GPS" (or even after the page previously used device mode) causes the position to oscillate between the device's own GPS and the Pi's server-broadcast GPS. The oscillation is visible as the map marker jumping between two geographic locations.

---

### 2. watchPosition success callback does not guard on gpsSource — device positions unconditionally flow through updateGPSPosition

**Location:** `frontend/app.js:1321-1333`
**Severity:** significant
**Found in:** Pass 1 — Contract violations

**Evidence:**

The `watchPosition` success callback at line 1321 calls `updateGPSPosition(data)` with no check on `gpsSource`:

```javascript
deviceWatchId = navigator.geolocation.watchPosition(
  function (pos) {
    var data = { ... };
    updateGPSPosition(data);   // Always fires, regardless of gpsSource
  },
  ...
);
```

Compare with the server WebSocket `onmessage` handler at line 1397, which correctly guards:

```javascript
gpsWs.onmessage = function (event) {
  if (gpsSource !== 'server') return;   // <-- guard present
  ...
};
```

The device callback has no equivalent guard `if (gpsSource !== 'device') return;`.

This is a defense-in-depth failure. Even if Bug #1 is fixed (by checking gpsSource before starting watchPosition), the watchPosition callback itself should independently verify that device mode is still active. Without this guard, any scenario that leaves a watchPosition active while in server mode will cause oscillation.

**Impact:** Amplifies Bug #1. Also means any future code path that accidentally leaves a watchPosition running will immediately cause oscillation, with no safety net.

---

### 3. getCurrentPosition error callback tries to clearWatch a deviceWatchId that was never set

**Location:** `frontend/app.js:1347-1349`
**Severity:** minor
**Found in:** Pass 3 — Failure mode reasoning

**Evidence:**

The error callback at line 1341 contains:

```javascript
function (err) {
  ...
  // Clean up any watch that might have started
  if (deviceWatchId !== null) {
    navigator.geolocation.clearWatch(deviceWatchId);
    deviceWatchId = null;
  }
  ...
}
```

The comment says "clean up any watch that might have started," but in the current code structure, `watchPosition` is only called inside the *success* callback. If `getCurrentPosition` fails (error callback), the success callback never ran, so `deviceWatchId` is always `null` at this point. The clearWatch here is dead code.

This is not harmful today, but it reveals confusion about the async flow and suggests the original author was uncertain about the timing. It could mask real issues during debugging ("I have cleanup code, why isn't it working?").

**Impact:** Dead code that obscures reasoning about the async flow. No runtime effect.

---

## Design Concerns

### No mutual exclusion primitive between GPS sources

The `gpsSource` variable is a simple string flag checked at various points in async callbacks. There is no single gate or lock that guarantees "only one source feeds updateGPSPosition at a time." The server side has a guard in `onmessage` (line 1397), but the device side has no equivalent guard in the `watchPosition` callback (line 1321). The two guards are structurally asymmetric — one is in the receiver, the other is missing. A consistent pattern would be to either:
- Guard both callbacks (belt), AND
- Ensure cleanup before starting the other source (suspenders)

Currently, only the server callback has a guard, and only the device path has cleanup-on-switch.

### Async callback outlives the intent that launched it

The `getCurrentPosition` call at line 1317 is a fire-and-forget async operation with no cancellation mechanism. The Geolocation API provides no way to cancel a pending `getCurrentPosition`. This means the only safe pattern is to check, inside the callback, whether the original intent is still valid (i.e., `gpsSource === 'device'`). This check is missing.

### watchPosition callback closures capture no state about which "session" started them

If multiple rapid toggles occur, each toggle to 'device' fires a new `getCurrentPosition`, each of whose success callbacks will assign a new `watchPosition` ID to the same `deviceWatchId` variable. The previous watch's ID is overwritten and leaked (never cleared). A session counter or generation ID would catch stale callbacks.
