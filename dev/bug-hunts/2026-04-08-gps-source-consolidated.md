# GPS Source Switching Bug Hunt — Consolidated Findings

**Date:** 2026-04-08
**Scope:** GPS source toggle (server vs device) — position oscillation when switching to device GPS
**Hunters:** Exploratory, Holistic, Multipass

---

## Confirmed Bugs

### B1. WebSocket onclose triggers reconnect even when user switched to device GPS
**Consensus:** All three hunters (critical, unanimous) — this is the direct cause of the oscillation
**Location:** `frontend/app.js:1383-1386` and `1395-1399`
**Evidence:** `switchGPSSource('device')` closes the WebSocket at line 1307. The `onclose` handler at line 1386 unconditionally calls `scheduleGPSReconnect()`. After 5 seconds, `connectGPS()` at line 1357 creates a new WebSocket with NO guard on `gpsSource`. The new WebSocket's `onmessage` at line 1377 calls `updateGPSPosition()` — now both device `watchPosition` and server WebSocket feed the same function.
**Impact:** Map marker oscillates between device position and Pi position at ~1 Hz. Navigation engine reads corrupted position data, potentially triggering false reroutes.
**Blast radius:** `frontend/app.js` GPS section only.
**Fix approach:** Guard `scheduleGPSReconnect()` and `connectGPS()` with `if (gpsSource !== 'server') return;`. Store the reconnect timer ID so it can be cancelled on source switch.

### B2. Reconnect timer is fire-and-forget — cannot be cancelled
**Consensus:** All three hunters (significant, unanimous)
**Location:** `frontend/app.js:1395-1400`
**Evidence:** `setTimeout` return value at line 1396 is discarded. No `clearTimeout` anywhere in the file. Switching sources cannot cancel pending reconnect timers. Multiple timers can stack up from rapid toggling or flaky connections.
**Impact:** Amplifies B1 — even adding a guard in `connectGPS()` would be defeated by already-scheduled timers. Multiple stacked timers can create multiple parallel WebSocket connections.
**Blast radius:** Same file.
**Fix approach:** Store timer ID in a module-level `gpsReconnectTimer` variable. Clear it in `switchGPSSource()` and at the start of `connectGPS()`.

### B3. watchPosition starts before getCurrentPosition permission is resolved
**Consensus:** All three hunters (significant, unanimous)
**Location:** `frontend/app.js:1310-1324`
**Evidence:** `getCurrentPosition()` at line 1310 is async (waits for user permission prompt). `watchPosition()` at line 1324 executes immediately without waiting for the callback. If the user denies permission, the error callback at line 1312 reverts `gpsSource` to `'server'` and calls `connectGPS()`, but never calls `clearWatch(deviceWatchId)`.
**Impact:** Orphaned `watchPosition` continues firing error callbacks alongside the reconnected server GPS. The `setGPSStale(true)` call in the watch error handler causes stale indicator flickering.
**Blast radius:** Same file.
**Fix approach:** Move `watchPosition()` inside the `getCurrentPosition()` success callback. Add `clearWatch(deviceWatchId)` in the error callback.

### B4. WebSocket onmessage has no source guard
**Consensus:** Holistic and Multipass found explicitly. Exploratory implied.
**Location:** `frontend/app.js:1374-1380`
**Evidence:** Neither the `onmessage` handler nor `updateGPSPosition()` checks `gpsSource`. Any live WebSocket feeds directly into the position pipeline regardless of the user's selection.
**Impact:** Defense-in-depth gap. Makes B1 trivially exploitable and hard to debug — even if B1 is fixed, any future code that opens a WebSocket would bypass the source toggle.
**Blast radius:** Same file.
**Fix approach:** Add `if (gpsSource !== 'server') return;` at the top of the `onmessage` handler.

### B5. connectGPS() doesn't close existing WebSocket before opening new one
**Consensus:** Exploratory and Multipass found. Holistic implied.
**Location:** `frontend/app.js:1357-1367`
**Evidence:** `connectGPS()` overwrites `gpsWs` with a new WebSocket without closing the old one. The old WebSocket's `onmessage` still fires and its eventual `onclose` triggers another reconnect cascade.
**Impact:** Under flaky connections or rapid source toggling, multiple parallel WebSocket connections accumulate. Each fires `updateGPSPosition()` and each `onclose` triggers another reconnect timer.
**Blast radius:** Same file.
**Fix approach:** Add `if (gpsWs) { gpsWs.close(); gpsWs = null; }` at the start of `connectGPS()`.

---

## Design Decisions Requiring User Input

None — all fixes are straightforward correctness bugs with one right answer.

---

## False Positives

### FP1. Brief stale flash on intentional WebSocket close
**Flagged by:** Exploratory
**Why invalid:** When switching to device GPS, the WebSocket `onclose` at line 1385 sets stale=true briefly before the first device position arrives. This is technically correct (GPS IS momentarily stale during the handoff) and will be eliminated by the B1 fix (onclose won't trigger reconnect, and the source guard in onmessage prevents the stale from being set when in device mode after the fix). Not a separate issue.

---

## Bugs Outside Primary Scope

None — all findings are within the GPS source switching code in `frontend/app.js`.

---

## Test Gap Analysis

### B1. WebSocket onclose triggers reconnect in device mode
**Why missed:** No automated tests for the frontend GPS code. The interaction between async WebSocket lifecycle events and source toggle state is difficult to test without mocking both the WebSocket and Geolocation APIs.
**Catch test:** A browser-based test (or mock-based unit test) that: sets `gpsSource = 'device'`, closes the WebSocket, waits 6 seconds, and asserts no new WebSocket connection was created.

### B2. Reconnect timer not cancellable
**Why missed:** No tests. The fire-and-forget pattern is invisible without inspecting timer state.
**Catch test:** Call `switchGPSSource('device')` and assert the reconnect timer was cleared.

### B3. watchPosition/getCurrentPosition race
**Why missed:** No tests. Requires mocking `navigator.geolocation` with async permission delay.
**Catch test:** Mock `getCurrentPosition` to call error callback, assert `deviceWatchId` is null after.

### B4. No source guard in onmessage
**Why missed:** No tests.
**Catch test:** Set `gpsSource = 'device'`, fire a WebSocket message event, assert `updateGPSPosition` was NOT called.

### B5. connectGPS doesn't close existing WebSocket
**Why missed:** No tests.
**Catch test:** Call `connectGPS()` twice, assert the first WebSocket's `close()` was called.

### Testing Pitfalls Updates
- None (no `dev/testing-pitfalls.md` exists yet)
