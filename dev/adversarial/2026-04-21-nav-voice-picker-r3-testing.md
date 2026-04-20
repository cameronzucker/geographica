---
round: 3
angle: Testing sufficiency
reviewer: general-purpose (Claude Opus 4.7)
date: 2026-04-21
---

## Scope

Adversarial review of §10 (Testing strategy) of
`docs/superpowers/specs/2026-04-21-nav-voice-picker-design.md`. Cross-checked
against the wake-lock reference pattern at `frontend/tests/wake-lock/`,
`tests/test_wake_lock_static.py`, and `.github/workflows/frontend-ci.yml`
— all of which are in-tree and landed at HEAD `b127060`.

Methodology: walked each listed unit and structural test, looked for bug classes
the test **cannot** catch, checked fixture coverage against real-world voice-list
shapes, and assessed whether tests are writable BEFORE implementation (TDD red).

## Findings summary

- MUST-FIX: 4
- SHOULD-FIX: 7
- NICE-TO-HAVE: 3
- **Total: 14**

Most dangerous coverage gap: **F3.1** (iOS Safari `voiceschanged` staleness —
the spec's mocks model `voiceschanged` → `getVoices()` as atomic, but the real
iOS 17 Safari bug is a ~100 ms gap where `getVoices()` still returns stale
voices after the event fires. No proposed test can catch this, and the manual
checklist Item 7 doesn't exercise it either).

---

### F3.1 — `voiceschanged` staleness not modeled; iOS Safari bug will ship silently

**Severity:** MUST-FIX
**Claim/gap in spec:** §10.1 `voiceschanged-bootstrap.test.mjs` and §7.3
**Bug class that could ship:** On iOS 17+ Safari, `voiceschanged` fires but
`getVoices()` returns the stale (empty or 2-voice) list for ~100 ms afterwards.
`getUtteranceVoice()` memoizes against the stale list (§7.2), then the user's
first nav prompt uses the wrong voice — or the hint flashes "Only a few voices
detected" and then disappears on the next `voiceschanged`, which feels buggy.
**Proposed fix:** Add `voiceschanged-staleness.test.mjs` with a mock that
exposes two sequential `getVoices()` results behind the same `voiceschanged`
event. Test that the module either (a) re-reads `getVoices()` on each utterance
resolution rather than only on `voiceschanged`, or (b) uses a short rAF/tick
re-read after the event. Also add manual-checklist Item 13: "on real iPhone
hardware, observe that the first nav utterance after cold-start uses the
selected voice (not the device default)."
**Test specification:**
```
Input: mocked speechSynthesis.getVoices() returns [] on first call,
  still [] on call made 0 ms after voiceschanged fires, then
  [<10 voices>] on call made 1 tick later.
Expected: getUtteranceVoice() returns a voice from the 10-voice list, not null.
  onVoiceListChanged fires exactly once with the non-empty list, not twice.
```

---

### F3.2 — Structural test `test_voice_picker_loaded_before_nav_ui` models wrong contract

**Severity:** SHOULD-FIX
**Claim/gap in spec:** §10.2 `test_voice_picker_loaded_before_nav_ui`
**Bug class that could ship:** The spec says "script load order enforced by
order of appearance" (§4.3), which is correct for Geographica today —
`frontend/index.html` lines 325-332 show all `<script src=...>` tags are plain
(no `async`, no `defer`, no `type="module"`). But if anyone adds `defer`
globally as a future perf optimization, `voice-picker.js` loading BEFORE
`nav-ui.js` in source order is meaningless; both `defer`-ed scripts execute at
DOMContentLoaded in source order, which is the same contract, but `async`
breaks it. The structural test as specified won't distinguish. It also won't
catch the real failure mode: the `app.js` call to `VoicePicker.init()` running
before `<script src="voice-picker.js">` has executed due to a missing tag.
**Proposed fix:** Add assertion that no `<script>` tag on `voice-picker.js` or
`nav-ui.js` has `async` attribute. Add assertion that `voice-picker.js` has a
`?v=YYYYMMDD` cache-buster matching the wake-lock pattern (§10.2 omits this
and `test_index_html_scripts_have_cache_buster` in the wake-lock tests only
lists silent-video-lock / wake-lock / nav-ui / navigation).
**Test specification:**
```
Input: frontend/index.html
Expected:
  - <script src="voice-picker.js?v=\d+"> tag present
  - voice-picker.js index < nav-ui.js index < app.js index (check all three)
  - No async attribute on voice-picker.js, nav-ui.js, or app.js script tags
```

---

### F3.3 — `KNOWN_VOICES` regression tests missing entirely

**Severity:** MUST-FIX
**Claim/gap in spec:** §10.2 — no test for duplicate keys, value typos, or the
table being non-empty.
**Bug class that could ship:** Three concrete bugs:
1. Duplicate keys in the object literal silently overwrite. JS has no duplicate-
   key error at runtime. If someone adds a second `'Susan': 'male'` later in the
   literal, the female value is overwritten and male-selecting users who have
   Susan installed get inconsistent behavior.
2. Value typo (`'Male'` vs `'male'`, or `'femaale'`) — the gender-match scan
   in §7.1 step 3c compares via strict equality. A typo silently breaks gender
   inference for that voice; no runtime error.
3. The table gets emptied in a merge conflict resolution and no test notices.
**Proposed fix:** Three new JS unit tests in `gender-inference.test.mjs` (or a
new `known-voices.test.mjs`):
**Test specification:**
```
Test 1 — no duplicate keys:
  Input: parse voice-picker.js source; extract KNOWN_VOICES literal text
  between `var KNOWN_VOICES = {` and matching `};`.
  Extract key strings (regex on quoted tokens before `:`).
  Expected: len(keys) === len(set(keys)).

Test 2 — values are only "male" or "female":
  Input: require()/vm-load voice-picker.js; iterate Object.values(KNOWN_VOICES).
  Expected: every value is either "male" or "female" (strict ===).

Test 3 — table has at least 20 entries (non-empty regression guard):
  Input: Object.keys(KNOWN_VOICES).length.
  Expected: >= 20.
```

---

### F3.4 — Gender-inference word-boundary regex not tested for false positives

**Severity:** MUST-FIX
**Claim/gap in spec:** §10.1 `gender-inference.test.mjs` — "30 known voice
names → correct gender; 5 substring-match cases; 3 unknown cases → `null`."
**Bug class that could ship:** §5.3 shows the fallback regex as
`/\bmale\b|\bman\b|\bboy\b/i`. Without explicit test cases, a naive
implementation could ship with `/male|man|boy/i` (no `\b`), which incorrectly
matches "female" → "male", "woman" → "man". The spec comment flags this but
the test suite never exercises it. The one-off `// note \b to avoid matching
"female"` comment in §5.3 is not enforced by any test.
**Proposed fix:** Extend `gender-inference.test.mjs` with explicit
anti-false-positive cases:
**Test specification:**
```
Input: inferGender("Google US English Female") → "female"
Input: inferGender("femaleness") → null (not "male")   # word boundary test
Input: inferGender("Emanuel") → null (not "male")      # "man" substring in "Emanuel"
Input: inferGender("Norman") → null (not "male")       # "man" substring
Input: inferGender("Woman") → "female"
Input: inferGender("Boyce") → null (not "male")        # "boy" substring
Input: inferGender("") → null
Input: inferGender("Microsoft Female - English")       → "female"
Input: inferGender("Microsoft George - English") → "male" (exact table match)
```

---

### F3.5 — `test_no_shrek_references` is cute, not load-bearing

**Severity:** NICE-TO-HAVE
**Claim/gap in spec:** §10.2 `test_no_shrek_references`
**Bug class that could ship:** None. This is a mood regression — not a
functional one. A future product decision to revisit Shrek voice (perhaps via
a vendored sample pack) would require deleting the test, which produces
friction for no benefit. It also can false-fire: if the spec itself is linked
from `frontend/CHANGELOG.md` and the changelog gets copy-pasted into the
frontend tree, the test fails.
**Proposed fix:** Replace with a test that IS load-bearing: a regression guard
that `nav-ui.js` still calls `speechSynthesis.cancel()` exactly once before
`speechSynthesis.speak()` per utterance (this is the "cancel-then-speak" flow
the spec preserves at [nav-ui.js:464-468](../../../frontend/nav-ui.js#L464-L468)).
If a future refactor drops the cancel, nav prompts queue up and overlap.
**Test specification:**
```
Input: parse nav-ui.js; find all occurrences of speechSynthesis.speak(.
Expected: each speak() call is preceded within 3 lines by speechSynthesis.cancel().
  (Same brace-tracking / comment-stripping approach as wake-lock tests.)
```

---

### F3.6 — `primeSpeech()` regression not tested

**Severity:** SHOULD-FIX
**Claim/gap in spec:** §10.1 and §10.2 — §4.2 explicitly says
`primeSpeech()` is NOT changed, but no test enforces this.
**Bug class that could ship:** A subagent executing the plan misreads §4.2
and threads voice selection into `primeSpeech()` "for consistency," which adds
first-utterance latency (the whole point of not doing it, per §4.2). Or
deletes `primeSpeech()` because "we always set voice now, why prime?" —
breaking the iOS gesture-context priming that was the whole reason the function
exists. §4.2 calls this out but it's not test-enforced.
**Proposed fix:** Add a Python structural test:
**Test specification:**
```
Input: frontend/nav-ui.js
Expected: function_body("function primeSpeech()") contains:
  - "volume" (the zero-volume priming marker)
  - "SpeechSynthesisUtterance"
  - "speak("
  And does NOT contain:
  - "VoicePicker"
  - "getUtteranceVoice"
  - "utterance.voice = "
```

---

### F3.7 — `name="units"` selector regression test insufficient

**Severity:** SHOULD-FIX
**Claim/gap in spec:** §10.2 `test_units_radios_still_named_units`
**Bug class that could ship:** The spec invariant (§6.1) is that
`document.querySelectorAll('input[name="units"]')` at
[nav-ui.js:85-87](../../../frontend/nav-ui.js#L85-L87) still resolves to 2
elements. A test that just checks for the presence of `<input type="radio"
name="units"` passes even if the markup is broken to 0 or 5 radios, or if the
elements are `<input type="checkbox">`. More subtly: moving them inside a
`.pref-group` with a new wrapper div is fine, but if a subagent wraps them in a
`<template>` tag as an "optimization," `querySelectorAll` returns 0 elements
and Units radios silently stop working.
**Proposed fix:** Exact-count and type-enforcing regression tests.
**Test specification:**
```
Test A: exactly 2 <input type="radio" name="units"> elements in index.html
  (one with value="imperial" and one with value="metric")
Test B: exactly 4 <input type="radio" name="coordfmt"> elements with values
  {dd, dms, maidenhead, mgrs}
Test C: the <input name="units"> elements are NOT nested inside a <template>
  or <script> or commented out.
```

---

### F3.8 — Preview-gate test can't detect the cross-origin sidebar-close signal

**Severity:** SHOULD-FIX
**Claim/gap in spec:** §10.1 `preview-gate.test.mjs` — "Simulated sidebar close
→ false."
**Bug class that could ship:** The spec relies on an "existing sidebar-toggle
close event" (§9.1) but doesn't say what that event is named or how the voice
picker listens. In the current codebase, `frontend/app.js` controls the
sidebar; no cross-module event bus is mentioned. If the implementation dispatches
`CustomEvent('sidebar:close')` on `window` but `preview-gate.test.mjs` mocks
`document.addEventListener`, the test passes against the mock but fails in
production. Cross-check: the wake-lock reference pattern calls
`doc._fire('visibilitychange')` — but this only works because `visibilitychange`
is a W3C-standard `document` event. Sidebar-close is a custom event and needs
its emission point pinned down in the spec or the plan.
**Proposed fix:** Either (a) spec the event name and dispatch target in §9.1
before plan-writing begins, or (b) have `preview-gate.test.mjs` exercise the
actual public API that resets `previewArmed` (e.g. `VoicePicker._testResetGate()`
or equivalent) rather than the event plumbing.
**Test specification:**
```
Spec addition required: §9.1 must name the exact event — one of:
  - window.addEventListener('geographica:sidebar-close', ...)
  - document.dispatchEvent(new CustomEvent('sidebar:close'))
  - a VoicePicker.notifySidebarClosed() imperative method called from app.js
Pick one. Otherwise the test can't fire the event the same way production will.
```

---

### F3.9 — Fixture completeness: no mock voice list for Windows Edge or Linux Firefox

**Severity:** SHOULD-FIX
**Claim/gap in spec:** §10.1 `voice-resolution.test.mjs` — lists "10 voices
(macOS-like), 2 voices (iOS default), empty list, list without any en-* voice."
**Bug class that could ship:** Windows Edge voice names are of the form
`Microsoft Zira - English (United States)`. The gender-inference scan in
§7.1 step 3c calls `inferGender(v.name)` — but is "v.name" the full
`"Microsoft Zira - English (United States)"` or the short token `"Zira"`?
§5.3 says "name is first token of full voice name" but the implementation
has to actually do the tokenization. Without a Windows-Edge-shaped fixture,
the exact-match table lookup silently misses because `KNOWN_VOICES['Microsoft Zira - English (United States)']` is undefined. Linux Firefox's eSpeak
voices have names like `"english"` or `"english-us"` — lowercase, no gender
hint, not in the table.
**Proposed fix:** Add four named fixture sets in `_fixtures.js`:
**Test specification:**
```
Fixture A — macOS Safari (10 voices): names include "Samantha", "Alex",
  "Daniel", "Fred", plus "Google US English" (Chrome-also), "Tom", "Karen",
  "Victoria", "Moira", "Rishi". voiceURI includes apple-style
  "com.apple.ttsbundle.Samantha-compact".
Fixture B — iOS default (2 voices): "Samantha" en-US and "Daniel" en-GB, no
  voice whose name matches "male"/"female" substring.
Fixture C — Windows Edge (6 voices): "Microsoft Zira - English (United States)",
  "Microsoft David - English (United States)", "Microsoft Mark - English (United States)",
  "Microsoft Hazel - English (Great Britain)", "Microsoft George - English (Great Britain)",
  "Microsoft Susan - English (Great Britain)".
Fixture D — Linux Firefox eSpeak (3 voices): "english", "english-us", "english-rp";
  no gender-hint-containing strings; lang values "en", "en-US", "en-GB".
Tests: Fixture C "Male" selection resolves to Microsoft David; Fixture D
"Male" selection returns null (no match, hint shown). Fixture D "Default"
returns null (device default). All four fixtures tested against
getUtteranceVoice() in all three modes.
```

---

### F3.10 — Unusual voice-shape edge cases not fixtured

**Severity:** SHOULD-FIX
**Claim/gap in spec:** §10.1 — no coverage of degenerate voice objects.
**Bug class that could ship:** Real `getVoices()` implementations have
returned:
- Voice with empty `name` string (seen on some older Chrome versions).
- Voice with unicode `name` (e.g. Google's Japanese voices sometimes leak into
  the en-* filter if `lang` is mis-tagged).
- Multiple voices with `default: true` (Samsung browsers).
- `lang` without a dash: `"en"` (espeak).
- `lang` with underscore: `"en_US"` (rare).
- `voiceURI` that equals `name` (Firefox Linux).
§7.1 step 2 filter `/^en[-_]?/i.test(v.lang)` handles the separator cases, but
`inferGender("")` and duplicate-default voices are untested. A crash in
`inferGender(undefined)` when `v.name` is falsy would break getUtteranceVoice()
per G6 contract ("Never throws").
**Proposed fix:** Add edge-case fixture voices and assert non-throw:
**Test specification:**
```
Input: getVoices() returns [
  { name: "", lang: "en-US", voiceURI: "weird-1" },
  { name: undefined, lang: "en-US", voiceURI: "weird-2" },
  { name: "Samantha", lang: "en-US", voiceURI: "com.apple.samantha", default: true },
  { name: "Daniel", lang: "en-GB", voiceURI: "com.apple.daniel", default: true },
  { name: "日本語", lang: "en-US", voiceURI: "weird-3" },
]
Expected: getUtteranceVoice() with mode="gender", gender="female" returns Samantha
  without throwing. inferGender("") returns null. inferGender(undefined) returns
  null (does not throw TypeError).
```

---

### F3.11 — Manual acceptance Items 7, 9, 10 are unexecutable without tooling

**Severity:** SHOULD-FIX
**Claim/gap in spec:** §10.3 Items 7 ("iOS low-voice hint"), 9 ("No gender
match (synthetic)"), 10 ("Empty voice list stub (synthetic)").
**Bug class that could ship:** These items say "synthetic" but don't say HOW
to synthesize. "Mock `getVoices()` on a real device" is not a documented
procedure. A beta tester or Cameron running the manual checklist sees "Item 10:
mock getVoices() to always return []" and has no clear path — DevTools console?
Patched app.js? Browser extension? Item 7 says "on iPhone with default voice
install" — but what constitutes default? iOS ships with a single default voice
per locale; "default voice install" on a fresh iPhone gives ~10 en-* voices
depending on region, which fails the `<= 3` threshold.
**Proposed fix:** The plan (not the spec) must add a debug-only affordance:
**Test specification:**
```
Add to plan (not spec): a debug query parameter `?voice-picker-mock=<fixture-name>`
that, when present AND location.hostname matches dev/localhost/pandora.*.ts.net,
forces VoicePicker to use a named fixture instead of the real getVoices().
Fixture names: "empty", "low-ios", "many", "no-male", "no-female".
Checklist Items 7/9/10 then become:
  - Item 7: visit /?voice-picker-mock=low-ios — hint appears.
  - Item 9: visit /?voice-picker-mock=no-male — click Male — mismatch hint.
  - Item 10: visit /?voice-picker-mock=empty — after 5s, stub replaces group.
Alternative: document the exact DevTools override snippet in §10.3 comments.
```

---

### F3.12 — CI workflow path-filter will not trigger on voice-picker changes

**Severity:** MUST-FIX
**Claim/gap in spec:** §10 — no mention of CI wiring; spec assumes existing
`.github/workflows/frontend-ci.yml` picks up new tests.
**Bug class that could ship:** Examined `.github/workflows/frontend-ci.yml` at
HEAD: lines 16-19 and 23-26 specify path triggers including `frontend/**`,
`tests/test_wake_lock_*.py`, `tests/test_frontend_*.py`. A new
`tests/test_voice_picker_static.py` file matches NONE of these globs. A PR
that touches only that test file plus `docs/` won't trigger the CI workflow at
all. The JS tests under `frontend/tests/voice-picker/` are covered (they match
`frontend/**`), but the Python structural tests for the voice picker won't
run on PR.
**Proposed fix:** Spec §10 must call out this CI config change. Either:
(a) rename the voice-picker static test to `tests/test_frontend_voice_picker.py`
to match the existing `test_frontend_*.py` glob, OR
(b) add `tests/test_voice_picker_*.py` to both `push` and `pull_request`
triggers in `frontend-ci.yml`.
**Test specification:**
```
Either path must be called out in §10 or a new §10.4 "CI integration".
Preferred path: rename to tests/test_frontend_voice_picker.py (no workflow edit
needed; matches existing glob tests/test_frontend_*.py). Then add a
self-verifying structural test:
  def test_frontend_ci_workflow_triggers_on_voice_picker_tests():
    workflow = read(".github/workflows/frontend-ci.yml")
    assert "tests/test_frontend_*.py" in workflow
      or "tests/test_voice_picker_*.py" in workflow
```

---

### F3.13 — TDD red-green requires implementation details missing from spec

**Severity:** SHOULD-FIX
**Claim/gap in spec:** §4.1 API + §10.1 tests; the plan will execute via
subagent-driven-development, which requires TDD.
**Bug class that could ship:** A subagent tasked with "write the tests first,
then implement" for `gender-inference.test.mjs` needs to know:
- Is `inferGender` exported? (§5.3 calls it a module-private function, but
  §10.1 says "30 known voice names → correct gender" — how does the test
  call the private function?) The wake-lock reference uses vm context and
  reaches into module-internal state via `win.WakeLock.<method>`; but
  `VoicePicker.inferGender` is not listed in §4.1 public API.
- What's the expected format of the hint element's text? §8.1 describes the
  logic but not the exact strings. Hint-text assertion in
  `preview-gate.test.mjs` or a new `hint-text.test.mjs` can't be written
  without knowing the exact copy.
- The dropdown rendering's DOM shape: `<option value="<voiceURI>">...</option>`
  with what label? `v.name` alone, or `v.name + " (" + v.lang + ")"`?
**Proposed fix:** The plan (not this spec) must specify:
**Test specification:**
```
1. Add VoicePicker.inferGender to §4.1 public API, OR add an underscore-
   prefixed test-only property (e.g. VoicePicker._inferGender) with contract
   "for tests only, not a stable API."
2. Pin exact hint text strings in §8 (currently templated in italics — a plan
   task must lock them as constants).
3. Pin dropdown label format in §6.1 (currently the <select> is empty
   markup; the render logic is implicit).
```

---

### F3.14 — `localStorage` version-schema backward-compat not tested

**Severity:** SHOULD-FIX
**Claim/gap in spec:** §10.1 `preference-persistence.test.mjs` — "Corrupt
JSON → default. Unknown version → default."
**Bug class that could ship:** §5.1 defines `version: 1` and §7.1 step 2
says "If parsed.version !== 1, treat as {mode: default}." But the test only
covers corrupt JSON and missing version — not a future `version: 2` value
that would also silently fall to default, losing the user's existing
preference on every version bump. More concretely: a returning user on
`version: 1` who upgrades to a future `version: 2` should have their
`mode/gender/voiceURI` migrated, not dropped. No migration path is tested,
and the spec's "unknown version = default" rule makes it impossible to add
non-breaking upgrades later.
**Proposed fix:** Either (a) change §7.1 step 2 to read `parsed.version <= 1`
with explicit migration hooks, or (b) accept the silent-reset-on-upgrade
behavior and test it explicitly so future contributors see the decision:
**Test specification:**
```
Test — write path always stamps version: 1:
  Trigger every write path in §5.4; parse localStorage; assert version === 1.

Test — forward-version graceful fallback:
  Input: localStorage[nav-voice-pref] = '{"mode":"gender","gender":"male","version":2}'
  Expected: getUtteranceVoice() returns null (as per §7.1 step 2).
  Also: the write happens on next UI interaction with version: 1 (clobber
  behavior is OK if documented).

Test — explicitly document the "we do not migrate" decision in §7.1 or a
  new §7.4 so a future dev knows this was chosen, not forgotten.
```

---

## Cross-cutting observations

1. **Mock pattern is sound for what it covers.** The wake-lock `node:vm`
   approach is appropriate for `voice-picker.js` — same IIFE style, same
   no-ES6-module constraint. Fixtures file pattern transfers directly.

2. **Three of the MUST-FIX findings (F3.1, F3.3, F3.4, F3.12) are about what's
   NOT in the test list**, not about bugs in what IS there. The existing
   proposed tests are competent; the gap is breadth.

3. **The structural-test-brittleness risk (F3.2, F3.7) is real but bounded.**
   Python-regex-on-JS tests do false-fail on renames, but the wake-lock tests
   at `tests/test_wake_lock_static.py` handle this with `strip_js_noise` /
   `function_body` helpers that parse braces. Reuse them.

4. **Manual checklist is the weakest layer.** Items 7, 9, 10 need tooling.
   Item 11 (a11y) needs a defined screen-reader-test owner — Geographica has
   no precedent process. Either spec one or reduce Item 11 to "smoke: aria
   attributes present" (which is testable structurally).

5. **Field test owner.** Spec doesn't say who runs the manual checklist on
   Android Chrome — Cameron has a Pixel per prior handoffs, but this should
   be named in the spec so it doesn't get skipped.
