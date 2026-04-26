---
round: 1
angle: TTM math and API correctness
reviewer: general-purpose (Claude Opus 4.7)
date: 2026-04-20
agent: alder
---

# Round 1 — TTM math, API correctness, algorithmic edge cases

Eight findings against `docs/superpowers/specs/2026-04-20-nav-voice-ttm-design.md`. Focus: places where the algorithm as specified would fire the wrong number of prompts, at the wrong time, under specific but not-implausible inputs. Four MUST-FIX (F1.1, F1.2, F1.3, F1.4), three SHOULD-FIX, one NICE-TO-HAVE.

The single most severe bug is F1.1: `distanceToManeuver` in the current codebase returns a *signed* along-route difference. The spec assumes non-negative. Under GPS jitter, U-turn maneuvers with overlapping `begin/end_shape_index`, or a dead-reckoning extrapolation that walks past the next maneuver's begin-shape before `currentManeuverIdx` advances, `distToNext` goes negative → `ttm = negative / positive = negative` → `ttm <= 30` is trivially true → far-tier fires for a maneuver the driver has already executed or is in the middle of executing. This is exactly the "wrong prompt, wrong time" failure mode the spec is trying to eliminate.

---

### F1.1 — `distanceToManeuver` can return negative; negative TTM passes every threshold

**Severity:** MUST-FIX

**Claim in spec:** §4.3 computes `var ttm = distToNext / speed;` and then compares `ttm <= ttmPair[1]` / `ttm <= ttmPair[0]`. The spec treats `distToNext` as a non-negative "how far ahead is the next maneuver" value. §7 "Edge cases" does not contemplate negative distances.

**Reality:** In the current source (`frontend/navigation.js:209-214`), `distanceToCoordIndex` is defined as:

```js
function distanceToCoordIndex(segIndex, t, targetIndex) {
  if (!cumulativeDistances) return 0;
  var current = cumulativeDistances[segIndex] + segmentDistances[segIndex] * t;
  var target = cumulativeDistances[targetIndex];
  return target - current;   // unsigned subtraction — can be negative
}
```

`distanceToManeuver(snap, maneuverIdx)` at `navigation.js:309-313` wraps this without a `Math.max(0, …)` guard. It returns a negative number whenever the snap's along-route position exceeds the target maneuver's `begin_shape_index` position. Four realistic ways this happens:

1. **U-turn maneuvers.** Valhalla's `auto` costing sometimes emits a `begin_shape_index` for a U-turn maneuver that equals the **same** shape index as the previous maneuver's end. A snap that progresses by one shape index past the U-turn boundary — while `findManeuverForSegment` still reports the pre-U-turn maneuver — produces `targetIdx < segIdx`.
2. **Dead-reckoning overshoot.** `deadReckonTick()` at `navigation.js:686-700` calls `checkVoice(drSnap)` where `drSnap` is an extrapolated position. During a 30-second DR window at 15 m/s, the DR snap advances 450m. If the next maneuver is 300m away, the DR snap walks 150m past it — `distToNext < 0` — AND `currentManeuverIdx` may lag because `findManeuverForSegment` is called on the DR snap just before checkVoice. Under the spec's D1 suppression, a negative TTM makes the near-tier condition trivially true → near fires → `announcedSet[nearKey] = true` → real GPS returns → near already "announced" → driver never hears the turn they should have heard at the real 30s point.
3. **GPS jitter at a maneuver boundary.** Snap bounces between seg *N-1* and seg *N* across two ticks. If seg *N* is the first segment of the next maneuver, tick 1 sees `targetIdx > segIdx` (fine), tick 2 sees `targetIdx <= segIdx` (negative). Under the band-aid's 3-tier model this is masked by the distance-based check (400m threshold); under TTM, a negative TTM passes every threshold simultaneously.
4. **Route start at the first maneuver.** Valhalla's first maneuver has `begin_shape_index = 0`. If the snap starts at seg 0 with t > 0, then `current > target = 0` → `distToNext < 0`.

**Impact:** Depending on which of the four paths triggers, either (a) a prompt fires for an already-crossed maneuver (driver gets "Turn left onto Oak Ave" when they are already on Oak Ave — exactly the Villa Rita field symptom), or (b) a near-tier fires for the next-next maneuver prematurely, silently consuming `announcedSet[nearKey]` so the real near-tier never fires. Both are the class of failure this spec exists to prevent.

**Proposed fix:** Two changes, both in §4.3:

1. Clamp distance at the source. Before computing `ttm`:
   ```js
   var distToNext = Math.max(0, distanceToManeuver(snap, nextIdx));
   ```
2. Early-return when `distToNext === 0` AND `currentManeuverIdx` still reports the pre-maneuver index (a sentinel that the snap is at-or-past the boundary but state hasn't caught up):
   ```js
   if (distToNext === 0 && snap.segmentIndex >= m.begin_shape_index) return;
   ```

Additionally, §7 should add an edge case (E10?): "`distToNext` clamped to zero; when zero, near-tier fires only if `ttmPair[1] > 0` — which it always is — so the clamp is safe." §6.1 unit test matrix should add a cell where the snap's `segmentIndex === m.begin_shape_index && t > 0` to guard against regression.

**Sources:** `frontend/navigation.js:209-214` (`distanceToCoordIndex`), `frontend/navigation.js:309-313` (`distanceToManeuver`), `frontend/navigation.js:686-700` (`deadReckonTick`). Valhalla U-turn maneuver docs: https://valhalla.github.io/valhalla/api/turn-by-turn/api-reference/#maneuver-types (types 16/17 = uturn_right/left, shape-index semantics undocumented by Valhalla).

---

### F1.2 — Epsilon at threshold boundaries: `<=` vs `<` unspecified, floating-point comparison at integer seconds

**Severity:** MUST-FIX

**Claim in spec:** §4.3 uses `ttm <= ttmPair[1]` and `ttm <= ttmPair[0]` (inclusive). §5 invariants I1 and I2 assert "Exactly 2" / "Exactly 1" announcement counts. §6.1 asserts announcement count matches invariants across a matrix including the entry distance `{500, 80, 40, 10}` m and speeds `{30, 10, 3, 0}` m/s.

**Reality:** Floating-point division at matrix boundaries. Consider a unit test cell at `speed = 10 m/s, entry = 80m, costing = auto` (far_s = 30, near_s = 3, floor = 50):

- Simulated tick at dist = 300m: TTM = 300/10 = 30.0 exactly? **No.** Matrix simulates ticks at 1 Hz from entry. At tick 22, dist advances as `80 - 22*10 = -140`, so the approach actually ends around tick 8 at dist=0. But between tick 5 (dist=30) and tick 4 (dist=40), the 30m-equivalent far crossing happens at tick 5. TTM = 30/10 = **3.0** exactly. Far threshold 30s — dist is already 30m, so TTM = 3.0 < 30.0 — far fires.

Forget that test; consider the *actual* boundary case. A highway approach at `speed = 30 m/s` entering from `entry = 1000m`:

- Tick 1: dist = 1000, TTM = 1000/30 = **33.333…**. Not crossed.
- Tick 2: dist = 970, TTM = 32.333…. Not crossed.
- Tick 4: dist = 910, TTM = 30.333…. Not crossed.
- Tick 5: dist = 880 — but only if velocity is *exactly* 30 m/s. GPS speed is never exactly 30 m/s; it jitters around it. If `speedMedian()` returns 30.01 and dist is 900.0, TTM = 29.990… → **far fires**. If `speedMedian()` returns 29.99 and dist is 900.0, TTM = 30.011… → far does **not** fire. The single-sample difference between 29.99 and 30.01 — well within GPS noise — flips the announcement tick by one.

This is not directly a correctness bug *if* the invariants are "fires at or near the threshold." But I1/I2's claim of **"Exactly 2"** / **"Exactly 1"** announcements is tested against a simulator, and a deterministic simulator with integer-arithmetic speed (10.0 m/s exactly) will pass while a realistic noisy-speed simulator fails intermittently. The spec does not define simulator speed semantics — `simulateApproach({speed, entryDist, costing, steps})` in §6.1 is silent on whether `speed` is the deterministic tick-to-tick step or the mean of a noisy stream.

More critically: the `<=` operator with `MIN_SPEED_FLOOR = 1.0` produces one silent cliff. At `speedSamples = []` (empty) → `speedMedian()` returns 1.0 → `speed = max(1.0, 1.0) = 1.0` → `ttm = distToNext / 1.0 = distToNext` (as seconds numerically, but the units are bogus: distance-in-meters as time-in-seconds). When `distToNext = 30` exactly, `ttm = 30.0 <= 30.0` is **true** → far fires. When `distToNext = 30.00001`, it's false. This is not a bug; it's the designed fallback (§E2). But it means route-start at ≤ 30m auto triggers exactly one far-tier on the route-start tick. Combined with the ≤ 50m floor triggering near on the same tick (near wins, D1 suppresses far) — OK. But if entry is `30.5m`, neither TTM nor floor conditions fire on tick 1 (TTM = 30.5 > 30, dist = 30.5 < 50 → floor fires → near fires). Wait — 30.5 ≤ 50, so floor triggers near. So 1 prompt. Fine. But at `entry = 50.5m`, TTM = 50.5 > 30, dist = 50.5 > 50 — **nothing fires** on tick 1. User gets zero prompts until they move — but if they are stopped at a light, they never move, and `speedSamples` never populates → `speedMedian()` stays at `MIN_SPEED_FLOOR = 1.0` forever → TTM stays at 50.5 forever → **no prompt ever fires**. This violates G4 (prompt when stopped at turn).

**Impact:** G4 fails at `50m < distToNext ≤ (far_s × 1.0m/s) = 30m` gap — i.e., between 30m and 50m of distance with speed=0, the near-floor governs → fires; at exactly the floor (50m), fires; above the floor but below where far would fire if speed were realistic (80m city case: at 10 m/s, TTM = 8s, far would have already fired during the approach) — the user never stops here spontaneously. But the edge is real: if the driver starts navigation *while already stopped at a light 60m from a turn* (feasible in post-reroute or "start nav after already approaching" flows), they hear no prompt until they begin moving. That is arguably a bug since G4 explicitly guarantees "Near-tier prompt fires when the driver is stationary *at* the next maneuver" — and the design rationale in §4.3 point 2 asserts "at the floor distance (≤ 50m auto), near fires naturally." It does, but **only at distances ≤ 50m; between 50m and 60m at rest, nothing fires**, which a field tester would experience as "I started nav at the light, the turn is right there, why isn't the voice talking?"

**Proposed fix:** Three changes:

1. §4.3: explicitly document whether thresholds are `<=` (inclusive, current) or `<` (exclusive) and add a comment that the choice affects the count of ticks on which a threshold is "armed." Current `<=` is defensible; keep it.
2. §6.1: specify that `simulateApproach` uses deterministic integer-tick advancement (no noise) and document that noisy-stream behavior is covered by §6.2 outlier test. Or: add a §6.7 "Threshold-boundary jitter" test that injects ±0.5 m/s GPS noise over a 30-tick approach and asserts far-tier fires within a ±1-tick window of the noise-free baseline.
3. §7 (new E10): "Route-start at rest, 50m < dist ≤ (far_s × MIN_SPEED_FLOOR)m." Document the no-prompt case and either (a) accept it as a trivia-level bug, or (b) widen the floor to `far_s × MIN_SPEED_FLOOR = 30m` → that's narrower, not wider. Correct fix: set `VOICE_DISTANCE_FLOOR.auto = far_s × MIN_SPEED_FLOOR` = 30m × 1 = 30m? No — the floor is currently 50m, which is already wider than 30m. Check the arithmetic: `far = 30s, MIN_SPEED_FLOOR = 1.0m/s`, so at speed=1.0m/s, far fires at `ttm = 30s ≡ dist = 30m`. Floor is 50m (wider). So for `dist ∈ (50, ∞)` at speed=0, nothing fires — which is the bug. Fix: either (i) raise `MIN_SPEED_FLOOR` to make `far_s × MIN_SPEED_FLOOR ≥ VOICE_DISTANCE_FLOOR` — at 50m/30s = 1.67 m/s — which biases TTM unfavorably at low real speeds, or (ii) accept that the "at-rest" regime uses the floor and document that the floor (50m) is the "at-rest near-fire distance" with no at-rest far-tier.

**Sources:** §4.1 constants table, §4.3 algorithm, §5 invariants I1/I4, §6.1 test matrix.

---

### F1.3 — `speedSamples` never shifts back to empty, but **`applyReroute()` re-runs `tick()` with stale `lastSpeed` and EMPTY `speedSamples`**

**Severity:** MUST-FIX

**Claim in spec:** §4.2: "Integration into `reset()` and `applyReroute()`: both paths clear the sample window (`speedSamples = [];`)." §4.5 shows `applyReroute` ending with `if (lastGPS) tick(lastGPS);`.

**Reality:** Look at the sequence in §4.5's `applyReroute`:

1. `announcedSet = {};`
2. `speedSamples = [];`
3. `precomputeDistances();`
4. `state = "navigating";`
5. `if (lastGPS) tick(lastGPS);`

Step 5 immediately enters `tick()`, which calls `pushSpeedSample(gpsSpeed)` (§4.2 integration claim). At entry to `checkVoice()`, `speedSamples.length === 1` (the just-pushed sample). `speedMedian()` returns `sorted[0] = thatSingleSample`. If the driver was rerouted *because* GPS showed off-route (which is the triggering condition for most reroutes), the sample that caused the reroute may be anomalous — an outlier spike from stale Bluetooth pairing with a phone, a multipath echo, or the classic cold-start-GPS 50-m/s phantom velocity. The reroute-induced re-tick uses that single anomalous sample as the median.

Now compute: if the new route's first maneuver is 40m away and the single-sample speed is 50 m/s, TTM = 40/50 = **0.8s** < 3s near threshold → near fires → D1 suppresses far → driver hears ONE prompt at the moment of re-route. If the first maneuver is actually a quarter-mile away (400m away) with the reroute putting the user on a different road, TTM = 400/50 = **8s** < 30s far → far fires. Driver hears far-tier on a maneuver that, at realistic speed, is ~40 seconds away.

Meanwhile: the *very* scenario §G6 claims the design nails — "Reroute clears all voice state: `announcedSet` AND the speed-sample window. The new route's first prompt fires without suppression from prior state." — **is compromised by the reroute-tick's use of a single-sample warmup median**. The spec acknowledges this at §E1 ("at worst, one premature prompt per route") but the interaction with the post-reroute window is not documented: reroute typically happens during active driving where the driver is most cognitively loaded, and "one premature prompt" at that moment is the worst moment for it.

**Impact:** Post-reroute behavior is exactly the scenario this redesign is targeting (Villa Rita detour = rerouted 3-maneuver cluster). A single-sample warmup window that biases high under outlier speeds (per §4.2 comment) fires the far-tier too early on the new route. Combined with D1 suppression, this can either (a) make D1 fire for a maneuver that's far away and irrelevant, consuming the near-tier cache for that maneuver, or (b) fire a far-tier prematurely, contributing to the "too many prompts" regression the spec exists to fix.

**Proposed fix:** Three-layer defense:

1. §4.2: on `applyReroute`, **preserve the last N speed samples from the pre-reroute window** if they are within a plausibility band (e.g., 0.5× to 2× of `lastSpeed`). A driver who was going 10 m/s before the reroute is still going ~10 m/s after. Clearing to empty is unnecessary and harmful.
2. §4.3 (alternative): skip `checkVoice(snap)` entirely on the re-tick that `applyReroute` triggers. Add a `skipVoice` flag parameter to `tick()`. The re-tick's purpose is to push UI state and advance the snap; it does not need to fire voice prompts on the same frame as the reroute. The first *naturally-arriving* GPS tick after reroute (≤ 1 second later) will have `speedSamples.length === 1` still, but by tick 3 we're at full median. Delaying voice by 1-3 seconds post-reroute is operationally invisible.
3. §6.3 test: "Reroute state clearing" should explicitly assert that the re-tick does NOT fire `onVoiceCb` if the current fix is (2), OR that the retained speedSamples produce a sensible TTM if the fix is (1).

**Sources:** §4.5 `applyReroute` code block, §4.2 speed-smoothing section, §G6 invariant.

---

### F1.4 — D1 suppression can silently drop a legitimate far prompt in a short→long maneuver sequence with mid-cluster acceleration

**Severity:** MUST-FIX

**Claim in spec:** §4.3 lines 189-208 (the `if (nearWouldFire)` block): "on near-fire, also mark far as announced so it can never fire on a later tick. The driver hears exactly ONE prompt for this maneuver when they are already within near-tier at activation time." §5 I2 asserts "Exactly 1 announcement per maneuver when the driver's entry-point is already inside the near-tier condition."

**Reality:** D1 assumes that "near fires" implies "driver is actively executing this maneuver imminently." That's true for the maneuver the driver is *approaching*. But `announcedSet` is keyed on `nextIdx = currentManeuverIdx + 1` — the **single** maneuver ahead. Consider this sequence:

1. Driver approaches maneuver M (right turn), currently 40m away at 10 m/s.
2. `nearWouldFire` true (dist ≤ floor 50m). Near fires for M. `announcedSet['M-far'] = true`, `announcedSet['M-near'] = true`.
3. Driver executes M. `currentManeuverIdx` advances. New `nextIdx = M+1`.
4. Maneuver M+1 is 500m away (normal surface-street block). Driver accelerates to 30 m/s (merges onto arterial).
5. At speed 30 m/s, maneuver M+1's far-tier should fire at dist = 900m. Driver is at dist = 500m when they pick up speed. TTM = 500/30 = 16.7s — already past the 30s far threshold would have fired. **But** far-tier for M+1 has NOT been marked announced; `announcedSet[(M+1)-far]` is fresh. So far fires at a subsequent tick when TTM crosses 30 — which happens immediately (dist = 500, speed ≥ 16.7 m/s, TTM ≤ 30). **OK, no bug here.** Correction: my scenario doesn't trigger the bug.

Let me re-examine. The spec asks: "near-fire on a short-maneuver-then-long-maneuver sequence where the user's speed doubles mid-cluster." Consider:

1. Driver approaches M, 40m at 10 m/s. Near fires for M, D1 suppresses far for M. `currentManeuverIdx` incremented.
2. Maneuver M+1 is 30m PAST maneuver M (a close pair — e.g., "right onto X, then immediate right onto Y").
3. Driver is still 40m from M, which means driver is 70m from M+1. On the **same tick** that near fires for M, `checkVoice` examines only `nextIdx = M` — returns after firing M's near. M+1's far is not considered.
4. Next tick: driver moves to 30m from M. `currentManeuverIdx` is still M-1 (driver hasn't executed M yet). `nextIdx = M`. `announcedSet['M-near']` is true → `nearWouldFire` false. `announcedSet['M-far']` is true → `farWouldFire` false. Nothing fires. Driver passes M.
5. Driver executes M. `currentManeuverIdx = M`. `nextIdx = M+1`. Driver is now 30m from M+1 (it's a close pair). TTM = 30/10 = 3s = near threshold. Dist = 30m ≤ 50m floor. Near fires for M+1. Far suppressed. **Driver hears 2 prompts (one for M, one for M+1) in 30m of driving — fine.** Matches §6.4 Villa Rita scenario.

OK — still no bug. Let me try harder. The spec's attack prompt asks about "near-fire on a short-maneuver-then-long-maneuver sequence where the user's speed doubles mid-cluster." Consider:

1. Driver is at 2 m/s crawling in traffic, 60m from maneuver M. Near does NOT fire (dist = 60 > 50 floor, TTM = 30 > 3 near).
2. Far fires when TTM crosses 30: dist = 60, TTM = 30 — far fires. `announcedSet['M-far'] = true`.
3. Driver accelerates to 20 m/s (traffic clears). Now TTM = 60/20 = 3s at the moment the traffic clears — if dist is still ≈ 60 → TTM = 3 = near threshold. Near fires. D1 suppresses far (already announced, irrelevant). Same result as "single-prompt flow." 
4. **BUT:** this path fires two prompts (far at step 2, near at step 3) within a few seconds. I2's "exactly 1 when entering inside near-tier" does NOT apply here because the driver **entered from outside near-tier** — I1's "exactly 2 per maneuver" applies. Count: 2. Matches I1.

The bug I was hunting — "D1 silently drops a legitimate far prompt" — doesn't actually materialize in the core algorithm. The D1 consumption of farKey is tied to the *same* nextIdx whose nearKey fired. Subsequent maneuvers are separate keys, unaffected.

**However, a real D1 subtlety remains:** the distance-floor path. Consider:

1. Driver is at 40 m/s (highway), 300m from an off-ramp maneuver M.
2. TTM = 300/40 = 7.5s. Far threshold 30s — already past. Near threshold 3s — not yet. Dist = 300m — above floor 50m. Nothing fires.
3. Driver decelerates from 40 m/s to 10 m/s entering a congested exit zone. `speedMedian()` now returns 10. Dist = 150m (driver has moved). TTM = 15s — still past far's 30s threshold. Near: TTM 15s > 3s. Dist 150m > 50m. Nothing fires.
4. Driver decelerates to stop-and-go 1 m/s. TTM = 100m/1m/s = 100s. Nothing fires until dist ≤ 50m floor.
5. At dist = 50m, floor triggers near. D1 suppresses far. Driver hears **ONE prompt, 50m from the exit**, with no prior advance notice at highway speed.

This violates §G1 — "Exactly 2 voice prompts per maneuver when the driver enters from outside the far-tier threshold." The driver *did* enter from outside far-tier (at 300m highway, TTM = 7.5s was already inside far's 30s, so far should have fired). Wait — 7.5s < 30s means TTM IS inside far's threshold. Far should have fired on step 2. Let me recheck: TTM ≤ 30 means within far-tier. TTM = 7.5 ≤ 30 → TRUE → `farWouldFire` is TRUE. **Far fires at step 2.** Then steps 3-5 find far already announced; near fires at step 5.

OK, so on my highway example, far fires at dist=300m (giving ~7.5s advance notice at 40 m/s — the highway problem NG1 punts on but the math is correct). I1 is upheld.

So the actual finding is subtler: **D1 suppression is correct in the core case, but the spec's I2 prose conflates "driver enters inside near-tier" with "driver is close when the tick arrives." For the latter to be unambiguous, the spec must assert that `announcedSet` is cleared on maneuver index advance — which it implicitly is (keys are per-nextIdx), but this invariant is not called out.** If a reader re-implements D1 keyed on `currentManeuverIdx` (the maneuver the driver is ON, not the next one), D1 bleed-over between maneuvers becomes possible.

**Impact:** Low in the reference implementation as specified. But the spec's invariants I1/I2 are asserted as "by construction" — and the construction depends on the keying being `nextIdx`-scoped. A sloppy re-implementation that uses `currentManeuverIdx` as the D1 key (seemingly equivalent) would break I1 after the first near-fire.

**Proposed fix:** Reclassify from MUST-FIX to SHOULD-FIX in light of this re-examination; document explicitly:

1. §4.3 add a comment: "`announcedSet` keys use `nextIdx` (the upcoming maneuver), NOT `currentManeuverIdx` (the maneuver the driver is on). D1 suppression only affects the single upcoming maneuver and does not bleed across maneuver boundaries."
2. §5 I2: change "driver's entry-point is already inside the near-tier" to "nearKey for the upcoming maneuver fires before its farKey. D1 suppresses the farKey for that same maneuver only."
3. §6 test: add a cell that verifies far-tier for maneuver M+1 is NOT suppressed by a near-fire on maneuver M.

*Reclassifying to SHOULD-FIX after code re-inspection; retaining the finding because the ambiguity in I2's prose is real even if the reference implementation is correct.*

**Sources:** §4.3 algorithm, §5 I1/I2 invariants, §6.4 Villa Rita test.

---

### F1.5 — `speedMedian()` length-2 warmup bias is exploitable and the claim in §4.2 comment has an off-by-one

**Severity:** SHOULD-FIX

**Claim in spec:** §4.2 helper comment (lines 146-154):

```
// For length 3 (steady state): index 1 = true median.
// For length 1 (first tick): index 0 = only sample.
// For length 2 (warmup): index 1 = larger-of-two — biases slightly high during
// the single-tick warmup window; acceptable since TTM is dist/speed, so a
// biased-high speed yields a biased-low TTM (fires slightly early, not late).
```

**Reality:** The math is correct: `Math.floor(2/2) = 1` → `sorted[1]` = larger of two. But the stated acceptability claim ("fires slightly early, not late") does not hold uniformly:

1. **Speed-bias-high ≠ TTM-bias-low uniformly.** A high-biased speed decreases TTM. Smaller TTM makes threshold crossings **earlier in time** (in the spec's own words). But "earlier" is bad for a field-tester who's already complaining about too-many-prompts in the pre-remediation run. The band-aid commit `e63f6d9` that this spec replaces exists because prompts firing too early are the primary UX defect.

2. **The length-2 window persists for exactly 1 tick.** With 1 Hz GPS, that's 1 second. Under a noisy-GPS scenario (50 m/s spike at tick 2), the length-2 sample set is `[10, 50]` → sorted = `[10, 50]` → median = 50. TTM = dist/50 — a 5× underestimate of real TTM. If dist = 300m, TTM = 6s — well under far's 30s threshold. **Far fires 5× earlier than the no-outlier baseline would have fired.** The spec's §E1 acknowledges "at worst, one premature prompt per route" but this is a worst-case ~4.5× timing distortion, not a one-tick one.

3. **§I5 claim: "Once `speedSamples` is full (3 samples), median rejects any single outlier."** This holds for sample-3 rejecting sample-1 or sample-2 if the outlier is in the middle. But the `.shift()` policy in `pushSpeedSample` makes the window FIFO: outlier at position 0, then outlier at position 0 shifts to position-0 of a 2-element window? No — on the third push, the window becomes `[s1, s2, s3]`; on the fourth push, `[s2, s3, s4]`. So an outlier at `s1` is evicted by `s4`. Good. But an outlier at `s2` (the middle) lives in the window for 3 ticks total. Median rejects it at positions [s1, s2, s3] and [s2, s3, s4], but if `s3` is ALSO an outlier (common for correlated GPS glitches — multipath lasts multiple seconds), the window [s2, s3, s4] has median = s3 = outlier. I5's "single outlier per window" is the operative word — correlated double outliers defeat median-3.

**Impact:** One-second warmup windows that fire TTM thresholds 4-5× earlier than steady state. Correlated multi-tick GPS glitches (common in urban canyons, bridges, tunnels exiting, all classic navigation-pain environments) defeat the median-3 design. The spec's "1 premature per route" bound is understated.

**Proposed fix:**

1. §4.2: expand `SPEED_WINDOW_SIZE` from 3 to **5**. Median-of-5 rejects up to 2 correlated outliers. Cost: 2 extra ticks (2 seconds) to reach steady state. Acceptable; compared to the 2 seconds spent on the current warmup, the first 5 ticks are all "partial steadystate" anyway.
2. §4.2 change median algorithm to "median of samples with length ≥ 3; `MIN_SPEED_FLOOR` for length 0-2." This removes the length-2 larger-of-two bias entirely.
3. §4.2 (alternative, cheaper): explicitly cap single-tick pushSpeedSample inputs at `max(lastSpeed × 2.0, 5 m/s)` — a simple outlier-rejection band that prevents 50 m/s spikes from entering the window in the first place. `lastSpeed × 2.0` handles acceleration (doubling speed in 1 second is only possible in sports cars at ~0-60); `5 m/s` floor accommodates zero-to-moving transition.
4. §I5: reword to "A single-tick GPS speed outlier at a *non-central* position in the window does not cause a TTM threshold to fire…. Correlated multi-tick outliers are outside the design envelope and are mitigated by the band-cap in pushSpeedSample."

**Sources:** §4.2 `speedMedian()` helper, §5 I5 invariant, §E1 edge case.

---

### F1.6 — Valhalla verbal instruction fallback chain may produce `onVoiceCb("")`; downstream behavior is undefined

**Severity:** SHOULD-FIX

**Claim in spec:** §4.3 uses `text = m.verbal_pre_transition_instruction || m.instruction` for near-tier and `m.verbal_transition_alert_instruction || m.instruction` for far-tier. §E8: "Maneuver with empty `verbal_pre_transition_instruction` and empty `verbal_transition_alert_instruction`. Fallback to `m.instruction || ""`. Empty-string onVoiceCb: the near-tier logic still calls `onVoiceCb("")` because we did not add a guard — acceptable, the voice-picker / Web Speech API layer is robust to empty strings (preserves existing behavior from current code)."

**Reality:** The current code at `frontend/navigation.js:343-351` (the `announce()` helper that the spec deletes) has `if (muted || !text || !onVoiceCb) return false;` — the **`!text` guard is present in current code** and would reject empty strings. §4.3's proposed replacement inlines the muted check (`if (!muted && onVoiceCb) onVoiceCb(text);`) and DROPS the `!text` check. This is a regression, not a preservation of behavior. `onVoiceCb("")` is then invoked.

Downstream: `frontend/nav-ui.js:494-501`'s `onVoice(text)` — I'd need to re-read to confirm, but the composed voice-picker spec (2026-04-21) documents the callback forwarding `text` into `new SpeechSynthesisUtterance(text)`. Empty-string utterances:

- Chrome: `speechSynthesis.speak(new SpeechSynthesisUtterance(""))` silently completes (fires `start` then `end` with no audio).
- Safari: empty utterance fires `error` with `"synthesis-failed"` in some versions.
- Firefox: silently completes like Chrome.

Benign in Chrome, noisy in Safari (produces an error event that the voice-picker's `activePreviewUtterance` cleanup might handle, or might not — see voice-picker R1 F1.1).

More critically: Valhalla's verbal instruction fields are documented as **optional**. Per the Valhalla API reference (https://valhalla.github.io/valhalla/api/turn-by-turn/api-reference/#narrative), `verbal_pre_transition_instruction` and `verbal_transition_alert_instruction` are populated only when `directions_options.units` is set and the narration generator has text to emit. For certain maneuver types (`destination`, `start`, `merge` with no verbal narration), these fields are **absent from the JSON** — not just empty strings. `m.verbal_pre_transition_instruction || m.instruction` → if both are undefined, result is `undefined`. Then `if (afterIdx < …) text += ", then " + …` — **`undefined + ", then "` evaluates to `"undefined, then "`** (JavaScript string coercion of undefined).

**Impact:** On any maneuver where Valhalla omits both verbal fields AND the `m.instruction` is empty or undefined (rare but not impossible for arrival maneuvers), the voice speaks "undefined" (literally the string). This is the classic "the word undefined appears in a user-visible UI" bug.

**Proposed fix:** Three small changes:

1. §4.3: restore the `!text` guard in both near and far paths. Before `onVoiceCb(text)`, check `if (text && text.length > 0)`.
2. §4.3: defensively coerce `m.instruction` with `|| ""`: `var text = m.verbal_pre_transition_instruction || m.instruction || "";`.
3. §E8: revise to reflect that the `!text` guard IS present (after fix 1), and that an empty fallback means NO voice prompt fires, which is correct behavior — silence is better than "undefined" or an empty utterance triggering a Safari error event.

**Sources:** `frontend/navigation.js:343-351` current `announce()` with `!text` guard, Valhalla API narrative docs, §E8 spec.

---

### F1.7 — Dead-reckoning tick uses a stale speed median; DR's own extrapolation uses `lastSpeed` but voice uses `speedMedian()` — inconsistent

**Severity:** SHOULD-FIX

**Claim in spec:** §E7: "`deadReckonTick()` calls `checkVoice(drSnap)` with the dead-reckoned snap. `lastSpeed` from the last real GPS tick is used by DR's extrapolation but `speedMedian()` reads `speedSamples` — these do not update during DR. TTM during DR uses the last-real-median. Acceptable: GPS outage is rare and DR is short-lived (≤30s per `DEAD_RECKON_MAX`)."

**Reality:** Acceptability claim is the issue. DR extrapolates position using `lastSpeed` (a scalar). Voice TTM uses `speedMedian()` (a different scalar derived from the full samples window). These can diverge:

1. Driver GPS outage right after a deceleration. `lastSpeed = 2 m/s` (just before outage). `speedSamples = [10, 8, 2]` (the deceleration sequence). Median = 8.
2. DR extrapolates position at 2 m/s — correct for the "driver is stopping" scenario.
3. Voice TTM uses median = 8. TTM = drSnap.distToNext / 8. Far threshold 30s → dist = 240m. Near threshold 3s → dist = 24m.
4. DR position advances 2 m/s × 30s = 60m over the outage. At the start of outage, dist was 300m → at end, dist = 240m. TTM (using median 8) = 240/8 = 30s. Far fires at the end of the outage based on a speed the driver is no longer at.

Conversely: driver GPS outage after an acceleration. `lastSpeed = 30 m/s` (just before outage). `speedSamples = [2, 10, 30]`. Median = 10. DR advances position at 30 m/s (fast). Voice TTM uses 10 m/s (slow). DR's position shows dist = 100m after 20s outage (30 × 20 = 600m advance, clamped to route end or maneuver boundary). Voice TTM at dist=100m at speed 10 = 10s < 30s far. Far fires. But by then, the driver has ALREADY passed the maneuver (their real speed was 30 m/s, so they're 600m past where DR says they are — or they've passed the end of the route).

**Impact:** During the one-in-a-hundred-trips GPS outage event, voice prompts fire based on a speed that's decoupled from the DR's position extrapolation. The prompts' *timing* can be off by a factor of (lastSpeed / speedMedian), which under hard acceleration or braking is 3-5×. This is the scenario where the driver is MOST confused (GPS out, voice saying wrong things, dead-reckoned map showing wrong position) — compounding errors.

**Proposed fix:** Two options:

1. Simplest: during DR, use `lastSpeed` directly instead of `speedMedian()`. Both DR's position extrapolation and voice's TTM denominator use the same scalar.
   ```js
   var speed = drActive ? Math.max(lastSpeed, MIN_SPEED_FLOOR) : Math.max(speedMedian(), MIN_SPEED_FLOOR);
   ```
2. More defensible: skip `checkVoice()` during DR entirely. Add a `skipVoice` parameter to `checkVoice()` or gate the call site. Voice prompts can resume when real GPS returns. §G5 already accepts "short-lived DR" as an edge case; extending that to "no voice during DR" is a clean degradation.

§E7 should also explicitly document what happens to `announcedSet` state if DR fires a prompt that real GPS would have skipped — the cache is consumed, and when real GPS returns, the prompt is silently lost.

**Sources:** `frontend/navigation.js:686-700` `deadReckonTick()`, `frontend/navigation.js:420-482` `deadReckon()`, §E7 spec edge case.

---

### F1.8 — G2 claim "Villa Rita: 3 maneuvers → 3 prompts" assumes a specific route topology; the spec does not verify that the Villa Rita scenario meets the assumption

**Severity:** NICE-TO-HAVE

**Claim in spec:** §1, §G2, §6.4 all assert "Villa Rita post-reroute 3-maneuver cluster: 3 prompts total (one near-tier per maneuver; far suppressed by D1), down from 9."

**Reality:** The claim holds if and only if the driver enters each maneuver already inside the near-tier condition (TTM ≤ near_s OR dist ≤ floor). For three maneuvers spaced 30m apart (§6.4 synthetic test), the driver is always ≤ 60m from the next maneuver (30m for the immediate, 60m for the after-that). At 10 m/s, TTM to the immediate = 3s — near threshold boundary. TTM to after-next = 6s — outside near but inside far's 30s. So on tick 1 post-reroute:

- Near fires for M1 (TTM ≤ 3). D1 suppresses far for M1. `return` — M2's condition is not evaluated.
- Tick 2: driver at 20m from M1 (moved 10m in 1 sec). Near fires?  Actually M1's near is already announced. Nothing for M1. After M1 execution (say at tick 4), currentManeuverIdx advances.
- Meanwhile: far for M2 and M3 are still fresh. On tick 2, the spec evaluates `nextIdx = M1` (not yet advanced); M1 done; early return from far logic (announcedSet[M1-far] set).
- On tick 4, currentManeuverIdx = M1; nextIdx = M2. TTM = dist-to-M2/speed. If driver is between M1 and M2 at dist=15m (passed M1, approaching M2), TTM = 1.5s — near fires for M2. D1 suppresses far. And so on.

Count: one near per maneuver = 3 prompts. **Matches §G2.** Good.

But the synthetic test in §6.4 uses 30m spacing. Field Villa Rita was "~200 ft" = ~60m of rerouted driving total for 3 maneuvers — i.e., 20m spacing between maneuvers (approximate; the spec doesn't specify exact Villa Rita distances). At 20m spacing with entry 40m before M1:

- Tick 1: dist-to-M1 = 40 (near floor 50), dist-to-M2 = 60, dist-to-M3 = 80. Near fires for M1.
- Tick 2: driver at dist 30 from M1. currentManeuverIdx still pre-M1. Near already fired. Nothing.
- Tick 3: driver past M1 (dist=0 or negative per F1.1!). currentManeuverIdx = M1. nextIdx = M2. dist-to-M2 = 20-10 = 10m at 10 m/s. Near fires for M2.
- Etc.

Count: 3 prompts. Still matches. But: F1.1's negative-distance risk applies at every maneuver transition in this dense cluster. If at tick 3 the snap reports `dist-to-M2 = -5m` (snap walked past M2's begin_shape_index before currentManeuverIdx advanced), and the computed TTM is negative, and `announcedSet[M2-far]` is fresh, far *fires first* at the negative-TTM tick — adding a spurious prompt BEFORE the near fires on tick 4.

**Impact:** Under F1.1's negative-distance bug, §G2's "3 prompts, down from 9" can regress to 4-5 prompts in the dense Villa Rita cluster — better than 9 but worse than the spec claims.

**Proposed fix:** After fixing F1.1, re-verify §6.4's test synthesizes a snap sequence that includes the maneuver-transition boundary (`segmentIndex === m.end_shape_index` on tick N, → `segmentIndex === m.end_shape_index + 1` on tick N+1, with `currentManeuverIdx` advancing on tick N+1 via `findManeuverForSegment`). Assert that no spurious prompts fire during this 1-tick transition window.

**Sources:** §G2, §6.4, F1.1 interaction.

---

## Summary

- **MUST-FIX (3):** F1.1 (negative `distToNext` → all thresholds trivially true), F1.2 (G4 violated at 50m < dist ≤ 60m stopped-at-light gap), F1.3 (applyReroute's immediate re-tick uses single-sample warmup median at exactly the wrong moment).
- **SHOULD-FIX (4):** F1.4 (I2 prose ambiguity around D1 keying, reclassified after re-examination), F1.5 (median-3 window too small for correlated GPS glitches; length-2 warmup bias under-documented), F1.6 (regression of `!text` guard → `onVoiceCb("")` or `"undefined"`), F1.7 (DR voice decoupled from DR position via two speed scalars).
- **NICE-TO-HAVE (1):** F1.8 (Villa Rita 3-prompt claim fragile under F1.1's negative-distance bug).

Total: 8 findings across 3/4/1 severity tiers. The spec's algorithmic frame is sound — TTM is the right unit, D1 suppression halves announcement rate in dense clusters correctly — but the realism of `distanceToManeuver`'s sign, the timing of re-tick after reroute, and the breadth of the speed-smoothing window need hardening before ship.

Recommend: v2 addresses F1.1, F1.2, F1.3 in §4.3/§4.2 as MUST-FIX; F1.4-F1.7 as SHOULD-FIX prose/implementation notes; F1.8 absorbed into §6.4's test design after F1.1 is fixed.
