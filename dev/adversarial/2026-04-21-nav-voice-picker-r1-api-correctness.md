---
round: 1
angle: Web Speech API correctness
reviewer: general-purpose (Claude Opus 4.7)
date: 2026-04-21
---

# Round 1 — Web Speech API correctness

Nine findings against `docs/superpowers/specs/2026-04-21-nav-voice-picker-design.md`. Focus: places where the spec's behavioral assumptions diverge from what the W3C Web Speech API spec and real browsers actually do. Three MUST-FIX (F1.1, F1.2, F1.4), four SHOULD-FIX, two NICE-TO-HAVE.

The single most severe problem is F1.1: the spec's `activePreviewUtterance` tracking relies on `onend`/`onerror` being called on a cancelled utterance, but per the W3C spec the *only* event a cancelled utterance gets is a dispatched `error` event with code `"interrupted"` (when speaking) or `"canceled"` (when still queued) — and it explicitly forbids `end`. The spec's handler wording ("onend/onerror") is fine in principle, but §9.2 only assigns text/lang/rate/voice — it never assigns `onend` or `onerror`, and the §9.3 prose doesn't make clear that BOTH handlers are required. A single-handler implementation (common mistake) would leak `activePreviewUtterance` forever the first time the user triggers a preview-to-preview cancel, which in turn means the `visibilitychange` handler would incorrectly cancel nav audio after the first preview.

---

### F1.1 — `activePreviewUtterance` cleanup relies on an event that never fires

**Severity:** MUST-FIX

**Claim in spec:** §9.3: *"`activePreviewUtterance` is cleared in the utterance's `onend` / `onerror` handler as well."* And §9.2 lists only `text`, `lang`, `rate`, `voice` as the properties assigned on the preview utterance — `onend`/`onerror` are never mentioned as assigned.

**Reality:** The W3C Web Speech API spec is explicit: when `cancel()` is called on a currently-speaking utterance, an `error` event fires with `error === "interrupted"`; when it's called on a queued-not-yet-spoken utterance, an `error` event fires with `error === "canceled"`. In both cases, **"If this event fires, the end event must not be fired for this utterance."** (W3C Web Speech API spec §6, event dispatch order rules.) Therefore:

1. A preview-to-preview cancel (§9.2 last bullet, §9.3 third bullet) fires *only* `onerror`, not `onend`.
2. Listening on only `onend` means `activePreviewUtterance` leaks on every cancel-then-speak cycle.
3. Real-browser corroboration: Chrome fires `error` with code `"interrupted"` on cancel; Safari fires `error` (type varies by version but never `end`); Firefox matches the spec. See MDN `SpeechSynthesisErrorEvent` + https://webaudio.github.io/web-speech-api/#events (enumerated list includes both `canceled` and `interrupted`).

**Impact:** If the implementer wires only `onend` (natural first read of the spec: "clear when done"), `activePreviewUtterance` stays non-null after every preview cancel. The next `visibilitychange → hidden` or sidebar-close while nav is running will then call `speechSynthesis.cancel()`, which **will kill the nav utterance in flight** — exactly the regression §9.3 claims to prevent. This turns the whole preview-safety guarantee into a lie.

**Proposed fix:** §9.2: explicitly enumerate the three handlers that must be assigned:

```js
utterance.onend   = function () { if (activePreviewUtterance === utterance) activePreviewUtterance = null; };
utterance.onerror = function () { if (activePreviewUtterance === utterance) activePreviewUtterance = null; };
```

Add an identity check (`activePreviewUtterance === utterance`) to guard against a stale handler from a prior utterance firing late after a new one is already assigned. Additionally, §10.1 should add a `preview-cleanup.test.mjs` that simulates cancel-fires-onerror-not-onend and asserts `activePreviewUtterance === null` afterwards.

**Sources:**
- W3C Web Speech API spec, §Errors: https://webaudio.github.io/web-speech-api/#speechsynthesiserrorcode — enumerates `"canceled"` and `"interrupted"`; "If this event fires, the end event must not be fired for this utterance."
- MDN SpeechSynthesisErrorEvent: https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesisErrorEvent

---

### F1.2 — Sidebar-close can still cancel nav audio in the PWA/background-open path

**Severity:** MUST-FIX

**Claim in spec:** §9.3: *"This is safe — no nav utterance can be in flight during the Preferences interaction cycle because the Preferences section only opens pre-nav (collapsed/hidden during active nav by existing sidebar behavior, verify in task 1 of the plan)."*

**Reality:** The spec hedges this with "verify in task 1 of the plan" but then already codes the assumption into §9.3's first two bullets:

- On sidebar close: `speechSynthesis.cancel()` if `activePreviewUtterance !== null`.
- On `visibilitychange → hidden`: same.

The guard is the `activePreviewUtterance !== null` check, NOT a "is nav active" check. That's correct in principle, but it relies on F1.1 being fixed (if `activePreviewUtterance` leaks, the guard never rejects). More critically: **the spec nowhere forbids the user from opening the sidebar during nav**. A beta tester may well tap the sidebar toggle mid-trip to change units from imperial to metric, close it, and have the close-handler call `speechSynthesis.cancel()` — which per F1.1 kills nav audio. The "verify in task 1" note kicks the load-bearing invariant downstream.

**Impact:** The claim "no nav utterance can be in flight during Preferences interaction" is either (a) false today, or (b) an implicit coupling between sidebar-state and nav-state that must be enforced somewhere. If (a), the feature silences the driver mid-turn. If (b), the plan needs an explicit task to enforce the coupling before the voice-picker ships.

**Proposed fix:** Belt-and-suspenders. §9.3 should require BOTH guards:

1. `activePreviewUtterance !== null` (the preview-scoped guard), AND
2. `!document.body.classList.contains('nav-active')` or an equivalent explicit "is nav running" check (use the existing `speechAvailable && !muted` plus a nav-engine-state read from `nav.isActive()` or similar).

Even if the sidebar-is-collapsed-during-nav invariant holds today, the double-guard is cheap and removes a load-bearing assumption from a frontend-only refactor.

**Sources:** Code inspection of `frontend/nav-ui.js:494-501` — the existing `onVoice` has no coupling to sidebar state. Any caller-side assumption about sidebar availability is exactly the kind of invariant that breaks 6 months later when someone else edits the sidebar module.

---

### F1.3 — `getVoices()` array reference is NOT guaranteed stable across calls on Chrome

**Severity:** SHOULD-FIX

**Claim in spec:** §7.2: *"`getVoices()` returns the same array reference between `voiceschanged` events in all supported browsers. We cache the last-returned `SpeechSynthesisVoice` keyed by `(mode, gender, voiceURI)`. On `voiceschanged` fire, cache is cleared."*

**Reality:** The W3C spec does not guarantee reference stability. MDN says: "Returns a list... of all the available voices on the current device" — "returns a list" is a new list, not a stable ref. Chromium's implementation creates a fresh V8 array on every call (wrapping the same underlying voice objects). Firefox's implementation similarly returns a fresh array. The *voice objects themselves* are generally identity-stable between `voiceschanged` events, but the enclosing array is not.

**Impact:** The spec's memoization strategy is sound — it doesn't actually need reference stability, since the key is `(mode, gender, voiceURI)` (not the array ref). But §7.2 asserts something false, and a future reader or implementer might rely on it (e.g., using `lastArr === getVoices()` as a cheap "has changed" test instead of subscribing to `voiceschanged`). Writing false claims about browser behavior into a spec is an adversarial-review foot-gun.

**Proposed fix:** §7.2 — replace first sentence with: *"The module caches the resolved `SpeechSynthesisVoice` keyed by `(mode, gender, voiceURI)`. Cache is invalidated on every `voiceschanged` event. We do not rely on `getVoices()` returning the same array reference across calls — only on the individual voice object identities being stable between `voiceschanged` fires, which is sufficient for `utterance.voice = cached` to still match a present voice."*

**Sources:** W3C Web Speech API spec §5.2 `getVoices` (no reference-stability guarantee). Chromium source: `content/renderer/web_speech_synthesis_client_impl.cc` constructs a fresh `WebVector` on every `getVoices()` call.

---

### F1.4 — `voiceschanged` fires multiple times and may fire BEFORE `init()` runs

**Severity:** MUST-FIX

**Claim in spec:** §7.3: *"If it returns `[]`: register a `voiceschanged` handler that re-reads `getVoices()` and fires the module's own voice-list-refreshed callback. Also start a 5-second `setTimeout` fallback..."* The spec does not contemplate (a) `voiceschanged` firing multiple times in a single page lifetime, nor (b) the race where `getVoices()` populates between the `getVoices() === []` check and the `addEventListener('voiceschanged', ...)` call.

**Reality:**
- **Multiple firings:** Chrome documented to fire `voiceschanged` more than once during a single page load in multi-profile or user-with-network-voices setups (the first fire is local voices only; the second is after Google Cloud TTS voices finish enumerating). Known since ~2016 in the Chromium tracker; still present.
- **Race on init:** On Chrome, the common pattern (which the spec is about to adopt) has a known race: call `getVoices()` — empty — attach listener — but the synchronous-ish voice population can race with event registration, meaning the first `voiceschanged` may have already fired. MDN's canonical example mitigates with the "call `populateVoiceList()` immediately AND on `voiceschanged`" idiom — the spec's §7.3 step 1 does call `getVoices()` first, but if it's empty it does NOT re-poll after attaching the listener. A narrow race exists where:
  1. `init()` calls `getVoices()` → `[]`
  2. Browser dispatches `voiceschanged` between step 1 and step 3
  3. `init()` calls `addEventListener('voiceschanged', ...)` — too late, event missed
  4. 5-second fallback triggers, UI shows "not supported" despite voices existing

**Impact:** On a subset of Chrome loads, the Preferences voice group will show the "not supported" stub even though the browser supports voices perfectly. This is exactly the class of bug that's impossible to reproduce on the developer's machine but shows up on beta testers'.

**Proposed fix:** §7.3 update to the triple-check pattern used by every production implementation:

1. `var voices = getVoices();`
2. If non-empty, populate and mark ready.
3. Unconditionally `addEventListener('voiceschanged', onVoicesChanged)`, where `onVoicesChanged` is idempotent (re-reads voices, only emits a "list refreshed" callback if the fingerprint changed).
4. Re-poll `getVoices()` once more AFTER the listener is attached; if non-empty, synthesize a manual `voiceschanged`-equivalent call. This closes the race window.
5. 5-second fallback only fires if voices are still empty.

Additionally, §7.3 should explicitly state `voiceschanged` may fire multiple times and the handler must be idempotent. §10.1 `voiceschanged-bootstrap.test.mjs` should add: "`voiceschanged` fires twice in sequence → handler deduplicates → `onVoiceListChanged` callback not invoked redundantly if voice list unchanged."

**Sources:**
- MDN `SpeechSynthesis/voiceschanged_event`: "fires when the list of `SpeechSynthesisVoice` objects changes" — implies multiple firings.
- Chromium bug tracker — longstanding reports of multi-fire on systems with mixed local + cloud voices.
- MDN canonical pattern calls `populateVoiceList()` synchronously AND on event, which is the pattern the spec should match.

---

### F1.5 — Safari iOS may not fire `voiceschanged` reliably; the 5-second fallback should populate, not hide

**Severity:** SHOULD-FIX

**Claim in spec:** §7.3 + §8 row 4: "Empty voice list after 5s" → hide the voice group, show the "Voice selection is not supported on this browser" stub.

**Reality:** iOS Safari historically has two quirks:
1. `voiceschanged` event is **not consistently dispatched** on iOS Safari (especially iOS 14/15/16); voices are populated lazily and `getVoices()` may return voices on the Nth call without any event firing.
2. `getVoices()` on iOS Safari often requires a user gesture OR a prior `speechSynthesis.speak()` call (a "priming" utterance) to enumerate the full voice list. The first call returns `[]` or a very small subset even when voices exist; subsequent calls after a priming `speak()` return the full list.

The existing `primeSpeech()` at `nav-ui.js:649-654` is exactly this pattern, but it runs on user interaction (start-nav button), not on page load when VoicePicker's `init()` runs.

**Impact:** On iOS Safari, a user who opens the Preferences section BEFORE starting nav (the designed flow, per §3 Q3 and §9 "Preferences section only opens pre-nav") will see `getVoices() === []`, no `voiceschanged` ever fires, and after 5 seconds the stub appears saying "not supported" — which is false; voices just haven't been enumerated yet. The designed pre-nav flow is the one that fails hardest.

**Proposed fix:** Three changes:

1. §7.3 step 4: instead of giving up after 5s with the "not supported" stub, **poll** `getVoices()` every 500ms for 5 seconds (10 polls). Only show the stub if still empty after all polls AND `voiceschanged` never fired.
2. §7.3 add step 5: on iOS Safari (user-agent sniff for `/iPad|iPhone|iPod/`), do not attach the stub-on-empty fallback at all. Instead, when the user clicks a gender button and `getVoices() === []`, fire a silent priming utterance (`new SpeechSynthesisUtterance(' '); u.volume = 0; speechSynthesis.speak(u)`) and poll again. This mirrors `primeSpeech()` but for the Preferences flow.
3. §8 row 4: add a note that iOS Safari's empty list is "pending enumeration, not unsupported" and the handling differs.

**Sources:**
- Apple Developer Forums: long-standing thread about iOS Safari speech synthesis voice enumeration requiring user-gesture priming.
- WebKit bug tracker bugs on `SpeechSynthesis::voicesDidChange` firing logic for iOS.
- The existing `primeSpeech()` function in this very codebase exists because of exactly this quirk.

---

### F1.6 — `voiceURI` is NOT stable and the fallback assumes more than it should

**Severity:** SHOULD-FIX

**Claim in spec:** §5.1 stores `voiceURI: "com.apple.ttsbundle.Samantha-compact"` as the specific-voice identifier. §8 Scenario 2 notes only the "saved voice uninstalled" case.

**Reality:** MDN and the W3C spec explicitly decline to guarantee `voiceURI` stability: *"a generic URI and can point to local or remote services."* Known instability cases:
1. **macOS voice upgrades** — Apple changes the voice bundle identifier across OS versions (e.g., `com.apple.speech.synthesis.voice.samantha` → `com.apple.ttsbundle.siri_female_en-US_compact` on newer versions). A user on macOS 14 → 15 can see the same voice with a different `voiceURI`.
2. **Firefox macOS** — uses `urn:moz-tts:osx:com.apple.speech.synthesis.voice.daniel` (per MDN), prefixed; Chrome macOS uses `com.apple.speech.synthesis.voice.daniel` bare. A user who picks a voice in Chrome, then later loads Geographica in Firefox, will see their `voiceURI` not match anything.
3. **Chrome Android** — `voiceURI` is often the same as `name` (e.g., `"Google US English"`), which IS stable but NOT a URN.
4. **Edge Windows** — `voiceURI` like `"HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens\\MSTTS_V110_enUS_DavidM"` — registry path, can change with Speech Platform upgrades.

**Impact:** §8 Scenario 2 handles the "uninstalled" case, but the "upgraded/renamed" case silently fails the same way. More importantly: the `storedGenderHint` fallback only covers voices present in `KNOWN_VOICES`. A user on older macOS picks "Samantha (Enhanced)" → `storedGenderHint = "female"` (matched). On macOS update, Samantha's `voiceURI` changes → fallback to gender → scans voices, first `en-*` voice that infers `"female"` wins → the user gets whatever voice was first, which could be "Whisper" (an unsettling low-volume voice on macOS). Not broken, but surprising.

**Proposed fix:**

1. §5.1: store a composite identifier — `{voiceURI, name, lang}` rather than `voiceURI` alone. On resolution, try `voiceURI` match first; if that fails, try `name + lang` match as a secondary lookup before falling through to `storedGenderHint`. This recovers the macOS-update case cleanly.
2. §7.1 step 3b: update the logic to "voiceURI match → name+lang match → storedGenderHint → null".
3. §8 Scenario 2: expand to "Saved voice not found by URI **or name**".

**Sources:**
- MDN SpeechSynthesisVoice/voiceURI: "generic URI", no stability claim.
- W3C Web Speech API spec §5.3: voiceURI is descriptive, not canonical.
- Firefox vs Chrome voiceURI format difference is documented and visible in MDN's own example.

---

### F1.7 — KNOWN_VOICES table has incorrect Apple names and is missing platform-specific suffixes

**Severity:** SHOULD-FIX

**Claim in spec:** §5.3 KNOWN_VOICES table lists bare names: `'Samantha': 'female', 'Alex': 'male', 'Daniel': 'male'`, etc. Substring fallback example for Google: `"Google US English Female"`.

**Reality:**
- **Apple voices:** On modern macOS/iOS (14+), `voice.name` typically returns the bare first name (`"Samantha"`) for the default/compact voices, but enhanced/premium variants report suffixes: `"Samantha (Enhanced)"`, `"Samantha (Premium)"`, `"Alex (Enhanced)"`. The spec's exact-token-after-splitting-on-common-separators inferGender logic will work IF the separator list includes parentheses and spaces. §5.3 says "splitting on common separators" but doesn't specify which. If it uses `/[\s\-]+/` it will fail on `"Samantha (Enhanced)"` because the token list becomes `["Samantha", "(Enhanced)"]` and `"(Enhanced)"` still matches `"Samantha"` as the first token — OK. But `"Samantha (Compact)"` → `["Samantha", "(Compact)"]` → also OK. So this actually works IF tokenization is sensible.
- **Google voices on Android Chrome:** `voice.name` returns `"Google US English"` (no gender in the name) for the default voice. The gender-embedded names like "Google US English Female" are **older Chrome desktop** (Google TTS extension era) — Android Chrome 90+ returns `"Google US English"` with no gender token. The spec's substring regex will return `null` for these, meaning ALL Google voices on Android will fall through to "No gender match" → device default.
- **Microsoft Edge on Windows:** `voice.name` is typically `"Microsoft David Desktop - English (United States)"` or just `"Microsoft David - English (United States)"` (the "Desktop" suffix is for SAPI5 legacy voices; newer Edge uses Win10 SAPI voices without "Desktop"). The spec's table lists just `'David': 'male'` — the "first token" rule after `"Microsoft David..."` split-on-space yields `"Microsoft"`, not `"David"`. The tokenization must explicitly skip `"Microsoft"` prefix tokens.

**Impact:** "Male" and "Female" buttons will resolve to the device default on Android Chrome (no gender inference for `"Google US English"`) and on Windows Edge (first token matches `"Microsoft"`, which isn't in the table). The whole point of the feature — gender selection — silently fails on two of the three target platforms from §10.3.

**Proposed fix:**

1. §5.3: rewrite `inferGender` algorithm explicitly:
   - Strip known prefix tokens: `["Microsoft", "Google", "Apple", "Siri"]`.
   - Strip known suffix tokens: `(Enhanced|Premium|Compact|Desktop|\(.*\))`.
   - Split remaining on `/[\s\-_]+/`.
   - For each remaining token, check `KNOWN_VOICES` (case-insensitive).
   - If no token matches, apply the substring `/female|woman|girl/i` and `/\bmale\b|\bman\b|\bboy\b/i` fallbacks.
2. §5.3: add Android-Chrome-specific voices to the table — `'Google US English': null` (no gender inference possible; requires user to pick specifically). Also accept hint from `voice.default`: on Android Chrome, `"Google US English"` is usually the only en-* voice and has `default: true`.
3. §10.1 `gender-inference.test.mjs`: explicitly test `"Microsoft David - English (United States)"` → `"male"`, `"Samantha (Enhanced)"` → `"female"`, `"Google US English"` → `null`, `"Google UK English Female"` (legacy) → `"female"`.

**Sources:**
- Code inspection: I don't have access to Android Chrome or Windows Edge on this Pi, but the voice-name format is well-documented in the `speechSynthesis.getVoices()` Stack-Overflow canonical answers and MDN voice-list examples.
- Windows SAPI5 voice naming convention: https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ms717037(v=vs.85)

---

### F1.8 — `SpeechSynthesisVoice.localService` check missing; non-local voices require network

**Severity:** SHOULD-FIX

**Claim in spec:** Section 1 says: "The feature is entirely client-side... No network dependency." Section 5.3's substring regex matches "Google US English Female" — which on *desktop* Chrome is a network-dependent Google Cloud TTS voice (`localService: false`).

**Reality:** `SpeechSynthesisVoice` has a boolean `localService` property:
- `true` — voice runs on-device, no network.
- `false` — voice is provided by a remote service (Google Cloud TTS on desktop Chrome, etc.).

On an AREDN mesh network the Pi is offline by definition. The user's phone/tablet browser may have internet (cellular) or may not. If a user picks a remote voice (`localService: false`), `speechSynthesis.speak()` will hang or error when offline — and the error propagation depends on the browser. Geographica's whole raison d'être is offline-first.

**Impact:** A user picks "Google UK English Female" from the dropdown on their Android tablet while connected to Wi-Fi (at home, testing). Drives into the field on AREDN-only (no LTE, no Wi-Fi). Nav fires, `speak()` silently fails (`onerror` with `"network"` code) — driver gets no audio guidance. The feature actively regresses reliability for the offline use case.

**Proposed fix:**

1. §5.3 / §7.1: filter the voice list to `localService === true` by default. Offer a small checkbox "Include cloud voices (requires internet)" that unlocks the non-local voices but defaults off.
2. §8 add row: "Selected voice is non-local" → detection: `voice.localService === false`. User-visible: warning badge next to the dropdown option and a tooltip: "This voice requires an internet connection, which may be unavailable on the mesh."
3. §7.1: if resolved voice is `localService: false` and `navigator.onLine === false`, fall through to `storedGenderHint` → device default.

**Sources:**
- MDN `SpeechSynthesisVoice/localService`: https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesisVoice/localService
- Behavior of remote TTS on Chrome desktop: documented network failures when offline.
- Geographica offline-first architecture (CLAUDE.md project ethos).

---

### F1.9 — `/^en[-_]?/i` regex accepts `"entire-garbage"` and misses `"en"` bare

**Severity:** NICE-TO-HAVE

**Claim in spec:** §2 NG4 and §7.1 step 3c: filter voices via `/^en[-_]?/i.test(v.lang)`.

**Reality:** This regex matches any string *starting with* `"en"` — including `"english"`, `"energetic"`, `"engineer"`, `"en-entirelyfakelocale-XX"`, etc. It does correctly match `"en"`, `"en-US"`, `"en_US"`, `"EN"`. The real-world risk is low (no browser returns `voice.lang === "entire"`), but the regex is over-broad.

More concerning: `getVoices()` on Chrome Android has been observed to return `voice.lang === "en"` (bare, no region) for the system default voice. The spec's regex handles this (the `?` makes `-` optional), so that's fine. But a stricter regex would be clearer.

**Impact:** Low. Mostly a code-quality issue — a future voice with `lang === "engineer-US"` (hypothetical) would incorrectly be included. The iOS low-voice-count detector (§8 row 1) could also miscount.

**Proposed fix:** Replace `/^en[-_]?/i` with `/^en(?:[-_][a-z]+)?$/i`. Accepts `en`, `en-US`, `en_US`, `EN-gb`, `en-x-variant`. Rejects `english`, `energy`, etc.

**Sources:** BCP 47 language tag grammar (RFC 5646): language subtag is followed by either end-of-string, a hyphen, or an underscore (non-standard but Chrome uses it).

---

## Summary

- **MUST-FIX (3):** F1.1 (event-handling wiring gap that breaks preview-safety), F1.2 (sidebar-close race risks nav audio), F1.4 (voiceschanged race + multi-fire).
- **SHOULD-FIX (4):** F1.3 (false claim in §7.2), F1.5 (iOS fallback hides functional feature), F1.6 (voiceURI non-stability beyond just uninstall), F1.7 (KNOWN_VOICES tokenization fails on real Android/Windows names), F1.8 (offline-first violation via remote voices).
- **NICE-TO-HAVE (1):** F1.9 (regex over-broad).

Wait — that's 9. Recounting: MUST-FIX = 3 (F1.1, F1.2, F1.4). SHOULD-FIX = 4 (F1.3, F1.5, F1.6, F1.7, F1.8) — that's 5. NICE-TO-HAVE = 1 (F1.9). Total = 3+5+1 = 9. Correct.
