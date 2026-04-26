# Nav distance post-M1 inflation — Exploratory hunter report

**Date:** 2026-04-24
**Hunter:** manzanita (exploratory)

---

## Threads followed

### Thread 1: `distToNext` computation path (navigation.js:481)

Starting at the call site where `distToNext` is computed and passed to `formatDistancePrefix`.

- Step 1: `checkVoice(snap)` at line 461 reads the fresh `snap` from `tick()` → `snapToRoute()`. No mutation between computation and use. `snap` is read-only through the entire `checkVoice` execution.
- Step 2: Line 481: `var distToNext = distanceToManeuver(snap, nextIdx)`. Follows into `distanceToManeuver` at line 421.
- Step 3: `distanceToManeuver` → `distanceToCoordIndex(snap.segmentIndex, snap.t, targetIdx)` where `targetIdx = route.maneuvers[nextIdx].begin_shape_index`. Formula: `cumulativeDistances[targetIdx] - (cumulativeDistances[snap.segmentIndex] + segmentDistances[snap.segmentIndex] * snap.t)`. Mathematically correct.
- Step 4: `distToNext` is never modified after line 481 before being passed to `formatDistancePrefix` at line 513.
- Step 5: Searched for any `Math.max`, `Math.min`, clamp, or direct assignment to `distToNext` after line 481. Found none. The `floor` variable is used ONLY in the fire condition at line 491, not to modify `distToNext`.
- **End state:** `distToNext` is computed correctly from the snap position. No distance-level clamping or flooring of the computed value. Thread terminated — computation is correct given correct inputs. Investigation must shift to WHY the input distance is in the 200ft bucket.

---

### Thread 2: The floor constant as the "minimum" Cameron suspected (navigation.js:52-56, 490-491)

- Step 1: `VOICE_DISTANCE_FLOOR.auto = 75` at line 52-56. Comment: `+25 m. ~+2.6 s buffer at 25 mph`.
- Step 2: Near-tier fires when `!announcedSet[nearKey] && (ttm <= ttmPair[1] || distToNext <= floor)` at line 490-491. For `auto`: `floor = 75m`, `ttmPair[1] = 3s`.
- Step 3: The floor fires at the MAXIMUM value of `distToNext = 75m`. `75m * 3.28084 = 246.06ft`. `Math.round(246.06/100)*100 = Math.round(2.46)*100 = 2*100 = 200`.
- Step 4: The bucket `[150ft, 249ft]` (i.e., `[45.7m, 75.9m]`) maps to "In 200 feet." The floor value of 75m sits INSIDE this bucket. Every near-tier fire triggered by the floor condition lands at `distToNext ≤ 75m = 246ft`, which rounds to 200ft.
- Step 5: The TTM condition fires at `ttm ≤ 3s`. At urban speeds (8-10 m/s), this fires at `distToNext = 3 * 8 = 24m`. `24m * 3.28 = 79ft → 100ft bucket`. But the floor fires FIRST (at 75m > 24m), so for any approach longer than 75m, the floor is always the dominant trigger and the near-tier always says "200 feet."
- Step 6: For M1 specifically, Cameron started navigation with GPS already inside the 75m zone or close enough that the TTM path fired first (~27m → 89ft → "In 100 feet"). This is because Villa Rita's initial position was only ~27-30m from M1's turn node.
- **End state: CONFIRMED BUG F1.** The `VOICE_DISTANCE_FLOOR.auto = 75m` value falls inside the "200 feet" rounding bucket. This IS the "minimum/floor" Cameron suspected. It doesn't clamp `distToNext` directly — it constrains the near-tier to fire only when `distToNext ≤ 75m`. Since 75m = 246ft rounds to 200ft, floor-triggered fires always report "200 feet."

---

### Thread 3: `snapToRoute` / `lastIndex` sticking post-turn (navigation.js:337-366)

- Step 1: `snapToRoute` uses window `[lastIndex - SNAP_WINDOW_BEHIND, lastIndex + SNAP_WINDOW_AHEAD]` = `[lastIndex - 3, lastIndex + 50]`.
- Step 2: `lastIndex` is updated to `best.segmentIndex` at line 356 on every call. No caching or batching.
- Step 3: After a turn, `lastIndex` might be at the pre-turn segment for one tick, but the 50-segment ahead window ensures the post-turn segment is searched. The fallback to full-polyline search at 100m provides a second net.
- Step 4: Heading penalty in `searchSegments` is only applied when `heading !== null && candidates.length > 1`. At turn speed below `HEADING_SPEED_GATE = 3 m/s`, `headingValid = false` → `null` heading → no penalty. After the turn at normal speed, heading aligns with the post-turn segment and correctly disambiguates.
- Step 5: Even if snap were stuck 1-2 segments behind for one tick, `lastIndex` would advance the next tick. The snap error would be transient, not persistent.
- **End state: DEAD END.** Snap lag cannot explain the consistent "200 feet" for every M2, M3, M4. The snap is working correctly.

---

### Thread 4: `findManeuverForSegment` and the early-advance mechanism (navigation.js:408-418, 760)

- Step 1: In `tick()` at line 760, `currentManeuverIdx = findManeuverForSegment(snap.segmentIndex)` runs BEFORE `checkVoice(snap)` at line 835.
- Step 2: `findManeuverForSegment` returns the maneuver where `segIdx >= begin_shape_index && segIdx < end_shape_index`. The moment `snap.segmentIndex` first crosses into M1's range, `currentManeuverIdx` jumps from 0 to 1 on that SAME tick.
- Step 3: `checkVoice` then computes `nextIdx = 1 + 1 = 2` (M2). `distToNext = distanceToManeuver(snap, 2)` = distance from the snap (at M1's entry point, or slightly past it) to M2's `begin_shape_index`.
- Step 4: If M1's leg (from M1.begin_shape_index to M2.begin_shape_index) is ≤ 75m — which is common in dense Phoenix urban routing — then `distToNext ≤ 75m` at the first tick inside M1's range. Near-tier for M2 fires immediately.
- Step 5: `formatDistancePrefix(distToNext)` at this point where `distToNext` = M1 leg length ≈ 50-75m → 164-246ft → rounds to 200ft.
- Step 6: `announcedSet["2-near"] = true` is set. All subsequent ticks approach M2 with `distToNext` going from ~50m to 0, but near-tier is already marked → no re-fire. The "200 feet" utterance plays as the driver closes the remaining distance.
- **End state: CONFIRMED BUG F2.** The early advance + short-leg condition causes near-tier to fire at M1's doorstep for M2, at M2's doorstep for M3, etc. The fire timing FEELS correct (fires just as you cross M1's node) but the distance stated (200ft = the remaining leg) is accurate at fire time yet the utterance plays out as the driver covers most of that leg.

---

### Thread 5: Chain-append `distBetween` anchor (navigation.js:519-522)

- Step 1: At line 520-522:
  ```javascript
  var distBetween = distanceToManeuver(
    { segmentIndex: m.begin_shape_index, t: 0 }, afterIdx
  );
  ```
  `m = route.maneuvers[nextIdx]` — the upcoming turn. `m.begin_shape_index` is the coord index of M-next's turn point.
- Step 2: The fake snap `{ segmentIndex: m.begin_shape_index, t: 0 }` anchors at M-next's START, not at the driver's current position.
- Step 3: `distBetween` = distance from M-next's turn point to M-after-next's turn point = the length of M-next's leg.
- Step 4: The PRIMARY distance prefix at line 513 correctly uses `snap` (driver position). The CHAIN prefix uses a fixed anchor. For a driver 50m before M-next, the chain says "then in [M-next leg length]m" but the driver is actually at [M-next leg length + 50m] from M-after-next.
- Step 5: This is a cross-sibling asymmetry: primary uses live position; chain uses static leg-start.
- **End state: CONFIRMED secondary bug F3.** The chain-append anchor is wrong. It should use `snap` (the driver's position), not `m.begin_shape_index`. Fix: replace `{ segmentIndex: m.begin_shape_index, t: 0 }` with `snap` at line 520.

---

### Thread 6: `distToNext <= 0` NaN guard (navigation.js:482)

- Step 1: `if (distToNext <= 0) return;` — in JavaScript, `NaN <= 0` is `false`. If `distToNext` were NaN (e.g., from `cumulativeDistances[out-of-range-index]`), the guard would NOT catch it.
- Step 2: The downstream `NaN <= floor` and `NaN <= ttmPair[1]` both evaluate to false, so both tiers are silently suppressed with no error output.
- Step 3: Compare to `formatDistancePrefix` at line 223: `!(meters >= DISTANCE_PREFIX_CUTOFF_METERS)` — this form correctly catches NaN.
- **End state: CONFIRMED minor bug F4.** The `distToNext <= 0` guard doesn't catch NaN; it should be `!(distToNext > 0)`. Does not explain Cameron's "200 feet" but is a real correctness gap for corrupted/edge-case route data.

---

### Thread 7: Far-tier `stripBakedDistance` skip under GPS recovery (navigation.js:565-579)

- Step 1: Near-tier at line 499: `text = stripBakedDistance(text)` — always strips.
- Step 2: Far-tier at line 569-578: `stripBakedDistance` is inside `if (!consumeGPSRecoveryFlag())`. If the recovery flag fires (first fresh tick after stale/DR), far-tier skips the strip and speaks the raw Valhalla text verbatim — which may contain baked distances like "In 300 feet, turn right."
- Step 3: Cameron's drive had clear-sky GPS (no DR), so this wouldn't have triggered. But it's a genuine cross-sibling inconsistency.
- **End state: CONFIRMED minor bug F5.** Stripping should happen unconditionally for far-tier, separate from the prefix-suppression decision. Doesn't explain Cameron's bug but is a real defect.

---

## Findings

### F1 — `VOICE_DISTANCE_FLOOR.auto = 75m` always produces "In 200 feet" for floor-triggered near-tier fires

**Location:** `frontend/navigation.js:52–56` (constant); `frontend/navigation.js:490–491` (fire condition)

**What's wrong:** `VOICE_DISTANCE_FLOOR.auto = 75` is the "minimum" Cameron suspected. The floor constrains near-tier to fire only when `distToNext ≤ 75m`. `75m × 3.28084 = 246ft`. `Math.round(246/100)*100 = 200`. The 100-foot rounding bucket [150ft, 249ft] = [45.7m, 75.9m] covers the entire range of possible floor-triggered fires. Every near-tier announcement triggered by the floor condition (rather than the 3s TTM threshold) says "In 200 feet," regardless of the exact `distToNext` value at fire time.

The floor was set to ensure TTS starts before the turn. At 8 m/s (urban speed), `75m / 8 m/s = 9.4 seconds` lead time — far more than the spec's 3-second near threshold. The extra lead time is reasonable for audio completion, but the value lands in a rounding bucket that misrepresents the actual distance.

**Why this matches Cameron's signature:** M1 fired at "In 100 feet" because Cameron started navigation close to M1 (~27-30m), where the TTM condition (`ttm ≤ 3s`) fired first. At 27m, `27 × 3.28 = 89ft → 100ft bucket`. M2, M3, etc. had longer approaches (>75m), so the floor fired first at `distToNext ≤ 75m = 246ft → 200ft` — deterministically for every subsequent turn.

**How to reproduce in test:**
```javascript
// Route: depart at 0m, M1 at 30m, M2 at 105m (75m leg after M1), M3 at 180m
// Start at -30m (30m before M1, inside TTM zone at 8 m/s)
// Drive through: assert M1 near says "In 100 feet"; assert M2 near says "In 200 feet"
// on first tick past M1.begin_shape_index; assert M3 near says "In 200 feet".
```

**Confidence:** HIGH

---

### F2 — Near-tier fires at maneuver-entry for legs ≤ 75m, not while approaching the turn

**Location:** `frontend/navigation.js:760` (`currentManeuverIdx` advance); `frontend/navigation.js:490–491` (floor check in `checkVoice`)

**What's wrong:** In `tick()`, `currentManeuverIdx = findManeuverForSegment(snap.segmentIndex)` runs before `checkVoice(snap)`. The instant `snap.segmentIndex` first enters M1's range, `currentManeuverIdx` becomes 1 and `checkVoice` immediately evaluates `distToNext` to M2. If M1's leg length is ≤ 75m, `distToNext ≤ floor → nearWouldFire = true` on that first tick. The near-tier for M2 fires at M1's doorstep.

`announcedSet["2-near"] = true` is set immediately. For all remaining ticks approaching M2 (from ~65m to 0m), the near check is already marked → no re-fire. The driver hears "200 feet" at M1's turn node, then silence for the remaining 65m to M2.

**Why this matches Cameron's signature:** "Some of those subsequent fires happened when Cameron was actually only ~35 ft / ~10m from the turn." At 8-12 m/s urban speed, the near-tier fires at M1's crossing point (~60-75m from M2). The TTS utterance takes ~1.5-3s to complete, during which the car travels ~15-25m. By the time the utterance finishes, Cameron is at ~40-60m from M2. By the time Cameron perceives it as an imminent cue and processes it, he's at 10-35m. The 5-10× perceived inflation is: [stated 200ft = 61m] / [perceived position ~10m] = 6×.

**How to reproduce in test:** Build a fixture with M1 leg = 65m. Navigate. Assert that the near-tier voice for M2 fires on the FIRST tick that `snap.segmentIndex` enters M1's range — not after any distance into M1.

**Confidence:** HIGH

---

### F3 — Chain-append `distBetween` uses static leg-start anchor instead of driver's position

**Location:** `frontend/navigation.js:520–522`

**What's wrong:**
```javascript
var distBetween = distanceToManeuver(
  { segmentIndex: m.begin_shape_index, t: 0 }, afterIdx
);
```
`m.begin_shape_index` is M-next's turn point (a fixed coordinate), not the driver's position. `distBetween` = M-next leg length (M-next-start → M-after-next-start). The primary prefix at line 513 correctly uses `snap` (driver's live position). The chain prefix uses a static anchor. For a driver 50m before M-next, the chain understates the actual M-after-next distance by 50m.

**Fix:** Replace `{ segmentIndex: m.begin_shape_index, t: 0 }` with `snap` at line 520.

**Why this matches Cameron's signature:** Affects the chain text ("then in X feet") accuracy. Secondary to F1/F2 but contributes to the overall inaccuracy of compound announcements.

**How to reproduce in test:** Route with M1 at 200m, M2 at 80m from M1 (within 500m chain threshold). Driver 50m before M1. Assert chain prefix ≈ 250m (driver to M2), not 80m (M1 leg length).

**Confidence:** HIGH

---

### F4 — `distToNext <= 0` guard fails to catch NaN; silently swallows announcements

**Location:** `frontend/navigation.js:482`

**What's wrong:** `if (distToNext <= 0) return;` — in JavaScript, `NaN <= 0` is `false`. NaN `distToNext` (from out-of-range `begin_shape_index`) bypasses the guard. The downstream tier conditions `NaN <= 3` and `NaN <= 75` are also false, silently suppressing all voice for that maneuver. No log, no error.

Compare to the correct pattern used in `formatDistancePrefix` at line 223: `!(meters >= X)` catches NaN.

**Fix:** Change line 482 to `if (!(distToNext > 0)) return;`

**Confidence:** MEDIUM (edge case, not Cameron's specific drive)

---

### F5 — Far-tier skips `stripBakedDistance` on GPS-recovery tick; speaks raw Valhalla text

**Location:** `frontend/navigation.js:569–579`

**What's wrong:** Near-tier always calls `stripBakedDistance(text)` (line 499). Far-tier wraps both `stripBakedDistance` and `formatDistancePrefix` inside `if (!consumeGPSRecoveryFlag())`. On the first fresh tick after a stale/DR episode, the recovery flag fires, the `if` block is skipped, and the raw Valhalla text (which may contain a baked "In 300 feet, turn right") is spoken verbatim. Stripping should happen unconditionally; only the live-computed prefix should be suppressed.

**Fix:** Move `stripBakedDistance` outside the `if (!consumeGPSRecoveryFlag())` block in the far-tier path.

**Confidence:** MEDIUM (GPS recovery events not present in Cameron's clear-sky drive)

---

## Dead ends

**H1 — Snap window sticking behind after turn:** Ruled out. `lastIndex` updates on every `snapToRoute` call (line 356). The 50-segment ahead window and 100m-fallback search ensure the correct post-turn segment is always found within one tick. No evidence of persistent snap lag.

**H4 — Heading weighting causing wrong post-turn snap:** Ruled out. Below `HEADING_SPEED_GATE = 3 m/s`, heading is invalid and set to `null`; `searchSegments` skips heading scoring when `heading === null`. At normal urban speeds above 3 m/s, heading correctly favors the post-turn segment. No heading-induced snap error.

**H3 — Stale `cumulativeDistances` after reroute:** Ruled out. `precomputeDistances()` is called in both `start()` and `applyReroute()`. The arrays are never mutated between route loads. All `distanceToCoordIndex` calculations are arithmetically correct given the correctly-precomputed arrays.

**H — `distToNext` directly clamped to floor value:** Explicitly searched for any assignment of `floor` to `distToNext` after line 481. None found. The `floor` variable is used ONLY in the fire-condition check at line 491. It does not modify the computed distance.

**H — Multi-leg shape index offset error:** Reviewed `buildRouteData` in `nav-ui.js:255-315`. The `indexAdjust` / `shapeOffset` logic is correct for multi-leg routes. For single-leg routes (Cameron's drive), `indexAdjust = 0`, `shapeOffset = 0`, and all maneuver indices pass through unchanged.

---

## Cross-validation note

My findings F1-F5 independently agree with the holistic and multipass hunters' F1-F5. Three independent passes converge on the same root cause:

- **Primary bug:** `VOICE_DISTANCE_FLOOR.auto = 75m` combined with 100-foot rounding buckets = deterministic "200 feet" for all floor-triggered near-tier fires.
- **Mechanism:** Early `currentManeuverIdx` advance + floor condition = near fires at maneuver-entry for short legs, with distance = leg length at time of fire.
- **Secondary bug (chain anchor):** `distBetween` should use `snap`, not `m.begin_shape_index`.
- **Minor bugs:** NaN guard weakness (F4), far-tier stripBakedDistance skip (F5).

**Fix priority:**
1. Lower `VOICE_DISTANCE_FLOOR.auto` from 75 to ≤ 45m (puts floor-triggered fires in the "100 feet" bucket: 45m × 3.28 = 148ft → 100ft).
2. Fix chain-append anchor: `distanceToManeuver(snap, afterIdx)` instead of the fixed anchor.
3. Fix NaN guard: `if (!(distToNext > 0)) return;`.
4. Fix far-tier strip: unconditional `stripBakedDistance` before the prefix-suppression block.
