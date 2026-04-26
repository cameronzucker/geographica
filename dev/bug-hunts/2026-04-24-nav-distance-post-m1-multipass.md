# Nav distance post-M1 inflation — Multipass hunter report

**Date:** 2026-04-24
**Hunter:** manzanita (multipass)

---

## Pass 1: Contract violations

### `VOICE_DISTANCE_FLOOR` violates its stated contract

**Location:** `frontend/navigation.js:52–56` (constant); `:490–491` (use in `checkVoice`)

The comment at line 53 reads: `// +25 m. ~+2.6 s buffer at 25 mph fast voice / +1.2 s slow voice.`

The implied contract: "The floor provides a buffer of ~1–3 seconds above the TTM near-tier threshold, so TTS begins before the driver reaches the turn." At 25 mph (11.2 m/s), the TTM near-tier fires at `3s × 11.2 = 33.6m`. The floor is 75m. That gap is `(75 − 33.6) / 11.2 = 3.7 seconds` of extra lead — not "~2.6 s" as commented. At 20 mph (8.9 m/s) the gap is `(75 − 26.7) / 8.9 = 5.4 seconds`.

The real contract breach: the floor fires near-tier at 75m from the turn, and `formatDistancePrefix(75m, imperial)` returns "In 200 feet" (75 × 3.28084 = 246ft → `Math.round(246/100)*100 = 200`). The near-tier is supposed to feel like an *imminent* cue ("turn soon") but is firing 246 feet away and saying "200 feet." At urban speeds this is 7–10 seconds before the turn — the same order of magnitude as the far-tier cue.

The contract of the near-tier, per the TTM spec (`near_seconds = 3`), is "fire when ~3 seconds to the turn." The floor overrides this for any approach where `distToNext` drops below 75m while `speed` is above `~1 m/s`, producing a near-tier fire at 2–10× the intended distance.

### `distanceToManeuver` does not document its sign semantics

**Location:** `frontend/navigation.js:421–425`

```javascript
function distanceToManeuver(snap, maneuverIdx) {
  if (maneuverIdx >= route.maneuvers.length) return 0;
  var targetIdx = route.maneuvers[maneuverIdx].begin_shape_index;
  return distanceToCoordIndex(snap.segmentIndex, snap.t, targetIdx);
}
```

The function can return a negative value when the snap point is past `targetIdx` (driver overshot). `checkVoice` guards against this at line 482 (`if (distToNext <= 0) return;`), but `buildState` at line 689 stores `dToNext` directly into `nextM.distanceTo` without a negative guard. The UI (`instrDist`) would then display a negative distance. Minor contract gap — not directly related to Cameron's bug, but could cause confusing displays during GPS jitter at a maneuver boundary.

---

## Pass 2: Cross-sibling pattern deviations

### Near-tier fires via floor; chain-append computes distance from M-start, not from driver

**Location:** `frontend/navigation.js:518–522`

The near-tier primary distance prefix uses the driver's live snap (correct):
```javascript
var distToNext = distanceToManeuver(snap, nextIdx);   // driver's position
var nearPrefix = formatDistancePrefix(distToNext, ...);
```

The chain-append secondary distance uses a **fixed anchor at M-next's begin_shape_index** (wrong):
```javascript
var distBetween = distanceToManeuver(
  { segmentIndex: m.begin_shape_index, t: 0 }, afterIdx
);
```

Here `m = route.maneuvers[nextIdx]`. So `m.begin_shape_index` is the turn point for M-next — the START of M-next's leg, not the driver's position. The chain says "then in X feet" where X = length of M-next's leg (M-next-start → M-after-next-start), not the distance from the driver to M-after-next.

**Cross-sibling violation:** The two prefix computations in the same function use different anchors. The primary uses `snap` (driver position). The chain uses `m.begin_shape_index` (the fixed turn point). They should both anchor on the driver's position.

**Example of error:** Driver is 27m before M1 (far-tier fired; now approaching near-tier zone). M1 leg is 80m. Chain says "then in 80m (~262ft → 300 feet) turn left" but the driver is actually 27 + 80 = 107m from M2 (351 feet). The chain understates the distance by 27m. In the "200 feet" scenario (M1 leg ≤ 75m, near fires immediately upon M1 entry), the error is smaller but the chain can still report a leg-length distance when the driver is at the leg start.

**Confidence:** HIGH. The asymmetry between `snap` and `m.begin_shape_index` as anchors is a genuine cross-sibling pattern deviation.

### Far-tier strips baked distance only when prefix is added; near-tier always strips

**Location:** `frontend/navigation.js:569–579` (far-tier) vs `:499` (near-tier)

Near-tier:
```javascript
text = stripBakedDistance(text);  // always strips
```

Far-tier:
```javascript
if (!consumeGPSRecoveryFlag()) {
  farText = stripBakedDistance(farText);  // strips only when prefix is added
  var farPrefix = formatDistancePrefix(distToNext, ...);
  if (farPrefix && farText ...) farText = farPrefix + ...;
}
```

If `consumeGPSRecoveryFlag()` returns `true` (first fresh tick after stale/DR), the far-tier skips `stripBakedDistance`. The Valhalla original text (with baked distance like "In 300 feet, turn right") is passed to `onVoiceCb` verbatim. The driver hears the Valhalla baked distance instead of the live-computed one. This is incorrect — even when suppressing the prefix, the baked-in distance should be stripped.

**Sibling violation:** Near-tier always strips. Far-tier conditionally skips stripping. Both should always strip. Severity: minor (GPS recovery events are rare on a clear-sky urban drive), but it's a semantic inconsistency.

---

## Pass 3: Failure modes

### Failure mode: short-leg route (leg < 75m) → near fires immediately upon maneuver advance

**Location:** `frontend/navigation.js:760`, `:490–491`

Tick flow:
1. `snap = snapToRoute(...)` — snap advances into M1's segment range
2. `currentManeuverIdx = findManeuverForSegment(snap.segmentIndex)` → returns 1 (M1)
3. `checkVoice(snap)` → `nextIdx = 2` (M2)
4. `distToNext = distanceToManeuver(snap, 2)` → distance from snap (at M1 boundary) to M2's begin_shape_index = **M1 leg length**

If M1 leg length ≤ 75m: `distToNext ≤ floor → nearWouldFire = true`. Near fires immediately.
`formatDistancePrefix(leg_length)`:
- leg_length ∈ [45.7m, 75.9m] → "In 200 feet" (246ft → 200)
- leg_length ∈ [30m, 45.6m] → "In 100 feet" (98–149ft → 100)
- leg_length < 30m → "" (no prefix, below cutoff)

For Cameron's Villa Rita route with urban legs in the 50–75m range: every near-tier M2+ fires at leg entry → "In 200 feet."

**This is the primary failure mode producing Cameron's signature.** It is deterministic and geometry-driven: any route with legs in [45.7m, 75.9m] produces "200 feet" immediately upon entering each leg.

### Failure mode: GPS jitter at maneuver boundary → snap oscillates between segments

**Location:** `frontend/navigation.js:337–366` (`snapToRoute`), `:408–418` (`findManeuverForSegment`)

If GPS jitter causes `snap.segmentIndex` to oscillate between `M0.end_shape_index - 1` and `M1.begin_shape_index` across consecutive ticks:
- Odd ticks: `currentManeuverIdx = 0`, `nextIdx = 1`, near fires/re-fires checked for M1
- Even ticks: `currentManeuverIdx = 1`, `nextIdx = 2`, near fires checked for M2

Because `announcedSet` is key-based and one-shot, once near-M1 fires, the oscillation doesn't re-fire M1. But if M2's near fires on the first "even tick" (via floor), it's marked. On subsequent "odd ticks", `nextIdx = 1`, `announcedSet["1-near"]` is already set → no double-fire.

Net effect: jitter at M1 boundary causes M2's near to fire immediately (same as the short-leg case). **Does not produce a double-fire, but does produce premature near-fire for M2.** This is a minor variant of F2 / the short-leg failure mode.

### Failure mode: `distToNext <= 0` guard skips far-tier at boundary

**Location:** `frontend/navigation.js:482`

`if (distToNext <= 0) return;` — this early return blocks BOTH near and far tier. If GPS jitter causes snap to temporarily overshoot a maneuver boundary (snap lands 1m past `M2.begin_shape_index` → `distToNext = -1`), then:
- Near and far for M2 never fire
- Next tick, driver is further past M2, `currentManeuverIdx` has advanced to M2, `nextIdx = M3`
- M2's voice tier is silently skipped

**This failure mode silently swallows an announcement.** It affects any maneuver where GPS temporarily overshoots by 1–3m (common in urban canyons). It does not explain Cameron's "200 feet" bug directly but is a real correctness gap.

---

## Pass 4: Concurrency / state machine

### `currentManeuverIdx` is advanced BEFORE `checkVoice` — correct ordering, but creates early-fire window

**Location:** `frontend/navigation.js:760` (advance) vs `:835` (`checkVoice`)

Tick order:
```
tick()
 ├─ snap = snapToRoute(...)        // sets lastIndex
 ├─ currentManeuverIdx = findManeuverForSegment(snap.segmentIndex)
 └─ checkVoice(snap)               // reads currentManeuverIdx
```

This ordering is correct: `checkVoice` always reads the freshly-updated `currentManeuverIdx`. There is no stale-index bug.

However, advancing `currentManeuverIdx` in the SAME tick as the snap crossing creates the "early fire" characteristic documented in F2 above. The moment snap first enters M1's range, `currentManeuverIdx` becomes 1 and `checkVoice` evaluates M2 — before the driver has taken a single step into M1's leg. If M1's leg is short, near-tier for M2 fires at the M1 doorstep.

A hypothetical alternative ordering — advance `currentManeuverIdx` one tick later (only after the driver has been in M1's range for ≥1 tick) — would give M2 one tick of margin. This is not a code bug, but the current ordering is the direct mechanical cause of F2.

### `announcedSet` is shared module state — applyReroute clears it

**Location:** `frontend/navigation.js:1040–1041` (`applyReroute`)

`announcedSet = {};` — cleared on reroute. This is correct.

There is no concurrency issue here since JavaScript is single-threaded and the nav engine is not async internally. All state mutations in `tick()`, `checkVoice()`, and `applyReroute()` are synchronous and non-overlapping. `announcedSet` cannot race with itself.

### `prevTickWasStaleOrDR` consumed in `checkVoice` shared between near and far calls

**Location:** `frontend/navigation.js:510` (near-tier), `:569` (far-tier)

When near-tier fires, `consumeGPSRecoveryFlag()` is called at line 510. The flag is consumed. If far-tier ALSO fires in the same tick (not possible — `return` at near-tier end prevents it), it would get `false` from a second consume. Since near-tier returns before far-tier, only one consume happens per tick per checkVoice call. **No bug.**

However, there is a subtle issue: the GPS recovery flag is consumed inside `checkVoice` (lines 510 and 569), but `checkVoice` is called from `tick()` which may also call `buildState` before `checkVoice` in some paths. Let me verify:

```
tick():
  ...
  checkVoice(snap)     // may consume prevTickWasStaleOrDR
  emitUpdate(buildState(snap, false))  // does NOT call consumeGPSRecoveryFlag
```

`buildState` does not call `consumeGPSRecoveryFlag`. Only `checkVoice` does. In the `joining` and `rerouting` paths, `checkVoice` is not called (early returns before reaching it). So the flag is only consumed when a voice tier fires. **No cross-path consumption conflict.**

---

## Pass 5: Error propagation

### `distanceToCoordIndex` with out-of-range `targetIndex` returns large positive or negative value silently

**Location:** `frontend/navigation.js:321–326`

```javascript
function distanceToCoordIndex(segIndex, t, targetIndex) {
  if (!cumulativeDistances) return 0;
  var current = cumulativeDistances[segIndex] + segmentDistances[segIndex] * t;
  var target = cumulativeDistances[targetIndex];
  return target - current;
}
```

If `targetIndex >= cumulativeDistances.length` (e.g., `maneuvers[N].begin_shape_index` was corrupted or the multi-leg `indexAdjust` produced an out-of-range value), then `cumulativeDistances[targetIndex]` = `undefined`. `undefined - current = NaN`. This NaN propagates:

- `distToNext = NaN` at `checkVoice:481`
- `distToNext <= 0` → `NaN <= 0` is `false` (NaN comparisons) → guard does NOT return early
- `ttm = NaN / speed = NaN`
- `nearWouldFire = !announcedSet[nearKey] && (NaN <= 3 || NaN <= 75)` = `!false && (false || false)` = **false**
- `farWouldFire = !announcedSet[farKey] && (NaN <= 30)` = **false**

Net: NaN `distToNext` silently suppresses all voice announcements for this maneuver. No crash, no log, no user feedback. **The NaN does not produce "200 feet"; it silences the maneuver entirely.** Not Cameron's bug, but a silent failure mode.

The guard should be strengthened:
```javascript
if (!(distToNext > 0)) return;  // catches NaN (NaN > 0 is false) and ≤ 0
```
(The existing `if (distToNext <= 0) return` does NOT catch NaN — `NaN <= 0` is `false` in JavaScript.)

### `segmentDistances[segIndex] * t` in chain-append when `segIndex = m.begin_shape_index` pointing to last coord

**Location:** `frontend/navigation.js:520–522`

If `m.begin_shape_index` equals `coords.length - 1` (the final destination coord), then `segmentDistances[coords.length - 1]` is `undefined` (segmentDistances has length `coords.length - 1`, indices 0 to `coords.length - 2`). `undefined * 0 = NaN` (since `t = 0`). Then `cumulativeDistances[coords.length - 1] + NaN = NaN`. `distBetween = NaN - NaN = NaN`.

`NaN <= NEXT_AFTER_NEXT_DISTANCE (500)` is `false`, so the chain-append block is skipped. No crash, correct behavior (no chain on Arrive maneuver). **No operational bug** — the NaN is silently handled by the downstream comparison. But it's fragile: any future use of `distBetween` before the ≤ check would propagate the NaN.

### `formatDistancePrefix` NaN guard is correct

**Location:** `frontend/navigation.js:223`

```javascript
if (!(meters >= DISTANCE_PREFIX_CUTOFF_METERS) || !isFinite(meters)) return '';
```

The `!(meters >= X)` form catches NaN correctly (`NaN >= X` is false, so `!(false)` = true → returns ''). ✓ This is the well-written NaN guard. The `distToNext <= 0` guard at line 482 should use the same pattern.

---

## Consolidated finding list

### F1 — `VOICE_DISTANCE_FLOOR.auto = 75m` always fires near-tier at "200 feet"

**Pass:** Pass 1 (contract violation) + Pass 3 (failure mode)
**Location:** `frontend/navigation.js:52–56` (constant); `:490–491` (floor check)
**What's wrong:** The floor value of 75m places near-tier fires in the `formatDistancePrefix` bucket that maps to "In 200 feet" (45.7m–75.9m range). At 75m, `75 × 3.28084 = 246ft → Math.round(246/100)*100 = 200`. Every time the floor fires (rather than the 3-second TTM threshold), the voice says "In 200 feet." For M1, Cameron started navigation within 30m of the turn, so M1 fired via TTM at 30m → "In 100 feet." For M2+, the driver was outside 75m when the maneuver became active, so the floor fired first → "In 200 feet" every time.
**Why this matches Cameron's signature:** Deterministic "200 feet" for every non-M1 turn, correct "100 feet" for M1 (which fired via TTM at a closer distance due to late nav start). The pattern is repeatable on any route where M1 is started within 30m and subsequent legs are in the 46–76m range.
**How to reproduce in test:** Build a route fixture: depart, M1 at 30m (start within TTM zone), M2 at 75m from M1, M3 at 75m from M2. Nav start at 30m from M1. Assert: M1 near fires with "In 100 feet" prefix; M2 near fires with "In 200 feet" prefix on first tick past M1; M3 near fires with "In 200 feet" prefix on first tick past M2.
**Confidence:** HIGH.

---

### F2 — Near-tier fires at maneuver entry, not at approach, for short legs

**Pass:** Pass 3 (failure mode) + Pass 4 (state machine)
**Location:** `frontend/navigation.js:760` (`currentManeuverIdx` advance) + `:490–491` (floor check in `checkVoice`)
**What's wrong:** `currentManeuverIdx` is updated to M1 the instant `snap.segmentIndex` first enters M1's range (i.e., the first snap on or past M1's begin_shape_index). On that same tick, `checkVoice` evaluates `distToNext` for M2 = the entire remaining M1 leg from the snap point to M2. If the M1 leg is ≤ 75m, the floor triggers immediately and the near-tier for M2 fires before the driver has started traversing M1. The stated distance is the leg length (accurate), but the fire is at the wrong moment (at M1 entry, not while approaching M2).
**Why this matches Cameron's signature:** "Some fires happened when Cameron was actually ~35 ft / ~10m from the turn but voice said '200 feet'" — near-tier for M_(n+1) fired when Cameron was at M_n's turn point (~60–75m from M_(n+1)), TTS played over ~1.5–2s while Cameron covered ~15–20m, utterance finished when Cameron was ~45–55m from the turn; by the time Cameron perceived the cue as "imminent turn warning," he was at ~10–35m. The 5–10× perceived inflation is the combination of: (a) floor-triggered early fire at leg entry, (b) TTS playback delay, (c) human perception lag.
**How to reproduce in test:** Use a fixture with M1 leg = 65m. Start navigation at M0. Drive through M0. Assert that near-tier for M2 fires on the first tick that snap.segmentIndex enters M1's range (not after 30–65m of M1 travel).
**Confidence:** HIGH.

---

### F3 — Chain-append `distBetween` anchors at M-next's start, not driver's position

**Pass:** Pass 2 (cross-sibling deviation)
**Location:** `frontend/navigation.js:520–522`
**What's wrong:**
```javascript
var distBetween = distanceToManeuver(
  { segmentIndex: m.begin_shape_index, t: 0 }, afterIdx
);
```
`m` is `route.maneuvers[nextIdx]` (the upcoming turn). `m.begin_shape_index` is the coord index of the upcoming turn point — not the driver's position. So `distBetween` = M-next leg length (from turn point to after-next turn point), not the driver's distance to after-next.

When the driver is still 50m before M-next, the chain says "then in [leg length]m, turn left" but the actual driver distance to after-next is [leg length + 50m]. The chain understates the distance by the driver's current approach distance to M-next.

Sibling inconsistency: `distToNext` (primary prefix) correctly uses `snap` (driver position). `distBetween` (chain prefix) uses a fixed anchor. Both should use `snap`.

**Fix:** Replace the chain call with `distanceToManeuver(snap, afterIdx)`.

**Why this matches Cameron's signature:** Contributes to the "chain text says a shorter distance than reality" aspect. If the chain says "then in 200 feet, turn left" but the driver is 350 feet from M-after-next, the chain is understating by 150 feet. Does not produce the primary "200 feet" bug (that is F1/F2) but adds inaccuracy to the compound announcement.
**How to reproduce in test:** Fix with a route: M1 at 200m, M2 at 80m from M1 (within chain threshold). Driver at 50m before M1. Assert chain prefix = driver-to-M2 distance (≈250m), not M1-leg-length (80m).
**Confidence:** HIGH.

---

### F4 — `distToNext <= 0` guard does not catch NaN; silent announcement suppression

**Pass:** Pass 5 (error propagation)
**Location:** `frontend/navigation.js:482`
**What's wrong:** `if (distToNext <= 0) return;` — JavaScript: `NaN <= 0` evaluates to `false`, so NaN `distToNext` passes the guard. Then `ttm = NaN / speed = NaN`. `ttm <= 3` is `false` for NaN. `distToNext <= floor` is `false` for NaN. Both tiers are silently suppressed. The maneuver receives no voice announcement and no error is logged.

This would trigger if `route.maneuvers[nextIdx].begin_shape_index` is out of range or if `cumulativeDistances` has a gap (e.g., multi-leg indexAdjust produces an out-of-range index). Not Cameron's specific bug, but a real correctness gap for edge cases.

**Fix:** `if (!(distToNext > 0)) return;` — the `!( > )` form catches NaN, matching the pattern used in `formatDistancePrefix` (line 223).
**How to reproduce in test:** Pass a `snap` with a `segmentIndex` pointing to a coord index beyond the route length. Verify that `checkVoice` returns early (guard catches it) rather than silently skipping the announcement.
**Confidence:** MEDIUM (triggered only by corrupted route data, not normal driving).

---

### F5 — Far-tier skips `stripBakedDistance` when GPS recovery flag is set

**Pass:** Pass 2 (cross-sibling deviation) + Pass 5 (error propagation)
**Location:** `frontend/navigation.js:569–579`
**What's wrong:** Near-tier always calls `stripBakedDistance(text)` (line 499). Far-tier only calls `stripBakedDistance(farText)` inside the `if (!consumeGPSRecoveryFlag())` block (line 571). If `consumeGPSRecoveryFlag()` returns `true` (first fresh tick after stale/DR), far-tier speaks the raw Valhalla text — which may contain baked distances like "In 300 feet, turn right." The baked distance is wrong (stale from route planning, not live-computed) and is spoken verbatim.

**Why this matches Cameron's signature:** Cameron's drive was on fresh GPS with no DR events, so this wouldn't have triggered on his specific drive. Included for completeness; it's a genuine cross-sibling inconsistency that causes wrong voice output under stale-then-fresh GPS transitions.
**How to reproduce in test:** Simulate a GPS outage (set `lastGPSTime` to past the stale threshold), then restore fresh GPS. Assert that on the first fresh tick where far-tier fires, the spoken text has been stripped of baked distances.
**Confidence:** MEDIUM.

---

## Hypotheses ruled out via five-pass analysis

**H1 — Snap window sticks behind:** The snap window `[lastIndex - 3, lastIndex + 50]` with fallback to full-polyline search at >100m provides ample coverage. `lastIndex` always tracks the best snap segment. No evidence of snap lag.

**H2 — `findManeuverForSegment` returns wrong index:** The logic is correct. It scans maneuvers in order and returns the first match. Potential gap: maneuvers with `begin_shape_index == end_shape_index` (zero-length maneuvers) would never match the loop condition (`segIdx >= X && segIdx < X` is always false), causing the engine to skip to the next maneuver. This edge case is not definitively ruled out but was not observed in Valhalla's typical output for simple routing.

**H3 — `cumulativeDistances` stale or incorrect:** `precomputeDistances()` runs once at start/reroute. The arithmetic is correct (haversine sums). `distanceToCoordIndex` arithmetic is correct.

**H4 — Heading weighting snaps driver to wrong segment:** Heading penalty is only applied when `headingValid = true && candidates.length > 1`. Below `HEADING_SPEED_GATE = 3 m/s`, heading is not used. At normal urban speeds (>3 m/s), heading helps, not hurts. No evidence of snap regression here.

**H5 — Dead-reckoning snap used for checkVoice:** `deadReckonTick()` explicitly omits `checkVoice` (line 889 comment). DR is not involved in Cameron's clear-sky urban drive.
