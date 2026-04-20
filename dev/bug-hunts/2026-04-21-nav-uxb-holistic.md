# Bug Hunt Report — Turn-by-turn Nav UX (holistic pass)

**Date:** 2026-04-21
**Scope:** Turn-by-turn navigation surface (engine + UI bridge) after four beta-tester reports and four failed fix attempts (1761508, 018adcf, 8b37aae, da0b0a0).

## Scope

Read in full:

- `frontend/navigation.js` (854 lines) — engine, state machine, voice, reroute.
- `frontend/nav-ui.js` (953 lines) — MapLibre+DOM bridge, GPS feed, padding, banners.
- `frontend/style.css` nav-relevant sections — `.map-btn`, `#nav-*`, `#compass-north-btn`, `#nav-overlay`, `@media` queries at 768 / 480 breakpoints, MapLibre ctrl overrides.
- `frontend/index.html` lines 220-320 — nav overlay markup, recenter button, compass/GPS buttons.
- `frontend/app.js` — custom compass button (166-220), `renderRoute` / `clearRoute` (2114-2220), route-fetch path (2055-2108), `addControl` calls (163, 224, 1098).

Approach: read the entire nav surface, then reason by theme (state/lifecycle, UI/padding, CSS/controls, voice/timing, reroute-map-sync) to find what the previous targeted fixes missed.

## Reasoning by theme

### 1. State machine + lifecycle

The engine has a clean FSM (`idle → joining → navigating → rerouting → arrived`), but the **engine and UI each own pieces of the "current route" state**, and the two are not fully synchronized on reroute:

- Engine owns: `route`, `route.maneuvers`, `coords`, `cumulativeDistances`, `announcedSet`.
- UI owns: `map.getSource('route')` (the blue polyline), `window._geographicaLastTrip`, the sidebar directions list (`<ol id="route-directions">`).

`nav.applyReroute(newRouteData, seq)` at nav-ui.js:512 updates the engine but **never propagates the new shape to the map source or the sidebar**. This is the #1 silent failure (Bug 2 confirmed).

`applyReroute` in navigation.js:791-818 has subtler state-consistency issues:

- **`announcedSet` filter is nonsensical across reroutes.** Line 805 keeps entries with `idx <= currentManeuverIdx`, but `currentManeuverIdx` is reset to `0` on line 798 one statement earlier. So the filter only keeps keys whose maneuver index is 0 — i.e., the depart maneuver. But those keys reference OLD maneuvers that no longer exist; the NEW route's maneuver 0 is a completely different entity. Keeping stale keys accomplishes nothing (post-reroute maneuver 0 never re-announces anyway — it's behind you), but the comment claims to preserve "forward maneuvers' thresholds" which is the opposite of what the code does. Fix: `announcedSet = {};`.
- **`lastAnnouncementTime` is NOT reset.** If the off-route/reroute cycle happens during a voice-cooldown window, the first announcement of the new route can be suppressed for up to 5s. Minor, but contributes to perception of "voice feels random after a reroute".
- **`lastRerouteTime` is not cleared on timeout.** In `triggerReroute` line 640-646, if the 10s timeout fires (no response from Valhalla), state flips to `navigating` but the 15s cooldown still blocks the next reroute for the remaining 5s. So if the user is still off-route, they're stuck on the wrong line for up to 20s, not 15s.
- **`rerouteTimeoutId` handle leak on timeout.** Line 641 fires the callback but doesn't set `rerouteTimeoutId = null`. Stale handle; minor.

### 2. UI / padding math

MapLibre's `padding` option shifts the camera's reference center AWAY from the padded edge. With `padding: { top: N }`, the map point placed at `center: [lng, lat]` is rendered at screen position `(vh + N) / 2` from the top of the viewport — i.e., `N/2` pixels below geometric center.

`getNavPadding()` returns `{ top: overlay.offsetHeight + 20 }`, where overlay is typically 120-160px tall. That's `top ≈ 140-180`. On a 1000px tall screen:

```
screen_y_of_center = (1000 + 160) / 2 = 580 px  →  58% from top
```

**That matches the "~57-60%" the testers report exactly.** It's not a bug in intent, it's a bug in understanding what `padding.top` does. Padding of N moves the center down by N/2, not N. To put the GPS marker at 80% (800px on 1000px screen), the center must be at 800. That requires an effective top-bottom differential of `2 × (800 - 500) = 600px`, i.e., `padding: { top: 600, bottom: 0 }` on a 1000px viewport. The fix is to make padding viewport-proportional:

```js
var vh = window.innerHeight;
return { top: vh * 0.6, bottom: 0 };   // puts center at 80% from top
```

Or equivalently `{ top: vh * 0.6 + overlay.offsetHeight, bottom: 0 }` if you also want to clear the overlay — though overlay is at top:0 so it's already out of the camera region.

**Also: padding leak across nav sessions.** `restoreMapState` (nav-ui.js:549-559) calls `easeTo` with center/zoom/pitch/bearing but **not padding**. MapLibre `easeTo` only updates properties you pass, so whatever padding was set during nav persists on the map object. After `stopNavigation()`, every subsequent `easeTo`/`flyTo` call the app makes inherits that ~160px top padding until something explicitly resets it. Symptoms: search result pans are off-centered after a nav session ends; recentering on GPS after ending nav feels low. Fix: add `padding: { top: 0, bottom: 0, left: 0, right: 0 }` to the `restoreMapState` easeTo.

### 3. CSS stacking / map controls

Four elements occupy the `bottom-right` strip during nav:

| element              | desktop bottom | mobile bottom (≤480) | height        | right |
| -------------------- | -------------- | -------------------- | ------------- | ----- |
| MapLibre scale bar   | ~30 (via `bottom-right` + override) | ~30 | 10    | 40    |
| MapLibre zoom ctrl   | 26 (from `!important`) | ~52   | ~68   | 0     |
| `#compass-north-btn` | 160            | 140                  | 36            | 12    |
| `#nav-recenter-btn`  | 120            | 120                  | 36            | 12    |

Concrete collision analysis:

- **Desktop:** recenter spans 120-156px; compass spans 160-196px. Gap of 4px — they do not overlap but they are visually flush, and recenter is BELOW compass, which is the opposite of what the tester asked for.
- **Mobile (≤480px):** recenter spans 120-156px; compass spans 140-176px. **16px overlap, recenter partially on top of compass.** Confirmed bug.
- **Both breakpoints:** the MapLibre NavigationControl (zoom) at `bottom-right` `!important: bottom: 26px` (style.css:1177) occupies 26-94px, so compass at 140-160px is just above it. Adding any height to these custom buttons would push into the zoom control. Any fix must reckon with this 4-way stack.

Desired layering (top→bottom at right edge): **recenter > compass > zoom > scale**. Proposed numbers:
- `#nav-recenter-btn`: bottom: 208 (desktop), 188 (mobile)
- `#compass-north-btn`: bottom: 162 (desktop), 142 (mobile)  (kept where it is)
- zoom ctrl: 26 (unchanged)

Giving each a 10px gap. Put recenter `46px` above compass (36 + 10).

### 4. Voice / timing

`VOICE_THRESHOLDS.auto = [800, 200, 50]` with `VOICE_COOLDOWN = 5000`. Fire logic in `checkVoice` (navigation.js:341-391) iterates thresholds and breaks after a successful announcement (to respect cooldown), relying on subsequent ticks to catch later thresholds.

Per-maneuver announcement count at common speeds:

| speed (m/s) | mph | 800→200 | 200→50 | announcements/turn |
| ----------- | --- | ------- | ------ | ------------------ |
| 30          | 67  | 20 s    | 5.0 s  | 3 (at the edge of cooldown for the last pair) |
| 20          | 45  | 30 s    | 7.5 s  | 3 |
| 13          | 30  | 46 s    | 12 s   | 3 |
| 5           | 11  | 120 s   | 30 s   | 3 |

Above VOICE_SPEED_GATE (2 m/s), **every auto-costing maneuver gets 3 announcements**. That matches the tester report. Two independent UX problems:

- **The 800m threshold is too far out in most contexts.** Google Maps uses ~500m (or 0.5mi) as the "far" threshold and typically only announces twice for non-highway maneuvers. Even at 67 mph (~highway), 800m is ~25 seconds out and feels premature to drivers.
- **200m + 50m is semantically redundant at driving speed.** The 50m announcement uses `verbal_pre_transition_instruction` ("Turn right onto Main Street, then turn left onto Oak"), and the 200m one typically uses `verbal_transition_alert_instruction` ("In 200 meters, turn right onto Main Street"). At 20 m/s, these are 7.5 seconds apart — for practical driving, that's back-to-back identical information.

Recommended fix: drop to **two thresholds for auto** (`[500, 50]`) or keep three but make them more distinct and context-aware (e.g., `[1000, 150, 30]` and suppress the 150m one if the 1000m one fired within 20 seconds). The two-threshold approach matches Google Maps / Apple Maps / Waze and is strictly simpler.

### 5. Reroute ↔ map sync (Bug 2 root cause deep-dive)

`onReroute` (nav-ui.js:470) and `attemptReroute` (nav-ui.js:500) wire the engine to Valhalla. On success:

```js
var newRouteData = buildRouteData(data.trip);
if (newRouteData) {
  rerouteRetries = 0;
  nav.applyReroute(newRouteData, seq);   // ← only engine is updated
  hideBanner();
}
```

Missing:

1. `map.getSource('route').setData(...)` with the new decoded polyline.
2. `window._geographicaLastTrip = data.trip` (so if the user stops and restarts nav, they get the NEW route, not the one that was rerouted-away from).
3. `window._geographicaLastTrip._costing = info.costing` (preserve costing).
4. Sidebar `<ol id="route-directions">` rebuild with the new maneuvers.

The cleanest fix is to call `renderRoute(data.trip)` from app.js, but that function is currently scoped to app.js's IIFE. Options:

- Expose `window._geographicaRenderRoute = renderRoute` from app.js, call from nav-ui.
- Duplicate the `map.getSource('route').setData(...)` call in nav-ui (less clean, but fewer coupling points).
- Refactor `renderRoute` into two parts: `updateRouteSource(trip)` (map + trip globals) and `renderRouteSummary(trip)` (sidebar + summary card), and call the former from both places.

During nav, rebuilding the sidebar is debatable (the sidebar is usually collapsed), but the map source MUST update or the user sees the old route the whole way.

### Race conditions worth noting

- `rerouteRetries` is module-level in nav-ui. If the engine triggers a new reroute (different `seq`) while the old one is mid-retry, both retry chains share the `rerouteRetries` counter. In practice `REROUTE_COOLDOWN=15s` + `REROUTE_TIMEOUT=10s` prevents genuine overlap, but the shared state is fragile.
- `rerouteSeq` in the engine is correctly checked on `applyReroute` (line 793). UI side does pass it through (nav-ui.js:494 `var seq = info._seq;` is closed over by `attemptReroute`). Seq handling is correct.
- `_geographicaGPSCallback` lifecycle: the nav-ui reads `window._geographicaGPSData` via polling (`setInterval(feedGPS, 500)`), it doesn't register a callback. `stopNavigation` clears `gpsFeedInterval` correctly. Clean.

## Confirmed bugs table

| # | Title | Severity | Location |
|---|-------|----------|----------|
| 1 | Reroute does not update map polyline, sidebar, or `_geographicaLastTrip` | critical | nav-ui.js:500-515 |
| 2 | Nav camera padding math: `top: overlay_height` puts marker at 58%, not 80% | significant | nav-ui.js:768-775 |
| 3 | Nav padding leaks across sessions (`restoreMapState` doesn't reset padding) | significant | nav-ui.js:549-559 |
| 4 | Three voice announcements per maneuver is excessive + first threshold is too far | significant | navigation.js:42-46 |
| 5 | Recenter/compass button overlap on mobile; recenter below compass on desktop (wrong order) | significant | style.css:1436-1439, 1673-1688 |
| 6 | `applyReroute` keeps stale `announcedSet` keys from pre-reroute maneuvers; comment contradicts code | minor | navigation.js:798-809 |
| 7 | `lastAnnouncementTime` not reset on reroute; `lastRerouteTime` not reset on timeout | minor | navigation.js:791-818, 640-646 |
| 8 | `document.documentElement.style.setProperty('--nav-overlay-height', ...)` per tick; CSS var unused | minor | nav-ui.js:453 |
| 9 | `rerouteTimeoutId = null` not set after timeout callback fires | trivial | navigation.js:640-646 |

## Per-reported-bug root cause

### Bug 1 — "3 announcements per turn, too redundant; first is too far out"

**Root cause:** `VOICE_THRESHOLDS.auto = [800, 200, 50]` (navigation.js:43) produces a guaranteed 3-announcement cadence at any driving speed above the 2 m/s speed gate. At typical driving speeds, the 200m and 50m announcements land 5-15 seconds apart — close enough that users perceive them as the same message repeated.

**Why previous fixes failed:** commit 1761508 adjusted the voice-coverage logic but did not cut a threshold. The structure of "3 tiered announcements" was preserved.

**Fix:** drop to `auto: [500, 50]` (matches Google Maps cadence). Optionally also lower the 500m for pedestrian/bicycle (already the case). Validate empirically at 30 and 60 mph.

**Side-effect check:** `NEXT_AFTER_NEXT_DISTANCE=500` appending "then X" is only done for the NEAR announcement (`ti === 2` branch, lines 372-385). That branch will still fire with 2 thresholds as `ti === 1`. Keep the branch but key it on `ti === thresholds.length - 1` so it still attaches to the final announcement regardless of threshold count.

### Bug 2 — "Map polyline doesn't update after a reroute"

**Root cause:** `attemptReroute` (nav-ui.js:500) calls `nav.applyReroute` which only updates engine-side state. `map.getSource('route').setData(...)` is never called for the new shape. `window._geographicaLastTrip` is also stale, which breaks restart-after-stop behavior.

**Why previous fixes failed:** the fixes addressed engine state (seq handling, retry logic) but never the UI <-> map source wiring.

**Fix:** after successful reroute, call a helper that updates the map source:

```js
// in attemptReroute, after nav.applyReroute(newRouteData, seq):
var newCoords = newRouteData.coords;
var src = map.getSource('route');
if (src) src.setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: newCoords } });
window._geographicaLastTrip = data.trip;
window._geographicaLastTrip._costing = info.costing;
```

Optionally also rebuild the sidebar directions list; less urgent since sidebar is usually hidden during nav.

### Bug 3 — "GPS marker at ~60%, want 80% (Google Maps style)"

**Root cause:** `getNavPadding()` returns `{ top: overlay.offsetHeight + 20 }`. With MapLibre's padding semantics, the screen center is offset by `padding.top / 2`, not `padding.top`. For a 1000px viewport and ~160px top padding, the marker lands at 580px (58%). To hit 80% (800px), effective top padding needs to be ~600px on that viewport.

**Why previous fixes failed:** all four prior fixes treated the offset as additive when it's halved by MapLibre. Throwing more pixels at `padding.top` nudges the marker but doesn't get close to 80% until the number becomes absurd (and makes camera math brittle).

**Fix:** make padding viewport-proportional.

```js
function getNavPadding() {
  if (!overlay || overlay.classList.contains('hidden')) return {};
  var vh = window.innerHeight;
  var overlayH = overlay.offsetHeight || 140;
  // Desired marker at 80% from top. With padding-as-inset, need top-bottom = 2*(0.8*vh - 0.5*vh) = 0.6*vh.
  // Also clear the overlay on top: add overlayH so the center isn't visually near/under it.
  var targetTop = Math.round(0.6 * vh + overlayH);
  if (Math.abs(targetTop - lastNavPaddingTop) > PADDING_RECALC_THRESHOLD) {
    lastNavPaddingTop = targetTop;
  }
  return { top: lastNavPaddingTop, bottom: 0, left: 0, right: 0 };
}
```

Additionally fix the padding-leak in `restoreMapState` by passing `padding: { top: 0, bottom: 0, left: 0, right: 0 }` in the easeTo (nav-ui.js:551).

### Bug 4 — "Recenter button overlaps compass button"

**Root cause:** CSS bottoms chosen without reference to each other. Recenter at bottom:120px sits below compass at 160px (desktop) and overlaps compass at 140px (mobile).

**Why previous fixes failed:** previous fix(es) adjusted ONE button's bottom value but not both, leaving the stacking order inverted or the mobile overlap unresolved.

**Fix:** put recenter ABOVE compass, with compass staying clear of the zoom control (which `!important`s itself to bottom:26px and is ~68px tall).

```css
/* Stack order bottom→top along right edge: scale/zoom (MapLibre) · compass · recenter */
#nav-recenter-btn { bottom: 208px; right: 12px; }
#compass-north-btn { bottom: 162px; right: 12px; }
@media (max-width: 480px) {
  #nav-recenter-btn { bottom: 188px; right: 12px; }
  #compass-north-btn { bottom: 142px; right: 12px; }
}
```

The 46px spacing = 36px button height + 10px gap. Zoom ctrl occupies 26-94px; compass at 142-178px (mobile) leaves 48px clearance, good.

## Additional findings from the holistic view

### A1. Padding leak across nav sessions (see theme 2 above)

`restoreMapState` at nav-ui.js:551 does not pass `padding` to `easeTo`. Because MapLibre only updates properties you pass, the ~160px top padding set during nav persists for the rest of the session. Symptoms: search pans off-center, `flyToGPS` lands high, KML import bounds look off. Fix: include `padding: { top: 0, bottom: 0, left: 0, right: 0 }` in the restore easeTo.

### A2. `applyReroute` announcedSet filter is wrong and misleading

navigation.js:798 resets `currentManeuverIdx = 0`, then line 805 filters `announcedSet` to keep `idx <= currentManeuverIdx` — i.e., keys for the depart (maneuver 0) of the OLD route, which no longer exists. The comment "Clear only forward maneuvers' thresholds" is the opposite of what the code does. Since no forward old keys are preserved AND no backward keys should match new route indices, the correct behavior is just `announcedSet = {};`.

### A3. `lastAnnouncementTime` not reset on reroute

`applyReroute` clears `speedHistory`, `offRouteHistory`, `announcedSet` (partially), `inOffRouteState`, `lastIndex`, `currentManeuverIdx` — but not `lastAnnouncementTime`. If the user gets a reroute and the next critical voice prompt would naturally fire within 5 seconds of the last pre-reroute announcement, it's suppressed. Minor, but contributes to voice feeling off after reroute. Fix: `lastAnnouncementTime = 0;` in `applyReroute`.

### A4. `lastRerouteTime` not cleared on reroute timeout

In `triggerReroute` (navigation.js:640-646), the 10s timeout flips state back to "navigating" but doesn't clear `lastRerouteTime`. The 15s `REROUTE_COOLDOWN` is computed from `lastRerouteTime`, so after a timeout the user can't trigger a new reroute for another 5 seconds. Low severity (the whole reroute path is fail-soft), but confusing to diagnose. Fix: on timeout, set `lastRerouteTime = 0` or shorten the cooldown-after-failure path.

### A5. Per-tick CSS variable write is dead code

nav-ui.js:453 sets `--nav-overlay-height` as a CSS custom property every tick, but no selector in `style.css` references that variable. Either use it (e.g., to size the padding in CSS) or remove the write; it's layout-thrashy.

### A6. `#sidebar-toggle` at z-index:25 overlays `#nav-overlay` (z-index:18)

Comment at nav-overlay says z:18 "below sidebar (20) so sidebar can overlay nav when open". That's correct, but `#sidebar-toggle` is z:25 — which means the hamburger button sits on top of the nav instruction card in the top-left corner. Visually this is fine (the button is small), but it means touches in that region go to the sidebar toggle, not the nav overlay's `stopPropagation` handler. No functional bug; worth noting for future layering work.

### A7. Dead-reckoning fires voice announcements

`deadReckonTick` (navigation.js:661-675) calls `checkVoice(drSnap)` during GPS outage. This can announce a turn that the user never actually reaches (if GPS is stale for 30s and DR extrapolates them past the turn). Low severity — DR is capped at 30s and accurate extrapolation is rare — but if the user stops moving during GPS outage, DR will still "drive them forward" and announce phantom turns. Consider suppressing voice during DR, or only allowing announcements within `VOICE_NEAR_ANNOUNCE_DISTANCE` of the maneuver.

## Design concerns (not bugs)

- **UI state is split across engine, `window._geographicaLastTrip`, map sources, and DOM.** Every reroute-adjacent bug stems from this split. A single `setActiveRoute(trip)` function that touches all four would eliminate an entire class of future bugs. The fact that four prior fixes touched the engine without touching the map source is strong evidence that the split is the real problem.
- **Padding math is a known footgun in MapLibre.** The one place the code uses padding got it wrong, and the one place that needed to clear it doesn't. Encode the "desired marker position" (percentage) rather than raw pixels, and always clear padding when leaving nav mode.
- **Module-level counters in nav-ui (`rerouteRetries`, `lastNavPaddingTop`, `lastGPSSignature`)** reset only in `stopNavigation`. If nav is entered-exited-entered rapidly (e.g., reroute cascades into arrival), these leak across sessions. Low risk in practice because the affected code paths idempotently overwrite on the next tick, but worth fencing.
- **Voice cadence encodes a single timing model (three tiered thresholds) across all costings and speeds.** A speed-adaptive model (e.g., `time-to-maneuver ≤ 30s` rather than `distance ≤ 800m`) would produce more natural announcements and be easier to tune empirically.

---

**Summary:** all four beta bugs have concrete root causes and all four can be closed in the same change:

1. `VOICE_THRESHOLDS.auto = [500, 50]` (and keep next-after-next attached to the final threshold regardless of count).
2. In `attemptReroute`, after `nav.applyReroute(...)`, update `map.getSource('route').setData(...)` and `window._geographicaLastTrip`.
3. Rewrite `getNavPadding()` to `0.6*vh + overlay.offsetHeight`, and pass zeroed padding in `restoreMapState`'s `easeTo`.
4. CSS: recenter bottom 208/188, compass stays at 162/142. Additionally drop `announcedSet = {};` in `applyReroute` and zero `lastAnnouncementTime`.
