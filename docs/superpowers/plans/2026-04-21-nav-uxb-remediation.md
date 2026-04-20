# Navigation UX Beta-Bug Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 2026-04-21 beta-tester navigation bug reports (4 primary + 9 adjacent) with a refactor-first, TDD-disciplined patch series that eliminates the "split active-route state" bug class and establishes the first automated tests for the nav engine.

**Architecture:**
- **Engine fixes** (pure JS in [frontend/navigation.js](../../../frontend/navigation.js)) get Node `node:test` unit tests that load the engine into a `vm` sandbox — no new dependencies, first-ever automated coverage for the nav state machine.
- **UI + reroute-data-flow fixes** (in [frontend/nav-ui.js](../../../frontend/nav-ui.js)) use Playwright assertions added to the existing [dev/harness/](../../../dev/harness/) infrastructure — same package.json, same `node:test` runner.
- **B2 is fixed by refactor, not band-aid:** introduce `setActiveRoute(trip, options)` that owns the engine, `window._geographicaLastTrip`, `lastRouteCoords`, the map `'route'` source, and the sidebar directions list. Initial-route and reroute paths both go through it.
- **B1 (voice tiering) is deliberately out of scope** — to be addressed by a separate TTM (time-to-maneuver) redesign with its own brainstorm + spec + adversarial review. See appendix.

**Tech Stack:** Vanilla JS + MapLibre GL JS frontend (no build step), Node 20+ `node:test` for engine tests, Playwright 1.48 for UI integration, conventional commits + release-please.

---

## Pre-flight: For every subagent executing a task

BEFORE starting any task below:
1. Read the skill: [.claude/skills/superpowers/test-driven-development/SKILL.md](../../../.claude/skills/superpowers/test-driven-development/SKILL.md) (or invoke `/test-driven-development`).
2. Read [dev/testing-pitfalls.md](../../../dev/testing-pitfalls.md) — several entries at the top are directly relevant (consecutive-counter fragility, polling-rate-vs-counter thresholds, announce-once state consumed on check, unrecoverable state on async failure, JS truthiness for numeric zero, split state across engine/UI globals/map sources).
3. Follow TDD: write the failing test → run it to confirm RED → implement minimal fix → run it to confirm GREEN → commit.
4. Read the **context block** at the top of each task — it lists the exact lines to touch and what the bug is.

BEFORE marking any task complete:
1. Review your tests against [dev/testing-pitfalls.md](../../../dev/testing-pitfalls.md). Are you hitting any documented pitfall? If yes, add explicit coverage.
2. Verify test coverage of the fix: are error paths tested? Are zero/null/undefined inputs tested?
3. Run the relevant test subset and confirm green.
4. Stage the minimal file set and commit with a conventional-commit message matching the scope (`fix(nav): ...` for engine/UI fixes, `refactor(nav): ...` for the setActiveRoute extraction, `test(nav): ...` for test-only additions).

AFTER every logical group of tasks (marked "**REVIEW LOOP**" below):
You MUST carefully review the batch of work from multiple perspectives and revise/refine as appropriate. Repeat this review loop (minimum 3 rounds; if you still find substantive issues in the third review, keep going with additional rounds until there are no findings). Then update your private journal and continue onto the next tasks.

---

## File Structure

**New files:**
- [frontend/tests/engine/test_runner.mjs](../../../frontend/tests/engine/test_runner.mjs) — Node `vm` sandbox loader for `navigation.js`
- [frontend/tests/engine/navigation.test.mjs](../../../frontend/tests/engine/navigation.test.mjs) — engine unit tests
- [dev/harness/drive-nav.mjs](../../../dev/harness/drive-nav.mjs) — Playwright harness for nav-UI integration

**Modified files:**
- [frontend/navigation.js](../../../frontend/navigation.js) — engine hygiene: applyReroute state reset (B9), reroute timeout cleanup (B10), GPS position dedup (B7), onReroute payload extension for costingOptions (B6)
- [frontend/nav-ui.js](../../../frontend/nav-ui.js) — buildRouteData updates for B5 (waypoints), B6 (costing_options), B13 (begin_shape_index clamp); reroute robustness for B11 (200-with-error) and B12 (abort on stop); padding math (B3+B8); mute propagation (B14); setActiveRoute call site (B2)
- [frontend/app.js](../../../frontend/app.js) — `setActiveRoute` owner function (B2 refactor); initial-route site converted; trip costingOptions storage (B6)
- [frontend/style.css](../../../frontend/style.css) — recenter/compass button stack (B4)

**Unchanged (by decision):**
- `VOICE_THRESHOLDS` in [navigation.js:42-46](../../../frontend/navigation.js#L42-L46) — B1 intentionally deferred to TTM redesign.

---

## Phase 0 — Engine test harness bootstrap

### Task 0: Node `vm`-based engine test runner

**Files:**
- Create: `frontend/tests/engine/test_runner.mjs`
- Create: `frontend/tests/engine/README.md`

**Context:** `frontend/navigation.js` is a browser IIFE that attaches `window.GeographicaNav`. To unit-test it in Node without a browser, we load the file via `node:vm` into a sandbox that exposes a fake `window` object. Node 20+ has `node:test` built in; no new dependencies.

- [ ] **Step 1: Create the runner that loads navigation.js into a sandbox**

Create `frontend/tests/engine/test_runner.mjs`:

```javascript
// Loads frontend/navigation.js into a vm sandbox exposing a fake window
// object and returns { nav, reset } where `nav` is window.GeographicaNav.
//
// Usage:
//   import { loadEngine } from './test_runner.mjs';
//   const { nav } = await loadEngine();
//   nav.start(routeData);
//
// Each call returns a FRESH engine instance (the IIFE is re-executed in a
// fresh vm.Context, so module-level mutable state — announcedSet,
// rerouteSeq, route, etc — starts clean).

import { readFileSync } from 'node:fs';
import { createContext, runInContext } from 'node:vm';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const NAV_JS_PATH = join(__dirname, '..', '..', 'navigation.js');

export async function loadEngine() {
  const code = readFileSync(NAV_JS_PATH, 'utf8');
  const win = {};
  const sandbox = {
    window: win,
    Date,
    Math,
    Object,
    Array,
    Number,
    String,
    parseInt,
    parseFloat,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    console,
  };
  const ctx = createContext(sandbox);
  runInContext(code, ctx, { filename: 'navigation.js' });
  if (!win.GeographicaNav) {
    throw new Error('GeographicaNav was not attached to window');
  }
  return { nav: win.GeographicaNav, window: win };
}

// Fixture: a minimal 2-maneuver straight-line route for general testing.
// Coords are in [lng, lat] order per MapLibre/Valhalla convention.
export function fixtureTwoManeuverRoute() {
  return {
    coords: [
      [-111.65, 35.20],  // start
      [-111.64, 35.20],  // maneuver 1 boundary (~1 km east)
      [-111.63, 35.21],  // end (~1 km NE)
    ],
    maneuvers: [
      {
        type: 1,
        instruction: 'Head east on Route 66',
        verbal_transition_alert_instruction: 'In half a mile, turn left',
        verbal_pre_transition_instruction: 'Turn left onto Oak Street',
        begin_shape_index: 0,
        end_shape_index: 1,
      },
      {
        type: 15,
        instruction: 'You have arrived at your destination',
        begin_shape_index: 2,
        end_shape_index: 2,
      },
    ],
    summary: { length: 2.0, time: 120 },
    totalDistance: 2000,
    totalTime: 120,
    costing: 'auto',
    remainingWaypoints: [],
  };
}
```

- [ ] **Step 2: Smoke test — runner loads without crash**

Create `frontend/tests/engine/navigation.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadEngine, fixtureTwoManeuverRoute } from './test_runner.mjs';

test('engine loads and exposes the expected API', async () => {
  const { nav } = await loadEngine();
  assert.equal(typeof nav.start, 'function');
  assert.equal(typeof nav.stop, 'function');
  assert.equal(typeof nav.updateGPS, 'function');
  assert.equal(typeof nav.applyReroute, 'function');
  assert.equal(typeof nav.setMuted, 'function');
  assert.equal(typeof nav.onUpdate, 'function');
  assert.equal(typeof nav.onReroute, 'function');
  assert.equal(typeof nav.getState, 'function');
});

test('start enters navigating when GPS is on-route', async () => {
  const { nav, window: win } = await loadEngine();
  win._geographicaGPSData = {
    lat: 35.20, lon: -111.65, heading: 90, speed: 5,
  };
  const updates = [];
  nav.onUpdate((s) => updates.push(s));
  nav.start(fixtureTwoManeuverRoute());
  assert.equal(updates.length, 1);
  assert.equal(updates[0].state, 'navigating');
});
```

- [ ] **Step 3: Run — confirm green**

Run: `node --test frontend/tests/engine/`
Expected: `# pass 2` / `# fail 0`

- [ ] **Step 4: Create README**

Create `frontend/tests/engine/README.md`:

```markdown
# Nav Engine Tests

Node 20+ `node:test` unit tests for [frontend/navigation.js](../../navigation.js).

## Run

```bash
node --test frontend/tests/engine/
```

## Design

The engine is a browser IIFE that attaches to `window.GeographicaNav`.
`test_runner.mjs` loads it via `node:vm` into a sandbox exposing a fake
`window`. Each `loadEngine()` call returns a FRESH engine — the IIFE
re-executes, so all module-level mutable state (announcedSet,
rerouteSeq, route) starts clean.

Tests import fixtures from `test_runner.mjs` — e.g. `fixtureTwoManeuverRoute`
gives a known 2-maneuver straight-line route for predictable snapping.
```

- [ ] **Step 5: Commit**

```bash
git add frontend/tests/engine/
git commit -m "$(cat <<'EOF'
test(nav): bootstrap Node vm-based engine test harness

Loads frontend/navigation.js into a fresh node:vm sandbox per test so
module-level state (announcedSet, rerouteSeq, route) starts clean.
Uses node:test built-in (Node 20+) — no new dependencies.

Establishes the first automated coverage for the nav engine. Subsequent
fixes in the 2026-04-21 nav UX remediation plan add test-first coverage
on top of this harness.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 1 — Engine hygiene (navigation.js)

### Task 1: Bug B9 — applyReroute resets announcedSet and lastAnnouncementTime

**Files:**
- Modify: `frontend/navigation.js:791-818`
- Test: `frontend/tests/engine/navigation.test.mjs`

**Context:** [navigation.js:798-809](../../../frontend/navigation.js#L798-L809) currently tries to preserve announcedSet keys for `idx <= currentManeuverIdx`, but resets `currentManeuverIdx = 0` immediately before, so it only keeps old-route maneuver-0 keys — semantically wrong, see [dev/bug-hunts/2026-04-21-nav-uxb-consolidated.md](../../../dev/bug-hunts/2026-04-21-nav-uxb-consolidated.md) B9. Also `lastAnnouncementTime` is not reset, so the new route's first announcement can be suppressed for up to 5 seconds post-reroute.

- [ ] **Step 1: Write the failing test**

Add to `frontend/tests/engine/navigation.test.mjs`:

```javascript
test('applyReroute clears announcedSet and lastAnnouncementTime', async () => {
  const { nav, window: win } = await loadEngine();
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((t) => voiceFires.push({ text: t, at: Date.now() }));

  nav.start(fixtureTwoManeuverRoute());

  // Drive close enough to trigger the 'near' announcement for maneuver 1
  // (50m threshold, speed 10 m/s passes speed gate).
  nav.updateGPS({ latitude: 35.20, longitude: -111.6405, heading: 90, speed: 10 });
  const firstFireCount = voiceFires.length;
  assert.ok(firstFireCount >= 1, 'expected at least one announcement on approach');

  // Simulate reroute: engine receives a new route via applyReroute.
  // Get the seq that would have been emitted by the engine's own
  // triggerReroute path — we simulate by calling the reroute path directly.
  let capturedSeq = null;
  nav.onReroute((info) => { capturedSeq = info._seq; });
  // Force an off-route trigger by feeding a far-off GPS; engine's hysteresis
  // requires 3 of 5 ticks off-route. Feed 5 in a row.
  for (let i = 0; i < 5; i++) {
    nav.updateGPS({ latitude: 35.25, longitude: -111.55, heading: 90, speed: 10 });
  }
  assert.ok(capturedSeq != null, 'engine should have fired onReroute callback');

  // New route — same shape, just a stand-in.
  const newRoute = fixtureTwoManeuverRoute();
  nav.applyReroute(newRoute, capturedSeq);

  // After applyReroute, announcedSet and lastAnnouncementTime must be fully reset:
  // driving the same approach as before must fire the announcement again.
  const beforeNewFires = voiceFires.length;
  nav.updateGPS({ latitude: 35.20, longitude: -111.6405, heading: 90, speed: 10 });
  assert.ok(
    voiceFires.length > beforeNewFires,
    'announcement should re-fire on new route; was suppressed — announcedSet/lastAnnouncementTime not cleared'
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test frontend/tests/engine/navigation.test.mjs`
Expected: `applyReroute clears announcedSet and lastAnnouncementTime` fails with assertion on `voiceFires.length > beforeNewFires`.

- [ ] **Step 3: Fix applyReroute**

In [frontend/navigation.js:791-818](../../../frontend/navigation.js#L791-L818), replace the announced-set filter block. Change:

```javascript
    applyReroute: function (routeData, seq) {
      // Ignore stale reroute responses
      if (seq !== rerouteSeq) return;
      if (rerouteTimeoutId) { clearTimeout(rerouteTimeoutId); rerouteTimeoutId = null; }

      route = routeData;
      lastIndex = 0;
      currentManeuverIdx = 0;
      offRouteHistory = [];
      inOffRouteState = false;
      // Clear only forward maneuvers' thresholds
      var newSet = {};
      for (var key in announcedSet) {
        var idx = parseInt(key.split('-')[0]);
        if (idx <= currentManeuverIdx) {
          newSet[key] = true;
        }
      }
      announcedSet = newSet;
      speedHistory = [];
      precomputeDistances();

      state = "navigating";

      if (lastGPS) {
        tick(lastGPS);
      }
    },
```

to:

```javascript
    applyReroute: function (routeData, seq) {
      // Ignore stale reroute responses
      if (seq !== rerouteSeq) return;
      if (rerouteTimeoutId) { clearTimeout(rerouteTimeoutId); rerouteTimeoutId = null; }

      route = routeData;
      lastIndex = 0;
      currentManeuverIdx = 0;
      offRouteHistory = [];
      inOffRouteState = false;
      // Full reset: old keys refer to a route that no longer exists.
      // Voice cooldown also resets so the new route's first announcement
      // isn't suppressed by the 5 s cooldown from the pre-reroute one.
      announcedSet = {};
      lastAnnouncementTime = 0;
      speedHistory = [];
      precomputeDistances();

      state = "navigating";

      if (lastGPS) {
        tick(lastGPS);
      }
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test frontend/tests/engine/navigation.test.mjs`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/navigation.js frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
fix(nav): reset announcedSet and lastAnnouncementTime on applyReroute (B9)

Pre-fix, applyReroute preserved announcedSet keys for idx <=
currentManeuverIdx after resetting currentManeuverIdx to 0 — keeping
only old-route maneuver-0 keys, which have no meaning against the new
route. lastAnnouncementTime was not reset, so the new route's first
announcement could be suppressed for up to 5 s by the 5 s voice cooldown.

Now: both announcedSet and lastAnnouncementTime are fully cleared.
Engine test drives a live-reroute scenario and asserts the same
approach fires an announcement on both the original and the new route.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Bug B10 — reroute timeout clears lastRerouteTime and rerouteTimeoutId

**Files:**
- Modify: `frontend/navigation.js:640-646`
- Test: `frontend/tests/engine/navigation.test.mjs`

**Context:** When the engine's 10 s REROUTE_TIMEOUT fires (the UI failed to produce a new route in time), the engine returns to `navigating` but leaves `lastRerouteTime` intact. The 15 s REROUTE_COOLDOWN stays active, so users remain unable to trigger a new reroute until 15 s after the FIRST trigger (not after the timeout) — effectively 20-25 s off-route instead of 15 s.

- [ ] **Step 1: Write the failing test**

Add to `frontend/tests/engine/navigation.test.mjs`:

```javascript
test('reroute timeout clears lastRerouteTime and rerouteTimeoutId', async () => {
  const { nav, window: win } = await loadEngine();
  // Use fake timers: override setTimeout/clearTimeout in the sandbox? Too
  // heavy — instead monkey-patch Date.now and directly inspect state via
  // getState after simulating timeout progression.
  //
  // Approach: freeze time so REROUTE_COOLDOWN window is deterministic,
  // trigger a reroute, drive the engine timeout by bumping time, and then
  // attempt a second reroute and assert it was NOT cooldown-blocked.

  const realNow = Date.now;
  let fakeNow = 1_000_000_000_000; // arbitrary starting epoch
  win.Date = class extends Date { static now() { return fakeNow; } };
  // Ensure the engine sees our patched Date.now by reloading:
  // (simpler path: use the already-loaded engine; Date.now in the engine
  // closure resolves at call time, so globalThis.Date.now is what matters)
  // In our vm sandbox, Date is a shared reference — we can override .now:
  const origNow = Date.now;
  Date.now = () => fakeNow;

  try {
    win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };

    const rerouteCalls = [];
    nav.onReroute((info) => rerouteCalls.push(info));

    nav.start(fixtureTwoManeuverRoute());

    // Trigger reroute #1 (3-of-5 ticks off-route).
    for (let i = 0; i < 5; i++) {
      nav.updateGPS({ latitude: 35.25, longitude: -111.55, heading: 90, speed: 10 });
    }
    assert.equal(rerouteCalls.length, 1, 'first reroute should fire');

    // Simulate engine timeout firing: advance fakeNow past REROUTE_TIMEOUT
    // (10 s). The engine's internal setTimeout callback needs to execute;
    // since we don't have fake timers, we synchronously trigger by
    // advancing time AND calling updateGPS (which re-enters tick and
    // sees state === 'rerouting' — it returns early without resetting,
    // so we'd be stuck). Instead, the simplest path is: wait for the real
    // setTimeout. This is a short test (10 s) OR we keep the test bounded
    // by using a smaller timeout... Actually let's take option three:
    // inspect behavior indirectly by advancing fakeNow past the 15 s
    // cooldown + 10 s timeout window (total 25 s), then attempt another
    // reroute-trigger and assert the cooldown passed.
    //
    // The critical assertion: post-timeout, REROUTE_COOLDOWN is based on
    // `lastRerouteTime`. If the fix is applied (lastRerouteTime = 0 on
    // timeout), a second reroute fires at fakeNow + 10s + epsilon (just
    // after the timeout). If the fix is NOT applied, the second reroute
    // is blocked until fakeNow + 15s (the original 15s cooldown from the
    // first trigger).
    //
    // Use real setTimeout, but bound the test to 11 s.
    await new Promise((r) => setTimeout(r, 10_500));
    fakeNow += 10_500;

    // Now attempt a second reroute at fakeNow=10.5 s post first trigger.
    // If lastRerouteTime was NOT cleared, the 15 s cooldown blocks this
    // and rerouteCalls.length stays at 1.
    for (let i = 0; i < 5; i++) {
      nav.updateGPS({ latitude: 35.30, longitude: -111.50, heading: 90, speed: 10 });
    }
    assert.equal(
      rerouteCalls.length,
      2,
      'second reroute should fire after engine timeout (lastRerouteTime not cleared)'
    );
  } finally {
    Date.now = origNow;
  }
});
```

(This test takes ~11 s; acceptable for a local regression test. Mark with `{ timeout: 15_000 }` in test options.)

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test --test-timeout=15000 frontend/tests/engine/navigation.test.mjs`
Expected: the `reroute timeout clears lastRerouteTime` test fails with `rerouteCalls.length === 1`.

- [ ] **Step 3: Fix the engine**

In [frontend/navigation.js:640-646](../../../frontend/navigation.js#L640-L646), replace:

```javascript
    rerouteTimeoutId = setTimeout(function () {
      if (state === "rerouting") {
        state = "navigating";
        offRouteHistory = [];
        inOffRouteState = false;
      }
    }, REROUTE_TIMEOUT);
```

with:

```javascript
    rerouteTimeoutId = setTimeout(function () {
      rerouteTimeoutId = null;
      if (state === "rerouting") {
        state = "navigating";
        offRouteHistory = [];
        inOffRouteState = false;
        // Clear the cooldown too — the failure already burned 10 s;
        // don't penalize the user with another 5 s of blocked reroutes.
        lastRerouteTime = 0;
      }
    }, REROUTE_TIMEOUT);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test --test-timeout=15000 frontend/tests/engine/navigation.test.mjs`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/navigation.js frontend/tests/engine/navigation.test.mjs
git commit -m "$(cat <<'EOF'
fix(nav): clear lastRerouteTime when engine reroute timeout fires (B10)

Pre-fix, the engine's 10 s REROUTE_TIMEOUT fallback returned state to
'navigating' but left lastRerouteTime intact — so the 15 s REROUTE_COOLDOWN
continued to block a second reroute attempt for another 5 s. Effective
off-route dwell: 20-25 s instead of 15 s.

Now: lastRerouteTime is reset when the timeout fires, AND
rerouteTimeoutId is nulled post-fire so stop/reset paths don't re-clear
a handle that already executed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Bug B14 — propagate UI mute state to engine on nav start

**Files:**
- Modify: `frontend/nav-ui.js:141-193` (`startNavigation`)
- Test: `dev/harness/drive-nav.mjs` (create in Task 12 — see dependency note)

**Context:** UI loads `muted` from localStorage at [nav-ui.js:78](../../../frontend/nav-ui.js#L78). `startNavigation` registers engine callbacks and calls `nav.start(routeData)` but never calls `nav.setMuted(muted)`. The engine's internal `muted` defaults to `false`. Even though the UI's `onVoice` handler silences `speechSynthesis.speak` when UI-side muted, the engine still populates `announcedSet`. If the user unmutes mid-route, already-crossed thresholds stay in the set — user misses what should have been audible prompts.

This task has no dedicated new test because the engine-side behavior is already covered by the B9 test (resetting announcedSet), and the UI-side propagation is a single line. It will be caught by the drive-nav.mjs smoke assertion in Task 14.

**Note on ordering:** This task is part of Phase 1's review loop but its Playwright assertion is added in Task 14. Ship the code change with a code-review check (manual eyes on the diff); the integration test lands later.

- [ ] **Step 1: Modify startNavigation**

In [frontend/nav-ui.js:158](../../../frontend/nav-ui.js#L158), find the block:

```javascript
    // Register engine callbacks and start navigation
    nav = window.GeographicaNav;
    nav.onUpdate(onNavUpdate);
    nav.onVoice(onVoice);
    nav.onArrival(onArrival);
    nav.onReroute(onReroute);
    nav.start(routeData);
```

and add mute sync immediately after `nav.start(routeData);`:

```javascript
    // Register engine callbacks and start navigation
    nav = window.GeographicaNav;
    nav.onUpdate(onNavUpdate);
    nav.onVoice(onVoice);
    nav.onArrival(onArrival);
    nav.onReroute(onReroute);
    nav.start(routeData);
    nav.setMuted(muted);  // B14: sync UI mute preference into engine
```

- [ ] **Step 2: Run existing engine tests (no regression)**

Run: `node --test frontend/tests/engine/`
Expected: all tests still pass (this is a nav-ui.js change; engine tests should be unaffected).

- [ ] **Step 3: Commit**

```bash
git add frontend/nav-ui.js
git commit -m "$(cat <<'EOF'
fix(nav): propagate UI mute state to engine on nav start (B14)

Pre-fix, startNavigation registered engine callbacks and started the
engine but never called nav.setMuted(muted). The UI's onVoice silenced
speechSynthesis when muted, but the engine's announcedSet still
populated — users who unmuted mid-route would miss already-crossed
thresholds.

Now: nav.setMuted(muted) is called immediately after nav.start(), so
the engine knows the user's preference from the first tick and defers
marking announcedSet when muted.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

**REVIEW LOOP 1** (after Phase 1, Tasks 1-3):

Review the three engine-side fixes against each other and against the pitfalls doc. Points to verify:

1. **Cross-check:** Did Task 1 (announcedSet reset) interact with Task 3 (mute propagation)? If user mutes before reroute: applyReroute clears announcedSet, but engine-side `muted` is still `true` from the pre-reroute `setMuted(true)` call — so the new route's announcements silently populate announcedSet without firing. Is that what we want? (Yes — that matches the UI behavior.)
2. **Pitfall: state consumed on check (testing-pitfalls.md entry).** The engine's `announce()` at [navigation.js:327-335](../../../frontend/navigation.js#L327-L335) marks `announcedSet[key] = true` even when `muted`. Regression? Verify by tracing: `checkVoice` → `announce(text, key)` → if `muted` return false, don't mark. Check this wasn't accidentally broken by B9.
3. **Pitfall: unrecoverable state on async failure.** Task 2 partially addresses this for the engine side. Did we introduce any new "stuck rerouting" path? (No — the fix only clears cooldown after the timeout fires; state transitions are unchanged.)
4. **Test brittleness:** the B10 test uses `await new Promise(setTimeout, 10500)` — 10+ seconds is slow. Acceptable for the v1 test harness; file a follow-up to introduce fake timers later.
5. **Cooldown semantics post-timeout:** after `lastRerouteTime = 0`, a fresh reroute can fire within the `OFF_ROUTE_*` hysteresis window (5 ticks × ~1 s). Is that desirable or does it thrash? Argument for: user has been off-route for 10 s already; needs help. Argument against: GPS noise could immediately re-trigger. Given the 3-of-5 hysteresis gate, thrashing is unlikely. Keep as-is.

Do at least 3 review rounds. Update your private journal with patterns noticed (e.g., "module-level mutable state made the vm.Context reload pattern essential for testability").

---

## Phase 2 — Reroute payload preservation (nav-ui.js)

### Task 4: Bug B5 — preserve intermediate waypoints on reroute

**Files:**
- Modify: `frontend/nav-ui.js:237-277` (`buildRouteData`)
- Modify: `frontend/nav-ui.js:470-498` (`onReroute`)
- Test: `dev/harness/drive-nav.mjs` (create in Task 14; this task ships a unit-level assertion in a new engine test)

**Context:** `buildRouteData` hardcodes `remainingWaypoints: []`. `triggerReroute` in the engine pulls from `route.remainingWaypoints` — always empty. Multi-stop trips get rerouted directly to the final destination, silently skipping intermediates.

Source of truth for intermediate waypoints: `trip.locations` array returned by Valhalla. The first entry is start, last is end, intermediate entries are `type: 'through'` waypoints.

- [ ] **Step 1: Write failing test via the engine harness**

Add to `frontend/tests/engine/navigation.test.mjs`:

```javascript
test('triggerReroute preserves remainingWaypoints in the callback info', async () => {
  const { nav, window: win } = await loadEngine();
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };

  // Route with two intermediate waypoints.
  const multiStopRoute = {
    ...fixtureTwoManeuverRoute(),
    remainingWaypoints: [
      { lat: 35.21, lon: -111.64, type: 'through' },
      { lat: 35.22, lon: -111.63, type: 'through' },
    ],
  };

  const rerouteCalls = [];
  nav.onReroute((info) => rerouteCalls.push(info));

  nav.start(multiStopRoute);

  for (let i = 0; i < 5; i++) {
    nav.updateGPS({ latitude: 35.25, longitude: -111.55, heading: 90, speed: 10 });
  }

  assert.equal(rerouteCalls.length, 1);
  assert.deepEqual(
    rerouteCalls[0].remainingWaypoints,
    [
      { lat: 35.21, lon: -111.64, type: 'through' },
      { lat: 35.22, lon: -111.63, type: 'through' },
    ],
    'remainingWaypoints must be passed through to the onReroute callback'
  );
});
```

- [ ] **Step 2: Run — this should PASS already for the engine side**

Run: `node --test frontend/tests/engine/`
Expected: the new test passes — the engine *does* pass `route.remainingWaypoints` into the callback info. The bug is in nav-ui.js's `buildRouteData`, which never populates it.

- [ ] **Step 3: Write a second failing test — this one targets buildRouteData**

Because `buildRouteData` lives inside the nav-ui.js IIFE and is not exported, we test it by exposing it on `window` in a test-only hook. Add to [nav-ui.js:1](../../../frontend/nav-ui.js) — after the IIFE's `'use strict'`:

```javascript
(function () {
  'use strict';
```

becomes:

```javascript
(function () {
  'use strict';

  // Test hook: expose internal helpers under a namespace for unit tests.
  // Populated at the bottom of the IIFE after the functions are defined.
  // No-op in production (only read by tests).
```

…and IMMEDIATELY BEFORE the `// BOOTSTRAP` section near [nav-ui.js:943-951](../../../frontend/nav-ui.js#L943-L951), BEFORE the `if (document.readyState === 'loading') ...` block, add:

```javascript
  // Test hook: expose internal helpers for unit tests. Must sit before
  // BOOTSTRAP so the assignment happens even if init() throws in a
  // degenerate (e.g. Node vm) environment.
  window._geographicaNavUIInternals = {
    buildRouteData: buildRouteData,
  };

  // =====================================================================
  //  BOOTSTRAP
  // =====================================================================

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
```

(The `BOOTSTRAP` section and its `if`/`else` block already exist; you're inserting the new 5 lines just above them. Do not duplicate the bootstrap section.)

Now write the nav-ui test. Create `frontend/tests/nav-ui/buildRouteData.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createContext, runInContext } from 'node:vm';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));

function loadNavUIInternals() {
  // nav-ui.js runs init() at IIFE end (`if (document.readyState === 'loading') ...
  // else init()`). We stub enough DOM and browser globals so init() doesn't
  // throw. Even if it did, window._geographicaNavUIInternals is assigned
  // BEFORE the bootstrap section (see Task 4 Step 4) so the internals are
  // captured regardless.
  const code = readFileSync(join(__dirname, '..', '..', 'nav-ui.js'), 'utf8');
  const stubEl = () => ({
    addEventListener: () => {},
    removeEventListener: () => {},
    classList: { contains: () => true, remove: () => {}, add: () => {}, toggle: () => {} },
    appendChild: () => {},
    removeChild: () => {},
    querySelector: () => null,
    closest: () => null,
    style: {},
    firstChild: null,
    offsetHeight: 100,
    dispatchEvent: () => {},
    setAttribute: () => {},
  });
  const doc = {
    readyState: 'complete', // avoid the DOMContentLoaded path
    getElementById: () => stubEl(),
    querySelector: () => null,
    querySelectorAll: () => [],
    documentElement: { style: { setProperty: () => {} } },
    createElement: () => stubEl(),
    createElementNS: () => stubEl(),
    addEventListener: () => {},
  };
  const win = {
    _geographicaMap: {
      on: () => {}, off: () => {}, easeTo: () => {}, getBearing: () => 0,
      getContainer: () => ({ clientHeight: 900 }),
      getSource: () => ({ setData: () => {} }),
      fitBounds: () => {},
    },
    _geographicaUseImperial: true,
    _geographicaGPSData: null,
    innerWidth: 1280,
    innerHeight: 900,
    localStorage: { getItem: () => null, setItem: () => {} },
    speechSynthesis: null,
    SpeechSynthesisUtterance: null,
    GeographicaNav: { // dummy — not used by buildRouteData
      onUpdate: () => {}, onVoice: () => {}, onArrival: () => {}, onReroute: () => {},
      start: () => {}, setMuted: () => {},
    },
  };
  // MutationObserver stub — observeRouteAvailability uses it.
  class StubMutationObserver {
    constructor(cb) { this.cb = cb; }
    observe() {}
    disconnect() {}
  }
  const sandbox = {
    window: win, document: doc,
    MutationObserver: StubMutationObserver,
    setTimeout, clearTimeout, setInterval, clearInterval,
    Date, Math, Object, Array, Number, String, parseInt, parseFloat, console,
  };
  const ctx = createContext(sandbox);
  try {
    runInContext(code, ctx, { filename: 'nav-ui.js' });
  } catch (err) {
    // init() may throw on degenerate stubs; internals should already be set.
    if (!win._geographicaNavUIInternals) throw err;
  }
  return win._geographicaNavUIInternals;
}

test('buildRouteData extracts remainingWaypoints from trip.locations', () => {
  const internals = loadNavUIInternals();
  const trip = {
    legs: [
      {
        shape: 'gxz_}Anbf}E',  // decodable stub — any polyline
        maneuvers: [{
          type: 1, instruction: 'Head east', begin_shape_index: 0, end_shape_index: 0,
        }],
      },
    ],
    summary: { length: 10, time: 600 },
    locations: [
      { lat: 35.20, lon: -111.65, type: 'break' },
      { lat: 35.21, lon: -111.64, type: 'through' },
      { lat: 35.22, lon: -111.63, type: 'through' },
      { lat: 35.23, lon: -111.62, type: 'break' },
    ],
    _costing: 'auto',
  };

  const result = internals.buildRouteData(trip);
  assert.deepEqual(
    result.remainingWaypoints,
    [
      { lat: 35.21, lon: -111.64, type: 'through' },
      { lat: 35.22, lon: -111.63, type: 'through' },
    ],
    'intermediate locations must be populated as remainingWaypoints'
  );
});

test('buildRouteData returns empty remainingWaypoints for 2-location trip', () => {
  const internals = loadNavUIInternals();
  const trip = {
    legs: [{ shape: 'gxz_}Anbf}E', maneuvers: [{ type: 1, instruction: 'go', begin_shape_index: 0, end_shape_index: 0 }] }],
    summary: { length: 1, time: 60 },
    locations: [
      { lat: 35.20, lon: -111.65, type: 'break' },
      { lat: 35.21, lon: -111.64, type: 'break' },
    ],
    _costing: 'auto',
  };
  const result = internals.buildRouteData(trip);
  assert.deepEqual(result.remainingWaypoints, []);
});

test('buildRouteData handles missing trip.locations gracefully', () => {
  const internals = loadNavUIInternals();
  const trip = {
    legs: [{ shape: 'gxz_}Anbf}E', maneuvers: [{ type: 1, instruction: 'go', begin_shape_index: 0, end_shape_index: 0 }] }],
    summary: { length: 1, time: 60 },
    _costing: 'auto',
  };
  const result = internals.buildRouteData(trip);
  assert.deepEqual(result.remainingWaypoints, []);
});
```

- [ ] **Step 4: Run — verify the first test fails, the empty-list tests pass**

Run: `node --test frontend/tests/`
Expected: `buildRouteData extracts remainingWaypoints` fails (gets `[]`); other two pass.

- [ ] **Step 5: Fix buildRouteData**

In [frontend/nav-ui.js:237-277](../../../frontend/nav-ui.js#L237-L277), replace the final return block:

```javascript
    return {
      coords: allCoords,
      maneuvers: allManeuvers,
      summary: summary,
      totalDistance: distMeters,
      totalTime: summary.time || 0,
      costing: trip._costing || 'auto',
      remainingWaypoints: []
    };
```

with:

```javascript
    // Extract intermediate waypoints from trip.locations.
    // Valhalla returns: [start, ...throughs, end].
    // Reroute will re-plan from current GPS → throughs → end.
    var locs = trip.locations || [];
    var intermediates = locs.length > 2 ? locs.slice(1, -1) : [];
    var remainingWaypoints = intermediates.map(function (loc) {
      return {
        lat: loc.lat,
        lon: loc.lon,
        type: loc.type || 'through',
      };
    });

    return {
      coords: allCoords,
      maneuvers: allManeuvers,
      summary: summary,
      totalDistance: distMeters,
      totalTime: summary.time || 0,
      costing: trip._costing || 'auto',
      remainingWaypoints: remainingWaypoints,
    };
```

- [ ] **Step 6: Run all tests — verify green**

Run: `node --test frontend/tests/`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/nav-ui.js frontend/tests/
git commit -m "$(cat <<'EOF'
fix(nav): preserve intermediate waypoints across reroutes (B5)

Pre-fix, buildRouteData hardcoded remainingWaypoints=[]. Multi-stop
trips (A → B → C → D) that deviated got rerouted directly to D,
silently dropping B and C. Valhalla returns the full locations array
in trip.locations — first is start, last is end, middle entries are
throughs.

Now: buildRouteData extracts intermediates from trip.locations and
attaches them as remainingWaypoints. Engine already passes these
through to onReroute; UI already includes them in the reroute body.
Entire flow is now correct end-to-end.

Also adds a test hook (window._geographicaNavUIInternals) for unit
testing IIFE-private functions. No production behavior change.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Bug B6 — preserve costing_options on reroute

**Files:**
- Modify: `frontend/app.js:2059-2075` (extend trip storage), `frontend/nav-ui.js:264-277` (buildRouteData), `frontend/nav-ui.js:488-492` (onReroute body)
- Test: `frontend/tests/nav-ui/buildRouteData.test.mjs`

**Context:** User's original route request at [app.js:2059-2075](../../../frontend/app.js#L2059-L2075) includes `costing`, but any `costing_options` (e.g., `avoid_highways`, bicycle `bicycle_type`) are currently not stored anywhere after the request. Even if the UI surfaces those later, they're lost at reroute time. The fix preserves `costing_options` on `_geographicaLastTrip` and threads it through `buildRouteData → route.costingOptions → onReroute callback → Valhalla request body`.

First: check the current state of costing_options in the UI. Inspect [app.js:2059-2075](../../../frontend/app.js#L2059-L2075) and the route panel HTML. If costing_options are NOT yet surfaced in the UI, this fix is purely preparatory (no user-visible change until the routing panel adds options), but unblocks future UI work. Still worth the fix for design-smell elimination.

- [ ] **Step 1: Check current route-request state**

Run: `grep -n 'costing_options' frontend/app.js frontend/nav-ui.js`

Record what you find in the commit message. If `costing_options` is not passed at all today, Task 5 is a defensive forward-fix: add pass-through plumbing so the feature works when UI adds it. Still ship it.

- [ ] **Step 2: Write failing test for buildRouteData**

Add to `frontend/tests/nav-ui/buildRouteData.test.mjs`:

```javascript
test('buildRouteData propagates costing_options to route payload', () => {
  const internals = loadNavUIInternals();
  const trip = {
    legs: [{ shape: 'gxz_}Anbf}E', maneuvers: [{ type: 1, instruction: 'go', begin_shape_index: 0, end_shape_index: 0 }] }],
    summary: { length: 1, time: 60 },
    locations: [
      { lat: 35.20, lon: -111.65, type: 'break' },
      { lat: 35.21, lon: -111.64, type: 'break' },
    ],
    _costing: 'bicycle',
    _costingOptions: { bicycle: { bicycle_type: 'road' } },
  };
  const result = internals.buildRouteData(trip);
  assert.deepEqual(
    result.costingOptions,
    { bicycle: { bicycle_type: 'road' } },
    'costingOptions must be preserved on the engine route payload'
  );
});

test('buildRouteData defaults costingOptions to null when absent', () => {
  const internals = loadNavUIInternals();
  const trip = {
    legs: [{ shape: 'gxz_}Anbf}E', maneuvers: [{ type: 1, instruction: 'go', begin_shape_index: 0, end_shape_index: 0 }] }],
    summary: { length: 1, time: 60 },
    locations: [{ lat: 35.20, lon: -111.65 }, { lat: 35.21, lon: -111.64 }],
    _costing: 'auto',
  };
  const result = internals.buildRouteData(trip);
  assert.equal(result.costingOptions, null);
});
```

- [ ] **Step 3: Run — verify both fail**

Run: `node --test frontend/tests/`
Expected: both new tests fail (`result.costingOptions` undefined).

- [ ] **Step 4: Fix buildRouteData**

In [frontend/nav-ui.js:264-277](../../../frontend/nav-ui.js#L264-L277) (after your B5 edit), extend the return:

```javascript
    return {
      coords: allCoords,
      maneuvers: allManeuvers,
      summary: summary,
      totalDistance: distMeters,
      totalTime: summary.time || 0,
      costing: trip._costing || 'auto',
      costingOptions: trip._costingOptions || null,
      remainingWaypoints: remainingWaypoints,
    };
```

- [ ] **Step 5: Fix the reroute body to include costing_options**

In [frontend/nav-ui.js:485-498](../../../frontend/nav-ui.js#L485-L498), extend the `body` object:

```javascript
    var body = {
      locations: locations,
      costing: info.costing || 'auto',
      directions_options: { units: window._geographicaUseImperial ? 'miles' : 'kilometers' }
    };
    if (info.costingOptions) {
      body.costing_options = info.costingOptions;
    }
```

- [ ] **Step 6: Thread costingOptions through the engine's onReroute callback**

In [frontend/navigation.js:648-656](../../../frontend/navigation.js#L648-L656), extend the onReroute payload:

```javascript
    if (onRerouteCb) {
      onRerouteCb({
        currentLat: lat,
        currentLng: lng,
        remainingWaypoints: route.remainingWaypoints || [],
        costing: route.costing,
        costingOptions: route.costingOptions || null,
        _seq: rerouteSeq
      });
    }
```

- [ ] **Step 7: Store `_costingOptions` on the original trip**

In [frontend/app.js:2059-2075](../../../frontend/app.js#L2059-L2075), inspect the route-request handler. After `lastRouteTrip = data.trip;`, add:

```javascript
          lastRouteTrip = data.trip;
          window._geographicaLastTrip = data.trip;
          window._geographicaLastTrip._costing = costing;
          window._geographicaLastTrip._costingOptions = body.costing_options || null;
```

(Assumes `body` is the outgoing request body containing `costing_options`. Verify this variable name against the actual code; rename if needed. If `costing_options` is not currently in the request body at all, set `_costingOptions = null` — the plumbing is ready for when the UI adds the feature.)

- [ ] **Step 8: Run all tests**

Run: `node --test frontend/tests/`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add frontend/nav-ui.js frontend/navigation.js frontend/app.js frontend/tests/
git commit -m "$(cat <<'EOF'
fix(nav): preserve costing_options across reroutes (B6)

Pre-fix, costing_options from the user's original route request were
never stored on the trip object post-fetch, never threaded through the
engine, and never included in reroute Valhalla requests. If the UI
surfaced an "avoid highways" toggle, a reroute would silently put the
user back on the highway.

Plumbing added:
- app.js stores body.costing_options on _geographicaLastTrip
- nav-ui.js buildRouteData threads it into the engine route payload
- navigation.js onReroute callback passes it back to the UI
- nav-ui.js reroute body includes costing_options if present

No user-visible change today (UI doesn't surface costing_options yet);
forward-fix that unblocks future routing-preference work.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Bug B13 — clamp `begin_shape_index` to zero in multi-leg stitching

**Files:**
- Modify: `frontend/nav-ui.js:244-262` (`buildRouteData` leg loop)
- Test: `frontend/tests/nav-ui/buildRouteData.test.mjs`

**Context:** In [nav-ui.js:255](../../../frontend/nav-ui.js#L255), the line `(mc.begin_shape_index || 0) - indexAdjust + shapeOffset` subtracts 1 for non-first legs. A maneuver with `begin_shape_index = 0` (every leg's first "start" maneuver) becomes `-1 + shapeOffset = shapeOffset - 1` — indexing into the previous leg's final segment. Voice/icon for the first maneuver of legs 2+ fires one segment early.

- [ ] **Step 1: Write failing test**

Add to `frontend/tests/nav-ui/buildRouteData.test.mjs`:

```javascript
test('buildRouteData clamps begin_shape_index=0 for subsequent legs', () => {
  const internals = loadNavUIInternals();
  // A 2-leg trip where the 2nd leg starts with a begin_shape_index=0 maneuver.
  const trip = {
    legs: [
      {
        shape: 'gxz_}Anbf}E', // any decodable polyline
        maneuvers: [{
          type: 1, instruction: 'Head east',
          begin_shape_index: 0, end_shape_index: 0,
        }],
      },
      {
        shape: 'gxz_}Anbf}E',
        maneuvers: [{
          type: 1, instruction: 'Continue east from waypoint B',
          begin_shape_index: 0, end_shape_index: 0,
        }],
      },
    ],
    summary: { length: 2, time: 120 },
    locations: [
      { lat: 35.20, lon: -111.65 },
      { lat: 35.21, lon: -111.64, type: 'through' },
      { lat: 35.22, lon: -111.63 },
    ],
    _costing: 'auto',
  };

  const result = internals.buildRouteData(trip);

  // Find the maneuver for leg 2. Its begin_shape_index must be >= the
  // shapeOffset of that leg (not shapeOffset - 1).
  const leg2Maneuvers = result.maneuvers.slice(1); // first from leg 1, rest from leg 2
  assert.ok(leg2Maneuvers.length >= 1);
  assert.ok(
    leg2Maneuvers[0].begin_shape_index >= 1,
    `expected begin_shape_index >= 1 for leg 2 start maneuver; got ${leg2Maneuvers[0].begin_shape_index}`
  );
});
```

- [ ] **Step 2: Run — verify fail**

Run: `node --test frontend/tests/`
Expected: the new test fails because `begin_shape_index` resolves to 0 (shapeOffset=1, then -1 clamps back to 0 via the `|| 0` short-circuit on negative numbers… actually let's re-verify: `-1 || 0` is `-1` in JS, not `0`. So `begin_shape_index = -1 + 1 = 0` for leg 2 — one segment too early). Confirm the test catches it.

- [ ] **Step 3: Fix the leg-stitching loop**

In [frontend/nav-ui.js:244-262](../../../frontend/nav-ui.js#L244-L262), change:

```javascript
      if (leg.maneuvers) {
        leg.maneuvers.forEach(function (m) {
          var mc = Object.assign({}, m);
          mc.begin_shape_index = (mc.begin_shape_index || 0) - indexAdjust + shapeOffset;
          mc.end_shape_index = (mc.end_shape_index || 0) - indexAdjust + shapeOffset;
          allManeuvers.push(mc);
        });
      }
```

to:

```javascript
      if (leg.maneuvers) {
        leg.maneuvers.forEach(function (m) {
          var mc = Object.assign({}, m);
          // Clamp at zero before offsetting: a leg-start maneuver has
          // begin_shape_index=0 and we slice off the first coord for
          // legs after the first (indexAdjust=1). Without clamp, the
          // index would land in the previous leg's last segment.
          var beginRaw = Math.max(0, (mc.begin_shape_index || 0) - indexAdjust);
          var endRaw = Math.max(0, (mc.end_shape_index || 0) - indexAdjust);
          mc.begin_shape_index = beginRaw + shapeOffset;
          mc.end_shape_index = endRaw + shapeOffset;
          allManeuvers.push(mc);
        });
      }
```

- [ ] **Step 4: Run — verify green**

Run: `node --test frontend/tests/`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/nav-ui.js frontend/tests/
git commit -m "$(cat <<'EOF'
fix(nav): clamp begin_shape_index=0 in multi-leg route stitching (B13)

Pre-fix, for legs after the first (where we slice off the shared first
coord and set indexAdjust=1), a maneuver with begin_shape_index=0
resolved to shapeOffset-1 — pointing into the previous leg's final
segment. Voice/icon for the first maneuver of every non-first leg
fired one segment early.

Now: Math.max(0, idx - indexAdjust) clamps before adding shapeOffset.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

**REVIEW LOOP 2** (after Phase 2, Tasks 4-6):

1. **Testing pitfall: JS truthiness for numeric zero.** Task 6's fix uses `|| 0` on `begin_shape_index`. If Valhalla ever returns `begin_shape_index: 0` for leg 1 (leg index 0), the code still behaves correctly because `indexAdjust = 0`. But for any future refactor, keep the zero-is-valid pattern in mind.
2. **B5+B6 interaction:** does `costingOptions` need waypoint-specific per-location `side`/`minimum_reachability`? Valhalla supports these per-location. Current fix preserves top-level costing_options only. Filed as follow-up if testers report "avoid pedestrian bridges" etc.
3. **buildRouteData test shape:** we're testing with fixture trips. Real Valhalla responses are much richer. Verify at integration time (Task 14 Playwright). For now, the fixture coverage is sufficient for regression guarding.
4. **Review the three commit messages for factual accuracy.** B6's "No user-visible change today" — verify by grepping for `costing_options` in app.js. If UI already surfaces the option, edit the commit message before pushing.

Minimum 3 review rounds. Update private journal.

---

## Phase 3 — `setActiveRoute` refactor (B2)

**Architecture decision recap:** Cameron chose the refactor path ("No more bandaids approaching 2.0.0"). `setActiveRoute(trip, options)` becomes the single entry point that updates:
- Engine route (via `GeographicaNav.start` OR `GeographicaNav.applyReroute`)
- `window._geographicaLastTrip`
- `lastRouteCoords` (module-local in app.js, used by spatial search)
- MapLibre `'route'` source `.setData(...)`
- Sidebar `<ol id="route-directions">` list

### Task 7: Extract `setActiveRoute` helper in app.js

**Files:**
- Modify: `frontend/app.js` — extract, do not yet convert call sites

**Context:** The existing [app.js:2114-2193](../../../frontend/app.js#L2114-L2193) `renderRoute(trip)` does most of this work but: (a) unconditionally fits bounds, (b) doesn't touch `window._geographicaLastTrip` (the caller does), (c) doesn't touch engine, (d) is not exposed on `window`. We refactor it into `setActiveRoute(trip, options)` in-place.

- [ ] **Step 1: Read the current renderRoute + clearRoute + routing callsite**

Run: `sed -n '2050,2220p' frontend/app.js` (or read via IDE). Record:
- What module-level vars does renderRoute touch? (`lastRouteCoords`)
- Where is `_geographicaLastTrip` currently set? ([app.js:2092-2093](../../../frontend/app.js#L2092-L2093))
- Where is the engine started? (`nav.start` in nav-ui.js startNavigation, NOT here)

- [ ] **Step 2: Define the new function signature**

In [frontend/app.js](../../../frontend/app.js), just above the existing `renderRoute` function (around line 2110), add a new function. Keep `renderRoute` for now to avoid changing call sites in this task.

```javascript
  /**
   * Single source of truth for "the active route has changed."
   * Owns: _geographicaLastTrip, lastRouteCoords, map source 'route',
   * sidebar #route-directions. Optionally fits bounds (default: true).
   *
   * Does NOT drive the engine — that's the caller's responsibility
   * because different call sites want different engine transitions
   * (nav-ui.js startNavigation → nav.start; reroute → nav.applyReroute).
   *
   * @param {Object} trip Valhalla trip object
   * @param {Object} [options]
   * @param {boolean} [options.refitBounds=true] if false, map camera is
   *   untouched (use during active navigation so the user isn't yanked
   *   to an overview view).
   * @param {string} [options.costing] optional costing to stamp on the
   *   trip (for reroute paths where the engine has this but the trip
   *   response doesn't).
   * @param {Object} [options.costingOptions] optional costing_options
   *   to stamp on the trip.
   * @returns {{ coords: Array<[number, number]>, maneuvers: Array }}
   *   Decoded route data for the caller to pass to the engine.
   */
  function setActiveRoute(trip, options) {
    options = options || {};
    var refitBounds = options.refitBounds !== false;

    // Decode polyline from each leg and merge
    var allCoords = [];
    var allManeuvers = [];

    trip.legs.forEach(function (leg) {
      var coords = decodePolyline(leg.shape);
      allCoords = allCoords.concat(coords);
      if (leg.maneuvers) {
        allManeuvers = allManeuvers.concat(leg.maneuvers);
      }
    });

    // Stamp costing / costingOptions on the trip so downstream readers
    // (reroute, export) have them.
    if (options.costing) trip._costing = options.costing;
    if (options.costingOptions !== undefined) trip._costingOptions = options.costingOptions;

    // Update module-level truths
    lastRouteTrip = trip;
    lastRouteCoords = allCoords.slice();
    window._geographicaLastTrip = trip;

    // Update map 'route' source
    var geojson = {
      type: 'Feature',
      geometry: {
        type: 'LineString',
        coordinates: allCoords,
      },
    };
    var source = map.getSource('route');
    if (source) {
      source.setData(geojson);
    }

    // Optionally fit bounds
    if (refitBounds && allCoords.length > 0) {
      var bounds = allCoords.reduce(function (b, coord) {
        return b.extend(coord);
      }, new maplibregl.LngLatBounds(allCoords[0], allCoords[0]));

      var isMobileRoute = window.innerWidth < 768;
      var sidebarWRoute = parseInt(getComputedStyle(document.documentElement)
        .getPropertyValue('--sidebar-width')) || 320;
      map.fitBounds(bounds, {
        padding: isMobileRoute
          ? { top: 40, bottom: 100, left: 20, right: 20 }
          : { top: 60, bottom: 60, left: sidebarWRoute + 20, right: 60 },
      });
    }

    // Rebuild summary + directions sidebar
    var summary = trip.summary || {};
    var dist = summary.length || 0;
    var distStr = useImperial ? dist.toFixed(1) + ' mi' : dist.toFixed(1) + ' km';
    var timeSec = summary.time || 0;
    var hours = Math.floor(timeSec / 3600);
    var minutes = Math.round((timeSec % 3600) / 60);
    var timeStr = hours > 0 ? hours + 'h ' + minutes + 'min' : minutes + ' min';

    var summaryEl = document.getElementById('route-summary');
    while (summaryEl.firstChild) summaryEl.removeChild(summaryEl.firstChild);
    var strong = document.createElement('strong');
    strong.textContent = distStr;
    summaryEl.appendChild(strong);
    summaryEl.appendChild(document.createTextNode(' \u00B7 ' + timeStr));
    summaryEl.classList.remove('hidden');

    var dirList = document.getElementById('route-directions');
    while (dirList.firstChild) dirList.removeChild(dirList.firstChild);
    allManeuvers.forEach(function (m) {
      var li = document.createElement('li');
      var instruction = m.instruction || m.verbal_pre_transition_instruction || '';
      if (m.length) {
        var unit = useImperial ? ' mi' : ' km';
        instruction += ' (' + m.length.toFixed(1) + unit + ')';
      }
      li.textContent = instruction;
      dirList.appendChild(li);
    });

    return { coords: allCoords, maneuvers: allManeuvers };
  }

  // Expose for nav-ui.js reroute path.
  window._geographicaSetActiveRoute = setActiveRoute;
```

- [ ] **Step 3: Run existing tests — verify no regressions (the function isn't called yet)**

Run: `node --test frontend/tests/ && python -m pytest tests/ services/search/tests/ -v -k 'not m2m and not nominatim'`
Expected: all passing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/app.js
git commit -m "$(cat <<'EOF'
refactor(nav): extract setActiveRoute as single source of truth (B2 prep)

Introduces window._geographicaSetActiveRoute(trip, options) that owns
the four-way state update for 'the active route changed':
  - lastRouteTrip / window._geographicaLastTrip
  - lastRouteCoords (used by spatial-search corridor queries)
  - map 'route' source GeoJSON
  - sidebar #route-summary + #route-directions

options.refitBounds defaults to true (preserves existing behavior when
called from initial route fetch); caller passes false during active
navigation to avoid yanking the user's view.

options.costing / options.costingOptions stamp onto the trip for reroute
path to read.

No call sites converted in this commit — behavior is unchanged. The
next two commits convert (1) the initial-route fetch and (2) the
reroute path to use setActiveRoute, closing B2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Convert initial-route fetch to use `setActiveRoute`

**Files:**
- Modify: `frontend/app.js:2086-2100` (the `.then` in the route fetch)
- Remove: `frontend/app.js:2110-2193` (`renderRoute`) — deleted now that setActiveRoute replaces it

**Context:** Before deletion, grep for any other callers of `renderRoute`. It should be called only from the route fetch `.then`.

- [ ] **Step 1: Verify renderRoute has only one caller**

Run: `grep -n 'renderRoute' frontend/*.js frontend/*.html`
Expected: exactly one call site in [app.js:2094](../../../frontend/app.js#L2094), plus its own definition at ~2114.

If more call sites appear, STOP and investigate — the cleanup plan assumed only one.

- [ ] **Step 2: Convert the call site**

**Note:** Task 5 Step 7 added `window._geographicaLastTrip._costingOptions = body.costing_options || null;` just after `_costing`. If Task 5 landed first (it did, by plan order), the current `if (data.trip)` block reads as:

```javascript
        if (data.trip) {
          lastRouteTrip = data.trip;
          window._geographicaLastTrip = data.trip;
          window._geographicaLastTrip._costing = costing;
          window._geographicaLastTrip._costingOptions = body.costing_options || null;
          renderRoute(data.trip);
          document.getElementById('export-route-btn').classList.remove('hidden');
        } else if (data.error) {
          alert('Routing error: ' + (data.error || 'Unknown error'));
        } else {
          alert('No route found.');
        }
```

(If Task 5 has NOT landed — e.g. you're running tasks out of order — the `_costingOptions` line won't be there. Adjust the match accordingly or complete Task 5 first.)

Replace the entire block above with:

```javascript
        if (data.trip) {
          setActiveRoute(data.trip, {
            refitBounds: true,
            costing: costing,
            costingOptions: body.costing_options || null,
          });
          document.getElementById('export-route-btn').classList.remove('hidden');
        } else if (data.error) {
          alert('Routing error: ' + (data.error || 'Unknown error'));
        } else {
          alert('No route found.');
        }
```

`setActiveRoute` handles `lastRouteTrip`, `window._geographicaLastTrip`, and the trip stamps internally; the three explicit assignments from the prior block are no longer needed at the call site.

- [ ] **Step 3: Delete the now-dead renderRoute function**

Remove [app.js:2110-2193](../../../frontend/app.js#L2110-L2193) entirely — `function renderRoute(trip) { ... }` and its closing brace.

Verify no other site references it:

Run: `grep -n 'renderRoute' frontend/*.js frontend/*.html`
Expected: no matches.

- [ ] **Step 4: Smoke-test in browser manually**

Start the frontend locally (if not already running), load `http://localhost:8088/` (or the configured dev URL), plan a 2-point route, verify:
- Blue line appears on map ✓
- Sidebar directions populate ✓
- Summary shows distance + time ✓
- `fitBounds` camera animates to route ✓

Record the result in your journal. If any of these break, you've introduced a regression — revert and re-examine `setActiveRoute` logic vs. original `renderRoute`.

- [ ] **Step 5: Run existing tests**

Run: `node --test frontend/tests/`
Expected: all pass. (These tests don't cover app.js, but ensure the nav-ui and engine tests aren't accidentally broken.)

- [ ] **Step 6: Commit**

```bash
git add frontend/app.js
git commit -m "$(cat <<'EOF'
refactor(nav): convert initial route fetch to setActiveRoute (B2 prep)

Replaces the renderRoute(trip) call + ad-hoc window._geographicaLastTrip
assignment with a single setActiveRoute(trip, { refitBounds: true,
costing, costingOptions }) call. Deletes the now-dead renderRoute
function (~80 LOC).

Prepares for the reroute-path conversion in the next commit which
closes B2 (map polyline stale after reroute).

Behavior unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Convert reroute path to use `setActiveRoute` (closes B2)

**Files:**
- Modify: `frontend/nav-ui.js:498-532` (`attemptReroute`)

**Context:** The `.then` handler currently calls `nav.applyReroute(newRouteData, seq)` only. Engine-side state updates; map source, sidebar, `_geographicaLastTrip`, and `lastRouteCoords` all stay stale. With `window._geographicaSetActiveRoute` now exposed by Task 7, we call it here before `nav.applyReroute`.

- [ ] **Step 1: Write integration test (Playwright harness)**

Create `dev/harness/drive-nav.mjs` — minimal harness to drive nav-ui.js with a mocked GPS and Valhalla proxy. This doubles as the harness for Tasks 10-13 as well.

```javascript
// Playwright-driven nav integration test.
//
// Mocks /valhalla/route + window._geographicaGPSData, then asserts:
//   1. Initial route renders blue line + sidebar directions.
//   2. Off-route GPS triggers reroute.
//   3. After reroute resolves, map source 'route' setData was called
//      with new coords (polyline updated — the B2 assertion).
//
// Usage: node drive-nav.mjs [--url=http://localhost:8088]

import { chromium } from 'playwright';

const argv = process.argv.slice(2);
const urlArg = argv.find((a) => a.startsWith('--url='));
const baseUrl = urlArg ? urlArg.slice(6) : 'http://localhost:8088';

const ORIGINAL_ROUTE_SHAPE = 'gxz_}Anbf}E_|@_|@';  // stub polyline
const REROUTE_SHAPE = 'abc123reroute_shape_different_from_original';

async function mockValhalla(page) {
  await page.route('**/valhalla/route', async (route, req) => {
    const body = JSON.parse(req.postData() || '{}');
    const isReroute = body.locations && body.locations.length > 0 &&
                       Math.abs(body.locations[0].lat - 35.25) < 0.1;
    const shape = isReroute ? REROUTE_SHAPE : ORIGINAL_ROUTE_SHAPE;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        trip: {
          legs: [{
            shape: shape,
            maneuvers: [
              { type: 1, instruction: 'Head east', begin_shape_index: 0, end_shape_index: 1,
                verbal_transition_alert_instruction: 'In half a mile, turn left',
                verbal_pre_transition_instruction: 'Turn left on Oak Street' },
              { type: 15, instruction: 'Arrived', begin_shape_index: 2, end_shape_index: 2 },
            ],
          }],
          summary: { length: 1.0, time: 60 },
          locations: [
            { lat: 35.20, lon: -111.65, type: 'break' },
            { lat: 35.21, lon: -111.64, type: 'break' },
          ],
        },
      }),
    });
  });
}

async function mainAsserts() {
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();

  await mockValhalla(page);
  await page.goto(baseUrl);

  // Wait for map to be ready.
  await page.waitForFunction(() => !!window._geographicaMap, null, { timeout: 10_000 });

  // Inject GPS data.
  await page.evaluate(() => {
    window._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };
  });

  // Request a route via the exposed API.
  // (Assumes the route-request DOM entry points are present; we call the
  //  setActiveRoute path directly for deterministic testing.)
  await page.evaluate(() => {
    // Simulate: the initial route fetch happened and setActiveRoute was called.
    return fetch('/valhalla/route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ locations: [{ lat: 35.20, lon: -111.65 }, { lat: 35.21, lon: -111.64 }], costing: 'auto' }),
    }).then((r) => r.json()).then((data) => {
      window._geographicaSetActiveRoute(data.trip, { refitBounds: true, costing: 'auto' });
    });
  });

  // Assert map 'route' source data has initial shape.
  const initialCoords = await page.evaluate(() => {
    const s = window._geographicaMap.getSource('route');
    return s && s._data && s._data.geometry ? s._data.geometry.coordinates.length : 0;
  });
  if (initialCoords === 0) {
    console.error('ASSERT FAIL: map route source never received initial coords');
    process.exit(1);
  }

  // Start nav and trigger reroute via off-route GPS.
  await page.evaluate(() => {
    const nav = window.GeographicaNav;
    // Manually feed the start trigger:
    const trip = window._geographicaLastTrip;
    // Use navigation.js's applyReroute directly isn't representative;
    // instead simulate by calling startNavigation via the DOM button.
    document.getElementById('start-nav-btn').click();
  });

  // Wait for nav-active class on body.
  await page.waitForFunction(() => document.body.classList.contains('nav-active'), null, { timeout: 5_000 });

  // Force off-route GPS for several ticks (engine hysteresis 3-of-5).
  for (let i = 0; i < 8; i++) {
    await page.evaluate(() => {
      window._geographicaGPSData = { lat: 35.25, lon: -111.55, heading: 90, speed: 10 };
    });
    await page.waitForTimeout(600);  // > 500 ms feedGPS interval
  }

  // Wait for map 'route' source to be updated with REROUTE_SHAPE's coords.
  await page.waitForFunction((originalCount) => {
    const s = window._geographicaMap.getSource('route');
    const coords = s && s._data && s._data.geometry ? s._data.geometry.coordinates : [];
    return coords.length > 0 && coords.length !== originalCount;
  }, initialCoords, { timeout: 15_000 }).catch(() => {
    console.error('ASSERT FAIL (B2): map route source did not update after reroute');
    process.exit(1);
  });

  console.log('PASS: map route source updates after reroute (B2)');
  await browser.close();
}

mainAsserts().catch((err) => {
  console.error('Harness crashed:', err);
  process.exit(1);
});
```

- [ ] **Step 2: Run — verify the assertion fails against the un-fixed reroute path**

Run: `cd dev/harness && node drive-nav.mjs --url=<your-dev-url>`
Expected: `ASSERT FAIL (B2): map route source did not update after reroute`.

(Requires a running dev frontend. If none is available on the dev machine, skip to Step 3 and document that the harness is written but couldn't be run here; it runs in CI.)

- [ ] **Step 3: Fix the reroute path in nav-ui.js**

In [frontend/nav-ui.js:500-532](../../../frontend/nav-ui.js#L500-L532), replace `attemptReroute` with:

```javascript
  function attemptReroute(body, seq, info) {
    fetch('/valhalla/route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
    .then(function (res) { return res.json(); })
    .then(function (data) {
      if (data && data.error) {
        // Valhalla returned 200 with {error: "..."} — no trip field.
        // Treat as a retryable failure, not a silent no-op. (B11)
        throw new Error('Valhalla error: ' + data.error);
      }
      if (data.trip && nav) {
        // Update all four state slots via the unified owner (B2).
        var applied = window._geographicaSetActiveRoute(data.trip, {
          refitBounds: false,          // keep camera locked during nav
          costing: info.costing,
          costingOptions: info.costingOptions || null,
        });
        var newRouteData = buildRouteData(data.trip);
        if (newRouteData) {
          rerouteRetries = 0;
          nav.applyReroute(newRouteData, seq);
          hideBanner();
        }
      }
    })
    .catch(function (err) {
      console.error('Reroute failed:', err);
      rerouteRetries++;
      if (rerouteRetries <= MAX_REROUTE_RETRIES) {
        var delay = Math.pow(2, rerouteRetries) * 1000;
        var timeoutId = setTimeout(function () {
          attemptReroute(body, seq, info);
        }, delay);
        pendingRerouteTimeouts.push(timeoutId);
      } else {
        rerouteRetries = 0;
        showBanner('Reroute failed \u2014 using current route', 'reroute-failed');
        setTimeout(hideBanner, 5000);
      }
    });
  }
```

Notice:
- Third parameter `info` — so the catch branch can re-trigger with the same costing/options.
- `pendingRerouteTimeouts` — used by Task 11 (B12). Declare it as a module-level array at the top of nav-ui.js alongside the other module state: `var pendingRerouteTimeouts = [];` (this change ships now because attemptReroute uses it; Task 11 is the cleanup on stopNavigation).

At the top of nav-ui.js (around [line 34](../../../frontend/nav-ui.js#L34)), add:

```javascript
  var pendingRerouteTimeouts = [];
```

And update the top-level caller in `onReroute` at [frontend/nav-ui.js:470-498](../../../frontend/nav-ui.js#L470-L498):

```javascript
    var seq = info._seq;

    rerouteRetries = 0;
    attemptReroute(body, seq);
```

to:

```javascript
    var seq = info._seq;

    rerouteRetries = 0;
    attemptReroute(body, seq, info);
```

- [ ] **Step 4: Run the Playwright harness**

Run: `cd dev/harness && node drive-nav.mjs --url=<your-dev-url>`
Expected: `PASS: map route source updates after reroute (B2)`.

- [ ] **Step 5: Run all tests**

Run: `node --test frontend/tests/`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/nav-ui.js dev/harness/drive-nav.mjs
git commit -m "$(cat <<'EOF'
fix(nav): update map polyline + sidebar + _geographicaLastTrip on reroute (B2)

Pre-fix, attemptReroute called only nav.applyReroute(newRouteData, seq)
— engine-side only. The map 'route' GeoJSON source, sidebar
#route-directions list, window._geographicaLastTrip, and lastRouteCoords
all remained on the pre-deviation polyline. Users saw their car "drive
off" the blue line after a successful reroute.

Now: attemptReroute invokes window._geographicaSetActiveRoute(trip,
{ refitBounds: false }) — the unified owner introduced in the previous
commits — before calling nav.applyReroute. All four state slots update
in one atomic step. refitBounds: false keeps the camera locked on the
driver's POV during active nav.

Third parameter `info` added to attemptReroute so retries preserve
costing and costingOptions. A new module-level pendingRerouteTimeouts
array tracks retry setTimeouts (cleanup landing in a follow-up commit
for B12).

Test: dev/harness/drive-nav.mjs --url=<dev-url> triggers off-route GPS
and asserts map.getSource('route')._data.geometry.coordinates changes
after reroute resolves.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

**REVIEW LOOP 3** (after Phase 3, Tasks 7-9):

1. **Conflation check:** does `setActiveRoute` accidentally couple initial-fetch and reroute paths that should differ? Specifically, the sidebar rebuild on every reroute is desired for v1 — user wants to see updated directions. If this flickers too much in testing, consider a `mode: 'initial' | 'reroute'` flag that suppresses sidebar-rebuild for reroutes with identical maneuvers. Defer unless user complains.
2. **Window exposure as an API surface:** `window._geographicaSetActiveRoute` is now a public contract. Document this in code (JSDoc above the function is already done). Add a one-liner in the nav-engine README about the contract.
3. **Interaction with B5 (waypoints) and B6 (costing_options):** the reroute path in Task 9 passes `info.costingOptions` from the engine callback, which came from the route payload (Task 5). Verify end-to-end: route fetch body has costing_options → app.js stores on `_costingOptions` → buildRouteData reads `trip._costingOptions` → engine route has `costingOptions` → engine callback emits it → reroute body includes it. Draw this diagram in the commit message review.
4. **Error-path testability:** Task 9's B11-related throw (Valhalla 200 with error) is exercised implicitly by the retry loop. Add an explicit Playwright test that mocks the error response? (Filed as Task 10 below.)
5. **Repeat reviews minimum 3 rounds.** Re-verify after any code change.

---

## Phase 4 — Reroute robustness

### Task 10: Bug B11 — explicit Valhalla-200-with-error branch

**Files:**
- Modify: `frontend/nav-ui.js:500-532` (already touched in Task 9)
- Test: `dev/harness/drive-nav.mjs` (extend with an error-mock mode)

**Context:** Task 9 already introduced the `if (data && data.error) throw new Error(...)` branch. This task adds the regression test.

- [ ] **Step 1: Extend drive-nav.mjs with an error-mode**

Add a `--mode=error` CLI flag to `dev/harness/drive-nav.mjs`. When set, the Valhalla mock returns `{ status: 200, body: JSON.stringify({ error: 'No route found' }) }` on the reroute POST (second POST to /valhalla/route).

After the off-route triggers, assert:
- `rerouteRetries` hit MAX_REROUTE_RETRIES → banner shows `Reroute failed — using current route`
- Banner becomes visible within `MAX_REROUTE_RETRIES * max-delay + fudge` (~16 s)

```javascript
// At the top of drive-nav.mjs, parse the mode flag:
const modeArg = argv.find((a) => a.startsWith('--mode='));
const mode = modeArg ? modeArg.slice(7) : 'b2';  // default: B2 assertion

// In mockValhalla, branch on mode:
async function mockValhalla(page) {
  let rerouteCallCount = 0;
  await page.route('**/valhalla/route', async (route, req) => {
    const body = JSON.parse(req.postData() || '{}');
    const isReroute = body.locations && Math.abs(body.locations[0].lat - 35.25) < 0.1;
    if (isReroute) rerouteCallCount++;

    if (mode === 'error' && isReroute) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'No route found' }),
      });
      return;
    }
    // ... (default behavior as before)
  });
}

// In mainAsserts, if mode === 'error', assert banner after timeout:
if (mode === 'error') {
  // Retries: 2s + 4s + 8s = 14s maximum
  await page.waitForFunction(() => {
    const b = document.getElementById('nav-banner');
    return b && !b.classList.contains('hidden') && b.textContent.includes('Reroute failed');
  }, null, { timeout: 20_000 }).catch(() => {
    console.error('ASSERT FAIL (B11): no Reroute failed banner after error-mode reroute');
    process.exit(1);
  });
  console.log('PASS: Reroute failed banner surfaces on Valhalla 200-with-error (B11)');
  await browser.close();
  return;
}
```

- [ ] **Step 2: Run**

Run: `cd dev/harness && node drive-nav.mjs --mode=error --url=<dev-url>`
Expected: `PASS: Reroute failed banner surfaces on Valhalla 200-with-error (B11)`.

- [ ] **Step 3: Commit**

```bash
git add dev/harness/drive-nav.mjs
git commit -m "$(cat <<'EOF'
test(nav): assert reroute 200-with-error surfaces failure banner (B11)

Extends drive-nav.mjs with --mode=error: the mocked Valhalla returns
200 with {error: "..."} (no trip field). Asserts the UI cycles through
MAX_REROUTE_RETRIES (exponential 2/4/8s) then surfaces the "Reroute
failed — using current route" banner, instead of silently staying on
"Recalculating..." forever.

The fix itself shipped as part of the B2 refactor commit (explicit
`if (data && data.error) throw` branch in attemptReroute).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Bug B12 — AbortController + tracked setTimeouts on `stopNavigation`

**Files:**
- Modify: `frontend/nav-ui.js:195-231` (`stopNavigation`), `frontend/nav-ui.js:498-532` (`attemptReroute`)
- Test: extend `dev/harness/drive-nav.mjs`

**Context:** Task 9 added `pendingRerouteTimeouts`. This task:
1. Clears pendingRerouteTimeouts in stopNavigation
2. Adds an AbortController to attemptReroute so in-flight fetches cancel on stop
3. Resets `rerouteRetries = 0` on stop

- [ ] **Step 1: Write failing test**

Extend `dev/harness/drive-nav.mjs` with a `--mode=stop-mid-reroute` case:
- Trigger off-route
- After reroute fetch is in flight but before resolution, click #stop-nav-btn
- Assert: no subsequent fetch hits /valhalla/route within 10 s
- Assert: no setActiveRoute is called after nav stops

```javascript
if (mode === 'stop-mid-reroute') {
  let rerouteHitsAfterStop = 0;
  let navStoppedAt = null;

  await page.route('**/valhalla/route', async (route, req) => {
    const now = Date.now();
    if (navStoppedAt && now > navStoppedAt) {
      rerouteHitsAfterStop++;
    }
    // Delay the response by 3 s so we can stop nav mid-flight.
    await new Promise((r) => setTimeout(r, 3000));
    // ... standard response ...
  });

  // Trigger off-route, then immediately click stop.
  for (let i = 0; i < 5; i++) {
    await page.evaluate(() => {
      window._geographicaGPSData = { lat: 35.25, lon: -111.55, heading: 90, speed: 10 };
    });
    await page.waitForTimeout(200);
  }

  // Wait 500 ms for the reroute fetch to start, then stop nav.
  await page.waitForTimeout(500);
  navStoppedAt = Date.now();
  await page.evaluate(() => document.getElementById('stop-nav-btn').click());

  // Wait 10 s and assert no further /valhalla/route calls.
  await page.waitForTimeout(10_000);
  if (rerouteHitsAfterStop > 0) {
    console.error(`ASSERT FAIL (B12): ${rerouteHitsAfterStop} reroute fetches fired after stop`);
    process.exit(1);
  }
  console.log('PASS: no reroute fetches after stopNavigation (B12)');
  await browser.close();
  return;
}
```

- [ ] **Step 2: Run — verify fail**

Run: `cd dev/harness && node drive-nav.mjs --mode=stop-mid-reroute --url=<dev-url>`
Expected: `ASSERT FAIL (B12)` if the retry cascade continues after stop.

- [ ] **Step 3: Fix nav-ui.js**

At top of nav-ui.js module state (near [line 34](../../../frontend/nav-ui.js#L34)), add:

```javascript
  var rerouteAbortController = null;
```

In `attemptReroute` (modified in Task 9), thread the AbortController:

```javascript
  function attemptReroute(body, seq, info) {
    if (rerouteAbortController) rerouteAbortController.abort();
    rerouteAbortController = new AbortController();
    var signal = rerouteAbortController.signal;

    fetch('/valhalla/route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: signal,
    })
    .then(function (res) { return res.json(); })
    .then(function (data) {
      if (signal.aborted) return;  // bail if user stopped nav mid-flight
      if (data && data.error) {
        throw new Error('Valhalla error: ' + data.error);
      }
      // ... (same as Task 9) ...
    })
    .catch(function (err) {
      if (err.name === 'AbortError') return;  // silent on user-initiated abort
      // ... (same as Task 9) ...
    });
  }
```

In `stopNavigation` ([nav-ui.js:195-231](../../../frontend/nav-ui.js#L195-L231)), append before the function closes:

```javascript
    // B12: cancel in-flight reroute fetches and clear pending retries.
    if (rerouteAbortController) {
      rerouteAbortController.abort();
      rerouteAbortController = null;
    }
    pendingRerouteTimeouts.forEach(function (id) { clearTimeout(id); });
    pendingRerouteTimeouts = [];
    rerouteRetries = 0;
  }
```

- [ ] **Step 4: Run**

Run: `cd dev/harness && node drive-nav.mjs --mode=stop-mid-reroute --url=<dev-url>`
Expected: `PASS: no reroute fetches after stopNavigation (B12)`.

- [ ] **Step 5: Commit**

```bash
git add frontend/nav-ui.js dev/harness/drive-nav.mjs
git commit -m "$(cat <<'EOF'
fix(nav): cancel in-flight reroute fetches and retries on stop (B12)

Pre-fix, stopNavigation cleared autoCenterTimer, gpsHeartbeatTimer, and
gpsFeedInterval but not the reroute path. A retry setTimeout scheduled
with 8 s exponential backoff could fire after nav stopped (and during
a re-started session), then either fail-silent on the `data.trip && nav`
guard or log a spurious console error.

Now:
- attemptReroute uses an AbortController; stopNavigation aborts it.
- Retry setTimeouts are tracked in pendingRerouteTimeouts; stopNavigation
  clears all of them.
- rerouteRetries counter is reset on stop so the next session starts
  from retry 0.

AbortError is silently ignored in the .catch branch to avoid spurious
console noise on user-initiated stops.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

**REVIEW LOOP 4** (after Phase 4, Tasks 10-11):

1. **Defense in depth:** three guards now exist against stale reroute application — `signal.aborted` check in the `.then`, AbortError short-circuit in the `.catch`, and the `data.trip && nav` guard inside the apply block. That's good; redundant but each catches a different case.
2. **Testing pitfall: Unrecoverable state on async failure.** Task 10 covers the 200-with-error case. Verify there's no pathway that leaves `rerouteRetries` non-zero after `stopNavigation` OR after retries exhaust — both paths now reset it. Cross-check.
3. **Pitfall: state consumed on check.** AbortController's `signal.aborted` check is a "consumed on check" pattern — once aborted, subsequent branches short-circuit. That's intentional here but worth noting.
4. Repeat min 3 rounds.

---

## Phase 5 — GPS feed + padding math

### Task 12: Bug B7 — engine dedups duplicate GPS positions for hysteresis

**Files:**
- Modify: `frontend/navigation.js:777-784` (engine `updateGPS`)
- Test: extend `frontend/tests/engine/navigation.test.mjs`

**Context:** [navigation.js:22](../../../frontend/navigation.js#L22) documents `OFF_ROUTE_TICKS = 5` as "legacy, unused" — the current hysteresis uses `OFF_ROUTE_WINDOW = 5` with `OFF_ROUTE_MIN_COUNT = 3`. The design intent was ~5 s of debounce at 1 Hz. But [nav-ui.js:323](../../../frontend/nav-ui.js#L323) polls every 500 ms and calls `updateGPS` every tick — so the engine receives each physical GPS reading twice, filling the window in ~2.5 s and firing premature reroutes under noise or while stopped at lights.

**Why engine-side, not UI-side:** A UI-side gate (only call `updateGPS` when lat/lng changes) would stop the engine from seeing a "keepalive" on stationary GPS — after `GPS_STALE_TIMEOUT = 3000` with no tick, the engine's stale checker would fire dead-reckoning even though GPS is actually fresh and the user is just stopped. Engine-side dedup preserves `lastGPSTime` updates (heartbeat-like) while gating only the state-transition path (`tick`).

- [ ] **Step 1: Write failing test**

Add to `frontend/tests/engine/navigation.test.mjs`:

```javascript
test('duplicate GPS positions do not fill off-route hysteresis (B7)', async () => {
  const { nav, window: win } = await loadEngine();
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };

  const rerouteCalls = [];
  nav.onReroute((info) => rerouteCalls.push(info));

  nav.start(fixtureTwoManeuverRoute());

  // Feed the SAME off-route position 10 times — simulates feedGPS()
  // ticking every 500 ms on a stationary vehicle whose backend-pushed
  // GPS data object hasn't changed. Engine must dedup by (lat,lng)
  // and only tick once per unique position, so hysteresis cannot fill.
  for (let i = 0; i < 10; i++) {
    nav.updateGPS({ latitude: 35.25, longitude: -111.55, heading: 90, speed: 10 });
  }
  assert.equal(rerouteCalls.length, 0, 'duplicate positions must not fill hysteresis');

  // Feed 5 distinct positions — each must count, hysteresis fills, reroute fires.
  const offRoutePositions = [
    [35.25, -111.55], [35.26, -111.54], [35.27, -111.53],
    [35.28, -111.52], [35.29, -111.51],
  ];
  offRoutePositions.forEach(([lat, lon]) => {
    nav.updateGPS({ latitude: lat, longitude: lon, heading: 90, speed: 10 });
  });
  assert.equal(rerouteCalls.length, 1, 'distinct positions fill hysteresis as designed');
});
```

- [ ] **Step 2: Run — verify fail**

Run: `node --test frontend/tests/engine/`
Expected: first assertion fails (10 duplicate ticks fill hysteresis, rerouteCalls.length becomes 1 after 3-5 ticks).

- [ ] **Step 3: Fix the engine's updateGPS**

In [frontend/navigation.js:777-784](../../../frontend/navigation.js#L777-L784), replace:

```javascript
    updateGPS: function (data) {
      lastGPS = data;
      lastGPSTime = Date.now();

      if (state !== "idle") {
        tick(data);
      }
    },
```

with:

```javascript
    updateGPS: function (data) {
      // Dedup on (lat, lng): the UI polls feedGPS every 500 ms but the
      // GPS source is ~1 Hz, so half the ticks carry an unchanged
      // position. The off-route hysteresis window (5-tick, 3-of-5) is
      // designed for 1 Hz; duplicate ticks would fill it in half the
      // intended time and cause false reroutes while stationary. (B7)
      //
      // We still refresh lastGPSTime so the stale-checker doesn't fire
      // DR on a stationary-but-fresh-GPS vehicle.
      var positionChanged = !lastGPS ||
        lastGPS.latitude !== data.latitude ||
        lastGPS.longitude !== data.longitude;

      lastGPS = data;
      lastGPSTime = Date.now();

      if (state !== "idle" && positionChanged) {
        tick(data);
      }
    },
```

- [ ] **Step 4: Run — verify green**

Run: `node --test frontend/tests/engine/`
Expected: all pass.

- [ ] **Step 5: Manual smoke in browser**

Drive the dev site: stand still for 10+ seconds with active nav, confirm NO "Recalculating..." banner and no reroute attempt. Then intentionally go off-route, confirm the reroute fires within ~5 seconds (5 distinct GPS positions).

- [ ] **Step 6: Commit**

```bash
git add frontend/navigation.js frontend/tests/
git commit -m "$(cat <<'EOF'
fix(nav): engine dedups duplicate GPS positions for hysteresis (B7)

Pre-fix, the UI polled feedGPS every 500 ms and called nav.updateGPS
unconditionally — even when window._geographicaGPSData.lat/lon hadn't
changed. GPS source updates at ~1 Hz, so every physical reading hit
the engine twice. The off-route hysteresis (OFF_ROUTE_WINDOW=5,
MIN_COUNT=3) was designed for 1 Hz; at effective 2 Hz it filled in
~2.5 s, doubling reroute rate under noise and firing false reroutes
while stopped at lights.

Fix is engine-side (not UI-side) to preserve the "stationary GPS is
still fresh" semantic — we still refresh lastGPSTime on duplicate
ticks so the engine's stale-checker doesn't fire dead-reckoning on
a parked vehicle.

updateGPS now gates the tick() call on (lat, lng) change but still
updates lastGPS and lastGPSTime on every call.

Test feeds 10 duplicate off-route positions and asserts zero reroutes,
then 5 distinct off-route positions and asserts exactly one reroute —
hysteresis behaves as originally designed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: Bug B3+B8 — proportional padding + restoreMapState padding clear

**Files:**
- Modify: `frontend/nav-ui.js:725-733` (`getNavPadding`), `frontend/nav-ui.js:549-559` (`restoreMapState`)
- Test: extend `dev/harness/drive-nav.mjs` with a padding snapshot assertion

**Context:** `getNavPadding` returns only `top: overlay.offsetHeight + 20`, placing the GPS marker at ~58% from top (MapLibre padding is an inset; effective center is `(top + H)/2`). Target: 78% from top (user asked for "bottom 20% or less"; 78% is an aggressive but usable target). Formula: `top = overlayH + 0.56 * mapH` (derivation in [dev/bug-hunts/2026-04-21-nav-uxb-consolidated.md](../../../dev/bug-hunts/2026-04-21-nav-uxb-consolidated.md) B3 section).

`restoreMapState` doesn't pass padding, so the nav-era inset leaks into post-nav `fitBounds`/`flyTo`.

- [ ] **Step 1: Modify getNavPadding for proportional math**

In [frontend/nav-ui.js:725-733](../../../frontend/nav-ui.js#L725-L733), replace:

```javascript
  function getNavPadding() {
    if (!overlay || overlay.classList.contains('hidden')) return {};
    var measured = overlay.offsetHeight + 20;
    if (Math.abs(measured - lastNavPaddingTop) > PADDING_RECALC_THRESHOLD) {
      lastNavPaddingTop = measured;
    }
    return { top: lastNavPaddingTop };
  }
```

with:

```javascript
  /**
   * Returns MapLibre `padding` suitable for placing the GPS marker at ~78%
   * from the top of the map container — below the nav overlay and well
   * into the bottom third so the user can see ahead of their direction of
   * travel.
   *
   * MapLibre `padding` is an *inset*: effective center is
   *   ((top + (H - bottom)) / 2, ...)
   * For a target y = f * H:
   *   f = (top + H - bottom) / (2*H)
   *   top - bottom = H * (2f - 1)
   * With bottom=0 and f=0.78: top = H * 0.56. Add overlayH so the overlay
   * itself doesn't cover the marker at extreme aspect ratios.
   */
  function getNavPadding() {
    if (!overlay || overlay.classList.contains('hidden')) {
      return { top: 0, bottom: 0, left: 0, right: 0 };
    }
    var overlayH = overlay.offsetHeight;
    var mapH = (map && map.getContainer) ? map.getContainer().clientHeight : window.innerHeight;
    if (!mapH || mapH < 100) mapH = window.innerHeight; // degenerate container
    // Target: marker at y = 0.78 * mapH
    //   top = mapH * (2 * 0.78 - 1) = mapH * 0.56
    // Add overlayH so top padding also covers the overlay.
    var desiredTop = overlayH + Math.round(mapH * 0.56);
    if (Math.abs(desiredTop - lastNavPaddingTop) > PADDING_RECALC_THRESHOLD) {
      lastNavPaddingTop = desiredTop;
    }
    return { top: lastNavPaddingTop, bottom: 0, left: 0, right: 0 };
  }
```

- [ ] **Step 2: Modify restoreMapState to clear padding**

In [frontend/nav-ui.js:549-559](../../../frontend/nav-ui.js#L549-L559), change:

```javascript
  function restoreMapState() {
    if (!savedMapState) return;
    map.easeTo({
      center: savedMapState.center,
      zoom: savedMapState.zoom,
      pitch: savedMapState.pitch,
      bearing: savedMapState.bearing,
      duration: 800
    });
    savedMapState = null;
  }
```

to:

```javascript
  function restoreMapState() {
    if (!savedMapState) return;
    map.easeTo({
      center: savedMapState.center,
      zoom: savedMapState.zoom,
      pitch: savedMapState.pitch,
      bearing: savedMapState.bearing,
      duration: 800,
      // B8: clear the nav-era padding so post-nav fitBounds/flyTo
      // aren't offset into the bottom of the screen.
      padding: { top: 0, bottom: 0, left: 0, right: 0 },
    });
    savedMapState = null;
  }
```

- [ ] **Step 3: Extend drive-nav.mjs with a padding assertion**

Add `--mode=padding` case to drive-nav.mjs:

```javascript
if (mode === 'padding') {
  // Start nav, wait for easeTo to settle.
  await page.evaluate(() => document.getElementById('start-nav-btn').click());
  await page.waitForFunction(() => document.body.classList.contains('nav-active'));
  await page.waitForTimeout(2000);  // let easeTo settle

  // Where on screen is the GPS marker (center of easeTo target)?
  const center = await page.evaluate(() => {
    const data = window._geographicaGPSData;
    const px = window._geographicaMap.project([data.lon, data.lat]);
    const mapH = window._geographicaMap.getContainer().clientHeight;
    return { y: px.y, mapH, fraction: px.y / mapH };
  });

  console.log(`GPS marker at y=${center.y}/${center.mapH} = ${(center.fraction*100).toFixed(1)}% from top`);
  if (center.fraction < 0.70 || center.fraction > 0.86) {
    console.error(`ASSERT FAIL (B3): GPS marker not in 70-86% range (got ${(center.fraction*100).toFixed(1)}%)`);
    process.exit(1);
  }
  console.log('PASS: GPS marker at ~78% from top (B3)');

  // Stop nav, verify post-nav fitBounds does NOT have stale padding.
  await page.evaluate(() => document.getElementById('stop-nav-btn').click());
  await page.waitForFunction(() => !document.body.classList.contains('nav-active'));
  // Force a fitBounds call and check the reported padding.
  const postNavPadding = await page.evaluate(() => {
    // MapLibre getPadding exists post-setPadding — fire a fitBounds then read.
    window._geographicaMap.fitBounds(
      [[-111.65, 35.20], [-111.60, 35.25]],
      { duration: 0, padding: { top: 20, bottom: 20, left: 20, right: 20 } }
    );
    return window._geographicaMap.getPadding();
  });
  if (postNavPadding.top > 50) {
    console.error(`ASSERT FAIL (B8): post-nav padding retained nav inset (top=${postNavPadding.top})`);
    process.exit(1);
  }
  console.log('PASS: padding cleared after nav (B8)');
  await browser.close();
  return;
}
```

- [ ] **Step 4: Run**

Run: `cd dev/harness && node drive-nav.mjs --mode=padding --url=<dev-url>`
Expected: `PASS: GPS marker at ~78% from top (B3)` + `PASS: padding cleared after nav (B8)`.

- [ ] **Step 5: Commit**

```bash
git add frontend/nav-ui.js dev/harness/drive-nav.mjs
git commit -m "$(cat <<'EOF'
fix(nav): proportional nav padding + clear padding on nav exit (B3, B8)

Pre-fix, getNavPadding returned only { top: overlay.offsetHeight + 20 }
— MapLibre's padding is an inset, not an offset, so center landed at
(top + H)/2 ≈ 58% from top. User wanted bottom 1/3 (~78%). Formula:
for target y=f*H with bottom=0, top = H*(2f-1). Using f=0.78:
top = H*0.56 + overlayH (extra for overlay coverage).

Also: restoreMapState's easeTo had no padding arg, so MapLibre retained
the nav-era top inset for the rest of the session. Post-nav fitBounds
calls were silently offset into the bottom of the screen.

Now:
- getNavPadding uses proportional formula with 78% target, reads
  mapH from map.getContainer() (falls back to window.innerHeight for
  degenerate containers).
- restoreMapState explicitly passes padding { top: 0, ... } to clear
  the nav-era inset.

Playwright test (drive-nav.mjs --mode=padding) asserts GPS marker is
at 70-86% from top during active nav AND that MapLibre.getPadding()
is cleared after stopNavigation.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

**REVIEW LOOP 5** (after Phase 5, Tasks 12-13):

1. **Math check (B3):** if overlayH=150 and mapH=900, desiredTop = 150 + 504 = 654. Effective center = (654 + 900)/2 = 777 ≈ 86% from top. If mapH=600 (landscape phone), desiredTop = 150 + 336 = 486. Effective center = (486 + 600)/2 = 543 ≈ 90% from top. **Too aggressive on short screens.** Reconsider formula. The correct derivation without the overlayH bonus: desiredTop = mapH * 0.56 → 504 for 900px gives center at 702 = 78%. With overlayH added on top: 654 → 777 = 86%. The overlayH bump makes short screens worse. Fix: drop the overlayH bump — the 0.56 * mapH formula already places the marker below the overlay area (typical overlayH ~100px, desiredTop ~504 on 900 screen, center at ~700 — the overlay at top covers 0-100, marker at 700, no conflict).

    **Corrected formula:** `desiredTop = Math.max(overlayH, Math.round(mapH * 0.56));`

    This ensures top >= overlayH (marker never under overlay) and uses the proportional formula otherwise. Update Step 1's code in Task 13.

2. **Testing pitfall: viewport-dependent tests.** The padding assertion in Step 3 needs a consistent browser viewport. Playwright's default is 1280×720. At 720px height, mapH is slightly less (accounting for status bar, controls). Assertion range 70-86% should cover typical variations.

3. **Mobile portrait check:** iPhone SE is 375×667. Verify formula at that size by adding a viewport-emulated mode to drive-nav.mjs, e.g. `--viewport=mobile`. Defer to a follow-up if time-constrained.

4. **Interaction with B2 refactor:** `setActiveRoute({ refitBounds: true })` for initial route uses hard-coded padding values `{ top: 60, bottom: 60, ... }` for desktop. That's initial-route framing, unrelated to nav padding. Keep as-is.

5. Minimum 3 review rounds. Apply the formula correction as a follow-up commit within this phase:

### Task 13.5: Formula correction from review loop 5

- [ ] **Step 1: Apply the corrected formula**

In [frontend/nav-ui.js:725-748](../../../frontend/nav-ui.js#L725-L748) (the `getNavPadding` just added in Task 13), change:

```javascript
    var desiredTop = overlayH + Math.round(mapH * 0.56);
```

to:

```javascript
    // Use max(overlayH, proportional target): proportional places the
    // marker at ~78% from top on typical viewports; max(overlayH) ensures
    // the marker is never hidden under the overlay on short viewports.
    var desiredTop = Math.max(overlayH + 20, Math.round(mapH * 0.56));
```

- [ ] **Step 2: Run padding test**

Run: `cd dev/harness && node drive-nav.mjs --mode=padding --url=<dev-url>`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/nav-ui.js
git commit -m "$(cat <<'EOF'
fix(nav): correct padding formula for short viewports (B3 follow-up)

Initial B3 fix (2 commits ago) set top = overlayH + 0.56*mapH, which
on a 600px-tall landscape phone placed the marker at ~90% from top
— too low, marker lost under bottom controls.

Corrected formula: top = max(overlayH + 20, 0.56*mapH). Proportional
term dominates on typical-height viewports; overlay coverage floor
applies on short viewports. At mapH=900: top=504, center=702 (78%).
At mapH=600: top=336, center=468 (78%). Stable 78% across viewports.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 6 — UI polish

### Task 14: Bug B4 — recenter + compass button stack

**Files:**
- Modify: `frontend/style.css:1436-1439`, `frontend/style.css:1673-1688`
- Test: extend `dev/harness/drive-nav.mjs` with `--mode=buttons`

**Context:** Buttons are 36×36. User wants recenter-btn (the re-center-on-route icon) ABOVE the compass, with a clear visual gap and no overlap at any supported viewport. Consolidated findings B4 section has the target positions.

- [ ] **Step 1: Write failing test**

Add `--mode=buttons` to `dev/harness/drive-nav.mjs`:

```javascript
if (mode === 'buttons') {
  // Start nav so nav-recenter-btn could be shown.
  await page.evaluate(() => document.getElementById('start-nav-btn').click());
  await page.waitForFunction(() => document.body.classList.contains('nav-active'));

  // Force nav-recenter-btn visible: simulate a manual pan.
  await page.evaluate(() => window._navPauseAutoCenter && window._navPauseAutoCenter());
  await page.waitForTimeout(100);

  // Test at desktop viewport.
  for (const viewport of [{ width: 1280, height: 800, label: 'desktop' }, { width: 375, height: 667, label: 'mobile' }]) {
    await page.setViewportSize(viewport);
    await page.waitForTimeout(100);

    const rects = await page.evaluate(() => {
      const recenter = document.getElementById('nav-recenter-btn');
      const compass = document.getElementById('compass-north-btn');
      return {
        recenter: recenter ? recenter.getBoundingClientRect() : null,
        compass: compass ? compass.getBoundingClientRect() : null,
      };
    });

    if (!rects.recenter || !rects.compass) {
      console.error(`ASSERT FAIL (B4/${viewport.label}): one of the buttons missing`);
      process.exit(1);
    }

    // Assertion 1: no overlap — recenter bottom must be above compass top.
    if (rects.recenter.bottom > rects.compass.top) {
      console.error(`ASSERT FAIL (B4/${viewport.label}): recenter/compass overlap (recenter.bottom=${rects.recenter.bottom}, compass.top=${rects.compass.top})`);
      process.exit(1);
    }

    // Assertion 2: recenter is ABOVE compass on screen (lower y = higher on screen).
    if (rects.recenter.top > rects.compass.top) {
      console.error(`ASSERT FAIL (B4/${viewport.label}): recenter must be above compass on screen`);
      process.exit(1);
    }

    // Assertion 3: gap of at least 8px between them.
    const gap = rects.compass.top - rects.recenter.bottom;
    if (gap < 8) {
      console.error(`ASSERT FAIL (B4/${viewport.label}): gap too small (${gap}px)`);
      process.exit(1);
    }

    console.log(`PASS (${viewport.label}): recenter above compass, gap=${gap}px`);
  }
  await browser.close();
  return;
}
```

- [ ] **Step 2: Run — verify fail on desktop (recenter below compass)**

Run: `cd dev/harness && node drive-nav.mjs --mode=buttons --url=<dev-url>`
Expected: `ASSERT FAIL (B4/desktop): recenter must be above compass on screen`.

- [ ] **Step 3: Fix CSS**

In [frontend/style.css:1436-1439](../../../frontend/style.css#L1436-L1439):

```css
#nav-recenter-btn {
  bottom: 120px;
  right: 12px;
}
```

Change to:

```css
/* Nav re-center button: stacked ABOVE the compass so the
   direction-of-travel control is the closer-to-thumb button. */
#nav-recenter-btn {
  bottom: 170px;
  right: 12px;
  z-index: 11;
}
```

In [frontend/style.css:1672-1688](../../../frontend/style.css#L1672-L1688):

```css
/* ----- Compass Button ----- */
#compass-north-btn {
  position: absolute;
  bottom: 160px; /* above zoom controls (~120px) + attribution */
  right: 12px;
  z-index: 10;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  transition: transform 0.15s ease-out;
}

@media (max-width: 480px) {
  #compass-north-btn {
    bottom: 140px; /* tighter on mobile, zoom controls are smaller */
  }
}
```

Change to:

```css
/* ----- Compass Button -----
   Stacked below #nav-recenter-btn so both are right-hand thumb
   accessible. 36px buttons + 14px gap = recenter at bottom:170,
   compass at bottom:120 (ample clearance over attribution). */
#compass-north-btn {
  position: absolute;
  bottom: 120px;
  right: 12px;
  z-index: 11;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  transition: transform 0.15s ease-out;
}

@media (max-width: 480px) {
  #nav-recenter-btn {
    bottom: 150px;
  }
  #compass-north-btn {
    bottom: 100px;
  }
}
```

Stack (desktop): compass 120-156, recenter 170-206. Gap = 14px. Clears attribution (~26px).
Stack (mobile): compass 100-136, recenter 150-186. Gap = 14px. Clears attribution.

- [ ] **Step 4: Run — verify pass**

Run: `cd dev/harness && node drive-nav.mjs --mode=buttons --url=<dev-url>`
Expected: both desktop and mobile PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/style.css dev/harness/drive-nav.mjs
git commit -m "$(cat <<'EOF'
fix(nav): stack recenter button above compass, resolve mobile overlap (B4)

Pre-fix:
  Desktop: #nav-recenter-btn at bottom:120 (120-156), #compass-north-btn
  at bottom:160 (160-196). 4px gap, but recenter was BELOW compass —
  opposite of the user-preferred thumb-access order.
  Mobile (≤480px): compass at bottom:140 (140-176), recenter unchanged
  at bottom:120 (120-156). 16px vertical overlap, z-index collision.

Now:
  Desktop: compass at bottom:120 (120-156), recenter at bottom:170
  (170-206). 14px gap. Recenter is above compass.
  Mobile: compass at bottom:100 (100-136), recenter at bottom:150
  (150-186). 14px gap. Same stack order.

Explicit z-index:11 on both so they sit above the base map-btn z:10.

Playwright test asserts no overlap and correct stack order at both
desktop (1280x800) and mobile (375x667) viewports.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

**REVIEW LOOP 6** (after Phase 6, Task 14):

1. **Scale-bar conflict check:** MapLibre's ScaleControl at `bottom-right` (from [app.js:222-224](../../../frontend/app.js#L222-L224)) normally renders at ~bottom:4, right:4. Compass at bottom:100 mobile / bottom:120 desktop clears it comfortably.
2. **Zoom controls:** no NavigationControl is added in [app.js](../../../frontend/app.js) — custom compass button covers that role. No conflict.
3. **Landscape mobile (`480-768px width`):** currently falls under desktop CSS. Gap stays at 14px. Acceptable.
4. **Attribution control:** MapLibre attributes at bottom-right by default (~16-20px tall). Clears our 100px floor.
5. **Min 3 review rounds.**

---

## Phase 7 — Runtime validation and integration

### Task 15: Full drive-nav harness sweep + manual smoke

**Files:**
- None created; verification only

- [ ] **Step 1: Run all harness modes against live dev stack**

Against a running dev frontend (`<dev-url>` — typically `http://pandora:8088` or similar):

```bash
cd dev/harness
node drive-nav.mjs --mode=b2 --url=<dev-url>
node drive-nav.mjs --mode=error --url=<dev-url>
node drive-nav.mjs --mode=stop-mid-reroute --url=<dev-url>
node drive-nav.mjs --mode=padding --url=<dev-url>
node drive-nav.mjs --mode=buttons --url=<dev-url>
```

All must return exit 0.

- [ ] **Step 2: Run all engine + nav-ui tests**

```bash
node --test frontend/tests/
```

Expected: all pass.

- [ ] **Step 3: Run project Python tests to verify no coupling broke**

```bash
python -m pytest tests/ services/search/tests/ -v -k 'not m2m and not nominatim'
```

Expected: same pass count as pre-plan baseline (the 2 pre-existing M2M failures are expected).

- [ ] **Step 4: Manual browser smoke (10 minutes)**

Load the dev frontend. Walk through:
1. Plan a simple 2-point route → blue line appears, sidebar directions populate, fitBounds animates. ✓
2. Click Start Nav → overlay appears, GPS marker visible in bottom ~3rd of screen, 3D tilt engaged. ✓
3. Voice plays at maneuver thresholds (1-2 per turn at current distance settings; full redesign deferred to TTM plan). ✓
4. Drive off-route (can simulate by moving `window._geographicaGPSData` in devtools) → blue line UPDATES to the new route after ~3 s of off-route GPS. Sidebar directions update. ✓
5. Click Stop Nav → overlay disappears, camera returns to pre-nav state, post-nav fitBounds is NOT offset (pan to any feature and verify standard centering). ✓
6. Recenter button and compass button both visible after manual pan, no overlap, recenter above compass. ✓

- [ ] **Step 5: Write release notes entry**

Append to `CHANGELOG.md` or `dev/implementation-log.md` per project convention. Scope: `fix(nav): 2026-04-21 beta-tester UX remediation`. List the 13 bug IDs addressed.

- [ ] **Step 6: Commit**

```bash
git add CHANGELOG.md dev/implementation-log.md
git commit -m "$(cat <<'EOF'
docs: log 2026-04-21 nav UX remediation (B2, B3, B4-B14 except B1)

Records the 13 bug fixes shipped from the 2026-04-21 beta-tester
triage + bug-hunt-cycle cycle. B1 (voice tiering) deferred to a
separate TTM redesign plan.

Full consolidated findings: dev/bug-hunts/2026-04-21-nav-uxb-consolidated.md
Plan: docs/superpowers/plans/2026-04-21-nav-uxb-remediation.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Appendix: Deferred follow-ups

### B1 — Voice TTM (time-to-maneuver) redesign

**Why deferred:** Cameron's decision 2026-04-21 — "No reason to fix now when we're going to rebuild it. Redesign with full adversarial review." A band-aid threshold retune would be discarded.

**Next action:** Start a fresh brainstorm session via `superpowers:brainstorming`. Spec the TTM model with these seed topics:
- Thresholds in seconds (e.g., `[30, 3]`) not meters.
- Speed source: rolling average over N ticks vs. raw.
- Divide-by-zero behavior at stopped/walking speeds.
- Distance floor (always fire within 50 m regardless of TTM).
- Interaction with `applyReroute` state reset and `setMuted`.
- Testing strategy: parameterized over 3+ speed regimes.

### O1 — `observeRouteAvailability` coupled to `#export-route-btn`

**Evidence:** [frontend/nav-ui.js:121-135](../../../frontend/nav-ui.js#L121-L135) — if the export button is restyled or removed, nav start button breaks.
**Recommended fix:** Add a `data-nav-available` attribute on body when a route is loaded; observe that instead.
**Priority:** low; defer until the export button changes.

### FP1 — `_geographicaUseImperial` race in `buildRouteData`

**Evidence:** [frontend/nav-ui.js:266](../../../frontend/nav-ui.js#L266) reads `window._geographicaUseImperial` to convert Valhalla summary.length to meters. If user toggles units between route fetch and nav start, multiplier is wrong.
**Recommended fix:** Read units from Valhalla response (`summary.units`) rather than global state.
**Priority:** low; rare race condition.

### FP2 — First-frame nav easeTo uses raw heading at zero speed

**Evidence:** [frontend/nav-ui.js:183-191](../../../frontend/nav-ui.js#L183-L191) — on stationary nav start, uses `gps.heading || 0` which may be a stale reading.
**Recommended fix:** Gate bearing by `speed >= HEADING_SPEED_GATE` at start; fall back to `map.getBearing()` if invalid.
**Priority:** low; visual wobble, not functional.

### FP3 — Dead reckoning can fire voice for turns that haven't happened

**Evidence:** [frontend/navigation.js:661-675](../../../frontend/navigation.js#L661-L675) — DR extrapolates position; checkVoice fires as if on real GPS.
**Recommended fix:** Suppress `checkVoice` when `drActive`; resume when real GPS returns.
**Priority:** low; 30 s DR cap limits blast radius.

### FP4 — Dead CSS variable `--nav-overlay-height`

**Evidence:** [frontend/nav-ui.js:453](../../../frontend/nav-ui.js#L453) — writes per tick, no selector reads it.
**Recommended fix:** Remove the line.
**Priority:** trivial cleanup; fold into next nav touch.

---

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-21-nav-uxb-remediation.md`.**

15 tasks spanning 6 phases + deferred follow-up appendix. Every task is TDD-preambled, has exact file paths and complete code blocks, and commits with conventional-commit messages. Six review loops built in (one after each phase).

**Two execution options:**

1. **Subagent-Driven (recommended).** Dispatch a fresh subagent per task, review between tasks. Fast iteration; each subagent starts with clean context. Use `superpowers:subagent-driven-development`.

2. **Inline Execution.** Execute tasks in this session with batch checkpoints. Use `superpowers:executing-plans`.

**My recommendation: Subagent-Driven.** Reasons:
- 15 self-contained tasks; plan has zero ambiguity and full code blocks — ideal for fresh subagents.
- Several tasks touch overlapping files (nav-ui.js in Phase 2, 4, 5) — each subagent's diff is small and easy to review before the next subagent picks up.
- Review loops after each phase are natural checkpoint gates; dispatching phase-by-phase lets me verify each group lands clean before moving on.
- The current session has consumed context on the consolidated findings — fresh subagents won't need that overhead.

Alternative if you want to execute inline: phases 1-3 (engine + setActiveRoute refactor) are the riskiest; if you'd rather drive those yourself and delegate phases 4-6 to subagents, that's also defensible.
