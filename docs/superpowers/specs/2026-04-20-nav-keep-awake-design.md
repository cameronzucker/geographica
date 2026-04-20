# Nav Keep-Awake — Design Spec

**Date:** 2026-04-20
**Scope:** Prevent mobile device screen-dim / auto-lock from silently stopping turn-by-turn navigation.
**Files:** `frontend/wake-lock.js` (new), `frontend/nav-ui.js`, `frontend/index.html`, `frontend/vendor/nosleep.min.js` (new vendored asset), `tests/test_wake_lock_static.py` (new), `tests/wake-lock/` (new, JS unit tests).
**Related:** Spec B (field-mode / Pi-as-AP) is being researched in parallel. This spec is deliberately independent — it ships regardless of Spec B's timeline.

---

## 1. Summary

On mobile devices, Geographica's navigation mode silently breaks when the phone dims its screen or auto-locks: browsers pause or heavily throttle JavaScript in backgrounded / screen-off tabs, so the GPS feed stops, the stale-GPS watchdog stops, turn-by-turn voice announcements stop firing, and reroute detection stops. A driver whose attention is on the road may not notice their phone has stopped navigating for them — a safety-of-life failure mode.

This spec specifies a keep-awake mechanism that holds the screen on for the duration of an active nav session, using the modern Screen Wake Lock API where available (Secure Context) and a universally-compatible NoSleep.js fallback where not. The mechanism is fully passive — no UI indicator, no audible chime, no user interaction required. When nav ends (explicit stop, arrival auto-stop, reroute failure, page unload), the lock releases and the device resumes normal power management.

## 2. Goals & non-goals

### Goals

- G1. While navigation is active, the device screen does not auto-dim or auto-lock due to idle timeout.
- G2. Mechanism works in both `isSecureContext === true` (HTTPS, Tailscale) and `isSecureContext === false` (plain HTTP on LAN / AREDN mesh / future Pi hotspot).
- G3. Mechanism releases promptly and reliably when navigation ends via any path (explicit Stop, arrival, page unload, catastrophic error).
- G4. Mechanism is entirely silent to the driver — no visual indicator, no audible chime, no banner, no modal. The feature is self-evidencing (the screen staying on IS the evidence that it works).
- G5. Mechanism is offline-safe — no CDN, no runtime network dependency.
- G6. Mechanism survives tab-hide / tab-show transitions (phone call interrupts, home button, app switch) without the driver having to take any action.
- G7. Code lives in its own module (`frontend/wake-lock.js`), not in `nav-ui.js` or `app.js` — consistent with [docs/pitfalls/implementation-pitfalls.md](../../pitfalls/implementation-pitfalls.md) #9 (frontend module boundaries).

### Non-goals

- NG1. Keeping the screen at full brightness. We prevent dimming-to-off; we do not override the user's brightness setting.
- NG2. Preventing user-initiated screen lock (power button press). That is a legitimate user action and cannot be overridden by a web app.
- NG3. Alerting the driver when the tab is backgrounded. Audible or visual alarms during driving are rejected as hostile — the existing nav state machine self-heals via its stale-GPS watchdog ([navigation.js:683](../../../frontend/navigation.js#L683)) and off-route detector ([navigation.js:633](../../../frontend/navigation.js#L633)) when the tab returns.
- NG4. Any UI indicator that keep-awake is active. Rejected in brainstorm — redundant with the evidence the screen itself provides.
- NG5. Preventing the browser spec-mandated behavior of releasing the Wake Lock on tab-hide. That's non-negotiable; we re-acquire on tab-show instead.
- NG6. Addressing the offline-HTTPS gating problem (Device GPS, STT). Those features remain gated on Secure Context independently. This spec is scoped to wake-lock only.
- NG7. Adding a new frontend test runner. We use Node's built-in `node:test` module for JS unit tests (zero dependencies) and Python static checks for structural invariants.

## 3. Architecture overview

Three layers, each serving a different failure mode.

```
   ┌──────────────────────────────────────────────────────────────┐
   │  frontend/nav-ui.js startNavigation() / stopNavigation()     │
   │  — only the nav state machine knows when to call these —     │
   └──────────────┬─────────────────────────────┬─────────────────┘
                  │ acquire()                   │ release()
                  ▼                             ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  frontend/wake-lock.js (new)                                 │
   │  - Owns: shouldBeActive flag, wakeLockSentinel, noSleep inst │
   │  - Attempts: navigator.wakeLock (primary)                    │
   │  - Falls through to: NoSleep.js (fallback)                   │
   │  - Re-acquires on visibilitychange when shouldBeActive       │
   └──────────────┬─────────────────────────────┬─────────────────┘
                  │                             │
                  ▼ primary                     ▼ fallback
   ┌──────────────────────────┐    ┌──────────────────────────┐
   │ navigator.wakeLock       │    │ NoSleep.js (vendored)    │
   │ ('screen')               │    │ silent-video autoplay    │
   │ Secure Context only      │    │ works on HTTP            │
   └──────────────────────────┘    └──────────────────────────┘
```

Keep-awake is a property of the nav state, not a feature the user opts into. Nav on → screen stays awake. Nav off → screen resumes its normal behavior.

## 4. Design details

### 4.1 Primary: Screen Wake Lock API

```js
// Inside wake-lock.js
async function requestPrimary() {
  if (!('wakeLock' in navigator)) return null;
  try {
    const sentinel = await navigator.wakeLock.request('screen');
    sentinel.addEventListener('release', onSentinelReleased);
    return sentinel;
  } catch (err) {
    console.warn('[wake-lock] navigator.wakeLock.request rejected', err);
    return null;
  }
}
```

Constraints:

- **Must be called from a user gesture context.** The `request('screen')` call is permitted only within a short grace window of a user-initiated event. `startNavigation()` is called synchronously from the Start-Nav button click handler ([nav-ui.js:141](../../../frontend/nav-ui.js#L141)). We MUST NOT await any promise between the click and the wake-lock request, or the gesture grace window closes and the request rejects.
- **Must be Secure Context.** `navigator.wakeLock` is undefined on plain HTTP. Detection is via `'wakeLock' in navigator`, which returns false on non-Secure-Context origins.
- **Auto-releases when tab hides.** Per the [W3C Screen Wake Lock spec](https://www.w3.org/TR/screen-wake-lock/), a released sentinel is signaled via the `release` event. We re-request on `visibilitychange` → `visible` if `shouldBeActive === true`.
- **Auto-releases on page unload.** No explicit cleanup needed for the navigate-away case, but we DO want to release on `stopNavigation()` for the case where nav ends but the page stays open (user returns to search, etc.).

### 4.2 Fallback: NoSleep.js

NoSleep.js ([github.com/richtr/NoSleep.js](https://github.com/richtr/NoSleep.js), MIT, ~3 KB minified, version 0.12.0) works by autoplaying a tiny silent `<video>` element in a loop. As long as a `<video>` is playing, iOS and Android will not dim or lock the screen, regardless of Secure Context.

```js
// Inside wake-lock.js
let noSleep = null;
function requestFallback() {
  if (!window.NoSleep) {
    console.warn('[wake-lock] NoSleep.js not loaded, no fallback available');
    return false;
  }
  if (!noSleep) noSleep = new window.NoSleep();
  try {
    noSleep.enable();      // returns a Promise; enable() must be called from a user gesture
    return true;
  } catch (err) {
    console.warn('[wake-lock] NoSleep.enable() threw', err);
    return false;
  }
}
```

Constraints:

- **Must be called from a user gesture context**, same as primary. Same pattern: synchronous within click handler.
- **Vendored, not CDN.** Per [docs/pitfalls/implementation-pitfalls.md](../../pitfalls/implementation-pitfalls.md) #6 (offline-first). File: `frontend/vendor/nosleep.min.js`. Script tag added to `frontend/index.html` BEFORE `nav-ui.js` so `window.NoSleep` is defined at nav-ui.js load time.
- **Low Power Mode on iOS disables `<video>` autoplay.** The fallback becomes a no-op. This degradation is acceptable — in Low Power Mode, the user has explicitly prioritized battery over features, and the nav engine's dead-reckoning still keeps state sensible. Documented in §5 "Failure modes."
- **NoSleep is instantiated lazily** (on first `enable()` call), not at module load. This avoids injecting a `<video>` element into DOM for users who never start nav.

### 4.3 Progressive enhancement + visibility handling

The public API of `wake-lock.js`:

```js
// Call from nav-ui.js startNavigation() — synchronously, no await between click and this call
WakeLock.acquire();

// Call from nav-ui.js stopNavigation() — safe to call even if never acquired
WakeLock.release();

// Diagnostic — returns 'wakelock' | 'nosleep' | 'none' | 'idle'
WakeLock.status();
```

The module's internal state machine:

```
        ┌──────────────────────────────────────────┐
        │  shouldBeActive (boolean)                │
        │  wakeLockSentinel (object | null)        │
        │  noSleepActive (boolean)                 │
        └──────────────────────────────────────────┘

       acquire()
         │
         ▼
       shouldBeActive = true
         │
         ├─── navigator.wakeLock available? ──yes──► request('screen')
         │                                              │
         │                                              ├─ success → sentinel held, done
         │                                              └─ reject → fall to NoSleep
         │
         └─── no / rejected ──► noSleep.enable()
                                    │
                                    ├─ success → noSleepActive = true, done
                                    └─ error → log warning, no further action


       release()
         │
         ▼
       shouldBeActive = false
         │
         ├─── wakeLockSentinel ? → sentinel.release() (awaited, errors swallowed)
         └─── noSleepActive ? → noSleep.disable()


       visibilitychange event (listener attached at module load, never detached)
         │
         ▼
       if shouldBeActive AND document.visibilityState === 'visible':
         if wakeLockSentinel === null AND 'wakeLock' in navigator:
           request('screen') again  ← browser released it on hide; re-acquire on show
         if noSleepActive AND !document.querySelector('video').currentTime advanced:
           noSleep.enable() again  ← may be a no-op or may re-kick the video
```

**Key invariant:** `shouldBeActive` is the *target* state. The actual lock state (sentinel existence, NoSleep active) is *observed* state. They can diverge briefly (lock released by browser, not yet re-acquired) without the driver noticing, because the re-acquisition is automatic on visibility return.

**Concrete `acquire()` implementation** (canonical — the subagent MUST follow this structure to correctly handle the race in §5.7):

```js
async function acquire() {
  // Idempotency: already acquired, nothing to do.
  if (shouldBeActive && wakeLockSentinel) return;
  shouldBeActive = true;

  // Try primary path. Note: no await between shouldBeActive = true and the request call,
  // so the user-gesture grace window is preserved.
  if ('wakeLock' in navigator) {
    try {
      const sentinel = await navigator.wakeLock.request('screen');
      if (!shouldBeActive) {
        // Race (§5.7): release() was called while the request was in flight.
        // The request resolved after the intent flipped to released. Discard the sentinel.
        sentinel.release().catch(function () {});
        return;
      }
      wakeLockSentinel = sentinel;
      sentinel.addEventListener('release', function () {
        // Browser released the lock (e.g., tab hidden). Clear our reference; visibilitychange
        // handler will re-acquire when the tab returns if shouldBeActive is still true.
        wakeLockSentinel = null;
      });
      return;
    } catch (err) {
      console.warn('[wake-lock] navigator.wakeLock.request rejected', err);
      // Fall through to NoSleep fallback.
    }
  }

  // Fallback path. Check shouldBeActive again in case release() fired during the try block.
  if (!shouldBeActive) return;
  if (!window.NoSleep) {
    console.warn('[wake-lock] NoSleep.js not loaded, no fallback available');
    return;
  }
  if (!noSleep) noSleep = new window.NoSleep();
  try {
    noSleep.enable();
    noSleepActive = true;
  } catch (err) {
    console.warn('[wake-lock] NoSleep.enable() threw', err);
  }
}
```

**Concrete `release()` implementation:**

```js
function release() {
  shouldBeActive = false;
  if (wakeLockSentinel) {
    wakeLockSentinel.release().catch(function () {});
    wakeLockSentinel = null;
  }
  if (noSleepActive && noSleep) {
    try { noSleep.disable(); } catch (err) { /* swallow */ }
    noSleepActive = false;
  }
}
```

### 4.4 Integration points (`nav-ui.js`)

Two call sites, both already well-defined in the existing nav-ui.js structure:

**At [nav-ui.js:160](../../../frontend/nav-ui.js#L160), immediately after `active = true; document.body.classList.add('nav-active');`:**

```js
active = true;
document.body.classList.add('nav-active');

// NEW: Acquire wake-lock synchronously within the user-gesture grace window.
// Must be called BEFORE any awaited promise or setTimeout/setInterval.
WakeLock.acquire();
```

**At [nav-ui.js:199](../../../frontend/nav-ui.js#L199), inside `stopNavigation()`, immediately after `document.body.classList.remove('nav-active');`:**

```js
document.body.classList.remove('nav-active');

// NEW: Release wake-lock. Safe to call unconditionally.
WakeLock.release();
```

**Why the class-toggle is the hook and not a new callback:** existing nav hook points are the class additions/removals, which already fire exactly once per nav session. Piggybacking keeps the call graph simple and ensures we never miss a release.

**Do NOT:**
- Hook into `nav.onArrival()`, `nav.onReroute()`, or any engine-level callbacks. The release contract is tied to nav-UI lifecycle, not engine internals.
- Add a call in `primeSpeech()`, `startGPSFeed()`, or any other sub-operation of `startNavigation()`. The acquire call must be synchronous within the click handler's grace window.
- Wrap the acquire call in a `try/catch` at the call site. Error handling lives inside `wake-lock.js` so the call site stays clean.

### 4.5 Visibility listener attachment

Attached at module load time, never detached:

```js
document.addEventListener('visibilitychange', function () {
  if (!shouldBeActive) return;                            // no nav active; ignore
  if (document.visibilityState !== 'visible') return;     // tab going hidden; browser handles release

  // Tab came back visible. Re-acquire if the sentinel was released by the browser.
  if ('wakeLock' in navigator && !wakeLockSentinel) {
    requestPrimary().then(function (s) { wakeLockSentinel = s; });
  }
  if (noSleepActive && noSleep) {
    // NoSleep.js: its own videoplay loop usually survives hide/show, but re-kick defensively.
    noSleep.enable().catch(function () { /* swallow */ });
  }
});
```

**Why attach at module load, not at acquire-time:** the listener is idempotent and cheap when `shouldBeActive === false` (single boolean check + early return). Attaching/detaching adds a failure mode (detach-on-release racing with a visibilitychange event) with no benefit.

### 4.6 Module layout

`frontend/wake-lock.js` — self-contained, namespace-exported as `window.WakeLock`. Pattern follows existing `window.GeographicaNav` / `window.GeographicaSearch` pattern in nav-ui.js. No ES modules, no build step.

```js
(function () {
  'use strict';

  var shouldBeActive = false;
  var wakeLockSentinel = null;
  var noSleep = null;
  var noSleepActive = false;

  async function acquire() { /* ... */ }
  function release() { /* ... */ }
  function status() { /* ... */ }

  // Visibility listener attached once on first load.
  document.addEventListener('visibilitychange', /* ... */);

  window.WakeLock = { acquire: acquire, release: release, status: status };
})();
```

`frontend/index.html` — script tags in order:

```html
<script src="vendor/nosleep.min.js"></script>
<script src="wake-lock.js"></script>
<!-- existing: -->
<script src="navigation.js"></script>
<script src="nav-ui.js"></script>
```

NoSleep must load before wake-lock.js so `window.NoSleep` is available at module init.

## 5. Failure modes and edge cases

For each, the expected behavior is specified precisely so subagents writing tests don't have to guess.

### 5.1 `navigator.wakeLock` undefined (HTTP origin, old browser)
Detection: `!('wakeLock' in navigator)`.
Behavior: `requestPrimary()` returns `null` immediately. Fall through to NoSleep.
Test: mock `navigator` without `wakeLock` property; assert `acquire()` calls NoSleep.

### 5.2 `navigator.wakeLock.request()` rejects
Causes: permissions policy (iframe), Low Power Mode on some browsers, tab already hidden at request time.
Behavior: caught `try/catch`, `console.warn`, fall through to NoSleep.
Test: mock `request` to throw; assert NoSleep path runs.

### 5.3 NoSleep.js not loaded (vendored file missing / 404)
Detection: `!window.NoSleep` at acquire-time.
Behavior: `console.warn`, `acquire()` completes silently with `shouldBeActive === true` but no actual lock. Next nav start or visibility return will retry, same outcome. No crash.
Test: leave `window.NoSleep` undefined; assert `acquire()` does not throw and logs warning.

### 5.4 NoSleep.js `enable()` throws or rejects
Causes: autoplay policy (iOS Low Power Mode, Safari's autoplay restrictions on new tabs), audio context creation fails.
Behavior: caught `try/catch`, `console.warn`, no further recovery. `shouldBeActive` remains `true` but neither mechanism is active. **Degraded mode**: the driver's phone will auto-dim on normal idle timeout. The nav engine itself continues to work as-is when the tab is visible.
Test: mock `NoSleep.enable()` to throw; assert no crash, warning logged.

### 5.5 `startNavigation()` called twice without intervening `stopNavigation()`
Behavior: `acquire()` is idempotent — if `shouldBeActive === true && wakeLockSentinel !== null`, do nothing. If `shouldBeActive === true && wakeLockSentinel === null` (e.g., released by browser), attempt to re-acquire. Never double-acquire.
Test: call `acquire()` twice; assert only one `request()` call to the mock.

### 5.6 `stopNavigation()` called before `startNavigation()` or after a previous `stopNavigation()`
Behavior: `release()` is idempotent — sets `shouldBeActive = false`, releases the sentinel if present, disables NoSleep if active. Safe to call on a fresh module load with no prior acquire.
Test: call `release()` with no prior `acquire()`; assert no error, `status()` returns `'idle'`.

### 5.7 `stopNavigation()` called while `acquire()` is still awaiting a rejected promise
Race: user taps Start → `request('screen')` is in flight → user taps Stop before the promise resolves/rejects → `shouldBeActive` goes true then false → promise eventually resolves with a sentinel.
Behavior: after `request('screen')` resolves, check `shouldBeActive`. If false, immediately release the sentinel and discard. Prevents orphaned locks.
Test: inject a delayed-resolve `request()` mock; call `acquire()` then `release()` before the mock resolves; assert the returned sentinel's `.release()` is called exactly once.

### 5.8 Tab hidden during active nav (phone call, app switch, home button)
Behavior: browser auto-releases the Wake Lock sentinel; `release` event fires on sentinel; our handler sets `wakeLockSentinel = null` but does NOT change `shouldBeActive`. NoSleep's `<video>` may be paused by browser.
On tab return (`visibilitychange` → `visible`): re-request primary if supported; re-kick NoSleep if active.
Test: simulate `visibilitychange` with `visibilityState='hidden'` then `'visible'`; assert re-acquisition attempt.

### 5.9 Page unload during active nav
Behavior: browser releases the Wake Lock automatically (spec-mandated). No explicit cleanup needed. NoSleep's `<video>` is destroyed with the DOM.
Test: not unit-testable; verified by the mechanism's construction.

### 5.10 Nav engine reports off-route, reroute in progress (existing banner)
Behavior: wake-lock unaffected. Lock remains held throughout the reroute window (up to 10 s per [navigation.js:633](../../../frontend/navigation.js#L633)).
Test: assert acquire → simulate reroute callback → assert lock still held.

### 5.11 Arrival → 3-second auto-stop delay
Behavior: wake-lock unaffected during the 3-second delay. `release()` is called when `stopNavigation()` fires after the delay. Screen stays on throughout the driver's parking / confirmation window.
Test: assert acquire → simulate `onArrival()` → wait 3s → assert `stopNavigation` called → assert release called.

### 5.12 User explicitly taps Stop button
Behavior: `stopNavigation()` → `release()`. Standard path.
Test: click Stop → assert release.

### 5.13 `nav-active` class manipulated directly by external code (third party or malicious)
Behavior: class toggle is NOT an event — our integration hooks fire from the specific nav-ui.js call sites, not from class-change observers. Defense: keep the hooks at `startNavigation` / `stopNavigation` exactly, not via `MutationObserver`.
Test: flip `nav-active` class directly without calling `startNavigation`; assert `acquire()` is NOT called.

### 5.14 Multiple tabs of Geographica open simultaneously, each with nav active
Behavior: each tab holds its own independent wake-lock. Browser permits this (locks are per-document). Acceptable — if user has two nav tabs, they deserve two locks.
Test: out of scope for unit tests; manual verification.

### 5.15 Browser permissions policy / iframe embedding blocks `wakeLock`
Behavior: `request()` rejects with `NotAllowedError`. Falls through to NoSleep as in §5.2.
Test: same mock as §5.2.

### 5.16 Low Power Mode on iOS
Behavior: `navigator.wakeLock` may work or may reject; `<video>` autoplay (NoSleep) is blocked. Worst-case: both paths fail. §5.4 handling applies.
**Documented degradation**, not a bug to fix. User who enabled Low Power Mode prioritized battery.

### 5.17 NoSleep's `<video>` element lingers in DOM across nav sessions
Behavior: NoSleep only adds the `<video>` once (idempotent init). `disable()` pauses the video but leaves the element. This is NoSleep's design. Not a memory leak in practice.
Test: call enable/disable multiple times; assert only one `<video>` element exists with `id` matching NoSleep's selector.

## 6. Testing strategy

Three layers. No new test runner introduced — we use what's already here plus Node's built-in test module.

### 6.1 Python static tests (`tests/test_wake_lock_static.py`)

These verify structural invariants — the things that break if someone deletes a file or forgets a script tag.

- `test_nosleep_js_is_vendored` — file exists at `frontend/vendor/nosleep.min.js`, size > 0, contains the literal string "NoSleep" somewhere.
- `test_wake_lock_js_exists` — file exists at `frontend/wake-lock.js`, exports `window.WakeLock`.
- `test_index_html_loads_scripts_in_correct_order` — parse `index.html`, find NoSleep script tag before wake-lock.js script tag before nav-ui.js script tag.
- `test_nav_ui_calls_wake_lock_acquire` — grep `frontend/nav-ui.js` for `WakeLock.acquire()`; assert present, and assert it appears within `startNavigation()`.
- `test_nav_ui_calls_wake_lock_release` — grep `frontend/nav-ui.js` for `WakeLock.release()`; assert present in `stopNavigation()`.
- `test_no_cdn_urls_for_nosleep` — no `unpkg.com`, `cdn.jsdelivr.net`, or `cdnjs.cloudflare.com` references for nosleep; must be offline-first (pitfall #6).

### 6.2 JS unit tests (`tests/wake-lock/` using `node:test`)

Node's built-in test runner, no external deps. Each test loads `wake-lock.js` into a constructed global scope (jsdom or a hand-rolled stub is fine; the module uses only `document`, `window`, `navigator`, and `console`).

One test file per failure-mode section in §5. Each test:
1. Constructs a global with specific mocks (`navigator.wakeLock`, `window.NoSleep`, `document`).
2. Loads wake-lock.js via `vm.runInNewContext` or similar.
3. Calls acquire / release / dispatches visibilitychange.
4. Asserts on mock call counts and returned values.

Named tests (per §5 above):
- `test_primary_unsupported_falls_to_nosleep` (5.1)
- `test_primary_reject_falls_to_nosleep` (5.2)
- `test_nosleep_missing_logs_warning` (5.3)
- `test_nosleep_enable_throw_logs_warning` (5.4)
- `test_acquire_idempotent` (5.5)
- `test_release_before_acquire_noop` (5.6)
- `test_release_during_pending_acquire_releases_sentinel` (5.7)
- `test_visibility_hidden_then_visible_reacquires` (5.8)
- `test_reroute_keeps_lock` (5.10)
- `test_arrival_delay_keeps_lock_until_stop` (5.11)
- `test_class_manipulation_does_not_acquire` (5.13)
- `test_nosleep_video_is_singleton` (5.17)

Target: each test runs in < 100 ms. Total suite < 2 s.

### 6.3 Manual field acceptance

Cannot be automated cleanly for this class of feature. Acceptance checklist, to be run on Cameron's primary Android phone and any available iPhone:

1. Open Geographica over Tailscale (HTTPS). Start nav to a nearby destination. Set phone down without interacting. Observe: screen stays on until nav ends.
2. Open Geographica over HTTP (LAN or AREDN). Start nav. Set phone down. Observe: screen stays on (via NoSleep fallback).
3. Start nav over HTTPS. Receive a phone call (or simulate via another device). Answer and end the call. Observe: returning to Geographica, screen stays on and nav continues; no intervention required.
4. Start nav, let arrive at destination. Observe: arrival banner shows for 3 s with screen still on; after auto-stop, screen resumes normal auto-dim.
5. Start nav in iOS Low Power Mode. Verify: nav engine continues to run when tab is visible; screen may dim on normal idle (expected degradation per §5.16). No crashes, no console errors.

## 7. Pitfalls addressed

Cross-reference to `docs/pitfalls/`.

| Pitfall | How this spec addresses it |
|---------|----------------------------|
| [implementation-pitfalls.md](../../pitfalls/implementation-pitfalls.md) #5 (HTTPS requirement for browser APIs) | Dual-path design: `navigator.wakeLock` on Secure Context, NoSleep.js fallback on HTTP. Spec explicitly documents which APIs work on which transport. |
| [implementation-pitfalls.md](../../pitfalls/implementation-pitfalls.md) #6 (Offline-first design) | NoSleep.js is vendored into `frontend/vendor/`, not loaded from CDN. Python test `test_no_cdn_urls_for_nosleep` enforces this. |
| [implementation-pitfalls.md](../../pitfalls/implementation-pitfalls.md) #9 (Frontend module boundaries) | New code lives in `frontend/wake-lock.js`, not added to `app.js` or `nav-ui.js`. nav-ui.js gets exactly two new one-line calls. |
| [testing-pitfalls.md](../../pitfalls/testing-pitfalls.md) #9 (Unrecoverable async state) | `shouldBeActive` is the target state, kept separate from observed lock state. The `release()`-during-pending-`acquire()` race (§5.7) is explicitly handled and tested; lock cannot become orphaned. |
| [testing-pitfalls.md](../../pitfalls/testing-pitfalls.md) #10 (JS truthiness for numeric zero) | Sentinel state uses explicit `null` checks (`wakeLockSentinel !== null`), not `||`. |
| [testing-pitfalls.md](../../pitfalls/testing-pitfalls.md) #11 (Duplicated logic across modules) | The wake-lock module is the only authority on lock state. nav-ui.js does not mirror or track lock state. |

## 8. Dependencies and vendored artifacts

- **NoSleep.js v0.12.0** (MIT licensed). Source: [https://github.com/richtr/NoSleep.js/releases/tag/v0.12.0](https://github.com/richtr/NoSleep.js/releases/tag/v0.12.0). Size: 3.1 KB minified. File: `frontend/vendor/nosleep.min.js`. License notice preserved at top of file.
- **Node.js ≥ 18** for JS unit tests in `tests/wake-lock/` via the built-in `node:test` module (stable since Node 20; experimental in 18–19). This project's dev Pi is on Node v20.19.2, confirmed at spec time. CI and LXD harness images must provide Node ≥ 18.
- **No other new dependencies.**

## 9. Out of scope / deferred

- OS1. Spec B (field-mode / Pi-as-AP). Research in flight; separate spec when ready.
- OS2. Offline-HTTPS story generally (CA install, nginx multi-listener). Belongs to Spec B.
- OS3. Backgrounding diagnostics telemetry. Console warnings are sufficient for beta-tester debugging today. A structured debug overlay or remote telemetry channel is a future enhancement.
- OS4. Voice TTS survival under tab throttling. Known concern that `speechSynthesis.speak()` utterances queued while the tab is hidden may be dropped or delayed by some browsers. Wake-lock minimizes tab-hide scenarios but does not prevent them. Monitor as a regression after this ships; file follow-up if observed in field tests.

## 10. Acceptance criteria (checklist)

Ship condition, all must be true:

- [ ] `frontend/vendor/nosleep.min.js` vendored (v0.12.0, MIT license preserved).
- [ ] `frontend/wake-lock.js` implements the public API (acquire/release/status) and the state machine described in §4.3.
- [ ] `frontend/index.html` loads `nosleep.min.js` before `wake-lock.js` before `nav-ui.js`.
- [ ] `nav-ui.js` calls `WakeLock.acquire()` inside `startNavigation()`, on the line immediately following `document.body.classList.add('nav-active')`, synchronously (no `await`, no `setTimeout`) within the user-gesture path.
- [ ] `nav-ui.js` calls `WakeLock.release()` inside `stopNavigation()`, on the line immediately following `document.body.classList.remove('nav-active')`.
- [ ] `tests/test_wake_lock_static.py` passes locally (6 tests per §6.1).
- [ ] `tests/wake-lock/*.test.js` passes under `node --test tests/wake-lock/` (12 tests per §6.2).
- [ ] Manual field acceptance checklist (§6.3) completed on at least one Android phone.
- [ ] No regression in existing `tests/` suite.
- [ ] No new console.error output during normal nav operation on HTTPS or HTTP.

## 11. Open questions

None as of spec writing. If adversarial review surfaces any, they'll be added here before handoff to `writing-plans`.

---

## Appendix A — Why NoSleep.js v0.12.0 specifically

v0.12.0 (May 2022) is the current stable release. The last update added iOS 15 compatibility. Earlier versions (v0.9.x) have documented issues with iOS Safari's stricter autoplay policy. No v1.0 has been released; the project is in "done, minor maintenance only" mode.

The file is small enough (~3 KB) that we don't need a package manager; direct vendoring is simpler and matches the existing `frontend/vendor/` pattern for `dompurify`, `jszip`, `togeojson`, and `maplibre-gl`.

## Appendix B — Why not `'video'` wake lock type?

The Screen Wake Lock spec defined only `'screen'` in the current Level 1 spec. A `'system'` type was proposed but deprecated. A `'video'` type was never standardized. Use `'screen'` and only `'screen'`.

## Appendix C — Why not a `navigator.keepAlive` / `Battery` gating?

Some tutorials suggest checking `navigator.getBattery()` and skipping wake-lock if the device is on low battery. This would defeat the feature's purpose — a driver in the field may be on 20 % battery and still need nav. Do not gate wake-lock on battery state. The user chose to start nav; trust them.
