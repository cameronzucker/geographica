# Nav UX Beta Bug Hunt — Multi-Pass

**Date:** 2026-04-21
**Scope:** `frontend/navigation.js`, `frontend/nav-ui.js`, `frontend/style.css` (nav sections), `frontend/app.js` (read-only: compass, route source, renderRoute/clearRoute), `frontend/index.html` (nav markup).
**Method:** Five focused passes (contract violations, cross-sibling patterns, failure modes, concurrency, error propagation) per `code-bug-hunter-multipass` skill.
**Reported bugs investigated:**
1. Voice announces 3× per turn; first announcement too far; last two redundant.
2. Route polyline doesn't update on the map after live reroute.
3. GPS marker not at bottom 1/3 of visible area during nav.
4. Recenter button overlaps compass on mobile; recenter should be above compass.

Prior fix commits that failed to resolve these (`1761508`, `018adcf`, `8b37aae`, `da0b0a0`) are treated as "attempted fix didn't close the root cause" — we re-examine with fresh eyes.

---

## Pass 1 — Contract Violations

### P1-1 [CRITICAL → Bug #2] `applyReroute` never notifies the UI to redraw the route polyline
**Location:** `frontend/navigation.js:791-818` (engine `applyReroute`), `frontend/nav-ui.js:500-516` (UI fetch), `frontend/app.js:2139-2142` (map `route` source).

**Contract:** UI sets up a `route` GeoJSON map source in `app.js` and calls `source.setData(...)` when a fresh trip comes in from `renderRoute()`. After a reroute, the engine swaps its internal route to new coords, but the `route` map source is NOT updated — only the engine state changes.

**Evidence:** `attemptReroute` (nav-ui.js:507-515) calls `buildRouteData(data.trip)` then `nav.applyReroute(newRouteData, seq)` and `hideBanner()`. It never calls anything equivalent to `map.getSource('route').setData(...)` with the new geometry. `window._geographicaLastTrip` is also not updated, so the on-disk reference (and future exports) is stale.

**Impact:** After a reroute, the vehicle visually drives off the old (stale) blue polyline toward a new path computed by the engine. Because the engine snaps the vehicle to the new coords, the map marker detaches from the drawn line — users see the car "driving off the route," which matches the reported bug.

**Fix approach:** After `nav.applyReroute(newRouteData, seq)` succeeds, update the map source:
```js
var src = map.getSource('route');
if (src) src.setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: newRouteData.coords } });
window._geographicaLastTrip = data.trip;
window._geographicaLastTrip._costing = info.costing;
```

---

### P1-2 [CRITICAL → Bug #1] `VOICE_COOLDOWN=5000ms` lets all three thresholds (800m, 200m, 50m) fire back-to-back
**Location:** `frontend/navigation.js:327-335` (`announce`), `362-390` (`checkVoice` loop), `42-49` (constants).

**Contract:** `VOICE_THRESHOLDS.auto = [800, 200, 50]` is meant to produce three spoken alerts per turn: "in half a mile, turn..." (800), "in 200m, turn..." (200), "turn here" (50). The cooldown (5000 ms) is supposed to space them out. But `checkVoice` iterates the thresholds in a SINGLE tick: the `for (var ti = 0; ti < thresholds.length; ti++)` loop runs every GPS tick.

**Evidence:** Inside the loop (navigation.js:362), every unannounced key in the same tick calls `announce`. `announce` enforces cooldown (line 330), so only the FIRST announcement in a tick wins — but the loop `break`s only when `announce` returns false. This means:
- In the first tick where `dist <= 800`, threshold 0 fires. Cooldown sets `lastAnnouncementTime = now`. Threshold 1 checks `now - lastAnnouncementTime < 5000` → TRUE → return false → `break`. OK so far.
- But on the NEXT tick (500 ms later), threshold 0 is already `announcedSet[key]` so it's skipped; threshold 1's cooldown is still 500 ms elapsed → blocked; break.
- Ten ticks later (5000 ms elapsed), if user is still >= 200m away, threshold 1 fires normally with the same "far" alert text.

**Real problem surfaces when the driver closes distance fast.** In city driving at 45 mph (~20 m/s), the driver traverses 800m → 200m → 50m in ~37 seconds. But consider an approach where the user *is already* inside the 200m ring when they first enter the maneuver (e.g., the just-started route has a 150m first turn). Then on first tick:
- `dist=150`, threshold 0 (800m) passes → `far` text announced; cooldown starts.
- 5000 ms later, `dist ≈ 50` → threshold 1 (200m) passes → `medium` text announced. But `dist` has already crossed into threshold 2 territory. Because threshold 1's `announcedSet[nextIdx + "-" + 1]` key was the gate, it announces `verbal_transition_alert_instruction` (far/medium text).
- Another ~2.5 seconds later user hits `dist < 50`, `announcedSet["-2"]` still empty → announces `verbal_pre_transition_instruction` ("turn now").

Result: THREE announcements for one turn in rapid succession — exactly the reported symptom. Worse: texts 1 and 2 are the same `verbal_transition_alert_instruction` (redundant), and text 3 is the near instruction.

Also: **threshold 0 fires "too far" because 800m means ~half a mile when driving fast and the driver has not yet mentally tracked the upcoming turn.** The `auto` thresholds were chosen for highway but fire on city streets too.

**Fix approach:**
1. After any announcement at threshold ti, mark all thresholds ti..N-1 as announced for that maneuver. Drop "too-far" announcement if we already passed the threshold (suppress threshold 0 if distance < 400).
2. Or: only fire threshold 0 if the user entered from outside the ring (require distance crossed 800m FROM > 800m, not "is within 800"). Same for threshold 1.
3. Tune thresholds to [400, 150, 30] for `auto` in-city, or make them costing+speed adaptive.

**Secondary (P1-2b):** `checkVoice` `break` on cooldown refusal means we break out of the loop entirely, but we KEEP looping across ALL still-unannounced keys in the next tick — so the moment cooldown clears, the very next tick will announce the NEXT threshold regardless of how much distance changed. This is why all three fire in a tight sequence.

---

### P1-3 [SIGNIFICANT → Bug #3] `getNavPadding` returns `{ top }` only — MapLibre `easeTo(padding)` uses `top` as TOP padding, not center-shift
**Location:** `frontend/nav-ui.js:768-775` (`getNavPadding`), `183-190` / `372-379` (applied via `easeTo`).

**Contract:** User wants GPS marker at bottom 1/3 of visible area during nav. MapLibre padding moves the map's logical center to the centroid of the padded region. With only `top` padding (say overlay = 180px tall, padding top = 200), MapLibre will shift the map center DOWN by `top/2 = 100px`. The GPS dot (at map center) lands at `(screenHeight / 2) + 100`.

On a 900px-tall phone, that's 550px from top → ~61% down. The user expects ~66% (bottom 1/3 = 66% from top).

**Evidence:** `getNavPadding` returns `{ top: lastNavPaddingTop }` only. MapLibre padding semantics: the camera positions its point-of-interest (the target center) at the centroid of `(viewport - padding on all sides)`. Since `bottom/left/right` default to 0, the centroid is shifted DOWN by `top/2`, not `top`. To shift the dot all the way to bottom-1/3, the padding should be **asymmetric with a negative or much larger top value** — or, more correctly, you set `top = overlay_height` AND `bottom = 0` while adjusting camera center.

Concrete math:
- Viewport height = 900. Overlay height = 180. Padding `{ top: 200 }`.
- Padded box: top=200, bottom=0 → height 700.
- Padded box centroid y = 200 + 700/2 = 550.
- GPS dot sits at centroid = y=550 from top of viewport = **61%** down.

To put it at 66% (bottom 1/3): centroid y = 600. That requires `top - bottom = 300`. If `bottom=0`, `top=300`. Currently `top = overlay + 20 ≈ 200`.

**Fix approach:** Change `getNavPadding` to compute padding such that `center = viewport*2/3`. Given viewport height H and overlay height O:
- We want centroid = 2H/3.
- Centroid = top + (H - top - bottom)/2.
- Let bottom = 0 (or small), solve: top = (4H/3) - H = H/3? No, algebra: top + (H - top)/2 = 2H/3 → top/2 + H/2 = 2H/3 → top = H/3.

So `top = window.innerHeight / 3` (not overlay height). The overlay only needs to not cover the dot. Overlay is ~180px, and on a 900px phone H/3 ≈ 300px, which is below the overlay — good.

Current code only accounts for "don't put the dot under the overlay" (top = overlay + 20), not "put the dot at bottom 1/3." These are different constraints.

---

### P1-4 [MINOR] `getNavPadding` returns `{}` when overlay hidden — callers still pass `{}` as padding
**Location:** `frontend/nav-ui.js:768-775`.

**Evidence:** When `overlay.classList.contains('hidden')`, returns `{}`. `map.easeTo({ padding: {} })` replaces previous padding with `{top:0,right:0,bottom:0,left:0}` — so during initial `startNavigation` easeTo (line 183), if overlay has not yet rendered (still `hidden` one microtask earlier at line 169 OR on very slow first-paint), padding is zero and GPS dot jumps to middle. Users will see a "snap up" after the overlay appears.

**Impact:** Minor visual glitch on first nav entry; the subsequent `feedGPS` tick corrects it 500 ms later.

**Fix approach:** At `startNavigation`, unhide overlay BEFORE easeTo, or read overlay height via `getBoundingClientRect()` before it's in the DOM layout.

---

### P1-5 [SIGNIFICANT] `nav.stop()` never unregisters `onUpdate/onReroute/onArrival/onVoice` callbacks
**Location:** `frontend/navigation.js:769-771` (`stop` → `reset`), `701-725` (`reset`).

**Contract:** `stop` should leave the engine in a clean state. But `reset` explicitly clears state variables EXCEPT the four callbacks: `onUpdateCb`, `onRerouteCb`, `onArrivalCb`, `onVoiceCb` survive. Meanwhile the UI sets `nav = null` at nav-ui.js:197 but can't clear the engine's callback slots because the engine exposes no setter for `null`.

**Evidence:** `reset()` resets everything except the four callbacks. `start` calls `reset()` first, so subsequent navigation sessions STILL have the old callbacks from the previous session wired. Because the engine is a module singleton (`window.GeographicaNav`), after `stopNavigation` the old `onUpdateCb` closure references still fire any late events emitted from `setInterval` callbacks — but `startStaleChecker` is stopped in `reset`, so this is only a concern if a NEW stale checker is started. Actually looking again: a late `tick` could still be in flight if `updateGPS` was called just before stop (though updateGPS is synchronous, so this is unlikely).

**Real risk:** In `startNavigation`, the user calls `nav.onUpdate(onNavUpdate)`. This closure captures local references to `overlay`, `lastNavState`, etc. — but those are module-scoped in the IIFE, so they persist across sessions. So re-registration just overwrites `onUpdateCb`. Not a bug per se — but if there were ANY bug where engine emits after stop, the old callback would run and toggle DOM in a stopped nav state.

A specific leak: `stopNavigation` does NOT call `nav.setMuted(false)` to sync. If `muted = true` persists in the engine across sessions, next session inherits mute state from BEFORE `toggleMute` was set. Actually `startNavigation` never syncs mute to the engine — the engine `muted` starts `false`, but the UI `muted` loads from localStorage. If user had muted previously (UI muted=true from localStorage), but engine muted=false because `reset` doesn't touch muted either … actually `reset` doesn't reset `muted`. So engine `muted` stays whatever it was last set to. If first run sets UI muted=true via load, but UI never calls `nav.setMuted(true)` at session start, engine thinks it's unmuted and calls `onVoice`, but then UI's `onVoice` short-circuits on `if (muted)` at line 457. OK — double gate, no audible bug.

**Impact:** Minor — defense in depth. Not root-cause of any listed bug.

---

### P1-6 [SIGNIFICANT] `setMuted` only affects engine's internal `announce` gate — UI still runs `onVoice` through its own gate
**Location:** `frontend/navigation.js:821-823`, `frontend/nav-ui.js:456-463`, `667-674`.

**Evidence:** There are TWO mute flags — engine `muted` (nav.js:155) and UI `muted` (nav-ui.js:18). `toggleMute` (nav-ui.js:667-674) updates BOTH via `nav.setMuted(muted)`. But `announce` in the engine short-circuits when `muted` is true — meaning `onVoiceCb` is not even called. So the UI's `muted` check in `onVoice` at line 457 is redundant but not harmful.

**Real issue:** `startNavigation` (nav-ui.js:141-193) loads `muted = localStorage.getItem(...)` at INIT but never calls `nav.setMuted(muted)` before `nav.start(routeData)`. So if the user was muted, the engine starts unmuted. First announcement fires in engine → `announce` returns true → `onVoiceCb` called → UI's `onVoice` checks `muted` → suppressed. **Cooldown is consumed in the engine for an announcement the user never heard.**

Now the user's actually-first-heard announcement (after unmute) is delayed by a full 5000 ms cooldown because a phantom announcement burned the cooldown.

**Fix approach:** In `startNavigation` before `nav.start(routeData)`, call `nav.setMuted(muted)`.

---

### P1-7 [MINOR] `applyReroute` clears `speedHistory` — historical speed ratio lost mid-trip
**Location:** `frontend/navigation.js:810`.

**Evidence:** After reroute, `speedHistory = []`. On the next `buildState`, `speedRatio()` returns 1.0 (default) until ≥5 new samples accumulate. This makes ETA momentarily revert to theoretical-speed estimate. Not wrong, but sudden ETA jumps.

**Impact:** Cosmetic ETA jitter after reroute.

---

### P1-8 [SIGNIFICANT] `applyReroute` preserves `announcedSet` for indices `<= currentManeuverIdx` — but maneuver INDICES in the new route don't correspond to the old route's indices
**Location:** `frontend/navigation.js:802-809`.

**Evidence:** The code tries to clear only "forward" maneuvers:
```js
for (var key in announcedSet) {
  var idx = parseInt(key.split('-')[0]);
  if (idx <= currentManeuverIdx) newSet[key] = true;
}
```
But after a reroute, `currentManeuverIdx` is reset to 0 (line 798). So the check `idx <= 0` keeps ONLY key "0-*" (maneuver 0 announced thresholds). Every other announcement key is discarded — this is probably desired behavior post-reroute (re-announce everything). But the NEW route's maneuver 0 is "start here" (depart), which wasn't announced in the old route as maneuver 0 either — we just happen to keep stale "0-0", "0-1", "0-2" marks that might silence legitimate first-maneuver announcements.

**Impact:** Edge case — if the old route had announced maneuver 0's thresholds and the new route's maneuver 0 is a depart/start, there's no alert to suppress. Mostly harmless. But the semantics are muddled: "preserve past announcements" is meaningless when indices are reset.

**Fix approach:** Just clear `announcedSet = {}` after reroute. The dedup by distance-threshold will naturally re-announce only upcoming maneuvers.

---

### P1-9 [SIGNIFICANT → Bug #4] `z-index` for `#nav-recenter-btn` and `#compass-north-btn` are both 10 — but ordering + bottom positions conflict
**Location:** `style.css:1436-1439` (`#nav-recenter-btn { bottom: 120px; right: 12px; }`), `1673-1688` (`#compass-north-btn { bottom: 160px` desktop, `140px` mobile).

**Evidence:** Computed positions on mobile (≤480px):
- `#nav-recenter-btn`: bottom 120, right 12, width 36px, height 36px → occupies y=(viewportH-156) to (viewportH-120)
- `#compass-north-btn`: bottom 140 (mobile), right 12, width 36px, height 36px → occupies y=(viewportH-176) to (viewportH-140)

Vertical gap: recenter top is (H-156), compass bottom is (H-140). Gap = (H-140) - (H-156) = 16px. They do NOT overlap pixel-wise on mobile — they're 16px apart. BUT this is TIGHT and on 480-768px range, compass is at 160px, gap = 4px. 

Wait — between 481 and 768 (media query ≤480 excludes these), compass bottom=160px, recenter bottom=120px. Gap = 160 - (120+36) = 4px. Basically touching.

On exactly ≤480px: compass=140, recenter=120. Recenter TOP = 120+36 = 156. Compass BOTTOM = 140. Compass is at y-range [H-176, H-140]. Recenter at [H-156, H-120]. Overlap = [H-156, H-140] = 16px of OVERLAP (compass-bottom > recenter-top means they DO overlap).

Let me recompute carefully:
- `bottom: 120px, height: 36px` → button spans vertically from `bottom=120` to `bottom=120+36 = 156`.
- `bottom: 140px, height: 36px` → button spans from `bottom=140` to `bottom=140+36 = 176`.
- In CSS, `bottom` is distance from viewport bottom to button's bottom edge. So recenter occupies `bottom ∈ [120, 156]`, compass occupies `bottom ∈ [140, 176]`.
- Overlap region: `bottom ∈ [140, 156]` → **16px of vertical overlap** on mobile ≤480px. That's the reported bug.

Additionally the user said "recenter should be semantically above compass." Currently recenter (bottom 120) is BELOW compass (bottom 140/160). To put recenter ABOVE compass: recenter bottom = 180, compass bottom = 120 (swap). Or stack: compass 120, recenter 170.

**Fix approach:** Swap positions so recenter is above compass. `#compass-north-btn { bottom: 120px }` (mobile) / 120px (desktop), `#nav-recenter-btn { bottom: 170px }` (both). Provides stacking order + clears zoom controls.

Also `#center-gps-btn` is at `bottom: 70px, left: 12px` — different side, no conflict. Scale bar (maplibre ctrl-bottom-right) is at `bottom: 26px !important` on mobile — must clear that.

---

### P1-10 [SIGNIFICANT] `stopNavigation` leaves `lastRouteTrip` / `_geographicaLastTrip` stale after reroute
**Location:** `frontend/nav-ui.js:195-231` (`stopNavigation`).

**Evidence:** After `stopNavigation`, `window._geographicaLastTrip` still points to the ORIGINAL trip (not the rerouted one — because rerouted trip was never saved, per P1-1). If the user presses "Start Nav" again after stop, they start on the original route, which they may have physically deviated from.

**Impact:** Compounds bug #2 if user stops after a reroute and restarts.

**Fix approach:** When reroute applies successfully, update `_geographicaLastTrip` and also call `renderRoute` or its subset to redraw.

---

### P1-11 [CRITICAL] No preservation of `remainingWaypoints` — reroutes use `[]` always
**Location:** `frontend/nav-ui.js:274-275` (buildRouteData returns `remainingWaypoints: []`).

**Evidence:** `buildRouteData` hardcodes `remainingWaypoints: []`. The reroute callback at navigation.js:652 sends `route.remainingWaypoints || []` to UI. So multi-stop trips that reroute LOSE all remaining waypoints — the reroute goes directly from current-GPS to final destination, skipping intermediate stops.

**Impact:** Multi-stop navigation broken on reroute.

**Fix approach:** Populate `remainingWaypoints` from `trip.locations` (skip first = origin, and maintain index). After each maneuver completion, or on reroute, compute which waypoints are still ahead based on snap position.

---

## Pass 2 — Cross-Sibling Pattern Violations

### P2-1 [SIGNIFICANT → Bug #3] `restoreMapState` does NOT apply `getNavPadding`, inconsistent with `startNavigation` / `feedGPS`
**Location:** `frontend/nav-ui.js:549-559` vs `183-190` and `372-379`.

**Evidence:** Both of the nav `easeTo` calls pass `padding: getNavPadding()`. `restoreMapState` passes zero padding implicitly by omission — but that's fine because nav has just ended, overlay has been hidden, and we're returning to pre-nav camera. HOWEVER MapLibre retains the last padding value unless explicitly cleared. If prior `easeTo` set `padding: { top: 200 }`, the next call WITHOUT `padding` inherits it. So `restoreMapState` silently moves the camera to the saved center but still offsets by the stale nav padding. User sees the map "drift" by the nav-padding amount upon nav exit.

**Fix approach:** `restoreMapState` should pass `padding: { top: 0, right: 0, bottom: 0, left: 0 }` explicitly.

---

### P2-2 [SIGNIFICANT → Bug #4] Compass button created via `createElement` in app.js; recenter button is static HTML in index.html. Both use `.map-btn` class, but positioning is scattered across two files
**Location:** `frontend/app.js:168-215` (compass), `frontend/index.html:309-319` (recenter), CSS 1436 + 1673.

**Evidence:** Compass position rules live in style.css at 1673-1688. Recenter rules at 1436-1439. These are DIFFERENT CSS blocks and the dev has to reason about both simultaneously when changing layout. A single `.nav-map-btn-stack` utility (flexbox column, anchored bottom-right) would prevent this. Not a bug per se — structural fragility. But it's clearly why the current overlap exists: two separate authors (or the same author at different times) independently picked `bottom:120` and `bottom:140` without considering stacking.

**Also:** `#sidebar-toggle` uses `top: 12px` — different side, no conflict. But `z-index: 25` for sidebar-toggle vs `z-index: 10` for compass/recenter — inconsistent. If `#sidebar-toggle`'s z-index is 25 to sit above nav-overlay (z-18), then recenter at z-10 sits BELOW the nav-overlay. If any part of the nav-overlay ever extends below the status area (e.g., banner grows to multi-line), the recenter button would be hidden. Currently nav-overlay is only at top (position:absolute; top:0), so no actual overlap.

---

### P2-3 [MINOR] `#nav-mute-btn` uses different styling base than `.map-btn` buttons
**Location:** `style.css:1373-1396`.

**Evidence:** Mute button has its own `position:absolute`, `width:32px`, `background: rgba(255,255,255,0.08)` — not using `.map-btn` class. On mobile this button is parented to `overlay` (nav-ui.js:664) so absolute positioning is relative to overlay, which is fine. Pattern is inconsistent but not wrong.

---

### P2-4 [SIGNIFICANT] `feedGPS` and `startNavigation` auto-center logic differ subtly on bearing
**Location:** `frontend/nav-ui.js:183-190` (startNavigation) vs `362-380` (feedGPS).

**Evidence:**
- `startNavigation`: `bearing: gps.heading || 0` — if heading is 0 (pointing North, totally valid GPS heading), `||` triggers fallback to 0 (same value, no-op), good. But if heading is undefined → falsy → 0. If heading is NaN → NaN is falsy? No — NaN is falsy. So → 0. OK.
- `feedGPS`: Uses `lastNavState.heading` if `headingValid`, else `map.getBearing()` — different: keeps current bearing, doesn't snap to 0.

Inconsistency: on first-frame entry, we forcibly set bearing to whatever raw `gps.heading` is (even if invalid/low-speed). But on subsequent frames we gate by engine's `headingValid`. A user starting navigation while stationary (common!) will see the map ROTATE to a random-stale heading, then settle to whatever.

**Fix approach:** First-frame easeTo should check `gps.speed >= HEADING_SPEED_GATE` before applying bearing, same as engine's gate.

---

### P2-5 [SIGNIFICANT → Bug #2] `renderRoute` (app.js:2139-2156) calls `fitBounds` with different padding than `getNavPadding`
**Location:** `frontend/app.js:2149-2156` vs `frontend/nav-ui.js:768-775`.

**Evidence:** `renderRoute` uses `{ top: 60, bottom: 60, left: sidebarW+20, right: 60 }` (or mobile 40/100). This is the pre-nav padding for "see the whole route." When the user clicks Start Nav, `startNavigation` does easeTo with `getNavPadding()` — different padding.

But if a reroute happens (Bug #2 fix would add a `renderRoute` call), that `renderRoute` would apply the pre-nav padding, which is WRONG for nav context and would reset the camera to "show the whole route" instead of staying in heads-up. So the fix for Bug #2 cannot simply call `renderRoute` — must call only the `source.setData` portion, not fitBounds.

---

## Pass 3 — Failure Mode Reasoning

### P3-1 [CRITICAL → Bug #1] GPS `heading` undefined vs null vs 0
**Location:** `frontend/nav-ui.js:336` (`heading = data.heading != null ? data.heading : (data.bearing != null ? data.bearing : 0)`), `frontend/navigation.js:540` (gate).

**Evidence:** `data.heading != null` treats both `null` and `undefined` as "missing" → `0`. So undefined heading propagates as `heading: 0` to engine. Engine checks `gpsSpeed >= 3 && gpsHeading !== null && gpsHeading !== undefined`. With `heading=0` (from fallback), check passes when speed >= 3 — but heading is BOGUS (gpsd sends heading=0 when no fix is moving). So engine treats 0-as-real-heading.

**Impact:** Compass orientation and snap-to-route disambiguation both use a fake "northbound" heading. Navigation snapping picks the wrong lane when parallel lanes exist.

**Fix approach:** Preserve undefined/null through to engine, don't coerce to 0: `heading: (data.heading != null) ? data.heading : (data.bearing != null ? data.bearing : null)`.

---

### P3-2 [CRITICAL → Bug #1] `gpsData.speed` undefined defaults to 0 — voice speed gate never opens
**Location:** `frontend/navigation.js:536` (`var gpsSpeed = gpsData.speed || 0`).

**Evidence:** If GPS dongle lacks speed (e.g., browser-geolocation-only mode from app.js), `speed` is undefined → 0. `lastSpeed = 0`. `checkVoice` gate: `if (lastSpeed < VOICE_SPEED_GATE(=2))` enters the gate and requires `distCheck <= VOICE_NEAR_ANNOUNCE_DISTANCE(=50)`. So no announcements unless user is within 50m of next maneuver — user walking/biking with undefined-speed GPS gets NO voice guidance until the very last second.

Conversely users WITH speed data but GPS reporting erratic speed (GPS jitter) might hit speed < 2 m/s gate intermittently, dropping voice prompts at distance and then firing at <50m (reinforcing the "only near" problem).

**Impact:** Contributes to reported bug #1's "first announcement is too late / all three bunched at turn".

**Fix approach:** When speed is unreliable/unavailable, fall back to a movement-based heuristic (distance covered vs time), or just don't gate on speed when GPS source lacks speed.

---

### P3-3 [CRITICAL → Bug #2] Valhalla 500 / empty trip silently falls back
**Location:** `frontend/nav-ui.js:506-516` (`attemptReroute`).

**Evidence:**
```js
.then(function (data) {
  if (data.trip && nav) {
    var newRouteData = buildRouteData(data.trip);
    if (newRouteData) { rerouteRetries = 0; nav.applyReroute(...); hideBanner(); }
  }
})
```
If Valhalla returns `{"error": "No path found"}` (no trip), the `.then` takes the falsy branch, does nothing — no retry, no user banner. The previous `.catch` path only catches network failures, not 200-responses-with-no-trip.

**Impact:** Off-route user sees "Recalculating..." banner stuck forever because engine timeout (`REROUTE_TIMEOUT = 10000`) fires and resets state back to "navigating" silently, but banner stays until next state emit overwrites it via `onNavUpdate`. The recalculating banner persists OR flickers on/off as state transitions hide/show it. User doesn't know rerouting failed.

**Fix approach:** Add `else { /* handle no-trip error, retry or show banner */ }` branch.

---

### P3-4 [SIGNIFICANT] User clicks "Stop" mid-reroute — fetch still in flight
**Location:** `frontend/nav-ui.js:500-532`.

**Evidence:** `fetch('/valhalla/route', ...)` is NOT abortable (no AbortController). User clicks Stop → `stopNavigation` sets `nav = null, active = false`. Fetch resolves later — `.then` block does `if (data.trip && nav)` — `nav` is null, so branch skipped. Good. But `hideBanner()` and `rerouteRetries = 0` still happen. And if retry triggers, `setTimeout(attemptReroute, delay)` schedules another fetch that fires 2-8 seconds AFTER nav is stopped, polling Valhalla uselessly.

**Impact:** Wasted network, potential banner ghost if another state emits in between (none should — engine is stopped). Mostly benign.

**Fix approach:** `stopNavigation` should cancel outstanding reroute retries: clear `rerouteRetryTimeout` (requires storing it).

---

### P3-5 [SIGNIFICANT → Bug #3] `overlay.offsetHeight === 0` poisons `getNavPadding`
**Location:** `frontend/nav-ui.js:768-775`.

**Evidence:** If overlay is display:none, offsetHeight=0, returns `{ top: 20 }`. `startNavigation` first easeTo at line 183 fires AFTER `overlay.classList.remove('hidden')` (line 169), so overlay should be laid out. BUT if CSS not yet fully parsed, or if overlay has 0 height because its children haven't rendered yet (e.g., first frame), `offsetHeight` could be low.

Also: `onNavUpdate` sets `--nav-overlay-height: overlay.offsetHeight + 'px'` (line 453) — if overlay is hidden (banner-only state never happens since banner is always visible during nav), this would be 0. Actually overlay is shown for entire nav; probably fine.

**Impact:** Intermittent stale padding on first frame.

---

### P3-6 [SIGNIFICANT] Maneuver list single-maneuver: `currentManeuverIdx + 1 >= route.maneuvers.length` — checkVoice returns early; no arrival voice
**Location:** `frontend/navigation.js:356-357`, and arrival handling at 589-596.

**Evidence:** Some Valhalla responses for very short trips produce ONE maneuver (start=destination). `currentManeuverIdx = 0`. `checkVoice` has `nextIdx = 1; if (nextIdx >= route.maneuvers.length) return;` — no voice, which is correct. Arrival detection: `snap.segmentIndex >= route.coords.length - 1 - ARRIVAL_SEGMENTS (=3)` → if route has only 2 coords (1 segment), the threshold is `segIdx >= -2` which is always true. Works.

**Impact:** No bug, but `ARRIVAL_SEGMENTS=3` means 3-coord routes always "arrive" at start. Edge case only, not a beta concern.

---

### P3-7 [MINOR] Route is a loop — start equals end. Snapping picks wrong side
**Location:** `snapToRoute` → `searchSegments` → heading disambiguation.

**Evidence:** For a route going A→B→A (loop), segments near A occur at beginning AND near end. Snap window is centered on `lastIndex`, so at start `lastIndex=0`, window covers early segments only (good). But as user approaches return, window slides forward and eventually includes the final segments which share coords with the initial ones — fallback full search at SNAP_FALLBACK_THRESHOLD=100m might pick the wrong segment.

**Impact:** On looped routes, user approaches destination and engine snaps them back to START position. Arrival check never fires.

**Fix approach:** Heading weighting helps, but for tightly-looping routes (same road both ways), consider limiting fallback search to forward direction only.

---

### P3-8 [CRITICAL → Bug #1] `speechSynthesis` not available on mobile Safari strict/private mode
**Location:** `frontend/nav-ui.js:75` (`speechAvailable`), 456-463 (`onVoice`).

**Evidence:** `speechAvailable = !!(window.speechSynthesis && window.SpeechSynthesisUtterance)`. On mobile Safari with strict privacy, `speechSynthesis` exists but `speak()` silently fails. `primeSpeech` sends an empty utterance — on iOS Safari, blank utterance throws or is a no-op.

Also `speechSynthesis.cancel()` in `onVoice` BEFORE every new utterance means that if the user is mid-announcement ("in half a mile, turn left"), the next 200m announcement cancels mid-word and starts the new one. Rapid cancel+speak cycling is known to crash iOS Safari's speech queue.

**Impact:** On iOS Safari, user hears choppy/truncated announcements or none at all. Symptoms match reported bug #1 ("first announcement too far / last two redundant") if previous announcement got CUT OFF partway and the user only heard "in half a" before the next "at 200m turn" hit.

**Fix approach:** Don't cancel if queue is empty; or queue utterances with a short debounce; or detect iOS and shorten announcement text.

---

### P3-9 [SIGNIFICANT → Bug #3] Window resize mid-nav — padding becomes stale
**Location:** `frontend/nav-ui.js:768-775`.

**Evidence:** `lastNavPaddingTop` caches overlay height to avoid re-easing. If user rotates phone or window resizes, overlay height may change (especially when `nav-banner` shows/hides). `PADDING_RECALC_THRESHOLD=5px` only recomputes if measured differs by >5px — but measured is fresh on each call (line 770). `if (Math.abs(measured - lastNavPaddingTop) > 5)` then `lastNavPaddingTop = measured` — so cache is updated when overlay grows. Actually this logic is FINE — it just hysteresis-dampens the cache.

HOWEVER: `feedGPS` applies `getNavPadding` every 500ms, so padding updates often. `startNavigation` applies once. Resize after startNav but before first feedGPS causes stale padding for up to 500 ms. Minor.

---

### P3-10 [SIGNIFICANT] `findManeuverForSegment` past last maneuver returns final — then `nextIdx = currentManeuverIdx+1 >= maneuvers.length` → skip voice
**Location:** `frontend/navigation.js:280-290`, `checkVoice` 356-357.

**Evidence:** As user approaches destination, `currentManeuverIdx` increments to final maneuver. Then `checkVoice` skips (nextIdx out of range). No "approaching destination" voice. Arrival check at 589 handles arrival voice via `onArrival`. OK.

---

### P3-11 [SIGNIFICANT] `observeRouteAvailability` shows startBtn whenever `export-route-btn` is unhidden — race with nav already active
**Location:** `frontend/nav-ui.js:121-135`.

**Evidence:** `MutationObserver` watches `export-route-btn`. If user clicks "Start Nav" then the route source in app.js is re-rendered (e.g., user edits a stop), `export-route-btn` unhide triggers observer → `if (!hidden && !active) startBtn.show()`. Conversely if active=true, branch doesn't show startBtn — good. But in the else branch `if (exportBtn.classList.contains('hidden'))`, startBtn hidden + `if (active) stopNavigation()` — this triggers nav stop when the route panel is cleared. OK, probably intentional.

But: `clearRoute` in app.js (line 2195) hides `export-route-btn`. If user clears route mid-nav, `stopNavigation` fires. User loses nav session via an action on a different panel. Probably intentional. Not a bug.

---

## Pass 4 — Concurrency Reasoning

### P4-1 [CRITICAL → Bug #2] `rerouteRetries` is module-level; second concurrent reroute resets first's counter
**Location:** `frontend/nav-ui.js:32-33`, 496 (`rerouteRetries = 0` in `onReroute`), 511, 519, 526.

**Evidence:** `rerouteRetries = 0` at module scope. On `onReroute`, it's set to 0 (line 496), then `attemptReroute` runs. On failure, `rerouteRetries++` at line 519. Retry schedules `setTimeout(attemptReroute, delay)`. If during the retry delay, user goes off-route AGAIN, engine calls `onReroute` again → `rerouteRetries = 0` → new attempt. But OLD setTimeout still pending → fires → `rerouteRetries++` → might exceed MAX → falls to silent failure branch for the NEW reroute's retry counter.

Also `seq` preserves old fetch context, and `nav.applyReroute(routeData, seq)` uses old seq → engine ignores stale seq. But `rerouteRetries` is shared, causing old retries to interfere with new counter.

**Impact:** Two concurrent reroutes corrupt each other's retry budget. User may see "Reroute failed" banner when ONE of them failed retry-exhaustion but the other succeeded.

**Fix approach:** Scope `retries` inside the closure: `attemptReroute(body, seq, retries=0)`, pass `retries+1` on recursive call, remove module-level counter.

---

### P4-2 [CRITICAL → Bug #2] `rerouteSeq` increments in engine's `triggerReroute` but UI doesn't know to abort its in-flight fetch
**Location:** `frontend/navigation.js:639`, `794` (`if (seq !== rerouteSeq) return`).

**Evidence:** User goes off-route → triggerReroute seq=1 → UI fires fetch#1. Before response, user goes off-route AGAIN (e.g., wrong turn after first wrong turn) → triggerReroute seq=2 → UI fires fetch#2. Fetch#1 returns first → `applyReroute(data1, seq=1)` → engine checks `seq(1) !== rerouteSeq(2)` → ignores. OK, engine-safe. But `hideBanner()` at nav-ui.js:513 STILL runs (not conditional on seq). So banner hidden momentarily even though seq-2 reroute still in flight.

Also: UI does NOT know it was ignored. Banner flickers.

**Fix approach:** In `applyReroute`, return status so UI knows if applied. UI then conditionally hides banner only on actual apply.

---

### P4-3 [SIGNIFICANT] `autoCenterTimer` can fire after `stopNavigation`
**Location:** `frontend/nav-ui.js:622-624`, `stopNavigation:223` (`clearTimeout(autoCenterTimer)`).

**Evidence:** `stopNavigation` clears. Good. But `recenter` callback → `feedGPS()` — `feedGPS` guards with `if (!active || !nav) return` at line 327, so late timer firing is safe.

---

### P4-4 [MINOR] GPS tick rate 500ms vs VOICE_COOLDOWN 5000ms — fast approach can skip thresholds
**Location:** `frontend/nav-ui.js:323` vs `navigation.js:49`.

**Evidence:** At 30 m/s (~65 mph), 500 ms tick covers 15m. Between 800m threshold fire and 5000ms cooldown, user covers 150m. So when threshold 1 (200m) becomes eligible (5s later), user is at ~650m — STILL above 200m. Good, announces correctly at 200m later.

But at 45 m/s (~100 mph, extreme): user covers 225m in 5s. At 800m first announce, 5s later user at 575m. Check threshold 1 (200m): not yet. Next tick, 500 ms, user at 560m. Eventually at 200m, announce. Still OK.

But at FOOT pace, 500 ms tick gives 2 samples per 1 m. Triggers fine.

Real risk: very fast GPS update flurry AFTER long silence (e.g., GPS was stale 20s, then flood of catchup updates). Each "update" advances the engine by one logical tick. Engine would process them sequentially but distance-to-next might CROSS multiple thresholds between updates. Actually since each GPS update snaps and checks voice, if first update at 800m, next update at 40m (big jump), threshold 0 fires then threshold 1 blocked by cooldown — but we only break out of loop, not mark threshold 1 as done. Next update (5s later), user at... well, "GPS stale then flood" is unusual.

---

### P4-5 [SIGNIFICANT] `primeSpeech` resolves async — announcements before prime resolves get dropped on iOS
**Location:** `frontend/nav-ui.js:643-648`.

**Evidence:** `primeSpeech` queues empty utterance. On iOS, first `speak` after user gesture "unlocks" audio. If the very first `onVoice` fires BEFORE primeSpeech's utterance finishes processing (few ms race), that announcement may be silent.

**Impact:** First announcement after start may be silent on iOS. Subsequent ones work.

---

### P4-6 [SIGNIFICANT] `feedGPS` setInterval + `stopNavigation`: interval could fire after `active=false`
**Location:** `frontend/nav-ui.js:323`, 225-226.

**Evidence:** `stopNavigation` does `if (gpsFeedInterval) clearInterval(gpsFeedInterval); gpsFeedInterval = null;` — but it also sets `active=false` first. Interval callback guards with `if (!active || !nav) return`. Safe.

---

### P4-7 [SIGNIFICANT] Engine's `staleInterval` is cleared on stop via `reset`, but never started from within `applyReroute` when engine transitions rerouting → navigating
**Location:** `frontend/navigation.js:813`, `681-690`.

**Evidence:** `startStaleChecker` is called only in `window.GeographicaNav.start`. `applyReroute` doesn't restart it — but it's already running from the original start (never stopped between). OK.

But if engine `stop` called mid-reroute (UI stops nav → `reset` → `stopStaleChecker()`), then engine is done. If fetch then returns with `applyReroute`, engine has route=null... actually `applyReroute` first checks `if (seq !== rerouteSeq)` — `rerouteSeq` was reset to 0 in `reset`. Passed seq is some positive number → doesn't match → return. Safe.

---

## Pass 5 — Error Propagation

### P5-1 [CRITICAL → Bug #2] `attemptReroute` final failure path doesn't restore engine state
**Location:** `frontend/nav-ui.js:519-530`.

**Evidence:** On final retry failure, UI shows "Reroute failed" banner for 5 seconds. Comment says `// Engine timeout will handle state recovery`. Engine's REROUTE_TIMEOUT (10000ms) fires at navigation.js:640-646: sets state back to "navigating", clears off-route history. So 10 seconds after reroute triggered, engine gives up. But if UI failed 3 retries taking >10s, engine has already reverted.

But if UI happens to succeed on retry AFTER the engine's 10-second timeout already fired:
- t=0: engine triggers reroute, state='rerouting'
- t=10s: engine timeout → state='navigating', `rerouteSeq` unchanged
- t=14s: UI fetch succeeds, calls `applyReroute(data, seq=1)` — seq matches `rerouteSeq=1` → applies.
- But engine state was 'navigating' (no longer 'rerouting'), still ok since `applyReroute` sets state='navigating' at line 813 anyway.

What about the other order:
- t=0: reroute fires
- t=3s: fetch fails, retry scheduled for t=5s
- t=5s: retry fetches → fails at t=8s, retry at t=12s
- t=10s: engine timeout → state='navigating'
- t=12s: retry fires → eventually resolves → `applyReroute` runs with old seq → matches → new route applied SEVERAL seconds late. If user has driven a ways, the new route is from an OLD position.

**Impact:** Post-timeout reroutes apply stale routes.

**Fix approach:** Abort pending retries if engine timeout has fired. Use AbortController + state read.

---

### P5-2 [SIGNIFICANT → Bug #2] `nav.applyReroute(data, seq)` returns undefined — no way for UI to know if applied
**Location:** `frontend/navigation.js:791-818`, `frontend/nav-ui.js:512`.

**Evidence:** `applyReroute` returns no value. On mismatched seq, it silently returns at line 793. UI has no signal. Banner hide runs regardless.

**Fix approach:** Return true/false.

---

### P5-3 [SIGNIFICANT → Bug #1] `onVoice` doesn't handle `speechSynthesis.speak` throw
**Location:** `frontend/nav-ui.js:459-462`.

**Evidence:** `speechSynthesis.speak(utterance)` wrapped in nothing. On iOS Safari strict mode, throws if audio session denied. Next call would throw too. No fallback. Engine `lastAnnouncementTime` was already set → cooldown consumed for nothing.

**Fix approach:** try/catch, reset cooldown on throw (or signal back to engine).

---

### P5-4 [SIGNIFICANT → Bug #1] `setManeuverIcon(null)` or `type=null` → `buildManeuverSVG` default path (straight arrow)
**Location:** `frontend/nav-ui.js:419-421`, `938-941`, `787-932`.

**Evidence:** `if (nm && nm.type != null) setManeuverIcon(nm.type)`. If Valhalla maneuver has `type` undefined, icon is NOT updated — stays as previous maneuver's icon. For the final maneuver (destination flag), type 4/5/6 is set by Valhalla usually. OK.

But in `switch (type)` at line 833, `null/undefined` wouldn't match any case → default (straight arrow). Not used because we gate at 419, but the safety is redundant.

**Impact:** No bug surfaced. Defensive comment.

---

### P5-5 [SIGNIFICANT → Bug #2] `buildRouteData` returns null on missing legs — silent failure
**Location:** `frontend/nav-ui.js:237-277`.

**Evidence:** `if (!trip || !trip.legs) return null`. Caller: `if (!routeData) return` in `startNavigation`, or `if (newRouteData) { ... }` in `attemptReroute`. In neither case is any user-visible error shown. On reroute, a malformed Valhalla response (no legs) → `buildRouteData` null → rerouter silently does nothing → `hideBanner` doesn't run → banner "Recalculating..." lingers until engine timeout.

**Fix approach:** On null return from `buildRouteData` in reroute path, show error banner.

---

### P5-6 [SIGNIFICANT] `buildRouteData` totalDistance calculation depends on `window._geographicaUseImperial`
**Location:** `frontend/nav-ui.js:266`.

**Evidence:** Uses `window._geographicaUseImperial` — but that global is set elsewhere (app.js). If it's undefined at the moment `buildRouteData` runs (e.g., before `syncUnits` has fired on first init), the conversion is `* 1000` (kilometers), but Valhalla's `summary.length` might be in miles. Mismatch of 1.609×.

**Impact:** `totalDistance` wrong on first-call race; `speedRatio` and ETA downstream are off by 60% for the life of the session.

**Fix approach:** Read from Valhalla's `directions_options.units` echo OR store unit at request time.

---

### P5-7 [SIGNIFICANT] `onReroute` callback doesn't include the previous route's destination explicitly — relies on `window._geographicaLastTrip.locations[-1]`
**Location:** `frontend/nav-ui.js:482-486`.

**Evidence:** If `window._geographicaLastTrip` was cleared (e.g., by `clearRoute` in app.js) between when nav started and when reroute fires, `lastTrip` is null. Then `locations` array won't include a destination — Valhalla routes from current GPS to nowhere → 400 error (probably).

Reproducer: start nav, then `clearRoute` somehow (programmatically). Off-route → reroute → no destination → fails.

**Impact:** Edge case. `observeRouteAvailability` might catch this via `stopNavigation` call when `clearRoute` hides export-btn. But if order is: (1) clear→export-btn hidden → stopNav fires → nav=null → engine doesn't tick → no reroute. Safe.

---

## Per-Reported-Bug Root Cause Summary

### Bug #1 — Voice announces 3× per turn; first too far; last two redundant
**Primary root causes:**
- P1-2: All three thresholds (800/200/50) fire in rapid succession when VOICE_COOLDOWN gate clears — they don't mark each other as redundant.
- P3-1, P3-2: Heading 0 vs undefined, speed 0 vs undefined — engine gate `lastSpeed < 2` makes voice suppressed at distance; then fires only at <50m where all thresholds stack.
- P3-8, P5-3: iOS Safari `speechSynthesis.cancel()` + `speak()` race, queue breakage.
- P1-6: Mute state out of sync at session start — first announcement swallowed but cooldown burned.

**Fix approach:**
1. `checkVoice`: when threshold ti fires, mark all `ti..N-1` as announced for that maneuver (one alert per maneuver-crossing, not three).
2. Tune thresholds to costing+speed adaptive: for auto at <50 km/h reduce 800→400, 200→150, 50→30.
3. Preserve undefined GPS heading/speed through to engine.
4. In `onVoice`: detect iOS + skip explicit cancel() when queue empty.
5. At `startNavigation`: `nav.setMuted(muted)` before `nav.start(routeData)`.

### Bug #2 — Route polyline doesn't update after reroute
**Primary root cause:** P1-1: `applyReroute` only updates engine route data, never updates the MapLibre `route` GeoJSON source.

**Secondary causes:**
- P1-10: `_geographicaLastTrip` not refreshed → stop+restart resumes original stale route.
- P5-5: `buildRouteData` returns null silently.
- P4-1, P4-2: Retry counter + seq races corrupt multi-reroute scenarios.
- P5-1: Post-engine-timeout reroute applies stale-position route.

**Fix approach:**
1. In `attemptReroute` success branch, call `map.getSource('route').setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: newRouteData.coords } })`.
2. Update `window._geographicaLastTrip = data.trip; window._geographicaLastTrip._costing = ...`.
3. Refactor `attemptReroute` to use closure-scoped retries and AbortController.
4. Return boolean from `applyReroute`; UI hides banner only on true.

### Bug #3 — GPS marker not at bottom 1/3
**Primary root cause:** P1-3: `getNavPadding` returns `{ top: overlay_height + 20 }` — this shifts map centroid DOWN by `top/2`, yielding ~55-60% down, not the intended 66%.

**Secondary causes:**
- P2-1: `restoreMapState` doesn't clear padding, and more critically can't see nav's applied padding.
- P3-5: `overlay.offsetHeight === 0` on first frame.
- P2-4: First-frame easeTo uses raw GPS heading even at zero speed.

**Fix approach:** Compute padding so that `(top + (H - top - bottom) / 2) = (2H/3)` → `top = H/3` (independent of overlay height, as long as overlay fits above that point). Read `window.innerHeight` dynamically; add `bottom = 0`.

### Bug #4 — Recenter button overlaps compass on mobile; semantic order wrong
**Primary root cause:** P1-9: CSS `bottom: 120px` for recenter + `bottom: 140px` for compass (mobile) + both 36px height → 16px vertical overlap. Also recenter is BELOW compass; user wants inverse.

**Fix approach:**
```css
#compass-north-btn { bottom: 120px; right: 12px; } /* desktop + mobile */
#nav-recenter-btn  { bottom: 170px; right: 12px; }
@media (max-width: 480px) {
  /* leave as-is, or slightly tighter */
}
```
Verify scale bar at `bottom: 26px !important` clears compass (120 - 26 - 20 = 74px gap, fine).

---

## Unique Findings (not mapped to reported bugs)

### U-1 [CRITICAL] Multi-stop reroutes lose all waypoints (P1-11)
`buildRouteData` hardcodes `remainingWaypoints: []`. Reroute goes current→destination, skipping intermediate stops. **Severity: critical for multi-stop nav.**

**Location:** nav-ui.js:274-275.

### U-2 [SIGNIFICANT] `restoreMapState` leaks nav padding into post-nav camera (P2-1)
After nav stop, map camera is offset by stale nav padding. User sees a drift on nav exit. **Fix:** explicit `padding: {top:0,...}` in restoreMapState easeTo.

### U-3 [SIGNIFICANT] First-frame nav easeTo uses raw GPS heading (P2-4)
Starting nav while stationary snaps map to last-stale heading. Engine gates heading by speed but startNav does not.

### U-4 [SIGNIFICANT] `_geographicaUseImperial` global race breaks totalDistance math (P5-6)
`buildRouteData` reads window global that might be undefined on early init; 1.6× error in totalDistance → ETA off by 60% for session lifetime.

### U-5 [SIGNIFICANT] `applyReroute` resets `announcedSet` incorrectly (P1-8)
Loop tries to preserve indices `<= currentManeuverIdx` (which was just reset to 0), so keeps only "0-*" keys. Semantically confused. Should just clear entirely.

### U-6 [SIGNIFICANT] `rerouteRetries` is module-level → concurrent reroutes corrupt counter (P4-1)
If a second reroute triggers while first is still retrying, counter gets reset mid-flight → first's retries exceed MAX prematurely or get "lost".

### U-7 [SIGNIFICANT] `applyReroute` return value is undefined — UI can't detect ignore (P5-2)
`hideBanner()` runs unconditionally after `nav.applyReroute`, even when engine ignored (seq mismatch). Banner flickers.

### U-8 [SIGNIFICANT] Valhalla 200 response with no-trip field silently no-ops in attemptReroute (P3-3)
Only network errors trigger retry. JSON-with-error-field goes nowhere → banner stuck until engine timeout.

### U-9 [SIGNIFICANT] `stopNavigation` doesn't cancel in-flight reroute fetch or retry setTimeout (P3-4)
Nav can be stopped mid-reroute, but the fetch+retry chain keeps running (wasteful, not catastrophic).

### U-10 [MINOR] `speedHistory` cleared on reroute — ETA reverts briefly to theoretical (P1-7)
Cosmetic ETA jitter after reroute until 5+ new samples accumulate.

### U-11 [MINOR] `feedGPS` easeTo bearing uses `map.getBearing()` when heading invalid (P2-4)
Better than nothing, but holds stale bearing even if user has STOPPED rotating. Might confuse on long stops.

### U-12 [MINOR] Looped routes (A→B→A) can snap to the wrong side on fallback full-polyline search (P3-7)
Heading weighting mitigates but doesn't eliminate.

### U-13 [MINOR] `onVoice` always `speechSynthesis.cancel()` before `speak()` → mid-utterance cuts (P3-8, P5-3)
Cancels "in half a mile, turn left" partway when 200m announcement arrives. User hears "in half a —" then "at 200m turn left" — feels like repetition + truncation.

### U-14 [MINOR] Nav engine callbacks not cleared on `stop()` (P1-5)
Defense-in-depth gap. Would matter if a late timer ever fired post-stop.

### U-15 [MINOR] `#nav-mute-btn` styled ad-hoc, not using `.map-btn` (P2-3)
Inconsistency in button styling system.

### U-16 [MINOR] `z-index` scattered: overlay=18, sidebar-toggle=25, map-btn=10 (P2-2)
If nav-overlay height ever grows into the map-btn zone, recenter/compass would be visually hidden. Presently no overlap but fragile.

---

## Design Concerns

- **Two truths for mute state** (engine + UI both track). Synchronization isn't enforced. Recommend: engine is source of truth for announcement gating; UI only flips engine flag and reads it back.
- **Module-level mutable counters** (`rerouteRetries`, `announcedSet`, `lastNavPaddingTop`) make concurrency reasoning hard. Prefer closure-scoped state per reroute attempt.
- **Two-file layout for map buttons** (compass in app.js, recenter in index.html) with matching CSS split across style.css:1436 and :1673 is structurally fragile. Proposal: one shared `.nav-btn-stack` flex container anchored at bottom-right.
- **Voice threshold semantics** are timing-based (cooldown) rather than distance-progress-based. A distance-progression model ("fire alert when crossing threshold from above") is more natural and would eliminate triple-fire.
- **No AbortController** on fetch-based operations. Reroute retries can outlive nav session, multi-tab scenarios could leak.
- **`_geographicaLastTrip` / `_geographicaUseImperial` / `_geographicaGPSData` / `_geographicaMap`** — four global window references, each a potential race source. Should be encapsulated into a single state module.
