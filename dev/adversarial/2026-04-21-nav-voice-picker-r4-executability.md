---
round: 4
angle: Subagent executability
reviewer: general-purpose (Claude Opus 4.7)
date: 2026-04-21
---

# Round 4 adversarial review — Nav voice picker spec, subagent-executability lens

Reviewing `/home/administrator/Code/geographica/docs/superpowers/specs/2026-04-21-nav-voice-picker-design.md`
as a subagent who received a plan authored from this spec with NO prior
conversation context. Goal: flag every spot where I'd either (a) get stuck, (b)
silently pick a wrong interpretation, or (c) ship a bug because the spec
deferred to "obvious" convention that isn't actually established in the
codebase.

Cross-checked against: `frontend/wake-lock.js`, `frontend/nav-ui.js`,
`frontend/index.html`, `frontend/style.css`, `frontend/app.js`.

---

### F4.1 — Wrong line numbers in §4.2 "Before" block and the `primeSpeech` reference

**Severity:** MUST-FIX
**Ambiguity location:** §4.2 (claims `nav-ui.js:465`), §4.2 tail (claims
`primeSpeech()` at `nav-ui.js:649-654`), and §7.1's `speechSynthesis.cancel()`
reference to `nav-ui.js:464`.

**Facts from codebase:**
- `new SpeechSynthesisUtterance(text)` is at `frontend/nav-ui.js:497`, not
  465. Line 465 lands inside `statusTime.textContent = formatDuration(...)`
  and has nothing to do with TTS.
- `primeSpeech()` is defined at `frontend/nav-ui.js:706`, not 649-654. Lines
  649-654 are inside `enableTerrain()`.
- `speechSynthesis.cancel()` is at line 496, not 464.
- The "Before" code block in §4.2 shows `utterance.lang = 'en-US';` as the
  third line. This IS in the actual code (line 499), but it's the third line
  of `onVoice()`, not of a block starting at line 465 — the spec's framing is
  off-by-a-function.

**Two valid interpretations:**
- A) Trust the spec's line numbers; locate the `Before` block by searching
  those exact line numbers — subagent fails to find a match and either aborts
  or guesses.
- B) Ignore the line numbers, search by content (`new SpeechSynthesisUtterance`).
  Subagent patches the right place but has lost trust in every other line
  citation in the spec (and there are many).

**Subagent most likely to pick:** A first, fail, then B under protest. This is
specifically the failure mode in `feedback_worktree_escape` / "pre-flight
assertions" territory — a subagent running unattended may `Edit` something at
line 465 blindly if a plan restates the number.

**What it should say explicitly:** "Insert the `chosenVoice` two lines
immediately before `speechSynthesis.speak(utterance)` inside the existing
`onVoice(text)` function in `frontend/nav-ui.js`. At time of writing the
function spans approximately lines 494-501; verify by searching for the
string `new SpeechSynthesisUtterance(text)` before editing." Remove all other
line-number citations or prefix them with "approximate; search by content."

---

### F4.2 — `onVoiceListChanged(callback)` callback signature is unspecified

**Severity:** MUST-FIX
**Ambiguity location:** §4.1 public API block.

**Two valid interpretations:**
- A) `callback(voices)` — receives the new array.
- B) `callback(newList, oldList)` — receives both for diffing.
- C) `callback()` — no args, consumer calls `getVoices()` itself.
- D) `callback({voices, source: 'voiceschanged'|'timeout-fallback'})` — event
  object.

**Subagent most likely to pick:** A (single-arg, the new list). But test
`voiceschanged-bootstrap.test.mjs` in §10.1 says "`onVoiceListChanged`
callbacks invoked" without asserting a signature — so a subagent could pick C
and still pass that test, leaving the dropdown renderer broken silently.

**What it should say explicitly:** "`onVoiceListChanged(callback)` —
`callback` is invoked with zero arguments whenever the internal voice list is
refreshed. Consumers should call `getVoices()` or
`VoicePicker.getUtteranceVoice()` themselves. Rationale: the module already
re-filters for `en-*`, so exposing a raw list would tempt consumers to
duplicate filter logic." Then state whether it fires once-on-init or only on
subsequent changes.

---

### F4.3 — `.sr-only` does NOT exist globally; spec asserts it does

**Severity:** MUST-FIX
**Ambiguity location:** §6.1 markup (`class="sr-only"` on the `<label>`), §6.2
bullet ("already defined globally, or added here if not").

**Fact from codebase:** `grep -n "sr-only\|visually-hidden\|screen-reader"
frontend/style.css` returns zero matches. The `.sr-only` class is NOT defined
anywhere in the current codebase.

**Two valid interpretations:**
- A) Subagent reads "already defined globally, or added here if not" as "check
  and add if missing" → adds correct CSS.
- B) Subagent reads the same phrase as "probably already there" → skips
  adding CSS → the hidden label becomes a visible "Specific voice" text node,
  a visible bug.

**Subagent most likely to pick:** B, because the phrase "already defined
globally" is stated as fact first and the "or added here if not" is a
parenthetical. Spec author knew it might not exist but a subagent under time
pressure will pattern-match the dominant assertion.

**What it should say explicitly:** "Add `.sr-only` to `frontend/style.css` as
part of Task [CSS task]. It does not currently exist in the codebase.
Definition:

```css
.sr-only {
  position: absolute;
  width: 1px; height: 1px;
  padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0,0,0,0);
  white-space: nowrap; border: 0;
}
```

"

---

### F4.4 — No sidebar-close EVENT exists; "existing sidebar open/close mechanism" is a local closure

**Severity:** MUST-FIX
**Ambiguity location:** §9.1 ("Reset to `false` on ... Sidebar close (existing
sidebar-toggle close event)"), §9.3 ("On sidebar close: ..."), §7 header
reference.

**Fact from codebase:** The only sidebar toggle lives inside `app.js` at
~line 1169 as a closure-scoped `setSidebarOpen(open)` function. It mutates
classList (`sidebar.classList.add('open')`) but does NOT dispatch any event,
custom or native. `grep -n "dispatchEvent\|CustomEvent"` near that code
returns no sidebar-related dispatches. The function is not hung on `window.`
and is not callable from outside the IIFE.

**Two valid interpretations:**
- A) Subagent registers a `MutationObserver` on `#sidebar`'s class attribute
  watching for removal of `.open`.
- B) Subagent modifies `app.js` to dispatch a new custom event (e.g.
  `document.dispatchEvent(new CustomEvent('sidebar:close'))`) inside
  `setSidebarOpen(false)`.
- C) Subagent polls `sidebar.classList.contains('open')` on a timer.
- D) Subagent silently skips this requirement because "it already exists"
  implies zero code changes — `previewArmed` then never resets on sidebar
  close and preview plays after the user wanders off.

**Subagent most likely to pick:** D under time pressure, A if conscientious.
Both leave the "hang off existing mechanism" framing unimplemented — there is
nothing existing to hang off.

**What it should say explicitly:** Pick exactly one. Recommend B because it
is the only option that doesn't introduce a new coupling shape: "Modify
`frontend/app.js` `setSidebarOpen(open)` (currently at ~line 1169) to
dispatch `document.dispatchEvent(new CustomEvent('geographica:sidebar', {
detail: { open: open } }))` after the classList mutations. `voice-picker.js`
subscribes to this event on `document`. Also count this as a scope expansion
out of the 'one-line `nav-ui.js` change' promise; `app.js` gets a ~4-line
addition."

---

### F4.5 — §4.3 script-ordering says "before nav-ui.js" but not where in the script block

**Severity:** SHOULD-FIX
**Ambiguity location:** §4.3.

**Fact from codebase:** `frontend/index.html:325-332` shows the script order:
`kmz-import` → `import-store` → `app.js` → `silent-video-lock` → `wake-lock`
→ `navigation.js` → `nav-ui.js` → `stt.js`. Existing modules use the
`?v=20260420` cache-bust query string.

**Two valid interpretations:**
- A) Before `nav-ui.js` but after `app.js` (since `VoicePicker.init()` is
  invoked from `app.js` DOMContentLoaded handler per §4.1 contract).
- B) Before `nav-ui.js` but before `app.js`, so `VoicePicker` is defined when
  `app.js` parses.
- C) Adjacent to `wake-lock.js` as a stylistic grouping.

**Subagent most likely to pick:** A. But the spec says `app.js` calls
`VoicePicker.init()` — if A is chosen and `app.js` runs a `VoicePicker.init`
call at script-parse time (not inside `DOMContentLoaded`), the call crashes.
Without explicit guidance, different subagents slot it in different places.

**What it should say explicitly:** "Insert the `<script>` tag immediately
after `wake-lock.js?v=20260420` and before `navigation.js?v=20260420`, with
the same `?v=20260421` cache-bust pattern. `VoicePicker.init()` is called
from `app.js`'s existing `DOMContentLoaded` handler (`app.js:4074`), so load
order relative to `app.js` is moot as long as `VoicePicker` is defined by
DOMContentLoaded."

---

### F4.6 — `storedGenderHint` write behavior when user picks "Default" button is not spelled out

**Severity:** SHOULD-FIX
**Ambiguity location:** §5.4 bullet "Gender button click".

**Fact from spec:** §5.4 says gender-button click writes `{mode: (gender ===
"default" ? "default" : "gender"), gender, voiceURI: null, storedGenderHint:
null, version: 1}`. So `storedGenderHint: null` is in fact stated for
ALL gender buttons including Default. But §8 row 2 ("Saved `voiceURI`
missing") assumes `storedGenderHint` is meaningful after a specific-voice
write, and §7.1 step 3b falls through using it.

**Two valid interpretations:**
- A) Subagent reads §5.4 literally — every gender-button click zeros out
  `storedGenderHint`, including Default. Correct.
- B) Subagent sees `gender` as `"male"|"female"|null` (null only when
  mode=default) and writes `gender: null` for Default. Spec's literal
  serialization contradicts §5.1 — §5.1 allows `gender: null` only when
  `mode` is NOT `"gender"`, and the §5.4 snippet writes the user-chosen
  string unconditionally (so Default would save `gender: "default"`, which
  §5.1 schema does not list as a legal value — schema says `"male" | "female"
  | null`).

**Subagent most likely to pick:** B (follows the schema) OR A (follows §5.4
literal code) — they produce different persisted payloads. Tests won't catch
this unless the subagent writes both write-path and read-path from the same
interpretation.

**What it should say explicitly:** Reconcile §5.1 and §5.4. Rewrite §5.4 as:
"Gender button click — if `data-gender === 'default'`, write `{mode:
'default', gender: null, voiceURI: null, storedGenderHint: null, version:
1}`. Otherwise write `{mode: 'gender', gender: data-gender, voiceURI: null,
storedGenderHint: null, version: 1}`."

---

### F4.7 — IIFE/strict/duplicate-load-guard pattern not prescribed

**Severity:** SHOULD-FIX
**Ambiguity location:** §4.1 (module boundary).

**Fact from codebase:** `frontend/wake-lock.js` opens with exactly:

```js
(function () {
  'use strict';
  if (window.WakeLock) return; // duplicate-load guard
```

Spec says "ES5 IIFE, attached to `window.VoicePicker`, consistent with
existing `frontend/*.js` modules" but does not show the opening, the strict
pragma, or the guard.

**Two valid interpretations:**
- A) Subagent mirrors wake-lock exactly (IIFE + `'use strict'` + duplicate-
  load guard).
- B) Subagent uses a bare top-level `window.VoicePicker = { ... }` object
  literal. Matches the API shape but loses strict-mode checking; if the file
  is accidentally loaded twice (e.g. cache-bust edit lands in both
  index.html and a stale service-worker) it silently re-initializes and
  double-binds event handlers.

**Subagent most likely to pick:** B, because the §4.1 code block IS a bare
object literal:

```js
window.VoicePicker = {
  init: function () { /* ... */ },
  ...
};
```

That sample literally has no IIFE wrapping.

**What it should say explicitly:** In §4.1, replace the code sample with the
wake-lock pattern:

```js
(function () {
  'use strict';
  if (window.VoicePicker) return; // duplicate-load guard
  // ... module-private state ...
  window.VoicePicker = {
    init: function () { /* ... */ },
    getUtteranceVoice: function () { /* ... */ },
    onVoiceListChanged: function (callback) { /* ... */ },
  };
})();
```

---

### F4.8 — "existing primary-accent color" variable name not given

**Severity:** NICE-TO-HAVE
**Ambiguity location:** §6.2 `.pref-voice-btn` bullet.

**Fact from codebase:** `style.css:13` defines `--accent`, `--accent-hover`,
`--accent-muted`. There is no `--primary-accent`.

**Two valid interpretations:**
- A) Subagent greps style.css, finds `--accent`, uses it. Correct.
- B) Subagent invents `--primary-accent` and either adds a new custom
  property (unused elsewhere) or hardcodes a hex.

**Subagent most likely to pick:** A. Low risk, but a plan-author transcribing
the spec may propagate "primary-accent" into a task description.

**What it should say explicitly:** "`.pref-voice-btn.active` — background:
`var(--accent)`, border-color: `var(--accent)`, color: the existing
on-accent text color (verify `--bg` or white)."

---

### F4.9 — Priority chain in §8.1 doesn't specify visual distinction between the two hint messages

**Severity:** SHOULD-FIX
**Ambiguity location:** §8.1 (hint priority chain) vs §6.1 (single
`#pref-voice-hint` element) vs §8 row 3 ("inline italic under the button
row").

**Two valid interpretations:**
- A) Both messages (iOS-low-count and no-gender-match) share the single
  `#pref-voice-hint` element and differ only in text content. Visual
  treatment identical (italic, muted). Acceptable because only one fires
  at a time per the priority chain.
- B) The two messages should render in different places — iOS hint under
  the disclosure, no-match hint under the button row — because §8 row 3
  specifies "inline italic under the button row" and §8 row 1 doesn't
  specify a location. That requires two elements, not one.

**Subagent most likely to pick:** A. Which is fine visually, but §8 row 3's
phrase "under the button row" will trip the subagent writing the Python
structural test `test_preferences_section_markup_present` — the test
currently only asserts ONE `#pref-voice-hint`. No conflict, but a reader of
the spec might over-infer.

**What it should say explicitly:** Add to §8.1: "Both messages render in
the single `#pref-voice-hint` element with identical visual treatment
(small, italic, `.pref-voice-hint` styling). The priority chain guarantees
only one is shown at a time. There is no second element."

---

### F4.10 — "verify in task 1 of the plan" language in §9.3

**Severity:** SHOULD-FIX
**Ambiguity location:** §9.3 parenthetical "(collapsed/hidden during active
nav by existing sidebar behavior, verify in task 1 of the plan)".

**Two valid interpretations:**
- A) Subagent assumes the plan will have a verification subtask and that
  someone else is responsible.
- B) Subagent inserts a defensive check:
  `if (document.body.classList.contains('nav-active')) return;` at the
  top of the preview entry point.

**Fact from codebase:** `nav-ui.js` uses `document.body.classList.contains
('nav-active')` as the nav-active sentinel (lines 1237, 1255, 1317 of
`app.js` — same convention). There IS no existing behavior that
hides/collapses the sidebar during nav. The sidebar remains openable at any
time.

**Subagent most likely to pick:** A, because the spec literally says "verify
in task 1 of the plan" and a plan-authoring subagent may OR may not encode
this as a task — easy to drop.

**What it should say explicitly:** "Add a defensive guard in `VoicePicker`'s
preview entry point: if `document.body.classList.contains('nav-active')`,
skip the preview entirely. Do not rely on sidebar visibility as the gate —
the sidebar is openable at any time, including during active nav." Remove
the "verify in task 1 of the plan" footnote.

---

### F4.11 — `previewArmed` arming conditions omit the disclosure toggle

**Severity:** SHOULD-FIX
**Ambiguity location:** §9.1 bullet: "Set to `true` when a click on
`.pref-voice-btn` or a `change` on `#pref-voice-select` originates from
within the current Preferences interaction."

**Two valid interpretations:**
- A) Clicking the "▾ Pick a specific voice…" disclosure toggle (`.pref-
  voice-advanced-toggle`) does NOT arm preview. User expands, picks a voice,
  `change` fires on the `<select>`, preview fires. Normal flow works.
- B) Clicking the disclosure toggle DOES arm preview because it's "within
  the Preferences interaction."
- C) Subagent interprets "interaction" as "any click inside `#pref-voice`"
  and arms on every click anywhere in the subtree, including stray label
  clicks.

**Subagent most likely to pick:** C, because "within the current Preferences
interaction" is undefined and vague.

**What it should say explicitly:** "Preview is armed strictly on two
user actions: (1) `click` on any `.pref-voice-btn`, (2) `change` on
`#pref-voice-select`. Clicking the disclosure toggle does NOT arm preview,
nor does any click elsewhere in `#pref-voice`."

---

### F4.12 — `click` vs `pointerdown` vs touch events unspecified for button handlers

**Severity:** NICE-TO-HAVE
**Ambiguity location:** §5.4 ("Gender button click"), §9.1 ("click on
`.pref-voice-btn`").

**Two valid interpretations:**
- A) Plain `click` event. Sufficient for desktop + mobile via synthesized
  events. Matches existing codebase conventions.
- B) `pointerdown` for lower latency on touch.
- C) Both `click` and `touchend` to handle broken mobile browsers.

**Subagent most likely to pick:** A, which is correct. Low risk, but worth
locking: "use `click`; matches existing nav-ui.js event model and is
sufficient for iOS/Android WebKit."

**What it should say explicitly:** "Use `click` event listeners throughout.
Do not add `pointerdown`, `touchend`, or dual listeners."

---

### F4.13 — No debug-log convention specified; wake-lock uses `console.warn`

**Severity:** NICE-TO-HAVE
**Ambiguity location:** §7.1 step 3c ("Emit a console.debug for
diagnostic"), §8 row 2 ("`console.debug('VoicePicker: ...')`").

**Fact from codebase:** `wake-lock.js` uses `console.warn('[wake-lock] ...')`
— warn level, bracketed module tag. Spec prescribes `console.debug` in two
places without a tag convention.

**Two valid interpretations:**
- A) `console.debug('VoicePicker: ...')` as literally written.
- B) `console.warn('[voice-picker] ...')` matching the neighbor-module
  convention. (Most browsers hide `console.debug` by default — diagnostic
  messages would not surface when a beta tester captures devtools
  screenshots for a bug report.)

**Subagent most likely to pick:** A (literal), which is almost certainly
wrong for diagnosis.

**What it should say explicitly:** "Use `console.warn('[voice-picker]
<message>', ...args)` for diagnostic logs, matching the `[wake-lock]`
convention in `wake-lock.js`. `console.debug` is too easily filtered out
in beta testers' devtools."

---

### F4.14 — CSS insertion point in style.css unspecified

**Severity:** NICE-TO-HAVE
**Ambiguity location:** §6.2.

**Two valid interpretations:**
- A) Append at end of file (subagent default).
- B) Group near existing `.legend-label` / `.radio-label` selectors since
  §6.2 says `.pref-label` "mirrors the existing `.legend-label` pattern."
- C) Group near the `#nav-mute-btn` selectors because this is "nav-related."

**Subagent most likely to pick:** A.

**What it should say explicitly:** "Append the new selectors to the end of
`frontend/style.css`. No existing CSS block needs to move."

---

### F4.15 — TDD ordering: minimum implementation stub required for `vm.createContext(...)` to load

**Severity:** SHOULD-FIX
**Ambiguity location:** §10.1 (wake-lock-pattern tests) implies TDD but spec
doesn't say.

**Two valid interpretations:**
- A) If plan interleaves task order as "write tests first, then
  implementation," the `node --test` runner needs `voice-picker.js` to at
  least parse and register `window.VoicePicker` with the three public
  method names, or every single test file fails to load at
  `vm.createContext(...)` time — the symptom looks like a test-harness
  bug, not a "implementation not done yet" signal.
- B) Plan author sequences as "implement skeleton → tests → fill in
  implementation → tests pass." Skeleton = IIFE + three empty methods.

**Subagent most likely to pick:** A literally (starts with tests), hits the
VM load failure, spends time debugging.

**What it should say explicitly:** "Before test tasks begin,
`frontend/voice-picker.js` must exist as a skeleton that at minimum
defines `window.VoicePicker = { init: function(){}, getUtteranceVoice:
function(){ return null; }, onVoiceListChanged: function(){} }`. Test
tasks assume this skeleton is loadable via `vm.createContext(...)`. Plan
should sequence this as Task 0 or equivalent."

---

## Summary

- **15 findings** (the cap).
- **Most ambiguous single spot:** F4.4 — "existing sidebar open/close
  mechanism" at §7 and §9.1/§9.3. There is no event, no callable function
  outside an IIFE, and no documented API. A subagent will most likely skip
  the `previewArmed` reset and ship a real UX bug where preview audio plays
  after the user has closed the sidebar.
- **Runner-up:** F4.1 — line numbers cited throughout the spec are all
  wrong, which will misdirect any subagent that trusts them blindly.
- **Pattern across findings:** the spec repeatedly defers to "existing
  conventions" that do not actually exist in the codebase (`sr-only`,
  `--primary-accent`, `sidebar-close event`) or cites wrong line numbers.
  Nine of 15 findings trace back to this one failure mode.
