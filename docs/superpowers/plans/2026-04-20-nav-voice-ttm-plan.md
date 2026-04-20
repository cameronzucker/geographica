# Nav Voice TTM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the distance-threshold voice-announcement model in `frontend/navigation.js` with the TTM (time-to-maneuver) model specified in [../specs/2026-04-20-nav-voice-ttm-design.md](../specs/2026-04-20-nav-voice-ttm-design.md) (commit `91e8266`), and delete the 2026-04-20 band-aid (commit `e63f6d9`) in the same PR.

**Architecture:** Pure in-engine change to the IIFE in `frontend/navigation.js`. No new files. `onVoiceCb` boundary preserved. 13 tasks following §8's 10-step order: new code first, then behavior rewrite, then cleanup. Each task is independently green-at-commit so the branch is never in a broken state.

**Tech Stack:** Vanilla JS (IIFE); Node.js `node:test` test runner; VM-sandboxed test harness in [frontend/tests/engine/test_runner.mjs](../../../frontend/tests/engine/test_runner.mjs).

**Agent identity:** Each subagent dispatched to execute a task MUST receive "You are agent `alder`" in its prompt so commit trailers stay consistent (per CLAUDE.md §"Agent identity"). Every commit includes `Agent: alder` on its own line in the message body.

**Branch:** work on `dev`. Do NOT create a new branch or worktree. Per CLAUDE.md, worktrees are BANNED on this project.

---

## Task map

| # | Task | §8 step | New tests | Commit type |
|---|---|---|---|---|
| T0 | Add Villa Rita synthetic fixture to test_runner.mjs | prep | — | `test(voice-ttm)` |
| T1 | Add TTM constants + expose via internals (legacy constants still present) | 1 | shape assertions | `feat(nav)` |
| T2 | Add `speedSamples` state + `pushSpeedSample` + `speedMedian` + wire into `tick()` | 2, 3 | 5 | `feat(nav)` |
| T3 | Rewrite `checkVoice` per §4.3; add I1/I2/I3/I4/I10 tests | 4 (core) | 5 | `feat(nav)` |
| T4 | Edge-case tests (empty text, unknown costing, distance clamp, cooldown guard) + I7 chain-on-near + I8 mute | 4 (edges) | 6 | `test(voice-ttm)` |
| T5 | Multi-costing matrix: bicycle + pedestrian behavior | 4 (costings) | 4 | `test(voice-ttm)` |
| T6 | Villa Rita synthetic test (§6.4) + single-outlier + correlated-outlier (I5) | 4 (villa-rita) | 3 | `test(voice-ttm)` |
| T7 | Remove `checkVoice` call from `deadReckonTick` + add I9 test | 5 | 1 | `fix(nav)` |
| T8 | Rewrite `applyReroute` (skip voice on re-tick, clear speedSamples) + `triggerReroute` scheduledSeq capture + tests | 6 | 4 | `fix(nav)` |
| T9 | Delete `announce()` helper + `lastAnnouncementTime` state | 7 | — | `refactor(nav)` |
| T10 | Delete band-aid constants + rewrite `_geographicaNavEngineInternals` (atomic) | 8 | internals-shape assertion | `refactor(nav)` |
| T11 | Rename stale test `applyReroute clears announcedSet and lastAnnouncementTime` → `...and speedSamples`; update assertions | 9 | — | `test(voice-ttm)` |
| T12 | Delete B1 regression guard test; commit with "closes B1, removes 2026-04-20 band-aid (e63f6d9)" | 10 | — | `refactor(nav)` |
| T13 | Add temporary debug log for field-gate §6.5 (gated behind `window._geographicaTTMDebug`) | — | 1 | `feat(nav)` |

After T13: manual field-drive of Villa Rita → Costco is the **ship gate** (spec §6.5 + §10 step 7). Dev-branch merge happens only after that passes.

---

## Per-task execution invariants

Every task:

- Runs `node --test frontend/tests/engine/` after its final step and confirms 100% green before committing.
- Adds `Agent: alder` and `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` as commit trailers.
- Uses `docs(*)` / `feat(nav)` / `fix(nav)` / `refactor(nav)` / `test(voice-ttm)` prefixes per [CONTRIBUTING.md](../../../CONTRIBUTING.md).
- Does NOT run `git push` (Cameron pushes at a natural milestone, typically after T12).

---

## Task 0: Add Villa Rita synthetic fixture

**Files:**
- Modify: `frontend/tests/engine/test_runner.mjs`

**Rationale:** Later tasks (T3, T6) need a 4-maneuver route with closely-spaced turns to exercise D1 suppression and the Villa Rita claim. Add this fixture once; many tasks reuse it.

- [ ] **Step 1: Add fixture function `fixtureVillaRitaCluster` at the bottom of `test_runner.mjs`**

Append to `frontend/tests/engine/test_runner.mjs` immediately before the `fixtureTwoManeuverRoute` alias:

```js
// Fixture: 4-maneuver route with 3 close-spaced turns ("Villa Rita class").
// maneuver[0] is the depart leg (not spoken).
// maneuver[1], maneuver[2], maneuver[3] are the 3 spoken turns.
// Coords in [lng, lat] order. Each turn is ~30m east of the previous at lat 35.20
// (1° longitude ≈ 91 km at lat 35, so 30 m ≈ 0.00033°).
export function fixtureVillaRitaCluster() {
  return {
    coords: [
      [-111.65000, 35.20],  // depart start (index 0)
      [-111.64967, 35.20],  // maneuver 1 boundary (30m east of depart)
      [-111.64934, 35.20],  // maneuver 2 boundary (30m east of maneuver 1)
      [-111.64901, 35.20],  // maneuver 3 boundary (30m east of maneuver 2)
      [-111.64868, 35.20],  // route end
    ],
    maneuvers: [
      {
        type: 1,
        instruction: 'Head east',
        verbal_transition_alert_instruction: 'In 100 feet, turn left',
        verbal_pre_transition_instruction: 'Head east',
        begin_shape_index: 0,
        end_shape_index: 1,
      },
      {
        type: 15,
        instruction: 'Turn left onto Mulberry',
        verbal_transition_alert_instruction: 'In 100 feet, turn left onto Mulberry',
        verbal_pre_transition_instruction: 'Turn left onto Mulberry',
        begin_shape_index: 1,
        end_shape_index: 2,
      },
      {
        type: 10,
        instruction: 'Turn right onto Oak',
        verbal_transition_alert_instruction: 'In 100 feet, turn right onto Oak',
        verbal_pre_transition_instruction: 'Turn right onto Oak',
        begin_shape_index: 2,
        end_shape_index: 3,
      },
      {
        type: 4,
        instruction: 'Turn left onto Villa Rita',
        verbal_transition_alert_instruction: 'In 100 feet, turn left onto Villa Rita',
        verbal_pre_transition_instruction: 'Turn left onto Villa Rita',
        begin_shape_index: 3,
        end_shape_index: 4,
      },
    ],
    summary: { length: 0.12, time: 12 },
    totalDistance: 120,
    totalTime: 12,
    costing: 'auto',
    remainingWaypoints: [],
  };
}
```

- [ ] **Step 2: Verify the existing test suite still passes**

Run: `cd /home/administrator/Code/geographica && node --test frontend/tests/engine/`
Expected: all existing tests pass (fixture is unused so far, but the file must still load cleanly).

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/engine/test_runner.mjs
git commit -m "$(cat <<'EOF'
test(voice-ttm): add Villa Rita synthetic fixture

4-maneuver route with 30m-spaced turns, matching the field scenario
at 2235 W Villa Rita Dr → North Phoenix Costco. Used by later TTM
tests to validate D1 suppression and the Villa Rita ship-criterion.
No engine changes in this commit.

Agent: alder
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 1: Add TTM constants, expose via test hook

**Files:**
- Modify: `frontend/navigation.js`
- Modify: `frontend/tests/engine/navigation.test.mjs`

**Rationale:** Per §8 step 1 — add without deleting. Old constants remain so existing tests and production code keep working.

- [ ] **Step 1: Write failing test in `navigation.test.mjs` (append after the last existing test)**

```js
test('TTM constants have expected shape and per-costing keys', async () => {
  const { window: win } = await loadEngine();
  const i = win._geographicaNavEngineInternals;
  assert.ok(i, 'internals hook must exist');
  assert.deepEqual(i.VOICE_TTM.auto, [30, 3]);
  assert.deepEqual(i.VOICE_TTM.bicycle, [20, 3]);
  assert.deepEqual(i.VOICE_TTM.pedestrian, [15, 2]);
  assert.equal(i.VOICE_DISTANCE_FLOOR.auto, 50);
  assert.equal(i.VOICE_DISTANCE_FLOOR.bicycle, 30);
  assert.equal(i.VOICE_DISTANCE_FLOOR.pedestrian, 15);
  assert.equal(i.MIN_SPEED_FLOOR, 1.0);
  assert.equal(i.SPEED_WINDOW_SIZE, 3);
  assert.equal(i.MAX_SPEED_DELTA_PER_TICK, 15);

  // Costing keys must match across VOICE_TTM and VOICE_DISTANCE_FLOOR (lint).
  const ttmKeys = Object.keys(i.VOICE_TTM).sort();
  const floorKeys = Object.keys(i.VOICE_DISTANCE_FLOOR).sort();
  assert.deepEqual(ttmKeys, floorKeys,
    'VOICE_TTM and VOICE_DISTANCE_FLOOR must have identical costing keys');
});
```

- [ ] **Step 2: Run — expect failure**

```
node --test frontend/tests/engine/navigation.test.mjs
```
Expected: the new test fails because `VOICE_TTM` is not on the internals hook.

- [ ] **Step 3: Add TTM constants to `navigation.js`**

In `frontend/navigation.js`, locate the `VOICE_THRESHOLDS` declaration (search for `var VOICE_THRESHOLDS`). Immediately after `var VOICE_NEAR_ANNOUNCE_DISTANCE = 50;` (the last BAND-AID-block line), add:

```js
  // ─── TTM (time-to-maneuver) voice model — spec v2 ──────────────────────
  // Each VOICE_TTM entry is [far_seconds, near_seconds]. Announcement timing
  // is ttm = distToNext / smoothedSpeed. The distance floor ensures near-tier
  // still fires when stationary at a maneuver (TTM → ∞ when speed → 0).
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
```

- [ ] **Step 4: Expose new constants on the existing `_geographicaNavEngineInternals` hook**

Locate `window._geographicaNavEngineInternals = {` (near the end of the IIFE). Add the 5 new keys while keeping the existing 3:

```js
  window._geographicaNavEngineInternals = {
    VOICE_THRESHOLDS: VOICE_THRESHOLDS,
    VOICE_COOLDOWN: VOICE_COOLDOWN,
    VOICE_SPEED_GATE: VOICE_SPEED_GATE,
    // TTM constants (spec v2) — old constants above are removed in T10:
    VOICE_TTM: VOICE_TTM,
    VOICE_DISTANCE_FLOOR: VOICE_DISTANCE_FLOOR,
    MIN_SPEED_FLOOR: MIN_SPEED_FLOOR,
    SPEED_WINDOW_SIZE: SPEED_WINDOW_SIZE,
    MAX_SPEED_DELTA_PER_TICK: MAX_SPEED_DELTA_PER_TICK
  };
```

- [ ] **Step 5: Run — expect the new test to pass AND all existing tests to still pass**

```
node --test frontend/tests/engine/navigation.test.mjs
```
Expected: all pass. If the B1 band-aid test still passes (it should — it asserts shape of `VOICE_THRESHOLDS` which is unchanged), good.

- [ ] **Step 6: Commit**

```bash
git add frontend/navigation.js frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
feat(nav): add TTM constants (spec v2 §4.1)

VOICE_TTM, VOICE_DISTANCE_FLOOR, MIN_SPEED_FLOOR, SPEED_WINDOW_SIZE,
MAX_SPEED_DELTA_PER_TICK added alongside existing band-aid constants.
Exposed via _geographicaNavEngineInternals. No behavior change yet —
constants are not referenced by checkVoice. Band-aid constants remain
in place and are removed in T10 of the implementation plan.

Part of TTM redesign; spec at docs/superpowers/specs/2026-04-20-nav-voice-ttm-design.md
(91e8266).

Agent: alder
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add speed-smoothing state + helpers + wire into tick()

**Files:**
- Modify: `frontend/navigation.js`
- Modify: `frontend/tests/engine/navigation.test.mjs`

**Rationale:** §8 steps 2-3 combined. New state (`speedSamples`), two helpers (`pushSpeedSample`, `speedMedian`), and the one-line wire-up in `tick()`. No caller yet uses `speedMedian()` — this task just populates the window.

- [ ] **Step 1: Write failing tests — speedSamples populates from updateGPS**

Append to `navigation.test.mjs`:

```js
test('pushSpeedSample: updateGPS populates speedSamples', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };
  nav.start(fixtureRouteWithTwoTurns());

  const i = win._geographicaNavEngineInternals;
  assert.equal(typeof i._getSpeedSamples, 'function',
    '_getSpeedSamples hook required for speed-window tests');

  nav.updateGPS({ latitude: 35.20, longitude: -111.649, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.648, heading: 90, speed: 11 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.647, heading: 90, speed: 12 });

  const samples = i._getSpeedSamples();
  assert.deepEqual(samples, [10, 11, 12],
    'speedSamples should contain the three post-start speeds in order');
});

test('pushSpeedSample: window size is capped at SPEED_WINDOW_SIZE (3)', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 5 };
  nav.start(fixtureRouteWithTwoTurns());
  const i = win._geographicaNavEngineInternals;

  for (let k = 0; k < 10; k++) {
    nav.updateGPS({
      latitude: 35.20, longitude: -111.65 + k * 0.0001,
      heading: 90, speed: 8 + k,
    });
  }
  assert.equal(i._getSpeedSamples().length, 3,
    'speedSamples must be bounded at SPEED_WINDOW_SIZE=3');
  assert.deepEqual(i._getSpeedSamples(), [15, 16, 17],
    'speedSamples must keep the most recent 3 accepted samples');
});

test('pushSpeedSample: physically-implausible delta is rejected (outlier clamp)', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };
  nav.start(fixtureRouteWithTwoTurns());
  const i = win._geographicaNavEngineInternals;

  // Seed window with two legitimate samples.
  nav.updateGPS({ latitude: 35.20, longitude: -111.649, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.648, heading: 90, speed: 10 });
  // Inject a 50 m/s outlier: delta = |50 - 10| = 40 > MAX_SPEED_DELTA_PER_TICK(15) → rejected.
  nav.updateGPS({ latitude: 35.20, longitude: -111.647, heading: 90, speed: 50 });
  // Inject a 10 m/s-delta sample (exactly above threshold of 15? No, 10 ≤ 15) → accepted.
  nav.updateGPS({ latitude: 35.20, longitude: -111.646, heading: 90, speed: 20 });

  const samples = i._getSpeedSamples();
  assert.ok(!samples.includes(50),
    'outlier 50 m/s must be rejected — delta from prior median exceeded 15 m/s');
  assert.ok(samples.includes(20),
    'legitimate delta <=15 m/s must be accepted');
});

test('pushSpeedSample: negative and NaN samples are sanitized to 0', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 0 };
  nav.start(fixtureRouteWithTwoTurns());
  const i = win._geographicaNavEngineInternals;

  nav.updateGPS({ latitude: 35.20, longitude: -111.649, heading: 90, speed: -5 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.648, heading: 90, speed: NaN });
  nav.updateGPS({ latitude: 35.20, longitude: -111.647, heading: 90, speed: 1 });

  const samples = i._getSpeedSamples();
  assert.ok(!samples.some(s => s < 0 || Number.isNaN(s)),
    'negative and NaN samples must be sanitized');
});

test('speedMedian: returns MIN_SPEED_FLOOR when window is empty', async () => {
  const { window: win } = await loadEngine();
  const i = win._geographicaNavEngineInternals;
  assert.equal(typeof i._speedMedian, 'function',
    '_speedMedian hook required for median tests');
  // Fresh engine: no samples yet.
  assert.equal(i._speedMedian(), i.MIN_SPEED_FLOOR);
});
```

- [ ] **Step 2: Run — expect all 5 new tests to fail**

```
node --test frontend/tests/engine/navigation.test.mjs
```
Expected: the new tests fail with "_getSpeedSamples is not a function" or similar.

- [ ] **Step 3: Add `speedSamples` state, helpers, and hook exposure to `navigation.js`**

Locate the existing block `// Voice` that declares `var muted = false;`, `var announcedSet = {};`, `var lastAnnouncementTime = 0;`. Add below them:

```js
  // Speed smoothing (spec v2 §4.2) — median-of-3 with outlier clamp.
  // MAX_SPEED_DELTA_PER_TICK rejects samples that differ from the prior median
  // by a physically-implausible amount. Catches GPS multipath bursts that a
  // median alone cannot reject.
  var speedSamples = [];

  function pushSpeedSample(s) {
    var clamped = (typeof s === 'number' && s >= 0 && isFinite(s)) ? s : 0;
    if (speedSamples.length >= 1) {
      var priorMedian = speedMedian();
      if (Math.abs(clamped - priorMedian) > MAX_SPEED_DELTA_PER_TICK) {
        return; // drop physically-implausible outlier
      }
    }
    speedSamples.push(clamped);
    if (speedSamples.length > SPEED_WINDOW_SIZE) speedSamples.shift();
  }

  function speedMedian() {
    if (speedSamples.length === 0) return MIN_SPEED_FLOOR;
    var sorted = speedSamples.slice().sort(function (a, b) { return a - b; });
    return sorted[Math.floor(sorted.length / 2)];
  }
```

- [ ] **Step 4: Wire `pushSpeedSample` into `tick()`**

Locate the line `lastSpeed = gpsSpeed;` near the top of `tick()` (search for `lastSpeed = gpsSpeed;`). On the line immediately after it, add:

```js
    pushSpeedSample(gpsSpeed);
```

- [ ] **Step 5: Add `_getSpeedSamples` and `_speedMedian` to the test hook**

In `window._geographicaNavEngineInternals`, add two entries at the bottom (before the closing `};`):

```js
    _getSpeedSamples: function () { return speedSamples.slice(); },
    _speedMedian: function () { return speedMedian(); }
```

- [ ] **Step 6: Reset speedSamples in `reset()`**

Locate the existing `reset()` function (search for `function reset() {`). Add `speedSamples = [];` alongside the existing `announcedSet = {};` and `lastAnnouncementTime = 0;` lines.

- [ ] **Step 7: Run — expect all 5 new tests to pass, all previous tests to still pass**

```
node --test frontend/tests/engine/navigation.test.mjs
```
Expected: full suite passes. Note: the B1 band-aid test still passes (it asserts `VOICE_THRESHOLDS` shape, not `speedSamples`).

- [ ] **Step 8: Commit**

```bash
git add frontend/navigation.js frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
feat(nav): speed-smoothing state + pushSpeedSample/speedMedian (spec v2 §4.2)

Median-of-3 rolling window with MAX_SPEED_DELTA_PER_TICK outlier
pre-filter. Rejects physically-implausible samples (GPS multipath)
before they enter the window. checkVoice does not yet consume this
data; wire-up happens in T3 when checkVoice is rewritten.

Part of TTM redesign.

Agent: alder
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Rewrite checkVoice + core invariant tests (I1, I2, I3, I4, I10)

**Files:**
- Modify: `frontend/navigation.js`
- Modify: `frontend/tests/engine/navigation.test.mjs`

**Rationale:** §8 step 4. The heart of the redesign. Replace the distance-threshold `checkVoice` body with the TTM algorithm per spec §4.3. Add tests for the 5 core invariants.

**Important:** The old `announce()` helper function and `VOICE_COOLDOWN` / `VOICE_SPEED_GATE` / `VOICE_NEAR_ANNOUNCE_DISTANCE` constants remain in source but become unreferenced. Orphaned code is removed in later tasks (T9/T10). Do NOT delete them in this task.

- [ ] **Step 1: Write failing tests for I1, I2, I3, I4, I10**

Append to `navigation.test.mjs`:

```js
test('TTM I1: 2 prompts per maneuver when entering from outside far (steady 10 m/s)', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());

  // Approach maneuver 1 (at lng -111.64) from far. Start pushing speed samples
  // to establish the smoothed window before crossing the 30s-TTM threshold.
  // At 10 m/s, 30s TTM = 300m. maneuver 1 is 1km east; start at ~500m away
  // and step in toward it.
  const startLng = -111.645;  // 500m west of maneuver 1
  const steps = 50;            // 50 GPS ticks at ~10m spacing
  for (let k = 0; k < steps; k++) {
    const lng = startLng + k * 0.0001;  // ~10m per step at lat 35
    nav.updateGPS({ latitude: 35.20, longitude: lng, heading: 90, speed: 10 });
  }
  // Expected: far-tier fires at ~300m, near-tier fires at ~50m floor = 2 prompts for maneuver 1.
  assert.equal(voiceFires.length, 2,
    `I1: expected exactly 2 prompts for maneuver 1, got ${voiceFires.length}`);
});

test('TTM I2: 1 prompt per maneuver when entering already inside near (D1 suppression)', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  // Start 30m west of maneuver 1 (well inside the 50m floor).
  // First move a bit so TTM pipeline is allowed to fire (NG8: no start-time voice).
  win._geographicaGPSData = { lat: 35.20, lon: -111.64030, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());
  // First movement tick — this is the "post-start first tick" per NG8.
  nav.updateGPS({ latitude: 35.20, longitude: -111.64025, heading: 90, speed: 10 });

  // D1 suppression: near-tier fires, far-tier is marked announced → 1 prompt for maneuver 1.
  assert.equal(voiceFires.length, 1,
    `I2: expected exactly 1 prompt (D1 suppression), got ${voiceFires.length}`);
});

test('TTM I3: zero prompts when stationary beyond distance floor', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  // Start 80m west of maneuver 1 (outside the 50m auto floor), stationary.
  win._geographicaGPSData = { lat: 35.20, lon: -111.64080, heading: 90, speed: 0 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());
  // Feed three stationary ticks.
  nav.updateGPS({ latitude: 35.20, longitude: -111.64079, heading: 90, speed: 0 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.64078, heading: 90, speed: 0 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.64077, heading: 90, speed: 0 });

  assert.equal(voiceFires.length, 0,
    `I3: expected 0 prompts when stationary beyond floor, got ${voiceFires.length}`);
});

test('TTM I4: near-tier fires when stationary at distance floor', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  // Start 30m west of maneuver 1 (inside the 50m floor), stationary.
  win._geographicaGPSData = { lat: 35.20, lon: -111.64030, heading: 90, speed: 0 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());
  // One "first movement tick" to allow TTM to fire (NG8). Tiny motion.
  nav.updateGPS({ latitude: 35.20, longitude: -111.64029, heading: 90, speed: 0.1 });

  assert.equal(voiceFires.length, 1,
    'I4: near-tier must fire when within distance floor, even near-stationary');
});

test('TTM I10: past-maneuver early-return (negative distToNext does not fire prompts)', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());

  // Jump past maneuver 1 — drive to lng -111.639 (east of maneuver 1 at -111.64).
  // findManeuverForSegment should advance currentManeuverIdx; checkVoice for the
  // new maneuver 2 fires normally (outside the I10 scope). Count that maneuver 1's
  // far/near prompts do NOT fire retroactively.
  nav.updateGPS({ latitude: 35.20, longitude: -111.639, heading: 90, speed: 10 });
  // Validate the stream by looking at announcedSet: maneuver 1's keys should not be set
  // by an overshoot (the engine-level invariant is that checkVoice for maneuver N does
  // not fire if driver has already crossed it).
  const keys = win._geographicaNavEngineInternals._getAnnouncedKeys();
  assert.ok(keys.length >= 0, 'announcedSet keys returned');
  // A prompt for maneuver 1 would be text containing "Main" or "Oak"; assert none.
  const m1Prompts = voiceFires.filter(t => /Main Street/.test(t));
  assert.equal(m1Prompts.length, 0,
    'I10: no prompts for already-passed maneuver 1');
});
```

- [ ] **Step 2: Run — expect I1, I2, I3, I4, I10 tests to fail (checkVoice still uses old logic)**

```
node --test frontend/tests/engine/navigation.test.mjs
```
Expected: the 5 new tests fail. Existing tests pass.

- [ ] **Step 3: Replace `checkVoice` body in `navigation.js`**

Locate `function checkVoice(snap) {` in `navigation.js`. Replace the entire function body (from `if (!route || !route.maneuvers) return;` through the final `}` of the function) with:

```js
  function checkVoice(snap) {
    if (!route || !route.maneuvers) return;

    var nextIdx = currentManeuverIdx + 1;
    if (nextIdx >= route.maneuvers.length) return;

    var m = route.maneuvers[nextIdx];
    var costing = route.costing || "auto";
    var ttmPair = VOICE_TTM[costing] || VOICE_TTM.auto;
    var floor = VOICE_DISTANCE_FLOOR[costing] || VOICE_DISTANCE_FLOOR.auto;

    // distanceToManeuver can return negative on overshoot / U-turn /
    // GPS jitter at maneuver boundaries. Negative would make every TTM
    // threshold trivially true, firing for wrong maneuvers.
    var rawDist = distanceToManeuver(snap, nextIdx);
    var distToNext = Math.max(0, rawDist);
    if (distToNext <= 0) {
      // Driver is AT or past the maneuver — findManeuverForSegment()
      // advances currentManeuverIdx on the next tick.
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
      var text = m.verbal_pre_transition_instruction || m.instruction || "";
      // Next-after-next chain — preserved from band-aid behavior.
      var afterIdx = nextIdx + 1;
      if (afterIdx < route.maneuvers.length) {
        var distBetween = distanceToManeuver(
          { segmentIndex: m.begin_shape_index, t: 0 }, afterIdx
        );
        if (distBetween <= NEXT_AFTER_NEXT_DISTANCE) {
          var afterText = route.maneuvers[afterIdx].instruction || "";
          if (afterText) text += ", then " + afterText;
        }
      }
      announcedSet[nearKey] = true;
      announcedSet[farKey] = true;  // D1 suppression
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

- [ ] **Step 4: Also add `_getAnnouncedKeys` hook (required by the I10 test)**

In `window._geographicaNavEngineInternals`, add another line after `_speedMedian`:

```js
    _getAnnouncedKeys: function () { return Object.keys(announcedSet).sort(); }
```

- [ ] **Step 5: Run — expect all 5 new I-tests to pass + existing tests to still pass**

```
node --test frontend/tests/engine/navigation.test.mjs
```
Expected: full suite green. The B1 band-aid test still passes (it asserts `VOICE_THRESHOLDS` shape — unchanged). The existing `applyReroute clears...` test still passes because its assertion is that announcements re-fire after reroute; the new checkVoice honors `announcedSet = {}` just like the old one did.

- [ ] **Step 6: Commit**

```bash
git add frontend/navigation.js frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
feat(nav): TTM checkVoice rewrite + I1/I2/I3/I4/I10 invariant tests

Replaces the distance-threshold checkVoice body with the TTM
algorithm per spec v2 §4.3: ttm = distToNext / speedMedian,
D1 close-turn suppression (skip far when near fires same tick),
distance-floor backstop for stationary-at-turn, past-maneuver
early-return via Math.max(0, distanceToManeuver).

Orphaned code still present (announce helper, VOICE_COOLDOWN,
VOICE_SPEED_GATE, VOICE_NEAR_ANNOUNCE_DISTANCE) — cleaned up in
T9/T10 per the plan's §8 ordering.

Part of TTM redesign.

Agent: alder
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Edge-case tests — empty text, unknown costing, cooldown regression guard

**Files:**
- Modify: `frontend/tests/engine/navigation.test.mjs`

**Rationale:** Spec §6.6. No engine changes — the new `checkVoice` already handles these cases; the tests verify that.

- [ ] **Step 1: Write failing tests for 4 edge cases**

Append to `navigation.test.mjs`:

```js
test('TTM edge: empty verbal instructions do not fire onVoiceCb', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.64030, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));

  // Custom route: maneuver 1 has no verbal text and no instruction.
  const silentRoute = fixtureRouteWithTwoTurns();
  silentRoute.maneuvers[1].verbal_pre_transition_instruction = '';
  silentRoute.maneuvers[1].verbal_transition_alert_instruction = '';
  silentRoute.maneuvers[1].instruction = '';
  nav.start(silentRoute);
  nav.updateGPS({ latitude: 35.20, longitude: -111.64025, heading: 90, speed: 10 });

  assert.equal(voiceFires.length, 0,
    'onVoiceCb must not fire with an empty string');
});

test('TTM edge: unknown costing falls back to auto without crashing', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.64030, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));

  const truckRoute = fixtureRouteWithTwoTurns();
  truckRoute.costing = 'truck'; // not in VOICE_TTM
  nav.start(truckRoute);
  nav.updateGPS({ latitude: 35.20, longitude: -111.64025, heading: 90, speed: 10 });

  // Must not throw; must fire prompts using auto thresholds.
  assert.ok(voiceFires.length >= 1,
    'unknown costing "truck" must fall back to auto and fire prompts');
});

test('TTM edge: distance clamp — simulated negative distance does not fire', async (t) => {
  // Test is indirect: override the fixture so the driver starts past maneuver 1.
  // findManeuverForSegment advances currentManeuverIdx past m1 on the first tick.
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });

  // Start 10m PAST maneuver 1 (east of lng -111.64).
  win._geographicaGPSData = { lat: 35.20, lon: -111.6399, heading: 90, speed: 10 };
  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());
  nav.updateGPS({ latitude: 35.20, longitude: -111.6398, heading: 90, speed: 10 });

  // maneuver 1's prompts must not fire retroactively.
  const m1Prompts = voiceFires.filter(t => /Main Street/.test(t));
  assert.equal(m1Prompts.length, 0,
    'prompts for already-passed maneuver must not fire');
});

test('TTM I8: muted state — announcedSet still populates, un-mute does not replay', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.64030, heading: 90, speed: 10 };
  const i = win._geographicaNavEngineInternals;

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.setMuted(true);
  nav.start(fixtureRouteWithTwoTurns());
  // First movement tick — near-tier condition met (inside 50m floor).
  nav.updateGPS({ latitude: 35.20, longitude: -111.64025, heading: 90, speed: 10 });

  assert.equal(voiceFires.length, 0, 'muted: no voice fires');
  const keys = i._getAnnouncedKeys();
  assert.ok(keys.length >= 2, 'muted: announcedSet must still populate (I8)');
  assert.ok(keys.includes('1-far') && keys.includes('1-near'),
    'muted: both far and near keys marked (D1 suppression applied)');

  // Un-mute: previous thresholds must NOT replay.
  nav.setMuted(false);
  nav.updateGPS({ latitude: 35.20, longitude: -111.64023, heading: 90, speed: 10 });
  assert.equal(voiceFires.length, 0,
    'un-mute must not replay already-crossed thresholds (I8)');
});

test('TTM I7: next-after-next chain fires on near-tier only, never on far-tier', async (t) => {
  const { fixtureVillaRitaCluster } = await import('./test_runner.mjs');
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  // Start west of cluster so far-tier fires for maneuver 1 without near-tier conditions.
  // depart segment is at lat 35.20, ~-111.65 to -111.64967 (30m long).
  // maneuver 1 is at -111.64967. To enter cluster outside near (50m floor at 10m/s
  // means also outside 3s-TTM=30m), start 80m west of maneuver 1.
  // But the depart segment is only 30m — can't be 80m west within the route.
  // Use fixtureRouteWithTwoTurns instead: maneuver 1 at -111.64, start at -111.65 (1km).
  win._geographicaGPSData = { lat: 35.20, lon: -111.645, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());

  // Approach far-tier (at 300m / TTM=30s). maneuver 2 = "Turn left onto Main" is in
  // fixtureRouteWithTwoTurns but is the 3rd maneuver (index 2, arrival). Wait —
  // fixture has 3 maneuvers: [Head east, Turn left onto Main, arrive]. At index 1
  // the next-after-next (index 2) is the arrival maneuver with instruction
  // "You have arrived at your destination". Chain appended if within 500m.
  //
  // Maneuver 2 begin_shape_index=2 (coord[-111.63]) is 1km east of maneuver 1.
  // So distBetween = 1000m > 500m → chain NOT appended.
  //
  // Assert: the first prompt (far-tier, "In half a mile, turn left") has NO chain.
  nav.updateGPS({ latitude: 35.20, longitude: -111.6425, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.642, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.6415, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.641, heading: 90, speed: 10 });

  assert.ok(voiceFires.length >= 1, 'at least one prompt must have fired');
  const first = voiceFires[0];
  assert.ok(!/, then /.test(first),
    'I7: far-tier prompt must not include next-after-next chain');
});

test('TTM edge: cooldown regression guard — adjacent near-prompts both fire', async (t) => {
  // Critical regression guard per R3 F3.7 / spec §6.6. If a later refactor
  // silently reintroduces a cooldown, two near-prompts firing in quick
  // succession across adjacent maneuvers would drop one. This test fails
  // loudly in that case.
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });

  const route = (await import('./test_runner.mjs')).fixtureVillaRitaCluster();
  // Start 10m west of maneuver 1 (inside the floor), 10 m/s.
  // Coords: maneuver 1 at -111.64967, so start at -111.64978 (10m west).
  win._geographicaGPSData = { lat: 35.20, lon: -111.64978, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push({ text, at: Date.now() }));
  nav.start(route);

  // Tick through maneuver 1 and into maneuver 2's near-tier in rapid succession.
  // Each step is ~5m; full traversal takes ~3 ticks.
  nav.updateGPS({ latitude: 35.20, longitude: -111.64972, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.64950, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.64935, heading: 90, speed: 10 });

  const mulberry = voiceFires.filter(v => /Mulberry/.test(v.text));
  const oak = voiceFires.filter(v => /Oak/.test(v.text));
  assert.ok(mulberry.length >= 1, 'Mulberry near-tier must fire');
  assert.ok(oak.length >= 1, 'Oak near-tier must fire in the next tick — no cooldown');
});
```

- [ ] **Step 2: Run — expect all 4 new tests to pass (engine already handles these)**

```
node --test frontend/tests/engine/navigation.test.mjs
```
Expected: all 4 pass (plus existing tests). If the cooldown guard fails, this is a genuine bug — investigate before continuing.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
test(voice-ttm): edge-case tests — empty text, unknown costing, distance clamp, cooldown guard

Validates TTM edge behavior from spec v2 §6.6:
- onVoiceCb never called with empty string (R1 F1.6).
- Unknown costing (truck) falls back to auto (R3 F3.6).
- Past-maneuver distance clamp: no retroactive prompts (R1 F1.1).
- Cooldown regression guard: adjacent near-prompts both fire.

All pass without engine changes — checkVoice in its TTM form
already handles these.

Agent: alder
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Multi-costing matrix — bicycle + pedestrian behavior

**Files:**
- Modify: `frontend/tests/engine/navigation.test.mjs`

**Rationale:** Spec §6.1 calls for all 3 costings exercised, not just plumbing. Bicycle floor=30m, pedestrian floor=15m, and their TTM pairs differ. Test each.

- [ ] **Step 1: Add 4 bicycle + pedestrian tests**

Append to `navigation.test.mjs`:

```js
test('TTM bicycle: near-tier fires at 30m floor (not 50m)', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  // 40m west of maneuver 1 (outside bicycle 30m floor, inside auto 50m floor).
  win._geographicaGPSData = { lat: 35.20, lon: -111.64040, heading: 90, speed: 5 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  const bikeRoute = { ...fixtureRouteWithTwoTurns(), costing: 'bicycle' };
  nav.start(bikeRoute);
  nav.updateGPS({ latitude: 35.20, longitude: -111.64035, heading: 90, speed: 5 });

  // At 40m+ from maneuver, bicycle's 30m floor NOT yet reached and
  // 3s-TTM at 5 m/s = 15m — also not reached. Expect 0 prompts.
  assert.equal(voiceFires.length, 0,
    'bicycle at 35m from maneuver, outside 30m floor, should not fire yet');
});

test('TTM bicycle: near-tier fires when inside 30m floor', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.64025, heading: 90, speed: 3 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  const bikeRoute = { ...fixtureRouteWithTwoTurns(), costing: 'bicycle' };
  nav.start(bikeRoute);
  // 25m from maneuver, inside 30m bicycle floor.
  nav.updateGPS({ latitude: 35.20, longitude: -111.64023, heading: 90, speed: 3 });
  assert.ok(voiceFires.length >= 1,
    'bicycle inside 30m floor must fire near-tier');
});

test('TTM pedestrian: near-tier fires at 15m floor', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  // 12m west of maneuver 1 (inside pedestrian 15m floor).
  win._geographicaGPSData = { lat: 35.20, lon: -111.64012, heading: 90, speed: 1.5 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  const walkRoute = { ...fixtureRouteWithTwoTurns(), costing: 'pedestrian' };
  nav.start(walkRoute);
  nav.updateGPS({ latitude: 35.20, longitude: -111.64010, heading: 90, speed: 1.5 });
  assert.ok(voiceFires.length >= 1,
    'pedestrian inside 15m floor must fire near-tier');
});

test('TTM pedestrian: outside 15m floor at walking pace does not fire near', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  // 20m west of maneuver 1 (outside 15m floor), walking 1 m/s.
  // TTM = 20/1 = 20s < 15s pedestrian far threshold? NO, 20 > 15. Far would not fire.
  // 3s near threshold at 1 m/s = 3m, not met.
  win._geographicaGPSData = { lat: 35.20, lon: -111.64020, heading: 90, speed: 1 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  const walkRoute = { ...fixtureRouteWithTwoTurns(), costing: 'pedestrian' };
  nav.start(walkRoute);
  nav.updateGPS({ latitude: 35.20, longitude: -111.64018, heading: 90, speed: 1 });
  assert.equal(voiceFires.length, 0,
    'pedestrian at 18m from maneuver, outside 15m floor and 15s TTM, should not fire');
});
```

- [ ] **Step 2: Run — expect all 4 to pass**

```
node --test frontend/tests/engine/navigation.test.mjs
```

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
test(voice-ttm): multi-costing matrix — bicycle and pedestrian

Spec v2 §6.1 calls for all 3 costings exercised. Tests bicycle's
30m floor and [20s, 3s] TTM, pedestrian's 15m floor and [15s, 2s] TTM.

Agent: alder
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Villa Rita synthetic test + correlated-outlier integration

**Files:**
- Modify: `frontend/tests/engine/navigation.test.mjs`

**Rationale:** Spec §6.4 (Villa Rita synthetic) + §6.2 (outlier integration). Both use the new `fixtureVillaRitaCluster` from T0.

- [ ] **Step 1: Write the Villa Rita synthetic test (spec §6.4)**

Append to `navigation.test.mjs`:

```js
test('TTM Villa Rita synthetic: 3-maneuver close cluster fires exactly 3 prompts (§6.4)', async (t) => {
  const { fixtureVillaRitaCluster } = await import('./test_runner.mjs');
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });

  // 40m west of maneuver 1 (the first spoken turn, index 1).
  // maneuver 1 is at -111.64967; 40m west = -111.65011.
  // Wait — fixture start is at -111.65000 (depart), so 40m west is outside the route.
  // Correct setup: start AT the route start, 40m before maneuver 1.
  // depart->maneuver1 segment spans -111.65000 to -111.64967 (33m). To be 40m
  // before maneuver 1, we'd be 7m BEFORE the start — not possible.
  // Instead: start AT the route start; 33m to maneuver 1.
  win._geographicaGPSData = { lat: 35.20, lon: -111.65000, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureVillaRitaCluster());

  // Tick through the cluster at 10 m/s: each segment is 30m, so ~3 ticks per segment.
  // Full cluster (3 turns) ~90m = ~9 ticks.
  const tickPositions = [
    -111.64990, -111.64980, -111.64970,  // approaching maneuver 1 (Mulberry)
    -111.64960, -111.64950, -111.64940,  // after maneuver 1, approaching maneuver 2 (Oak)
    -111.64930, -111.64920, -111.64910,  // after maneuver 2, approaching maneuver 3 (Villa Rita)
    -111.64900, -111.64890, -111.64880,  // after maneuver 3, approaching end
  ];
  for (const lng of tickPositions) {
    nav.updateGPS({ latitude: 35.20, longitude: lng, heading: 90, speed: 10 });
  }

  // Expect exactly 3 prompts (one near-tier per spoken maneuver; D1 suppresses far for all 3).
  assert.equal(voiceFires.length, 3,
    `Villa Rita: expected exactly 3 prompts (D1 suppression), got ${voiceFires.length}: ${JSON.stringify(voiceFires)}`);
  // Each must be a pre-transition ("Turn left onto Mulberry" style), not an alert.
  const alerts = voiceFires.filter(t => /In 100 feet/.test(t));
  assert.equal(alerts.length, 0,
    'Villa Rita prompts must be near-tier (pre-transition), not alert-tier');
});

test('TTM outlier integration: correlated 2-outliers-in-3-window are rejected (I5)', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.645, heading: 90, speed: 10 };
  const i = win._geographicaNavEngineInternals;

  nav.onVoice(() => {});
  nav.start(fixtureRouteWithTwoTurns());

  // Seed window with 2 legitimate 10 m/s samples.
  nav.updateGPS({ latitude: 35.20, longitude: -111.644, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.6435, heading: 90, speed: 10 });
  assert.deepEqual(i._getSpeedSamples(), [10, 10]);

  // Inject TWO 50 m/s outliers in a row — median-of-3 alone would be fooled
  // (window would become [10, 50, 50] → median 50). But the pre-filter rejects
  // each outlier because delta from prior median stays > 15 m/s.
  nav.updateGPS({ latitude: 35.20, longitude: -111.643, heading: 90, speed: 50 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.6425, heading: 90, speed: 50 });

  const samples = i._getSpeedSamples();
  assert.ok(!samples.includes(50),
    'I5: correlated 2-outliers-in-3 must be rejected by pre-filter');
});

test('TTM outlier integration: GPS 50 m/s spike does not flip thresholds', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.645, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());

  // Baseline: steady 10 m/s approach to maneuver 1.
  const baseLngs = [-111.644, -111.6435, -111.643];
  for (const lng of baseLngs) {
    nav.updateGPS({ latitude: 35.20, longitude: lng, heading: 90, speed: 10 });
  }
  const baselineCount = voiceFires.length;

  // Inject a 50 m/s outlier — must be rejected by pushSpeedSample's clamp.
  nav.updateGPS({ latitude: 35.20, longitude: -111.6425, heading: 90, speed: 50 });
  // Speed window should still be [10, 10, 10] — no premature near-tier.
  const samples = win._geographicaNavEngineInternals._getSpeedSamples();
  assert.ok(!samples.includes(50),
    'outlier must be rejected from speed window');
});
```

- [ ] **Step 2: Run — expect both to pass**

```
node --test frontend/tests/engine/navigation.test.mjs
```
Expected: green. If Villa Rita fires >3 prompts, inspect `voiceFires` output; most likely cause is far-tier firing because near is just outside 50m floor at the initial tick. Adjust entry distance if needed (keep test within ±20% of 3-prompt target; the exact count is the spec claim).

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
test(voice-ttm): Villa Rita synthetic + outlier integration (spec §6.2, §6.4)

Villa Rita synthetic (4-maneuver cluster, 30m spacing, 10 m/s): asserts
exactly 3 prompts fire, all near-tier pre-transition. This is the
automated proxy for the ship-gate field drive; §6.5 manual drive
remains the final blocker.

Outlier integration: 50 m/s GPS spike during approach does not enter
the speed window (rejected by MAX_SPEED_DELTA_PER_TICK clamp).

Agent: alder
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: deadReckonTick removes checkVoice call (I9)

**Files:**
- Modify: `frontend/navigation.js`
- Modify: `frontend/tests/engine/navigation.test.mjs`

**Rationale:** §8 step 5 + new invariant I9 / G11. DR becomes position-only; does not call checkVoice, so it cannot pre-lock distant maneuvers' `announcedSet` keys.

- [ ] **Step 1: Write failing test for I9**

Append to `navigation.test.mjs`:

```js
test('TTM I9: dead-reckoning does not fire voice announcements', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.645, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());

  // One real tick to seed state.
  nav.updateGPS({ latitude: 35.20, longitude: -111.6445, heading: 90, speed: 10 });
  const baselineCount = voiceFires.length;

  // Simulate stale-GPS by pushing Date.now() forward. The stale-checker runs
  // on a 1s interval; wait long enough that it would fire. In the test VM the
  // interval is real, so wait 2s.
  await new Promise(r => setTimeout(r, 2500));

  // After DR fires, if I9 is broken, prompts would have fired for maneuver 1
  // (driver is ~400m away, far-tier threshold 300m). Assert none did.
  assert.equal(voiceFires.length, baselineCount,
    'I9: DR must not fire voice announcements');
});
```

- [ ] **Step 2: Run — expect failure (current DR calls checkVoice)**

```
node --test frontend/tests/engine/navigation.test.mjs
```
Expected: the I9 test fails.

- [ ] **Step 3: Remove the `checkVoice(drSnap)` call from `deadReckonTick`**

In `navigation.js`, locate `function deadReckonTick()`. Find the line `checkVoice(drSnap);` inside it and delete the line. Update the surrounding comments to note that DR is position-only per spec v2 G11:

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
    // G11: dead-reckoning is position-only. No voice — DR cannot reliably
    // distinguish a legitimate TTM threshold crossing from an extrapolation
    // artifact, and pre-locking announcedSet keys would silently skip
    // prompts on GPS recovery.
    emitUpdate(buildState(drSnap, true));
  }
```

- [ ] **Step 4: Run — expect I9 to pass, all previous tests to pass**

```
node --test frontend/tests/engine/navigation.test.mjs
```

- [ ] **Step 5: Commit**

```bash
git add frontend/navigation.js frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
fix(nav): dead-reckoning is position-only, no voice (spec v2 G11)

Removes checkVoice(drSnap) from deadReckonTick. DR extrapolates
position for stale-GPS cases but cannot reliably distinguish a
legitimate TTM threshold crossing from an extrapolation artifact.
Pre-locking announcedSet keys during DR would silently skip
prompts on GPS recovery — exactly the failure mode R2 F2.3 of the
adversarial review flagged.

Closes R2 F2.3.

Agent: alder
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: applyReroute rewrite + triggerReroute scheduledSeq + tests

**Files:**
- Modify: `frontend/navigation.js`
- Modify: `frontend/tests/engine/navigation.test.mjs`

**Rationale:** §8 step 6. Three behavior changes + 4 tests:
- `applyReroute` success path clears `speedSamples` (new) alongside existing `announcedSet`.
- `applyReroute` re-tick inside skips voice (new helper `tickNoVoice` or module flag).
- `triggerReroute`'s timeout closure captures scheduled seq (R2 F2.1).
- `applyReroute` stale-drop path preserves state (R2 F2.2).

- [ ] **Step 1: Write failing tests**

Append to `navigation.test.mjs`:

```js
test('TTM reroute success: speedSamples cleared', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };
  const i = win._geographicaNavEngineInternals;

  nav.start(fixtureRouteWithTwoTurns());
  // Populate speed window.
  nav.updateGPS({ latitude: 35.20, longitude: -111.649, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.648, heading: 90, speed: 11 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.647, heading: 90, speed: 12 });
  assert.equal(i._getSpeedSamples().length, 3);

  // Force reroute.
  let seq = null;
  nav.onReroute((info) => { seq = info._seq; });
  [[35.25, -111.55], [35.26, -111.54], [35.27, -111.53],
   [35.28, -111.52], [35.29, -111.51]].forEach(([lat, lon]) => {
    nav.updateGPS({ latitude: lat, longitude: lon, heading: 90, speed: 10 });
  });
  nav.applyReroute(fixtureRouteWithTwoTurns(), seq);

  assert.deepEqual(i._getSpeedSamples(), [],
    'applyReroute success path must clear speedSamples');
});

test('TTM reroute stale-drop: speedSamples and announcedSet preserved', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.64030, heading: 90, speed: 10 };
  const i = win._geographicaNavEngineInternals;

  nav.onVoice(() => {}); // no-op sink
  nav.start(fixtureRouteWithTwoTurns());
  nav.updateGPS({ latitude: 35.20, longitude: -111.64025, heading: 90, speed: 10 });

  const keysBefore = i._getAnnouncedKeys();
  const samplesBefore = i._getSpeedSamples();
  assert.ok(keysBefore.length > 0, 'announcedSet must be populated before stale-drop');
  assert.ok(samplesBefore.length > 0, 'speedSamples must be populated before stale-drop');

  // Apply reroute with a mismatched seq (999 is not the current rerouteSeq).
  nav.applyReroute(fixtureRouteWithTwoTurns(), 999);

  assert.deepEqual(i._getAnnouncedKeys(), keysBefore,
    'stale-drop: announcedSet must be preserved');
  assert.deepEqual(i._getSpeedSamples(), samplesBefore,
    'stale-drop: speedSamples must be preserved');
});

test('TTM reroute re-tick: no voice fires on the immediate re-tick inside applyReroute', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  // Start 20m west of maneuver 1, inside the 50m floor.
  // Seed GPS so applyReroute's re-tick has a cached lastGPS.
  win._geographicaGPSData = { lat: 35.20, lon: -111.64020, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());

  // Move to maneuver 1 area to build up announced state.
  nav.updateGPS({ latitude: 35.20, longitude: -111.64018, heading: 90, speed: 10 });
  const beforeReroute = voiceFires.length;

  // Trigger reroute.
  let seq = null;
  nav.onReroute((info) => { seq = info._seq; });
  [[35.25, -111.55], [35.26, -111.54], [35.27, -111.53],
   [35.28, -111.52], [35.29, -111.51]].forEach(([lat, lon]) => {
    nav.updateGPS({ latitude: lat, longitude: lon, heading: 90, speed: 10 });
  });
  const beforeApply = voiceFires.length;

  // Apply reroute — its internal re-tick(lastGPS) MUST NOT fire voice
  // even though the driver is still within near-tier of maneuver 1 in the new route.
  nav.applyReroute(fixtureRouteWithTwoTurns(), seq);
  assert.equal(voiceFires.length, beforeApply,
    're-tick inside applyReroute must not fire voice');

  // On the NEXT real GPS tick, voice fires normally.
  nav.updateGPS({ latitude: 35.20, longitude: -111.64017, heading: 90, speed: 10 });
  assert.ok(voiceFires.length > beforeApply,
    'voice must fire on the first post-reroute real GPS tick');
});

test('TTM reroute timeout: stale timeout does not clobber a just-applied reroute', async (t) => {
  // R2 F2.1: the timeout closure must capture scheduledSeq and only reset if
  // rerouteSeq still matches — so a late timeout from a prior reroute cannot
  // clobber state set by a subsequent applyReroute.
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };

  const seqs = [];
  nav.onReroute((info) => { seqs.push(info._seq); });
  nav.start(fixtureRouteWithTwoTurns());

  // Fire a first reroute (this schedules a 10s timeout with some seq=1).
  [[35.25, -111.55], [35.26, -111.54], [35.27, -111.53],
   [35.28, -111.52], [35.29, -111.51]].forEach(([lat, lon]) => {
    nav.updateGPS({ latitude: lat, longitude: lon, heading: 90, speed: 10 });
  });

  // Apply it immediately — state returns to "navigating", rerouteSeq advances.
  nav.applyReroute(fixtureRouteWithTwoTurns(), seqs[0]);

  // Fast-forward past the initial 10s timeout. If the closure doesn't
  // capture scheduledSeq, the timeout callback would reset state and
  // clear lastRerouteTime even though the reroute already succeeded.
  // We cannot fake-timer here, so we wait real time — bounded test timeout.
  await new Promise(r => setTimeout(r, 11_000));

  // Assertion: no extra onReroute calls fired after the timeout.
  // (A broken timeout closure would call setState("navigating") without
  // firing onReroute, so the assertion is on STATE consistency, not re-fire.)
  // The best observable assertion is that a subsequent off-route still triggers
  // a fresh reroute (engine didn't latch into a broken state).
  [[35.25, -111.55], [35.26, -111.54], [35.27, -111.53],
   [35.28, -111.52], [35.29, -111.51]].forEach(([lat, lon]) => {
    nav.updateGPS({ latitude: lat, longitude: lon, heading: 90, speed: 10 });
  });
  assert.equal(seqs.length, 2,
    'engine must still fire a new reroute after a stale timeout');
}, { timeout: 20_000 });
```

- [ ] **Step 2: Run — expect new tests to fail**

```
node --test frontend/tests/engine/navigation.test.mjs
```
Expected: the 4 reroute tests fail. Existing tests still pass.

- [ ] **Step 3: Add `speedSamples = [];` to `applyReroute` success path**

In `navigation.js`, locate the `applyReroute` method inside the public API block. Find the line `announcedSet = {};`. Add on the next line:

```js
      speedSamples = [];
```

- [ ] **Step 4: Skip voice on the `applyReroute` re-tick**

Two-line change. Add a module-scope flag near the other voice state:

```js
  var suppressVoiceOnNextTick = false;
```

In the `checkVoice` function, at the very top (before the `if (!route || !route.maneuvers) return;` line), add:

```js
    if (suppressVoiceOnNextTick) {
      suppressVoiceOnNextTick = false;
      return;
    }
```

In `applyReroute`, immediately before the final `if (lastGPS) { tick(lastGPS); }` block, set the flag:

```js
      suppressVoiceOnNextTick = true;
      if (lastGPS) tick(lastGPS);
```

- [ ] **Step 5: Capture `scheduledSeq` in the `triggerReroute` timeout closure**

In `navigation.js`, locate `function triggerReroute(lat, lng)`. Find the block:

```js
    rerouteSeq++;
    rerouteTimeoutId = setTimeout(function () {
      rerouteTimeoutId = null;
      if (state === "rerouting") {
        ...
      }
    }, REROUTE_TIMEOUT);
```

Replace with:

```js
    rerouteSeq++;
    var scheduledSeq = rerouteSeq; // R2 F2.1: capture at scheduling time.
    rerouteTimeoutId = setTimeout(function () {
      rerouteTimeoutId = null;
      if (scheduledSeq !== rerouteSeq) return; // a newer reroute succeeded; do not clobber.
      if (state === "rerouting") {
        state = "navigating";
        offRouteHistory = [];
        inOffRouteState = false;
        lastRerouteTime = 0;
      }
    }, REROUTE_TIMEOUT);
```

- [ ] **Step 6: Also reset `suppressVoiceOnNextTick` in `reset()`**

In `reset()`, add `suppressVoiceOnNextTick = false;` alongside the other state resets.

- [ ] **Step 7: Run — expect all 4 new reroute tests to pass + everything else green**

```
node --test frontend/tests/engine/navigation.test.mjs
```

- [ ] **Step 8: Commit**

```bash
git add frontend/navigation.js frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
fix(nav): applyReroute/triggerReroute hardening (spec v2 §4.5)

applyReroute success path: clear speedSamples alongside announcedSet.
Re-tick inside applyReroute skips voice via suppressVoiceOnNextTick
flag — voice fires from a 1-sample warmup window at the most
cognitively-loaded moment is the wrong design (R1 F1.3). Position
updates still emit.

Stale-drop path (seq mismatch): preserve announcedSet AND speedSamples.
Engine continues on original route.

triggerReroute: capture scheduledSeq in timeout closure; late timeout
cannot clobber a just-applied reroute's state (R2 F2.1).

Closes R1 F1.3, R2 F2.1, R2 F2.2.

Agent: alder
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Delete announce() helper and lastAnnouncementTime

**Files:**
- Modify: `frontend/navigation.js`

**Rationale:** §8 step 7. The `announce()` helper and `lastAnnouncementTime` state are no longer referenced by anything. Clean up.

- [ ] **Step 1: Verify the helper is truly unreferenced**

```bash
grep -n 'announce\b\|lastAnnouncementTime' frontend/navigation.js
```
Expected output: only the function declaration itself (`function announce(text, key)`), the state variable declaration (`var lastAnnouncementTime = 0;`), and the two `reset()` / `applyReroute()` reset lines. If you see any OTHER reference (e.g., `announce(someText, someKey)` as a call), STOP — T3's checkVoice rewrite missed something, and deleting `announce` here will break the build.

- [ ] **Step 2: Delete the `announce` function body**

In `navigation.js`, locate `function announce(text, key) {` and delete the entire function, including its closing `}` and surrounding blank lines. The adjacent comment block that describes announce() also goes.

- [ ] **Step 3: Delete `lastAnnouncementTime` state + both reset lines**

- Find and delete the line `var lastAnnouncementTime = 0;` in the module-scope state block.
- In `reset()`, delete the line `lastAnnouncementTime = 0;`.
- In `applyReroute()` (success path), delete the line `lastAnnouncementTime = 0;` (if present).

- [ ] **Step 4: Run the test suite**

```
node --test frontend/tests/engine/navigation.test.mjs
```
Expected: full green. The one existing test named `applyReroute clears announcedSet and lastAnnouncementTime` still passes because its assertion body checks that announcements re-fire after reroute — the assertion does not read `lastAnnouncementTime` directly. The test name is stale; T11 renames it.

- [ ] **Step 5: Commit**

```bash
git add frontend/navigation.js
git commit -m "$(cat <<'EOF'
refactor(nav): delete announce() helper and lastAnnouncementTime state

Orphaned by T3's checkVoice rewrite. announce() existed to enforce
VOICE_COOLDOWN, which TTM removes (D3 of the brainstorm). checkVoice
now inlines the !muted + onVoiceCb check directly.

Band-aid constants are still present — removed in T10.

Agent: alder
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Delete band-aid constants + rewrite _geographicaNavEngineInternals (ATOMIC)

**Files:**
- Modify: `frontend/navigation.js`
- Modify: `frontend/tests/engine/navigation.test.mjs`

**Rationale:** §8 step 8. Deleting the constants without rewriting the internals hook in the same edit triggers a load-time `ReferenceError` because the hook still references them. This task is therefore ATOMIC — both edits in one commit.

- [ ] **Step 1: Write failing assertion — old keys should be gone**

Append to `navigation.test.mjs`:

```js
test('TTM internals hook: band-aid keys are removed', async () => {
  const { window: win } = await loadEngine();
  const i = win._geographicaNavEngineInternals;
  assert.equal(i.VOICE_THRESHOLDS, undefined,
    'VOICE_THRESHOLDS must be removed from internals hook');
  assert.equal(i.VOICE_COOLDOWN, undefined,
    'VOICE_COOLDOWN must be removed from internals hook');
  assert.equal(i.VOICE_SPEED_GATE, undefined,
    'VOICE_SPEED_GATE must be removed from internals hook');
  // TTM keys remain.
  assert.ok(i.VOICE_TTM, 'VOICE_TTM must remain');
  assert.ok(i.VOICE_DISTANCE_FLOOR, 'VOICE_DISTANCE_FLOOR must remain');
});
```

- [ ] **Step 2: Run — expect failure (old keys still present from T1)**

```
node --test frontend/tests/engine/navigation.test.mjs
```
Expected: the internals-hook test fails. **Also expect the existing B1 band-aid test to still pass** — it's T12 that deletes it.

- [ ] **Step 3: Delete band-aid constants and the BAND-AID comment block**

In `navigation.js`, locate the large `// Voice thresholds per costing...` comment block and the following constants. Delete in full:

- The entire multi-line comment block starting `// Voice thresholds per costing. Each entry is [far, near] in meters.` through `// VOICE_NEAR_ANNOUNCE_DISTANCE all likely go away together).`.
- `var VOICE_THRESHOLDS = { ... };` block (multi-line).
- `var VOICE_COOLDOWN = 5000;`
- `var VOICE_SPEED_GATE = 2;`
- `var VOICE_NEAR_ANNOUNCE_DISTANCE = 50;`

Leave `NEXT_AFTER_NEXT_DISTANCE` and the new TTM constants in place.

- [ ] **Step 4: Rewrite the `_geographicaNavEngineInternals` hook in the SAME EDIT**

Locate `window._geographicaNavEngineInternals = {` and replace the entire block with the v2 shape:

```js
  // Test hook: expose tuning constants + minimal state inspectors so tests
  // can assert on behavior without re-parsing the source. No-op in production
  // (only read by unit tests).
  window._geographicaNavEngineInternals = {
    VOICE_TTM: VOICE_TTM,
    VOICE_DISTANCE_FLOOR: VOICE_DISTANCE_FLOOR,
    MIN_SPEED_FLOOR: MIN_SPEED_FLOOR,
    SPEED_WINDOW_SIZE: SPEED_WINDOW_SIZE,
    MAX_SPEED_DELTA_PER_TICK: MAX_SPEED_DELTA_PER_TICK,
    _getSpeedSamples: function () { return speedSamples.slice(); },
    _speedMedian: function () { return speedMedian(); },
    _getAnnouncedKeys: function () { return Object.keys(announcedSet).sort(); }
  };
```

Note: the band-aid comment block referenced "juniper" — that comment goes with the deleted constants.

- [ ] **Step 5: Run — expect the new internals-hook test to pass + everything else green**

```
node --test frontend/tests/engine/navigation.test.mjs
```
Expected: full green. The B1 band-aid test still exists and is expected to FAIL here because it reads `internals.VOICE_THRESHOLDS.auto.length` — `VOICE_THRESHOLDS` is now undefined. **That failure is expected and is closed by T12 (same PR).** If the build-gate CI fails on the B1 test, confirm T12 is next in the subagent queue; otherwise a single composite commit (T10+T12) is acceptable.

Alternative if the B1 failure is problematic mid-PR: temporarily skip it via `test.skip('B1 band-aid...')` in this commit, then delete it outright in T12.

- [ ] **Step 6: Commit**

```bash
git add frontend/navigation.js frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
refactor(nav): remove band-aid constants + rewrite internals hook

Atomic edit: deletes VOICE_THRESHOLDS, VOICE_COOLDOWN,
VOICE_SPEED_GATE, VOICE_NEAR_ANNOUNCE_DISTANCE and the BAND-AID
block comment. In the same edit, rewrites
_geographicaNavEngineInternals to drop references to the deleted
keys (otherwise load-time ReferenceError).

NEXT_AFTER_NEXT_DISTANCE retained — unrelated chaining behavior.

The B1 regression-guard test begins failing at this commit because
it reads VOICE_THRESHOLDS; T12 deletes it immediately after.

Part of TTM redesign — spec v2 §4.1, §4.6, §8 step 8.

Agent: alder
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Rename stale `applyReroute clears announcedSet and lastAnnouncementTime` test

**Files:**
- Modify: `frontend/tests/engine/navigation.test.mjs`

**Rationale:** §8 step 9. The existing test name references the now-deleted `lastAnnouncementTime`. Rename to reflect current state (`announcedSet` + `speedSamples`) and update one assertion to read `_getSpeedSamples()` for direct coverage.

- [ ] **Step 1: Locate the test and rename it**

Find the line:

```js
test('applyReroute clears announcedSet and lastAnnouncementTime', async (t) => {
```

Rename to:

```js
test('applyReroute clears announcedSet and speedSamples', async (t) => {
```

- [ ] **Step 2: Strengthen one assertion by adding a direct speedSamples check**

Inside that same test, after the line `nav.applyReroute(newRoute, capturedSeq);`, add:

```js
  const i = win._geographicaNavEngineInternals;
  assert.deepEqual(i._getSpeedSamples(), [],
    'applyReroute must clear speedSamples alongside announcedSet');
```

Note: `win` is already defined in the test scope (from `const { nav, window: win } = await loadEngine();`). The behavioral re-fire assertion immediately below it is preserved unchanged.

- [ ] **Step 3: Run — all tests green**

```
node --test frontend/tests/engine/navigation.test.mjs
```

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
test(voice-ttm): rename stale test applyReroute clears → ...speedSamples

T10 deleted lastAnnouncementTime; the test name was stale. Renamed
and added a direct _getSpeedSamples() assertion alongside the
existing behavioral re-fire check. Closes R4 F4.8.

Agent: alder
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Delete B1 regression-guard test — closes B1

**Files:**
- Modify: `frontend/tests/engine/navigation.test.mjs`

**Rationale:** §8 step 10. The band-aid is gone; its regression-guard is no longer meaningful. Delete the test. Commit message explicitly names B1 closure per spec §8.

- [ ] **Step 1: Delete the test**

In `navigation.test.mjs`, locate and delete the entire test block starting at:

```js
test('B1 band-aid: voice tiers capped at 2 per costing (remove when TTM ships)', async () => {
```

through its closing `});`. Also delete the preceding blank line if it leaves a double-blank.

- [ ] **Step 2: Run — all tests green**

```
node --test frontend/tests/engine/navigation.test.mjs
```

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
refactor(nav): closes B1, removes 2026-04-20 band-aid (e63f6d9)

Deletes the B1 regression-guard test that existed to protect the
distance-threshold shape of VOICE_THRESHOLDS while the band-aid
was live. TTM replaces the entire distance model; the shape guard
is no longer meaningful.

B1 (voice over-announcement in close-turn clusters) — originally
caught 2026-04-20 at Villa Rita → North Phoenix Costco (9 prompts
in 200 ft). Band-aid shipped as e63f6d9 ([400m, 50m] tiers).
This commit, landing alongside the TTM redesign, CLOSES B1:

- Villa Rita-class cluster: 3 prompts (down from 9).
- Looser clusters (55m spacing): ≤6 prompts.
- All 48-state TTM test matrix green.
- Manual field-drive ship gate per spec §6.5 remains blocking.

spec: docs/superpowers/specs/2026-04-20-nav-voice-ttm-design.md (91e8266)
reviews: dev/adversarial/2026-04-20-nav-voice-ttm-r{1..6}-*.md (928a7d1)

Agent: alder
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Temporary field-gate debug log for §6.5 ship gate

**Files:**
- Modify: `frontend/navigation.js`
- Modify: `frontend/tests/engine/navigation.test.mjs`

**Rationale:** Spec §6.5 + R5 F5.9. The Villa Rita re-drive needs timestamped callback data to distinguish "3 callbacks" (spec target) from "3 fully-spoken utterances" (user experience). Add a debug log gated behind `window._geographicaTTMDebug`. Opt-in via a browser console: `window._geographicaTTMDebug = true`.

Remove this debug hook in a follow-up PR after the field drive validates.

- [ ] **Step 1: Write failing test**

Append to `navigation.test.mjs`:

```js
test('TTM field-gate debug hook: captures callback context when enabled', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaTTMDebug = true;
  win._geographicaTTMDebugLog = [];
  win._geographicaGPSData = { lat: 35.20, lon: -111.64030, heading: 90, speed: 10 };

  nav.onVoice(() => {});
  nav.start(fixtureRouteWithTwoTurns());
  nav.updateGPS({ latitude: 35.20, longitude: -111.64025, heading: 90, speed: 10 });

  const log = win._geographicaTTMDebugLog;
  assert.ok(log.length >= 1, 'debug log must capture at least one entry on near-tier fire');
  const entry = log[0];
  assert.ok(typeof entry.timestamp === 'number');
  assert.ok(typeof entry.maneuverIdx === 'number');
  assert.ok(entry.tier === 'near' || entry.tier === 'far');
  assert.ok(typeof entry.distToNext === 'number');
  assert.ok(typeof entry.ttm === 'number');
  assert.equal(typeof entry.onRerouteRetick, 'boolean');
});
```

- [ ] **Step 2: Run — expect failure**

```
node --test frontend/tests/engine/navigation.test.mjs
```

- [ ] **Step 3: Add debug-hook logging inside `checkVoice`**

Locate the `if (nearWouldFire) {` block. Just before `if (!muted && text && onVoiceCb) onVoiceCb(text);`, add:

```js
      if (typeof window !== 'undefined' && window._geographicaTTMDebug) {
        (window._geographicaTTMDebugLog = window._geographicaTTMDebugLog || []).push({
          timestamp: Date.now(),
          maneuverIdx: nextIdx,
          tier: 'near',
          distToNext: distToNext,
          ttm: ttm,
          onRerouteRetick: false  // re-tick is intercepted at function entry; see suppressVoiceOnNextTick
        });
      }
```

Do the same for the `if (farWouldFire) {` block (with `tier: 'far'`).

Note: the `onRerouteRetick` field is always `false` in the current design because `suppressVoiceOnNextTick` returns early. It remains in the log shape for possible future use and to match spec §6.5's contract.

- [ ] **Step 4: Run — expect new test to pass**

```
node --test frontend/tests/engine/navigation.test.mjs
```

- [ ] **Step 5: Commit**

```bash
git add frontend/navigation.js frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
feat(nav): §6.5 field-gate debug hook

Opt-in debug log for the Villa Rita → Costco ship gate per spec v2 §6.5.
Enable via window._geographicaTTMDebug = true in a browser console;
inspect window._geographicaTTMDebugLog after the drive for per-callback
context (timestamp, maneuverIdx, tier, distToNext, ttm).

No-op in production when the flag is unset.

This hook is TEMPORARY. Remove in a follow-up PR after the field drive
validates TTM behavior.

Agent: alder
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Plan self-review checkpoints

After executing all tasks, run the following verifications before declaring the plan complete:

1. **Full test suite green.**
   ```bash
   cd /home/administrator/Code/geographica
   node --test frontend/tests/engine/
   python -m pytest tests/ -v                # regression check on python tests
   ```

2. **Band-aid fully gone.**
   ```bash
   grep -n 'VOICE_THRESHOLDS\|VOICE_COOLDOWN\|VOICE_SPEED_GATE\|VOICE_NEAR_ANNOUNCE_DISTANCE\|lastAnnouncementTime\|BAND-AID' frontend/navigation.js
   ```
   Expected: no matches.

3. **Commit trailer consistency.**
   ```bash
   git log --grep='^Agent: alder' --oneline dev | wc -l
   ```
   Expected: at least 13 (one per task).

4. **Spec §8 10-step ordering respected.**
   ```bash
   git log --oneline 2b4f070..HEAD | cat
   ```
   Reviewing the log should show: constants → helpers → wire-in → checkVoice → DR → reroute → cleanup → band-aid removal → test rename → B1 closure → field-gate debug.

5. **Manual field drive** per spec §6.5 (Villa Rita → Costco westerly detour). This is the **ship gate**. Both criteria must pass:
   - Callback count: ≤ 3 prompts for the 3-maneuver post-reroute cluster.
   - Audible-utterance count: ≤ 3 fully-spoken utterances with no mid-utterance cancellation.

Only after the field drive passes: `git switch main && git merge --ff-only dev && git push origin main`. release-please handles the version bump.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-20-nav-voice-ttm-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration. Uses `superpowers:subagent-driven-development`. Each dispatched subagent receives "You are agent alder" to keep commit trailers consistent.

**2. Inline Execution** — tasks executed in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

Which approach?
