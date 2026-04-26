---
round: 2
angle: Concurrency and race safety
reviewer: general-purpose (Claude Opus 4.7)
date: 2026-04-21
---

# Nav Voice Picker — Round 2 Adversarial Review: Concurrency & Race Safety

Spec under review: [docs/superpowers/specs/2026-04-21-nav-voice-picker-design.md](../../docs/superpowers/specs/2026-04-21-nav-voice-picker-design.md)

Cross-checked against:
- `frontend/nav-ui.js` (init L49, onVoice L494-501, stopNavigation speechSynthesis.cancel L211, primeSpeech L706)
- `frontend/app.js` (sidebar open/close at L1162-1196, overlay-click → setSidebarOpen(false) L1192)
- `frontend/wake-lock.js` (acquireGeneration pattern L6, L22, L29, L44, L51, L63, L92)

---

### F2.1 — `activePreviewUtterance` has a cancel-then-speak clear race (critical)

**Severity:** MUST-FIX

**Claim in spec:** §9.3:
> "`activePreviewUtterance` is cleared in the utterance's `onend` / `onerror` handler as well."
> "On a new selection mid-preview: `speechSynthesis.cancel()` before speaking the next one"

**Race scenario:**
1. t=0: User clicks Male. `cancel()` runs (no-op, nothing active). New utterance M is built. `activePreviewUtterance = M`. `speak(M)`. `M.onstart` fires. M speaking.
2. t=200ms: User clicks Female. Code path: `cancel()` → `activePreviewUtterance = F` → `speak(F)`.
3. `cancel()` is not actually synchronous in terms of the `onend` delivery — Chrome, WebKit, and Firefox all queue utterance-end events on the main task loop. `M.onend` (or `onerror`) fires **after** `activePreviewUtterance = F` has already been assigned.
4. The `onend` handler the spec describes clears `activePreviewUtterance` unconditionally. `activePreviewUtterance` becomes `null` while F is still in flight.
5. User closes sidebar at t=400ms. Handler checks `activePreviewUtterance !== null` → **false** → does NOT cancel F. F keeps speaking after sidebar close.

**Impact:** Preview audio plays over the user's subsequent actions (map interaction, entering a search query, starting nav). The spec's §9.3 invariant — "preview cancellation is scoped to the preview utterance only" — holds in the wrong direction: it *fails to cancel* a live preview that should have been stopped.

**Proposed fix:** Mirror wake-lock.js's generation-counter pattern. Module-private `previewGeneration = 0`. Every new preview bumps it: `var myGen = ++previewGeneration; activePreviewUtterance = u; u.onend = u.onerror = function () { if (myGen === previewGeneration) activePreviewUtterance = null; };`. The `onend` only clears if this utterance is still the active one.

**Test to add:** In `preview-gate.test.mjs`, mock `speechSynthesis` with queued async `onend` delivery (via `queueMicrotask` or `setTimeout(..., 0)`). Fire two `click` events back-to-back on Male then Female. Then fire the stale M.onend. Assert `activePreviewUtterance === F` (not null). Then simulate sidebar close; assert `speechSynthesis.cancel()` was called.

---

### F2.2 — `speechSynthesis.cancel()` has no synchronous `onend` contract across browsers

**Severity:** MUST-FIX

**Claim in spec:** §9.2:
> "Cancel any in-flight utterance first: `speechSynthesis.cancel()` (matches the nav-ui pattern at nav-ui.js:464)."

**Race scenario:**
1. On Safari iOS, `speechSynthesis.cancel()` is documented to flush the queue but `SpeechSynthesisUtterance.onend` may not fire at all for cancelled utterances (WebKit bug #146484, still open as of 2024). The spec's §9.3 clears `activePreviewUtterance` in `onend` / `onerror`.
2. User clicks Male. M starts. User closes sidebar. Handler sees `activePreviewUtterance = M`, calls `cancel()`. M stops speaking. But `M.onend` never fires on iOS Safari.
3. `activePreviewUtterance` stays pointing at M forever.
4. User opens sidebar again, clicks Female. F is set as `activePreviewUtterance`. cancel-then-speak runs. `F.onend` (eventually) fires and clears `activePreviewUtterance`. OK for this case.
5. But if user never clicks another voice button, `activePreviewUtterance` holds a stale `M` reference for the rest of the session. On subsequent `visibilitychange → hidden`, the handler sees non-null and fires `cancel()` — cancelling any *nav utterance* currently in flight. This violates §G4 / §9.3 "must never interrupt an active nav utterance".

**Impact:** On iOS Safari, a single preview → sidebar-close sequence permanently arms the `visibilitychange` handler to nuke active nav voice lines. User pauses nav, Apple Maps takes over the screen momentarily (CarPlay, notification), comes back — next nav prompt got interrupted because the stale preview-utterance reference triggered a `cancel()`.

**Proposed fix:** (a) Clear `activePreviewUtterance = null` synchronously *at the point of calling cancel* — don't rely on `onend`. (b) Also clear it at the top of the next-utterance build, before calling `cancel()` for the new one. `onend` becomes a belt-and-suspenders clear that guards on generation counter per F2.1.

**Test to add:** In `preview-gate.test.mjs`, mock `speechSynthesis.cancel()` to NOT fire `onend` (iOS Safari semantics). Start preview M. Close sidebar (calls cancel). Simulate visibilitychange-hidden. Assert `speechSynthesis.cancel()` was NOT called a second time. (Additionally: start a nav-style utterance after closing the sidebar and assert it isn't interrupted.)

---

### F2.3 — `voiceschanged` mid-preview re-resolution gap

**Severity:** SHOULD-FIX

**Claim in spec:** §7.2:
> "`getVoices()` returns the same array reference between `voiceschanged` events in all supported browsers. We cache the last-returned `SpeechSynthesisVoice` keyed by `(mode, gender, voiceURI)`. On `voiceschanged` fire, cache is cleared."

**Race scenario:**
1. User clicks Female. `cancel()` runs. `getUtteranceVoice()` resolves to "Samantha" (voice list v1). `speak(F)` with `F.voice = Samantha_v1`.
2. F starts speaking.
3. Mid-utterance, the OS installs a new voice (or `voiceschanged` fires for any reason — Chrome on Android is known to fire it multiple times during startup, sometimes many seconds post-init). Cache is invalidated.
4. The in-flight F keeps using `Samantha_v1`. But the `Samantha` reference from the now-stale voice array may no longer be a valid voice handle in some browsers (Chromium re-materializes voice objects on list refresh). Undefined behavior — may continue normally, may cut out, may fall back to default mid-sentence.
5. Next nav utterance (minutes later) goes through `getUtteranceVoice()` — cache miss, re-resolves against fresh list. May now pick "Samantha_v2" (new object) or a different voice if the name-to-gender mapping hit a different entry due to voice-list reordering.

**Impact:** Preview may glitch mid-utterance. More importantly, the spec claims voice resolution is stable; in practice the user's "Female" choice might resolve to a different voice across `voiceschanged` fires even though the underlying preference hasn't changed, because the gender-scan returns the *first* match in list order.

**Proposed fix:** (a) Gender-mode resolution should sort the filtered voice list by a stable key (e.g., `voiceURI`) before picking "first match", so the output is idempotent across `voiceschanged` reshuffles. (b) On `voiceschanged` firing mid-preview, the spec should explicitly decide: leave the in-flight utterance alone (likely correct; cancellation mid-sentence is worse) and document this.

**Test to add:** In `voice-resolution.test.mjs`, call `getUtteranceVoice()` against a 5-voice list that resolves to voice B. Swap the underlying list to the same 5 voices in reverse order. Fire `voiceschanged`. Call `getUtteranceVoice()` again. Assert the resolved voice is still B (by voiceURI), not a different voice that happens to come first in the reversed order.

---

### F2.4 — First-nav-prompt races `voiceschanged` cold-start window

**Severity:** SHOULD-FIX

**Claim in spec:** §7.3:
> "On `init()`: call `getVoices()` once. If it returns a non-empty array, we're done (Firefox-style synchronous population). If it returns `[]`: register a `voiceschanged` handler..."

**Race scenario:**
1. Page loads. `nav-ui.js` init has `setTimeout(init, 200)` at L52-54 (map not ready).
2. `VoicePicker.init()` also runs on DOM-ready. `getVoices()` returns `[]` on Chromium. voiceschanged listener registered.
3. User has a preserved route (QR-loaded trip). Taps Start Nav immediately (within 500ms of page load). `primeSpeech()` runs at nav-ui.js L706-711 with an empty utterance.
4. First real nav prompt fires ~1-3 seconds later (per route geometry). `onVoice` calls `VoicePicker.getUtteranceVoice()`. If `voiceschanged` has fired by now on Chromium (usually yes but not guaranteed — observed up to 5s on some Android devices), gender resolution works. If not, `getVoices()` returns `[]`, scan fails, returns `null`, browser picks default voice.
5. `voiceschanged` finally fires 2s later. Cache invalidated. Next prompt (30s later, next maneuver) re-resolves and picks the user's preferred voice.

**Impact:** The *first* turn instruction of a nav session can be delivered in the device default voice instead of the user's preferred voice — specifically "Male"/"Female". User selected "Male" → heard female first prompt → starts nav anyway → every subsequent prompt is male → experience feels broken. The spec doesn't address this.

**Proposed fix:** (a) `getUtteranceVoice()` should return `null` gracefully (spec says it does — confirm this is OK per §G4 "zero regression"). (b) Prime the voice-picker by calling `getVoices()` in response to `primeSpeech()` as well — piggyback on the spec-unchanged prime-speech call at nav-ui.js:649-654 to force voice list population. Chromium `getVoices()` called after any speak() call tends to kick the list. (c) Document this behavior in §8: "first-utterance-after-cold-load may fall back to default voice; re-resolves on second prompt."

**Test to add:** In `voiceschanged-bootstrap.test.mjs`, mock `getVoices()` to return `[]` initially. Call `getUtteranceVoice()` with `mode: "gender"`. Assert returns `null` (not throws, not blocks on voiceschanged). Then fire voiceschanged with non-empty list. Call `getUtteranceVoice()` again. Assert returns the correct voice.

---

### F2.5 — Sidebar close detection is underspecified (3 close paths exist)

**Severity:** SHOULD-FIX

**Claim in spec:** §9.1:
> "Reset to `false` on any of: Sidebar close (existing sidebar-toggle close event)."
> §9.3: "On sidebar close: if `activePreviewUtterance !== null` → `speechSynthesis.cancel()`."

**Race scenario:** Actual sidebar-close paths per app.js L1162-1196:
1. `#sidebar-toggle` click (hamburger) — L1186.
2. `#sidebar-overlay` click (tap outside sidebar) — L1192.
3. `setSidebarOpen(false)` called programmatically (e.g., after search result selection, route import, other app flows).

The spec says "existing sidebar-toggle close event" — singular. Implementation attached to only the `#sidebar-toggle` click would miss paths (2) and (3).

**Scenario:** User clicks Male. Preview starts. User taps map area outside sidebar (overlay click). Sidebar closes via path (2). Voice-picker never hears about it. `previewArmed` stays true. `activePreviewUtterance` stays set. Preview keeps speaking while map is in full view. User then clicks Female 10s later (via hamburger reopen) — preview fires as expected, but the *previous* preview speaking through map interaction was a regression.

**Impact:** Preview audio plays after sidebar close via tap-outside (the most common close path on mobile).

**Proposed fix:** Hook the state reset to `sidebar.classList.remove('open')` via MutationObserver, OR wrap `setSidebarOpen` to emit a custom event (`sidebarclosed`) and have VoicePicker listen on that. MutationObserver is simplest for a module-boundary-respecting fix.

**Test to add:** `test_preview_cancels_on_all_sidebar_close_paths` in `preview-gate.test.mjs`: simulate each of the three close paths (toggle click, overlay click, programmatic `setSidebarOpen(false)`) and assert `speechSynthesis.cancel()` was called and `previewArmed === false` after each.

---

### F2.6 — Sidebar can be opened mid-nav — preview CAN kill nav utterance

**Severity:** MUST-FIX

**Claim in spec:** §9.3:
> "This is safe — no nav utterance can be in flight during the Preferences interaction cycle because the Preferences section only opens pre-nav (collapsed/hidden during active nav by existing sidebar behavior, verify in task 1 of the plan)."

**Race scenario:** Cross-checking the codebase: app.js L1185-1196 (sidebar-toggle handler) has no guard for `active` / nav state. nav-ui.js L206 sets `document.body.classList.add('nav-active')` but nothing in the sidebar-open handler checks it. There is no CSS rule that hides the sidebar toggle during nav either (searched nav-ui/app.js/index.html — nav-overlay appears, start-btn/stop-btn swap, but sidebar remains toggleable).

Sequence:
1. User starts nav. First voice prompt "In 500 feet, turn right" begins. `speechSynthesis` queue has utterance U1.
2. User taps hamburger mid-nav (to verify route? switch units to metric while driving?). Sidebar opens.
3. User bumps the Female button. `previewArmed` is true (just clicked). Preview path: `speechSynthesis.cancel()` → kills U1 mid-word → builds F → speaks F.
4. U1 never completes. Turn instruction is truncated. User misses the turn.

**Impact:** **Silent, dangerous nav regression.** The spec's defence — "Preferences only opens pre-nav" — is factually wrong based on app.js L1185-1196. The "verify in task 1 of the plan" caveat does not rescue the spec; if verification fails, the whole preview gate is unsafe.

**Proposed fix:** Two layers:
(a) Disable `.pref-voice-btn` and `#pref-voice-select` when `document.body.classList.contains('nav-active')` (add `[disabled]` + grey out). VoicePicker listens to a mutation on `document.body.className` or wraps nav start/stop with events.
(b) Inside preview logic, explicitly check `document.body.classList.contains('nav-active')`. If true, do not call `cancel()` — return early. §9.3 claims this is "additional safety but redundant given the preview-utterance-tracking"; F2.6 shows it's *not* redundant.

**Test to add:** In `preview-gate.test.mjs`, set `document.body.className = 'nav-active'` then trigger a `.pref-voice-btn` click. Assert `speechSynthesis.cancel()` was NOT called AND `speechSynthesis.speak()` was NOT called.

---

### F2.7 — 30s "idle reset" doesn't account for in-sidebar interactions

**Severity:** NICE-TO-HAVE

**Claim in spec:** §9.1:
> "Reset to `false` on any of: ... Module-internal timeout of 30 seconds after last click (handles 'user configured then wandered away')."

**Race scenario:**
1. User opens sidebar. Clicks Male. `previewArmed = true`. 30s timer starts. Preview plays.
2. User then interacts with Units radios — switches to Metric. Then plays with Coordinates radios. 25s elapsed since Male click.
3. User sees the new "km" phrasing and thinks "cool, let me preview that" and taps Female. Timer has now been running 32s. `previewArmed` was reset to `false` at t=30s. No preview fires. User confused.

**Impact:** UX bug — user interaction within Preferences section should count as "still configuring", but the spec's gate only re-arms on `.pref-voice-btn` / `#pref-voice-select` activity.

**Proposed fix:** Reset the 30s idle timer on ANY click within `#pref-voice`'s containing Preferences section (Units + Coordinates radios count as "still configuring"). Alternative: bump the timeout to 5 minutes since the user is actively in the sidebar.

**Test to add:** In `preview-gate.test.mjs`, simulate: click Male → 25s wait → click Units radio → 25s wait → click Female → assert preview fires (timer was reset by Units click).

---

### F2.8 — Memoization cache keyed by array identity is wrong

**Severity:** SHOULD-FIX

**Claim in spec:** §7.2:
> "We cache the last-returned `SpeechSynthesisVoice` keyed by `(mode, gender, voiceURI)`. On `voiceschanged` fire, cache is cleared."

Also §7.1 step 4:
> "Memoize result against the voice list's identity (current array reference from getVoices())."

**Race scenario:** Internal inconsistency — §7.1 says "voice list's identity" (array reference), §7.2 says "(mode, gender, voiceURI)" key. Which is the cache key? If implemented as array-reference:

1. `voiceschanged` fires at t=0. Cache invalidated. List = array A.
2. `getUtteranceVoice()` called, resolves to voice V against A. Cache stores (A → V).
3. `voiceschanged` fires at t=1s (Chrome on Android commonly fires this multiple times during startup). Cache invalidated. `getVoices()` now returns array B (distinct reference, same contents).
4. `getUtteranceVoice()` re-resolves against B. In a "gender" mode, scan returns first match. If B happens to be in a different sort order (spec doesn't guarantee `getVoices()` order across fires), V' may differ from V.
5. Preview was spoken with V; next nav utterance uses V'. User hears different voice between preview and first turn instruction.

**Impact:** Resolution non-determinism across `voiceschanged` fires, audible to user as "the voice changed even though I didn't change my preference".

**Proposed fix:** (a) Reconcile §7.1 and §7.2 — pick one cache key semantics. (b) For gender mode, apply a stable sort on the filtered voice list (by voiceURI) before picking the first match, so the same underlying set of voices always resolves to the same pick regardless of `getVoices()` order.

**Test to add:** Same as F2.3 — feed the same set of voices in two different orders, assert same resolved voice.

---

### F2.9 — localStorage `storage` event cross-tab not addressed

**Severity:** NICE-TO-HAVE

**Claim in spec:** §5.1 defines the localStorage schema. No mention of cross-tab sync via the `storage` event.

**Race scenario:**
1. User has Geographica open in two tabs (common on dev/testing, and possible in field use if someone shares a link).
2. Tab A: user changes voice to Female. localStorage writes. Preview fires in tab A.
3. Tab B: UI still shows "Default" active in its in-memory state. If tab B is used for navigation, each nav utterance re-reads from localStorage (via `getUtteranceVoice()`) — it picks up Female. But the UI button doesn't update to reflect this, so the user sees "Default" active but hears Female.
4. User in tab B then clicks Default, overwriting the Female setting tab A made. Tab A's UI still says Female. Confused users, confused bug reports.

**Impact:** UI/state desync across tabs. Not dangerous, but misleading.

**Proposed fix:** VoicePicker listens to `window.addEventListener('storage', ...)` for `nav-voice-pref` changes and re-renders the button state + dropdown selection. Low effort, strong correctness win.

**Test to add:** In `preference-persistence.test.mjs`, simulate a `storage` event for `nav-voice-pref` with a new value. Assert the UI button state updates.

---

### F2.10 — `visibilitychange → hidden` during preview doesn't address resume

**Severity:** NICE-TO-HAVE

**Claim in spec:** §9.3:
> "On `visibilitychange` → hidden: if `activePreviewUtterance !== null` → `speechSynthesis.cancel()`."

**Race scenario:**
1. User clicks Male. Preview starts. `activePreviewUtterance = M`.
2. Phone receives a call. `visibilitychange → hidden`. Cancel fires. M stops. `activePreviewUtterance` clears (via `onend` or F2.1's generation-counter fix).
3. Call ends. `visibilitychange → visible`. No handler for resume.
4. User still sees Male as the active button (UI state unchanged). But preview was truncated mid-sentence. User doesn't know if the voice worked or not.
5. iOS PWA standalone mode additionally: after `visibilitychange → hidden → visible`, `speechSynthesis` can enter a broken state where subsequent `speak()` calls are silently dropped until `cancel()` + `speak()` are called fresh. (Known WebKit quirk, same class as the §5.19-style PWA issue.)

**Impact:** (a) User misses the preview. (b) On iOS PWA, the next nav utterance (even hours later) may be silently dropped.

**Proposed fix:** On `visibilitychange → visible`, if preview was cancelled by the hidden handler and `previewArmed` is still true, optionally replay the preview (debatable UX). More importantly: on visibility-regain, call `speechSynthesis.cancel()` once as a cold-reset for iOS PWA — mirrors the wake-lock.js pattern at L85-99.

**Test to add:** In `preview-gate.test.mjs`, start preview → fire `visibilitychange → hidden` → fire `visibilitychange → visible`. Assert `speechSynthesis` is in a usable state (a subsequent `speak()` succeeds and its `onstart` fires).

---

### F2.11 — Rapid-click rate limit missing — speech engine queue overflow

**Severity:** SHOULD-FIX

**Claim in spec:** §9.2:
> "Cancel any in-flight utterance first: `speechSynthesis.cancel()`"

**Race scenario:**
1. User rapid-clicks Default → Male → Female → Male → Female → Default within 500ms (fidgeting, or a stuck touch event).
2. Each click: cancel → speak. 6 calls. Per WebKit and Chromium, rapid `cancel()` + `speak()` sequences can leave the engine in a "speaking-but-silent" state where `speechSynthesis.speaking === true` but no audio is emitted. No `onerror` fires. This is observed across multiple reports; no official fix as of 2024.
3. The final "Default" preview may not be audible. User thinks voice picker is broken.

Additionally, each click does a localStorage write per §5.4. 6 writes of a ~100-byte JSON object in 500ms is trivially safe, but not free; every click also re-resolves `getUtteranceVoice()` and invalidates the memoization cache implicitly via the write path (the spec doesn't explicitly invalidate on write — but should, since the preference just changed).

**Impact:** (a) Preview may go silent after rapid clicks. (b) Cache may serve stale resolved-voice for a preference that no longer matches.

**Proposed fix:** (a) Debounce preview by ~150ms — only speak after clicks settle. (b) Explicit cache invalidation on any write to `nav-voice-pref`. (c) Ensure `activePreviewUtterance`-vs-generation-counter logic (F2.1 fix) applies.

**Test to add:** In `preview-gate.test.mjs`, fire 6 clicks within 500ms. Assert `speechSynthesis.speak()` was called at most 2 times (debounced) OR that only the final utterance is heard (speaking flag clears, final utterance's onstart fires). Also assert the final persisted preference matches the last click.

---

### F2.12 — Mock-based tests won't catch any of F2.1-F2.11 if mocks are synchronous

**Severity:** SHOULD-FIX (meta-finding about the test strategy)

**Claim in spec:** §10.1:
> "Mocks for `window.speechSynthesis`, `window.localStorage`, and `document` constructed via a `_fixtures.js` module"

**Race scenario:** Most of the races above (F2.1, F2.2, F2.3, F2.4, F2.10, F2.11) depend on `speechSynthesis.speak()` being async-effectful — `onend`/`onstart` fire after the current microtask. If the mock fires `onend` synchronously inside `speak()`, none of these race windows exist in tests. Tests pass. Production still races.

**Impact:** False-green tests. The spec doesn't specify the mock's timing model.

**Proposed fix:** §10.1 must add a test infrastructure requirement: **the speechSynthesis mock MUST deliver `onstart` / `onend` / `onerror` asynchronously via `queueMicrotask` or `setTimeout(..., 0)`, matching browser semantics**. Include a meta-test that asserts the mock does this, to prevent future test rewrites from regressing to synchronous behavior.

**Test to add:** `test_mock_is_async.mjs` — constructs an utterance, records ordering: `speak(u); /* synchronous assertion */ assert(u.onstart was not yet called)`. Then `await new Promise(r => setTimeout(r, 10))`. Assert `u.onstart was called`.

---

## Summary

- **MUST-FIX:** F2.1, F2.2, F2.6
- **SHOULD-FIX:** F2.3, F2.4, F2.5, F2.8, F2.11, F2.12
- **NICE-TO-HAVE:** F2.7, F2.9, F2.10

**Most subtle race:** F2.1 — the `onend` / clear-on-cancel race across rapid button clicks. The spec's `activePreviewUtterance` pattern appears correct but inverts itself under async `onend` delivery: the stale utterance's `onend` clears the *new* utterance's tracking state, disabling the very cancel path the feature relies on.

**Canonical remedy pattern:** Port the `acquireGeneration` counter from `wake-lock.js` L6/L22/L29/L44/L51/L63/L92 into voice-picker.js verbatim — same problem class, already has a proven in-tree solution.
