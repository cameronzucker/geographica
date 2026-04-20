# Nav Voice Picker — Design Spec

**Date:** 2026-04-21
**Scope:** Let Geographica nav users choose a preferred voice (Default / Male / Female / specific installed voice) for turn-by-turn audio prompts, persisted per-device in localStorage. Replaces the current "browser picks a voice" default.
**Files:** `frontend/voice-picker.js` (new), `frontend/app.js` (dispatch sidebar CustomEvent, load voice-picker script), `frontend/nav-ui.js` (one-line integration), `frontend/index.html` (Preferences section markup, script tag), `frontend/style.css` (Preferences CSS + `.sr-only` global utility), `frontend/tests/voice-picker/` (JS unit tests), `tests/test_frontend_voice_picker.py` (Python structural tests; filename matches existing CI glob `test_frontend_*.py`).
**Related:** Grew from a beta-tester request ("Shrek voice"). Shrek voice is out of scope — it isn't in any OS voice list; voice cloning is infeasible on a Pi and legally questionable regardless. Feature delivers the legitimate half (male / female / specific voice) that was the real gap. Pattern follows [2026-04-20-nav-keep-awake-design.md](2026-04-20-nav-keep-awake-design.md) for module boundaries, `acquireGeneration`-counter concurrency pattern, testing shape, and deployment assumptions.

## Revision history

- **v2 (2026-04-21)** — Post-adversarial rewrite. Five-round review (4× Claude `general-purpose` subagents at distinct lenses: API correctness, concurrency, testing sufficiency, subagent executability; 1× Codex CLI for outside-Claude cross-validation) surfaced **17 MUST-FIX + 25 SHOULD-FIX + 5 NICE-TO-HAVE** findings. All 5 round files in [dev/adversarial/2026-04-21-nav-voice-picker-r{1..5}-*.md](../../../dev/adversarial/), committed as `fbcfd7e`. Major structural changes:
  - **Preview lifecycle rewritten around `previewGeneration` counter** — verbatim port of `wake-lock.js` pattern. Closes R1 F1.1 (`onend` doesn't fire on cancel per W3C), R2 F2.1 (cancel-then-speak clear race), R2 F2.2 (iOS Safari silent-cancel leak).
  - **Explicit `nav-active` guard** — sidebar is openable mid-nav (verified against `app.js` `setSidebarOpen`). Voice buttons disable during nav; preview entry early-returns on `document.body.classList.contains('nav-active')`. Closes R1 F1.2, R2 F2.6, R4 F4.4.
  - **`voiceschanged` bootstrap uses triple-check + poll + iOS priming** — MDN canonical pattern. Idempotent handler. Closes R1 F1.4, R1 F1.5, R3 F3.1.
  - **`localService` default filter** — cloud voices hidden unless user explicitly opts in via labeled checkbox. Closes R1 F1.8 and R5 F5.1 (offline-first violation on AREDN mesh).
  - **State-model honesty** — when saved specific voice is missing, UI shows an explicit "Saved voice unavailable" state with the fallback voice clearly named, rather than silently lighting a gender button (R5 F5.5 accepted per user decision; overrides v1 Q4 Scenario 2's "silent fallback").
  - **Composite voice identifier** `{voiceURI, name, lang}` — saved with multi-key fallback so macOS upgrades (which change `voiceURI`) don't silently lose the user's pick. Closes R1 F1.6.
  - **`inferGender` rewritten** with explicit prefix/suffix stripping — handles `"Microsoft David - English (United States)"` and `"Samantha (Enhanced)"` correctly. Closes R1 F1.7.
  - **Sidebar-close event** — `app.js` now dispatches `CustomEvent('geographica:sidebar')` from `setSidebarOpen`. Closes R2 F2.5, R4 F4.4, R3 F3.8.
  - **All line numbers removed from spec** — replaced with search-by-content contract. Closes R4 F4.1.
  - **Python structural test file renamed** to match existing `tests/test_frontend_*.py` CI glob. Closes R3 F3.12.
  - **`.sr-only` CSS utility added globally** — referenced by spec but previously undefined in codebase. Closes R4 F4.3.
  - **Rejected findings (user decisions, 2026-04-21):**
    - R5 F5.2 (replace custom button radios with native inputs + full ARIA keyboard model) — rejected. Rationale: custom buttons match the existing codebase pattern (mute, compass, recenter, etc.). Over-engineering a single widget creates inconsistency.
    - R5 F5.3 (explicit preview button for a11y) — rejected. Q3-C (auto-preview on expansion) stands; the existing nav-voice-prompt flow already uses speechSynthesis without a11y ceremony.
- **v1 (2026-04-21)** — Initial design, commit `c4be361`. Based on Q1-Q4 brainstorm. Spec asserted "Preferences only opens pre-nav" and silent fallback on missing voice. Both premises invalidated by adversarial review.

---

## 1. Summary

Geographica's turn-by-turn nav speaks instructions via the browser's Web Speech API — `new SpeechSynthesisUtterance(text)` with no voice selected. The browser picks whatever voice it defaults to, which is usually device- and locale-specific and feels random across sessions.

This spec adds a **per-device voice preference** stored in localStorage, controlled by a new **"Preferences"** section in the sidebar. The user gets three quick buttons — Default / Male / Female — with an optional disclosure that reveals the installed-voice list (filtered by default to on-device voices for offline reliability; cloud voices available via an explicit opt-in).

The feature is entirely client-side: speech synthesis happens on the device rendering the UI (driver's phone, in-vehicle tablet), not on the Pi. No network dependency even when cloud voices are opted in (they're a device-browser-network concern, not a Geographica-server concern).

## 2. Goals & non-goals

### Goals

- **G1.** User can pick a voice preference (Male / Female / Default) in one tap and hear it immediately in the current expansion cycle (Q3 auto-preview semantics).
- **G2.** Power users can override gender inference and pick a specific installed voice by name from a disclosure-revealed dropdown.
- **G3.** Preferences persist in localStorage per-device across page reloads.
- **G4.** Zero regression to existing nav audio behavior. The only change to `nav-ui.js`'s speech path is a single `utterance.voice = chosen` assignment guarded by a null check. Mute button, `primeSpeech()`, and cancel-then-speak flow all unchanged.
- **G5.** Feature silently degrades on browsers without Web Speech API — the Preferences voice group hides; the nav overlay mute button is unaffected.
- **G6.** Module boundary: voice enumeration, gender inference, preference persistence, preview logic, dropdown rendering all in `frontend/voice-picker.js`. `nav-ui.js` holds no voice-picker concerns beyond the single assignment.
- **G7.** iOS Safari works out of the box (voiceschanged-unreliable path handled via priming) and via the low-voice-count hint.
- **G8.** Preview audio never interrupts an active nav utterance. Guard is both preview-utterance-scoped (generation counter) AND explicit nav-active body-class check.
- **G9.** Offline-first: cloud-backed voices are filtered out by default. User must explicitly opt in to include them, with labeling that names the network dependency.
- **G10.** State-model honesty: when a saved specific voice is not installed on the current device, the UI shows an explicit unavailable state with the fallback voice named. It does not silently lie about what's stored.
- **G11.** Subagent-executable: the spec cites code by content (search terms), not line numbers. All required conventions (IIFE shape, event names, CSS variables) are named explicitly.

### Non-goals

- **NG1.** Cross-device voice sync. Each device keeps its own preference; no Pi-side storage.
- **NG2.** Voice rate / pitch / volume sliders. YAGNI.
- **NG3.** Per-route voice overrides.
- **NG4.** Localization beyond `en-*`. `utterance.lang` follows the resolved voice's own `lang` when a specific voice is picked (so `en-GB` voice speaks with `en-GB` tag), otherwise defaults to `en-US`. Expanding to other-language voices is a future spec.
- **NG5.** Server-side TTS / neural voice synthesis. Infeasible on Pi 5 at interactive nav latency; also out of scope per the brainstorm hard-skip.
- **NG6.** Changes to nav-overlay mute button or `nav-muted` localStorage key.
- **NG7.** Migration of existing users' nav experience. Default mode = "Default" = browser default = current behavior.
- **NG8.** UI for editing the gender-inference table. Hardcoded module constant.
- **NG9.** Full WAI-ARIA radio-group keyboard model (roving tabindex, arrow-key navigation, Space activation) for the Male/Female/Default buttons. Explicit user decision 2026-04-21: the codebase uses simple `<button>` widgets throughout (mute, compass, recenter, nav-start, nav-stop) without this treatment; over-engineering one widget creates inconsistency. Buttons remain plain `<button>` with `click` handlers.
- **NG10.** Explicit preview button. Q3-C auto-preview behavior stands. Explicit user decision 2026-04-21.

## 3. User-facing decisions locked via brainstorming (v1)

- **Q1 — Granularity:** Hybrid. Gender quick-pick (3 buttons: Default / Male / Female) plus an "advanced disclosure" revealing the filtered voice list. Matches the `feedback_optional_input_hidden_by_default` pattern.
- **Q2 — Location:** New **Preferences** section in the sidebar, absorbing the existing Units and Coordinates sub-blocks.
- **Q3 — Preview behavior:** Auto-preview on selection, **gated on the Preferences section being in an "expanded" state** (the `previewArmed` flag tracks this — set on click, reset on sidebar-close or 30-second idle).
- **Q4 — Edge cases (partially superseded by v2 adversarial review):**
  - **Scenario 1 (iOS low voice count ≤ 3):** hint text under buttons with iOS Settings guidance — **stands**.
  - **Scenario 2 (saved voice missing) — SUPERSEDED:** v1 chose silent fallback; v2 adversarial-review finding R5 F5.5 surfaced a state-model-honesty concern and user accepted the override. v2 behavior: explicit inline "Saved voice unavailable — using [fallback]" helper text when Preferences is expanded.
  - **Scenario 3 (no gender match):** inline italic "No [Male|Female] voice detected on this device — using default" — **stands**.
  - **Scenario 4 (empty voice list):** hide voice group, show "Voice selection not supported on this browser" — **stands but refined**: a transient "Detecting available voices…" state precedes the stub during the 5-second bootstrap window (R5 F5.6).

## 4. Architecture

### 4.1 Module boundary

New file `frontend/voice-picker.js`. Shape matches `frontend/wake-lock.js` verbatim: IIFE wrapper, strict mode, duplicate-load guard, public API attached to `window.VoicePicker`. Exact opener:

```js
(function () {
  'use strict';
  if (window.VoicePicker) return; // duplicate-load guard

  // module-private state
  var voices = [];
  var previewGeneration = 0;
  var activePreview = null;   // { utterance, gen } or null
  var previewArmed = false;
  var idleResetTimer = null;
  // ...

  // ... private functions: inferGender, resolveVoice, render, etc. ...

  window.VoicePicker = {
    init: function () { /* ... */ },
    getUtteranceVoice: function () { /* returns SpeechSynthesisVoice | null */ },
    onVoiceListChanged: function (callback) { /* zero-arg callback */ },
  };
})();
```

**Contract:**

- `init()` — called once from `app.js` DOMContentLoaded handler. Idempotent. Attaches DOM handlers, loads preferences, starts voice bootstrap.
- `getUtteranceVoice()` — called from `nav-ui.js` per nav utterance. Returns a `SpeechSynthesisVoice` to assign, or `null` to let the browser default. Never throws. Memoizes per `(mode, gender, voiceURI-or-name-lang-tuple)` key across calls within the same voice-list revision.
- `onVoiceListChanged(callback)` — zero-argument callback. Registered consumers should re-read `getVoices()` themselves (or call `getUtteranceVoice()`). Fires after every successful voice-list refresh, including the initial bootstrap. Handler is idempotent internally — if the voice list fingerprint (sorted voiceURI+name+lang) is unchanged, the callback does not fire.

### 4.2 Integration point in nav-ui.js

Locate the `onVoice(text)` function by searching `nav-ui.js` for the string `new SpeechSynthesisUtterance(text)` (do NOT trust line numbers — they move). Inside the function, between `utterance.lang = ...` and `speechSynthesis.speak(utterance)`, insert:

```js
var chosenVoice = window.VoicePicker && window.VoicePicker.getUtteranceVoice();
if (chosenVoice) {
  utterance.voice = chosenVoice;
  utterance.lang = chosenVoice.lang || utterance.lang;  // follow voice's locale
}
```

Null-guard on `window.VoicePicker`: if `voice-picker.js` fails to load, `nav-ui.js` keeps working exactly as today.

**`primeSpeech()` is NOT changed** — locate it by searching `nav-ui.js` for `function primeSpeech`. The function uses a zero-volume silent utterance to wake up the speech engine. Voice selection is irrelevant there and would add first-utterance latency if resolved. Leave `primeSpeech()` alone.

### 4.3 Script load order and cache buster

Add a `<script>` tag to `frontend/index.html`:

```html
<script src="voice-picker.js?v=20260421"></script>
```

Position: immediately after `wake-lock.js?v=...` and before `navigation.js?v=...` (same script block, no `async`, no `defer`). Locate by searching `index.html` for `src="wake-lock.js`. The `?v=YYYYMMDD` cache-buster must match the commit date to force reload on deploy.

Use today's date (`20260421`) or whatever date the commit lands on.

### 4.4 New dependency: sidebar-close event dispatch from app.js

`app.js` currently has a closure-scoped `setSidebarOpen(open)` function that toggles the `.open` class on `#sidebar`. No event fires. VoicePicker needs to hear sidebar close to reset `previewArmed` and cancel any in-flight preview.

**Change:** add a single dispatch inside `setSidebarOpen(open)` (locate by searching `app.js` for `function setSidebarOpen`):

```js
function setSidebarOpen(open) {
  // ... existing classList mutation ...
  document.dispatchEvent(new CustomEvent('geographica:sidebar', {
    detail: { open: open }
  }));
}
```

VoicePicker listens on `document`:

```js
document.addEventListener('geographica:sidebar', function (e) {
  if (!e.detail.open) onSidebarClose();
});
```

This covers all three sidebar-close paths (toggle click, overlay tap-outside, programmatic calls) since they all route through `setSidebarOpen(false)`.

## 5. Data model

### 5.1 localStorage schema

**Key:** `nav-voice-pref` (consistent with existing `nav-muted` convention).

**Value:** JSON-stringified object.

```json
{
  "mode": "default" | "gender" | "specific" | "unavailable",
  "gender": "male" | "female" | null,
  "voice": {
    "voiceURI": "<original voiceURI>",
    "name": "<original voice.name>",
    "lang": "<original voice.lang>"
  } | null,
  "storedGenderHint": "male" | "female" | null,
  "allowCloudVoices": false,
  "version": 1
}
```

- `mode` — source of truth for resolution.
- `gender` — meaningful when `mode === "gender"`.
- `voice` — **composite identifier** (new in v2 per R1 F1.6). Stores voiceURI + name + lang at the time of user selection. Resolution tries voiceURI first, then name + lang as fallback, so macOS voice-bundle-ID changes across OS upgrades don't silently lose the user's pick. Meaningful when `mode === "specific"` or `mode === "unavailable"`.
- `storedGenderHint` — computed at write-time when user picks a specific voice with an inferrable gender. Used as a second-level fallback if both voiceURI and name+lang match fail.
- `allowCloudVoices` — boolean opt-in for `localService === false` voices. Defaults to `false`; inverted when user ticks the "Include cloud voices (requires internet)" checkbox.
- `mode === "unavailable"` is a new terminal state (R5 F5.5): saved specific voice not present on current device AND no gender fallback applicable. UI shows explicit helper text; does not silently coerce to gender mode.
- `version` — `1` for this spec. Unknown version → treat as `{mode: "default"}`.

### 5.2 Default state

User with no `nav-voice-pref` key: `getUtteranceVoice()` returns `null` → `utterance.voice` is not set → identical to current `main` behavior.

### 5.3 Gender-inference table and algorithm

Module-private constant `KNOWN_VOICES` in `voice-picker.js`. Covers common macOS/iOS (Apple), Android/Chrome (Google), Windows Edge (Microsoft), Linux Firefox (eSpeak) voices. Keys are bare names (post-tokenization), values are `"male"` or `"female"` (lowercase, strict). Must contain no duplicate keys (enforced by unit test; R3 F3.3).

```js
var KNOWN_VOICES = {
  // Apple — iOS + macOS (names as reported bare by getVoices(), post-tokenization)
  'Samantha': 'female', 'Karen': 'female', 'Moira': 'female', 'Tessa': 'female',
  'Victoria': 'female', 'Veena': 'female', 'Fiona': 'female',
  'Kate': 'female', 'Serena': 'female',
  'Alex': 'male', 'Daniel': 'male', 'Fred': 'male', 'Oliver': 'male',
  'Tom': 'male', 'Rishi': 'male', 'Aaron': 'male',
  // Microsoft — Edge on Windows (post-tokenization, "Microsoft" prefix stripped)
  'Zira': 'female', 'Hazel': 'female', 'Susan': 'female',
  'David': 'male', 'Mark': 'male', 'George': 'male', 'James': 'male'
};
```

**Algorithm `inferGender(rawName)`** (R1 F1.7, R3 F3.4):

```js
function inferGender(rawName) {
  if (!rawName || typeof rawName !== 'string') return null;
  // 1. Strip known platform prefixes.
  var name = rawName.replace(/^(Microsoft|Google|Apple|Siri)\s+/i, '');
  // 2. Strip parenthetical/suffix tokens: "Samantha (Enhanced)", "David Desktop".
  name = name.replace(/\s*\((?:Enhanced|Premium|Compact|Natural)\)\s*/gi, '');
  name = name.replace(/\s+(?:Desktop|Mobile)\b/gi, '');
  // 3. Strip trailing " - English (United States)" style locale descriptors.
  name = name.replace(/\s*-\s*English.*$/i, '');
  // 4. Take first whitespace/hyphen-delimited token.
  var firstToken = name.split(/[\s\-_]+/)[0];
  if (KNOWN_VOICES[firstToken]) return KNOWN_VOICES[firstToken];
  // 5. Substring fallback with strict word boundaries.
  //    Note: /\bmale\b/ must come after /\bfemale\b/ check (or use negative lookbehind).
  //    Tests enforce "femaleness" and "Emanuel" do NOT return "male".
  if (/\b(?:female|woman|girl)\b/i.test(rawName)) return 'female';
  if (/(?<!fe)\b(?:male|man|boy)\b/i.test(rawName)) return 'male';
  return null;
}
```

**Test contract:** see §10.1 `gender-inference.test.mjs` for the enumerated test cases including the false-positive guards (`"femaleness"`, `"Emanuel"`, `"Norman"`, `"Boyce"`).

**Test accessibility:** expose as `VoicePicker._inferGender` (underscore-prefixed, explicitly marked as "test-only") so unit tests can exercise it without making it a public API.

### 5.4 Write paths — when `nav-voice-pref` is persisted

Five distinct write paths, all in `voice-picker.js`:

1. **Default button click:** write `{mode: "default", gender: null, voice: null, storedGenderHint: null, allowCloudVoices: <current value>, version: 1}`.
2. **Male/Female button click:** write `{mode: "gender", gender: <"male"|"female">, voice: null, storedGenderHint: null, allowCloudVoices: <current value>, version: 1}`.
3. **Specific voice chosen via dropdown `change`:** write `{mode: "specific", gender: null, voice: {voiceURI, name, lang}, storedGenderHint: inferGender(voice.name), allowCloudVoices: <current value>, version: 1}`. `storedGenderHint` is computed at write-time so a later voice uninstall retains the gender signal.
4. **"Include cloud voices" checkbox toggle:** write the current pref with `allowCloudVoices` updated. If toggling OFF and current `mode === "specific"` with a `voice` that has `localService === false`, normalize to fallback (see §7.1).
5. **Fallback normalization (implicit, from §7.1 resolution):** if resolution cannot find the saved specific voice, the module writes an updated pref with `mode: "unavailable"` to make the UI state honest. `voice` field retained so the name can be displayed.

**Cross-tab sync (R2 F2.9):** module listens for `window.addEventListener('storage', …)` with key `nav-voice-pref`. On foreign-tab write, re-reads the pref and re-renders button/dropdown state.

## 6. UI & markup

### 6.1 Sidebar markup (replaces current `<h3>Units</h3>` and `<h3>Coordinates</h3>` blocks)

Locate by searching `index.html` for `<h3>Units</h3>`. Replace with:

```html
<h3>Preferences</h3>

<div class="pref-group" id="pref-voice">
  <div class="pref-label">Nav voice</div>

  <div class="pref-voice-buttons">
    <button type="button" class="pref-voice-btn active" data-gender="default">Default</button>
    <button type="button" class="pref-voice-btn"        data-gender="male">Male</button>
    <button type="button" class="pref-voice-btn"        data-gender="female">Female</button>
  </div>

  <button type="button" class="pref-voice-advanced-toggle" aria-expanded="false"
          aria-controls="pref-voice-advanced">▾ Pick a specific voice…</button>

  <div class="pref-voice-advanced hidden" id="pref-voice-advanced">
    <label for="pref-voice-select" class="sr-only">Specific voice</label>
    <select id="pref-voice-select"></select>
    <label class="checkbox-label">
      <input type="checkbox" id="pref-voice-allow-cloud">
      Include cloud voices (requires internet — may fail on mesh)
    </label>
  </div>

  <p class="pref-voice-hint hidden" id="pref-voice-hint"></p>

  <div class="pref-voice-stub hidden" id="pref-voice-stub">
    Voice selection is not supported on this browser.
  </div>
  <div class="pref-voice-detecting hidden" id="pref-voice-detecting">
    Detecting available voices…
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

**Invariants** (regression-tested in §10.2):
- Exactly 2 `<input type="radio" name="units">` elements (values `imperial`, `metric`) — preserves the existing `nav-ui.js` `querySelectorAll('input[name="units"]')` selector.
- Exactly 4 `<input type="radio" name="coordfmt">` elements (values `dd`, `dms`, `maidenhead`, `mgrs`).
- The `#pref-voice` container has the three gender buttons, the disclosure toggle, the advanced sub-tree with `<select>` + cloud-voice checkbox, plus the three message stubs (`hint`, `detecting`, `stub`).

### 6.2 CSS (append to end of frontend/style.css)

Append at end of file (standard insertion point for new feature CSS):

- `.pref-group` — margin-bottom for section spacing.
- `.pref-label` — small uppercase label; mirror `.legend-label` visual treatment.
- `.pref-voice-buttons` — flex row, gap 6px.
- `.pref-voice-btn` — flex:1; padding 8px; border 1px solid existing border color; border-radius 4px; uses `var(--accent)` on `.active` (NOT `--primary-accent`; that variable does not exist in this codebase — R4 F4.8).
- `.pref-voice-btn:disabled` — opacity 0.5; cursor not-allowed; title attribute populated dynamically with "Voice can only be changed before or after navigation" (new: nav-active guard visual, §8 new row).
- `.pref-voice-advanced-toggle` — text-button style, `var(--accent)` color, left-aligned.
- `.pref-voice-advanced` — container for dropdown + cloud-voice checkbox.
- `.pref-voice-hint`, `.pref-voice-stub`, `.pref-voice-detecting` — small, italic, muted color; inline block.
- `.checkbox-label` — already exists in codebase; reuse.

**Additionally add `.sr-only` as a global utility** (R4 F4.3; class is referenced by this spec and does not currently exist anywhere in `style.css`):

```css
.sr-only {
  position: absolute !important;
  width: 1px; height: 1px;
  padding: 0; margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
```

### 6.3 No changes to nav overlay

The nav overlay, its mute button, and the `nav-muted` localStorage key are unchanged. Voice prefs are pre-trip configuration; mute is in-flight control.

## 7. Voice resolution

### 7.1 getUtteranceVoice()

```
1. Read `nav-voice-pref` from localStorage. Parse JSON; on any error, treat as {mode: "default"}.
2. If parsed.version !== 1, treat as {mode: "default"} (see §7.4 for migration stance).
3. Candidate voice list:
   - If parsed.allowCloudVoices === true:  candidates = getVoices().filter(v => /^en[-_]?/i.test(v.lang));
   - Else:                                 candidates = getVoices().filter(v => /^en[-_]?/i.test(v.lang) && v.localService !== false);
   (The `localService !== false` form is deliberate — some browsers don't set the property; undefined is treated as "probably local". R5 F5.1.)
4. Switch on parsed.mode:
   a. "default"  → return null.
   b. "specific" → look up candidates for voiceURI match. If found → return it.
                   Otherwise look up candidates for (name, lang) match. If found → return it (R1 F1.6).
                   Otherwise, if parsed.storedGenderHint is non-null, fall through to (c) with gender = storedGenderHint.
                   Otherwise, write {mode: "unavailable"} to localStorage and return null (G10 — state-model honesty, R5 F5.5).
   c. "gender"   → scan candidates, call inferGender(v.name) on each. First voice whose inferred gender matches parsed.gender → return.
                   If no match → return null (device default).
   d. "unavailable" → same as (b) except skip the localStorage write (already unavailable). If voice reappears in candidates between `voiceschanged` fires, normalize back to "specific" on next resolution.
5. Memoize return value per (mode, gender, voice.voiceURI, voice.name, voice.lang) key; invalidate on voiceschanged.
```

### 7.2 Memoization correctness

The memoization key is `(mode, gender, voice.voiceURI, voice.name, voice.lang)` — NOT the `getVoices()` array reference. The W3C spec does not guarantee array-reference stability across calls (R1 F1.3), though individual voice objects are generally identity-stable between `voiceschanged` events. The cache is invalidated whenever `voiceschanged` fires — by which point the handler has already re-read the list.

**Stable sort for gender-mode resolution** (R2 F2.3): within the filtered candidates list, sort by `voiceURI` (lexicographic) before scanning for gender match. This makes the "first matching voice" resolution idempotent across `voiceschanged` fires regardless of the underlying list order.

### 7.3 voiceschanged bootstrap (rewritten; MDN canonical pattern)

On `init()`:

1. Call `getVoices()` once, store in internal `voices` array.
2. `addEventListener('voiceschanged', onVoicesChanged)` on `speechSynthesis`. The handler is idempotent: it re-reads `getVoices()`, computes a fingerprint (sorted voiceURI + name + lang), and only fires `onVoiceListChanged` callbacks if the fingerprint differs from the stored one.
3. After listener attach, call `getVoices()` once more and synthesize a manual refresh pass if non-empty. Closes the MDN race where `voiceschanged` can fire between step 1 and step 2.
4. If still `[]`, enter "detecting" state: show `.pref-voice-detecting` element. Start a polling loop: `setInterval(poll, 500)` calling `getVoices()` every 500 ms for up to 10 iterations (5 seconds total).
5. If any poll returns non-empty, clear the interval, hide `.pref-voice-detecting`, render the picker.
6. If all 10 polls return empty AND the browser supports `speechSynthesis`:
   - On iOS Safari (UA-sniff for `/iPad|iPhone|iPod/`): fire a silent priming utterance (`new SpeechSynthesisUtterance(' '); u.volume = 0; speechSynthesis.speak(u)`) and resume polling for 5 more seconds. Many iOS Safari versions require a user-gesture-adjacent prime before `getVoices()` enumerates (R1 F1.5). **Caveat: this prime fires without a user gesture on init, and may be no-op'd by Safari's autoplay policies; if so, the prime will be retried on the user's first voice-button click, at which point the click provides the gesture context.** `VoicePicker._primedAtLeastOnce` flag prevents duplicate primes.
   - On non-iOS: transition `.pref-voice-detecting` → `.pref-voice-stub` ("Voice selection is not supported on this browser"). Show a "Retry voice detection" button that re-runs the poll (R5 F5.6).

### 7.4 Schema migration (no migration; documented decision)

Unknown `version` values → treat as default. Future upgrade paths (e.g., `version: 2`) can migrate by reading v1 data and writing v2 format on next UI interaction. Silent-reset-on-upgrade is chosen deliberately — voice preferences are cheap to re-enter and forward-compat bugs are expensive. Documented in §10.1 test.

## 8. Error handling matrix

| # | Condition | Detection | Behavior | State element |
|---|---|---|---|---|
| 1 | iOS low voice count | `candidates.length <= 3` and `/iPad\|iPhone\|iPod/.test(navigator.userAgent)` | `.pref-voice-hint` shows: *"Only a few voices detected. On iOS, add more via Settings → Accessibility → Spoken Content → Voices."* | `#pref-voice-hint` |
| 2 | Saved voice missing (specific mode) | `mode === "specific"` AND voiceURI match fails AND name+lang match fails AND `storedGenderHint` non-null | Silent fall-through to gender resolution. Gender button reflects the fallback. `console.warn('[voice-picker] saved voice not present, using gender fallback', savedVoice)`. | (no UI) |
| 3 | **Unavailable state** (R5 F5.5) | `mode === "specific"` AND all lookups + gender fallback fail | Persist `mode: "unavailable"`. `.pref-voice-hint` shows: *"Saved voice '[voice.name]' is not installed on this device — using device default."* All three gender buttons revert to inactive styling. | `#pref-voice-hint` |
| 4 | No gender match for requested gender | `mode === "gender"` AND no candidate's inferred gender matches parsed.gender | Button stays visually selected; `.pref-voice-hint` shows: *"No [Male\|Female] voice detected on this device — using device default."* | `#pref-voice-hint` |
| 5 | Detecting (bootstrap in progress) | init() polling with empty voices | `.pref-voice-detecting` visible; voice buttons + disclosure HIDDEN | `#pref-voice-detecting` |
| 6 | Voice API unsupported (stuck empty) | 5s poll + iOS prime both empty | `.pref-voice-stub` visible with retry button; buttons + disclosure stay hidden | `#pref-voice-stub` |
| 7 | **Nav-active guard** (new in v2) | `document.body.classList.contains('nav-active')` | Voice buttons + cloud checkbox + disclosure toggle all set `disabled`. Preview path early-returns. Tooltip on hover: *"Voice can only be changed before or after navigation."* | buttons.disabled |
| 8 | Cloud voice chosen without opt-in | User manually picks a voice with `localService === false` via dropdown while `allowCloudVoices === false` (shouldn't normally happen since dropdown is pre-filtered, but possible via devtools edit) | Treat as unavailable (row 3). Hint additionally notes *"(requires internet)"*. | `#pref-voice-hint` |

### 8.1 Hint priority chain

Single `#pref-voice-hint` element. After every pref write, `voiceschanged` fire, and on `init()`, evaluate:

1. If **detecting** is active → hint hidden (detecting element takes over).
2. If **stub** is active → hint hidden (stub takes over).
3. If `mode === "unavailable"` → row 3 message (highest priority when voices are known).
4. Determine effective gender:
   - `mode === "gender"` → effective gender = `pref.gender`.
   - `mode === "specific"` with voice present → no effective gender; skip to step 6.
   - `mode === "specific"` with voice missing, falling through to `storedGenderHint` → effective gender = `storedGenderHint`.
5. If effective gender is non-null and no candidate matches it → row 4 message.
6. Else if row 1 (iOS low voice count) condition is true → row 1 message.
7. Else → hint hidden.

Rows 3 > 4 > 1 precedence is intentional: an unavailable-specific-voice is more actionable for the user than "add more iOS voices."

## 9. Preview logic (Q3 auto-preview; v2 hardening)

### 9.1 Preview gate (`previewArmed`)

Module-scope boolean. Rules:

- Starts `false` at `init()`.
- Set to `true` when:
  - `click` on any `.pref-voice-btn` (gender buttons), OR
  - `change` on `#pref-voice-select` (specific voice chosen).
  - Clicking `.pref-voice-advanced-toggle` does NOT arm (R4 F4.11). Clicking the cloud-voice checkbox does NOT arm.
- Reset to `false` when:
  - `geographica:sidebar` event fires with `detail.open === false` (§4.4).
  - Module-internal timeout of 30 seconds after any interaction within `#pref-voice` (including Units/Coordinates radio clicks within the surrounding Preferences section — R2 F2.7).
- When `previewArmed === true` AND a new selection is made → preview fires.
- When `previewArmed === false` (e.g. page-load localStorage restore) → preview does NOT fire.

### 9.2 Preview utterance (with generation counter)

Mirror `wake-lock.js`'s `acquireGeneration` pattern verbatim (R1 F1.1, R2 F2.1, R2 F2.2):

```js
function speakPreview() {
  if (document.body.classList.contains('nav-active')) return;  // §8 row 7
  speechSynthesis.cancel();
  var myGen = ++previewGeneration;
  var utt = new SpeechSynthesisUtterance(formatPreviewPhrase());
  utt.rate = 1.0;
  var v = getUtteranceVoice();
  if (v) { utt.voice = v; utt.lang = v.lang || 'en-US'; }
  else   { utt.lang = 'en-US'; }
  // Clear only if still the active-preview generation.
  utt.onend   = function () { if (myGen === previewGeneration) activePreview = null; };
  utt.onerror = function () { if (myGen === previewGeneration) activePreview = null; };
  activePreview = { utterance: utt, gen: myGen };
  speechSynthesis.speak(utt);
}
```

Both `onend` AND `onerror` are explicitly assigned (R1 F1.1: W3C spec says a cancelled utterance dispatches ONLY `error`, never `end`). Generation-counter guard handles the cancel-then-speak race (R2 F2.1) AND the iOS-Safari-silent-cancel case (R2 F2.2: iOS may fire neither; `activePreview` is cleared synchronously at the top of the next `speakPreview()` since `++previewGeneration` invalidates the prior gen).

### 9.3 Preview stop (scoped to preview only, never nav)

Three entry points. All check generation identity before calling `cancel()`:

- **Sidebar close** (`geographica:sidebar` with `detail.open === false`): if `activePreview !== null` → `speechSynthesis.cancel()`; `activePreview = null` synchronously.
- **`visibilitychange → hidden`**: if `activePreview !== null` → `speechSynthesis.cancel()`; `activePreview = null` synchronously. The `activePreview`-non-null guard prevents cancelling a nav utterance that happens to be in flight (preview and nav cannot both be active per §8 row 7, but belt-and-suspenders).
- **New selection mid-preview**: `speakPreview()` itself (above) calls `speechSynthesis.cancel()` at the top, then the new utterance's `++previewGeneration` invalidates the stale `onend/onerror` guard of the prior utterance.

**iOS PWA visibility-resume quirk** (R2 F2.10): on `visibilitychange → visible` after having been hidden for >2 seconds, call `speechSynthesis.cancel()` once as a cold-reset to unwedge the engine from a known iOS bug where post-background `speak()` calls are silently dropped. Mirrors the wake-lock iOS-reacquire pattern.

### 9.4 Rapid-click debounce

User clicks Male → Female → Male rapidly (R2 F2.11). Three issues:
1. Speech engine queue overflow (Chromium/WebKit bug → "speaking but silent" state).
2. Three localStorage writes in fast succession.
3. Memoization cache invalidated on every write.

Mitigation: debounce the PREVIEW utterance by 150 ms (only speak after clicks settle). The localStorage write fires immediately on each click (so the pref always matches the last click). `speakPreview()` itself is queued via `setTimeout(..., 150)` on a module-scope reset-on-fire timer. Cache invalidation on pref-write is explicit; memoization is cleared immediately.

### 9.5 Unit mode source of truth

`useImperial` read from the same `input[name="units"]:checked` selector `nav-ui.js` already uses. VoicePicker listens to the same `change` event and re-renders the preview sample phrase on unit toggle. Sample: *"In 500 feet, turn right onto Main Street."* / *"In 150 meters, turn right onto Main Street."*

Note on sample phrase (R5 F5.4): the US-centric "Main Street" example is a placeholder acceptable for an en-US-first launch. Non-US English voices (en-GB, en-AU, en-IN) will hear it with the voice's native pronunciation, which is acceptable. Consider replacing with a locale-neutral phrase in a future i18n spec.

## 10. Testing strategy

### 10.1 JS unit tests — frontend/tests/voice-picker/

Pattern: node `--test`, `node:vm` sandboxed load of the IIFE source, mocks via `_fixtures.js` in the same directory (mirror `frontend/tests/wake-lock/_fixtures.js`).

**Async mock timing requirement** (R2 F2.12): the speechSynthesis mock MUST deliver `onstart` / `onend` / `onerror` asynchronously via `queueMicrotask` or `setTimeout(..., 0)`. Include a meta-test `test_mock_is_async.mjs` that constructs an utterance, calls speak(), asserts `onstart` was NOT synchronously fired, then awaits a microtask and asserts it was. Guards against future test rewrites regressing to synchronous timing.

**Test files:**

- `gender-inference.test.mjs` — 30 KNOWN_VOICES entries → correct gender; false-positive guards (`"femaleness"` → null, `"Emanuel"` → null, `"Norman"` → null, `"Boyce"` → null, `"Woman"` → female, `"Google US English Female"` → female); platform tokenization (`"Microsoft David - English (United States)"` → male, `"Samantha (Enhanced)"` → female, `"Google US English"` → null).
- `known-voices.test.mjs` — no duplicate keys (parse KNOWN_VOICES source); values are only `"male"` or `"female"` (strict `===`); table has ≥ 20 entries.
- `preference-persistence.test.mjs` — write each §5.4 write path → read back identical; corrupt JSON → `{mode: "default"}`; unknown `version` → `{mode: "default"}`; schema migration stub (writing a `version: 2` pref is ignored; next UI interaction rewrites as `version: 1`).
- `voice-resolution.test.mjs` — each mode in §7.1 produces expected voice or null. Four fixture voice lists (R3 F3.9): macOS-like 10-voice, iOS 2-voice, Windows-Edge 6-voice, Linux-Firefox 3-voice (lowercase "english"). Assert `localService === false` voices are filtered out unless `allowCloudVoices === true`. Assert stable-sort produces same result for list A and list A-reversed (R2 F2.8).
- `fallback-behavior.test.mjs` — voiceURI-only match fails → (name, lang) match succeeds. Both fail → storedGenderHint match succeeds. All three fail → `{mode: "unavailable"}` persisted; `getUtteranceVoice()` returns null.
- `voiceschanged-bootstrap.test.mjs` — empty initial getVoices() → register listener → handler fires → voice list populated → `onVoiceListChanged` called once. Listener fires twice with identical fingerprint → callback fires only once (idempotence). 5-second timeout on non-iOS → stub state. iOS UA sniff → prime-utterance path.
- `preview-gate.test.mjs` — starts `previewArmed=false` → click Male → armed → preview fires. Click outside `#pref-voice` (Units radio) within 30s → timer resets, still armed. 30s idle → armed=false. Simulated `geographica:sidebar` close event → armed=false + cancel. 6 rapid clicks within 500ms → speak called ≤ 2 times (debounced).
- `preview-cleanup.test.mjs` (NEW per R1 F1.1) — speak utterance A → mock fires `error` (not `end`, per W3C) → `activePreview === null`. Speak A then immediately speak B (simulating cancel-then-speak) → A.onerror fires AFTER B.onstart → `activePreview === {utterance: B, gen: 2}` (generation guard prevents A's handler from nulling the B reference).
- `nav-active-guard.test.mjs` (NEW per R2 F2.6) — `document.body.className = 'nav-active'` → click Male → `speak()` NOT called; `cancel()` NOT called. Clear nav-active → click Male → preview fires.
- `edge-voice-shapes.test.mjs` (R3 F3.10) — getVoices returns voices with `name === ""`, `name === undefined`, duplicate `default: true` flags, unicode name, `lang === "en"` bare. `getUtteranceVoice()` never throws; `inferGender("")` and `inferGender(undefined)` return null.
- `cross-tab-sync.test.mjs` (R2 F2.9) — simulate `storage` event for `nav-voice-pref` with new value → UI re-renders; selected button updates.

### 10.2 Python structural tests — tests/test_frontend_voice_picker.py

**Filename matches existing `.github/workflows/frontend-ci.yml` path-filter glob** `tests/test_frontend_*.py` (R3 F3.12). Do NOT name the file `test_voice_picker_static.py` — that does not match the glob, CI won't trigger on voice-picker-only PRs.

Tests (pattern mirrors `tests/test_wake_lock_static.py`):

- `test_voice_picker_js_exists_and_is_iife` — file exists; opens with `(function () {`, `'use strict';`, `if (window.VoicePicker) return;` within first 10 lines.
- `test_voice_picker_js_exports_public_api` — defines `window.VoicePicker` with `init`, `getUtteranceVoice`, `onVoiceListChanged` (minimum); `_inferGender` for test access.
- `test_voice_picker_script_in_index_html` — `<script src="voice-picker.js?v=\d+">` present; appears after `wake-lock.js` and before `navigation.js`; no `async` attribute on any of the three.
- `test_preferences_section_markup_present` — `#pref-voice` + 3 `.pref-voice-btn` with correct `data-gender`; `#pref-voice-advanced`; `#pref-voice-hint`; `#pref-voice-stub`; `#pref-voice-detecting`; `#pref-voice-allow-cloud` checkbox.
- `test_units_radios_exact_count` (R3 F3.7) — exactly 2 `<input type="radio" name="units">` elements with values `imperial` and `metric`; not inside `<template>` or commented.
- `test_coordfmt_radios_exact_count` — exactly 4 radios with expected values.
- `test_sr_only_class_defined_in_style_css` (R4 F4.3) — `.sr-only` block present with position:absolute and clip rule.
- `test_app_js_dispatches_sidebar_event` (R4 F4.4) — `app.js` `setSidebarOpen` function body contains `dispatchEvent(new CustomEvent('geographica:sidebar'`.
- `test_nav_ui_integrates_voice_picker` — `nav-ui.js` contains `VoicePicker.getUtteranceVoice()` call, preceded within 3 lines by `window.VoicePicker &&`.
- `test_nav_ui_still_has_cancel_then_speak` (R3 F3.5 replacement) — `nav-ui.js`'s `onVoice` function has `speechSynthesis.cancel()` within 3 lines before `speechSynthesis.speak(`.
- `test_prime_speech_not_touched` (R3 F3.6) — `primeSpeech()` function body contains `volume`, `SpeechSynthesisUtterance`, `speak(`, and does NOT contain `VoicePicker`, `getUtteranceVoice`, or `utterance.voice =`.
- `test_no_shrek_references` — mood regression guard; removes if it starts false-positiving. Low-value but low-cost.

### 10.3 Manual acceptance checklist

Run on desktop Chrome + iOS Safari + Android Chrome. Cameron is the designated checklist runner.

1. Default state (fresh browser, no localStorage): Default button active; no sound. Start nav → prompts use browser default. IDENTICAL to `main`.
2. Male selection: click Male → preview fires. Reload → Male still active. Start nav → prompts are male.
3. Female selection: click Female → preview fires in different voice. Reload → Female active. Nav → female.
4. Specific voice: expand "Pick a specific voice…"; dropdown populated, cloud voices absent (opt-out default). Pick Daniel (en-GB). Preview fires. Nav voice is Daniel, `utterance.lang = 'en-GB'`.
5. Cloud voices opt-in: tick "Include cloud voices" — additional voices appear in dropdown, tagged appropriately. Untick → they disappear. Persists across reload.
6. Unavailable state (synthetic — see §10.3 debug query-param, below): force a saved voice that doesn't exist in current voice list → open Preferences → see "Saved voice '<name>' is not installed on this device — using device default." All gender buttons inactive.
7. iOS low-voice hint: on iPhone with default install (≤3 en-* voices), hint appears.
8. Metric toggle: with Male selected, switch to Metric. Sample phrase on next preview says meters.
9. Preview gate: close sidebar mid-preview → audio stops. Reopen → no auto-replay.
10. Nav-active guard: start nav → open sidebar → voice buttons are disabled, tooltip on hover. Stop nav → buttons re-enabled.
11. Empty-voice-list stub (synthetic, see below): forced empty → 5s "Detecting…" → retry button → stub.
12. Rapid-click debounce: tap Default → Male → Female → Male → Female within 500ms. Only final voice's preview plays audibly.
13. Cross-tab sync: open Geographica in two tabs. Change voice in tab A → tab B's UI updates (button highlight moves) within 1 second.
14. Regression: mute button on nav overlay still works; `nav-muted` key unchanged.

**Debug query-param for synthetic cases** (R3 F3.11): the plan (not this spec) must add a dev-only affordance: query-param `?voice-picker-mock=<fixture-name>` that, when `location.hostname` matches `localhost` / `127.0.0.1` / `pandora.*.ts.net`, overrides `getVoices()` to return a named fixture. Fixtures: `empty`, `low-ios`, `many`, `no-male`, `no-female`, `cloud-only`, `unavailable-specific` (this last writes a synthetic `nav-voice-pref` with a non-existent voiceURI).

## 11. Deployment

No Docker changes. No data-pipeline changes. Frontend-only feature shipped via the existing `geographica-frontend` bind-mount — live on page reload.

The `?v=20260421` cache-buster on the new script + edits to `index.html` ensure most browsers pick up the change on next revalidation. Beta testers should hard-reload (Ctrl/Cmd-Shift-R) once after the feature lands. CHANGELOG entry recommended: *"New Preferences section with Nav voice picker. Hard-refresh once after upgrade."*

## 12. Out of scope (restated)

- Shrek voice or any novelty / cloned / character voice.
- Cross-device preference sync (NG1).
- Voice rate / pitch / volume sliders (NG2).
- Per-route voice overrides (NG3).
- Non-English voices (NG4).
- Server-side TTS (NG5).
- Changes to nav-overlay mute button (NG6).
- Existing-user migration (NG7).
- Gender-inference table UI (NG8).
- Full WAI-ARIA radio-group keyboard model (NG9 — user decision 2026-04-21; consistent with codebase button conventions).
- Explicit preview button (NG10 — user decision 2026-04-21; auto-preview Q3-C stands).

Any one of these could be a future spec. None ship in this one.
