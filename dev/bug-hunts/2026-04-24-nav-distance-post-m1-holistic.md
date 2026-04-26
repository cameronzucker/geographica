# Nav distance post-M1 inflation — Holistic hunter report

**Date:** 2026-04-24
**Hunter:** manzanita (holistic)

---

## State model

- `route` — immutable after `start()` / `applyReroute()`. Contains `coords`, `maneuvers[]` (each with `begin_shape_index`, `end_shape_index`), `costing`.
- `segmentDistances[i]` — precomputed once in `precomputeDistances()`, haversine of `coords[i]→coords[i+1]`. Never mutated post-start.
- `cumulativeDistances[i]` — precomputed once. `cumulativeDistances[i]` = route distance from `coords[0]` to `coords[i]`. Never mutated post-start.
- `lastIndex` — rolling "last snapped segment index". Updated to `best.segmentIndex` on every `snapToRoute()` call. Seeds the snap window `[lastIndex - 3, lastIndex + 50]`.
- `currentManeuverIdx` — set in `tick()` by `findManeuverForSegment(snap.segmentIndex)` **before** `checkVoice()` runs. Represents "which maneuver leg the driver is currently executing."
- `announcedSet` — `{ "N-far": true, "N-near": true }`. Keys are set once per maneuver per tier, never cleared except on `reset()` / `applyReroute()`.
- `VOICE_DISTANCE_FLOOR.auto = 75` — near-tier fires when `distToNext <= 75` OR `ttm <= 3`. This floor fires well before the 30m imminent-cutoff.
- `VOICE_TTM.auto = [30, 3]` — far fires at TTM ≤ 30s; near fires at TTM ≤ 3s.
- `distanceToManeuver(snap, idx)` — computes along-route distance from `snap` to `maneuvers[idx].begin_shape_index` using `cumulativeDistances` arithmetic. Returns negative if snap is past the target.
- `checkVoice(snap)` — called every GPS tick during navigating. Reads `currentManeuverIdx` (already updated), computes `nextIdx = currentManeuverIdx + 1`, fires far or near tier for `route.maneuvers[nextIdx]`.
- `prevTickWasStaleOrDR` / `drActive` — GPS recovery flag. Does not affect fire decisions; only suppresses the distance prefix on the first fresh tick after stale/DR.
- `suppressVoiceOnNextTick` — one-shot flag, only set on `applyReroute()` re-tick. Not relevant to normal driving.

---

## Reasoning trace

### How M1 fires correctly

- At route start, `currentManeuverIdx = 0` (depart leg), `nextIdx = 1` (M1 = first spoken turn).
- As the driver approaches M1, `distToNext` decreases smoothly.
- On Cameron's drive, near-tier for M1 fires via **TTM** (ttm ≤ 3s at ~9 m/s → fires at ~27m). `distToNext = 27m = 89ft → Math.round(89/100)*100 = 100 → "In 100 feet"`.  ✓

### What changes after M1

- Driver physically crosses M1's turn point. On the next GPS tick, `snap.segmentIndex` enters M1's range: `snap.segmentIndex >= maneuvers[1].begin_shape_index`. `findManeuverForSegment` returns `1`. `currentManeuverIdx = 1`.
- `checkVoice` now targets `nextIdx = 2` (M2). `announcedSet["1-near"]` is already set (from M1's near-tier fire). M1 is done.

### Why M2 says "In 200 feet" regardless of actual position

Step 1 — `currentManeuverIdx` advances the instant `snap.segmentIndex` enters M1's range (i.e., the driver is at or just past M1.begin_shape_index, the turn point).

Step 2 — `distToNext = distanceToManeuver(snap, 2)` = along-route distance from the snap point to `maneuvers[2].begin_shape_index` = the length of the M1 leg from the snap point to M2's boundary.

Step 3 — Near-tier fires when `distToNext <= VOICE_DISTANCE_FLOOR.auto (75)`. If the M1 leg is < 75m long (common in urban close-spaced turn sequences), `distToNext ≤ 75` is true **on the very first tick** that `currentManeuverIdx` becomes 1. Near fires immediately, before the driver has covered any of the M1 leg.

Step 4 — `formatDistancePrefix(distToNext)` where `distToNext ≈ 55–75m`:
- `feet = 55*3.28084 = 180ft → Math.round(180/100)*100 = 200` → "In 200 feet"
- `feet = 75*3.28084 = 246ft → Math.round(246/100)*100 = 200` → "In 200 feet"

The entire range 45.7m–75.9m (the bucket that rounds to 200 feet) maps to "In 200 feet". The 75m floor sits inside this bucket.

Step 5 — `announcedSet["2-near"] = true`. Near-tier for M2 will never fire again. As the driver closes the remaining distance to M2 (e.g., 70m → 50m → 10m), `checkVoice` keeps early-returning at the `distToNext <= 0` guard (no, distToNext is positive but `announcedSet[nearKey]` is true). No further voice fires for M2.

The driver hears "In 200 feet" when they cross M1's boundary (at the start of a ≤75m M1 leg), then silence until they're past M2. From the driver's perspective: voice fired when they were ~30-65m from M2 but said "200 feet"; by the time they processed the utterance they were at 10m. The TTS takes 1-2 seconds to play, during which the car covers 10-20m at urban speeds.

### Why this pattern repeats for M3, M4...

Every maneuver after M1 faces the same condition: the instant `currentManeuverIdx` advances to maneuver N, `checkVoice` evaluates distance to maneuver N+1. If maneuver N's leg is < 75m (common in dense urban routing), near fires immediately via floor → "In 200 feet". This is deterministic and route-geometry-dependent. Routes with legs < 75m always produce this pattern; routes with legs > 75m are fine.

### The "first fire correct" invariant

M1 is special: its near-tier fires while `currentManeuverIdx = 0` (driver still in M0's leg). The driver is typically 27-75m BEFORE M1 at near-fire time. At 27m (the TTM=3s regime at 9 m/s) → 89ft → "In 100 feet". At 75m (pure floor trigger) → 246ft → "In 200 feet". M1 fires correctly when the driver's approach speed means TTM fires before the floor; this is typical of the first maneuver because the driver has been accelerating toward it.

For M2+, the near-tier fires at the first tick where `currentManeuverIdx` becomes N. If the leg is short, `distToNext` is already in the "200 feet" zone and the driver has NOT been "approaching M2" — they've just crossed M1 and are at the start of a short leg.

---

## Findings

### F1 — `VOICE_DISTANCE_FLOOR.auto = 75m` lands in the "200 feet" formatDistancePrefix bucket

**Location:** `frontend/navigation.js:52–56` (constant definition); `frontend/navigation.js:490–491` (floor check in checkVoice)

**What's wrong:** The auto floor was set to 75m to provide TTS lead time (~2.6s at highway speeds, per the comment). But 75m × 3.28084 = 246ft, which `Math.round(246/100)*100 = 200`. So the floor fires at a distance that is labeled "200 feet" to the driver. Meanwhile M1 fires via TTM at ~27m = 89ft → "In 100 feet". The discrepancy (200 vs 100 feet) is not just cosmetic — it fires 2.5–5× earlier than the driver expects the near-tier cue.

The test suite **explicitly validates this behavior** at line 1348–1368 of `navigation.test.mjs`: `assert.match(fires[0], /^In 200 feet, turn left onto First Street/)`. The test was written to confirm the 75m floor maps to "200 feet". This means the bug is **in the constant value**, not in the rounding logic or the test.

**Why this matches Cameron's signature:** M1 fires at ~27m (TTM path) → "In 100 feet" ✓. M2+ fires at 75m (floor path) → "In 200 feet" × repeatedly.

**The "5–10× inflation" explained:** Cameron perceives the voice as firing when he's at ~10m from the turn. That's because near-tier fires at 65–75m from M2, but TTS takes ~1.5–2s to complete, during which the car travels ~15–20m at urban speeds (8–10 m/s). When the utterance finishes playing, Cameron is at ~45–55m from M2. By the time he processes it as "that was the turn cue," he's at ~10–35m. The stated distance "200 feet" vs actual ~150–100 feet at voice start = 1.3–2× inflation at voice start; by utterance end it's 3–5×; by perceived moment it's 5–10×.

**How to reproduce in test:** Write a fixture where M1's near-tier fires at 27m (TTM path), then drive past M1 into a 70m M2 leg and observe that M2's near fires immediately at the leg start with "In 200 feet" prefix, while the driver is 70m from M2.

**Confidence:** HIGH. The root cause is the floor value. The test at line 1348 explicitly asserts and locks in this behavior.

---

### F2 — For short inter-turn legs (leg length < 75m), near-tier fires at the START of the leg, not at an appropriate approach distance

**Location:** `frontend/navigation.js:490–491` (floor check); `frontend/navigation.js:760` (currentManeuverIdx update timing)

**What's wrong:** `currentManeuverIdx = findManeuverForSegment(snap.segmentIndex)` runs **before** `checkVoice(snap)` in `tick()`. The moment the driver crosses maneuver N's `begin_shape_index`, `currentManeuverIdx` advances to N and `checkVoice` immediately evaluates `distToNext` for maneuver N+1.

If the leg (M-N to M-(N+1)) is shorter than the floor (75m for auto), `distToNext` at first entry is already ≤ 75m → near fires. The voice prompt for M-(N+1) fires when the driver is at M-N's doorstep, not when they're approaching M-(N+1). The "In 200 feet" spoken distance is technically accurate (they ARE ~200 feet from M-(N+1)) but fires at the wrong moment — the driver is just starting the previous maneuver, not approaching the next.

**Why this matches Cameron's signature:** Villa Rita–class urban segments have legs of 30–80m. On any leg ≤ 75m, near-tier fires immediately at the start of that leg → "In 200 feet" (for legs 45.7–75.9m) or no prefix (for legs < 30m). Cameron's drive "Villa Rita → 24th" had multiple short legs in this range.

**How to reproduce in test:** Use `fixtureVillaRitaCluster` (30m legs). Near-tier fires immediately upon entry to each leg. The "In 200 feet" pattern would occur on any fixture with leg length in [45.7, 75.9]. The 30m legs in Villa Rita fixture actually produce sub-cutoff distances (no prefix), which is why the existing test passes — but any fixture with 60–75m legs would reproduce the spoken "200 feet" at leg entry.

**Confidence:** HIGH.

---

### F3 — Chain-append `distanceToManeuver` uses M1's START as anchor, not the driver's current position

**Location:** `frontend/navigation.js:520–521`

**What's wrong:** The chain-append calculation uses:
```javascript
var distBetween = distanceToManeuver(
  { segmentIndex: m.begin_shape_index, t: 0 }, afterIdx
);
```
Here `m = route.maneuvers[nextIdx]` = M1. The snap object `{ segmentIndex: m.begin_shape_index, t: 0 }` represents the start of M1, not the driver's current position. So `distBetween` = length of M1's leg (M1 start → M2 start), which is **shorter than the driver's actual distance to M2** (driver is still approaching M1 from within M0).

For example: driver is 27m before M1; M1 leg is 80m. Chain says "then in 80m (262ft → 300 feet) turn..." but driver is actually 107m from M2 (350 feet). The chain underreports the distance to the after-next maneuver by the driver's current distance to M1.

**Why this matches Cameron's signature:** This affects the chain ("then in X feet") portion of voice prompts, not the primary near-tier prefix for the upcoming maneuver. It could cause the chain text to say a shorter distance than reality (e.g., "then in 200 feet" when 350 feet away). Severity is moderate since chain text is supplementary.

**How to reproduce in test:** Use `fixtureWiderCluster` (200m legs). Fire near-tier for M1 while 27m before M1. Check chain's "then in X feet" — it should be ≈200m (M1 leg) but driver is ≈227m from M2.

**Confidence:** MEDIUM. This is a genuine arithmetic error in the chain anchor point, but it contributes less to Cameron's primary complaint (which is the primary near-tier prefix, not the chain).

---

## Hypotheses ruled out

**H1 — `lastIndex` snap window sticks behind post-turn:** Ruled out. `lastIndex` is always updated to `best.segmentIndex` after each snap. The window `[lastIndex - 3, lastIndex + 50]` gives 50 segments of lookahead, more than enough for any urban segment. The fallback to full-polyline search (`SNAP_FALLBACK_THRESHOLD = 100m`) provides a second safety net. No evidence of snap lag in the code.

**H4 — `lastValidHeading` retains pre-turn bearing, penalizing post-turn segments:** Ruled out. The heading weight in `searchSegments` is only applied when `heading !== null && heading !== undefined && candidates.length > 1`. At a turn, speed typically drops below `HEADING_SPEED_GATE = 3 m/s`, setting `headingValid = false`, which causes `null` to be passed to `snapToRoute` → no heading penalty applied. Even if heading were applied, the +50 segment window and fallback prevent snap from getting stuck.

**H2 — `findManeuverForSegment` advances `currentManeuverIdx` late:** The opposite is true — it advances EARLY. The moment `snap.segmentIndex` first enters M1's range (`>= begin_shape_index`), `currentManeuverIdx` becomes 1, and `checkVoice` immediately evaluates M2. This early advance is the mechanism behind F2.

**H3 — `cumulativeDistances` rebuilt post-start:** Ruled out. `precomputeDistances()` is only called in `start()` and `applyReroute()`. `segmentDistances` and `cumulativeDistances` are never mutated mid-route. All `distanceToCoordIndex` results are arithmetically correct given the precomputed arrays.

**H5 — Silent reroute rebuilds route mid-trip:** Ruled out for Cameron's specific observation. Reroutes require off-route detection (3-of-5 ticks > 50m), `applyReroute` clears `announcedSet` and resets `lastIndex`. Cameron's drive was continuous without reroutes. If a silent reroute had occurred, it would also reset all maneuver indices and the "200 feet" pattern would reset after the reroute.

**H6 — Dead-reckoning snap used for `checkVoice`:** Ruled out. `deadReckonTick()` explicitly does NOT call `checkVoice` — the comment at line 889 reads "G11 (spec v2): dead-reckoning is position-only. No voice." GPS was fresh on Cameron's urban drive (1 Hz with clear sky), so DR never engaged.

---

## Fix recommendation

### Primary fix: Lower `VOICE_DISTANCE_FLOOR.auto` to 30m (or align it with the prefix cutoff)

`VOICE_DISTANCE_FLOOR.auto = 75` was set for TTS lead time. But 75m at 9 m/s (20 mph urban) = 8.3 seconds — far more than the 2-3s the comment claims, and far more than the spec's `near_seconds = 3`. The floor should sit below the "In 100 feet" bucket boundary (30.48m) so that floor-triggered fires say "In 100 feet" instead of "In 200 feet".

Proposed value: `VOICE_DISTANCE_FLOOR.auto = 35` (115ft → rounds to 100ft → "In 100 feet"). This gives ~4s lead at 9 m/s — enough for TTS to start before the turn.

Alternative: `VOICE_DISTANCE_FLOOR.auto = 45` (148ft → rounds to 100ft → "In 100 feet" since 148ft < 150ft crossover). Still in the "100 feet" bucket.

At 75m, 45.7m is the lower bound of the "200 feet" bucket (150ft threshold). So any floor ≤ 45.7m avoids the "200 feet" problem.

### Secondary fix: Chain-append anchor (F3)

Replace the fixed-anchor snap with the driver's current snap for the chain distance calculation:

```javascript
// Current (wrong): anchors at M1's begin_shape_index, not driver's position
var distBetween = distanceToManeuver(
  { segmentIndex: m.begin_shape_index, t: 0 }, afterIdx
);

// Correct: anchor at driver's current snap
var distBetween = distanceToManeuver(snap, afterIdx);
```

This makes the chain text "then in X feet" accurate relative to the driver, not relative to M1's start.

---

## Summary

Cameron's "first fire correct, all subsequent fires say 200 feet" is a **floor constant mismatch**, not a snap, heading, or dead-reckoning bug. `VOICE_DISTANCE_FLOOR.auto = 75m` was set for TTS lead time, but 75m × 3.28084 = 246ft, which `formatDistancePrefix` maps to "In 200 feet" (the 200-foot bucket covers 45.7m–75.9m). M1 fires via TTM (~27m → "In 100 feet"); every subsequent maneuver whose leg is < 75m fires via floor immediately upon leg entry → "In 200 feet". Lowering the floor to 35–45m places floor-triggered fires in the "In 100 feet" bucket and gives appropriate approach timing. The chain-append anchor is a secondary accuracy issue, fixable independently.
