# Nav Voice TTM (Time-to-Maneuver) — Design Spec

**Date:** 2026-04-20
**Scope:** Replace the distance-threshold voice-announcement model in `frontend/navigation.js` with a time-to-maneuver (TTM) model, plus a close-turn suppression rule that halves announcement count in dense clusters and an outlier-clamp on speed smoothing that hardens TTM against GPS multipath. Deletes the 2026-04-20 band-aid commit `e63f6d9` in the same PR. Closes bug B1 from the 2026-04-20 nav UX remediation.
**Files:** [frontend/navigation.js](../../../frontend/navigation.js) (primary), [frontend/tests/engine/navigation.test.mjs](../../../frontend/tests/engine/navigation.test.mjs) (add TTM matrix, delete band-aid regression guard, rename one stale-named existing test).
**Related:** Handoff [handoff_20260420_nav_voice_ttm_kickoff.md](../../../../.claude/projects/-home-administrator-Code-geographica/memory/handoff_20260420_nav_voice_ttm_kickoff.md). Composes cleanly with the in-flight [2026-04-21-nav-voice-picker-design.md](2026-04-21-nav-voice-picker-design.md) — voice-picker selects *which* voice speaks, TTM decides *when* to fire; they meet only at the `onVoiceCb` callback boundary, which this spec preserves exactly. Builds on but replaces the band-aid shipped as `e63f6d9`.

## Revision history

- **v2 (2026-04-20)** — Post-adversarial rewrite. Six-round review (5× Claude subagents at distinct lenses; 1× Codex v0.118.0 cross-validation) surfaced **22 MUST-FIX + 32 SHOULD-FIX + 6 NICE-TO-HAVE** findings, committed as `928a7d1`. Major structural changes:
  - **Distance-semantics hardening** (R1 F1.1) — `distToNext` is now `Math.max(0, distanceToManeuver(...))` with an explicit past-maneuver early-return. Negative distances from U-turns, GPS jitter at maneuver boundaries, and dead-reckoning overshoot can no longer make every TTM threshold trivially true.
  - **Outlier-clamp in speed smoothing** (R3 F3.1) — `pushSpeedSample` now rejects samples whose delta from the prior median exceeds `MAX_SPEED_DELTA_PER_TICK = 15 m/s` (physically implausible). Catches correlated multi-tick GPS multipath errors that a median-of-3 cannot reject.
  - **Route-start scope narrowed** (R6 F6.1, F6.2) — G2 and G4 now apply only after the first post-start movement tick. `start()` does NOT run the TTM pipeline; this keeps nav-ui.js explicitly out of scope and avoids a cross-file refactor. An explicit non-goal NG8 documents this.
  - **Determinism claim narrowed** (R6 F6.4) — G7 now states determinism holds on the direct `tick()` path only; stale-GPS and DR paths remain wall-clock-dependent.
  - **Dead-reckoning does NOT call `checkVoice`** (R2 F2.3) — DR emits position-only updates. Prevents leaped-past-maneuvers from pre-locking distant `announcedSet` keys and silently skipping intermediate prompts. Pre-existing class of bug; TTM closes it.
  - **Reroute-state-clear scope clarified** (R2 F2.2) — §4.5 now explicitly distinguishes the `applyReroute`-success path (full state clear) from the stale-drop path (no state clear). Test §6.3 covers both.
  - **Reroute timeout closure captures `rerouteSeq`** (R2 F2.1) — prevents a late timeout from clobbering a just-applied reroute.
  - **`applyReroute` skips voice on the re-tick** (R1 F1.3) — the immediate `tick(lastGPS)` inside `applyReroute` runs with `speedSamples` cleared; firing voice from a single-sample-warmup window at the most cognitively-loaded moment is the wrong design. Voice on the re-tick is deferred to the next regular GPS tick.
  - **Text guards added** (R1 F1.6) — `onVoiceCb` is not called with empty string; `", then <next>"` chain not appended when `<next>` instruction is empty.
  - **Villa Rita claim qualified** (R5 F5.1) — §1 summary distinguishes the "Villa Rita-class" cluster (3 prompts, D1 fully suppresses far for all 3 maneuvers) from looser clusters (up to 6 prompts, still below the 9-prompt baseline). Honest framing, not hand-wave.
  - **Test strategy expanded** (R3 F3.1, F3.2, F3.4, F3.6, F3.7, F3.12; R4 F4.8) — `simulateApproach` contract pinned as integration-level; fake-timer infra declared out-of-scope for this PR; unknown-costing fallback test added; cooldown-regression guard test added; all 3 costings exercised (not just plumbing); existing stale-named test renamed; §6.4 rewritten in engine-native "upcoming maneuvers" language.
  - **§6.5 field gate instrumented** (R6 F6.5, R5 F5.9) — temporary debug log captures callback timestamp, maneuver index, tier, distToNext, ttm, and whether the fire was on the post-reroute re-tick. Ship criterion measures both callback count AND audible-utterance completion (nav-ui.js cancels mid-utterance, so callback count alone can mask a "chopped audio" outcome).
  - **Line-number citations replaced** (R4 F4.1) — every reference to `navigation.js:<N>` replaced with search-by-content descriptions (function name, nearest surrounding constant, identifying comment). Robust to the TTM rewrite itself shifting line numbers.
  - **Deletion checklist unified and ordered** (R4 F4.2, F4.9) — §8 now lists an 8-step execution order that avoids intermediate-broken states and includes the `_geographicaNavEngineInternals` shape rewrite (else a `ReferenceError` hits on script load).
  - **Rejected findings** (documented below) — R1 F1.2 (stopped-at-light "gap" at 50 < dist < ~80 m): intentional design. Firing "Turn left onto Mulberry" to a stationary driver 55 m from the turn is premature — the driver hasn't started the approach. When motion resumes, TTM fires correctly. The perceived gap is correct UX.
  - Rounds: [dev/adversarial/2026-04-20-nav-voice-ttm-r{1..6}-*.md](../../../dev/adversarial/).
- **v1 (2026-04-20)** — Initial design, commit `2b4f070`. Based on a 6-question brainstorm covering close-turn suppression, thresholds, legacy-constant cleanup, speed smoothing, highway exits, and deceleration skew. Pending 5+ round adversarial review.

### Rejected findings (with rationale)

- **R1 F1.2 (stopped-at-light "dead band" at 50 < dist < ~80 m)** — rejected. Claim: a stationary driver beyond the distance floor but inside the far-tier-at-floor-speed radius hears nothing. Reality: this is intentional. Firing a near-tier prompt to a driver who is stationary 55 m from the turn ("Turn left onto Mulberry") is premature — the driver hasn't begun the approach. When motion resumes, TTM fires the prompt correctly. The alternative (raising the floor to ~80 m) would cause near-tier to fire for *moving* drivers 75 m from the turn, which field testers already flagged as "too far out." Invariant I3 ("zero announcements when stationary beyond the distance floor") is preserved as the correct design.

- **R5 F5.2 (highway chattier than band-aid above 30 mph)** — rejected for v1, logged for beta feedback. Claim: at speeds > 13.3 m/s, TTM's `[30s, 3s]` produces larger distances than the band-aid's `[400m, 50m]`; at 30 m/s highway, far fires at 900m vs band-aid's 400m. Reality: Geographica's AREDN / SAR / trail audience is surface-street-heavy; field testers said the current bounds were "too far out" at surface speeds, which TTM fixes. The highway regression is real but narrow, and the alternative (auto `[20s, 3s]` at 600m highway far) shortens the surface-street advance notice that field testers explicitly want preserved. If beta feedback surfaces highway chattiness, a future spec adds a `maneuver.type`-based override for on-highway segments — same mechanism as the deferred exit 3-tier (NG1).

---

## 1. Summary

Geographica's turn-by-turn navigation uses distance thresholds (`[800m, 200m, 50m]` originally; band-aided to `[400m, 50m]` on 2026-04-20) to decide when to speak voice prompts. Distance is the wrong unit because it does not encode driving urgency: 800 m at 70 mph is 25 s of notice (reasonable), but 800 m at 15 mph is 2 min (the driver forgets before acting). The 2026-04-20 Villa Rita field test produced **up to 9 voice prompts in ~200 ft** of rerouted surface-street driving — past unhelpful, into actively dangerous.

This spec replaces the distance model with a **time-to-maneuver (TTM)** model: `ttm = distToNext / smoothedSpeed`. Announcement thresholds become seconds-of-advance-notice:

- **auto:** `[30s, 3s]` with a 50 m distance floor
- **bicycle:** `[20s, 3s]` with a 30 m floor
- **pedestrian:** `[15s, 2s]` with a 15 m floor

And adds a **close-turn suppression rule** (D1): on any tick where the near-tier condition is met AND the far-tier has not yet fired for this maneuver, the far-tier is suppressed — the driver hears only the near-tier prompt (which already chains the next-after-next maneuver via preserved `NEXT_AFTER_NEXT_DISTANCE = 500 m` logic).

Under this model:

- **Villa Rita-class cluster** (3 maneuvers within a few dozen meters, post-reroute, at city speed): 3 prompts total (one near-tier per maneuver; far suppressed by D1 for all 3), down from 9.
- **Looser cluster** (e.g., 55 m spacing, 80 m entry): up to 6 prompts worst-case — D1 suppression applies only when far and near conditions both meet the same tick, which holds at tight spacing but degrades as spacing grows. Still below the 9-prompt baseline at any realistic geometry.
- **Highway** (30 m/s / 67 mph): far fires at 900 m, near at 90 m — genuinely useful advance notice. **Note:** at speeds above ~30 mph, TTM is more talkative than the band-aid's raw distances; this is accepted as AREDN-audience tradeoff (see Rejected findings above).
- **City / surface** (10 m/s / 22 mph): far fires at 300 m, near at 30 m (floored to 50 m). Matches field-tester expectation ("current bounds are too far out").
- **Walking / crawl** (≤ 3 m/s): TTM becomes large; distance floor governs.

The 2026-04-20 band-aid (commit `e63f6d9`) — `VOICE_THRESHOLDS = { auto: [400, 50], ... }` — and its regression-guard test are removed in the same PR as TTM lands.

## 2. Goals & non-goals

### Goals

- **G1.** Exactly 2 voice prompts per maneuver when the driver enters from outside the far-tier threshold and proceeds through normally, *after the first post-start movement tick* (invariant holds at any speed above the speed floor).
- **G2.** Exactly 1 voice prompt per maneuver when the driver enters already inside the near-tier condition (post-reroute or on a mid-route maneuver whose approach began within near-tier), *measured from the first post-start or post-reroute movement tick*. Villa Rita-class close cluster: 3 maneuvers → 3 prompts.
- **G3.** Zero voice prompts when the driver is stationary beyond the distance floor. TTM → ∞, floor not met, nothing fires — this is the correct UX for "not yet approaching."
- **G4.** Near-tier prompt fires when the driver is stationary ≤ the distance floor from the maneuver (stopped at light at the turn itself), *measured from the first post-start movement tick*. The distance floor backstops TTM → ∞.
- **G5.** Prompt-firing is robust to isolated GPS outlier spikes (single-tick 50 m/s spike in a 10 m/s stream) AND to short runs of correlated multipath errors (e.g., urban-canyon 2-outliers-in-3 window). Median-of-3 rejects single outliers; the new `pushSpeedSample` delta-clamp rejects physically-implausible samples before they enter the window.
- **G6.** Reroute applied successfully clears all voice state (`announcedSet`, `speedSamples`). Reroute stale-drop (seq mismatch) does NOT clear state — the engine continues on the original route. The re-tick inside `applyReroute` emits position updates but does not fire voice (speed window is empty or length-1; voice from a 1-sample warmup is the wrong design).
- **G7.** Behavior is deterministic on the direct `tick()` path: identical `(route, GPS samples, tick-arrival ordering)` inputs produce identical announcement counts and timing. The stale-GPS / dead-reckoning path depends on the real-clock scheduler interval and is explicitly NOT deterministic.
- **G8.** Composes cleanly with [2026-04-21-nav-voice-picker-design.md](2026-04-21-nav-voice-picker-design.md): voice-picker acts on the `onVoiceCb` callback boundary, which is preserved unchanged.
- **G9.** Mute-state interaction unchanged: when muted, `announcedSet` still populates (so already-crossed TTM points are not re-fired when the user un-mutes mid-route).
- **G10.** Test-hook shape (`window._geographicaNavEngineInternals`) updates to expose the new constants/state. Consumer tests migrate cleanly.
- **G11.** Dead-reckoning path is position-only; it does NOT call `checkVoice`. Prevents leaped-past-maneuvers from pre-locking distant `announcedSet` keys.

### Non-goals

- **NG1.** Highway-exit 3-tier announcements. Deferred. If beta-testers surface missed exits on interstate trips, a future spec adds a per-maneuver-type override for `ramp / exit_left / exit_right`.
- **NG2.** Deceleration anticipation. Deferred. The distance floor masks most of the timing drift from hard braking.
- **NG3.** Changes to `frontend/nav-ui.js`'s voice pipeline, to `app.js`, to `index.html`, or to CSS. The engine-side `onVoiceCb(text)` contract is preserved exactly.
- **NG4.** Changes to reroute trigger logic, off-route detection, or arrival geofence. Out of scope.
- **NG5.** Replaying or deduplicating prompts that were queued but not yet spoken when the tab is backgrounded. Web Speech API queuing semantics are handled elsewhere.
- **NG6.** A "how many prompts remaining" UI indicator.
- **NG7.** Per-user-preference threshold tuning (chatty vs terse). Voice-picker provides voice selection; tier tuning is not in scope.
- **NG8. Start-time voice.** `start()` does NOT call `checkVoice(snap)` on route entry. If a user starts navigation already inside the near-tier condition of the first maneuver, voice does not fire until the first post-start movement tick. Rationale: running the TTM pipeline from `start()` would require moving `nav.setMuted(muted)` above `nav.start(routeData)` in `nav-ui.js` (else a muted user could hear the first prompt) and re-ordering `primeSpeech()` / wake-lock acquisition — all of which expand scope into nav-ui.js and violate NG3. Post-start voice-silence for one tick is a small UX cost; most drivers begin motion within a few seconds of starting navigation.
- **NG9. Dead-reckoning voice announcements.** Per G11, DR is position-only. Drivers with stale GPS do not receive voice prompts until GPS recovers. Matches existing behavior; does not regress.

## 3. Architecture overview

TTM is a pure in-engine change. External contract surfaces are unchanged:

```
                                                            
   GPS service       │  updateGPS(data)      │  onVoiceCb(text)  
   (services/gps)    │  ──────────────▶      │  ──────────────▶  
                     │                       │                    
                     │  ┌─────────────────┐  │                    
                     │  │ navigation.js   │  │                    
                     │  │                 │  │                    
                     │  │  tick()         │  │                    
                     │  │   pushSpeedSamp │  │                    
                     │  │   snapToRoute   │  │                    
                     │  │   checkVoice    │──┼────▶              
                     │  │                 │  │                    
                     │  │  deadReckonTick │  │                    
                     │  │   (position-    │  │                    
                     │  │    only; NO     │  │                    
                     │  │    checkVoice)  │  │                    
                     │  │                 │  │                    
                     │  │  reset()        │  │                    
                     │  │  applyReroute() │  │                    
                     │  │   → announcedSet│  │                    
                     │  │   → speedSamples│  │                    
                     │  │                 │  │                    
                     │  └─────────────────┘  │                    
                                                             
```

All changes are inside the IIFE at `frontend/navigation.js`. No new files. No changes to `nav-ui.js`, `app.js`, or any service.

## 4. Design

### 4.1 Constants

**New** (add near the top of the IIFE, directly after `VOICE_THRESHOLDS` is deleted):

```js
// Time-to-maneuver (TTM) voice thresholds. Each entry is [far_seconds, near_seconds].
// Announcement timing is ttm = distToNext / smoothedSpeed.
// The distance floor ensures near-tier still fires when stationary at a maneuver
// (stopped at light at the turn) because TTM → ∞ when speed → 0.
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
var MIN_SPEED_FLOOR = 1.0;              // m/s — TTM denominator minimum
var SPEED_WINDOW_SIZE = 3;              // median-of-3 rolling window
var MAX_SPEED_DELTA_PER_TICK = 15;      // m/s — physically-implausible sample delta
                                        // (>34 mph change in 1s; rejects GPS multipath)
```

**Preserved** (unchanged):

```js
var NEXT_AFTER_NEXT_DISTANCE = 500;   // meters — near-tier appends ", then <next>" if chain eligible
```

**Deleted** (per D3 of the brainstorm; §8 §8 covers the ordering):

- `VOICE_THRESHOLDS` (the band-aid constant and its preceding BAND-AID block comment)
- `VOICE_COOLDOWN`
- `VOICE_SPEED_GATE`
- `VOICE_NEAR_ANNOUNCE_DISTANCE`

### 4.2 Speed smoothing with outlier clamp

**New state** (module-scope, inside the IIFE, declared alongside `announcedSet`):

```js
var speedSamples = [];   // rolling buffer of accepted raw GPS speeds; length ≤ SPEED_WINDOW_SIZE
```

**New helpers:**

```js
function pushSpeedSample(s) {
  // Sanitize malformed upstream data.
  var clamped = (typeof s === "number" && s >= 0 && isFinite(s)) ? s : 0;

  // Outlier clamp (R3 F3.1): reject samples whose delta from the prior median
  // exceeds MAX_SPEED_DELTA_PER_TICK. Catches correlated multi-tick GPS
  // multipath errors (urban canyon, tunnel exit) that median-of-3 cannot
  // reject. Physically implausible — no vehicle accelerates or decelerates
  // by 15 m/s in 1 second. We do NOT clamp on the first sample of a route
  // (no prior median) — acceptable because the first sample feeds directly
  // into the warmup median and is then replaced by subsequent samples.
  if (speedSamples.length >= 1) {
    var priorMedian = speedMedian();
    if (Math.abs(clamped - priorMedian) > MAX_SPEED_DELTA_PER_TICK) {
      return;   // drop; sample does not enter window
    }
  }

  speedSamples.push(clamped);
  if (speedSamples.length > SPEED_WINDOW_SIZE) speedSamples.shift();
}

function speedMedian() {
  if (speedSamples.length === 0) return MIN_SPEED_FLOOR;
  var sorted = speedSamples.slice().sort(function (a, b) { return a - b; });
  // Length 3 (steady state): index 1 = true median.
  // Length 1: index 0 = only sample.
  // Length 2: index 1 = larger-of-two (biases slightly high during 1-tick warmup).
  return sorted[Math.floor(sorted.length / 2)];
}
```

**Integration into `tick()`:** immediately after the existing heading-speed-gate block that sets `lastSpeed = gpsSpeed;`, add `pushSpeedSample(gpsSpeed);`. The existing `lastSpeed` is retained for the heading-validity gate and the `buildState()` payload; speed smoothing is a separate concern.

**Integration into `reset()` and `applyReroute()` (success path only):** `speedSamples = [];`.

### 4.3 Core algorithm — `checkVoice`

Replaces the entire existing `checkVoice` function (search for `function checkVoice(` in `navigation.js`). The replacement:

```js
function checkVoice(snap) {
  if (!route || !route.maneuvers) return;

  var nextIdx = currentManeuverIdx + 1;
  if (nextIdx >= route.maneuvers.length) return;

  var m = route.maneuvers[nextIdx];
  var costing = route.costing || "auto";
  var ttmPair = VOICE_TTM[costing] || VOICE_TTM.auto;
  var floor = VOICE_DISTANCE_FLOOR[costing] || VOICE_DISTANCE_FLOOR.auto;

  // R1 F1.1: distanceToManeuver can return negative on overshoot / U-turn /
  // GPS jitter at maneuver boundaries. A negative value would make every
  // TTM threshold trivially true, firing prompts for wrong maneuvers.
  var rawDist = distanceToManeuver(snap, nextIdx);
  var distToNext = Math.max(0, rawDist);
  if (distToNext <= 0) {
    // Driver is AT or past the maneuver — let findManeuverForSegment()
    // advance currentManeuverIdx on the next tick. Do not fire.
    return;
  }

  var speed = Math.max(speedMedian(), MIN_SPEED_FLOOR);
  var ttm = distToNext / speed;

  var farKey = nextIdx + "-far";
  var nearKey = nextIdx + "-near";

  var nearWouldFire = !announcedSet[nearKey] &&
    (ttm <= ttmPair[1] || distToNext <= floor);
  var farWouldFire = !announcedSet[farKey] && ttm <= ttmPair[0];

  if (nearWouldFire) {
    // Near-tier fire. D1 suppression also marks far as announced so it
    // cannot fire on a later tick for this maneuver.
    var text = m.verbal_pre_transition_instruction || m.instruction || "";

    // Next-after-next chain (preserved from existing behavior).
    var afterIdx = nextIdx + 1;
    if (afterIdx < route.maneuvers.length) {
      var distBetween = distanceToManeuver(
        { segmentIndex: m.begin_shape_index, t: 0 }, afterIdx
      );
      if (distBetween <= NEXT_AFTER_NEXT_DISTANCE) {
        var afterText = route.maneuvers[afterIdx].instruction || "";
        // R1 F1.6: only append the chain if the next-after-next has a
        // non-empty instruction. Never produce "..., then " with no content.
        if (afterText) text += ", then " + afterText;
      }
    }

    announcedSet[nearKey] = true;
    announcedSet[farKey] = true;  // D1 suppression
    // R1 F1.6: never call onVoiceCb with an empty string.
    if (!muted && text && onVoiceCb) onVoiceCb(text);
    return;
  }

  if (farWouldFire) {
    var farText = m.verbal_transition_alert_instruction || m.instruction || "";
    announcedSet[farKey] = true;
    if (!muted && farText && onVoiceCb) onVoiceCb(farText);
  }
}
```

**Key differences from the existing `checkVoice`:**

1. **No `VOICE_COOLDOWN` check.** TTM determinism + D1 suppression make cooldown redundant. Rapid-fire near-tier prompts across adjacent maneuvers in a close cluster are information the driver *needs*.
2. **No `VOICE_SPEED_GATE` check.** Speed → 0 yields `speedMedian() → MIN_SPEED_FLOOR` yields `ttm = distToNext / 1.0` (seconds). At typical distances, `ttm > 30s` so far does not fire; at the floor distance (≤ 50m auto), near fires via the floor. Speed gating is subsumed by TTM → ∞ semantics.
3. **Near-check runs FIRST.** If both conditions are met simultaneously (D1 case), we fire near and mark far consumed.
4. **Distance clamp and past-maneuver early-return** (R1 F1.1) are new.
5. **Text guards** (R1 F1.6): empty-string and ", then <empty>" never fire.
6. **`announce()` helper deleted** (§4.4).

### 4.4 The `announce()` helper — deleted

Search for `function announce(text, key)` in navigation.js. Delete the function in full. The `lastAnnouncementTime` state variable declared near the other voice-state variables (`announcedSet`, `muted`) also deletes.

### 4.5 State and reset

**`reset()` — updated:** Remove `lastAnnouncementTime = 0;`. Add `speedSamples = [];` near the other voice-state resets. All other resets unchanged.

**`applyReroute()` (success path only) — updated:**

```js
applyReroute: function (routeData, seq) {
  // R2 F2.1 / F2.2: stale-drop path does NOT clear state. The engine
  // continues on the original route. Only the success path clears.
  if (seq !== rerouteSeq) return;
  if (rerouteTimeoutId) { clearTimeout(rerouteTimeoutId); rerouteTimeoutId = null; }

  route = routeData;
  lastIndex = 0;
  currentManeuverIdx = 0;
  offRouteHistory = [];
  inOffRouteState = false;
  announcedSet = {};
  speedSamples = [];              // NEW (R1 F1.3)
  speedHistory = [];
  precomputeDistances();

  state = "navigating";

  // R1 F1.3: the immediate re-tick below runs with speedSamples empty.
  // Voice from a 1-sample warmup at the most cognitively-loaded moment
  // (driver just rerouted) is the wrong design. Defer voice to the next
  // regular GPS tick. Position updates DO emit normally.
  if (lastGPS) {
    tickNoVoice(lastGPS);
  }
}
```

Where `tickNoVoice(gpsData)` is a wrapper that invokes the same tick path but passes a flag into `checkVoice` to skip firing (OR — simpler — temporarily sets a module-level `suppressVoiceOnThisTick = true` flag that `checkVoice` checks and resets). Implementation detail: the plan will pick whichever is cleaner. The observable behavior is what the spec constrains.

**`reroute timeout` closure — updated** (R2 F2.1):

```js
function triggerReroute(lat, lng) {
  var now = Date.now();
  if (now - lastRerouteTime < REROUTE_COOLDOWN) return;
  lastRerouteTime = now;
  state = "rerouting";
  rerouteSeq++;
  var scheduledSeq = rerouteSeq;   // R2 F2.1: capture at scheduling time

  rerouteTimeoutId = setTimeout(function () {
    rerouteTimeoutId = null;
    // Only reset if the seq we captured still matches — prevents a late
    // timeout from clobbering a just-applied reroute's state.
    if (scheduledSeq !== rerouteSeq) return;
    if (state === "rerouting") {
      state = "navigating";
      offRouteHistory = [];
      inOffRouteState = false;
      lastRerouteTime = 0;
    }
  }, REROUTE_TIMEOUT);
  // ... rest of triggerReroute unchanged
}
```

**`deadReckonTick` — updated** (R2 F2.3, G11): remove the `checkVoice(drSnap)` call. DR becomes position-only:

```js
function deadReckonTick() {
  if (state === "idle" || state === "arrived") return;
  if (!lastSnap) return;
  var elapsed = Date.now() - lastGPSTime;
  if (elapsed < GPS_STALE_TIMEOUT) return;
  var drSnap = deadReckon(elapsed);
  if (!drSnap) return;
  drActive = true;
  currentManeuverIdx = findManeuverForSegment(drSnap.segmentIndex);
  // NO checkVoice — DR is position-only. See NG9 / G11.
  emitUpdate(buildState(drSnap, true));
}
```

### 4.6 Test-hook shape

Search for `window._geographicaNavEngineInternals` in navigation.js. The replacement exposes the new constants and state, drops the deleted ones. If the script loads without the old shape being rewritten, any existing test that references `VOICE_COOLDOWN` hits a `TypeError: Cannot read property of undefined` on the test's own access — desired, forces migration.

```js
window._geographicaNavEngineInternals = {
  VOICE_TTM: VOICE_TTM,
  VOICE_DISTANCE_FLOOR: VOICE_DISTANCE_FLOOR,
  MIN_SPEED_FLOOR: MIN_SPEED_FLOOR,
  SPEED_WINDOW_SIZE: SPEED_WINDOW_SIZE,
  MAX_SPEED_DELTA_PER_TICK: MAX_SPEED_DELTA_PER_TICK,
  _getSpeedSamples: function () { return speedSamples.slice(); },
  _getAnnouncedKeys: function () { return Object.keys(announcedSet).sort(); }
};
```

## 5. Derived invariants

Updated from v1 per scope-narrowing decisions. These hold by construction and are asserted by §6:

- **I1.** Exactly 2 announcements per maneuver when the driver's entry-point is outside the far-tier threshold, the driver proceeds through at speed ≥ MIN_SPEED_FLOOR, *and* at least one post-start movement tick has occurred.
- **I2.** Exactly 1 announcement per maneuver when the driver's entry-point is already inside the near-tier condition (TTM ≤ near_s OR distToNext ≤ floor), *measured after the first post-start or post-reroute movement tick*.
- **I3.** Zero announcements when the driver is stationary beyond the distance floor.
- **I4.** Near-tier fires when the driver is stationary ≤ the distance floor from the maneuver, *measured after the first post-start movement tick*.
- **I5.** Isolated single-tick GPS speed outlier does not cause any TTM threshold to fire earlier than the no-outlier baseline. Correlated 2-outliers-in-3 window attacks are rejected by the `MAX_SPEED_DELTA_PER_TICK` pre-filter: outlier samples never enter the window, so median cannot be corrupted.
- **I6.** Reroute success path clears `announcedSet` AND `speedSamples`. Reroute stale-drop (seq mismatch) clears neither; engine continues on original route. The immediate re-tick inside `applyReroute` emits position updates but does NOT fire voice.
- **I7.** Next-after-next chain (", then <next>") is appended on the near-tier announcement only. Never appended with empty next instruction.
- **I8.** `muted = true` prevents `onVoiceCb` invocation but does NOT prevent `announcedSet` population. Un-muting does not replay crossed thresholds.
- **I9.** Dead-reckoning does not call `checkVoice`. DR emits position-only updates.
- **I10.** Past-maneuver early-return: when `distanceToManeuver(snap, nextIdx) ≤ 0`, `checkVoice` returns without firing or mutating `announcedSet`.

## 6. Test strategy

### 6.1 Unit test matrix — engine

In `frontend/tests/engine/navigation.test.mjs`, add a new section "TTM voice announcements" that parameterizes over:

- **Speeds:** `{30, 10, 3, 0}` m/s
- **Entry distances:** `{500, 80, 40, 10}` m
- **Costings:** `{auto, bicycle, pedestrian}` — **all three are exercised** in the matrix, not merely plumbing-tested (R3 F3.12). Bicycle's floor interaction at 5 m/s and pedestrian's floor at 1.5 m/s are distinct from auto's and must be asserted directly.

Each cell asserts announcement count and timing match invariants I1-I10. **Full matrix is 4 × 4 × 3 = 48 cells; minimum coverage is:**

- Every invariant I1-I10 is exercised by ≥ 1 cell (map published in a comment at the top of the test file).
- Per-costing: ≥ 4 cells covering (speed-floor-dominated, TTM-dominated, stationary-within-floor, stationary-beyond-floor).

### 6.2 Outlier rejection — three scenarios

- **Single-tick outlier** (preserved): inject one 50 m/s sample in a 10 m/s stream. Assert thresholds fire identically to baseline.
- **Correlated 2-outliers-in-3** (R3 F3.1 closer): inject two 50 m/s samples in a row in a 10 m/s stream. Assert: `_getSpeedSamples()` shows the outliers were REJECTED at the pre-filter (speedSamples remains `[10, 10, 10]`, not `[50, 50, 10]`). Assert thresholds fire identically to baseline.
- **Gradual acceleration bypass** (R3 F3.1 extra): feed a legitimate ramp 10 → 12 → 14 → 16 m/s (2 m/s increments). Assert all samples are ACCEPTED (not rejected by the 15 m/s delta clamp — the delta is 2 per tick).

### 6.3 Reroute state-clear — success and stale-drop

- **Success path:** Apply a reroute with matching seq. Assert `_getSpeedSamples()` returns empty. Assert `_getAnnouncedKeys()` returns empty. Assert that a subsequent tick that crosses a near-tier threshold fires voice normally.
- **Stale-drop path:** Apply a reroute with seq = 999 (mismatch). Assert the old `announcedSet` keys are preserved (engine still on original route). Assert `_getSpeedSamples()` is unchanged from pre-`applyReroute` call.
- **Re-tick voice-silence:** Apply a successful reroute when `lastGPS` is set. Assert no voice fires on the immediate re-tick inside `applyReroute`. Assert voice DOES fire on the first regular subsequent `updateGPS()` call if a threshold is crossed.

### 6.4 Dense-cluster (Villa Rita synthetic) test — engine-native framing

Per R6 F6.3: "3 maneuvers" in product-language is ambiguous against the engine convention of `nextIdx = currentManeuverIdx + 1` where `maneuver[0]` is the depart/start maneuver and the first spoken is `maneuver[1]`.

Synthesize a route with **4 maneuvers total**: `[depart, turn1, turn2, destination]`, where `turn1` and `turn2` are spaced 30 m apart and the simulated vehicle enters the route snapped 40 m before `turn1` at 10 m/s. Assert:

- Exactly 3 voice prompts fired (one near-tier for each spoken maneuver: `turn1`, `turn2`, `destination`; no far-tier prompts — D1 suppression holds for all 3).
- Each prompt uses `verbal_pre_transition_instruction` text (not `verbal_transition_alert_instruction`).
- Each near-tier prompt includes the `", then <next>"` chain when the next-after-next is within `NEXT_AFTER_NEXT_DISTANCE = 500 m`.

### 6.5 Manual field regression gate — ship blocker

Before merge, re-drive the Villa Rita → Costco westerly-detour route from the 2026-04-20 field observation. Ship criteria:

- **Callback-count criterion:** ≤ 3 engine `onVoiceCb` invocations for the 3-maneuver post-reroute cluster.
- **Audible-utterance criterion** (R6 F6.5): ≤ 3 fully spoken utterances for the cluster, with NO mid-utterance cancellation observed (nav-ui.js calls `speechSynthesis.cancel()` before each new `speak()`, so 3 callbacks within 3 seconds can still sound like chopped audio — we measure both).

**Instrumentation** (R5 F5.9): add a temporary debug log in the spec v2 implementation PR that captures, for each `onVoiceCb` invocation: `{ timestamp, maneuverIdx, tier, distToNext, ttm, onRerouteRetick }`. Remove the log in a follow-up PR after the field drive validates. This is the evidence gap that let the band-aid's "too far out" ship without catching the 9-prompt disaster; closing it is a one-time instrumentation cost.

Ship decision flow:
- Both criteria pass → merge dev → main.
- Only callback passes, audible fails → do NOT ship. File a follow-up ticket for nav-ui.js queue-not-cancel behavior; that's a different spec.
- Callback fails → do NOT ship. Root-cause before re-tuning thresholds.

### 6.6 Other targeted tests

- **Cooldown-regression guard** (R3 F3.7): fire two near-tier prompts for adjacent maneuvers within 100 ms of engine time. Assert BOTH `onVoiceCb` invocations fire. If a later refactor silently reintroduces cooldown (common "safety net" mistake), this test fails loudly.
- **Unknown-costing fallback** (R3 F3.6): set `route.costing = "truck"` (not in VOICE_TTM). Assert engine falls back to `auto` thresholds without crashing.
- **Costing-key sanity lint** (R3 F3.6): assert `Object.keys(VOICE_TTM).sort()` === `Object.keys(VOICE_DISTANCE_FLOOR).sort()`. Catches typos at script load.
- **Past-maneuver early-return** (R1 F1.1, I10): mock `distanceToManeuver` to return `-5`. Assert `checkVoice` returns without firing and without mutating `announcedSet`.
- **DR-no-voice** (R2 F2.3, I9): force a stale-GPS state that triggers `deadReckonTick`. Assert NO `onVoiceCb` invocation, even if DR's extrapolated position crosses a TTM threshold.

### 6.7 Fake-timer infra

Declared **out-of-scope** for this PR (R3 F3.4). The TTM test matrix controls the GPS stream directly; tests can synthesize a clock by passing fake `Date.now()` values through a test hook or by controlling the stale-checker's interval registration. If a future spec introduces a clock-dependent test need not covered by this approach, fake-timer infra can be added then.

## 7. Edge cases

- **E1. Warmup.** On the first GPS tick of a new route, `speedSamples.length === 1`. `speedMedian()` returns that single value. If it's physically plausible (`MAX_SPEED_DELTA_PER_TICK` clamp bypassed for the first sample), it enters the window normally. Benign.
- **E2. GPS never arrives.** `speedSamples.length === 0`, `speedMedian()` returns `MIN_SPEED_FLOOR`. TTM = distToNext at 1.0 m/s. For a 900 m maneuver, TTM = 900 s, no fire. For a 30 m maneuver, distance floor triggers near. Benign.
- **E3. Driver decelerates sharply.** Speed denominator drops; near-threshold moves inward in space. Distance floor backstops. Max lag ~1-2 seconds.
- **E4. Driver accelerates past the far-tier threshold.** No special case — if far fired, no effect; if not, far fires when TTM crosses.
- **E5. Stopped at a red light ≤ distance floor.** TTM→∞ (speed clamped), dist ≤ floor → near fires. Driver hears "Turn left onto Mulberry" while stopped; executes when the light changes.
- **E6. Stopped at a red light > distance floor.** TTM→∞ (after warmup), dist > floor. Nothing fires. Correct — see Rejected findings for rationale.
- **E7. Dead-reckoning tick during GPS outage.** `deadReckonTick` does NOT call `checkVoice` (G11). DR emits position-only updates.
- **E8. Empty verbal instructions.** `onVoiceCb` not called with empty string; `", then <empty>"` chain not appended.
- **E9. Mute toggled mid-maneuver.** `muted` checked at announce-time; `announcedSet` still populates. Un-mute does NOT re-fire.
- **E10. Reroute stale-drop.** `applyReroute` with seq mismatch returns early without mutating state. `announcedSet` and `speedSamples` preserved; engine continues on original route.
- **E11. Past-maneuver distance.** `distanceToManeuver` returns ≤ 0 (U-turn, GPS jitter, overshoot). `checkVoice` clamps to 0 and returns without firing. `findManeuverForSegment` advances `currentManeuverIdx` on the next tick naturally.
- **E12. Reroute re-tick with empty speed window.** `applyReroute` clears `speedSamples`, then invokes `tickNoVoice(lastGPS)`. Position updates emit; no voice fires. First voice fires on the next real `updateGPS`.

## 8. Band-aid removal — in the same PR, in this order

Execute these edits in sequence to avoid intermediate broken states (R4 F4.9). Each step individually preserves load-time correctness.

1. **Add new constants** (`VOICE_TTM`, `VOICE_DISTANCE_FLOOR`, `MIN_SPEED_FLOOR`, `SPEED_WINDOW_SIZE`, `MAX_SPEED_DELTA_PER_TICK`) near the existing constants block. Do NOT delete anything yet.
2. **Add new state and helpers** (`speedSamples`, `pushSpeedSample`, `speedMedian`). No callers yet.
3. **Wire `pushSpeedSample` into `tick()`** right after `lastSpeed = gpsSpeed;`. Old `checkVoice` still runs; no behavioral change.
4. **Rewrite `checkVoice`** in full per §4.3. Old constants (`VOICE_THRESHOLDS`, `VOICE_COOLDOWN`, `VOICE_SPEED_GATE`, `VOICE_NEAR_ANNOUNCE_DISTANCE`) are still referenced by `announce()` but NOT by the new `checkVoice`.
5. **Remove `deadReckonTick`'s `checkVoice(drSnap)` call** per §4.5.
6. **Rewrite `applyReroute()`** per §4.5 (capture scheduledSeq, clear speedSamples, invoke tickNoVoice for the re-tick). Rewrite `triggerReroute`'s timeout closure per §4.5.
7. **Delete the `announce()` helper function** and its `lastAnnouncementTime` state variable (and the reset()-line that sets it). No other caller remains — steps 4 and 5 removed the last callers.
8. **Delete the band-aid constants** (`VOICE_THRESHOLDS`, `VOICE_COOLDOWN`, `VOICE_SPEED_GATE`, `VOICE_NEAR_ANNOUNCE_DISTANCE`) and the BAND-AID block comment. **Rewrite `window._geographicaNavEngineInternals`** per §4.6 in the SAME edit to avoid load-time `ReferenceError` (R4 F4.2).
9. **Rename the existing test** `applyReroute clears announcedSet and lastAnnouncementTime` (in `navigation.test.mjs`) to `applyReroute clears announcedSet and speedSamples`, and update its assertion body to match (R4 F4.8).
10. **Delete the regression-guard test** `B1 band-aid: voice tiers capped at 2 per costing (remove when TTM ships)` from `navigation.test.mjs`.

**Commit message on the final PR commit** must include the phrase `closes B1, removes 2026-04-20 band-aid (e63f6d9)` in the body, with `Agent: <moniker>` trailer per CLAUDE.md. The plan (subagent-driven-development) can split these 10 steps across multiple commits or collapse into one — that's a plan-author's call — but the final PR's concluding commit must name B1 closure.

## 9. Files changed

- **`frontend/navigation.js`** — constants block rewrite (steps 1, 8); `pushSpeedSample` + `speedMedian` helpers (step 2); `tick()` integration (step 3); `checkVoice` rewrite (step 4); `deadReckonTick` voice-removal (step 5); `applyReroute` + `triggerReroute` updates (step 6); `announce()` deletion (step 7); `_geographicaNavEngineInternals` rewrite (step 8).
- **`frontend/tests/engine/navigation.test.mjs`** — add §6.1-§6.6 tests; rename the stale-named reroute test (step 9); delete the B1 regression guard (step 10).

**Not changed:**

- `frontend/nav-ui.js` — `onVoiceCb` boundary preserved (NG3). Voice-picker integration site untouched.
- `frontend/app.js`, `frontend/index.html`, any CSS — no UI surface change.
- `services/gps/` — raw `gpsData.speed` continues to be passed; smoothing is engine-internal.

## 10. Process / ship gates

1. ✅ **Spec v1** — committed as `2b4f070`.
2. ✅ **Adversarial review — 6 rounds** — committed as `928a7d1`. 60 total findings; 22 MUST-FIX; 1 rejected with rationale; remainder accepted and incorporated into v2.
3. ✅ **Spec v2** (this document).
4. **Implementation plan** via `superpowers:writing-plans`. Tasks with TDD preamble, exact code blocks matching §4.3 / §4.5, review checkpoints. Plan file: `docs/superpowers/plans/2026-04-20-nav-voice-ttm-plan.md`.
5. **Subagent-driven execution** via `superpowers:subagent-driven-development`. Fresh implementer per task; each dispatch includes "You are agent `<moniker>`" so commit trailers stay consistent.
6. **Integration review** pre-merge (superpowers:code-reviewer or `codex review --base main`).
7. **Runtime validation on the live stack** AND **§6.5 field re-drive of Villa Rita → Costco**. This is the ship gate. Both the callback-count and audible-utterance criteria must pass.
8. **Merge `dev` → `main`** only after field re-drive passes. release-please handles version bump.

## 11. Open questions

None as of v2. All 22 MUST-FIX findings from the adversarial review are either incorporated or rejected with rationale in the Revision history. Spec is ready for plan-writing.

---

**Authored by agent alder. v2 post 6-round adversarial review.**
