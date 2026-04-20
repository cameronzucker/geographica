# Nav Voice TTM (Time-to-Maneuver) — Design Spec

**Date:** 2026-04-20
**Scope:** Replace the distance-threshold voice-announcement model in `frontend/navigation.js` with a time-to-maneuver (TTM) model, plus a close-turn suppression rule that halves announcement count in dense clusters. Deletes the 2026-04-20 band-aid commit `e63f6d9` in the same PR. Closes bug B1 from the 2026-04-20 nav UX remediation.
**Files:** [frontend/navigation.js](../../../frontend/navigation.js) (primary), [frontend/tests/engine/navigation.test.mjs](../../../frontend/tests/engine/navigation.test.mjs) (add TTM matrix, delete band-aid regression guard), possibly [frontend/tests/engine/test_runner.mjs](../../../frontend/tests/engine/test_runner.mjs) (fake-timer helper if not present).
**Related:** Handoff [handoff_20260420_nav_voice_ttm_kickoff.md](../../../../.claude/projects/-home-administrator-Code-geographica/memory/handoff_20260420_nav_voice_ttm_kickoff.md). Composes cleanly with the in-flight [2026-04-21-nav-voice-picker-design.md](2026-04-21-nav-voice-picker-design.md) — voice-picker selects *which* voice speaks, TTM decides *when* to fire; they meet only at the `onVoiceCb` callback boundary, which is unchanged by this spec. Builds on but replaces the band-aid shipped as `e63f6d9`.

## Revision history

- **v1 (2026-04-20)** — Initial design, authored by agent `alder`. Based on a 6-question brainstorm covering close-turn suppression, thresholds, legacy-constant cleanup, speed smoothing, highway exits, and deceleration skew. Each decision locked against field-testing context from the 2026-04-20 Villa Rita → Costco detour run (9 prompts in ~200 ft of driving). Pending 5+ round adversarial review before v2.

---

## 1. Summary

Geographica's turn-by-turn navigation uses three distance thresholds per maneuver (`[800m, 200m, 50m]` originally; band-aided to `[400m, 50m]` on 2026-04-20) to decide when to speak voice prompts. Distance is the wrong unit because it does not encode driving urgency: 800m at 70 mph is 25 seconds of notice (reasonable), but 800m at 15 mph is 2 minutes (the driver forgets before acting). The 2026-04-20 Villa Rita field test produced **up to 9 voice prompts in ~200 ft** of rerouted surface-street driving — past unhelpful, into actively dangerous.

This spec replaces the distance model with a **time-to-maneuver (TTM)** model: `ttm = distToNext / smoothedSpeed`. Announcement thresholds become seconds-of-advance-notice:

- **auto:** `[30s, 3s]` with a 50m distance floor (ensures stopped-at-light-at-maneuver still fires)
- **bicycle:** `[20s, 3s]` with a 30m floor
- **pedestrian:** `[15s, 2s]` with a 15m floor

And adds a **close-turn suppression rule** (D1): on any tick where the near-tier condition is met AND the far-tier has not yet fired for this maneuver, the far-tier is suppressed — the driver hears only the near-tier prompt (which already chains the next-after-next maneuver via preserved `NEXT_AFTER_NEXT_DISTANCE = 500m` logic). This halves announcement rate in post-reroute dense clusters without losing information.

Under this model:

- At highway speed (30 m/s / 67 mph): far fires at 900m, near at 90m. Genuinely useful advance notice.
- At city speed (10 m/s / 22 mph): far fires at 300m, near at 30m (floor → 50m). Matches field-tester expectation ("current bounds are too far out").
- At walking/crawl speed (≤ 3 m/s): TTM goes large; distance floor governs.
- **Villa Rita post-reroute 3-maneuver cluster:** 3 prompts total (one near-tier per maneuver; far suppressed by D1), down from 9.

The 2026-04-20 band-aid (commit `e63f6d9`) — `VOICE_THRESHOLDS = { auto: [400, 50], ... }` — is deleted in the same PR as TTM lands. The existing regression-guard test `B1 band-aid: voice tiers capped at 2 per costing (remove when TTM ships)` is deleted alongside.

## 2. Goals & non-goals

### Goals

- **G1.** Exactly 2 voice prompts per maneuver when the driver enters from outside the far-tier threshold and proceeds through normally (invariant holds at any speed above the speed floor).
- **G2.** Exactly 1 voice prompt per maneuver when the driver enters already inside the near-tier condition (post-reroute or route-start into a close maneuver). Villa Rita close-cluster: 3 maneuvers → 3 prompts.
- **G3.** Zero voice prompts when the driver is stationary beyond the distance floor. No idle chatter at a red light that is far from the next turn.
- **G4.** Near-tier prompt fires when the driver is stationary *at* the next maneuver (e.g., stopped at a light at the turn itself). The distance floor backstops TTM→∞.
- **G5.** Prompt-firing is robust to single-tick GPS outliers (50 m/s spike in a 10 m/s stream must not flip thresholds). Median-of-3 smoothing rejects 1 outlier per window.
- **G6.** Reroute clears all voice state: `announcedSet` AND the speed-sample window. The new route's first prompt fires without suppression from prior state.
- **G7.** Behavior is deterministic: identical `(route, GPS stream)` inputs produce identical announcement counts and timing. No hidden cooldown or randomness.
- **G8.** Composes cleanly with [2026-04-21-nav-voice-picker-design.md](2026-04-21-nav-voice-picker-design.md): voice-picker acts on the `onVoiceCb` callback boundary, which is preserved unchanged.
- **G9.** Mute-state interaction unchanged: when muted, `announcedSet` still populates (so already-crossed TTM points are not re-fired when user un-mutes mid-route).
- **G10.** Test-hook shape (`window._geographicaNavEngineInternals`) updates to expose the new constants/state. Existing test-hook-consumer tests get a clean migration with no silent breakage.

### Non-goals

- **NG1.** Highway-exit 3-tier announcements (Google/Apple-style "in 2 miles / in half a mile / now"). Deferred. If beta-testers complain about missed exits on highway trips, a future spec adds a per-maneuver-type tier override for `ramp / exit_left / exit_right`. Geographica's AREDN / SAR / trail-driving audience is surface-street-heavy; this is not the v1 priority.
- **NG2.** Deceleration anticipation (using predicted-speed-at-maneuver instead of current speed). Deferred. The 50m distance floor masks most of the 1-2 second timing drift from hard braking.
- **NG3.** Changes to `frontend/nav-ui.js`'s voice pipeline. The engine-side `onVoiceCb(text)` contract is preserved exactly — voice-picker's `utterance.voice = chosen` assignment site is untouched.
- **NG4.** Changes to the reroute trigger logic, off-route detection, or arrival geofence. Out of scope.
- **NG5.** Replaying or deduplicating prompts that were queued but not yet spoken when the tab is backgrounded. Web Speech API queuing semantics are handled elsewhere; TTM decides when to *invoke* `onVoiceCb`, not what happens after.
- **NG6.** A "how many prompts remaining" UI indicator. Announcement count is internal to the engine; no UX surface.
- **NG7.** Per-user-preference threshold tuning (e.g., "chatty" vs "terse" voice setting). The voice-picker spec provides voice selection; tier tuning is not in scope for this iteration.

## 3. Architecture overview

TTM is a pure in-engine change. External contract surfaces are unchanged:

```
    GPS service             │ updateGPS(data)              │ onVoiceCb(text)          
    (services/gps)          │ ───────────────▶             │ ───────────────▶        
                            │                              │                          
                            │                              │                          
                            │  ┌────────────────────────┐  │                          
                            │  │  frontend/navigation.js │  │                          
                            │  │                        │  │                          
                            │  │  tick()                │  │                          
                            │  │   ├─ pushSpeedSample   │  │                          
                            │  │   ├─ snapToRoute       │  │                          
                            │  │   └─ checkVoice        │──┼──────────────▶           
                            │  │                        │  │                          
                            │  │  reset() / applyReroute│  │     (frontend/nav-ui.js 
                            │  │   └─ speedSamples=[]   │  │      → Web Speech API    
                            │  │      announcedSet={}   │  │      → voice-picker.js)  
                            │  └────────────────────────┘  │                          
                            │                              │                          
```

All changes are inside the IIFE at [frontend/navigation.js](../../../frontend/navigation.js). No new files. No changes to `nav-ui.js`, `app.js`, or any service.

## 4. Design

### 4.1 Constants

**New (added at the top of the IIFE, alongside the existing constants):**

```js
// Time-to-maneuver (TTM) voice thresholds. Each entry is [far_seconds, near_seconds].
// Announcement timing is computed as ttm = distToNext / smoothedSpeed.
// The distance floor ensures near-tier still fires when stationary at a maneuver.
var VOICE_TTM = {
  auto:       [30, 3],
  bicycle:    [20, 3],
  pedestrian: [15, 2]
};
var VOICE_DISTANCE_FLOOR = {
  auto:       50,
  bicycle:    30,
  pedestrian: 15
};
var MIN_SPEED_FLOOR = 1.0;       // m/s — TTM denominator minimum, prevents divide-by-zero
var SPEED_WINDOW_SIZE = 3;       // median-of-3 rolling window rejects single-tick outliers
```

**Preserved (unchanged):**

```js
var NEXT_AFTER_NEXT_DISTANCE = 500;   // meters — near-tier appends ", then <next>" if chain eligible
```

**Deleted:**

```js
var VOICE_THRESHOLDS = { auto: [400, 50], bicycle: [200, 30], pedestrian: [75, 20] };  // REMOVED
var VOICE_COOLDOWN = 5000;                  // REMOVED — TTM determinism makes cooldown dead weight
var VOICE_SPEED_GATE = 2;                   // REMOVED — MIN_SPEED_FLOOR + distance floor replace
var VOICE_NEAR_ANNOUNCE_DISTANCE = 50;      // REMOVED — subsumed by VOICE_DISTANCE_FLOOR
```

Along with the large BAND-AID block comment (lines 42-57 of `e63f6d9`).

### 4.2 Speed smoothing

**New state** (module-scope, inside the IIFE):

```js
var speedSamples = [];   // rolling buffer of raw GPS speeds, most-recent last; length ≤ SPEED_WINDOW_SIZE
```

**New helpers:**

```js
function pushSpeedSample(s) {
  // Clamp to non-negative; treat NaN / undefined as 0. GPS speed should never be
  // negative, but defense in depth against malformed upstream data.
  var clamped = (typeof s === "number" && s >= 0 && isFinite(s)) ? s : 0;
  speedSamples.push(clamped);
  if (speedSamples.length > SPEED_WINDOW_SIZE) speedSamples.shift();
}

function speedMedian() {
  if (speedSamples.length === 0) return MIN_SPEED_FLOOR;
  var sorted = speedSamples.slice().sort(function (a, b) { return a - b; });
  // For length 3 (steady state): index 1 = true median.
  // For length 1 (first tick): index 0 = only sample.
  // For length 2 (warmup): index 1 = larger-of-two — biases slightly high during
  // the single-tick warmup window; acceptable since TTM is dist/speed, so a
  // biased-high speed yields a biased-low TTM (fires slightly early, not late).
  return sorted[Math.floor(sorted.length / 2)];
}
```

**Integration into `tick()`:** immediately after the existing line `lastSpeed = gpsSpeed;` (around navigation.js:559), add `pushSpeedSample(gpsSpeed);`. The existing `lastSpeed` is retained because `HEADING_SPEED_GATE` and the `buildState()` payload still reference it. Speed smoothing is a separate concern from heading validity.

**Integration into `reset()` and `applyReroute()`:** both paths clear the sample window (`speedSamples = [];`). On reroute, the speed samples from the previous route are physically still valid but are cleared for cohesion with the existing `announcedSet = {}; lastAnnouncementTime = 0;` reset block (both become `announcedSet = {}; speedSamples = [];` — `lastAnnouncementTime` deletes alongside cooldown).

### 4.3 Core algorithm — `checkVoice`

Replaces [frontend/navigation.js:357-411](../../../frontend/navigation.js#L357-L411) in full.

```js
function checkVoice(snap) {
  if (!route || !route.maneuvers) return;

  var nextIdx = currentManeuverIdx + 1;
  if (nextIdx >= route.maneuvers.length) return;

  var m = route.maneuvers[nextIdx];
  var costing = route.costing || "auto";
  var ttmPair = VOICE_TTM[costing] || VOICE_TTM.auto;             // [far_s, near_s]
  var floor = VOICE_DISTANCE_FLOOR[costing] || VOICE_DISTANCE_FLOOR.auto;

  var distToNext = distanceToManeuver(snap, nextIdx);
  var speed = Math.max(speedMedian(), MIN_SPEED_FLOOR);
  var ttm = distToNext / speed;

  var farKey = nextIdx + "-far";
  var nearKey = nextIdx + "-near";

  var nearWouldFire = !announcedSet[nearKey] &&
    (ttm <= ttmPair[1] || distToNext <= floor);
  var farWouldFire = !announcedSet[farKey] && ttm <= ttmPair[0];

  if (nearWouldFire) {
    // D1 suppression: on near-fire, also mark far as announced so it can never
    // fire on a later tick. The driver hears exactly ONE prompt for this
    // maneuver when they are already within near-tier at activation time.
    var text = m.verbal_pre_transition_instruction || m.instruction;

    // Next-after-next chain (preserved from existing behavior — see
    // frontend/navigation.js:396-405 of the current source).
    var afterIdx = nextIdx + 1;
    if (afterIdx < route.maneuvers.length) {
      var distBetween = distanceToManeuver(
        { segmentIndex: m.begin_shape_index, t: 0 }, afterIdx
      );
      if (distBetween <= NEXT_AFTER_NEXT_DISTANCE) {
        text += ", then " + (route.maneuvers[afterIdx].instruction || "");
      }
    }

    announcedSet[nearKey] = true;
    announcedSet[farKey] = true;  // D1 suppression
    if (!muted && onVoiceCb) onVoiceCb(text);
    return;
  }

  if (farWouldFire) {
    announcedSet[farKey] = true;
    if (!muted && onVoiceCb)
      onVoiceCb(m.verbal_transition_alert_instruction || m.instruction);
  }
}
```

**Key differences vs the existing `checkVoice`:**

1. **No `VOICE_COOLDOWN` check.** TTM determinism + D1 suppression make cooldown unnecessary. Rapid-fire near-tier prompts across adjacent maneuvers in a close cluster are information the driver *needs*, not spam.
2. **No `VOICE_SPEED_GATE` check.** Speed=0 yields `speedMedian() → MIN_SPEED_FLOOR = 1.0` yields `ttm = distToNext / 1.0 = distToNext` (as seconds). At typical distances, `ttm > 30s` so far does not fire; at the floor distance (≤ 50m auto), near fires naturally. Speed gating is subsumed by the TTM→∞ semantics.
3. **`announcedSet` keys are `"<idx>-far"` / `"<idx>-near"`** instead of `"<idx>-<tier_num>"`. Self-documenting; test assertions read cleanly.
4. **Near-check runs FIRST.** If both conditions are met simultaneously (e.g., driver rerouted 40m from turn at 10 m/s — TTM = 4s AND dist = 40m, both > and = respectively to near conditions; far-tier 30s-TTM also crossed), we fire near and mark far consumed. D1 suppression is structural, not conditional.
5. **`announce()` helper deleted entirely.** The 10-line function at `navigation.js:343-351` exists only to enforce the cooldown; cooldown is gone, so `onVoiceCb(text)` is called directly with the `muted` check inline.

### 4.4 The `announce()` function — deleted

[navigation.js:343-351](../../../frontend/navigation.js#L343-L351) becomes dead after checkVoice is rewritten. Delete:

```js
function announce(text, key) {
  if (muted || !text || !onVoiceCb) return false;
  var now = Date.now();
  if (now - lastAnnouncementTime < VOICE_COOLDOWN) return false;
  lastAnnouncementTime = now;
  if (key) announcedSet[key] = true;
  onVoiceCb(text);
  return true;
}
```

The `lastAnnouncementTime` state variable (declared around navigation.js:173) also deletes. All references in `reset()` and `applyReroute()` (lines 744 and 842 of current source) drop.

### 4.5 State and reset

**`reset()` — updated:**

```js
function reset() {
  route = null;
  state = "idle";
  lastIndex = 0;
  currentManeuverIdx = 0;
  offRouteHistory = [];
  inOffRouteState = false;
  lastRerouteTime = 0;
  rerouteSeq = 0;
  joinStartTime = 0;
  lastGPS = null;
  lastGPSTime = 0;
  lastValidHeading = 0;
  headingValid = false;
  lastSpeed = 0;
  lastSnap = null;
  drActive = false;
  announcedSet = {};
  // lastAnnouncementTime = 0;  — DELETED alongside VOICE_COOLDOWN
  speedSamples = [];             // NEW
  speedHistory = [];
  segmentDistances = null;
  cumulativeDistances = null;
  if (rerouteTimeoutId) { clearTimeout(rerouteTimeoutId); rerouteTimeoutId = null; }
  stopStaleChecker();
}
```

**`applyReroute()` — updated:**

```js
applyReroute: function (routeData, seq) {
  if (seq !== rerouteSeq) return;
  if (rerouteTimeoutId) { clearTimeout(rerouteTimeoutId); rerouteTimeoutId = null; }

  route = routeData;
  lastIndex = 0;
  currentManeuverIdx = 0;
  offRouteHistory = [];
  inOffRouteState = false;
  announcedSet = {};
  // lastAnnouncementTime = 0;  — DELETED
  speedSamples = [];              // NEW
  speedHistory = [];
  precomputeDistances();

  state = "navigating";
  if (lastGPS) tick(lastGPS);
}
```

### 4.6 Test-hook shape

[navigation.js:891-895](../../../frontend/navigation.js#L891-L895) currently exposes `VOICE_THRESHOLDS`, `VOICE_COOLDOWN`, `VOICE_SPEED_GATE`. Under TTM:

```js
window._geographicaNavEngineInternals = {
  VOICE_TTM: VOICE_TTM,
  VOICE_DISTANCE_FLOOR: VOICE_DISTANCE_FLOOR,
  MIN_SPEED_FLOOR: MIN_SPEED_FLOOR,
  SPEED_WINDOW_SIZE: SPEED_WINDOW_SIZE,
  // Inspect smoothing state for test assertions on outlier rejection:
  _getSpeedSamples: function () { return speedSamples.slice(); }
};
```

The `VOICE_NEAR_ANNOUNCE_DISTANCE` name disappears (never was on the test hook). The removed constants are not re-added under new names — consumer tests must migrate to TTM assertions.

## 5. Derived invariants

These hold by construction of §4.3 and §4.2 and are asserted by the test matrix in §6:

- **I1.** Exactly 2 announcements per maneuver when the driver's entry-point is outside the far-tier threshold and the driver proceeds through at a speed ≥ MIN_SPEED_FLOOR. Holds across all speed regimes because the far threshold is time-normalized.
- **I2.** Exactly 1 announcement per maneuver when the driver's entry-point is already inside the near-tier condition (TTM ≤ near_s OR distToNext ≤ floor). D1 suppression fires far-key along with near-key.
- **I3.** Zero announcements when the driver is stationary and beyond the distance floor. TTM→∞ from speed clamped to 1.0; far threshold not met; floor not met.
- **I4.** Near-tier fires when the driver is stationary ≤ the distance floor from the maneuver (stopped-at-light-at-turn case). Distance floor triggers regardless of TTM.
- **I5.** A single-tick GPS speed outlier (e.g., one 50 m/s sample in a stream of 10 m/s samples) does not cause a TTM threshold to fire earlier than it would have fired in the no-outlier baseline stream. Once `speedSamples` is full (3 samples), median rejects any single outlier. During warmup (1 or 2 samples), an outlier can cause one premature fire per route; `announcedSet` then locks that threshold so the standard "fire-once-per-maneuver-tier" mechanism bounds the damage.
- **I6.** Reroute clears `announcedSet` AND `speedSamples`. Immediate next `tick()` on the new route sees fresh state.
- **I7.** Next-after-next chain (", then <next>") is appended on the near-tier announcement only, never on the far-tier. Preserves existing behavior.
- **I8.** `muted = true` prevents `onVoiceCb` invocation but does NOT prevent `announcedSet` population. Un-mute mid-route does not replay crossed thresholds.

## 6. Test strategy

### 6.1 Unit test matrix — engine

In [frontend/tests/engine/navigation.test.mjs](../../../frontend/tests/engine/navigation.test.mjs), add a new section "TTM voice announcements" that parameterizes over:

- **Speeds:** `{30, 10, 3, 0}` m/s (highway / city / crawl / stopped)
- **Entry distances:** `{500, 80, 40, 10}` m (outside-far / inside-far-outside-near / at-floor / deep-inside-near)
- **Costings:** `{auto, bicycle, pedestrian}` — at minimum, one maneuver scenario per costing to confirm the per-costing constants are plumbed.

Each cell asserts announcement count matches invariants I1–I4. Total matrix: 4 × 4 × 3 = 48 cells; trim to ~12 representative cells if full matrix is cumbersome to hand-author. Use a helper `simulateApproach({speed, entryDist, costing, steps})` that synthesizes GPS ticks and returns `{count, prompts}`.

### 6.2 Outlier rejection test

One test: feed a 1 Hz stream of 10 m/s samples at 300m from maneuver. Inject a single 50 m/s sample at tick T. Assert that the far-tier threshold is crossed (or not) identically to the no-outlier baseline stream. Assert `_getSpeedSamples()` length ≤ SPEED_WINDOW_SIZE and median behavior matches expectation.

### 6.3 Reroute state clearing

Drive an approach that fires one near-tier for maneuver 0. Invoke `applyReroute(newRoute, seq)`. Assert `_getSpeedSamples()` is empty AND a test accessor (or behavioral probe: immediate repeat approach) confirms `announcedSet` is empty. The new route's first maneuver fires normally.

### 6.4 Dense-cluster (Villa Rita synthetic) test

Synthesize a 3-maneuver route with maneuvers spaced 30m apart. Enter the route at 10 m/s, 40m before maneuver 1. Assert:
- Exactly 3 voice prompts fired (one near-tier per maneuver, no far-tier prompts — D1 suppression holds).
- Each prompt uses the `verbal_pre_transition_instruction` text (not `verbal_transition_alert_instruction`).
- Each near-tier prompt includes the ", then <next>" chain because maneuvers are within `NEXT_AFTER_NEXT_DISTANCE = 500m` of each other.

This is the **automated proxy for the Villa Rita field scenario**. It does not substitute for §6.5 below.

### 6.5 Manual field regression gate — ship blocker

**Before merge**, re-drive the Villa Rita → Costco westerly-detour route from the 2026-04-20 field observation. Count voice prompts. Ship criteria:

- **Pass:** ≤ 3 prompts for the rerouted 3-maneuver cluster (vs 9 observed pre-remediation, ~6 observed under band-aid).
- **Fail → investigate:** > 3 prompts. Likely cause is a miscount in the reroute-state-clearing path or a threshold-units bug. Do not re-tune thresholds as a shortcut — root-cause the drift.

Unit tests alone are insufficient for ship sign-off. Per the handoff and the 2026-04-20 nav UX remediation post-mortem, green unit tests coincided with the 9-prompt field disaster. The field re-drive is the ship gate.

### 6.6 Test-hook migration

Existing tests that import `window._geographicaNavEngineInternals.VOICE_THRESHOLDS` fail loudly on undefined — desired. Update the band-aid regression test (`B1 band-aid: voice tiers capped at 2 per costing (remove when TTM ships)`) by deleting it in this PR. Any other cooldown / speed-gate consumers migrate to the new TTM hooks.

## 7. Edge cases

- **E1. Warmup.** On the first GPS tick of a new route, `speedSamples.length === 1`. `speedMedian()` returns that single value. If it's an outlier, one far-tier prompt might fire prematurely; `announcedSet` then locks it. Acceptable: at worst, one premature prompt per route, not per maneuver.
- **E2. GPS never arrives.** If `speedSamples.length === 0`, `speedMedian()` returns `MIN_SPEED_FLOOR`. TTM computed at 1.0 m/s. For a route-start scenario, this just means the far-tier fires at `far_s` meters (e.g., 30m for auto), which matches the distance floor — user hears one prompt at route start. Benign.
- **E3. Driver decelerates sharply approaching maneuver.** TTM denominator drops, pushing the near-tier threshold *inward* in space (closer to the maneuver). Prompt fires slightly later than "ideal." The distance floor backstops: if TTM near-threshold drifts to below the floor, the floor fires near anyway. Max lag is ~1-2 seconds at typical decelerations. D6 acceptance: deferred to a future spec if field testing flags it.
- **E4. Driver accelerates past the far-tier threshold mid-approach.** TTM denominator grows; far-tier threshold moves *outward* in space. If far has already fired for this maneuver, no effect. If not, far fires when TTM crosses the threshold — same logic, no special case.
- **E5. Stopped at a red light within the distance floor of the next turn.** TTM→∞ (speed clamped to 1.0, TTM = e.g. 40m/1 = 40s > 30s far threshold, so far does not fire; but dist = 40m ≤ 50m floor, so near fires via the floor trigger). Correct UX: driver hears "Turn left onto Mulberry" while stopped at the light — they execute the turn when the light changes.
- **E6. Stopped at a red light beyond the distance floor of the next turn (e.g., 80m stationary).** TTM→80s, dist=80m > 50m floor. Nothing fires. Correct — driver is not yet close enough to announce to.
- **E7. Dead-reckoning tick during GPS outage.** `deadReckonTick()` calls `checkVoice(drSnap)` with the dead-reckoned snap. `lastSpeed` from the last real GPS tick is used by DR's extrapolation but `speedMedian()` reads `speedSamples` — these do not update during DR. TTM during DR uses the last-real-median. Acceptable: GPS outage is rare and DR is short-lived (≤30s per `DEAD_RECKON_MAX`).
- **E8. Maneuver with empty `verbal_pre_transition_instruction` and empty `verbal_transition_alert_instruction`.** Fallback to `m.instruction || ""`. Empty-string onVoiceCb: the near-tier logic still calls `onVoiceCb("")` because we did not add a guard — acceptable, the voice-picker / Web Speech API layer is robust to empty strings (preserves existing behavior from current code).
- **E9. Mute toggle mid-maneuver.** `muted` flag checked at announcement time (line `if (!muted && onVoiceCb)`). `announcedSet` is populated unconditionally. Un-muting does NOT re-fire previously suppressed prompts — matches current behavior (I8).

## 8. Band-aid removal — in the same PR

The 2026-04-20 band-aid (commit `e63f6d9`) is removed in the PR that lands TTM. Specifically:

1. **Delete** `VOICE_THRESHOLDS`, `VOICE_COOLDOWN`, `VOICE_SPEED_GATE`, `VOICE_NEAR_ANNOUNCE_DISTANCE` constants and the large BAND-AID block comment (lines 42-67 of the current source).
2. **Delete** the test `B1 band-aid: voice tiers capped at 2 per costing (remove when TTM ships)` in [frontend/tests/engine/navigation.test.mjs](../../../frontend/tests/engine/navigation.test.mjs).
3. **Delete** `lastAnnouncementTime` state variable + all references in `reset()` and `applyReroute()`.
4. **Delete** `announce()` helper function (inlined into checkVoice).
5. **Commit message:** must include "closes B1, removes 2026-04-20 band-aid (`e63f6d9`)" in the body. Per CLAUDE.md conventions, include `Agent: alder` trailer.

Do NOT land TTM without removing the band-aid in the same PR — the two are designed as a unit. Leaving both live simultaneously produces unpredictable interactions (two thresholds systems fighting for who fires first).

## 9. Files changed

- [frontend/navigation.js](../../../frontend/navigation.js) — constants block rewrite, `checkVoice` rewrite, `speedSamples` + helpers added, `announce()` deleted, `reset()` + `applyReroute()` cleanup, test-hook shape update.
- [frontend/tests/engine/navigation.test.mjs](../../../frontend/tests/engine/navigation.test.mjs) — add §6.1–§6.4 tests, delete band-aid regression guard.
- [frontend/tests/engine/test_runner.mjs](../../../frontend/tests/engine/test_runner.mjs) — possibly add fake-timer helper if the TTM tests need fine-grained `Date.now` control (the 2026-04-20 nav-keep-awake post-mortem noted fake-timer infra was partly deferred; if still absent, add it here).

**NOT changed:**

- [frontend/nav-ui.js](../../../frontend/nav-ui.js) — `onVoiceCb` boundary unchanged; voice-picker integration site unaffected.
- [frontend/app.js](../../../frontend/app.js), [frontend/index.html](../../../frontend/index.html), any CSS — no UI surface change.
- `services/gps/` — raw `gpsData.speed` continues to be passed to `updateGPS`; smoothing is engine-internal.

## 10. Process / ship gates

Per the 2026-04-20 nav voice TTM kickoff handoff and the 2026-04-20 nav UX remediation discipline:

1. **This spec (v1)** — written.
2. **Adversarial review — 5+ rounds, at distinct lenses.** At minimum:
   - R1 API correctness / TTM math / edge cases
   - R2 concurrency / timer / reroute interleaving
   - R3 testing sufficiency / coverage gap hunt
   - R4 subagent executability / spec-search-by-content
   - R5 product / UX / field-context framing
   - R6 Codex (via `npx --yes @openai/codex review --uncommitted`) cross-validation — the non-Claude lens that caught 3 MUST-FIX items on the nav-keep-awake spec.
   All rounds write artifacts to `dev/adversarial/2026-04-20-nav-voice-ttm-r{1..6}-<angle>.md`.
3. **Spec v2** — incorporates MUST-FIX findings. Revision history lists rejected findings with rationale.
4. **Implementation plan** via `superpowers:writing-plans`. Tasks with TDD preamble, exact code blocks, review checkpoints. Plan file: `docs/superpowers/plans/2026-04-20-nav-voice-ttm-plan.md`.
5. **Subagent-driven execution** via `superpowers:subagent-driven-development`. Fresh implementer per task; each dispatch includes "You are agent `alder`" so commit trailers stay consistent.
6. **Integration review** pre-merge.
7. **Runtime validation on the live stack** AND **§6.5 field re-drive of Villa Rita → Costco**. This is the ship gate.
8. **Merge `dev` → `main`** only after the field re-drive passes.

## 11. Open questions

None as of v1 — all 10 seed questions from the handoff have been resolved or explicitly deferred (exits → NG1, deceleration → NG2). Adversarial review may surface new ones.

---

**Authored by agent alder. Pending adversarial review before v2.**
