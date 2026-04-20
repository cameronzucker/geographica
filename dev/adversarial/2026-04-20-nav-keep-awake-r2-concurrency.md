---
round: 2
angle: Concurrency and race conditions
reviewer: general-purpose
date: 2026-04-20
---

# Round 2 — Concurrency and races

The spec claims in §4.3 and the Pitfall table row for testing-pitfalls #9 that "The `release()`-during-pending-`acquire()` race is explicitly handled and tested; lock cannot become orphaned." That claim is too strong. §5.7 covers exactly one interleaving (Start → Stop while primary request is in flight and succeeds). The state machine has at least eight additional interleavings it does not handle. Below are the findings I can substantiate against the `§4.3` canonical code as written.

## Findings

### F2.1 — Start → Stop → Start while original primary `request('screen')` is still in flight resurrects the old sentinel and orphans it

**Severity:** MUST-FIX
**Scenario:**
1. Actor A (click): `acquire()` is called. `shouldBeActive = true`. `navigator.wakeLock.request('screen')` is invoked; a Promise P1 is pending.
2. Actor A (click): `release()` is called. `shouldBeActive = false`. `wakeLockSentinel` is still `null` (P1 has not resolved), so the `if (wakeLockSentinel)` branch in `release()` does nothing.
3. Actor A (click): `acquire()` is called again. Idempotency check `shouldBeActive && wakeLockSentinel` is `false && null` → skip. We set `shouldBeActive = true` and issue `navigator.wakeLock.request('screen')` → Promise P2 pending.
4. Browser: P1 resolves with sentinel S1.
5. `acquire()` (first invocation, resumed): checks `if (!shouldBeActive)` → `shouldBeActive` is `true` (we just re-acquired), so the race guard does NOT fire. `wakeLockSentinel = S1`. Listener attached.
6. Browser: P2 resolves with sentinel S2.
7. `acquire()` (second invocation, resumed): checks `if (!shouldBeActive)` → `true`. `wakeLockSentinel = S2`. We have silently overwritten S1. S1 is now orphaned — it is held by the browser but no JS reference exists to call `.release()` on it.

**Current spec behavior (§4.3 as written):** the race guard in §5.7 is `if (!shouldBeActive) release the sentinel`. It does not detect "another acquire started while I was in flight." There is no generation counter / token / abort signal.

**Problem:** two concurrent in-flight `request('screen')` calls are possible. The later assignment wins the `wakeLockSentinel` slot; the earlier sentinel is leaked until the page unloads. Per the W3C spec, multiple screen locks on the same document are permitted but each must be released independently. The driver will eventually see the lock stick around even after `release()` because only S2 gets released on the next `stopNavigation()` — S1 persists until tab-close or navigation.

**Proposed fix:** introduce a monotonic generation counter. Each call to `acquire()` increments it and captures its own value in a local; on resume, if the local does not match the current generation, treat the resolved sentinel as stale and release+discard it.

```js
var acquireGeneration = 0;
async function acquire() {
  if (shouldBeActive && wakeLockSentinel) return;
  shouldBeActive = true;
  var myGen = ++acquireGeneration;
  if ('wakeLock' in navigator) {
    try {
      const sentinel = await navigator.wakeLock.request('screen');
      if (!shouldBeActive || myGen !== acquireGeneration) {
        sentinel.release().catch(function () {});
        return;
      }
      wakeLockSentinel = sentinel;
      sentinel.addEventListener('release', function () { wakeLockSentinel = null; });
      return;
    } catch (err) { /* fall through */ }
  }
  if (!shouldBeActive || myGen !== acquireGeneration) return;
  // ... NoSleep path, also gated by myGen
}
```

### F2.2 — `release()` called during pending acquire does not await the in-flight Promise; caller assumes cleanup completed

**Severity:** MUST-FIX
**Scenario:**
1. `acquire()` invoked. `navigator.wakeLock.request('screen')` Promise P is pending.
2. `stopNavigation()` fires (arrival auto-stop, 3-second timer). `release()` runs synchronously: `shouldBeActive = false`, sentinel is null → no-op, `noSleepActive` false → no-op. `release()` returns.
3. Promise P resolves with sentinel S.
4. `acquire()` continuation checks `shouldBeActive` → false → calls `S.release().catch()`. This is ASYNC — an unawaited Promise.
5. `stopNavigation()` continues, might trigger `startNavigation()` soon after (user taps Start again quickly), which can interleave with step 4 — see F2.1.

**Current spec behavior:** §4.3 releases the sentinel in the race guard but never awaits. The caller of `release()` has no way to know the cleanup is pending.

**Problem:** `release()` returns synchronously as if it's done, but there may be work still in flight. Any test that asserts `acquire-then-release → no held locks` immediately after `release()` returns can spuriously pass while an orphan sentinel is still being cleaned asynchronously. More importantly for production: if the page is reloaded within the grace window (user panics and hits refresh), the browser may hold the sentinel across unload until GC'd. Low impact in practice but it falsifies the spec's claim "lock cannot become orphaned."

**Proposed fix:** `release()` should return a Promise. Document it as async. Subagent test §5.7 should `await release()` and THEN assert. Alternatively, keep a `pendingAcquire` Promise reference and have `release()` chain `.then(s => s.release())` onto it.

### F2.3 — Visibility handler `requestPrimary().then(s => wakeLockSentinel = s)` has no race guard

**Severity:** MUST-FIX
**Scenario (§4.5 code):**
1. Tab hidden. Browser releases S1. `release` event handler clears `wakeLockSentinel = null`. `shouldBeActive` is still `true`.
2. Tab becomes visible. Visibility handler fires: `shouldBeActive` true, `wakeLockSentinel` null → calls `requestPrimary()`. Promise Pv pending.
3. Before Pv resolves, user taps Stop. `release()` runs: `shouldBeActive = false`. No sentinel held. Returns.
4. Pv resolves with sentinel Sv. `.then(function (s) { wakeLockSentinel = s; })` fires. `wakeLockSentinel = Sv`.
5. `shouldBeActive` is now `false`, but `wakeLockSentinel = Sv` (non-null). The screen is held on forever (or until the next `acquire() → release()` pair).

**Current spec behavior:** §4.5 has no `if (!shouldBeActive)` check in its `.then()` handler. It unconditionally stores the returned sentinel.

**Problem:** same class of bug as F2.1 but via the visibility path. The spec explicitly exempts the visibility handler from §5.7-style guard. Result: orphan lock that survives `release()`.

**Proposed fix:**
```js
if ('wakeLock' in navigator && !wakeLockSentinel) {
  requestPrimary().then(function (s) {
    if (!s) return;
    if (!shouldBeActive) { s.release().catch(function () {}); return; }
    wakeLockSentinel = s;
    s.addEventListener('release', function () { wakeLockSentinel = null; });
  });
}
```
Note the spec's §4.5 snippet ALSO forgets to attach a `release` listener on the re-acquired sentinel — a separate bug: after the second hide/show cycle, the next browser-initiated release won't clear `wakeLockSentinel`, breaking idempotency in `acquire()`.

### F2.4 — `sentinel.release` event fires after our own explicit `release()` → NPE-like state because handler references `wakeLockSentinel` that was already nulled

**Severity:** SHOULD-FIX
**Scenario:**
1. `acquire()` succeeds. `wakeLockSentinel = S`. Listener attached to S: `function () { wakeLockSentinel = null; }`.
2. `release()` called. `wakeLockSentinel = null` (line-by-line: `wakeLockSentinel.release().catch(...)` then `wakeLockSentinel = null`).
3. S's release Promise resolves. W3C spec says `release` event fires on the sentinel.
4. Listener runs: `wakeLockSentinel = null`. Already null. No error, but redundant.
5. Now the user does Stop → Start → Stop cycles quickly. Each cycle attaches a new listener to a new sentinel. But the listeners from previous sentinels are still registered on old sentinels (held in closure). If the browser for some reason fires `release` on S_old AFTER a new sentinel S_new has been installed (e.g., delayed event delivery, or §5.14 multi-tab weirdness), `wakeLockSentinel = null` wipes S_new's reference, orphaning S_new.

**Current spec behavior:** listener closes over nothing; it unconditionally nulls the module-level `wakeLockSentinel`.

**Problem:** listener fires for the wrong sentinel and nulls the current one. Rare but possible under heavy tab-switching or browser oddities.

**Proposed fix:** capture the sentinel in the listener and compare:
```js
sentinel.addEventListener('release', function () {
  if (wakeLockSentinel === sentinel) wakeLockSentinel = null;
});
```

### F2.5 — Tab hides during pending `navigator.wakeLock.request('screen')`; request rejects with `NotAllowedError`, §4.3 falls through to NoSleep which cannot enable on hidden tab either, leaving `shouldBeActive = true` with no lock

**Severity:** SHOULD-FIX (documented as §5.16 degradation, but not this code path)
**Scenario:**
1. `acquire()` called. `shouldBeActive = true`. `request('screen')` invoked, Promise pending.
2. Browser: tab becomes hidden (user hit home button in the 50 ms before request resolved).
3. Per W3C, `request('screen')` now rejects with `NotAllowedError` because wake-lock can't be acquired on a hidden document.
4. §4.3 catch block: `console.warn`, fall through to NoSleep.
5. `noSleep.enable()` is called on a hidden tab. Autoplay policy rejects (NoSleep's internal `<video>.play()` Promise rejects). `enable()` may throw synchronously or return a rejected Promise — §4.3 uses `try/catch` but does NOT await, so a rejected Promise is uncaught.
6. State: `shouldBeActive = true`, `wakeLockSentinel = null`, `noSleepActive = true` (optimistically set), no actual lock held.
7. Tab becomes visible again. Visibility handler: `wakeLockSentinel` null → re-request primary, this time succeeds. Good.
8. BUT: `noSleepActive === true` from step 6, so visibility handler also calls `noSleep.enable().catch()`. Now we have BOTH primary wakelock AND NoSleep video running simultaneously. Battery drain without need; also `noSleepActive` never gets cleared on subsequent release (see F2.6).

**Current spec behavior:** §4.3 fallback path sets `noSleepActive = true` BEFORE confirming NoSleep actually enabled. It uses `try/catch` on `noSleep.enable()` which returns a Promise — the catch only catches sync throws, not async rejections. The `noSleepActive` flag diverges from actual NoSleep state.

**Problem:** (a) `noSleepActive` is set to true even on async failure; (b) both mechanisms can end up active simultaneously after a visibility cycle; (c) the "tab hid during request" case isn't in §5.

**Proposed fix:** await `noSleep.enable()` and set `noSleepActive` only on resolve. Add §5.18 covering tab-hide during pending acquire.
```js
try {
  await noSleep.enable();
  if (!shouldBeActive || myGen !== acquireGeneration) { noSleep.disable(); return; }
  noSleepActive = true;
} catch (err) { console.warn(...); /* noSleepActive stays false */ }
```

### F2.6 — `noSleepActive` is a boolean mirror of a state owned by NoSleep.js; they can desynchronize via NoSleep's internal `<video>.pause()` from the browser

**Severity:** SHOULD-FIX
**Scenario:**
1. `acquire()` → NoSleep path → `noSleepActive = true`, video playing.
2. Tab hidden. Browser pauses `<video>` (mobile browsers routinely do this). NoSleep's internal loop sees the pause.
3. Tab visible. §4.5 visibility handler: `noSleepActive && noSleep` → true → `noSleep.enable().catch()`. Unawaited Promise.
4. Meanwhile, on same event, primary path: `'wakeLock' in navigator && !wakeLockSentinel` → true → request primary. Succeeds.
5. Now: primary held, AND NoSleep video playing (because we unconditionally re-enabled in step 3).
6. `release()` called. Sentinel released. NoSleep.disable() called. All good... unless NoSleep.enable() in step 3 was still in flight — `disable()` + concurrent `enable()` in NoSleep internals can leave the `<video>` autoplaying after `disable()`. See NoSleep.js issue tracker (v0.12.0 has no internal queue for overlapping enable/disable).

**Current spec behavior:** §4.5 unconditionally calls `noSleep.enable()` on visibility return regardless of whether primary is also being re-acquired. Never calls `disable()` when primary succeeds on visibility return.

**Problem:** dual-enable leads to dual-lock; NoSleep's internal state is not guaranteed atomic across overlapping enable/disable calls; `noSleepActive` doesn't track the actual video state.

**Proposed fix:** on visibility return, re-acquire EITHER primary OR NoSleep, not both. Prefer primary if `wakeLock` is available; disable NoSleep explicitly if primary succeeds.

### F2.7 — Module loaded twice (duplicate script tag, HMR, or test harness re-import) attaches two `visibilitychange` listeners and creates two `window.WakeLock` namespaces owning independent state

**Severity:** SHOULD-FIX
**Scenario:**
1. Developer accidentally includes `<script src="wake-lock.js">` twice in index.html (or some bundler injects it twice; or a test `vm.runInNewContext` re-evaluates it).
2. Two IIFEs run. Each attaches its own `visibilitychange` listener. Each has its own `shouldBeActive` / `wakeLockSentinel` / `noSleep`.
3. `window.WakeLock` is overwritten by the second IIFE — `nav-ui.js` will call the second's `acquire`.
4. First IIFE's `shouldBeActive` is always false. First IIFE's visibility listener always early-returns — harmless.
5. BUT: if the second load happens AFTER an `acquire()` call (e.g., dynamic script insertion), the first IIFE holds `shouldBeActive = true` and a live sentinel; now `window.WakeLock.release()` calls the SECOND IIFE's release, which does nothing. Orphan lock in the first IIFE's closure, no way to release.

**Current spec behavior:** §4.6 "Visibility listener attached once on first load" is aspirational but not enforced. No idempotency guard on the IIFE.

**Problem:** duplicate load = orphan state. The spec's Python static test `test_index_html_loads_scripts_in_correct_order` doesn't check for duplicates.

**Proposed fix:** guard the IIFE body with `if (window.WakeLock) return;`. Also add a static test that asserts each script tag appears exactly once in index.html.

### F2.8 — `acquire()` idempotency check is non-atomic: `shouldBeActive && wakeLockSentinel` races with concurrent visibility-triggered re-acquire

**Severity:** SHOULD-FIX
**Scenario:**
1. Tab hidden; browser released S. `release` event fires → `wakeLockSentinel = null`. `shouldBeActive` still `true`.
2. Tab visible. Visibility handler starts `requestPrimary()`. Promise Pv pending. `wakeLockSentinel` still `null`.
3. In the same event-loop tick (before Pv resolves), user taps Start again (they thought nav stopped during the hide). `nav-ui.js` calls `WakeLock.acquire()`.
4. `acquire()` idempotency: `shouldBeActive (true) && wakeLockSentinel (null)` → `false` → proceed. `shouldBeActive = true` (already). `navigator.wakeLock.request('screen')` → Promise Pa pending.
5. Pv resolves with Sv → `wakeLockSentinel = Sv` (via §4.5's lax handler, see F2.3).
6. Pa resolves with Sa → `acquire()` continuation checks `shouldBeActive` → true → `wakeLockSentinel = Sa`. Sv orphaned.

**Current spec behavior:** two independent paths can both issue `request('screen')` without coordination. Same class as F2.1 but via visibility × user-gesture interleaving.

**Problem:** identical to F2.1 — orphan sentinel.

**Proposed fix:** the generation counter in F2.1's fix, combined with making the visibility handler participate in the same counter scheme, eliminates both F2.1 and F2.8.

### F2.9 — `release` event listener never removed; each hide/show cycle accumulates listeners on sentinels until GC'd; minor memory growth, no state bug, but violates "listener once" invariant

**Severity:** NICE-TO-HAVE
**Scenario:** 10 hide/show cycles create 10 sentinels, each with a listener. Old sentinels get GC'd eventually. No bug, but spec's §4.5 claim "single boolean check + early return, cheap" is a little misleading about total listener count in the system.

**Proposed fix:** none needed; document that listener lifetime is bounded by sentinel lifetime.

---

## Summary

**MUST-FIX: F2.1, F2.2, F2.3.** These are orphan-lock bugs that falsify the spec's Pitfalls-table claim "lock cannot become orphaned." All three stem from the same structural issue: the `§4.3` async code uses `shouldBeActive` as its only race guard, which is a one-bit state insufficient to distinguish "released then re-acquired" from "still acquiring." A monotonic generation counter is the minimal fix and resolves F2.1/F2.3/F2.8 together.

**SHOULD-FIX: F2.4, F2.5, F2.6, F2.7, F2.8.** Edge-case orphans, NoSleep/primary dual-activation, and duplicate-module hazards. None are safety-of-life, but §5's "degraded mode" hand-waving is currently covering for real bugs that would surface during field tests on unreliable mobile browsers.

**NICE-TO-HAVE: F2.9.**

Spec should be updated to add §5.18 (tab-hide during pending acquire), §5.19 (rapid Start/Stop/Start during pending acquire), §5.20 (visibility-triggered re-acquire races with explicit release). The canonical code in §4.3 and §4.5 should be rewritten with the generation counter before any subagent implements it — otherwise the subagent will faithfully reproduce all three MUST-FIX orphan-lock bugs.
