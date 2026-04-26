# Nav near-tier floor-fire prefix suppression — Implementation plan

**Date:** 2026-04-25
**Bug hunt:** [dev/bug-hunts/2026-04-24-nav-distance-post-m1-consolidated.md](../bug-hunts/2026-04-24-nav-distance-post-m1-consolidated.md) — confirmed bug B1
**Plan author:** manzanita
**Execution protocol:** `superpowers:subagent-driven-development` — single implementer dispatch executes 3 sequential commits in one session, then one final code-quality review covers the cumulative diff.
**Branch:** `dev` (no worktrees per CLAUDE.md ban).
**Field-test gate:** Cameron's re-drive Villa Rita → Costco. Acceptance: voice no longer says "In 200 feet" for turns user is actually <100 ft from. Floor-fires speak bare maneuver text ("Turn left onto X"); TTM-fires keep distance prefix ("In 100 feet, turn left onto X").

## Bug recap (one paragraph)

`VOICE_DISTANCE_FLOOR.auto = 75m` × 3.28084 = 246.1 ft → `Math.round(246/100)*100 = 200`. The 75m floor sits exactly inside the "In 200 feet" bucket. **Below 56 mph the floor always fires before TTM=3s, so every city/surface-street near-tier announcement deterministically says "200 feet"** regardless of actual user distance to the maneuver. Cameron's first turn (~90 ft, TTM-fire path won) said "100 feet" correctly; every subsequent turn floor-fired at 75m → "200 feet". Field-perceived inflation 5–10× because TTS playback completes ~20m later (user already at 50–55m) and cognitive recognition lands ~10–35m. Strategy B fix: distinguish TTM-fire from floor-fire; apply distance prefix on TTM-fires only; bare maneuver text on floor-fires.

## Existing state

- HEAD on `dev`: most recent nav-voice cycle commits land at `afef50c` (Phase D sweep). Sidebar work followed at `46bd08c` (Issue 3). Subsequent commits may include parallel ruler-stream work — irrelevant to this fix.
- Engine file: [frontend/navigation.js](../../frontend/navigation.js) — 1116 lines. Near-tier branch at lines 486–554.
- Test file: [frontend/tests/engine/navigation.test.mjs](../../frontend/tests/engine/navigation.test.mjs) — 80 tests at HEAD. Tests pinning the buggy "In 200 feet" output: I13a (`'I13: near-tier fires "In 200 feet, " prefix at 75 m floor'`), I13c (`'I13: imperial vs metric dispatch'`), I13g (`'I13g: full pipeline — multi-cue depart strips chain + applies live prefix'`).
- Spec: [docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md](../../docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md) §5.2, §5.4. The §5.4 Villa Rita walkthrough hard-codes "In 200 feet, ..." in the spec table — needs an addendum or update.

## Design — Strategy B detail

### Mechanical change (5 functional lines + 2 debug-log lines + 3 comment lines)

Inside `checkVoice` (frontend/navigation.js around lines 487–554), before the existing `if (nearWouldFire) { ... }` block:

```js
// Distinguish TTM-fire from floor-fire. TTM-fire = user approaching at speed,
// distance prefix is meaningful. Floor-fire = the floor caught it (slow approach
// or stationary), distance prefix would be misleading because the engine fires
// at ~75 m which always lands in the "200 feet" bucket regardless of how close
// the user actually is by the time TTS finishes. Bare maneuver text reads as
// imminent — same intent as the spec §5.1 30 m / 100 ft cutoff, re-grounded
// here via fire-mode rather than distance threshold (which is dead code in
// the current engine because near-tier never fires below 30 m).
var nearTTMFire   = ttm <= ttmPair[1];
var nearFloorFire = !nearTTMFire && distToNext <= floor;
```

Then inside the near-tier `if (nearWouldFire) { ... }` block, replace the existing single-flag pattern with two:

```js
// Single consume per tick (spec §5.3); used by both base and chain.
var gpsRecovery = consumeGPSRecoveryFlag();
// Base prefix suppressed on floor-fire OR GPS-recovery.
var skipBasePrefix = nearFloorFire || gpsRecovery;
// Chain prefix only suppressed on GPS-recovery — distBetween is precomputed
// from cumulativeDistances at start(), independent of live snap, so it's not
// stale on a recovery tick. Floor-fire status doesn't affect the chain because
// the chain text describes M_(n+1)→M_(n+2) (heads-up about the next turn after
// this one), which is genuinely informational regardless of whether THIS fire
// was floor- or TTM-triggered.
var skipChainPrefix = gpsRecovery;
```

Then update the two `if (!skipPrefix)` gates to use the distinct flags:
- Base text prefix: `if (!skipBasePrefix)` (was: `if (!skipPrefix)`)
- Chain-append prefix: `if (!skipChainPrefix)` (was: `if (!skipPrefix)`)

Finally, add `fireMode` to the existing `_geographicaTTMDebugLog` push for the near-tier branch:

```js
(window._geographicaTTMDebugLog = window._geographicaTTMDebugLog || []).push({
  timestamp: Date.now(),
  maneuverIdx: nextIdx,
  tier: 'near',
  fireMode: nearTTMFire ? 'ttm' : 'floor',  // NEW
  distToNext: distToNext,
  ttm: ttm,
  onRerouteRetick: false
});
```

### What the announcement sounds like under Strategy B

| Scenario | Speed | distToNext at fire | Old output | New output |
|---|---:|---:|---|---|
| Far-away approach, city speed (Cameron's main case) | 25 mph | 75m (floor-fire) | "In 200 feet, turn left onto X" | **"Turn left onto X"** |
| Close-start (Cameron's M1) | 25 mph | 27m (TTM-fire, 2.4s) | "In 100 feet, turn left onto X" | "In 100 feet, turn left onto X" (unchanged) |
| Highway approach | 60 mph | 80m (TTM-fire, 3s) | "In 300 feet, turn left onto X" | "In 300 feet, turn left onto X" (unchanged) |
| Slow parking lot | 5 mph | 75m (floor-fire) | "In 200 feet, turn left onto X" | **"Turn left onto X"** |
| Stationary at red light | 0 mph (clamped to 1.0) | 60m (floor-fire) | "In 200 feet, turn left onto X" | **"Turn left onto X"** |
| Floor-fire WITH chain | 25 mph | 75m → 459m chain | "In 200 feet, turn left onto X, then in 1/4 mile, turn right onto Y" | **"Turn left onto X, then in 1/4 mile, turn right onto Y"** |
| TTM-fire WITH chain | 25 mph | 27m → 459m chain | "In 100 feet, turn left onto X, then in 1/4 mile, turn right onto Y" | "In 100 feet, turn left onto X, then in 1/4 mile, turn right onto Y" (unchanged) |
| GPS-recovery first fresh tick | any | any | "Turn left onto X, then turn right onto Y" (no prefix on either) | "Turn left onto X, then turn right onto Y" (unchanged — gpsRecovery still gates both) |

Buffer-at-25-mph from Issue 1 is preserved (still firing at 75m); the *content* of the announcement changes from "In 200 feet, turn left onto X" to bare "Turn left onto X" — about 1s shorter at fast voice (no "In 200 feet, " preamble). Net: speech still finishes well before the turn, and the user no longer hears an inflated number.

### Why chain-append doesn't take floor-fire into account

The chain phrase "..., then in 1/4 mile, turn right onto Y" is genuinely heads-up info about the maneuver *after* the next one. Its distance argument (`distBetween`) is M_(n+1)→M_(n+2) leg length, computed from `cumulativeDistances` (precomputed at `start()`). That distance is meaningful as planning info regardless of whether the parent fire was TTM- or floor-triggered. Suppressing it on floor-fire would be over-suppression — chain heads-up is useful even on slow approaches.

GPS-recovery still suppresses both base and chain because on a recovery tick the *user-position* uncertainty propagates through the chain math (the chain attaches to text that the user receives at a timestamp where distance integrity is in doubt).

### What's NOT changing

- `VOICE_DISTANCE_FLOOR.auto = 75m`, `bicycle = 45m`, `pedestrian = 15m` — values unchanged.
- `VOICE_TTM` table — unchanged.
- `formatDistancePrefix` itself — unchanged. Bucketing math is correct given a meaningful input distance; the bug was *which* distances reached it, not *how* it bucketed them.
- `stripBakedDistance` — unchanged.
- Far-tier branch — unchanged. Far-tier always TTM-fires (no floor on far); prefix always applies.
- Chain-append's `distBetween` anchor — unchanged (per Cameron's D2 decision: keeps Reading A — `m.begin_shape_index` start anchor — which Cameron validated against Google Earth on his actual drive).
- The 30m / 100 ft cutoff in `formatDistancePrefix` — unchanged. Still empty-returns for sub-cutoff distances. Now that floor-fires don't apply the prefix, the cutoff is even more dead code than before — but harmless.
- GPS-recovery suppression scope — unchanged (still gates both base and chain).

## Pre-flight (mandatory)

```bash
cd /home/administrator/Code/geographica
git branch --show-current        # must be `dev`
git log -1 --format='%h %s'      # capture for post-flight comparison
git status --short                # expect only untracked dev/notes/ from parallel agent
```

If branch shifted: `git switch dev` then re-verify.

## Tasks

### Task 1: TDD-red — update existing tests that pin the bug, add new TTM-fire coverage

**Files:**
- Modify: [frontend/tests/engine/navigation.test.mjs](../../frontend/tests/engine/navigation.test.mjs)

**Read first** (mandatory; subagent has no prior session context):
- This plan in full (the Design section above is load-bearing for understanding which tests change and how).
- The bug-hunt consolidated report at [dev/bug-hunts/2026-04-24-nav-distance-post-m1-consolidated.md](../bug-hunts/2026-04-24-nav-distance-post-m1-consolidated.md) — particularly the executive summary and B1.
- [docs/pitfalls/testing-pitfalls.md](../../docs/pitfalls/testing-pitfalls.md) — TDD discipline.
- [frontend/tests/engine/navigation.test.mjs](../../frontend/tests/engine/navigation.test.mjs) — current tests at I13a, I13c (metric variant), I13g; current I14, I14b for GPS-recovery context (do not modify those).

**Step 1 — Update three existing tests to reflect Strategy B output.** These currently pin the buggy "In 200 feet, ..." output. Under Strategy B the floor-fire produces a bare maneuver string (chain prefix preserved):

Test 1 (`'I13: near-tier fires "In 200 feet, " prefix at 75 m floor'`, around line 1349 in navigation.test.mjs):
- Rename to `'I13: near-tier floor-fire produces bare base + chain prefix'`.
- Change the assertion regex from `/^In 200 feet, turn left onto First Street, then in 700 feet, turn right onto Second Road/` to `/^Turn left onto First Street, then in 700 feet, turn right onto Second Road/` (no "In 200 feet, " preamble; chain "then in 700 feet" preserved). Update the comment block above the assertion to explain the new expectation in terms of nearFloorFire path.

Test 2 (`'I13: imperial vs metric dispatch — same fixture switches units'`, around line 1390):
- Rename to `'I13: floor-fire metric/imperial dispatch produces bare base + chain prefix'`.
- Change the metric assertion regex from `/^In 70 meters, turn left onto First Street, then in 200 meters, turn right onto Second Road/` to `/^Turn left onto First Street, then in 200 meters, turn right onto Second Road/`. Comment update similarly.

Test 3 (`'I13g: full pipeline — multi-cue depart strips chain + applies live prefix'`, around line 1436):
- Rename to `'I13g: full pipeline — strip Valhalla chain + bare base on floor-fire'`.
- Change the assertion from `assert.equal(fires[fires.length - 1], 'In 200 feet, turn left onto Test Avenue.', ...)` to `assert.equal(fires[fires.length - 1], 'Turn left onto Test Avenue.', ...)`. Update the inline pipeline-trace comment block (the one that walks through stripBakedDistance → uppercase → prefix prepend) to reflect that prefix is suppressed because nearFloorFire = true (74m → ttm = 6.7 s > 3 s, so TTM path doesn't fire; floor lights it up; prefix suppressed).

DO NOT modify these tests:
- I13: cutoff suppresses near-tier prefix for very-short-spacing fixture (still valid — fires at <30m sub-cutoff, prefix already empty for orthogonal reason).
- I13: prompt count invariant on Villa Rita fixture (G9 regression guard) — count-only, no string assertion change needed (re-verify: count must remain 3 under Strategy B; running it post-implementation will confirm).
- I14, I14b — GPS-recovery tests; Strategy B doesn't change GPS-recovery suppression behavior (still suppresses both base and chain).

**Step 2 — Add one new test for the TTM-fire path** so the suite distinguishes the two fire modes. Insert it adjacent to the modified I13a:

```js
test('I13: near-tier TTM-fire applies prefix (close-start scenario)', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const { fixtureWiderCluster } = await import('./test_runner.mjs');
  win._geographicaUseImperial = true;
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 11 };
  const fires = [];
  nav.onVoice((t) => fires.push(t));
  nav.start(fixtureWiderCluster());
  // Drive to 30 m before M1 (M1 at -111.64780). 30 m at 11 m/s = TTM 2.7 s
  // -> ttm <= 3 s -> nearTTMFire wins, prefix applied.
  // Driver approaches from west (route start at -111.65000, M1 at -111.64780).
  // 30 m west of M1: 30 / (cos(35.2°) × 111000) ≈ 30 / 90791 ≈ 0.00033 deg.
  // longitude = -111.64780 - 0.00033 = -111.64813 (more negative = further west).
  for (let i = 0; i < 3; i++) {
    nav.updateGPS({ latitude: 35.20, longitude: -111.64813, speed: 11 });
  }
  assert.ok(fires.length >= 1, 'expected near-tier to fire');
  // 30 m → 98 ft → bucket 100 → "In 100 feet, "
  // Chain to M2 (200 m) → 656 ft → bucket 700 → "then in 700 feet, "
  assert.match(fires[fires.length - 1],
    /^In 100 feet, turn left onto First Street, then in 700 feet, turn right onto Second Road/,
    `expected TTM-fire prefix path, got: ${JSON.stringify(fires[fires.length - 1])}`);
});
```

Verify the longitude math before committing: at lat 35.20°, 1° lon ≈ 90791 m, so 30 m ≈ 0.00033°. M1 is at -111.64780; 30 m WEST (approaching from west) is `-111.64780 - 0.00033 = -111.64813`. Distance haversine'd: `|(-111.64813) - (-111.64780)| × 0.8171 × 111000 = 29.9 m`. ✓ Inside the 75m floor (so near-tier fires) AND TTM=29.9/11=2.7s ≤ 3s (so nearTTMFire wins). 29.9m → 98 ft → bucket 100. Assertion is "In 100 feet". ✓

**Step 3 — Run tests to verify failure.** From the project root:

```bash
node --test --test-force-exit frontend/tests/engine/ 2>&1 | tail -30
```

Expected at HEAD (before Task 2 implementation): the three updated assertions FAIL (current code emits "In 200 feet" / "In 70 meters" / "In 200 feet"); the new I13 TTM-fire test PASSES (current code already produces "In 100 feet" because at 30m the existing logic happens to generate that bucket — but it was lucky, not designed). Other tests PASS.

If a test you didn't intend to break is failing, STOP and report `BLOCKED`. Don't continue to Task 2 with broken non-target tests.

**Step 4 — Commit.** From the project root:

```bash
git add frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
test(nav): expect bare base text on near-tier floor-fire (Strategy B)

Three existing tests pinned the bug: I13 floor-fire imperial, I13 floor-fire
metric, I13g full-pipeline — all asserted "In 200 feet, ..." / "In 70 meters,
..." which is the buggy floor-fire output. Strategy B suppresses the prefix
on floor-triggered near-tier fires (chain prefix preserved), so the asserted
output is now bare maneuver text + chain.

New I13 TTM-fire test added: at 30 m / 11 m/s the TTM=2.7s threshold lights
near-tier first (nearTTMFire wins over nearFloorFire), prefix applied,
"In 100 feet, turn left onto First Street, then in 700 feet, turn right
onto Second Road" — confirming the prefix path still works for fast/close
approaches.

These tests FAIL at this commit; implementation lands in next commit.

Per bug-hunt B1, see dev/bug-hunts/2026-04-24-nav-distance-post-m1-consolidated.md
and dev/plans/2026-04-25-nav-distance-floor-fire-suppression-plan.md.

Agent: manzanita
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

**Step 5 — Post-flight branch check:**

```bash
git branch --show-current && git log -1 --format='%h %s'
```

If branch shifted: `git switch dev && git cherry-pick <your-sha>` then re-verify.

---

### Task 2: TDD-green — implement Strategy B in `checkVoice`

**Files:**
- Modify: [frontend/navigation.js](../../frontend/navigation.js)

**Read first:**
- This plan's Design section (the "Mechanical change" subsection has the exact replacement code).
- frontend/navigation.js lines 461–600 — the `checkVoice` function in full, both near-tier branch (around 486–554) and far-tier branch (around 556–600). Don't edit far-tier; you only need to read it for context (the asymmetry already exists there for stripBakedDistance / GPS-recovery and is left as-is per the bug-hunt's O2 deferral).

**Step 1 — Compute the fire-mode flags before the `nearWouldFire` evaluation.** Insert immediately above the existing line `var farKey = nextIdx + "-far";`:

Locate (exact match for the block):
```js
    var speed = Math.max(speedMedian(), MIN_SPEED_FLOOR);
    var ttm = distToNext / speed;

    var farKey = nextIdx + "-far";
    var nearKey = nextIdx + "-near";

    var nearWouldFire = !announcedSet[nearKey] &&
      (ttm <= ttmPair[1] || distToNext <= floor);
```

Replace with:
```js
    var speed = Math.max(speedMedian(), MIN_SPEED_FLOOR);
    var ttm = distToNext / speed;

    var farKey = nextIdx + "-far";
    var nearKey = nextIdx + "-near";

    // Distinguish TTM-fire from floor-fire (spec §5.2 + B1 floor-fire suppression).
    // TTM-fire = user is approaching at speed; distance prefix is meaningful.
    // Floor-fire = floor caught it (slow/stationary); engine fires at ~75 m
    // which always lands in the "200 feet" bucket regardless of how close the
    // user actually is by TTS-completion time. Bare maneuver text reads as
    // imminent — re-grounds the spec's 30 m / 100 ft cutoff intent via fire-
    // mode rather than a distance threshold (the cutoff was dead code because
    // near-tier never fires below 30 m in practice).
    var nearTTMFire   = ttm <= ttmPair[1];
    var nearFloorFire = !nearTTMFire && distToNext <= floor;
    var nearWouldFire = !announcedSet[nearKey] && (nearTTMFire || nearFloorFire);
```

**Step 2 — Inside the `if (nearWouldFire) { ... }` block, replace the single `skipPrefix` flag with the two-flag pattern.**

Locate (inside the near-tier branch, around current lines 509–517):
```js
      // GPS-recovery guard — single consume per tick, shared with chain-append below.
      var skipPrefix = consumeGPSRecoveryFlag();
      // Prepend live-distance prefix to base text (spec v2 §5.2).
      if (!skipPrefix) {
        var nearPrefix = formatDistancePrefix(distToNext, _geographicaUseImperial());
        if (nearPrefix && text && text.length > 0) {
          text = nearPrefix + text.charAt(0).toLowerCase() + text.slice(1);
        }
      }
```

Replace with:
```js
      // Single consume per tick (spec §5.3); used by both base and chain.
      var gpsRecovery = consumeGPSRecoveryFlag();
      // Base prefix suppressed on floor-fire OR GPS-recovery. Floor-fire
      // suppression matches the spec's "imminent prompt" intent for close-up
      // fires (B1 fix); GPS-recovery suppression preserves spec §5.3 semantics.
      var skipBasePrefix = nearFloorFire || gpsRecovery;
      // Chain prefix only suppressed on GPS-recovery — distBetween is precomputed
      // from cumulativeDistances, independent of live snap, so floor-fire status
      // doesn't affect chain accuracy. The chain heads-up about M_(n+1)→M_(n+2)
      // is genuinely informational regardless of how this fire was triggered.
      var skipChainPrefix = gpsRecovery;
      // Prepend live-distance prefix to base text (spec v2 §5.2).
      if (!skipBasePrefix) {
        var nearPrefix = formatDistancePrefix(distToNext, _geographicaUseImperial());
        if (nearPrefix && text && text.length > 0) {
          text = nearPrefix + text.charAt(0).toLowerCase() + text.slice(1);
        }
      }
```

**Step 3 — Update the chain-append's gate to use `skipChainPrefix`.**

Locate (around current lines 528–541, inside the `if (afterText)` block):
```js
            // Reuse skipPrefix from above — single consume per tick.
            var chainJoin;
            if (!skipPrefix) {
              var afterPrefix = formatDistancePrefix(distBetween, _geographicaUseImperial());
              if (afterPrefix) {
                var lcPrefix = afterPrefix.charAt(0).toLowerCase() + afterPrefix.slice(1);
                var lcAfter  = afterText.charAt(0).toLowerCase()  + afterText.slice(1);
                chainJoin = ", then " + lcPrefix + lcAfter;
              } else {
                chainJoin = ", then " + afterText;
              }
            } else {
              chainJoin = ", then " + afterText;
            }
```

There is exactly ONE `if (!skipPrefix)` in this block (the outer one immediately after the `// Reuse skipPrefix from above ...` comment). Replace it with `if (!skipChainPrefix)`. Do NOT touch the inner `if (afterPrefix) { ... } else { ... }` (it's not gated by `skipPrefix`). Do NOT touch the outer `} else { chainJoin = ", then " + afterText; }` branch (the only change is the condition). The comment line above should change to:

```js
            // Use skipChainPrefix — chain ignores floor-fire (heads-up about M2 is
            // valuable regardless), responds only to GPS-recovery.
```

**Step 4 — Add `fireMode` to the near-tier debug log.**

Locate (around current lines 547–560, inside the `if (window._geographicaTTMDebug)` block):
```js
          (window._geographicaTTMDebugLog = window._geographicaTTMDebugLog || []).push({
            timestamp: Date.now(),
            maneuverIdx: nextIdx,
            tier: 'near',
            distToNext: distToNext,
            ttm: ttm,
            // Always false: re-tick suppression early-returns at the top of
            // checkVoice before reaching this branch. If true ever appears in
            // a field-test log, suppressVoiceOnNextTick semantics broke.
            onRerouteRetick: false
          });
```

Insert a new key `fireMode` between `tier` and `distToNext`:
```js
          (window._geographicaTTMDebugLog = window._geographicaTTMDebugLog || []).push({
            timestamp: Date.now(),
            maneuverIdx: nextIdx,
            tier: 'near',
            fireMode: nearTTMFire ? 'ttm' : 'floor',
            distToNext: distToNext,
            ttm: ttm,
            // Always false: re-tick suppression early-returns at the top of
            // checkVoice before reaching this branch. If true ever appears in
            // a field-test log, suppressVoiceOnNextTick semantics broke.
            onRerouteRetick: false
          });
```

This addition is for Cameron's next field-test debugging. Production noise zero (only logs when `_geographicaTTMDebug` is set).

**Step 5 — Verify all engine tests pass.** From the project root:

```bash
node --test --test-force-exit frontend/tests/engine/ 2>&1 | tail -10
```

Expected: `# pass 81` (80 prior + 1 new I13 TTM-fire test from Task 1). All previously-failing assertions from Task 1 now PASS because Strategy B is implemented.

If any test fails: investigate before committing. Don't commit broken state. Common failure modes:
- I13 prompt count invariant on Villa Rita fixture: if this fails (counts ≠ 3), there's an unintended interaction between the two-flag pattern and the `announcedSet` marking. The marks happen BEFORE the prefix construction (G11), so prefix suppression shouldn't change which prompts fire — only their text. But verify.
- I14 / I14b GPS-recovery tests: gpsRecovery still gates both base and chain (skipChainPrefix = gpsRecovery includes it). Should pass unchanged.

**Step 6 — Self-review checklist before commit:**

1. `grep -n "skipPrefix\b" frontend/navigation.js` — should return ZERO hits. The variable name `skipPrefix` is fully replaced by `skipBasePrefix` and `skipChainPrefix`. (If a stray `skipPrefix` remains, the chain logic still uses the old flag and Task 1's failing tests will keep failing for the chain assertion.)
2. `grep -n "// NEW:" frontend/navigation.js` — must return zero hits.
3. ES5 syntax: only `var`, `function`, no arrow / template-literal / spread. (`grep -n "=>" frontend/navigation.js` — should match the pre-existing comment occurrences only; no new arrows in the changes.)
4. The G11 mark-order is preserved: `announcedSet[nearKey] = true; announcedSet[farKey] = true;` still happens BEFORE the new flag computation (those marks are at lines 507–508 in current code, before the `var gpsRecovery` line you added at line ~509). Don't reorder.
5. `consumeGPSRecoveryFlag()` is called EXACTLY ONCE in the near-tier branch. The far-tier branch has its own separate call at line ~570; you did NOT touch far-tier.

**Step 7 — Commit.** From the project root:

```bash
git add frontend/navigation.js
git commit -m "$(cat <<'EOF'
fix(nav): suppress distance prefix on near-tier floor-fires (B1)

Per bug-hunt B1 (dev/bug-hunts/2026-04-24-nav-distance-post-m1-consolidated.md):
VOICE_DISTANCE_FLOOR.auto = 75m × 3.28084 = 246.1ft → Math.round(246/100)*100
= 200, so every floor-triggered near-tier fire announced "In 200 feet"
deterministically at city/surface-street speeds (below the 56 mph crossover
where TTM=3s would beat floor=75m).

Strategy B (Cameron's call): distinguish TTM-fire from floor-fire. TTM-fires
keep the live distance prefix (meaningful: user is approaching at speed).
Floor-fires speak bare maneuver text ("Turn left onto X") — re-grounds the
spec §5.1 30 m / 100 ft cutoff intent ("imminent prompt") via fire-mode
rather than the dead-code distance threshold.

Chain prefix is preserved on floor-fire (the chain's distBetween is precomputed
from cumulativeDistances, not from live snap; chain is heads-up about M_(n+1)→
M_(n+2) which is genuinely informational regardless of how the parent fire
was triggered). GPS-recovery still suppresses both base and chain, unchanged.

Cameron's field-test report: at the actual turn (35 ft from M_(n+1)) the
voice was saying "In 200 feet" — a 5-10× perceived inflation. With Strategy
B, floor-fires (the dominant case at city speed) say bare "Turn left onto
X" — the imminent semantic that's correct for short-distance fires.

Adds fireMode field to _geographicaTTMDebugLog for future field-test triage.

VOICE_DISTANCE_FLOOR values are unchanged (Issue 1's buffer preserved).

Tests: 81/81 pass (80 prior + 1 new I13 TTM-fire coverage).

Agent: manzanita
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

**Step 8 — Post-flight check.**

---

### Task 3: Spec + impl-log + testing-pitfalls update

**Files:**
- Modify: [docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md](../../docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md) — add a v3 revision note describing the floor-fire suppression. Update §5.4 Villa Rita walkthrough to reflect Strategy B output (the table at lines 412–423 of the spec).
- Modify: [dev/implementation-log.md](../implementation-log.md) — add a 2026-04-25 entry above the most recent (2026-04-24 sidebar / nav-voice).
- Modify: [docs/pitfalls/testing-pitfalls.md](../../docs/pitfalls/testing-pitfalls.md) — add the new generalizable pitfall ("don't pin numeric output mappings without auditing the input source") drafted in the bug-hunt's test-gap analysis.

**Step 1 — Spec v3 revision note.** Append to the Revision history section (around line 11–13):

```markdown
- **v3 (2026-04-25)** — Field-test from Cameron (Villa Rita → 24th drive) surfaced B1: every auto floor-triggered near-tier fire produced "In 200 feet" deterministically because `VOICE_DISTANCE_FLOOR.auto = 75m` × 3.28084 = 246 ft maps to the "200 feet" bucket. Strategy B fix lands: distinguish TTM-fire (prefix applied) from floor-fire (bare maneuver text, chain prefix preserved). The 30 m / 100 ft cutoff intent ("read as imminent below this") is now re-grounded via fire-mode rather than the never-reachable distance threshold. Floor values unchanged; Issue 1 buffer preserved. See [bug-hunt](../../dev/bug-hunts/2026-04-24-nav-distance-post-m1-consolidated.md) and [plan](../../dev/plans/2026-04-25-nav-distance-floor-fire-suppression-plan.md).
```

**Step 2 — Update §5.4 Villa Rita walkthrough table** (lines ~412–423). Replace the spec-v2 expected text in each row that's a 75m floor-fire with the Strategy B output. For each row that says "Seg N near · 75 m" or "Seg N near+chain · 75 m":

- Old: `**"In 200 feet, turn left onto X, then in <chain>, turn left onto Y"**`
- New: `**"Turn left onto X, then in <chain>, turn left onto Y"**` (drop the "In 200 feet, " prefix; keep the chain phrase verbatim).

Specifically:
- Seg 0: drop "In 200 feet, " from the start of the spec-v2 text.
- Seg 1: same.
- Seg 2 near: same.
- Seg 3 near+chain: same.
- Seg 4 near+chain: same.
- Seg 5 near+chain: same.
- Seg 6 near+chain: same.
- Seg 7 near+chain: this is a 35 m floor-fire that previously announced "In 100 feet, turn right, then in 700 feet, your destination is on the left". It's a SHORT-LEG floor-fire (35m < 75m floor). Under Strategy B with a 35m fire: nearTTMFire = (35/9.2 = 3.8s > 3s = false), nearFloorFire = (35 ≤ 75 = true). Floor-fire → suppress base. New text: `**"Turn right, then in 700 feet, your destination is on the left"**` (drop "In 100 feet, ").

(Seg 2 far stays "In a quarter mile, turn right onto North Black Canyon Highway" — far-tier doesn't have a floor, only TTM-fires, so prefix always applies. Unchanged.)
(Seg 3 far stays "In a quarter mile, turn left onto West Utopia Road" — same reason. Unchanged.)

After the edits, the table should show: every "near" or "near+chain" row that was at the 75m/35m floor distance has lost its "In <distance>, " prefix; chain phrases are intact; far rows are unchanged.

Also update the "Speech-time check on the longest utterance (Seg 3 chain at 25 mph)" paragraph immediately below the table (around line 427–433). The longest utterance under Strategy B is the chain-only form: "Turn left onto West Utopia Road, then in 400 feet, turn left onto North Black Canyon Highway." — recompute word count (~12 words) and the fast-voice / slow-voice timing. The conclusion still holds (speech completes well before turn arrival); the new numbers are simply tighter than spec-v2's.

**Step 3 — Implementation log entry.** Insert ABOVE the most recent entry in [dev/implementation-log.md](../implementation-log.md) (the entry directly under the "---" separator near the top of the file):

```markdown
## 2026-04-25 — Nav voice floor-fire prefix suppression (B1 from field-test bug hunt)

**Released as:** not yet released (shipped on `dev`; ship gate is Cameron's re-drive of Villa Rita → Costco).
**Plan / spec:** [docs/superpowers/plans/2026-04-25-nav-distance-floor-fire-suppression-plan.md](../docs/superpowers/plans/2026-04-25-nav-distance-floor-fire-suppression-plan.md) · spec v3 update at [docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md](../docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md).
**Bug hunt:** [dev/bug-hunts/2026-04-24-nav-distance-post-m1-consolidated.md](../dev/bug-hunts/2026-04-24-nav-distance-post-m1-consolidated.md) — 3-hunter bug-hunt-cycle, all hunters HIGH-confidence convergence on the floor-bucket interaction.
**Execution protocol:** `superpowers:subagent-driven-development` — single implementer dispatch executing 3 sequential commits, then one final code-quality review.
**Agent moniker:** manzanita.

### Summary

Cameron's Villa Rita → 24th drive surfaced that the just-shipped (2026-04-24) live-distance prefix feature was announcing "In 200 feet" for every near-tier fire after M1, even when he was as close as 35 ft from the turn. Mechanism: VOICE_DISTANCE_FLOOR.auto = 75m × 3.28084 = 246.1 ft → bucket 200; the 75m floor sits at the top of the "In 200 feet" bucket; below 56 mph the floor always wins over TTM=3s, so every city/surface-street near-tier fire deterministically said "In 200 feet". The first turn was correct ("In 100 feet" via TTM-fire path) only because Cameron started ~27m from M1 — TTM threshold beat floor for that one case.

Strategy B (Cameron's call): suppress the live-distance prefix on floor-fires; preserve it on TTM-fires. The 30 m / 100 ft "imminent" intent from spec §5.1 is now re-grounded via fire-mode rather than the never-reachable distance threshold. Chain prefix is preserved on floor-fires (the chain's distBetween is precomputed from cumulativeDistances; floor-fire status doesn't affect chain accuracy). VOICE_DISTANCE_FLOOR values unchanged — Issue 1's buffer preserved.

### Key decisions

- **Strategy B over A**: Cameron rejected lowering the floor (would undo Issue 1's buffer that the previous cycle just shipped). Strategy B preserves the buffer, eliminates the implausible-distance failure mode, and aligns with the spec's "imminent" intent.
- **D2 chain anchor: keep Reading A** (current code, M_(n+1)→M_(n+2) leg length). Cameron validated against Google Earth on his actual drive — secondary turn distances are dead-on. The hunters' Reading B suggestion is treated as a false positive.
- **Defer O1 (NaN guard) and O2 (far-tier strip-on-recovery)** to a future cleanup commit. Both pre-existing minor improvements, orthogonal to B1.

### Notable bugs caught

- **B1**: VOICE_DISTANCE_FLOOR + 100-ft bucket interaction → all auto floor-fires "In 200 feet". Identified by the 3-hunter bug-hunt-cycle (HIGH consensus); Cameron's support-engineer intuition ("a decision table, formula, or lookup is hitting some kind of minimum") pointed directly at the mechanism class.

### Notable test gap

The existing test suite at navigation.test.mjs:1349-1411 explicitly *encoded* "In 200 feet" as the expected output for 75m floor-fires. The tests passed but were pinning the bug. Added a new entry to [docs/pitfalls/testing-pitfalls.md](../docs/pitfalls/testing-pitfalls.md) (#14): **"Don't pin numeric output mappings without auditing the input source."** Generalizable to any feature that uses tunable constants + bucketing.

### Commits

```
[Task 1 SHA]  test(nav): expect bare base text on near-tier floor-fire (Strategy B)
[Task 2 SHA]  fix(nav): suppress distance prefix on near-tier floor-fires (B1)
[Task 3 SHA]  docs(nav): spec v3 + impl-log + testing pitfall — floor-fire suppression
```

### Outcome

`node --test --test-force-exit frontend/tests/engine/` → **81 / 81 pass** at HEAD. Three I13 floor-fire tests rewrote their assertions to reflect bare base + chain prefix (the prior assertions were pinning B1's buggy output). One new I13 TTM-fire test confirms the prefix path still works for fast/close approaches.

`python -m pytest tests/ services/search/tests/` → no new regressions vs the known-pre-existing list.

**Ship gate:** Cameron re-drives Villa Rita → 19001 N 27th Ave Costco. Acceptance: voice no longer says "In 200 feet" for near turns (floor-fires are bare); near-tier prefix only on TTM-fires (which happen at higher speed or close-start scenarios). Buffer at 25 mph preserved (still firing at 75m / 6.7s).
```

**Step 4 — Add the testing-pitfall.** Append to [docs/pitfalls/testing-pitfalls.md](../../docs/pitfalls/testing-pitfalls.md). Match the existing one-section-per-pitfall format (numbered heading, 2-4 line body):

```markdown
## 14. Don't pin numeric output mappings without auditing the input source

When a test asserts `someFormatter(X) === "literal output Y"`, also audit *why X is what it is*. If X is sourced from a tunable constant elsewhere in the code (a floor, a threshold, a magic number), the test pins the bucket-rounding *and* implicitly pins the constant — every passing run rubber-stamps the constant's choice instead of validating the user-experience consequence.

Symptom: tests pass but the feature feels wrong in field testing because the output is mechanically correct given the input but the input was the wrong choice. Hit this on the 2026-04-25 nav voice floor-fire bug — `formatDistancePrefix(75, true) === "In 200 feet, "` was asserted as correct, but 75m was the bug; the assertion locked it in.

Defence: where a test asserts a numeric mapping, add a comment linking the input value to the originating constant + spec rationale, so a future reviewer can audit "is X still the right input?" alongside "does the function correctly map X → Y?"
```

(If pitfall numbering goes higher than 13 by the time you land this — e.g., a parallel session added one — increment to the next available number and adjust the in-text reference if any other entry references this one.)

**Step 5 — Run full test suite to confirm no regressions.**

```bash
node --test --test-force-exit frontend/tests/engine/ 2>&1 | tail -10
python -m pytest tests/ services/search/tests/ --tb=no -q 2>&1 | tail -10
```

Expected: engine 81/81 pass. Python: same known-pre-existing failures as the 2026-04-24 baseline (no NEW regressions). If a python test that wasn't pre-existing fails, STOP and investigate.

**Step 6 — Commit docs.**

```bash
git add docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md dev/implementation-log.md docs/pitfalls/testing-pitfalls.md
git commit -m "$(cat <<'EOF'
docs(nav): spec v3 + impl-log + testing pitfall — floor-fire suppression

Spec v3 revision note documents Strategy B (B1 fix), and §5.4 Villa Rita
walkthrough table is updated to reflect the bare-base floor-fire output
(chain phrases preserved; far rows unchanged because far-tier always
TTM-fires).

Implementation log captures the bug-hunt-cycle origin, design decisions
(Strategy B over A, D2 chain anchor false-positive resolution, O1/O2
deferral), and the new testing-pitfall.

Testing-pitfalls #14 added: don't pin numeric output mappings without
auditing the input source. Generalizable beyond nav-voice — applies to
any feature that uses tunable constants + bucketing.

Agent: manzanita
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

**Step 7 — Post-flight branch check.**

---

## Final review (after Task 3 completes)

Dispatch one code-reviewer subagent (`superpowers:code-reviewer`, Sonnet) over the cumulative diff `<Task-1-base>..HEAD -- frontend/ docs/ dev/`.

Lenses for the reviewer:
- **Spec conformance**: spec v3 + §5.4 table edits accurately reflect the implementation; Strategy B described correctly.
- **Behavior preservation**: TTM-fires still apply prefix (verified by the new I13 test); GPS-recovery still suppresses both base and chain (verified by I14/I14b unchanged); chain preserved on floor-fire (verified by I13 floor-fire chain assertions).
- **Code style**: ES5 maintained, no new globals, no `// NEW:` annotations, single `consumeGPSRecoveryFlag()` call per tick, G11 mark-order preserved.
- **Test quality**: assertion ordering (`assert.ok(fires.length >= N)` precedes match) preserved; new test's longitude math verified.
- **No accidental scope creep**: VOICE_DISTANCE_FLOOR values unchanged; far-tier branch unchanged; formatDistancePrefix unchanged.

If the final review surfaces a Critical, dispatch a fix subagent and re-review. If only Minors, defer them to a follow-up commit and proceed to ship-gate.

## Ship gate (Cameron's manual acceptance)

Cameron re-drives Villa Rita Dr → 19001 N 27th Ave Costco.

Acceptance criteria:
1. **No more "In 200 feet" on close-up turns**. Floor-fires (the dominant case at city/surface-street speeds) speak bare "Turn left onto X" / "Turn right onto Y" — no preamble distance.
2. **Chain heads-up preserved**. Compound announcements at chain-eligible maneuvers say "Turn left onto X, then in 1/4 mile, turn right onto Y" — chain phrase and distance correct (Cameron's Reading-A validation against Google Earth confirmed).
3. **Far-tier still gives heads-up at 30s out**. "In 1/4 mile, turn left onto X" still fires for the heads-up tier. Unchanged.
4. **TTM-fire still applies prefix when relevant**. If Cameron does a close-start scenario (begins nav within 30m of M1 at speed), he hears "In 100 feet, turn left onto X" — TTM-fire path. (Verifiable in the test suite; field test optional.)
5. **Buffer preserved at 25 mph**. Speech still finishes well before the turn (now ~1s sooner because the bare prompt is shorter). No "still in the air past the turn" regression from Issue 1.

If all pass → `git switch main && git merge --ff-only dev && git push origin main` (sidebar work also rides along, per the 2026-04-24 reduced-ship-gate decision).

## What NOT to do

- Do NOT change `VOICE_DISTANCE_FLOOR.auto` value — that's Strategy A, explicitly rejected by Cameron in favor of Strategy B.
- Do NOT change the chain-append's `distanceToManeuver({segmentIndex: m.begin_shape_index, t: 0}, afterIdx)` anchor — Cameron validated Reading A against Google Earth on his drive.
- Do NOT touch the far-tier branch — far-tier doesn't have a floor; prefix always applies via TTM-fire path; F5 (far-tier strip-on-recovery asymmetry) is deferred per O2.
- Do NOT touch `formatDistancePrefix` — the bucketing math is correct given a meaningful input; the bug was in *which distances reached it*.
- Do NOT add a NaN guard to `if (distToNext <= 0)` — that's F4/O1, deferred.
- Do NOT use `git worktree` (CLAUDE.md ban).
- Do NOT amend the previous nav-voice commits — all already pushed; add NEW commits for these fixes.
- **Do NOT add tests beyond the four specified in Task 1** (3 updated existing + 1 new TTM-fire). Additional coverage is welcome but must be a separate follow-up commit, NOT bundled with this fix.
- **Do NOT refactor adjacent code in `checkVoice`** — variable rename, comment cleanup, debug-log restructure (beyond adding `fireMode`), or any other "while I'm here" cleanup. The diff scope is exactly: 3 inserted/modified lines for fire-mode flags + 2 renamed `skipPrefix` → `skipBasePrefix`/`skipChainPrefix` instances + 1 added `fireMode` debug-log field + comment updates. Anything else is scope creep.
- Do NOT change `consumeGPSRecoveryFlag()` semantics or its single-call-per-tick discipline. The flag is consumed exactly once; both `skipBasePrefix` and `skipChainPrefix` derive from the cached `gpsRecovery` value.
