---
round: 3
angle: Testing sufficiency and quality
reviewer: general-purpose
date: 2026-04-20
---

# Round 3 — Testing strategy

Verdict up front: the testing strategy is well-intentioned but **not
sufficient to ship a safety-of-life feature with confidence**. A substantial
fraction of the prescribed tests are structural (grep-for-string, file-exists)
or mock-heavy around the exact surface we need to trust. Several failure modes
in §5 are cross-referenced to tests that do not actually exercise the claimed
behavior. There are no negative-invariant tests, no deterministic clock
strategy, no performance / battery bound, and the only assertion that "the
screen actually stays on" lives in the manual checklist — zero CI coverage.

## Findings

### F3.1 — Grep-based static tests mistake presence-of-string for presence-of-behavior
**Severity:** MUST-FIX
**Issue:** §6.1 `test_nav_ui_calls_wake_lock_acquire` and
`test_nav_ui_calls_wake_lock_release` are described as grep assertions that a
literal string appears in the right function. That passes when the call is
inside a JS block comment (`// WakeLock.acquire()`), inside a template
literal, inside a string reserved for a logger (`console.log('WakeLock.acquire() will run later')`),
inside an `if (false)` branch, or inside a function that is defined but never
called. It also passes if `acquire()` is invoked AFTER an `await`, which
§4.1 calls out as the most likely failure cause (gesture grace window lost).
**Why it matters:** the Round 2 acceptance criterion in §10 explicitly
requires the call to be synchronous with no intervening `await` — a grep
cannot enforce that. A subagent can pass all static tests and still ship a
non-working feature where `wakeLock.request` rejects in production.
**Proposed fix:** parse `nav-ui.js` with a lightweight JS parser (the project
already ships `acorn` indirectly via nothing — but Python has `esprima-python`
or even a hand-rolled regex scanner that matches the statement list between
`function startNavigation` and its closing brace). Assert that (a) `WakeLock.acquire()`
appears as a statement, not inside a comment/string; (b) no `await`
expression lexically precedes it inside `startNavigation`; (c) no
`setTimeout` / `Promise.resolve().then()` wraps it. Same shape for `release()`
at the exit path.

### F3.2 — §5.7 race test is prescribed but the canonical fix has a hole the test does not cover
**Severity:** MUST-FIX
**Issue:** §5.7 says the test injects a delayed-resolve `request()` mock,
calls `acquire()` then `release()` before it resolves, and asserts
`sentinel.release()` is called exactly once. That covers the "primary
resolves after release" race. It does NOT cover the fallback race: `acquire()`
enters the NoSleep branch because `'wakeLock' in navigator` is false,
`noSleep.enable()` is in flight (it returns a Promise), `release()` is called
before `enable()` resolves, and when `enable()` finally succeeds,
`noSleepActive` is never set to `true` (because the code sets it
synchronously after the call) — but the `<video>` has already started.
Looking at the canonical `acquire()` in §4.3: `noSleep.enable()` is called
WITHOUT being awaited, and `noSleepActive = true` runs immediately. If
`release()` fires in between `noSleep.enable()` starting and the video
actually beginning to play, `disable()` may run before the video element
exists, leaving an orphan `<video>` that keeps the screen on forever after
nav ends. **This is exactly testing-pitfalls.md #9 ("Unrecoverable async
state") which §7 of the spec claims is addressed.**
**Proposed fix:** add `test_release_during_pending_nosleep_enable`. Assert
that after a release-during-pending-enable cycle, no `<video>` is playing and
`WakeLock.status()` returns `'idle'`.

### F3.3 — Visibility-handler test does not exercise the real browser contract
**Severity:** SHOULD-FIX
**Issue:** §6.2 `test_visibility_hidden_then_visible_reacquires` needs to
dispatch a synthetic `visibilitychange` event AND flip
`document.visibilityState` to `'hidden'` / `'visible'`. In a hand-rolled
`vm.runInNewContext` document stub, `visibilityState` is whatever the stub
assigns — but in real browsers it is a read-only accessor that is updated BY
the browser before the event fires. A subagent who builds a stub where the
test sets `document.visibilityState = 'visible'` and then dispatches the
event will pass even if the production code reads `ev.target.visibilityState`
(which is legal) or checks `document.hidden` (which the stub probably does
not provide). §4.5 uses `document.visibilityState !== 'visible'` — the test
must verify this exact predicate under a mock that behaves like a real
browser, not a stub that happens to have the property set.
**Proposed fix:** (a) mandate `jsdom` as the DOM for `tests/wake-lock/` — it
is a Node dependency (~few MB), but it implements the correct
`document.hidden` / `visibilityState` semantics and synthetic event
dispatch. §8 says "no other new dependencies" — that constraint is the
wrong optimization here. Alternative: (b) document the exact stub contract
required in §6.2 with a reference implementation so all 12 tests start from
the same fixture, and add a test that asserts the stub matches real browser
semantics (`document.hidden === (document.visibilityState !== 'visible')`).

### F3.4 — No test for the user-gesture grace window — the most likely production failure
**Severity:** MUST-FIX
**Issue:** The spec repeatedly stresses that `WakeLock.acquire()` must be
called synchronously in the click handler. None of the 12 JS unit tests
assert this. It cannot be tested with a navigator.wakeLock mock because the
mock has no concept of "gesture grace window." But the structural invariant
— that between the button click handler entry and `WakeLock.acquire()` there
is no await, no Promise chain, no timer — is the thing most likely to be
accidentally broken by a future refactor.
**Proposed fix:** F3.1's parser-based static test covers it. Alternatively a
Playwright test that clicks the Start button with a mocked `wakeLock.request`
that records the time delta from click to request — asserts delta < 50 ms.
Playwright is already mentioned in §Testing / TODO, so this is incremental.

### F3.5 — Flaky time-dependent test: `test_arrival_delay_keeps_lock_until_stop`
**Severity:** SHOULD-FIX
**Issue:** §6.2 prescribes `test_arrival_delay_keeps_lock_until_stop` for
§5.11 (3-second arrival delay). The spec does not say whether to use real
timers or fake timers. A subagent who reaches for `await new Promise(r => setTimeout(r, 3100))`
will produce a test that wall-clock-sleeps 3.1 seconds per run and flakes
under CI load. Node's `node:test` has `t.mock.timers` (since Node 20.4) —
the spec should mandate it. Also: §6.2 targets < 100 ms per test and < 2 s
for the suite; a real-timer 3 s sleep blows that budget by 50 %.
**Proposed fix:** §6.2 must say "use `t.mock.timers.enable({ apis: ['setTimeout'] })`
and `t.mock.timers.tick(3000)`." Document the pattern once at the top of the
test file.

### F3.6 — No negative-invariant tests
**Severity:** SHOULD-FIX
**Issue:** Every named test in §6.2 asserts a positive outcome ("NoSleep is
called", "re-acquisition is attempted", "sentinel.release is called"). None
assert the complement: `sentinel.release` is NOT called while tab is still
visible; `NoSleep.enable` is NOT called when `navigator.wakeLock` succeeded;
`WakeLock.acquire` is NOT called when `nav-active` class is toggled by a
non-nav-ui source (§5.13 test is there but as worded it asserts acquire
wasn't called — verify this one explicitly). Without negative tests, a
subagent who writes an over-eager `acquire()` that fires both paths is
green.
**Proposed fix:** for each named test, add a paired `call_count` assertion
on the opposite mock (e.g., when primary succeeds, assert
`NoSleep.prototype.enable.callCount === 0`). This is a five-minute addition
per test, high value.

### F3.7 — Mock fidelity is under-specified — subagent mocks will drift
**Severity:** MUST-FIX
**Issue:** The spec tells subagents to mock `navigator.wakeLock.request`
but does not specify the shape of the returned sentinel. The W3C contract:
`request('screen')` returns `Promise<WakeLockSentinel>` where
`WakeLockSentinel` has `released: boolean`, `type: 'screen'`, `release():
Promise<void>`, and inherits from `EventTarget` (supports `addEventListener('release', ...)`).
A hand-rolled mock that returns `{ release: () => {} }` will pass
`test_primary_unsupported_falls_to_nosleep` but the production code uses
`sentinel.addEventListener('release', ...)` at §4.3 — which will throw
`TypeError` if the mock is a plain object. The test might pass anyway
because the throw is swallowed by the outer try/catch, then the code falls
through to NoSleep — producing the APPEARANCE of correctness for the wrong
reason.
**Proposed fix:** §6.2 must specify, verbatim, the sentinel mock factory:

```js
function makeSentinelMock() {
  const listeners = {};
  return {
    type: 'screen',
    released: false,
    release: t.mock.fn(() => { this.released = true; return Promise.resolve(); }),
    addEventListener: (name, cb) => { (listeners[name] ||= []).push(cb); },
    removeEventListener: (name, cb) => { /* ... */ },
    _fire: (name) => { (listeners[name] || []).forEach(fn => fn()); },
  };
}
```

Also specify the `NoSleep` mock shape (`enable(): Promise<void>`,
`disable(): void`, constructor is `new`-able).

### F3.8 — No assertion that the screen actually stays on
**Severity:** NICE-TO-HAVE (acknowledged) but CI-gap is MUST-FIX
**Issue:** The ultimate behavioral assertion — "the OS does not lock the
screen" — is only in §6.3 manual checklist. That is unavoidable for the
final behavioral test, but the *intermediate* proxy is testable in
Playwright: after `WakeLock.acquire()`, `navigator.wakeLock` should hold
exactly one active sentinel whose `released === false`. Playwright running
against a real Chromium in headless mode gives you a real `navigator.wakeLock`
(in Secure Context via `localhost`). This is the closest-to-behavior assertion
available without a physical phone.
**Proposed fix:** add one Playwright test to §6 that (a) loads the frontend
on `http://localhost`, (b) clicks Start-Nav, (c) evaluates
`await navigator.wakeLock.request('screen').then(s => s.released)` and
asserts Chromium granted the lock. Not a full screen-stays-on proof, but a
real-browser smoke test that passes CI. Manual §6.3 stays.

### F3.9 — Manual field acceptance has no regression story
**Severity:** MUST-FIX
**Issue:** §6.3 is five items. There is no documented procedure for running
them when the feature breaks three months from now. No test harness, no
"bring a phone and retest after every PR touching nav-ui.js or wake-lock.js"
instruction. If a future refactor of `nav-ui.js:160` moves the `acquire()`
call past an await and static tests don't catch it (F3.1), the next time
anyone discovers the regression is when a beta tester reports their phone
locked during nav on a drive. A feature documented as safety-of-life
deserves at least a documented trigger ("any PR touching these files
requires Cameron to re-run §6.3 manually, and the commit message must
reference the phone model tested").
**Proposed fix:** add a CODEOWNERS-style gate or a pre-merge checklist line
in CONTRIBUTING.md: "Changes to `frontend/wake-lock.js`, `frontend/nav-ui.js`
integration points, or `frontend/vendor/nosleep.min.js` require a §6.3
checklist replay and attaching screenshot/video evidence to the PR."

### F3.10 — No battery / performance bound
**Severity:** SHOULD-FIX
**Issue:** NoSleep's `<video>` loop has measurable CPU + battery cost. On
a two-hour drive the fallback path will drain the battery measurably faster
than the primary. There is no spec'd bound ("X% extra drain over baseline
nav") and no test (synthetic or manual) to measure it. §5.16 acknowledges
Low Power Mode but the reverse — a tester on a full battery who sees 30%
extra drain and blames nav — is not modeled.
**Proposed fix:** add to §6.3 a final checklist item: "Measure battery
drain over a 30-minute nav session on NoSleep path vs primary path vs
baseline (nav off). Record the delta. If NoSleep path exceeds baseline by
more than 15%/hour, file a follow-up." Even one data point is better than
zero.

### F3.11 — `tests/wake-lock/*.test.js` collision with pytest collection
**Severity:** MUST-FIX
**Issue:** `/home/administrator/Code/geographica/tests/` is the pytest root
(confirmed: 82 test files, all `test_*.py`, `conftest.py` present). There is
no `pytest.ini` / `pyproject.toml` restricting collection. Pytest's default
`test_*.py` / `*_test.py` glob will ignore `*.test.js`, but it WILL walk
into `tests/wake-lock/` looking for Python tests, which is harmless — until
someone adds a `conftest.py` or `__init__.py` there. More importantly, the
CI command `python -m pytest tests/ -v` and the new JS command `node --test
tests/wake-lock/` now share a directory. This is a latent source of "which
tool owns which files" confusion. Pytest also exhibits "rootdir inference"
that can surprise when mixed content appears under `tests/`.
**Proposed fix:** put JS tests at `frontend/tests/wake-lock/` or
`tests-js/wake-lock/`, NOT under `tests/`. Update §6.2, §8, and §10
acceptance criteria accordingly. This is a one-word change in the spec but
prevents a whole class of tooling-confusion bugs.

### F3.12 — 17 failure modes, 12 tests — several §5 claims of "not unit-testable" are wrong
**Severity:** SHOULD-FIX
**Issue:** Inventory of §5 vs §6.2:

| §5 mode | Test in §6.2? |
|---|---|
| 5.1 undefined | yes |
| 5.2 reject | yes |
| 5.3 NoSleep missing | yes |
| 5.4 NoSleep throw | yes |
| 5.5 double acquire | yes |
| 5.6 double release | yes |
| 5.7 race | yes (partial — see F3.2) |
| 5.8 visibility | yes |
| 5.9 page unload | spec says "not unit-testable" |
| 5.10 reroute | yes |
| 5.11 arrival delay | yes |
| 5.12 explicit stop | MISSING |
| 5.13 class manipulation | yes |
| 5.14 multi-tab | spec says "out of scope" |
| 5.15 iframe | spec says "same mock as 5.2" — no separate test |
| 5.16 Low Power Mode | MISSING |
| 5.17 `<video>` singleton | yes |

Gaps: (a) **5.12 has no named test** even though it's the most common path
(user taps Stop). It may be implied by `test_acquire_idempotent` calling
release, but the spec needs an explicit `test_explicit_stop_releases_lock`.
(b) **5.16 Low Power Mode**: the spec says "§5.4 handling applies" but LPM
can reject primary AND NoSleep; testing the combined failure is worth one
test: `test_both_paths_fail_does_not_crash`. (c) **5.9 page unload** is
testable in Playwright by closing the page and polling for sentinel release
— claimed "not unit-testable" is only true for `node:test`. (d) **5.15
iframe** is listed as "same mock as 5.2" but the rejection class is
`NotAllowedError` specifically; the spec's catch-all `catch (err)` swallows
all errors equally, which is correct but untested. Add
`test_not_allowed_error_falls_to_nosleep`.
**Proposed fix:** add the three missing tests. Rename §5.9 expected
verification to "Playwright, not `node:test`." Close the spec's own audit
trail.

### F3.13 — "No regression in existing `tests/` suite" is under-specified
**Severity:** NICE-TO-HAVE
**Issue:** §10 acceptance criterion "No regression in existing `tests/` suite"
assumes the suite is Python-only today. Once JS tests live under `tests/`
(F3.11), this acceptance criterion is ambiguous — does it cover Python,
Node, or both? A subagent running only `python -m pytest tests/` misses JS
regressions. This is a process bug, not a code bug, but it is a testing
bug.
**Proposed fix:** acceptance criterion reads: "`python -m pytest tests/ -v`
AND `node --test tests/wake-lock/` (or new path per F3.11) both pass with
zero new failures or warnings."

## Summary

12 findings, 4 MUST-FIX (F3.1, F3.2, F3.7, F3.9, F3.11), 5 SHOULD-FIX, 2
NICE-TO-HAVE plus the CI-gap inside F3.8.

The two highest-impact gaps: **(1) structural tests that mistake string
presence for behavior (F3.1)**, which lets a refactor silently break the
gesture grace window — the single most likely production failure; and
**(2) mock fidelity under-specification (F3.7)**, which lets subagent tests
pass for the wrong reason. Close these two and the test suite moves from
"false confidence" to "meaningful confidence." The rest are important but
incremental.
