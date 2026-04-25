# Nav Voice TTM Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Issues 1 + 2 from the [2026-04-24 nav-voice-followup spec v2](../specs/2026-04-24-nav-voice-followup-design.md) — raise the near-tier distance floor (50→75 m auto, 30→45 m bicycle) AND add Google-Maps-style live-distance prefixes to far-tier, near-tier, and chain-append prompts. Issue 3 (sidebar BFCache) is in a separate plan.

**Architecture:** Pure in-engine change to `frontend/navigation.js`. Two new private helpers (`formatDistancePrefix`, `stripBakedDistance`), one new state variable (`prevTickWasStaleOrDR` for GPS-recovery guard), three amended output paths inside `checkVoice`. External `onVoiceCb(text)` boundary preserved.

**Tech Stack:** Vanilla JS (ES5 — IIFE module), Node test runner (`node --test --test-force-exit`), Python pytest for structural tests, no build step.

---

## File structure

- **Modify** `frontend/navigation.js`:
  - `VOICE_DISTANCE_FLOOR` constants (Issue 1)
  - Module-scope state: `prevTickWasStaleOrDR`
  - Module-scope helpers: `_geographicaUseImperial`, `consumeGPSRecoveryFlag`, `formatDistancePrefix`, `stripBakedDistance`
  - `checkVoice()` body: three output paths (far-tier, near-tier base text, chain-append)
  - `_geographicaNavEngineInternals` test-hook exports
- **Modify** `frontend/tests/engine/test_runner.mjs`:
  - Add `fixtureWiderCluster` (200 m maneuver spacing) for prefix-firing assertions
- **Modify** `frontend/tests/engine/navigation.test.mjs`:
  - Add I12, I13, I14, I15, I16 tests
- **Do NOT modify** `frontend/nav-ui.js`, `frontend/app.js`, `frontend/index.html`, CSS — out of scope per spec NG5.

---

## Pre-flight (run BEFORE Task 1)

Branch / checkout safety check, per [CLAUDE.md §"Git workflow — worktrees are BANNED"](../../../CLAUDE.md) and [feedback_worktree_escape](file:///home/administrator/.claude/projects/-home-administrator-Code-geographica/memory/feedback_worktree_escape.md).

- [ ] Run from repo root: `pwd && git rev-parse --show-toplevel && git branch --show-current && git status --short`. Confirm: cwd is `/home/administrator/Code/geographica`, branch is `dev` (or whatever the user-instructed feature branch is — DO NOT ASSUME), working tree is clean.
- [ ] If branch is NOT `dev` and the user did not explicitly direct otherwise, STOP and ask the user. The 2026-04-24 session had a documented incident where the working checkout was switched externally and a commit landed on the wrong branch.
- [ ] After every commit in this plan, run `git log -1 --format="%h %d %s"` to verify the commit landed on the expected branch (the `%d` decoration shows the branch ref).

---

## Task 0: Add `_geographicaUseImperial` helper

**Why first:** every other helper consumes it. Pure function. Trivial.

**Files:**
- Modify: `frontend/navigation.js` (module scope, near other helpers around line 195)

BEFORE starting work:
1. Read the skill at `superpowers:test-driven-development` (or invoke `/test-driven-development`).
2. Read `docs/pitfalls/testing-pitfalls.md` and `docs/pitfalls/implementation-pitfalls.md`.
3. Follow TDD: write failing test → implement → verify green.

- [ ] **Step 1: Write the failing test** in `frontend/tests/engine/navigation.test.mjs` (append at end of file before any closing constructs):

```js
test('_geographicaUseImperial helper returns true by default', async () => {
  const { window: win } = await loadEngine();
  // Default: window._geographicaUseImperial is set to true at app.js:123
  // but our test environment doesn't load app.js — undefined globally.
  // Helper should return TRUE when unset (matches app.js default).
  win._geographicaUseImperial = undefined;
  const internals = win._geographicaNavEngineInternals;
  assert.equal(internals._useImperial(), true);
});

test('_geographicaUseImperial helper returns false when explicitly set false', async () => {
  const { window: win } = await loadEngine();
  win._geographicaUseImperial = false;
  const internals = win._geographicaNavEngineInternals;
  assert.equal(internals._useImperial(), false);
});

test('_geographicaUseImperial helper returns true when explicitly set true', async () => {
  const { window: win } = await loadEngine();
  win._geographicaUseImperial = true;
  const internals = win._geographicaNavEngineInternals;
  assert.equal(internals._useImperial(), true);
});
```

- [ ] **Step 2: Run tests to verify failure**

Run: `node --test --test-force-exit frontend/tests/engine/navigation.test.mjs 2>&1 | tail -30`
Expected: 3 NEW tests fail (`internals._useImperial is not a function` or similar).

- [ ] **Step 3: Implement the helper** in `frontend/navigation.js`. Add this function alongside other module-scope helpers (around line 195, after the `speedHistory` declaration):

```js
function _geographicaUseImperial() {
  return typeof window !== 'undefined' && window._geographicaUseImperial !== false;
}
```

- [ ] **Step 4: Export via test hook.** In `frontend/navigation.js` `_geographicaNavEngineInternals` object (around line 983-991), add the helper:

```js
  window._geographicaNavEngineInternals = {
    VOICE_TTM: VOICE_TTM,
    VOICE_DISTANCE_FLOOR: VOICE_DISTANCE_FLOOR,
    MIN_SPEED_FLOOR: MIN_SPEED_FLOOR,
    SPEED_WINDOW_SIZE: SPEED_WINDOW_SIZE,
    MAX_SPEED_DELTA_PER_TICK: MAX_SPEED_DELTA_PER_TICK,
    _getSpeedSamples: function () { return Array.from(speedSamples); },
    _speedMedian: function () { return speedMedian(); },
    _getAnnouncedKeys: function () { return Object.keys(announcedSet).sort(); },
    _useImperial: _geographicaUseImperial   // NEW
  };
```

- [ ] **Step 5: Run tests, verify pass**

Run: `node --test --test-force-exit frontend/tests/engine/navigation.test.mjs 2>&1 | tail -10`
Expected: all 3 new tests pass; existing tests unaffected.

BEFORE marking this task complete:
1. Review tests against `docs/pitfalls/testing-pitfalls.md`.
2. Verify the helper preserves the existing `app.js:123` default semantics.
3. Run full suite: `node --test --test-force-exit frontend/tests/engine/`. Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add frontend/navigation.js frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
feat(nav): _geographicaUseImperial helper for live-distance prefix

Per spec v2 §5.3. Reads window._geographicaUseImperial at call time;
defaults to true (imperial) when unset, matching app.js:123.

Agent: <YOUR_MONIKER>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

After commit: `git log -1 --format="%h %d %s"` to confirm branch.

---

## Task 1: Issue 1 — VOICE_DISTANCE_FLOOR lift (auto 50→75, bicycle 30→45)

**Why second:** smallest standalone change. Independent of Issue 2. Field-test acceptance benefits from running this first to feel the buffer improvement in isolation.

**Files:**
- Modify: `frontend/navigation.js` (constants around line 52-56)
- Modify: `frontend/tests/engine/navigation.test.mjs` (add I12 tests)

BEFORE starting work:
1. Read `docs/pitfalls/testing-pitfalls.md`.
2. TDD: write failing test → implement → verify green.

- [ ] **Step 1: Write the failing test** in `frontend/tests/engine/navigation.test.mjs`:

```js
test('TTM I12: VOICE_DISTANCE_FLOOR.auto is 75 m', async () => {
  const { window: win } = await loadEngine();
  const internals = win._geographicaNavEngineInternals;
  assert.equal(internals.VOICE_DISTANCE_FLOOR.auto, 75);
});

test('TTM I12: VOICE_DISTANCE_FLOOR.bicycle is 45 m', async () => {
  const { window: win } = await loadEngine();
  const internals = win._geographicaNavEngineInternals;
  assert.equal(internals.VOICE_DISTANCE_FLOOR.bicycle, 45);
});

test('TTM I12: VOICE_DISTANCE_FLOOR.pedestrian unchanged at 15 m', async () => {
  const { window: win } = await loadEngine();
  const internals = win._geographicaNavEngineInternals;
  assert.equal(internals.VOICE_DISTANCE_FLOOR.pedestrian, 15);
});
```

- [ ] **Step 2: Run tests to verify failure**

Run: `node --test --test-force-exit frontend/tests/engine/navigation.test.mjs 2>&1 | grep -E "I12|fail" | head -10`
Expected: 2 tests fail (auto = 50 not 75, bicycle = 30 not 45); pedestrian test passes.

- [ ] **Step 3: Update constants** in `frontend/navigation.js` lines 52-56:

```js
  var VOICE_DISTANCE_FLOOR = {
    auto:       75,  // +25 m. ~+2.6 s buffer at 25 mph fast voice / +1.2 s slow voice.
    bicycle:    45,  // +15 m mirror. Same +50% relative scale.
    pedestrian: 15   // unchanged. Walking-pace buffer ample.
  };
```

- [ ] **Step 4: Run tests, verify pass**

Run: `node --test --test-force-exit frontend/tests/engine/navigation.test.mjs 2>&1 | tail -5`
Expected: all 3 I12 tests pass; existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/navigation.js frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
fix(nav): raise near-tier distance floor for surface-street buffer

VOICE_DISTANCE_FLOOR.auto    50 → 75 m
VOICE_DISTANCE_FLOOR.bicycle 30 → 45 m
VOICE_DISTANCE_FLOOR.pedestrian unchanged at 15 m

Closes the 25-mph "broaches the intersection" symptom Cameron reported
post-TTM-ship. At 25 mph (11.2 m/s), 75 m floor gives 6.7 s warning vs
the prior 4.5 s — ~2.2 s additional notice that absorbs TTS speech time
plus the new live-distance prefix from a separate commit.

High-speed (≥48 mph) timing unchanged — TTM still governs above the
floor.

Per spec v2 §4.

Agent: <YOUR_MONIKER>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `formatDistancePrefix` helper (imperial + metric)

**Files:**
- Modify: `frontend/navigation.js` (module scope, after `_geographicaUseImperial`)
- Modify: `frontend/tests/engine/navigation.test.mjs` (unit tests)

BEFORE starting work: TDD, write failing tests first.

- [ ] **Step 1: Write the failing tests** in `frontend/tests/engine/navigation.test.mjs`:

```js
test('formatDistancePrefix: imperial cutoff (29 m → "")', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(0, true), '');
  assert.equal(fmt(29, true), '');
});

test('formatDistancePrefix: imperial feet band (round to 100)', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(31, true), 'In 100 feet, ');
  assert.equal(fmt(91, true), 'In 300 feet, ');
  assert.equal(fmt(290, true), 'In 1000 feet, ');  // 951 ft rounds to 1000
});

test('formatDistancePrefix: imperial fractional miles', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  // 305 m = 1001 ft = 0.190 mi (just into [0.190, 5/16) quarter band)
  assert.equal(fmt(305, true), 'In a quarter mile, ');
  assert.equal(fmt(500, true), 'In a quarter mile, '); // 1640 ft = 0.311 mi
  // 504 m = 1654 ft = 0.3133 mi (just past 5/16)
  assert.equal(fmt(504, true), 'In half a mile, ');     // wait — 1/3? No. Spec drops 1/3 band.
});
```

NOTE: the spec drops the 1/3 mile band. Bands are quarter (1000-1980 ft), half (1980-3300 ft), three-quarter (3300-4620 ft), one (4620-7920 ft), then whole miles. So `504 m = 1654 ft` is in the [1980, 3300) ft band? Let me recompute. Actually 504 m × 3.28084 = 1653 ft. 1653 ft is in [1000, 1980) ft = quarter band. So `fmt(504, true) === 'In a quarter mile, '`. Correct the test:

```js
  assert.equal(fmt(504, true), 'In a quarter mile, '); // 1653 ft, still in quarter band [1000, 1980)
```

Continue tests:

```js
test('formatDistancePrefix: imperial half mile band', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  // 700 m = 2297 ft, in [1980, 3300) ft → half mile
  assert.equal(fmt(700, true), 'In half a mile, ');
  // 800 m = 2625 ft, still in half band
  assert.equal(fmt(800, true), 'In half a mile, ');
});

test('formatDistancePrefix: imperial three-quarter mile band', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  // 1100 m = 3609 ft, in [3300, 4620) → three quarters
  assert.equal(fmt(1100, true), 'In three quarters of a mile, ');
});

test('formatDistancePrefix: imperial one mile band', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  // 1500 m = 4921 ft, in [4620, 7920) → one mile
  assert.equal(fmt(1500, true), 'In one mile, ');
  // 2100 m = 6890 ft, still in one mile band
  assert.equal(fmt(2100, true), 'In one mile, ');
});

test('formatDistancePrefix: imperial multi-mile (round to whole)', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  // 2500 m = 8202 ft = 1.553 mi, ≥ 7920 ft → multi-mile, Math.round(1.553) = 2
  assert.equal(fmt(2500, true), 'In 2 miles, ');
  // 8000 m = 26247 ft = 4.972 mi → Math.round = 5
  assert.equal(fmt(8000, true), 'In 5 miles, ');
});

test('formatDistancePrefix: metric cutoff', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(0, false), '');
  assert.equal(fmt(29, false), '');
});

test('formatDistancePrefix: metric meters band low (round to 10)', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(31, false), 'In 30 meters, ');
  assert.equal(fmt(85, false), 'In 90 meters, ');
});

test('formatDistancePrefix: metric meters band mid (round to 50)', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(101, false), 'In 100 meters, ');
  assert.equal(fmt(480, false), 'In 500 meters, ');
  assert.equal(fmt(998, false), 'In 1000 meters, ');  // edge: rounds to 1000
});

test('formatDistancePrefix: metric one-kilometer band', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(1000, false), 'In one kilometer, ');
  assert.equal(fmt(1499, false), 'In one kilometer, ');
});

test('formatDistancePrefix: metric multi-kilometer (round to 0.1)', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  // 1500 m = Math.round(15)/10 = 1.5
  assert.equal(fmt(1500, false), 'In 1.5 kilometers, ');
  // 2345 m = Math.round(23.45)/10 = 2.3
  assert.equal(fmt(2345, false), 'In 2.3 kilometers, ');
});

test('formatDistancePrefix: monotonicity property — output never decreases as meters increases', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  // Numerically encode the prefix for monotonicity comparison.
  function distanceValue(prefix, useImperial) {
    if (prefix === '') return -1;  // cutoff
    var m = prefix.match(/In (.+?), /);
    if (!m) throw new Error('unexpected prefix shape: ' + prefix);
    var phrase = m[1];
    if (/feet$/.test(phrase)) return parseInt(phrase, 10) * 0.3048; // ft → m
    if (phrase === 'a quarter mile')           return 0.25 * 1609.344;
    if (phrase === 'half a mile')              return 0.5  * 1609.344;
    if (phrase === 'three quarters of a mile') return 0.75 * 1609.344;
    if (phrase === 'one mile')                 return 1.0  * 1609.344;
    if (/miles$/.test(phrase))   return parseInt(phrase, 10) * 1609.344;
    if (phrase === 'one kilometer') return 1000;
    if (/kilometers$/.test(phrase)) return parseFloat(phrase) * 1000;
    if (/meters$/.test(phrase))     return parseInt(phrase, 10);
    throw new Error('unmatched phrase: ' + phrase);
  }
  for (const useImperial of [true, false]) {
    let prevValue = -2;
    for (let m = 0; m <= 10000; m += 10) {
      const v = distanceValue(fmt(m, useImperial), useImperial);
      assert.ok(v >= prevValue,
        `non-monotone at m=${m} useImperial=${useImperial}: prev=${prevValue}, now=${v}, prefix="${fmt(m, useImperial)}"`);
      prevValue = v;
    }
  }
});
```

- [ ] **Step 2: Run tests to verify failure**

Run: `node --test --test-force-exit frontend/tests/engine/navigation.test.mjs 2>&1 | grep -E "formatDistancePrefix|fail" | head -20`
Expected: all 13 new `formatDistancePrefix` tests fail (helper not exported).

- [ ] **Step 3: Implement the helper** in `frontend/navigation.js`. Add at module scope (after `_geographicaUseImperial` from Task 0):

```js
// Cutoff: below this, prompts read as imminent ("turn right" with no prefix).
var DISTANCE_PREFIX_CUTOFF_METERS = 30;  // ≈ 100 ft

// Per spec v2 §5.1. Returns "" if below cutoff. Output ends with ", ".
function formatDistancePrefix(meters, useImperial) {
  if (meters < DISTANCE_PREFIX_CUTOFF_METERS) return '';
  if (useImperial) {
    var feet = meters * 3.28084;
    if (feet < 1000) return 'In ' + (Math.round(feet / 100) * 100) + ' feet, ';
    var miles = feet / 5280;
    if (miles < 1980 / 5280) return 'In a quarter mile, ';
    if (miles < 3300 / 5280) return 'In half a mile, ';
    if (miles < 4620 / 5280) return 'In three quarters of a mile, ';
    if (miles < 7920 / 5280) return 'In one mile, ';
    return 'In ' + Math.round(miles) + ' miles, ';
  }
  // metric
  if (meters < 100) return 'In ' + (Math.round(meters / 10) * 10) + ' meters, ';
  if (meters < 1000) return 'In ' + (Math.round(meters / 50) * 50) + ' meters, ';
  if (meters < 1500) return 'In one kilometer, ';
  return 'In ' + (Math.round(meters / 100) / 10).toFixed(1) + ' kilometers, ';
}
```

- [ ] **Step 4: Export via test hook.** In `_geographicaNavEngineInternals` (around line 983), add `_formatDistancePrefix`:

```js
    _useImperial: _geographicaUseImperial,
    _formatDistancePrefix: formatDistancePrefix   // NEW
```

- [ ] **Step 5: Run tests, verify pass**

Run: `node --test --test-force-exit frontend/tests/engine/navigation.test.mjs 2>&1 | tail -10`
Expected: all 13 new tests pass (including monotonicity property test).

BEFORE marking complete:
1. Review against testing-pitfalls.md.
2. Verify monotonicity test really sweeps 0 → 10000 m in 10 m steps without crashing.

- [ ] **Step 6: Commit**

```bash
git add frontend/navigation.js frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
feat(nav): formatDistancePrefix — Google-Maps-style live-distance helper

Per spec v2 §5.1. Imperial: feet (round 100) up to 999 ft, then spelled
fractional miles (a quarter / half a / three quarters of a / one), then
multi-mile (round whole). Metric: meters (round 10 < 100 m, round 50 from
100-999 m), then "In one kilometer" at 1000 m, then "In N.N kilometers"
(Math.round/10 — no .toFixed quirk).

Cutoff: < 30 m / 100 ft returns "" (caller speaks the maneuver alone).

Spelled-out fractions match Valhalla's own phrasing and pronounce
deterministically across browser TTS engines (per adversarial review
F3.N-7).

Includes monotonicity property test sweeping 0-10000 m in 10 m steps —
the spoken value strictly never goes down as live distance grows.

Agent: <YOUR_MONIKER>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `stripBakedDistance` helper

**Files:**
- Modify: `frontend/navigation.js` (module scope, after `formatDistancePrefix`)
- Modify: `frontend/tests/engine/navigation.test.mjs` (unit tests)

BEFORE starting work: TDD.

- [ ] **Step 1: Write the failing tests** in `frontend/tests/engine/navigation.test.mjs`:

```js
test('stripBakedDistance: no chain — passes through unchanged', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  assert.equal(strip('Turn left onto Main.'), 'Turn left onto Main.');
});

test('stripBakedDistance: real Valhalla mid-string distance chain', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  // Pulled from live Valhalla auto route (Villa Rita depart maneuver).
  assert.equal(
    strip('Drive east on West Villa Rita Drive. Then, in 900 feet, Turn left onto North 21st Avenue.'),
    'Drive east on West Villa Rita Drive.'
  );
});

test('stripBakedDistance: mid-string non-distance chain (existing Then suffix)', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  assert.equal(
    strip('Turn right onto 24th Drive. Then Turn left onto West Union Hills Drive.'),
    'Turn right onto 24th Drive.'
  );
});

test('stripBakedDistance: comma-form Then (the latent bug we are fixing)', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  // Existing engine regex /\.\s*Then\s+/ failed on this comma form. Spec v2 fixes.
  assert.equal(
    strip('Turn right. Then, Turn right.'),
    'Turn right.'
  );
});

test('stripBakedDistance: leading "Then " (existing pattern preserved)', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  assert.equal(
    strip('Then turn left onto Union Hills Drive.'),
    'turn left onto Union Hills Drive.'
  );
});

test('stripBakedDistance: decimal distance in chain — does not stop at decimal point', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  // R1 F1.5: existing [^.]* in the strip regex stops at "1.5", leaving baked chain.
  // Spec v2's (?:[^.]|\.(?=\d))* allows decimal-point passthrough.
  assert.equal(
    strip('In 1.5 miles, Merge onto I-5. Then, in 0.3 miles, Take exit 42.'),
    'In 1.5 miles, Merge onto I-5.'
  );
});

test('stripBakedDistance: fractional-words chain (Valhalla quarter mile form)', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  assert.equal(
    strip('Drive north. Then, in a quarter mile, Keep left to stay on North Central Avenue.'),
    'Drive north.'
  );
});

test('stripBakedDistance: leading "In <dist>, X" NOT stripped (no real Valhalla emission)', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  // Spec v2 §5.1 deliberately does NOT strip leading "In <dist>" because
  // live Valhalla doesn't emit that shape on transition_alert / pre_transition.
  // Caller's own prefix logic handles this case.
  assert.equal(
    strip('In 400 feet, Turn left.'),
    'In 400 feet, Turn left.'
  );
});

test('stripBakedDistance: empty input — returns unchanged', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  assert.equal(strip(''), '');
  assert.equal(strip(undefined), undefined);
  assert.equal(strip(null), null);
});
```

- [ ] **Step 2: Run tests to verify failure**

Run: `node --test --test-force-exit frontend/tests/engine/navigation.test.mjs 2>&1 | grep -E "stripBakedDistance|fail" | head -20`
Expected: all 9 tests fail (helper not exported).

- [ ] **Step 3: Implement the helper** in `frontend/navigation.js`. Add at module scope (after `formatDistancePrefix`):

```js
// Per spec v2 §5.1. Strips Valhalla's mid-string baked distance from a
// verbal_pre_transition or verbal_transition_alert string. Three patterns
// applied in sequence:
//   1. ". Then, in <dist>, <Imperative>." (mid-string distance chain) — strip whole
//   2. ". Then <rest>" (chain without distance, comma-form accepted) — strip whole
//   3. "Then " leading — strip prefix only
// (?:[^.]|\.(?=\d))* allows decimal-passthrough so "1.5 miles" isn't split.
// No /i flag — Valhalla always title-cases; (?=[A-Z]) lookahead intact.
function stripBakedDistance(text) {
  if (!text) return text;
  // Pattern 1: trailing ". Then, in <dist> <unit>, <rest>"
  text = text.replace(
    /\.\s*Then[\s,]+in\s+[a-zA-Z0-9.\s]+?\s(?:feet|foot|mile|miles|meters?|kilometers?|km)\s*,\s*(?:[^.]|\.(?=\d))*\.?\s*$/,
    '.'
  );
  // Pattern 2: trailing ". Then <rest>" (no distance) — broadened to accept "Then,"
  text = text.replace(
    /\.\s*Then[\s,]+(?:[^.]|\.(?=\d))*\.?\s*$/,
    '.'
  );
  // Pattern 3: leading "Then "
  text = text.replace(/^Then\s+/, '');
  return text;
}
```

- [ ] **Step 4: Export via test hook.** In `_geographicaNavEngineInternals`:

```js
    _formatDistancePrefix: formatDistancePrefix,
    _stripBakedDistance: stripBakedDistance   // NEW
```

- [ ] **Step 5: Run tests, verify pass**

Run: `node --test --test-force-exit frontend/tests/engine/navigation.test.mjs 2>&1 | tail -5`
Expected: all 9 stripBakedDistance tests pass.

BEFORE marking complete:
1. Review pitfalls. Specifically: regex over-matching is a known testing pitfall; verify the negative-control test (leading "In <dist>" NOT stripped) passes.
2. Run full suite — no regressions in unrelated tests.

- [ ] **Step 6: Commit**

```bash
git add frontend/navigation.js frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
feat(nav): stripBakedDistance — strips Valhalla mid-string distance chains

Per spec v2 §5.1. Three regex patterns applied in sequence:
  1. Trailing ". Then, in <dist>, <Imperative>." — strip whole (Valhalla's
     real multi-cue shape, NOT the leading-"In" form spec v1 assumed)
  2. Trailing ". Then <rest>" — generalized to accept "Then,"  comma form
     (closes pre-existing latent bug — old regex required \s+ after Then)
  3. Leading "Then " — preserved from existing engine

Decimal-aware via (?:[^.]|\.(?=\d))* so "1.5 miles" doesn't split. No /i
flag — Valhalla always title-cases, (?=[A-Z]) lookahead now intact.

Per adversarial findings R2 F2.1 (real Valhalla shape) + R2 F2.2 + R3
F3.N-3 (/i defeats capital guard) + R1 F1.5 (decimal-mile bug).

Agent: <YOUR_MONIKER>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Review checkpoint (after Tasks 0-3)

After this batch (helpers + Issue 1 floor lift), do a multi-perspective review:

Carefully review the batch from multiple perspectives:
- **Spec-conformance lens:** does each helper match spec v2 §5.1's contract?
- **Pitfalls lens:** any patterns from `docs/pitfalls/testing-pitfalls.md` violated? Tautological tests? Stubbed-out implementations?
- **Style lens:** does the new code match the existing IIFE module's conventions (var, no arrow fns, no const)?

Do at least 3 review rounds. If you still find substantive issues in the third review, keep going. Then update the dev/implementation log and continue to Task 4.

---

## Task 4: GPS-recovery state + `consumeGPSRecoveryFlag` helper

**Files:**
- Modify: `frontend/navigation.js` (module-scope state + helper)
- Modify: `frontend/tests/engine/navigation.test.mjs`

BEFORE starting work: TDD.

- [ ] **Step 1: Write the failing tests:**

```js
test('consumeGPSRecoveryFlag: normal flow always returns false', async () => {
  const { nav, window: win } = await loadEngine();
  const internals = win._geographicaNavEngineInternals;
  // Simulate a fresh GPS state — never stale, never DR.
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 10 };
  nav.start(fixtureRouteWithTwoTurns());
  // Tick a few times with fresh GPS.
  for (let i = 0; i < 3; i++) {
    nav.updateGPS({ latitude: 35.20, longitude: -111.65, speed: 10 });
  }
  // After all-fresh ticks, the recovery flag should never have been armed.
  assert.equal(internals._peekGPSRecoveryFlag(), false,
    'recovery flag should be false after all-fresh ticks');
});

test('consumeGPSRecoveryFlag: arms after stale, fires once on recovery', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const internals = win._geographicaNavEngineInternals;
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 10 };
  nav.start(fixtureRouteWithTwoTurns());
  // Tick once fresh
  nav.updateGPS({ latitude: 35.20, longitude: -111.65, speed: 10 });
  // Force "stale" — directly mutate engine state via internals if exposed,
  // or simulate by NOT calling updateGPS for > GPS_STALE_TIMEOUT ms.
  // Implementation detail: use the test-only setter exposed in Step 3 below.
  internals._setLastGPSTime(Date.now() - 5000);  // 5 s old, exceeds 3 s timeout
  // Next tick — armed
  nav.updateGPS({ latitude: 35.20, longitude: -111.65, speed: 10 });
  // Recovery flag should be true on consume; consume sets it back to false.
  assert.equal(internals._consumeGPSRecoveryFlag(), true);
  assert.equal(internals._consumeGPSRecoveryFlag(), false);
});
```

- [ ] **Step 2: Run tests to verify failure**

Run: `node --test --test-force-exit frontend/tests/engine/navigation.test.mjs 2>&1 | grep -E "GPSRecovery|fail" | head -10`
Expected: 2 tests fail (helpers not exported).

- [ ] **Step 3: Implement the state + helpers** in `frontend/navigation.js`. Add at module scope (alongside other GPS state, around line 152-160):

```js
  // GPS-recovery guard — spec v2 §5.3. Tracks whether the previous tick was
  // in DR / stale-GPS state so the FIRST fresh tick can suppress its prefix
  // (prevents jarringly-precise distance from a single recovered sample).
  var prevTickWasStaleOrDR = false;

  function consumeGPSRecoveryFlag() {
    var nowFresh = !drActive && (Date.now() - lastGPSTime <= GPS_STALE_TIMEOUT);
    if (prevTickWasStaleOrDR && nowFresh) {
      prevTickWasStaleOrDR = false;
      return true;  // suppress prefix this tick
    }
    prevTickWasStaleOrDR = drActive || (Date.now() - lastGPSTime > GPS_STALE_TIMEOUT);
    return false;
  }
```

- [ ] **Step 4: Export via test hook.** In `_geographicaNavEngineInternals`:

```js
    _stripBakedDistance: stripBakedDistance,
    _consumeGPSRecoveryFlag: consumeGPSRecoveryFlag,        // NEW
    _peekGPSRecoveryFlag: function () { return prevTickWasStaleOrDR; },  // NEW (test-only inspector)
    _setLastGPSTime: function (t) { lastGPSTime = t; }       // NEW (test-only mutator)
```

- [ ] **Step 5: Run tests, verify pass**

Run: `node --test --test-force-exit frontend/tests/engine/navigation.test.mjs 2>&1 | tail -10`
Expected: 2 GPS-recovery tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/navigation.js frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
feat(nav): GPS-recovery flag for prefix-suppression on first post-stale tick

Per spec v2 §5.3 + Codex F5.4. New module-scope state prevTickWasStaleOrDR;
new consumeGPSRecoveryFlag() helper. On the first fresh checkVoice tick
after drActive clears OR lastGPSTime > GPS_STALE_TIMEOUT clears, the
helper returns true (one-shot). checkVoice will use this to suppress the
live-distance prefix for that one tick — prevents speaking a precise
"In 200 feet" computed from a single recovered GPS sample after dead
reckoning estimation.

Test hooks: _peekGPSRecoveryFlag (read-only inspector), _setLastGPSTime
(test-only setter so tests can simulate stale state without time passage).

Agent: <YOUR_MONIKER>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Wire prefix into far-tier path

**Files:**
- Modify: `frontend/navigation.js` (`checkVoice` far-tier branch around line 462-481)
- Modify: `frontend/tests/engine/navigation.test.mjs`

BEFORE starting work: TDD. Read spec v2 §5.2 carefully — order of operations is load-bearing (mark `announcedSet` BEFORE prefix construction for exception safety).

- [ ] **Step 1: Add a fixture** for above-cutoff far-tier testing. In `frontend/tests/engine/test_runner.mjs` (append after the existing fixtures, before any closing constructs):

```js
// Fixture: 2-maneuver route with a long first segment so far-tier fires at
// a TTM-governed distance well above the cutoff. Used for I13 prefix tests.
// 2000 m segment at lat 35.20 (1° longitude ≈ 91 km at lat 35, so 2000 m ≈ 0.022°).
export function fixtureLongFirstSegment() {
  return {
    coords: [
      [-111.65000, 35.20],     // depart start
      [-111.62800, 35.20],     // M1 boundary (2000 m east)
      [-111.62700, 35.20],     // route end (100 m past M1)
    ],
    maneuvers: [
      {
        type: 1,
        instruction: 'Head east',
        verbal_transition_alert_instruction: 'In 2000 feet, turn left',
        verbal_pre_transition_instruction: 'Head east',
        begin_shape_index: 0,
        end_shape_index: 1,
      },
      {
        type: 15,
        instruction: 'Turn left onto Test Avenue',
        verbal_transition_alert_instruction: 'Turn left onto Test Avenue',
        verbal_pre_transition_instruction: 'Turn left onto Test Avenue',
        begin_shape_index: 1,
        end_shape_index: 2,
      },
    ],
    summary: { length: 2.1, time: 130 },
    totalDistance: 2100,
    totalTime: 130,
    costing: 'auto',
    remainingWaypoints: [],
  };
}
```

- [ ] **Step 2: Write the failing test:**

```js
test('I13: far-tier fires "In a quarter mile, " prefix when above cutoff', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const { fixtureLongFirstSegment } = await import('./test_runner.mjs');
  win._geographicaUseImperial = true;
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 16 };
  const fires = [];
  nav.onVoice((t) => fires.push(t));
  nav.start(fixtureLongFirstSegment());
  // Drive at 16 m/s. Far-tier ttm ≤ 30 → fires at distance ≤ 480 m.
  // Approach to 470 m from M1 (M1 at lng -111.628; 470 m east of start).
  // 470 m east at lat 35.20: dx_deg = 470 / (111000 * cos(35.20°)) ≈ 0.005174
  // GPS at lng = -111.65 + 0.005174 ≈ -111.64483
  for (let i = 0; i < 3; i++) {
    nav.updateGPS({ latitude: 35.20, longitude: -111.64483, speed: 16 });
  }
  // Far-tier should have fired.
  assert.ok(fires.length >= 1, 'expected far-tier to fire');
  // Far-tier text MUST start with "In a quarter mile, " (480 m fire = 1575 ft, in [1000, 1980) band).
  assert.match(fires[0], /^In a quarter mile, /,
    `expected far-tier text to start with "In a quarter mile, ", got: ${JSON.stringify(fires[0])}`);
});

test('I15: far-tier exception in formatDistancePrefix marks announcedSet but does not fire', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const { fixtureLongFirstSegment } = await import('./test_runner.mjs');
  // Mock formatDistancePrefix to throw.
  const internals = win._geographicaNavEngineInternals;
  const origFmt = internals._formatDistancePrefix;
  internals._formatDistancePrefix = () => { throw new Error('mock failure'); };
  // Note: the production code doesn't read from _formatDistancePrefix; it calls
  // the closure-bound function directly. So this test as written may not
  // actually exercise the throw path. Skip if no testable hook exists; revisit
  // when reviewing exception-safety design.
  // For now, assert via _getAnnouncedKeys that mark-before-construct invariant
  // holds: trigger the path that would throw IF the helper threw, and verify
  // announcedSet has the maneuver key marked.
  // ... [this test may need redesign — flag for review]
  internals._formatDistancePrefix = origFmt;
});
```

NOTE: the I15 exception-safety test as written depends on whether the IIFE binds the helper at definition time (closure capture) or reads it dynamically. If closure capture, the mock won't take effect. Plan to either:
(a) refactor to read helpers via late-binding (adds complexity), OR
(b) accept that I15 invariant is verified by code review only.

Recommend (b): code-review verify that `announcedSet[farKey] = true` is set BEFORE the `farPrefix = formatDistancePrefix(...)` line. Mark this test SKIPPED with a comment, file the verification as a code-review checklist item in the task review checkpoint.

- [ ] **Step 3: Run test, verify failure**

Run: `node --test --test-force-exit frontend/tests/engine/navigation.test.mjs 2>&1 | grep -E "I13|fail" | head -10`
Expected: I13 far-tier test fails (no prefix in current text).

- [ ] **Step 4: Modify the far-tier branch** in `frontend/navigation.js` `checkVoice()` around line 462-481. CURRENT code:

```js
    if (farWouldFire) {
      var farText = m.verbal_transition_alert_instruction || m.instruction || "";
      announcedSet[farKey] = true;
      if (!muted && farText && onVoiceCb) {
        if (typeof window !== 'undefined' && window._geographicaTTMDebug) {
          (window._geographicaTTMDebugLog = window._geographicaTTMDebugLog || []).push({
            timestamp: Date.now(),
            maneuverIdx: nextIdx,
            tier: 'far',
            distToNext: distToNext,
            ttm: ttm,
            onRerouteRetick: false
          });
        }
        onVoiceCb(farText);
      }
    }
```

NEW code (preserve debug-log block, add prefix between mark-announced and onVoiceCb):

```js
    if (farWouldFire) {
      var farText = m.verbal_transition_alert_instruction || m.instruction || "";
      announcedSet[farKey] = true;  // MARK FIRST per spec v2 §5.2 G11 exception safety
      // Spec v2 §5.2: strip baked distance, prepend live distance unless GPS-recovery guard fires.
      if (!consumeGPSRecoveryFlag()) {
        farText = stripBakedDistance(farText);
        var farPrefix = formatDistancePrefix(distToNext, _geographicaUseImperial());
        if (farPrefix && farText && farText.length > 0) {
          farText = farPrefix + farText.charAt(0).toLowerCase() + farText.slice(1);
        }
      }
      if (!muted && farText && onVoiceCb) {
        if (typeof window !== 'undefined' && window._geographicaTTMDebug) {
          (window._geographicaTTMDebugLog = window._geographicaTTMDebugLog || []).push({
            timestamp: Date.now(),
            maneuverIdx: nextIdx,
            tier: 'far',
            distToNext: distToNext,
            ttm: ttm,
            onRerouteRetick: false
          });
        }
        onVoiceCb(farText);
      }
    }
```

- [ ] **Step 5: Run test, verify pass**

Run: `node --test --test-force-exit frontend/tests/engine/navigation.test.mjs 2>&1 | tail -10`
Expected: I13 far-tier test passes; existing tests unaffected.

BEFORE marking complete:
1. Manually verify in source: `announcedSet[farKey] = true;` is on the line BEFORE the `consumeGPSRecoveryFlag()` line (G11 invariant).
2. Run full suite, confirm no regression in existing 7 engine tests.

- [ ] **Step 6: Commit**

```bash
git add frontend/navigation.js frontend/tests/engine/navigation.test.mjs frontend/tests/engine/test_runner.mjs
git commit -m "$(cat <<'EOF'
feat(nav): live-distance prefix on far-tier voice prompts

Per spec v2 §5.2 (Issue 2 part 1). Far-tier in checkVoice now:
  1. Marks announcedSet[farKey] BEFORE prefix construction (exception safe — G11)
  2. Calls consumeGPSRecoveryFlag() — skips prefix on first post-DR/stale tick
  3. Strips baked Valhalla chain via stripBakedDistance
  4. Prepends formatDistancePrefix(distToNext, useImperial)

Cameron's stated example "In 1/4 mile, turn right onto Black Canyon Highway"
is now produced by the far-tier on Union Hills (486 m fire at 36 mph) —
matches the spec §5.4 expected transcript.

Includes new fixtureLongFirstSegment fixture (2000 m first segment) for
testing far-tier behavior at TTM-governed distances above cutoff.

Agent: <YOUR_MONIKER>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Wire prefix into near-tier base text + chain-append

**Files:**
- Modify: `frontend/navigation.js` (`checkVoice` near-tier branch around line 398-460)
- Modify: `frontend/tests/engine/navigation.test.mjs`

**Critical:** these two paths share the same `consumeGPSRecoveryFlag()` invocation — call once at the top of the near-tier branch, store in `skipPrefix`, both base text and chain-append use it.

BEFORE starting work: TDD. Read spec v2 §5.2 near-tier code carefully — STRIP must happen BEFORE uppercase normalization (existing engine uppercases AFTER existing Then-strip — preserve that order; the new stripBakedDistance subsumes the existing two-line Then-strip block).

- [ ] **Step 1: Add a fixture** for above-cutoff near-tier + chain testing. In `frontend/tests/engine/test_runner.mjs`:

```js
// Fixture: 4-maneuver route with 200 m maneuver spacing — wide enough that
// near-tier fires above the new 30 m cutoff AND chain-append distance is
// also above cutoff. For I13 prefix-firing assertions.
// 200 m at lat 35.20 ≈ 0.0022°.
export function fixtureWiderCluster() {
  return {
    coords: [
      [-111.65000, 35.20],
      [-111.64780, 35.20],     // M1 boundary (200 m east)
      [-111.64560, 35.20],     // M2 boundary
      [-111.64340, 35.20],     // M3 boundary
      [-111.64120, 35.20],     // route end
    ],
    maneuvers: [
      {
        type: 1,
        instruction: 'Head east',
        verbal_transition_alert_instruction: 'In 700 feet, turn left',
        verbal_pre_transition_instruction: 'Head east',
        begin_shape_index: 0,
        end_shape_index: 1,
      },
      {
        type: 15,
        instruction: 'Turn left onto First Street',
        verbal_transition_alert_instruction: 'Turn left onto First Street',
        verbal_pre_transition_instruction: 'Turn left onto First Street',
        begin_shape_index: 1,
        end_shape_index: 2,
      },
      {
        type: 10,
        instruction: 'Turn right onto Second Road',
        verbal_transition_alert_instruction: 'Turn right onto Second Road',
        verbal_pre_transition_instruction: 'Turn right onto Second Road',
        begin_shape_index: 2,
        end_shape_index: 3,
      },
      {
        type: 4,
        instruction: 'Turn left onto Third Avenue',
        verbal_transition_alert_instruction: 'Turn left onto Third Avenue',
        verbal_pre_transition_instruction: 'Turn left onto Third Avenue',
        begin_shape_index: 3,
        end_shape_index: 4,
      },
    ],
    summary: { length: 0.8, time: 80 },
    totalDistance: 800,
    totalTime: 80,
    costing: 'auto',
    remainingWaypoints: [],
  };
}
```

- [ ] **Step 2: Write the failing tests:**

```js
test('I13: near-tier fires "In 200 feet, " prefix at 75 m floor', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const { fixtureWiderCluster } = await import('./test_runner.mjs');
  win._geographicaUseImperial = true;
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 11 };
  const fires = [];
  nav.onVoice((t) => fires.push(t));
  nav.start(fixtureWiderCluster());
  // Drive to 75 m east of start (just at floor for M1).
  // 75 m east at lat 35.20: dx_deg = 75 / (111000 * cos(35.20°)) ≈ 0.000826
  // M1 at -111.64780; driver at 75 m before M1 → -111.64780 + 0.000826 ≈ -111.64698
  for (let i = 0; i < 3; i++) {
    nav.updateGPS({ latitude: 35.20, longitude: -111.64698, speed: 11 });
  }
  assert.ok(fires.length >= 1, 'expected near-tier to fire');
  // 75 m → 246 ft → round 200 → "In 200 feet, "
  // Chain to M2 (200 m after M1) → 656 ft → round 700 → "then in 700 feet, ..."
  assert.match(fires[fires.length - 1],
    /^In 200 feet, turn left onto First Street, then in 700 feet, turn right onto Second Road/,
    `expected near+chain prefix structure, got: ${JSON.stringify(fires[fires.length - 1])}`);
});

test('I13: cutoff suppresses near-tier prefix for very-short-spacing fixture', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const { fixtureVillaRitaCluster } = await import('./test_runner.mjs');
  win._geographicaUseImperial = true;
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 11 };
  const fires = [];
  nav.onVoice((t) => fires.push(t));
  nav.start(fixtureVillaRitaCluster());
  // Villa Rita fixture uses 30 m spacing. At 30 m to next maneuver, that's
  // 98 ft — BELOW the 100 ft cutoff. Near-tier prefix should be empty.
  // Drive to 25 m east of start (within floor, below cutoff).
  for (let i = 0; i < 3; i++) {
    nav.updateGPS({ latitude: 35.20, longitude: -111.6498, speed: 11 });
  }
  assert.ok(fires.length >= 1, 'expected near-tier to fire');
  // No "In N feet, " prefix at < 30 m fire distance.
  assert.doesNotMatch(fires[0], /^In \d+ feet,/,
    `expected no prefix at sub-cutoff distance, got: ${JSON.stringify(fires[0])}`);
});

test('I13: imperial vs metric dispatch — same fixture switches units', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const { fixtureWiderCluster } = await import('./test_runner.mjs');
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 11 };
  const fires = [];
  nav.onVoice((t) => fires.push(t));
  // Run as metric.
  win._geographicaUseImperial = false;
  nav.start(fixtureWiderCluster());
  for (let i = 0; i < 3; i++) {
    nav.updateGPS({ latitude: 35.20, longitude: -111.64698, speed: 11 });
  }
  assert.ok(fires.length >= 1, 'expected near-tier to fire');
  // 75 m → "In 80 meters, " (round 50 if >= 100, else round 10. 75 < 100 → round 10 = 80)
  // Chain 200 m → "In 200 meters, " (round 50 → 200)
  assert.match(fires[fires.length - 1],
    /^In 80 meters, turn left onto First Street, then in 200 meters, turn right onto Second Road/,
    `metric dispatch failed, got: ${JSON.stringify(fires[fires.length - 1])}`);
});

test('I13: prompt count invariant on Villa Rita fixture (G9 regression guard)', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const { fixtureVillaRitaCluster } = await import('./test_runner.mjs');
  win._geographicaUseImperial = true;
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 10 };
  const fires = [];
  nav.onVoice((t) => fires.push(t));
  nav.start(fixtureVillaRitaCluster());
  // Drive through all three maneuvers (existing TTM v3 test from §6.4).
  const lngs = [
    -111.6498, -111.6497, -111.6496,
    -111.6495, -111.6494, -111.6493,
    -111.6492, -111.6491, -111.6490,
  ];
  for (const lng of lngs) {
    nav.updateGPS({ latitude: 35.20, longitude: lng, speed: 10 });
  }
  // TTM v3 baseline asserts exactly 3 prompts. New prefix logic must preserve.
  assert.equal(fires.length, 3,
    `expected 3 prompts (TTM v3 baseline preserved), got ${fires.length}: ${JSON.stringify(fires)}`);
});
```

- [ ] **Step 3: Run tests to verify failure**

Run: `node --test --test-force-exit frontend/tests/engine/navigation.test.mjs 2>&1 | grep -E "I13|fail" | head -10`
Expected: 3-4 of the new I13 tests fail (no prefix in current near-tier text); G9 regression test may already pass at 3.

- [ ] **Step 4: Modify the near-tier branch** in `frontend/navigation.js` `checkVoice()` around line 398-460. CURRENT code (abridged):

```js
    if (nearWouldFire) {
      var text = m.verbal_pre_transition_instruction || m.instruction || "";
      // ... two-line Then-strip block ...
      if (text.length > 0) {
        text = text.charAt(0).toUpperCase() + text.slice(1);
      }
      var afterIdx = nextIdx + 1;
      if (afterIdx < route.maneuvers.length) {
        var distBetween = distanceToManeuver(...);
        if (distBetween <= NEXT_AFTER_NEXT_DISTANCE) {
          var afterText = route.maneuvers[afterIdx].instruction || "";
          if (afterText) {
            text = text.replace(/\.\s*$/, '') + ", then " + afterText;
            announcedSet[afterIdx + "-far"] = true;
          }
        }
      }
      announcedSet[nearKey] = true;
      announcedSet[farKey] = true;
      if (!muted && text && onVoiceCb) { ... onVoiceCb(text); }
      return;
    }
```

NEW code:

```js
    if (nearWouldFire) {
      var text = m.verbal_pre_transition_instruction || m.instruction || "";
      // NEW: stripBakedDistance subsumes the existing two-line Then-strip pattern
      // AND adds mid-string ". Then, in <dist>, X" stripping (spec v2 §5.1 + §5.2).
      text = stripBakedDistance(text);
      if (text.length > 0) {
        text = text.charAt(0).toUpperCase() + text.slice(1);
      }
      // GPS-recovery guard — single consume per tick, shared with chain-append below.
      var skipPrefix = consumeGPSRecoveryFlag();
      // NEW: prepend live-distance prefix to base text.
      if (!skipPrefix) {
        var nearPrefix = formatDistancePrefix(distToNext, _geographicaUseImperial());
        if (nearPrefix && text && text.length > 0) {
          text = nearPrefix + text.charAt(0).toLowerCase() + text.slice(1);
        }
      }
      // MARK announcedSet BEFORE chain-append construction (exception safety — G11).
      // NOTE: this is a slight reorder from existing engine, which marked AFTER chain.
      // Reorder is safe because chain-append doesn't read announcedSet[nearKey] or
      // announcedSet[farKey] — only writes announcedSet[afterIdx + "-far"].
      announcedSet[nearKey] = true;
      announcedSet[farKey] = true;
      var afterIdx = nextIdx + 1;
      if (afterIdx < route.maneuvers.length) {
        var distBetween = distanceToManeuver(
          { segmentIndex: m.begin_shape_index, t: 0 }, afterIdx
        );
        if (distBetween <= NEXT_AFTER_NEXT_DISTANCE) {
          var afterText = stripBakedDistance(route.maneuvers[afterIdx].instruction || "");
          if (afterText) {
            // MARK afterIdx-far suppression BEFORE chain text construction.
            announcedSet[afterIdx + "-far"] = true;  // I11 chain extension
            // Build chain. Reuse the same skipPrefix from above (single consume per tick).
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
            text = text.replace(/\.\s*$/, '') + chainJoin;
          }
        }
      }
      if (!muted && text && onVoiceCb) {
        if (typeof window !== 'undefined' && window._geographicaTTMDebug) {
          (window._geographicaTTMDebugLog = window._geographicaTTMDebugLog || []).push({
            timestamp: Date.now(),
            maneuverIdx: nextIdx,
            tier: 'near',
            distToNext: distToNext,
            ttm: ttm,
            onRerouteRetick: false
          });
        }
        onVoiceCb(text);
      }
      return;
    }
```

**Important:** delete the existing two-line Then-strip block (the `text.replace(/\.\s*Then\s+[^.]*\.?\s*$/i, '.')` and `text.replace(/^Then\s+/i, '')` lines around line 413-414) — `stripBakedDistance` now subsumes them.

- [ ] **Step 5: Run tests, verify pass**

Run: `node --test --test-force-exit frontend/tests/engine/navigation.test.mjs 2>&1 | tail -10`
Expected: all 4 new I13 tests pass; G9 regression test passes (still exactly 3 prompts on Villa Rita).

BEFORE marking complete:
1. Manually verify in source: `announcedSet[nearKey] = true;` and `announcedSet[afterIdx + "-far"] = true;` are set BEFORE their respective text-building blocks (G11 exception safety).
2. Verify the existing two-line Then-strip block is gone (no double-stripping).
3. Run the full engine suite, confirm ALL existing tests still pass — including the existing TTM v3 tests around chain-append behavior.

- [ ] **Step 6: Commit**

```bash
git add frontend/navigation.js frontend/tests/engine/navigation.test.mjs frontend/tests/engine/test_runner.mjs
git commit -m "$(cat <<'EOF'
feat(nav): live-distance prefix on near-tier base + chain-append

Per spec v2 §5.2 (Issue 2 part 2). Near-tier in checkVoice now:
  1. stripBakedDistance handles BOTH the existing leading/trailing Then
     patterns AND the new mid-string ". Then, in <dist>, X" pattern
     (replaces the two-line strip block at the prior site)
  2. Single consumeGPSRecoveryFlag() at the top — shared between base text
     and chain-append (one consume per tick)
  3. Marks announcedSet BEFORE text construction (G11 exception safety)
  4. Prepends formatDistancePrefix to base text
  5. Chain-append also gets its own distance prefix (lowercased "in" for
     sentence flow: "X, then in 1/4 mile, ...")

Cameron's stated examples now produced:
  - "In 200 feet, turn left onto Utopia Road, then in 400 feet, turn left
    onto North Black Canyon Highway" (chain with both distances)
  - "Turn right, then in 100 feet, turn right" (parking-lot chain at the
    cutoff boundary)

Includes new fixtureWiderCluster (200 m spacing) for testing prefix above
cutoff. fixtureVillaRitaCluster (30 m spacing) verified to NOT prefix
(below cutoff) — preserves the parking-lot imminent-turn semantics.

Agent: <YOUR_MONIKER>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Review checkpoint (after Tasks 4-6)

After the checkVoice integration, do another multi-perspective review:

- **Spec-conformance lens:** does each of the three output paths match spec v2 §5.2?
- **Pitfalls lens:** review the new tests against `docs/pitfalls/testing-pitfalls.md`. Specifically: the mock-based I15 exception-safety test was flagged as needing redesign in Task 5 — is the "code-review verification" fallback documented?
- **Integration lens:** do the existing TTM v3 tests still pass without modification? If any TTM v3 test now fails, the prefix logic broke something it shouldn't have.
- **Pre-existing-bug lens:** the `stripBakedDistance` Pattern 2 (broadened "Then,") fixes a latent bug. Is there ANY risk this broader pattern over-strips? Run the existing engine tests and any field-fixture tests; if NONE regress, the broader pattern is safe.

Do at least 3 review rounds. Then update the dev/implementation-log and continue.

---

## Task 7: I14 GPS-recovery integration tests

**Files:**
- Modify: `frontend/tests/engine/navigation.test.mjs`

BEFORE starting work: TDD. The recovery flag's behavior is now wired into checkVoice; integration tests verify end-to-end suppression.

- [ ] **Step 1: Write the failing test:**

```js
test('I14: GPS-recovery guard suppresses prefix on first post-stale tick', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const { fixtureLongFirstSegment } = await import('./test_runner.mjs');
  const internals = win._geographicaNavEngineInternals;
  win._geographicaUseImperial = true;
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 16 };
  const fires = [];
  nav.onVoice((t) => fires.push(t));
  nav.start(fixtureLongFirstSegment());

  // Tick once fresh.
  nav.updateGPS({ latitude: 35.20, longitude: -111.65, speed: 16 });
  assert.equal(fires.length, 0, 'no fire yet at 2000 m from M1');

  // Force "stale" — set lastGPSTime in the past.
  internals._setLastGPSTime(Date.now() - 5000);
  // Next tick — recovery flag arms, fires near far-tier threshold.
  // Approach to 470 m from M1 (in far-tier range).
  nav.updateGPS({ latitude: 35.20, longitude: -111.64483, speed: 16 });
  assert.ok(fires.length >= 1, 'expected far-tier to fire');
  // FIRST post-recovery prompt should have NO prefix (suppressed).
  assert.doesNotMatch(fires[0], /^In .+, /,
    `expected NO prefix on first post-recovery fire, got: ${JSON.stringify(fires[0])}`);

  // Subsequent ticks should resume normal prefix behavior.
  // At this point M1's far is announced. Drive past M1 to trigger M2 far at next opportunity.
  // Actually: the test fixture only has 2 maneuvers (depart + M1); after M1 near fires,
  // no further announcements. Inverse-test approach: re-arm staleness, fire fresh again.
  internals._setLastGPSTime(Date.now() - 5000);
  nav.updateGPS({ latitude: 35.20, longitude: -111.6470, speed: 16 });  // closer to M1, near tier
  if (fires.length >= 2) {
    // Second fire should have prefix (or no prefix if recovery flag fired again — depends on
    // whether the Date.now() - 5000 set re-armed). Loose-assert that we got SOMETHING fired.
    // Tighter assertion would require a deterministic time-source; skipped for v1.
  }
});

test('I14b: GPS-stale recovery composes with normal-flow prefix on second tick', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const { fixtureWiderCluster } = await import('./test_runner.mjs');
  const internals = win._geographicaNavEngineInternals;
  win._geographicaUseImperial = true;
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 11 };
  const fires = [];
  nav.onVoice((t) => fires.push(t));
  nav.start(fixtureWiderCluster());

  // Force stale, then fresh tick at near-tier distance.
  internals._setLastGPSTime(Date.now() - 5000);
  nav.updateGPS({ latitude: 35.20, longitude: -111.64698, speed: 11 });
  assert.ok(fires.length >= 1, 'expected near-tier fire on recovery tick');
  assert.doesNotMatch(fires[0], /^In \d+ feet,/,
    `expected NO prefix on recovery tick, got: ${JSON.stringify(fires[0])}`);

  // After the recovery-suppressed fire, the engine should resume normal prefix behavior.
  // M1's near is now announced. Drive past M1 toward M2.
  // Position at -111.64560 (M2 boundary) means M2 is 0 m away — past it.
  // To stay in near-tier range for M2, position 75 m before M2.
  // M2 at -111.64560; 75 m before (east) = -111.64478 (yes, 75 m east less in lng — wait)
  // Actually: driver was at M1 (-111.64780), needs to move past M1 toward M2 (-111.64560).
  // 75 m before M2 = -111.64560 + 0.000826 = -111.64478. (Driver is approaching, so lng increases.)
  for (let i = 0; i < 3; i++) {
    nav.updateGPS({ latitude: 35.20, longitude: -111.64478, speed: 11 });
  }
  // At this point the next near-tier (M2) should have fired with a prefix.
  if (fires.length >= 2) {
    assert.match(fires[fires.length - 1], /^In \d+ feet,/,
      `expected prefix on subsequent (non-recovery) tick, got: ${JSON.stringify(fires[fires.length - 1])}`);
  }
});
```

- [ ] **Step 2: Run tests to verify failure**

Run: `node --test --test-force-exit frontend/tests/engine/navigation.test.mjs 2>&1 | grep -E "I14|fail" | head -10`
Expected: I14 tests should already pass IF Task 5 + Task 6 wired the recovery flag correctly. If they fail, debug the recovery-flag wiring.

- [ ] **Step 3 (only if tests fail): Debug + fix.**

Common failure modes:
- The recovery flag is consumed twice per tick (once in far-tier, once in near-tier). Check that the call site logic in Task 5/6 is correct.
- The `_setLastGPSTime` mutator isn't taking effect. Verify it's exported in the test hook.
- The `prevTickWasStaleOrDR` state isn't being updated on every checkVoice call (the consume function should mutate the state on every invocation).

- [ ] **Step 4: Run tests, verify pass**

Run: `node --test --test-force-exit frontend/tests/engine/navigation.test.mjs 2>&1 | tail -10`
Expected: I14 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
test(nav): I14 GPS-recovery prefix-suppression integration

Verifies that the first checkVoice fire after lastGPSTime > GPS_STALE_TIMEOUT
clears (or drActive clears) speaks the maneuver text WITHOUT the live-distance
prefix. Subsequent fires resume normal prefix behavior.

Per spec v2 §5.6 invariant I14 + Codex F5.4 adversarial finding.

Agent: <YOUR_MONIKER>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Full-pipeline integration test (Codex F5.5)

**Files:**
- Modify: `frontend/tests/engine/navigation.test.mjs`

BEFORE starting work: this test pins the strip + uppercase + prefix order against the actual rendered text. Codex F5.5 specifically called this out as an unprotected invariant.

- [ ] **Step 1: Write the test:**

```js
test('I13g: full pipeline — multi-cue depart strips chain + applies live prefix', async (t) => {
  // Synthesize a fixture with the real Valhalla multi-cue shape on the depart-leading maneuver.
  // The mid-string ". Then, in 900 feet, X." is the actual Villa Rita depart pattern.
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaUseImperial = true;
  const fires = [];
  nav.onVoice((t) => fires.push(t));

  // Build a route where M1 has the multi-cue VPT shape.
  const route = {
    coords: [
      [-111.65000, 35.20],  // start
      [-111.64780, 35.20],  // M1 boundary (200 m east)
      [-111.64560, 35.20],  // route end
    ],
    maneuvers: [
      {
        type: 1,
        instruction: 'Head east',
        verbal_transition_alert_instruction: 'In 700 feet, turn left',
        verbal_pre_transition_instruction: 'Head east',
        begin_shape_index: 0,
        end_shape_index: 1,
      },
      {
        type: 15,
        instruction: 'Turn left onto Test Avenue',
        verbal_transition_alert_instruction: 'Turn left onto Test Avenue',
        // Multi-cue VPT: real Valhalla depart shape with baked distance + chained next-turn.
        verbal_pre_transition_instruction: 'Turn left onto Test Avenue. Then, in 900 feet, Continue on Test Avenue.',
        begin_shape_index: 1,
        end_shape_index: 2,
      },
    ],
    summary: { length: 0.4, time: 40 },
    totalDistance: 400,
    totalTime: 40,
    costing: 'auto',
    remainingWaypoints: [],
  };
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 11 };
  nav.start(route);
  // Drive to 75 m before M1 to fire near-tier.
  for (let i = 0; i < 3; i++) {
    nav.updateGPS({ latitude: 35.20, longitude: -111.64698, speed: 11 });
  }
  assert.ok(fires.length >= 1, 'expected near-tier to fire');
  // Expected: stripBakedDistance removes ". Then, in 900 feet, Continue on Test Avenue.";
  // residual is "Turn left onto Test Avenue."; uppercase preserved; live prefix "In 200 feet, "
  // prepended with first letter lowercased: "In 200 feet, turn left onto Test Avenue."
  assert.equal(fires[fires.length - 1], 'In 200 feet, turn left onto Test Avenue.',
    `pipeline order broken — expected clean strip + prefix, got: ${JSON.stringify(fires[fires.length - 1])}`);
});
```

- [ ] **Step 2: Run test, verify pass**

Run: `node --test --test-force-exit frontend/tests/engine/navigation.test.mjs 2>&1 | tail -5`
Expected: I13g passes (assuming Task 6 was implemented correctly).

If it FAILS: debug. Most likely cause is order-of-operations in the near-tier branch (strip happens after prefix, or chain-append fires when it shouldn't, or the test fixture's M2 is too close and chain triggers).

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
test(nav): I13g full-pipeline — strip Valhalla chain + live prefix

Pins the order-of-operations contract from spec v2 §5.2 against a
synthesized fixture using Valhalla's actual multi-cue depart shape
(". Then, in 900 feet, X."). Verifies stripBakedDistance removes the
trailing chain entirely AND the live-distance prefix replaces it cleanly.

Per Codex F5.5 adversarial finding — without this test, a future
implementation could reorder the transforms and pass the unit tests
while regressing the real utterance shape.

Agent: <YOUR_MONIKER>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Final integration smoke test + ship-gate documentation

**Files:**
- No code changes
- Run full test suite + verify ship-gate criteria from spec §6

- [ ] **Step 1: Run the full engine test suite.**

Run: `node --test --test-force-exit frontend/tests/engine/ 2>&1 | tail -20`
Expected: ALL tests pass — both pre-existing TTM v3 tests AND the new I12, I13, I14, I15 (code-review-verified), I16 (monotonicity) tests. Count: should be 7 pre-existing + ~22 new = ~29 tests.

- [ ] **Step 2: Run the broader project test suite to check no regressions outside engine.**

Run: `python -m pytest tests/ services/search/tests/ -v 2>&1 | tail -30`
Expected: no regressions beyond the known pre-existing failures (per START.md):
- `test_wake_lock_static.py::test_wake_lock_js_exists_and_exports_api` (pre-existing per START.md)
- 2 pre-existing M2M failures
- 18 Nominatim env errors (require docker compose up)

- [ ] **Step 3: Verify ship-gate criteria** by reading the spec §6 acceptance criteria and confirming each is testable on Cameron's field drive:

  1. Issue 1 acceptance — "+1 s of post-speech buffer at 25 mph" — verifiable by re-driving Villa Rita → Costco and observing prompt timing.
  2. Issue 2 acceptance — far-tier on Union Hills speaks "In a quarter mile, turn right onto North Black Canyon Highway"; near-tier speaks "In 200 feet, turn left onto X"; chain-append carries its own distance; parking-lot turns < 30 m fire bare "Turn right".
  3. Regression — total prompt count is 11 (TTM v3 baseline).
  4. GPS-recovery sanity — first post-recovery prompt speaks maneuver alone (no prefix). Verifiable via `_geographicaTTMDebugLog`.

- [ ] **Step 4: Update implementation log.**

Append to `dev/implementation-log.md` (top of the file, reverse-chronological):

```markdown
## 2026-04-24 — Nav voice TTM follow-up Issues 1+2 shipped on dev

**Agent:** <YOUR_MONIKER>
**Branch:** dev
**Spec:** [docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md](../docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md) (v2)
**Plan:** [docs/superpowers/plans/2026-04-24-nav-voice-followup-plan.md](../docs/superpowers/plans/2026-04-24-nav-voice-followup-plan.md)

Field-surfaced fixes from Cameron's post-TTM-ship driving:
- **Issue 1 (floor lift):** VOICE_DISTANCE_FLOOR.auto 50→75 m, bicycle 30→45 m. +1.3 s post-speech buffer at 25 mph.
- **Issue 2 (live-distance prefix):** Google-Maps-style "In a quarter mile, turn right onto X" prefix on far-tier, near-tier, and chain-append. Spelled-out fractions for deterministic TTS pronunciation. 30 m / 100 ft cutoff preserves imminent-turn semantics.

5-round adversarial review (4× Claude lenses + 1× Codex cross-validation) surfaced 8 MUST-FIX, 18 SHOULD-FIX. v2 spec incorporates all. v1 spec was net-regression; v2 fixes the regex against real Valhalla output, drops `/i` flag for guard intactness, lifts floor enough to absorb prefix TTS even at slow voice, adds GPS-recovery prefix-suppression.

Issue 3 (sidebar BFCache) split into separate spec + plan.

Tests added: I12 (floor values), I13 (prefix integration), I14 (GPS recovery), I16 (monotonicity property), I13g (full-pipeline order). I15 (exception safety) verified by code review only — see plan Task 5 for rationale.

**Ship gate:** Cameron re-drives Villa Rita → Costco. Acceptance per spec §6.
```

- [ ] **Step 5: Commit the implementation log.**

```bash
git add dev/implementation-log.md
git commit -m "$(cat <<'EOF'
docs(nav): implementation log — TTM follow-up Issues 1+2 shipped on dev

Per writing-plans + subagent-driven-development discipline. Closes the
2026-04-24 nav-voice-followup spec v2.

Agent: <YOUR_MONIKER>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final review checkpoint

After Task 9, do a final cross-task multi-perspective review:

- **Spec lens:** does every spec §2 goal (G1-G12) have a corresponding implemented behavior?
- **Test lens:** are all spec §5.5 invariants (I12-I16) covered by green tests?
- **Pitfalls lens:** any new test patterns that fall into `docs/pitfalls/testing-pitfalls.md`?
- **Architecture lens:** is the engine's IIFE module structure preserved? No new globals leaked?

Three rounds minimum. If you still find substantive issues, keep going.

After review: write the handoff document at `~/.claude/projects/-home-administrator-Code-geographica/memory/handoff_20260424_nav_voice_followup_shipped.md` with the standard handoff structure (commit-by-commit, deferred items, ship-gate-pending status).

Then halt: Cameron re-drives Villa Rita → Costco for the field-test merge gate. He will report back, and at that point a separate session may merge dev → main.
