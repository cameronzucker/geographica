# Nav distance post-M1 inflation — Consolidated findings

**Date:** 2026-04-24
**Scope:** Geographica nav engine post-Tasks-0-9 state on `dev` (HEAD `46bd08c`). Specifically `frontend/navigation.js` voice-tier announcement system.
**Hunters:** Exploratory (manzanita), Holistic (manzanita), Multipass (manzanita) — all Sonnet, parallel.
**Trigger:** Cameron's field test surfaced deterministic post-M1 inflation: first near-tier fire on M1 was correct ("In 100 feet, " at ~90 ft), every subsequent fire stuck at "In 200 feet" regardless of actual distance. Some subsequent fires happened when Cameron was actually ~35 ft from the turn — voice still said "200 feet". Cameron's support-engineer intuition: "a decision table, formula, or lookup is hitting some kind of minimum."

---

## Executive summary

**1 confirmed bug (P0, all 3 hunters HIGH confidence).** **0 false positives.** **2 design decisions needing Cameron's input.** **2 out-of-scope improvements (defer-able).**

Cameron's intuition was correct — there *is* a "minimum" hitting at the wrong granularity. It is not a clamp on `distToNext`; it is the **interaction between `VOICE_DISTANCE_FLOOR.auto = 75m` and the 100-ft bucket boundaries in `formatDistancePrefix`.** 75m × 3.28084 = 246.1 ft → `Math.round(246/100)*100 = 200`. **The 75m floor sits at the top of the "In 200 feet" bucket, so every floor-triggered near-tier fire announces "In 200 feet" by construction.** Below 56 mph, the floor always wins over the TTM=3s threshold, so all city-speed floor-fires deterministically say "200 feet".

Math (verified independently in Phase 3 cross-validation):

| Costing | Floor (m) | At floor in feet | Imperial bucket | Crossover speed (TTM beats floor) |
|---|---:|---:|---|---|
| auto | **75** | **246.1 ft** | **"In 200 feet, "** | **56 mph** |
| bicycle | 45 | 147.6 ft | "In 100 feet, " | 34 mph |
| pedestrian | 15 | 49.2 ft | "" (sub-cutoff) | 17 mph |

The bug is `auto`-only. Bicycle and pedestrian floors land in semantically appropriate buckets.

**Why M1 was correct on Cameron's drive:** Cameron started navigation close to M1 (within ~27m, per "90 ft" reading). At 25 mph, distToNext=27m gives ttm=2.4s ≤ 3s near-tier TTM threshold → **TTM-fire path wins, announces "100 feet"** (27m → 89 ft → bucket 100). For M2, M3, etc., Cameron approached from far — engine fires at 75m boundary via floor → always "200 feet".

---

## Confirmed Bugs

### B1. `VOICE_DISTANCE_FLOOR.auto = 75m` lands in the "200 feet" bucket; every auto floor-fire says "200 feet"

**Consensus:** All 3 hunters HIGH confidence (exploratory F1+F2, holistic F1+F2, multipass F1+F2).
**Location:** [frontend/navigation.js:53](../../frontend/navigation.js#L53) (the constant) + [navigation.js:491](../../frontend/navigation.js#L491) (the OR clause in `nearWouldFire`) + [navigation.js:226](../../frontend/navigation.js#L226) (the bucket math).
**Evidence:**
```js
// navigation.js:52-56
var VOICE_DISTANCE_FLOOR = {
  auto:       75,    // 246 ft → bucket 200
  bicycle:    45,    // 148 ft → bucket 100
  pedestrian: 15     // 49 ft  → empty (sub-cutoff)
};

// navigation.js:491
nearWouldFire = !announcedSet[nearKey] && (ttm <= ttmPair[1] || distToNext <= floor);

// navigation.js:226
if (feet < 1000) return 'In ' + (Math.round(feet / 100) * 100) + ' feet, ';
```
At any speed below the crossover (56 mph for auto), `distToNext <= floor` becomes true *before* `ttm <= 3` does. The fire happens on the first tick where `distToNext` drops to ≤ 75m — which lands in the [45.7, 75.9]m range = the "In 200 feet" bucket.

The 100-ft rounding granularity makes this deterministic: any floor-fire is in a 30m-wide window, and the 100-ft bucket is 30.5m wide, so the floor sits inside exactly one bucket ("In 200 feet").

**Impact:** Every auto-mode near-tier announcement at city/surface-street speeds (5–55 mph) says "In 200 feet" regardless of actual distance. Cameron's perception of "wildly implausible distance for very close upcoming turns" is the user-experience consequence: when the actual road geometry produces a 50–75m floor-fire while user is approaching at 20 mph, the voice utterance ends ~2s later (covering ~18m of travel), and by the time the user perceives the cue as meaningful, they're in the 30–55m / 100–180 ft range — but the voice already said "200 feet". The net audible mismatch on close turns is 2–6×.

The pattern is masked at very high speed (56+ mph) where TTM-fire wins; nobody noticed because the test fixtures and field tests were on city speeds.

**Blast radius:** Affects every `auto`-costing route's near-tier announcements. Bicycle and pedestrian costings are unaffected (their floors land in safer buckets). Test suite at [navigation.test.mjs:1348-1368](../../frontend/tests/engine/navigation.test.mjs#L1348-L1368) and the Villa Rita reference in spec §5.4 explicitly **lock in** the "In 200 feet" assertion — those tests must change with the fix.

**Fix approach:** Two viable strategies (Cameron picks; see D1 below):
- **Strategy A**: Lower `VOICE_DISTANCE_FLOOR.auto` to ≤ 45m. At 45m → 148 ft → bucket 100. Floor-fires now say "In 100 feet". Trade-off: reduces the buffer from 6.7s (at 25 mph) → 4s — gives back some of the buffer that Issue 1 of the just-shipped cycle was specifically buying. Effectively re-opens the original "speech in the air past the turn" failure mode.
- **Strategy B**: Keep the 75m floor for safety/buffer, but **suppress the prefix on floor-triggered fires**. TTM-triggered fires keep the prefix (where the distance is meaningful — user is approaching at speed); floor-triggered fires speak the bare maneuver text ("Turn left onto X"). Semantically aligned with the spec's original 30m / 100 ft "imminent" intent — the 30m cutoff in `formatDistancePrefix` was supposed to enable this but never wired up because the engine never fires at <30m. This re-purposes the cutoff intent via a different (cleaner) signal: floor-fire vs TTM-fire.

Strategy B is the holistic hunter's recommendation and aligns most closely with what Cameron asked for (no implausible distances on close turns) without sacrificing the buffer.

---

## Design Decisions Requiring User Input

### D1. Strategy for B1: Lower the floor, or suppress prefix on floor-fires?

**The concern:** The fix for B1 has multiple defensible shapes. The choice depends on which guarantee is more important.

**Options:**

- **D1a — Strategy A: Lower floor to 45m (auto only).** Smallest mechanical change (one constant). Auto floor-fires now land in "In 100 feet" bucket. **Cost:** loses ~2.7s of post-speech buffer at 25 mph (the +1.3 s of audible "still-playing-at-the-turn" prevention that Issue 1 of the just-shipped cycle was about). Effectively undoes Issue 1.

- **D1b — Strategy B: Keep 75m floor, suppress prefix on floor-fires only.** Distinguishes TTM-fire (meaningful distance, prefix applied) from floor-fire (imminent, no prefix). Voice says "In 200 feet, turn left onto X" only when TTM=3s threshold lights it up (i.e., when user is approaching fast enough that 200 ft is meaningful). When floor lights it up (slow approach, parking-lot, stop-and-go), voice says bare "Turn left onto X". **Cost:** ~10 lines of code change in checkVoice + chain-append, plus test rewrites. **Pro:** Preserves Issue 1's buffer; eliminates the implausible-distance failure mode entirely; no constants change.

- **D1c — Strategy C: Differentiate floor by speed (e.g., 75m at high speed, 45m at low speed).** More complex; introduces speed-dependent state in floor selection. Probably over-engineered for the symptom.

**Recommendation:** **D1b (Strategy B).** Three reasons:
1. Doesn't undo Issue 1 (Cameron's prior validated buffer fix).
2. Aligns with the spec's *intent* on the 30m / 100 ft cutoff ("read as imminent below this") — currently dead code; this re-grounds it via the floor-fire vs TTM-fire distinction.
3. Cleanest semantic mapping: a TTM-fire is by definition "user is approaching at speed, distance is meaningful"; a floor-fire is "user is close enough to the maneuver that the floor caught it, regardless of speed — the announce IS imminent."

### D2. Chain-append distance anchor: keep M_(n+1)→M_(n+2), or switch to driver→M_(n+2)?

**The concern:** All three hunters flagged the chain-append distance computation:
```js
// navigation.js:520-522
var distBetween = distanceToManeuver(
  { segmentIndex: m.begin_shape_index, t: 0 }, afterIdx
);
```
This anchors at M_(n+1)'s start, so `distBetween` = M_(n+1)→M_(n+2) leg length. Hunters argue this should be `snap` (driver's current position) so `distBetween` = total user-→-M_(n+2).

**Why this needs a decision:** The two interpretations of "Turn left, *then in X feet, turn right*":
- **Reading A (current):** "After the first turn, drive X to reach the next turn." X = M_(n+1)→M_(n+2) leg length. Anchored at M_(n+1)'s start.
- **Reading B (hunters' fix):** "In X feet from your current position, turn right (at the second turn)." X = driver→M_(n+2). Anchored at driver's snap.

Consider a 75m fire on M_(n+1) with M_(n+2) 459m past M_(n+1):
- Reading A: chain says "then in 1/4 mile, turn left" (459m → 1/4 mile bucket). True spec §5.4 phrasing.
- Reading B: chain says "then in 1/4 mile, turn left" (75 + 459 = 534m → still 1/4 mile bucket; the bucket is 980 ft wide so both interpretations coincidentally land in the same answer for typical numbers).

**Operationally:** Reading A tells the driver lane-change planning info ("after the first turn, you have X feet"). Reading B tells total trip-from-now distance to the second turn. Reading A is more actionable when chain-append exists *because* the two turns are close.

**Spec evidence:** [docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md §5.4](../../docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md#54-expected-prompts-on-villa-rita--costco) walks through Villa Rita with Reading A annotations ("Seg 0 near+chain · 75 m, M[2] @ 459 m | … 'then in a quarter mile, turn left onto West Union Hills Drive'" — 459m is the M[1]→M[2] leg length).

**Recommendation:** **Keep Reading A (current code).** It matches the spec, matches conventional driving-direction speech ("turn left, then in 500 feet, turn right"), and is actionable for the driver. The hunters' Reading B argument is internally consistent but contradicts the spec's design intent. **Treat F3 as a false positive.**

(If Cameron prefers Reading B, that's also fine — it's a design decision, not a defect — and it's a 1-line change.)

---

## False Positives

### FP1. F3 — Chain-append uses M_(n+1)→M_(n+2) anchor (per current code)
**Flagged by:** All 3 hunters (HIGH confidence).
**Why invalid as a defect:** Spec §5.4 explicitly uses the M_(n+1)→M_(n+2) leg-length interpretation. Hunters reasoned about "what should this mean" without checking the spec; the spec authors deliberately chose Reading A. See D2 above for the design alternative if Cameron prefers to revisit.

---

## Bugs Outside Primary Scope

### O1. NaN guard at navigation.js:482 doesn't catch NaN
**Found by:** Exploratory F4, Multipass F4.
**Location:** [navigation.js:482](../../frontend/navigation.js#L482) — `if (distToNext <= 0) return;`.
**Issue:** `NaN <= 0` is `false` in JavaScript. A NaN `distToNext` (from out-of-range `begin_shape_index` or arithmetic on undefined) bypasses the guard, and downstream conditions `NaN <= ttmPair[1]` and `NaN <= floor` are also both false → silent suppression of the announcement with no log.
**Compare:** `formatDistancePrefix` at line 223 uses the correct `!(meters >= X)` form which catches NaN.
**Blast radius:** Edge case (only reachable if route shape is malformed); not Cameron's specific drive.
**Recommendation:** Defer — fold into a future cleanup commit. Don't bundle with the B1 fix; orthogonal.

### O2. Far-tier skips `stripBakedDistance` on GPS-recovery tick; near-tier always strips
**Found by:** Exploratory F5, Multipass F5.
**Location:** [navigation.js:565-579](../../frontend/navigation.js#L565-L579) (far-tier branch).
**Issue:** Near-tier always calls `stripBakedDistance(text)` (line 491). Far-tier only strips when `!consumeGPSRecoveryFlag()` (line 569 onwards) — on the first fresh tick after stale/DR, the strip is skipped and Valhalla's raw "In 700 feet, turn left" is spoken verbatim *with* the live-distance prefix (giving "In 1/4 mile, in 700 feet, turn left" — double-prefix).
**Blast radius:** Only reachable on GPS-recovery transitions. Cross-sibling inconsistency.
**Recommendation:** Defer — fold into the same future cleanup commit as O1. Orthogonal to B1.

---

## Test Gap Analysis

### B1. `VOICE_DISTANCE_FLOOR.auto = 75m` always says "In 200 feet" on floor-fire

**Why missed:** Test [navigation.test.mjs:1348-1368](../../frontend/tests/engine/navigation.test.mjs#L1348-L1368) explicitly *encodes* "In 200 feet" as the expected output for a 75m floor-fire on `fixtureWiderCluster`. The test passes — but it's pinning the *bug* as correct behavior, not detecting it. The plan author wrote the assertion based on the spec table (which itself derived from the bucket arithmetic), not against a user-acceptance criterion of "spoken distance must be perceptually accurate to actual distance".

This is a **`docs/pitfalls/testing-pitfalls.md` pitfall**: tests that assert on "what the code currently does" rather than "what the user should experience." The unit-test bucket sweep (lines 1057–1141) is also accurate-but-pinning — it locks in the 75m → "200 feet" mapping without questioning whether *the input value 75m* is the right input value.

**Pitfall coverage:** This is a NEW class of pitfall not yet documented. The closest related pitfall is "tests that assert what they constructed" but this is broader: "tests that pin a numeric mapping driven by a constant elsewhere in the code, without verifying the constant's value is the right value."

**Catch test that would have caught this:** A field-acceptance test (or a synthesized acceptance test using Villa Rita-class fixtures with `costing: 'auto'`) asserting that the *user-perceived distance* matches the *spoken distance* within ±25%, across a sweep of approach speeds (10–55 mph). Such a test would have failed at 25 mph because user-perceived distance at announce-time + TTS playback is 30–55m (98–180 ft), but the announcement says 200 ft.

This kind of test is harder to write — it requires a model of "user's perceived position when the cue is heard" (announce-fire-time + TTS playback latency + cognitive recognition delay). But it's the right *shape* of test for voice-driven UX features.

**Pitfall recommendation:** Add a new entry to `docs/pitfalls/testing-pitfalls.md`: **"Don't pin numeric output mappings without auditing the input source."** When a test asserts `formatDistancePrefix(X, true) === "In 200 feet"`, also audit *why X is 75m*. If X is sourced from a tunable constant elsewhere, the test pins the bug, not the spec.

### Testing Pitfalls Updates
- Drafted addition (above) — recommend adding to `docs/pitfalls/testing-pitfalls.md` in the same fix-plan PR. The pitfall is generalizable to any UX-bucketing feature (similar pattern could bite imagery quality buckets, search-result count buckets, etc.).

---

## Phase 3 completeness check

Findings enumerated across all 3 reports:

| Report | Finding | Disposition |
|---|---|---|
| Multipass | F1 (floor=75 → "200 feet") | → B1 (confirmed) |
| Multipass | F2 (short legs fire at entry) | → B1 mechanism (consolidated) |
| Multipass | F3 (chain-append anchor) | → FP1 / D2 (false positive as defect; design decision exists) |
| Multipass | F4 (NaN guard) | → O1 (out of scope) |
| Multipass | F5 (far-tier strip on recovery) | → O2 (out of scope) |
| Multipass | Pass-2 cross-sibling: chain anchor | → FP1 / D2 (same as F3) |
| Exploratory | F1, F2 | → B1 (consolidated) |
| Exploratory | F3 | → FP1 / D2 |
| Exploratory | F4 | → O1 |
| Exploratory | F5 | → O2 |
| Holistic | F1, F2 | → B1 |
| Holistic | F3 | → FP1 / D2 |

All hunter findings accounted for. ✓
