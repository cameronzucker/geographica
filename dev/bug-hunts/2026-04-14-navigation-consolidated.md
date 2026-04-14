# Navigation System Bug Hunt — Consolidated Findings

**Date:** 2026-04-14
**Scope:** Turn-by-turn navigation engine and UI — `frontend/navigation.js` (790 lines), `frontend/nav-ui.js` (882 lines), relevant sections of `frontend/app.js`, `frontend/style.css`
**Hunters:** Exploratory, Holistic, Multipass

---

## Confirmed Bugs

### B1. Off-route counter resets on any single on-route tick (no hysteresis)
**Consensus:** All three hunters identified this
**Location:** `navigation.js:577-588`
**Evidence:** The off-route detector requires 5 *consecutive* ticks where `distanceFromRoute > 50m`, but resets `offRouteCount` to 0 on any single tick within 50m (line 586). With typical GPS noise of ±10-15m, a driver 60m off-route will get occasional favorable jitter that drops below 50m, resetting the counter entirely. The threshold uses the same 50m for both entering and exiting off-route state — no hysteresis band.
**Impact:** Rerouting almost never triggers in practice. Users must manually exit navigation, recalculate, and re-enter. This is the primary root cause of field report #1.
**Blast radius:** `navigation.js` only. Fix is isolated to the off-route detection block.
**Fix approach:** Add hysteresis — use 50m to enter off-route state, 35m to exit. Use a cumulative "3 of last 5" counter instead of requiring consecutive ticks.

### B2. Reroute failure leaves engine permanently stuck in "rerouting" state
**Consensus:** Multipass identified; verified by consolidation
**Location:** `nav-ui.js:471-474`, `navigation.js:557-561`
**Evidence:** When the fetch to `/valhalla/route` fails (network error, Valhalla down), the catch handler logs the error but never resets engine state. The engine remains in `state = "rerouting"` (set at `navigation.js:600`). In `tick()`, when `state === "rerouting"`, the engine just emits updates and returns (line 557-561) — it never re-checks off-route or triggers a new reroute. The comment "engine will retry after cooldown" is incorrect; there is no retry logic. The engine is permanently stuck until the user manually stops and restarts navigation.
**Impact:** On an offline-first mesh network platform where Valhalla may be unreachable, this is especially damaging. Any failed reroute attempt bricks the navigation session.
**Blast radius:** Requires changes in both `nav-ui.js` (error handler) and `navigation.js` (state recovery or timeout). Consider adding a `cancelReroute()` API to the engine.
**Fix approach:** Add a reroute timeout (e.g., 10s) in the engine that reverts state to "navigating" if no `applyReroute` arrives. Add retry logic in the UI's catch handler with exponential backoff (3 retries, then revert to navigating with a "reroute failed" banner).

### B3. GPS feed polls at 500ms but engine expects 1Hz — double-processing and broken stale detection
**Consensus:** All three hunters identified
**Location:** `nav-ui.js:295` (500ms interval), `navigation.js:22` (comment: "consecutive 1 Hz ticks")
**Evidence:** `feedGPS()` runs every 500ms via `setInterval`, polling `window._geographicaGPSData`. The GPS WebSocket updates that global at ~1Hz. This means: (a) the engine processes the same GPS data point twice per real fix, (b) `lastGPSTime` in the engine (set in `updateGPS()` at `navigation.js:725`) is refreshed every 500ms even when GPS data hasn't changed, making `gpsStale` never trigger, and (c) the off-route counter increments at 2Hz not 1Hz, so `OFF_ROUTE_TICKS=5` means 2.5s not the intended 5s.
**Impact:** Compounds B1 (off-route detection), breaks GPS stale detection, and contributes to voice rapid-fire (B4).
**Blast radius:** `nav-ui.js` feed mechanism. Fix may also require adding a GPS data timestamp comparison to detect stale data.
**Fix approach:** Change to event-driven architecture: have the GPS WebSocket push directly to the engine instead of polling a global. Alternatively, compare `data.timestamp` or a hash to skip duplicate data. Update OFF_ROUTE_TICKS comment or adjust the value.

### B4. Voice announcements rapid-fire near turns, roundabouts, and after reroutes
**Consensus:** All three hunters identified
**Location:** `navigation.js:336-368`, `navigation.js:745`
**Evidence:** Three contributing factors:
1. **Snap oscillation:** When GPS is near a maneuver boundary, `currentManeuverIdx` changes on alternate ticks. Since `announcedSet` keys include `nextIdx`, each oscillation creates a fresh key and re-triggers the announcement.
2. **No global cooldown:** The deduplication is per-maneuver-threshold, but there's no minimum inter-announcement gap. Two different maneuver indices can both announce within the same 500ms.
3. **Reroute clears announced set:** `applyReroute()` (line 745) clears `announcedSet = {}`. If the user is already close to a maneuver after rerouting, all three thresholds fire in rapid succession.
**Impact:** Extremely annoying rapid-fire voice during parking lots, roundabouts, and any reroute near a turn. Field report #2.
**Blast radius:** `navigation.js` only. The voice callback interface doesn't change.
**Fix approach:** Add a global minimum inter-announcement cooldown (e.g., 5 seconds). On reroute, don't clear `announcedSet` entirely — instead mark thresholds for maneuvers the user has already passed as consumed. Add a speed gate (don't announce below 2 m/s to suppress parking lot spam).

### B5. GPS position centered on screen — no padding for nav overlay
**Consensus:** All three hunters identified
**Location:** `nav-ui.js:336-342` (all `map.easeTo()` calls during navigation)
**Evidence:** `map.easeTo({ center: [lng, lat], ... })` uses no `padding` option. The GPS dot appears at the geometric center of the viewport. With the nav overlay covering ~120-150px at the top and pitch=60 showing a 3D perspective, only ~40% of the visible map shows the road ahead. Also, the initial `easeTo` at line 166-173 similarly has no padding.
**Impact:** Users can't see upcoming road and turns. Field report #3.
**Blast radius:** `nav-ui.js` only — three `easeTo` calls need padding added. Also need to calculate the actual nav overlay height to set `padding.top` correctly.
**Fix approach:** Add `padding: { top: navOverlayHeight }` to all `map.easeTo()` calls during navigation. The overlay height should be measured dynamically since it varies with content.

### B6. `heading === 0` (due north) treated as falsy
**Consensus:** Multipass and Holistic identified
**Location:** `nav-ui.js:308`
**Evidence:** `var heading = data.heading || data.bearing || 0` — when `data.heading` is exactly 0 (due north), JavaScript treats it as falsy and falls through to `data.bearing`. This means a vehicle heading due north gets assigned whatever `data.bearing` is (which may be stale or wrong).
**Impact:** Incorrect map rotation when traveling due north. Subtle but affects correctness.
**Blast radius:** `nav-ui.js` only, single line fix.
**Fix approach:** Use `data.heading != null ? data.heading : (data.bearing || 0)` or similar explicit null check.

### B7. UI heading validity check disagrees with engine's speed gate
**Consensus:** Exploratory and Holistic identified
**Location:** `nav-ui.js:310` vs `navigation.js:516-522`
**Evidence:** Engine: `headingValid = gpsSpeed >= HEADING_SPEED_GATE` (3 m/s ≈ 6.7 mph). UI: `headingValid = heading !== 0 || speed > 1` (1 m/s ≈ 2.2 mph). At walking pace (1-3 m/s), the UI considers heading valid and rotates the map using noisy GPS heading, while the engine correctly rejects it. Also, the UI's check (`heading !== 0`) has a truthiness bug — a heading of exactly 0 degrees (north) makes this false.
**Impact:** Disorienting map spinning at low speeds (walking, parking lots). Compounds B4 (parking lot voice spam).
**Blast radius:** `nav-ui.js` only. Should use the engine's `headingValid` from the state object instead of re-deriving it.
**Fix approach:** Use `state.headingValid` and `state.heading` from the engine callback instead of independently computing heading validity in `feedGPS()`. The engine already does this correctly.

### B8. Sidebar toggle and search bar overlap nav overlay on mobile
**Consensus:** All three hunters identified
**Location:** `style.css:661` (`#sidebar-toggle` z-index 25), `style.css:1229` (`#nav-overlay` z-index 22)
**Evidence:** The hamburger button has `z-index: 25`, rendering above the nav overlay at `z-index: 22`. Neither the sidebar toggle nor the search container is hidden or repositioned when navigation is active. On mobile, both overlap the instruction panel.
**Impact:** UI elements cover turn-by-turn instructions. Field report #4.
**Blast radius:** CSS and potentially `nav-ui.js` (to add/remove a class on navigation start/stop). `app.js` sidebar logic unchanged.
**Fix approach:** When navigation starts, add a `.nav-active` class to `<body>`. Use CSS to hide `#sidebar-toggle` and reposition `#search-container` below the nav overlay, or hide search entirely during navigation. When navigation stops, remove the class.

### B9. Costing always resolves to 'auto' — wrong voice thresholds for bike/pedestrian
**Consensus:** Holistic identified; verified by consolidation
**Location:** `nav-ui.js:246`
**Evidence:** `(trip.legs[0].summary || {}).costing || 'auto'` reads `leg.summary.costing`, but Valhalla's response format doesn't include a `costing` field in leg summaries. The costing model is set in the request (`app.js:1829`) but not echoed in the response. So this always falls through to `'auto'`.
**Impact:** Bicycle routes get driving-distance thresholds (800/200/50m instead of 400/100/30m) — announcements come too early. Pedestrian routes get even worse thresholds (800/200/50m instead of 200/50/20m). Voice announces turns half a kilometer before they arrive when walking.
**Blast radius:** `nav-ui.js` and `app.js`. Need to propagate the costing model from the route request through `_geographicaLastTrip` to `buildRouteData`.
**Fix approach:** In `app.js`, attach the costing model to the trip object: `data.trip._costing = costing` after line 1850. In `nav-ui.js:246`, read `trip._costing || 'auto'` instead of trying to extract it from the leg summary.

### B10. `buildState` heading ternary is a no-op
**Consensus:** All three hunters identified
**Location:** `navigation.js:491`
**Evidence:** `heading: headingValid ? lastValidHeading : lastValidHeading` — both branches return the same value. Copy-paste error. The false branch should likely return `null` or `0` to indicate heading is unreliable.
**Impact:** Consumers of the state object can't distinguish between valid and invalid heading by checking the `heading` field — they must also check `headingValid`. Currently the UI does check `headingValid` separately (poorly — see B7), so functional impact is limited.
**Blast radius:** `navigation.js` only, single line.
**Fix approach:** Change to `heading: headingValid ? lastValidHeading : null`.

### B11. Multi-leg routes create duplicate coordinates at leg boundaries
**Consensus:** All three hunters identified
**Location:** `nav-ui.js:222-233`
**Evidence:** `allCoords = allCoords.concat(coords)` duplicates the shared waypoint between legs (Valhalla's last point of leg N equals first point of leg N+1). This creates zero-length segments and offsets maneuver shape indices by 1 per leg boundary for all subsequent legs.
**Impact:** Affects multi-destination routes only. Single-destination routes (the common case) are unaffected. Could cause maneuver misalignment, incorrect distance calculations, and snap oscillation near waypoints.
**Blast radius:** `nav-ui.js` only.
**Fix approach:** Skip the first coordinate of each leg after the first: `if (i > 0) coords = coords.slice(1);` before concatenation. Adjust `shapeOffset` accordingly.

### B12. Muted announcements permanently consumed — can't replay on unmute
**Consensus:** Holistic and Multipass identified
**Location:** `nav-ui.js:606-612`, `navigation.js:317-319,341`
**Evidence:** `toggleMute()` changes the local `muted` flag and updates localStorage/icon, but never calls `nav.setMuted()`. The engine's `announce()` function checks its own `muted` flag (which is never updated). However, `announce()` only gates `onVoiceCb` — the `announcedSet` marking at line 341 happens BEFORE the `announce()` call at line 364, so thresholds are consumed regardless of mute state. If the user un-mutes mid-route, missed announcements won't replay.
**Impact:** Minor — users who mute and unmute won't hear announcements for turns they already passed the threshold for. They'll still hear the next threshold hit.
**Blast radius:** Both files. Either sync mute state to engine, or move `announcedSet` marking inside the `announce()` function.
**Fix approach:** Call `nav.setMuted(muted)` in `toggleMute()`. In the engine, skip `announcedSet` marking when muted so thresholds are re-checked on unmute.

### B13. GPS heartbeat timer resets on poll, not on new GPS data
**Consensus:** Exploratory identified as design concern; verified by consolidation
**Location:** `nav-ui.js:325-328`
**Evidence:** The heartbeat timer (`gpsHeartbeatTimer`) is cleared and reset every time `feedGPS()` runs — which is every 500ms. Since `feedGPS` runs on interval regardless of whether GPS data has actually changed, the timer never expires and the "GPS signal delayed" banner from the heartbeat path never shows.
**Impact:** User never sees a GPS-delayed warning from the UI heartbeat mechanism. The engine has its own `gpsStale` check but that's also broken by B3 (lastGPSTime refreshed on every poll).
**Blast radius:** `nav-ui.js`. Fix connects to B3 — adding data freshness checking would fix both.
**Fix approach:** Only reset the heartbeat timer when GPS data has actually changed (compare timestamps or coordinates).

### B14. Dead `lastGPS` check in `start()` — always null after `reset()`
**Consensus:** Multipass identified; verified by consolidation
**Location:** `navigation.js:687,692`
**Evidence:** `start()` calls `reset()` at line 687, which sets `lastGPS = null` at line 665. Then at line 692, `if (lastGPS)` is always false. The initial snap at lines 693-694 never executes. Navigation always starts in "joining" state regardless of GPS position.
**Impact:** Minor — the first `feedGPS()` tick (500ms later) will snap and transition to "navigating" if the user is on-route. But the initial state update at line 707 uses a fallback snap object pointing to `route.coords[0]` which may be far from the user's actual position.
**Blast radius:** `navigation.js` only.
**Fix approach:** Read `window._geographicaGPSData` directly in `start()` before `reset()`, or save/restore `lastGPS` across the reset.

---

## Design Decisions Requiring User Input

### D1. Return-to-north button — custom implementation needed
**Location:** `app.js:158` (`showCompass: false`)
**The concern:** No return-to-north button exists anywhere. The compass was deliberately disabled because MapLibre's `NavigationControl` with `showCompass: true` calls `dragRotate.enable()` internally, re-enabling the CTRL+drag rotation behavior that Pitfall #11 specifically prohibits.
**Why this needs a decision:** A custom north button must be built that resets bearing to 0 WITHOUT re-enabling dragRotate. The question is scope and behavior:
**Options:**
1. **Navigation-only north button:** Add to nav overlay, only visible during navigation. Resets bearing to 0 momentarily, then resumes heading-following after 10 seconds (like recenter button behavior). Simplest, addresses the field report directly.
2. **Global north button:** Always visible on the map (like Google Maps compass). Uses `map.easeTo({ bearing: 0 })` without touching dragRotate. Works in and out of navigation mode. More useful but slightly more UI to maintain.
3. **Both:** Navigation mode gets option 1; non-navigation mode gets option 2 as a persistent compass icon.
**Recommendation:** Option 2 (global) — a single always-visible compass button that calls `map.easeTo({ bearing: 0 })`. During navigation, it also temporarily pauses heading-following (like manual pan does). This is simpler than maintaining two separate buttons and covers both use cases.

---

## False Positives

### FP1. Dead code variable `d` in `remainingDistance`
**Flagged by:** Multipass
**Why invalid:** `navigation.js:176` declares `var d = segmentDistances[segIndex] * (1 - t)` which appears unused. However, looking at the full function (lines 174-180), the computation was refactored to use `total - atPoint` but `d` was left behind. This IS dead code but it's not a bug — it has no functional impact. Including it here rather than as a confirmed bug because it's a code cleanup item, not a correctness issue. The hunters that found it classified it correctly as minor.

---

## Bugs Outside Primary Scope

None identified — all findings are within the scoped navigation files.

---

## Test Gap Analysis

### B1. Off-route counter reset (no hysteresis)
**Why missed:** No tests exist for the navigation engine. The entire `navigation.js` is untested — no test files reference it. The engine is a browser-side IIFE with no module exports, making it difficult to test outside a browser environment.
**Pitfall coverage:** New pattern — "browser-only IIFE code with no test harness"
**Catch test:** Feed a sequence of GPS positions where positions alternate between 45m and 55m from the route. Assert that reroute is triggered within a reasonable time despite the oscillation. Test with realistic GPS noise patterns.

### B2. Reroute failure leaves engine stuck
**Why missed:** No tests. Would require mocking fetch and simulating network failures.
**Pitfall coverage:** New pitfall — "unrecoverable async state: when an async operation fails, the state machine must have a recovery path"
**Catch test:** Start navigation, trigger off-route, mock fetch to reject, assert engine recovers to "navigating" state within timeout period.

### B3. GPS feed 500ms vs engine 1Hz
**Why missed:** No tests. This is an integration issue between nav-ui.js and navigation.js that would only surface in real-world GPS conditions.
**Pitfall coverage:** One-off — specific to the polling architecture
**Catch test:** Feed identical GPS data twice in succession. Assert that the engine processes it only once (no state changes, no counter increments).

### B4. Voice rapid-fire
**Why missed:** No tests. Would require simulating GPS positions near maneuver boundaries over time.
**Pitfall coverage:** One-off — specific to the deduplication key design
**Catch test:** Feed GPS positions that cause `currentManeuverIdx` to oscillate between N and N+1 over 10 ticks. Assert that the same announcement plays at most once per threshold. Assert minimum 5s between announcements.

### B5. GPS centered (no padding)
**Why missed:** Visual/layout issue — would require Playwright or similar visual testing.
**Pitfall coverage:** Not applicable
**Catch test:** Playwright test: start navigation, verify GPS dot is in the bottom third of the viewport.

### B6. heading === 0 falsy
**Why missed:** No tests. Classic JS truthiness bug.
**Pitfall coverage:** New pitfall — "JS truthiness for numeric zero: `0 || fallback` skips zero. Use `!= null` for nullable numbers."
**Catch test:** Call feedGPS with `heading: 0, speed: 10`. Assert that `heading` value used is 0, not bearing fallback.

### B7. UI/engine heading validity mismatch
**Why missed:** No tests. The dual heading validity check is spread across two files with no shared test.
**Pitfall coverage:** New pitfall — "duplicated logic across modules: when two modules independently compute the same derived value, they will drift"
**Catch test:** Feed GPS at speed 2 m/s with heading 90. Assert UI uses engine's `headingValid: false`, not its own `speed > 1` check.

### B9. Costing always 'auto'
**Why missed:** No tests. Would require a real or mocked Valhalla response to verify the costing propagation path.
**Pitfall coverage:** One-off — specific to Valhalla response format
**Catch test:** Build route data from a mock trip with pedestrian costing. Assert `routeData.costing === 'pedestrian'`.

### Testing Pitfalls Updates
- Added: "Unrecoverable async state" (generalizable)
- Added: "JS truthiness for numeric zero" (generalizable)
- Added: "Duplicated logic across modules" (generalizable)
- Not added: Browser-only IIFE testing (architectural, not a pitfall)
