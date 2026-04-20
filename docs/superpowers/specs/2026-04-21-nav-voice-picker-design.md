# Nav Voice Picker — Design Spec

**Date:** 2026-04-21
**Scope:** Let Geographica nav users choose a preferred voice (male / female / specific voice) for turn-by-turn audio prompts, persisted per-device in localStorage. Replaces the current "browser picks a voice" default.
**Files:** `frontend/voice-picker.js` (new), `frontend/nav-ui.js` (one-line integration change), `frontend/index.html` (Preferences section markup), `frontend/style.css` (Preferences CSS), `frontend/tests/voice-picker/` (new JS unit tests), `tests/test_voice_picker_static.py` (new Python structural tests).
**Related:** Grew from a beta-tester request ("Shrek voice"). Shrek voice is out of scope — it isn't in any OS voice list, and actual voice cloning (XTTS / Bark) is infeasible on a Pi and legally questionable. Feature delivers the legitimate half (male / female / specific voice) that was the real gap. Pattern follows [2026-04-20-nav-keep-awake-design.md](2026-04-20-nav-keep-awake-design.md) for module boundaries, testing shape, and deployment assumptions.

## Revision history

- **v1 (2026-04-21)** — Initial design. Brainstormed via visual-companion (4 interactive questions: granularity, location, preview behavior, edge cases). All four user decisions captured in §3.

---

## 1. Summary

Geographica's turn-by-turn nav speaks instructions via the browser's Web Speech API — `new SpeechSynthesisUtterance(text)` with no voice selected ([nav-ui.js:462-469](../../../frontend/nav-ui.js#L462-L469)). The browser picks whatever voice it defaults to, which is usually device- and locale-specific and feels random across sessions.

This spec adds a **per-device voice preference** stored in localStorage, controlled by a new **"Preferences"** section in the sidebar. The user gets three quick buttons — Default / Male / Female — with an optional disclosure that reveals the full installed-voice list for power users.

The feature is entirely client-side. The Raspberry Pi sees no change — speech synthesis happens on the device rendering the UI (driver's phone, in-vehicle tablet, etc.). No network dependency, no server changes, no new data-pipeline artifacts.

## 2. Goals & non-goals

### Goals

- **G1.** User can pick a voice preference (Male / Female / Default) in one tap and hear it immediately in the current expansion cycle.
- **G2.** Power users can override gender inference and pick a specific installed voice by name from a disclosure-revealed dropdown.
- **G3.** Preferences persist in localStorage per-device across page reloads and across voice-list reshuffles within reason.
- **G4.** Zero regression to the existing `onVoice()` call site in `nav-ui.js` beyond a single line that assigns `utterance.voice`. The existing mute button, mute state, priming behavior, and cancel-on-new-utterance logic all remain unchanged.
- **G5.** Feature is silently degraded on browsers without Web Speech API — the Preferences voice group hides itself; the nav overlay's mute button is unaffected.
- **G6.** Module boundary: voice enumeration, gender inference, preference persistence, preview logic, and dropdown rendering all live in `frontend/voice-picker.js`. `nav-ui.js` holds no voice-picker concerns beyond the single `utterance.voice = VoicePicker.getUtteranceVoice()` assignment.
- **G7.** iOS Safari specifically works: low voice count is detected and the user sees an inline hint pointing to iOS Settings for adding voices; saved `voiceURI` surviving a voice uninstall falls back to the stored gender hint silently.

### Non-goals

- **NG1.** Cross-device voice synchronization. Each device keeps its own preference; no Pi-side storage.
- **NG2.** Voice rate / pitch / volume sliders. YAGNI; no user has asked for this.
- **NG3.** Per-route voice overrides.
- **NG4.** Localization beyond `en-*`. Geographica is English-only today; the voice picker filters `getVoices()` via `/^en[-_]?/i` on `voice.lang` (tolerating `en-US`, `en_US`, `en`, case-insensitively). Expanding to other locales is a future spec.
- **NG5.** Server-side TTS / neural voice synthesis. The user explicitly hard-skipped Shrek-voice-style novelty in brainstorming; legitimate voice cloning (XTTS, Bark) is infeasible on a Pi 5 for interactive nav latency.
- **NG6.** Any change to the nav-overlay mute button or its localStorage key (`nav-muted`). The mute toggle remains a separate concern.
- **NG7.** Migration of existing users' nav experience. Voice preference defaults to "Default" (= browser default = current behavior) for any user who has not opened the Preferences section.
- **NG8.** Exposing or editing the gender-inference table via UI. It's a hardcoded module-private constant.

## 3. User-facing decisions locked via brainstorming

- **Q1 — Granularity:** Hybrid. Gender quick-pick (3 buttons) plus an "advanced disclosure" to reveal the full voice list. Matches the `feedback_optional_input_hidden_by_default` pattern.
- **Q2 — Location:** New **Preferences** section in the sidebar, absorbing the existing Units and Coordinates radios (previously peer `<h3>` sections in [index.html:108-128](../../../frontend/index.html#L108-L128)). Rationale: voice picker on its own felt like a lonely single-item section; folding Units + Coordinates in makes the section feel substantive.
- **Q3 — Preview behavior:** Auto-preview on selection, **gated on the Preferences section being in an "expanded" state** (i.e. the user has just clicked a voice button in this interaction cycle). Does not fire on page-load / localStorage restore. See §7 for the precise gate.
- **Q4 — Edge cases:** All four defaults approved (see §8).

## 4. Architecture

### 4.1 Module boundary

New file: [frontend/voice-picker.js](../../../frontend/voice-picker.js).

Public API (ES5 IIFE, attached to `window.VoicePicker`, consistent with existing `frontend/*.js` modules):

```js
window.VoicePicker = {
  init: function () { /* ... */ },
  getUtteranceVoice: function () { /* returns SpeechSynthesisVoice | null */ },
  onVoiceListChanged: function (callback) { /* ... */ },
};
```

**Contract:**

- `init()` — called once from `app.js` during DOM-ready. Attaches DOM event handlers to `#pref-voice` sub-tree. Loads saved preference from localStorage. Starts a `voiceschanged` listener and a 5-second fallback timer (§8).
- `getUtteranceVoice()` — called from `nav-ui.js` per utterance. Returns a `SpeechSynthesisVoice` object to assign to `utterance.voice`, or `null` to let the browser pick. Never throws. Memoizes its result across calls within the same voice-list revision.
- `onVoiceListChanged(callback)` — registers a callback fired whenever the module-internal voice list is refreshed (on initial `voiceschanged` or when the fallback timer detects an empty list). Used internally by the dropdown renderer; exposed in case `nav-ui.js` or a future consumer needs to react.

### 4.2 Integration point in `nav-ui.js`

Exactly one change, at [nav-ui.js:465](../../../frontend/nav-ui.js#L465):

```js
// Before
var utterance = new SpeechSynthesisUtterance(text);
utterance.rate = 1.0;
utterance.lang = 'en-US';
speechSynthesis.speak(utterance);

// After
var utterance = new SpeechSynthesisUtterance(text);
utterance.rate = 1.0;
utterance.lang = 'en-US';
var chosenVoice = window.VoicePicker && window.VoicePicker.getUtteranceVoice();
if (chosenVoice) utterance.voice = chosenVoice;
speechSynthesis.speak(utterance);
```

Null-guard on `window.VoicePicker`: in the degenerate case where `voice-picker.js` fails to load (404, CSP block), nav-ui.js keeps working exactly as it does today.

**[nav-ui.js:649-654 `primeSpeech()`](../../../frontend/nav-ui.js#L649-L654) is NOT changed** — priming is about waking up the speech engine with an empty utterance at `volume = 0`; voice selection is irrelevant and would add first-utterance latency if we resolved it here. The voice is only set on real nav prompts via the change shown above.

### 4.3 Script load order

[frontend/index.html](../../../frontend/index.html) `<script>` tags — `voice-picker.js` loads **before** `nav-ui.js` (and `app.js` which calls `VoicePicker.init()`). `nav-ui.js` already checks for `window.speechSynthesis` at init; no ordering guarantee needs to be added for speech detection itself.

## 5. Data model

### 5.1 localStorage schema

**Key:** `nav-voice-pref` (singular key, matches the existing `nav-muted` key convention).

**Value:** JSON-stringified object.

```json
{
  "mode": "default" | "gender" | "specific",
  "gender": "male" | "female" | null,
  "voiceURI": "com.apple.ttsbundle.Samantha-compact" | null,
  "storedGenderHint": "male" | "female" | null,
  "version": 1
}
```

- `mode` — which source of truth to use when resolving the voice.
- `gender` — meaningful only when `mode === "gender"`. Drives `getUtteranceVoice()` gender-match scan.
- `voiceURI` — meaningful only when `mode === "specific"`. Matched against `v.voiceURI` in the current voice list.
- `storedGenderHint` — populated whenever the user picks a specific voice if that voice has an inferrable gender. Used as the *fallback* when a saved `voiceURI` is no longer present on the device (§8 Scenario 2). `null` if the originally chosen specific voice had no known gender.
- `version` — forward-compat marker. `1` for this spec. `getUtteranceVoice()` treats any unknown version as `{mode: "default"}` silently (corruption-resilient).

### 5.2 Default state

A user who has never opened the Preferences voice group has no `nav-voice-pref` key in localStorage. `getUtteranceVoice()` returns `null` → `utterance.voice` is not set → identical to current `main` behavior.

### 5.3 Gender-inference table

Module-private constant in `voice-picker.js`. Covers the ~30 commonly-installed voices across Apple (macOS/iOS), Google (Android/Chrome), Microsoft (Edge/Windows). Values are `"male"`, `"female"`.

```js
var KNOWN_VOICES = {
  // Apple — iOS + macOS Safari (names as reported by getVoices())
  'Samantha': 'female', 'Karen': 'female', 'Moira': 'female', 'Tessa': 'female',
  'Victoria': 'female', 'Veena': 'female', 'Fiona': 'female',
  'Kate': 'female', 'Serena': 'female',
  'Alex': 'male', 'Daniel': 'male', 'Fred': 'male', 'Oliver': 'male',
  'Tom': 'male', 'Rishi': 'male', 'Aaron': 'male',
  // Microsoft — Edge on Windows (name is first token of full voice name)
  'Zira': 'female', 'Hazel': 'female', 'Susan': 'female',
  'David': 'male', 'Mark': 'male', 'George': 'male', 'James': 'male',
};
```

**Substring fallback** for Google-style voice names that embed gender in the string:

```js
function inferGender(voiceName) {
  // 1. Exact token match against KNOWN_VOICES after splitting on common separators.
  // 2. /\bfemale\b|\bwoman\b|\bgirl\b/i  → "female"
  // 3. /\bmale\b|\bman\b|\bboy\b/i       → "male"   (note \b to avoid matching "female")
  // 4. Unknown                             → null
}
```

**Scope of the table:** this is the *only* shared data between the gender buttons and the rest of the system. No CSV file, no YAML, no external fetch. Hardcoded. Adding a voice is a one-line code change.

### 5.4 Write paths — when `nav-voice-pref` is persisted

Preference writes happen in exactly three places, all inside `voice-picker.js`:

- **Gender button click** (`.pref-voice-btn`) — writes `{mode: (gender === "default" ? "default" : "gender"), gender, voiceURI: null, storedGenderHint: null, version: 1}`.
- **Specific voice chosen** (`#pref-voice-select` `change`) — writes `{mode: "specific", gender: null, voiceURI: select.value, storedGenderHint: inferGender(voice.name), version: 1}`. `storedGenderHint` is populated *at write time* from the inference table so that a later voice uninstall doesn't lose the fallback signal.
- **Dropdown reset to "(auto)"** — if the dropdown has an explicit "Use Default / Male / Female" leading option and the user picks it, the write mirrors the gender-button path.

Reads happen only in `getUtteranceVoice()` per §7 and in the sidebar render pass (to highlight the active button / select option).

### 6.1 index.html

Replace [index.html:108-128](../../../frontend/index.html#L108-L128) (current standalone `<h3>Units</h3>` and `<h3>Coordinates</h3>` sections) with:

```html
<h3>Preferences</h3>

<div class="pref-group" id="pref-voice">
  <div class="pref-label">Nav voice</div>
  <div class="pref-voice-buttons" role="radiogroup" aria-label="Navigation voice gender">
    <button type="button" class="pref-voice-btn active" data-gender="default"
            role="radio" aria-checked="true">Default</button>
    <button type="button" class="pref-voice-btn" data-gender="male"
            role="radio" aria-checked="false">Male</button>
    <button type="button" class="pref-voice-btn" data-gender="female"
            role="radio" aria-checked="false">Female</button>
  </div>
  <button type="button" class="pref-voice-advanced-toggle" aria-expanded="false"
          aria-controls="pref-voice-advanced">▾ Pick a specific voice…</button>
  <div class="pref-voice-advanced hidden" id="pref-voice-advanced">
    <label for="pref-voice-select" class="sr-only">Specific voice</label>
    <select id="pref-voice-select"></select>
  </div>
  <p class="pref-voice-hint hidden" id="pref-voice-hint"></p>
  <div class="pref-voice-stub hidden" id="pref-voice-stub">
    Voice selection is not supported on this browser.
  </div>
</div>

<div class="pref-group">
  <div class="pref-label">Units</div>
  <label class="radio-label"><input type="radio" name="units" value="imperial" checked> Imperial (ft, mi)</label>
  <label class="radio-label"><input type="radio" name="units" value="metric"> Metric (m, km)</label>
</div>

<div class="pref-group">
  <div class="pref-label">Coordinates</div>
  <label class="radio-label"><input type="radio" name="coordfmt" value="dd" checked> Decimal Degrees</label>
  <label class="radio-label"><input type="radio" name="coordfmt" value="dms"> Degrees/Minutes/Seconds</label>
  <label class="radio-label"><input type="radio" name="coordfmt" value="maidenhead"> Maidenhead Grid</label>
  <label class="radio-label"><input type="radio" name="coordfmt" value="mgrs"> MGRS</label>
</div>
```

**Invariant:** the `name="units"` radio group keeps its exact selector. [nav-ui.js:85-87](../../../frontend/nav-ui.js#L85-L87) does `document.querySelectorAll('input[name="units"]')` and that selector continues to resolve correctly after the move. Same for `name="coordfmt"` consumers.

### 6.2 style.css

New selectors appended to [frontend/style.css](../../../frontend/style.css):

- `.pref-group` — margin-bottom for section spacing; no border.
- `.pref-label` — small uppercase label, mirrors the existing `.legend-label` / `.label` pattern used elsewhere.
- `.pref-voice-buttons` — flex row, gap 6px.
- `.pref-voice-btn` — 3-button flex children, rounded 4px, border matching existing button style, `:hover` darken, `.active` uses the existing primary-accent color.
- `.pref-voice-advanced-toggle` — text-button style, accent text color, left-aligned.
- `.pref-voice-hint` — small italic, muted color. Renders inline.
- `.pref-voice-stub` — same muted style as hint.
- `.hidden` — already defined globally (used elsewhere).
- `.sr-only` — already defined globally, or added here if not (screen-reader-only visually-hidden utility).

No existing selectors are modified.

### 6.3 No changes to the nav overlay

The nav overlay, its mute button, and the `nav-muted` localStorage key are untouched. Voice prefs are pre-trip configuration; mute is in-flight control.

## 7. Voice-resolution logic

### 7.1 `getUtteranceVoice()`

```
1. Read `nav-voice-pref` from localStorage. Parse JSON; on any error, treat as {mode: "default"}.
2. If parsed.version !== 1, treat as {mode: "default"}.
3. Switch on parsed.mode:
   a. "default"  → return null.
   b. "specific" → look up getVoices().find(v => v.voiceURI === parsed.voiceURI).
                    If found → return it.
                    If not found → fall through to (c) using parsed.storedGenderHint as parsed.gender.
                                   If storedGenderHint is null → return null (device default).
   c. "gender"   → scan getVoices() filtered to /^en[-_]?/i.test(v.lang). For each voice, call
                    inferGender(v.name). Return the first voice whose inferred gender === parsed.gender.
                    If none found → return null (device default). Emit a console.debug for diagnostic.
4. Memoize result against the voice list's identity (current array reference from getVoices()).
   Invalidate on voiceschanged event.
```

### 7.2 Memoization correctness

`getVoices()` returns the same array reference between `voiceschanged` events in all supported browsers. We cache the last-returned `SpeechSynthesisVoice` keyed by `(mode, gender, voiceURI)`. On `voiceschanged` fire, cache is cleared.

### 7.3 The `voiceschanged` bootstrap

- On `init()`: call `getVoices()` once. If it returns a non-empty array, we're done (Firefox-style synchronous population).
- If it returns `[]`: register a `voiceschanged` handler that re-reads `getVoices()` and fires the module's own voice-list-refreshed callback.
- Also start a 5-second `setTimeout` fallback (§8 Empty voice list). If `voiceschanged` has not fired and the list is still empty at t=5s, we conclude the API is non-functional and hide the voice group.

## 8. Error handling matrix

All four Q4 defaults are codified here.

| Condition | Detection | User-visible behavior | Implementation |
|---|---|---|---|
| **iOS low voice count** | `getVoices().filter(v => /^en[-_]?/i.test(v.lang)).length <= 3` | `pref-voice-hint` shows: *"Only a few voices detected. On iOS, add more via Settings → Accessibility → Spoken Content → Voices."* | Re-evaluated on every `voiceschanged`. Hint hidden when count > 3. |
| **Saved `voiceURI` missing** | `mode === "specific"` and `getVoices().find(v => v.voiceURI === stored) === undefined` | Silent fallback to `storedGenderHint` → device default. On next Preferences expand, the Male / Female button reflects the fallback state. No modal, no banner. | `getUtteranceVoice()` falls through per §7.1 step 3b. `console.debug("VoicePicker: saved voice not present, falling back", storedVoiceURI)`. |
| **No gender match** | `mode === "gender"` and the filtered-scan returns no voice | Button stays visually selected; inline italic under the button row: *"No [Male \| Female] voice detected on this device — using device default."* | Hint text swaps to the gender-specific message. Re-evaluated on `voiceschanged`. |
| **Empty voice list after 5s** | `voiceschanged` hasn't fired by `setTimeout(5000)` AND `getVoices()` still returns `[]` | `.pref-voice-buttons`, `.pref-voice-advanced-toggle`, `.pref-voice-hint`, and `.pref-voice-advanced` are all hidden. `.pref-voice-stub` becomes visible: *"Voice selection is not supported on this browser."* Units and Coordinates sub-groups are unaffected. Nav overlay's mute button is unaffected. | In `init()`: one-shot timer. |

### 8.1 What the hint element looks like

There's exactly one `.pref-voice-hint` element. Its text content is driven by a priority chain, evaluated after every preference write, every `voiceschanged` fire, and at `init()`:

1. If **empty-voice-list** is active → hint is hidden (the stub takes over the whole voice group).
2. Else determine the *effective* gender being attempted:
   - `mode === "gender"` → effective gender = `pref.gender`
   - `mode === "specific"` with a missing voiceURI → effective gender = `pref.storedGenderHint` (may be `null`)
   - `mode === "specific"` with the voiceURI found, or `mode === "default"` → no effective gender; skip to step 4
3. If effective gender is non-null and no voice matches it in the current list → hint shows the gender-specific message (*"No Male voice detected on this device — using device default."*).
4. Else if **iOS low voice count** is active → hint shows the iOS message.
5. Else → hint is hidden.

This ordering means the gender-mismatch message takes precedence over the iOS-low-count message when both apply (a user with 2 iOS voices who picks "Male" when both are female gets the mismatch message, not the add-more-voices message — the mismatch is the more actionable signal).

## 9. Preview logic (Q3 choice C)

### 9.1 The preview gate

A module-scope boolean `previewArmed`. Rules:

- Starts `false`.
- Set to `true` when a click on `.pref-voice-btn` or a `change` on `#pref-voice-select` originates from within the current Preferences interaction.
- Reset to `false` on any of:
  - Sidebar close (existing sidebar-toggle close event).
  - Module-internal timeout of 30 seconds after last click (handles "user configured then wandered away").
- When `previewArmed` is true AND the user makes a new selection → preview fires.
- When `previewArmed` is false (e.g. page load → localStorage restore → button appears selected; but user did not click) → preview does NOT fire.

### 9.2 Preview utterance

- Cancel any in-flight utterance first: `speechSynthesis.cancel()` (matches the nav-ui pattern at [nav-ui.js:464](../../../frontend/nav-ui.js#L464)).
- Build a fresh utterance with:
  - text = `formatPreviewPhrase(useImperial)` → *"In 500 feet, turn right onto Main Street."* or *"In 150 meters, turn right onto Main Street."*
  - `lang = 'en-US'`, `rate = 1.0` (match nav-ui defaults)
  - `voice = getUtteranceVoice()` for the voice the user just picked (re-resolved after the preference write).
- `speechSynthesis.speak(utterance)`.

### 9.3 Preview stop

Preview cancellation is **scoped to the preview utterance only** — it must never interrupt an active nav utterance. Implementation: track `activePreviewUtterance` as a module-private reference. Cancel only when that reference is non-null:

- On sidebar close: if `activePreviewUtterance !== null` → `speechSynthesis.cancel()`.
- On `visibilitychange` → hidden: if `activePreviewUtterance !== null` → `speechSynthesis.cancel()`. If nav is active, its in-flight utterance would also be cancelled by a naïve `cancel()` call — the guard prevents this. A nav-active check (`document.body.classList.contains('nav-active')` or equivalent) is an additional safety but redundant given the preview-utterance-tracking.
- On a new selection mid-preview: `speechSynthesis.cancel()` before speaking the next one (same as the cancel-then-speak flow in [nav-ui.js:464-468](../../../frontend/nav-ui.js#L464-L468)). This is safe — no nav utterance can be in flight during the Preferences interaction cycle because the Preferences section only opens pre-nav (collapsed/hidden during active nav by existing sidebar behavior, verify in task 1 of the plan).
- `activePreviewUtterance` is cleared in the utterance's `onend` / `onerror` handler as well.

### 9.4 Unit mode source of truth

`useImperial` is read from the same `input[name="units"]:checked` selector [nav-ui.js:85-87](../../../frontend/nav-ui.js#L85-L87) already uses. VoicePicker listens to the same `change` event so the preview phrase re-renders on unit switch.

## 10. Testing strategy

### 10.1 JS unit tests — `frontend/tests/voice-picker/`

Pattern borrowed from [frontend/tests/wake-lock/](../../../frontend/tests/wake-lock/) — node `--test`, `node:vm` sandboxed load of the IIFE source (not ES6 import; `voice-picker.js` is an IIFE that attaches to `window.VoicePicker`, matching the wake-lock style). Mocks for `window.speechSynthesis`, `window.localStorage`, and `document` constructed via a `_fixtures.js` module in the same directory, mirroring [frontend/tests/wake-lock/_fixtures.js](../../../frontend/tests/wake-lock/_fixtures.js). Not under the Python `tests/` root (see G2 of the nav-keep-awake spec — pytest collection collision).

Test files and cases (minimum viable coverage; add more in implementation if gaps surface):

- `gender-inference.test.mjs` — 30 known voice names → correct gender; 5 substring-match cases ("Google US English Female", "Microsoft George - English (United States)", etc.); 3 unknown cases → `null`.
- `preference-persistence.test.mjs` — write {mode:"gender", gender:"male"} → reload → read back identical. Corrupt JSON → `{mode: "default"}`. Unknown version → `{mode: "default"}`.
- `voice-resolution.test.mjs` — each mode in §7.1 produces the expected voice or null across mocked `getVoices()` lists: 10 voices (macOS-like), 2 voices (iOS default), empty list, list without any en-* voice.
- `fallback-behavior.test.mjs` — saved `voiceURI` not in list → falls through to `storedGenderHint`. Both stored and gender-match missing → returns `null`.
- `voiceschanged-bootstrap.test.mjs` — `init()` with empty initial `getVoices()` → registers handler → handler fires → internal list refreshed → `onVoiceListChanged` callbacks invoked. 5-second fallback → hides voice group.
- `preview-gate.test.mjs` — `previewArmed` starts false → click → true → preview fires. Simulated sidebar close → false. 30s idle → false. Page-load restore path → false → no preview.

### 10.2 Python structural tests — `tests/test_voice_picker_static.py`

Pattern: [tests/test_wake_lock_static.py](../../../tests/test_wake_lock_static.py). Fast, no JS runtime, verifies markup/module contracts via regex.

- `test_voice_picker_js_exports_public_api` — `voice-picker.js` defines `window.VoicePicker` with `init`, `getUtteranceVoice`, `onVoiceListChanged`.
- `test_voice_picker_loaded_before_nav_ui` — `<script src="voice-picker.js">` appears before `<script src="nav-ui.js">` in `index.html`.
- `test_preferences_section_markup_present` — `#pref-voice` container + three `.pref-voice-btn` elements with `data-gender="default|male|female"` + `#pref-voice-advanced` + `#pref-voice-hint` + `#pref-voice-stub` all present in `index.html`.
- `test_units_radios_still_named_units` — regression guard. `<input type="radio" name="units"` still present after the section move.
- `test_coordfmt_radios_still_named_coordfmt` — regression guard.
- `test_nav_ui_calls_voice_picker_get_voice` — `nav-ui.js` contains the call `VoicePicker.getUtteranceVoice()` with a null-guard preceding it.
- `test_no_shrek_references` — light-touch regression guard against brainstorming's hard-skipped novelty. Checks the codebase for case-insensitive `shrek` and `ogre` in source files (excluding this spec's revision-history reference). If someone adds it later, they rename or delete the test. Scope: `frontend/*.js`, `frontend/*.html`, `frontend/*.css`.

### 10.3 Manual acceptance checklist

Matches [nav-keep-awake §6.3 pattern](2026-04-20-nav-keep-awake-design.md#L53). Run on at least desktop Chrome + iOS Safari + Android Chrome before declaring ship-ready.

1. **Default state:** fresh browser (no localStorage for `nav-voice-pref`). Open sidebar, navigate to Preferences. "Default" button is active. No sound. Start nav → voice prompts use browser default. IDENTICAL to current `main` behavior.
2. **Male selection:** click Male. Preview fires in the selected voice. Refresh page. Open Preferences. Male button is still active. Start nav → voice prompts are male.
3. **Female selection:** click Female. Preview fires in a different voice. Refresh. Female button active. Start nav → voice prompts are female.
4. **Specific voice:** expand "Pick a specific voice…". Dropdown populated. Pick "Daniel (en-GB)" (if present). Preview fires. Gender buttons deselect OR the matching gender button lights up if Daniel is in the inference table. Start nav → voice prompts are Daniel's.
5. **Metric toggle:** with Male selected, switch Units to Metric. Click Male again (or re-preview). Sample phrase says meters, not feet.
6. **Preview gate:** close sidebar while preview is speaking → audio stops. Open sidebar → no auto-replay.
7. **iOS low-voice hint:** on iPhone with default voice install (≤ 3 en-* voices), the hint appears under the buttons. On a device with 20+ voices, the hint is hidden.
8. **Saved voice missing:** manually edit localStorage to `{mode: "specific", voiceURI: "nonexistent-voice-xyz", storedGenderHint: "female"}`. Reload. Female button is active (via fallback). Start nav → voice prompts are female. No error banner.
9. **No gender match (synthetic):** on a device with no inferrable male voices, click Male. Button appears selected. Inline italic hint appears under the row. Start nav → voice prompts use device default (not silent).
10. **Empty voice list stub (synthetic):** mock `getVoices()` to always return `[]`. After 5 seconds, the voice group is replaced by the stub message. Units and Coordinates sub-groups still present and functional.
11. **Disclosure accessibility:** screen reader (VoiceOver / TalkBack) reads the gender buttons as a radio group. Advanced disclosure's `aria-expanded` state toggles correctly. `#pref-voice-advanced`'s hidden state is respected by the AT.
12. **No regression to mute:** mute button on nav overlay still works. `nav-muted` key unchanged.

## 11. Deployment

No Docker changes. No data-pipeline changes. Frontend-only feature shipped via the existing `geographica-frontend` bind-mount — changes are live on page reload after files are committed.

Geographica currently ships frontend assets without content-hash cache-busting. Beta testers must hard-reload (Ctrl/Cmd-Shift-R) once after this feature lands; `frontend/index.html` gets an edit (new Preferences markup + new `<script>` tag), so default HTML-cache rules will pick up the change on next revalidation for most users. A short CHANGELOG entry mentioning the hard-reload is the only user-facing deployment note.

## 12. Out of scope (restated for emphasis)

- Shrek voice. Any novelty / cloned / cartoon / character voice. Deliberately skipped by the user during brainstorming.
- Cross-device preference sync.
- Voice rate / pitch / volume sliders.
- Per-route or per-costing-model voice overrides.
- Non-English voices.
- Server-side TTS.
- Changes to the nav overlay, mute button, or `nav-muted` key.

Any one of these could be a future spec. None ship in this one.
