# Nav Voice Picker — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a per-device voice picker for Geographica's turn-by-turn nav, delivering Default/Male/Female gender quick-pick plus a specific-voice disclosure, with offline-first defaults and race-safe preview lifecycle.

**Architecture:** Single new frontend module `voice-picker.js` (IIFE matching `wake-lock.js` pattern), integrated into nav-ui's speech path via a one-line `getUtteranceVoice()` call. Preferences persist in localStorage. Sidebar close events bubble through a new `CustomEvent('geographica:sidebar')` dispatched from `app.js`'s `setSidebarOpen`. Preview audio lifecycle uses a `previewGeneration` counter pattern ported verbatim from `wake-lock.js`'s `acquireGeneration`.

**Tech Stack:** Vanilla JS (ES5 IIFE style matching existing frontend modules); `node:vm` sandboxed tests with `node --test`; Python structural tests via `pytest`; MapLibre/Valhalla/nginx stack unchanged.

**Spec:** [docs/superpowers/specs/2026-04-21-nav-voice-picker-design.md](../specs/2026-04-21-nav-voice-picker-design.md) v2, commit `e6c8098`.

**Adversarial review artifacts:** [dev/adversarial/2026-04-21-nav-voice-picker-r{1..5}-*.md](../../../dev/adversarial/), commit `fbcfd7e`. 17 MUST-FIX findings all addressed in spec v2; cited per-task below.

---

## Execution guardrails (read before first task)

- **Branch:** Work on `dev` in the main repo at `/home/administrator/Code/geographica`. **Do NOT create a worktree** — worktrees are BANNED per [CLAUDE.md](../../../CLAUDE.md) §"Git workflow — worktrees are BANNED".
- **Destructive git commands are BANNED** — no `git reset --hard`, no `git push --force`, no `git commit --amend` on shared commits, no `git checkout -- .`. If you think you need one, stop and ask.
- **Commit trailers MUST include `Agent: ocotillo`** on every commit this plan produces. Example:
  ```
  feat(voice-picker): <subject>

  <body>

  Agent: ocotillo
  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  ```
- **Subagent moniker inheritance:** if you dispatch subagents (via the Agent tool) to execute any task, their prompts MUST include the line `"You are agent ocotillo; use this in your commit trailers."` Failure to inherit creates commits that can't be traced back to this session during post-hoc forensics.
- **TDD protocol:** write a failing test FIRST for every behavior task, run it, see it fail, THEN implement. No "write the whole module, then tests" shortcuts.
- **Never stop production stack** (`docker compose down`) without explicit user permission. The `geographica-frontend` container uses a bind-mount, so file edits are live on page reload.
- **Before commit**: the commit message's trailer line MUST be on its own line above `Co-Authored-By:`. Git trailers are order-agnostic but the convention is `Agent:` last-but-one.

## Per-task TDD preamble (do once per task)

Before the first step of every behavior task:

1. If you haven't already this session, invoke `superpowers:test-driven-development` and `superpowers:verification-before-completion` to refresh the discipline. Also read [docs/pitfalls/testing-pitfalls.md](../../pitfalls/testing-pitfalls.md) and [docs/pitfalls/implementation-pitfalls.md](../../pitfalls/implementation-pitfalls.md).
2. Verify branch: `git branch --show-current` → expect `dev`. Verify working-tree cleanliness scoped to your about-to-touch files: `git status <paths>`.
3. Follow TDD: write failing test → run to confirm red → implement → run to confirm green.

## Per-task completion check (do before marking task done)

1. Re-read your added tests against [docs/pitfalls/testing-pitfalls.md](../../pitfalls/testing-pitfalls.md). Are error paths tested? Edge cases? Async timing?
2. Run the relevant test subset AND confirm green output with your own eyes (per `verification-before-completion` skill: copy the actual terminal output into the task; do not paraphrase).
3. Confirm the commit trailer includes `Agent: ocotillo`.

## Review loops between phases

After every phase (every 4-6 tasks), pause and run THREE review rounds from different angles: correctness, test coverage, subagent-readiness of the remaining work. If substantive issues surface in round 3, keep reviewing until clean. Document the review in your private journal / todo list and proceed.

---

## File structure

Files created or modified by this plan:

| Path | Action | Responsibility |
|---|---|---|
| `frontend/voice-picker.js` | **Create** | The whole feature — IIFE module, public API (`VoicePicker.init`, `getUtteranceVoice`, `onVoiceListChanged`), private state, DOM handlers, preview lifecycle |
| `frontend/tests/voice-picker/_fixtures.js` | **Create** | Shared mocks: `speechSynthesis` (async), `localStorage`, `document`, `navigator`; 4 voice-list fixtures (macOS, iOS, Windows, Linux) |
| `frontend/tests/voice-picker/<N>.test.mjs` | **Create** (11 files) | `node --test` sandboxed tests, one per behavior cluster |
| `tests/test_frontend_voice_picker.py` | **Create** | Python structural tests (pytest). Filename matches `test_frontend_*.py` CI glob. |
| `frontend/index.html` | **Modify** | Replace `<h3>Units</h3>`/`<h3>Coordinates</h3>` block with `<h3>Preferences</h3>` containing voice picker + Units + Coordinates sub-groups; insert `<script src="voice-picker.js?v=20260421">` |
| `frontend/style.css` | **Modify** | Append `.pref-*` selectors and global `.sr-only` utility |
| `frontend/nav-ui.js` | **Modify** (surgical) | Insert 4 lines in `onVoice(text)` between `utterance.lang = ...` and `speechSynthesis.speak(utterance)` |
| `frontend/app.js` | **Modify** (surgical) | (a) dispatch `CustomEvent('geographica:sidebar')` from `setSidebarOpen`; (b) call `VoicePicker.init()` from the DOMContentLoaded handler |
| `CHANGELOG.md` | **Modify** | Add entry under Unreleased: nav voice picker + hard-refresh note |

No Docker config, no pipeline config, no Python service code changes. Entirely frontend.

---

## Phase 0 — Foundation (tests can load the module; mocks are realistic)

### Task 0.1: Create voice-picker.js skeleton

**Rationale:** Without a minimally-parseable module at `frontend/voice-picker.js`, `vm.createContext` in Phase 1 tests will throw and the TDD loop can't start. Skeleton attaches the three public methods as no-ops. No tests yet — skeleton is too trivial to red-green-refactor.

**Files:**
- Create: `frontend/voice-picker.js`

- [ ] **Step 1: Write the skeleton**

```js
(function () {
  'use strict';
  if (window.VoicePicker) return; // duplicate-load guard

  window.VoicePicker = {
    init: function () {},
    getUtteranceVoice: function () { return null; },
    onVoiceListChanged: function (_callback) {},
  };
})();
```

- [ ] **Step 2: Verify the file parses under Node**

Run: `node --check frontend/voice-picker.js`

Expected: exits 0 silently. Any parse error → fix.

- [ ] **Step 3: Commit**

```bash
git add frontend/voice-picker.js
git commit -m "$(cat <<'EOF'
feat(voice-picker): skeleton IIFE module with public API stubs

Parses cleanly; public methods no-op. Phases 1-3 add real behavior
via TDD. Enables node:vm-based tests to load the module without
"function not defined" errors.

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 0.2: Create shared test fixtures (_fixtures.js)

**Files:**
- Create: `frontend/tests/voice-picker/_fixtures.js`

- [ ] **Step 1: Write the fixtures module**

```js
// frontend/tests/voice-picker/_fixtures.js
// Shared mocks for voice-picker unit tests. Pattern mirrors frontend/tests/wake-lock/_fixtures.js.

// speechSynthesis mock with ASYNC event delivery (R2 F2.12).
// onstart/onend/onerror fire via queueMicrotask, not synchronously.
function makeSpeechSynthesisMock(opts) {
  opts = opts || {};
  var queue = [];
  var speaking = false;
  var listeners = {};  // { voiceschanged: [fn, ...] }
  var cancelFiresEnd = opts.cancelFiresEnd === true;  // default false (W3C-correct)

  var api = {
    _voices: opts.voices || [],
    _speakCalls: [],
    _cancelCalls: 0,

    getVoices: function () { return api._voices.slice(); },

    speak: function (utt) {
      api._speakCalls.push(utt);
      queue.push(utt);
      speaking = true;
      queueMicrotask(function () {
        if (typeof utt.onstart === 'function') utt.onstart({});
      });
      queueMicrotask(function () {
        if (queue.indexOf(utt) === -1) return;  // cancelled
        queue = queue.filter(function (q) { return q !== utt; });
        if (queue.length === 0) speaking = false;
        if (typeof utt.onend === 'function') utt.onend({});
      });
    },

    cancel: function () {
      api._cancelCalls++;
      var wasQueue = queue.slice();
      queue = [];
      speaking = false;
      // W3C: cancelled utterance fires error, NOT end (R1 F1.1).
      wasQueue.forEach(function (utt) {
        queueMicrotask(function () {
          if (cancelFiresEnd) {
            if (typeof utt.onend === 'function') utt.onend({});
          } else {
            if (typeof utt.onerror === 'function') utt.onerror({ error: 'interrupted' });
          }
        });
      });
    },

    addEventListener: function (type, fn) {
      (listeners[type] = listeners[type] || []).push(fn);
    },
    removeEventListener: function (type, fn) {
      listeners[type] = (listeners[type] || []).filter(function (f) { return f !== fn; });
    },
    _fire: function (type) {
      (listeners[type] || []).forEach(function (fn) { fn({}); });
    },
    _setVoices: function (voices) {
      api._voices = voices;
      api._fire('voiceschanged');
    },
    get speaking() { return speaking; },
    get pending() { return queue.length > 0; },
  };
  return api;
}

// localStorage mock.
function makeLocalStorageMock() {
  var store = {};
  return {
    getItem: function (k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
    setItem: function (k, v) { store[k] = String(v); },
    removeItem: function (k) { delete store[k]; },
    clear: function () { store = {}; },
    get _raw() { return store; },
  };
}

// Minimal document mock with event dispatch + classList on body.
function makeDocumentMock() {
  var listeners = {};
  var body = {
    _classes: new Set(),
    classList: {
      add: function (c) { body._classes.add(c); },
      remove: function (c) { body._classes.delete(c); },
      contains: function (c) { return body._classes.has(c); },
      toggle: function (c) { body._classes.has(c) ? body._classes.delete(c) : body._classes.add(c); },
    },
    className: '',
  };
  Object.defineProperty(body, 'className', {
    get: function () { return Array.from(body._classes).join(' '); },
    set: function (v) {
      body._classes.clear();
      String(v).split(/\s+/).filter(Boolean).forEach(function (c) { body._classes.add(c); });
    },
  });

  var elements = {};  // id → minimal element mock

  return {
    body: body,
    addEventListener: function (type, fn) {
      (listeners[type] = listeners[type] || []).push(fn);
    },
    removeEventListener: function (type, fn) {
      listeners[type] = (listeners[type] || []).filter(function (f) { return f !== fn; });
    },
    dispatchEvent: function (ev) {
      (listeners[ev.type] || []).forEach(function (fn) { fn(ev); });
      return true;
    },
    getElementById: function (id) { return elements[id] || null; },
    _registerElement: function (id, el) { elements[id] = el; },
    _listeners: listeners,
  };
}

// navigator mock with configurable UA (for iOS detection tests).
function makeNavigatorMock(userAgent) {
  return { userAgent: userAgent || 'Mozilla/5.0 (node test)' };
}

// Voice-list fixtures. Each voice is a plain object matching SpeechSynthesisVoice shape.
var FIXTURES = {
  macos10: [
    { voiceURI: 'com.apple.ttsbundle.Samantha-compact', name: 'Samantha', lang: 'en-US', localService: true, default: true },
    { voiceURI: 'com.apple.speech.synthesis.voice.alex', name: 'Alex', lang: 'en-US', localService: true, default: false },
    { voiceURI: 'com.apple.ttsbundle.Daniel-compact', name: 'Daniel', lang: 'en-GB', localService: true, default: false },
    { voiceURI: 'com.apple.speech.synthesis.voice.karen', name: 'Karen', lang: 'en-AU', localService: true, default: false },
    { voiceURI: 'com.apple.ttsbundle.Moira-compact', name: 'Moira', lang: 'en-IE', localService: true, default: false },
    { voiceURI: 'com.apple.ttsbundle.Tom-compact', name: 'Tom', lang: 'en-US', localService: true, default: false },
    { voiceURI: 'com.apple.ttsbundle.Victoria-compact', name: 'Victoria', lang: 'en-US', localService: true, default: false },
    { voiceURI: 'com.apple.ttsbundle.Fred-compact', name: 'Fred', lang: 'en-US', localService: true, default: false },
    { voiceURI: 'com.apple.ttsbundle.Samantha-enhanced', name: 'Samantha (Enhanced)', lang: 'en-US', localService: true, default: false },
    { voiceURI: 'Google US English', name: 'Google US English', lang: 'en-US', localService: false, default: false },
  ],
  ios2: [
    { voiceURI: 'com.apple.ttsbundle.Samantha-compact', name: 'Samantha', lang: 'en-US', localService: true, default: true },
    { voiceURI: 'com.apple.ttsbundle.Daniel-compact', name: 'Daniel', lang: 'en-GB', localService: true, default: false },
  ],
  windowsEdge6: [
    { voiceURI: 'Microsoft Zira Desktop', name: 'Microsoft Zira - English (United States)', lang: 'en-US', localService: true, default: true },
    { voiceURI: 'Microsoft David Desktop', name: 'Microsoft David - English (United States)', lang: 'en-US', localService: true, default: false },
    { voiceURI: 'Microsoft Mark Mobile', name: 'Microsoft Mark - English (United States)', lang: 'en-US', localService: true, default: false },
    { voiceURI: 'Microsoft Hazel Desktop', name: 'Microsoft Hazel - English (Great Britain)', lang: 'en-GB', localService: true, default: false },
    { voiceURI: 'Microsoft George Mobile', name: 'Microsoft George - English (Great Britain)', lang: 'en-GB', localService: true, default: false },
    { voiceURI: 'Microsoft Susan Desktop', name: 'Microsoft Susan - English (Great Britain)', lang: 'en-GB', localService: true, default: false },
  ],
  linuxFirefox3: [
    { voiceURI: 'urn:moz-tts:speechd:english', name: 'english', lang: 'en', localService: true, default: true },
    { voiceURI: 'urn:moz-tts:speechd:english-us', name: 'english-us', lang: 'en-US', localService: true, default: false },
    { voiceURI: 'urn:moz-tts:speechd:english-rp', name: 'english-rp', lang: 'en-GB', localService: true, default: false },
  ],
  empty: [],
  degenerate: [
    { voiceURI: 'weird-1', name: '', lang: 'en-US', localService: true },
    { voiceURI: 'weird-2', name: undefined, lang: 'en-US', localService: true },
    { voiceURI: 'com.apple.samantha', name: 'Samantha', lang: 'en-US', localService: true, default: true },
    { voiceURI: 'com.apple.daniel', name: 'Daniel', lang: 'en-GB', localService: true, default: true },
    { voiceURI: 'weird-3', name: '日本語', lang: 'en-US', localService: true },
  ],
};

module.exports = {
  makeSpeechSynthesisMock: makeSpeechSynthesisMock,
  makeLocalStorageMock: makeLocalStorageMock,
  makeDocumentMock: makeDocumentMock,
  makeNavigatorMock: makeNavigatorMock,
  FIXTURES: FIXTURES,
};
```

- [ ] **Step 2: Verify fixtures module loads**

Run: `node -e "console.log(Object.keys(require('./frontend/tests/voice-picker/_fixtures.js')))"`

Expected: `[ 'makeSpeechSynthesisMock', 'makeLocalStorageMock', 'makeDocumentMock', 'makeNavigatorMock', 'FIXTURES' ]`

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/voice-picker/_fixtures.js
git commit -m "$(cat <<'EOF'
test(voice-picker): shared fixtures module for JS unit tests

Provides async speechSynthesis mock (W3C-correct: cancel fires
error not end, per R1 F1.1), localStorage mock, document mock with
body classList + event dispatch, navigator mock, and four voice-list
fixtures covering macOS (10 voices), iOS (2), Windows Edge (6),
Linux Firefox (3) plus empty + degenerate shapes.

Mirrors the pattern at frontend/tests/wake-lock/_fixtures.js.

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 0.3: Meta-test — fixture async timing is correct

**Files:**
- Create: `frontend/tests/voice-picker/_fixtures.test.mjs`

- [ ] **Step 1: Write the meta-test**

```js
// frontend/tests/voice-picker/_fixtures.test.mjs
import { test } from 'node:test';
import assert from 'node:assert';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { makeSpeechSynthesisMock } = require('./_fixtures.js');

test('mock onstart fires asynchronously, not synchronously', async () => {
  const ss = makeSpeechSynthesisMock();
  let onstartCalled = false;
  const utt = {
    onstart: () => { onstartCalled = true; },
    onend: () => {},
    onerror: () => {},
  };
  ss.speak(utt);
  assert.strictEqual(onstartCalled, false, 'onstart must not fire synchronously');
  await new Promise(r => setImmediate(r));
  assert.strictEqual(onstartCalled, true, 'onstart must fire after a microtask');
});

test('cancel fires onerror (not onend) per W3C spec', async () => {
  const ss = makeSpeechSynthesisMock();
  let endFired = false, errorFired = false;
  const utt = {
    onstart: () => {},
    onend: () => { endFired = true; },
    onerror: () => { errorFired = true; },
  };
  ss.speak(utt);
  ss.cancel();
  await new Promise(r => setImmediate(r));
  assert.strictEqual(endFired, false, 'cancelled utterance must NOT fire onend');
  assert.strictEqual(errorFired, true, 'cancelled utterance MUST fire onerror');
});
```

- [ ] **Step 2: Run test and verify green**

Run: `cd /home/administrator/Code/geographica && node --test frontend/tests/voice-picker/_fixtures.test.mjs`

Expected: `# pass 2` in the summary.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/voice-picker/_fixtures.test.mjs
git commit -m "$(cat <<'EOF'
test(voice-picker): meta-test that speechSynthesis mock is async

Guards against future refactors regressing to synchronous event
delivery, which would hide the real-browser timing bugs this
feature's adversarial review (R1 F1.1, R2 F2.12) was designed to
catch.

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 1 — Pure logic (gender inference, persistence, resolution)

### Task 1.1: gender-inference.test.mjs + inferGender implementation

**Files:**
- Create: `frontend/tests/voice-picker/gender-inference.test.mjs`
- Modify: `frontend/voice-picker.js` (add `KNOWN_VOICES` and `_inferGender`)

- [ ] **Step 1: Write the failing test**

```js
// frontend/tests/voice-picker/gender-inference.test.mjs
import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(path.join(__dirname, '../../voice-picker.js'), 'utf-8');

function loadVoicePicker() {
  const ctx = vm.createContext({ window: {}, console: console });
  vm.runInContext(SOURCE, ctx);
  return ctx.window.VoicePicker;
}

test('inferGender: exact table match — Apple bare names', () => {
  const vp = loadVoicePicker();
  assert.strictEqual(vp._inferGender('Samantha'), 'female');
  assert.strictEqual(vp._inferGender('Alex'), 'male');
  assert.strictEqual(vp._inferGender('Daniel'), 'male');
  assert.strictEqual(vp._inferGender('Karen'), 'female');
});

test('inferGender: handles Apple Enhanced/Premium suffix', () => {
  const vp = loadVoicePicker();
  assert.strictEqual(vp._inferGender('Samantha (Enhanced)'), 'female');
  assert.strictEqual(vp._inferGender('Alex (Premium)'), 'male');
});

test('inferGender: Microsoft prefix + locale descriptor stripped', () => {
  const vp = loadVoicePicker();
  assert.strictEqual(vp._inferGender('Microsoft David - English (United States)'), 'male');
  assert.strictEqual(vp._inferGender('Microsoft Zira - English (United States)'), 'female');
  assert.strictEqual(vp._inferGender('Microsoft David Desktop'), 'male');
});

test('inferGender: Google substring fallback', () => {
  const vp = loadVoicePicker();
  assert.strictEqual(vp._inferGender('Google US English Female'), 'female');
  assert.strictEqual(vp._inferGender('Google UK English Male'), 'male');
  assert.strictEqual(vp._inferGender('Google US English'), null, 'no gender token → null');
});

test('inferGender: word-boundary regex does not false-positive', () => {
  const vp = loadVoicePicker();
  // The false-positive guards that R3 F3.4 demanded explicit tests for.
  assert.strictEqual(vp._inferGender('femaleness'), null, '"femaleness" contains "male" substring but should not match');
  assert.strictEqual(vp._inferGender('Emanuel'), null, '"Emanuel" contains "man" substring but should not match');
  assert.strictEqual(vp._inferGender('Norman'), null, '"Norman" contains "man" substring but should not match');
  assert.strictEqual(vp._inferGender('Boyce'), null, '"Boyce" contains "boy" substring but should not match');
  assert.strictEqual(vp._inferGender('Woman'), 'female');
});

test('inferGender: null/undefined/empty safe', () => {
  const vp = loadVoicePicker();
  assert.strictEqual(vp._inferGender(null), null);
  assert.strictEqual(vp._inferGender(undefined), null);
  assert.strictEqual(vp._inferGender(''), null);
  assert.strictEqual(vp._inferGender(123), null);
});

test('inferGender: unknown name returns null', () => {
  const vp = loadVoicePicker();
  assert.strictEqual(vp._inferGender('Xyzzy'), null);
  assert.strictEqual(vp._inferGender('english-rp'), null);  // Linux eSpeak
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test frontend/tests/voice-picker/gender-inference.test.mjs`

Expected: tests fail with `TypeError: vp._inferGender is not a function` — confirms the module has no such method yet.

- [ ] **Step 3: Add KNOWN_VOICES table + inferGender to voice-picker.js**

Replace the skeleton with:

```js
(function () {
  'use strict';
  if (window.VoicePicker) return; // duplicate-load guard

  var KNOWN_VOICES = {
    // Apple — iOS + macOS (post-tokenization)
    'Samantha': 'female', 'Karen': 'female', 'Moira': 'female', 'Tessa': 'female',
    'Victoria': 'female', 'Veena': 'female', 'Fiona': 'female',
    'Kate': 'female', 'Serena': 'female',
    'Alex': 'male', 'Daniel': 'male', 'Fred': 'male', 'Oliver': 'male',
    'Tom': 'male', 'Rishi': 'male', 'Aaron': 'male',
    // Microsoft — Edge on Windows
    'Zira': 'female', 'Hazel': 'female', 'Susan': 'female',
    'David': 'male', 'Mark': 'male', 'George': 'male', 'James': 'male'
  };

  function inferGender(rawName) {
    if (!rawName || typeof rawName !== 'string') return null;
    var name = rawName.replace(/^(Microsoft|Google|Apple|Siri)\s+/i, '');
    name = name.replace(/\s*\((?:Enhanced|Premium|Compact|Natural)\)\s*/gi, '');
    name = name.replace(/\s+(?:Desktop|Mobile)\b/gi, '');
    name = name.replace(/\s*-\s*English.*$/i, '');
    var firstToken = name.split(/[\s\-_]+/)[0];
    if (KNOWN_VOICES[firstToken]) return KNOWN_VOICES[firstToken];
    if (/\b(?:female|woman|girl)\b/i.test(rawName)) return 'female';
    if (/(?<!fe)\b(?:male|man|boy)\b/i.test(rawName)) return 'male';
    return null;
  }

  window.VoicePicker = {
    init: function () {},
    getUtteranceVoice: function () { return null; },
    onVoiceListChanged: function (_callback) {},
    _inferGender: inferGender,
    _KNOWN_VOICES: KNOWN_VOICES,
  };
})();
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test frontend/tests/voice-picker/gender-inference.test.mjs`

Expected: `# pass 7` in summary.

- [ ] **Step 5: Commit**

```bash
git add frontend/voice-picker.js frontend/tests/voice-picker/gender-inference.test.mjs
git commit -m "$(cat <<'EOF'
feat(voice-picker): inferGender + KNOWN_VOICES table

Explicit prefix/suffix stripping for Microsoft/Google/Apple voice
naming conventions per R1 F1.7. Word-boundary regex with
(?<!fe) negative lookbehind prevents "male" matching "female" (R3 F3.4).

7 test cases including all four R3 F3.4 false-positive guards
(femaleness, Emanuel, Norman, Boyce) pass.

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 1.2: known-voices.test.mjs — table invariants

**Files:**
- Create: `frontend/tests/voice-picker/known-voices.test.mjs`

- [ ] **Step 1: Write the failing tests**

```js
// frontend/tests/voice-picker/known-voices.test.mjs
import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(path.join(__dirname, '../../voice-picker.js'), 'utf-8');

function loadVoicePicker() {
  const ctx = vm.createContext({ window: {}, console: console });
  vm.runInContext(SOURCE, ctx);
  return ctx.window.VoicePicker;
}

test('KNOWN_VOICES has no duplicate keys (source-level parse)', () => {
  const match = SOURCE.match(/var KNOWN_VOICES\s*=\s*\{([\s\S]+?)\};/);
  assert.ok(match, 'KNOWN_VOICES declaration not found in source');
  const body = match[1];
  const keys = Array.from(body.matchAll(/'([^']+)'\s*:/g)).map(m => m[1]);
  const unique = new Set(keys);
  assert.strictEqual(keys.length, unique.size,
    `KNOWN_VOICES has duplicate keys: ${keys.length} total, ${unique.size} unique`);
});

test('KNOWN_VOICES: every value is strictly "male" or "female"', () => {
  const vp = loadVoicePicker();
  for (const [name, gender] of Object.entries(vp._KNOWN_VOICES)) {
    assert.ok(gender === 'male' || gender === 'female',
      `${name}: expected "male" or "female", got "${gender}"`);
  }
});

test('KNOWN_VOICES: has at least 20 entries', () => {
  const vp = loadVoicePicker();
  const count = Object.keys(vp._KNOWN_VOICES).length;
  assert.ok(count >= 20, `KNOWN_VOICES should have >= 20 entries, has ${count}`);
});
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `node --test frontend/tests/voice-picker/known-voices.test.mjs`

Expected: `# pass 3`.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/voice-picker/known-voices.test.mjs
git commit -m "$(cat <<'EOF'
test(voice-picker): KNOWN_VOICES regression guards

Closes R3 F3.3: no duplicate keys (silent overwrite in JS), value
typos (strict === 'male'/'female'), table-emptied-by-merge-conflict
(minimum entry count).

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 1.3: preference-persistence.test.mjs + readPref/writePref

**Files:**
- Create: `frontend/tests/voice-picker/preference-persistence.test.mjs`
- Modify: `frontend/voice-picker.js`

- [ ] **Step 1: Write the failing tests**

```js
// frontend/tests/voice-picker/preference-persistence.test.mjs
import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { makeLocalStorageMock } = require('./_fixtures.js');
const SOURCE = fs.readFileSync(path.join(__dirname, '../../voice-picker.js'), 'utf-8');

function loadVoicePicker(opts) {
  opts = opts || {};
  const ls = opts.localStorage || makeLocalStorageMock();
  const win = { localStorage: ls };
  const ctx = vm.createContext({ window: win, localStorage: ls, console: console });
  vm.runInContext(SOURCE, ctx);
  return { vp: ctx.window.VoicePicker, ls: ls };
}

test('readPref: missing key → default mode', () => {
  const { vp } = loadVoicePicker();
  const pref = vp._readPref();
  assert.strictEqual(pref.mode, 'default');
});

test('readPref: corrupt JSON → default mode', () => {
  const ls = makeLocalStorageMock();
  ls.setItem('nav-voice-pref', '{not valid json');
  const { vp } = loadVoicePicker({ localStorage: ls });
  assert.strictEqual(vp._readPref().mode, 'default');
});

test('readPref: unknown version → default mode', () => {
  const ls = makeLocalStorageMock();
  ls.setItem('nav-voice-pref', JSON.stringify({ mode: 'gender', gender: 'male', version: 2 }));
  const { vp } = loadVoicePicker({ localStorage: ls });
  assert.strictEqual(vp._readPref().mode, 'default');
});

test('writePref: gender-button path round-trips', () => {
  const { vp, ls } = loadVoicePicker();
  vp._writePref({ mode: 'gender', gender: 'female' });
  const raw = ls.getItem('nav-voice-pref');
  const parsed = JSON.parse(raw);
  assert.strictEqual(parsed.mode, 'gender');
  assert.strictEqual(parsed.gender, 'female');
  assert.strictEqual(parsed.voice, null);
  assert.strictEqual(parsed.storedGenderHint, null);
  assert.strictEqual(parsed.allowCloudVoices, false);
  assert.strictEqual(parsed.version, 1);
  assert.deepStrictEqual(vp._readPref(), parsed);
});

test('writePref: specific-voice path stores composite identifier + gender hint', () => {
  const { vp, ls } = loadVoicePicker();
  vp._writePref({
    mode: 'specific',
    voice: { voiceURI: 'com.apple.samantha', name: 'Samantha', lang: 'en-US' },
  });
  const parsed = JSON.parse(ls.getItem('nav-voice-pref'));
  assert.strictEqual(parsed.mode, 'specific');
  assert.deepStrictEqual(parsed.voice, { voiceURI: 'com.apple.samantha', name: 'Samantha', lang: 'en-US' });
  assert.strictEqual(parsed.storedGenderHint, 'female',
    'storedGenderHint should be computed at write-time from inferGender(voice.name)');
});

test('writePref: unavailable state preserves voice for display', () => {
  const { vp, ls } = loadVoicePicker();
  vp._writePref({
    mode: 'unavailable',
    voice: { voiceURI: 'com.apple.gone', name: 'Gone Voice', lang: 'en-US' },
  });
  const parsed = JSON.parse(ls.getItem('nav-voice-pref'));
  assert.strictEqual(parsed.mode, 'unavailable');
  assert.strictEqual(parsed.voice.name, 'Gone Voice');
});

test('writePref: allowCloudVoices persists across writes', () => {
  const { vp, ls } = loadVoicePicker();
  vp._writePref({ mode: 'default', allowCloudVoices: true });
  let parsed = JSON.parse(ls.getItem('nav-voice-pref'));
  assert.strictEqual(parsed.allowCloudVoices, true);
  vp._writePref({ mode: 'gender', gender: 'male', allowCloudVoices: true });
  parsed = JSON.parse(ls.getItem('nav-voice-pref'));
  assert.strictEqual(parsed.allowCloudVoices, true);
});
```

- [ ] **Step 2: Run test to verify failure**

Run: `node --test frontend/tests/voice-picker/preference-persistence.test.mjs`

Expected: failure with `_readPref is not a function` or similar.

- [ ] **Step 3: Add read/write to voice-picker.js**

Inside the IIFE in `voice-picker.js`, below `inferGender`:

```js
  var LS_KEY = 'nav-voice-pref';

  function readPref() {
    var raw;
    try { raw = window.localStorage.getItem(LS_KEY); } catch (e) { return { mode: 'default' }; }
    if (!raw) return { mode: 'default' };
    var parsed;
    try { parsed = JSON.parse(raw); } catch (e) { return { mode: 'default' }; }
    if (!parsed || parsed.version !== 1) return { mode: 'default' };
    return parsed;
  }

  function writePref(update) {
    var prev = readPref();
    if (prev.version !== 1) prev = {};  // start fresh if version mismatch
    var next = {
      mode: update.mode != null ? update.mode : (prev.mode || 'default'),
      gender: update.gender != null ? update.gender : (prev.gender || null),
      voice: update.voice !== undefined ? update.voice : (prev.voice || null),
      storedGenderHint: update.storedGenderHint !== undefined
        ? update.storedGenderHint
        : (update.voice && update.voice.name ? inferGender(update.voice.name) : (prev.storedGenderHint || null)),
      allowCloudVoices: update.allowCloudVoices !== undefined ? update.allowCloudVoices : (prev.allowCloudVoices || false),
      version: 1,
    };
    if (next.mode === 'gender' || next.mode === 'default') {
      next.voice = null;
      next.storedGenderHint = null;
    }
    try { window.localStorage.setItem(LS_KEY, JSON.stringify(next)); } catch (e) { /* quota, private mode */ }
    return next;
  }
```

Add to public API:

```js
    _readPref: readPref,
    _writePref: writePref,
    _LS_KEY: LS_KEY,
```

- [ ] **Step 4: Run tests and verify all 7 pass**

Run: `node --test frontend/tests/voice-picker/preference-persistence.test.mjs`

Expected: `# pass 7`.

- [ ] **Step 5: Commit**

```bash
git add frontend/voice-picker.js frontend/tests/voice-picker/preference-persistence.test.mjs
git commit -m "$(cat <<'EOF'
feat(voice-picker): localStorage read/write with schema version

Read: key missing, corrupt JSON, unknown version → default mode.
Write: five paths per spec §5.4. Computes storedGenderHint at
write-time for later fallback (R5 F5.5 prep).

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 1.4: voice-resolution.test.mjs + getUtteranceVoice core

**Files:**
- Create: `frontend/tests/voice-picker/voice-resolution.test.mjs`
- Modify: `frontend/voice-picker.js`

- [ ] **Step 1: Write the failing test**

```js
// frontend/tests/voice-picker/voice-resolution.test.mjs
import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { makeSpeechSynthesisMock, makeLocalStorageMock, FIXTURES } = require('./_fixtures.js');
const SOURCE = fs.readFileSync(path.join(__dirname, '../../voice-picker.js'), 'utf-8');

function load(fixtureName) {
  const ss = makeSpeechSynthesisMock({ voices: FIXTURES[fixtureName] });
  const ls = makeLocalStorageMock();
  const win = { speechSynthesis: ss, localStorage: ls, navigator: { userAgent: 'test' } };
  const ctx = vm.createContext({ window: win, speechSynthesis: ss, localStorage: ls, console: console });
  vm.runInContext(SOURCE, ctx);
  return { vp: ctx.window.VoicePicker, ss: ss, ls: ls };
}

test('resolution: default mode → null (browser default)', () => {
  const { vp } = load('macos10');
  assert.strictEqual(vp.getUtteranceVoice(), null);
});

test('resolution: gender male on macOS → Alex (first en-* male in stable sort)', () => {
  const { vp } = load('macos10');
  vp._writePref({ mode: 'gender', gender: 'male' });
  const v = vp.getUtteranceVoice();
  assert.ok(v, 'must resolve a voice');
  assert.strictEqual(v.name, 'Alex');
});

test('resolution: gender female on macOS → Samantha', () => {
  const { vp } = load('macos10');
  vp._writePref({ mode: 'gender', gender: 'female' });
  assert.strictEqual(vp.getUtteranceVoice().name, 'Samantha');
});

test('resolution: specific voice match by voiceURI', () => {
  const { vp } = load('macos10');
  vp._writePref({
    mode: 'specific',
    voice: { voiceURI: 'com.apple.ttsbundle.Daniel-compact', name: 'Daniel', lang: 'en-GB' },
  });
  const v = vp.getUtteranceVoice();
  assert.strictEqual(v.name, 'Daniel');
  assert.strictEqual(v.lang, 'en-GB');
});

test('resolution: localService=false voices filtered unless allowCloudVoices', () => {
  const { vp } = load('macos10');
  vp._writePref({
    mode: 'specific',
    voice: { voiceURI: 'Google US English', name: 'Google US English', lang: 'en-US' },
    allowCloudVoices: false,
  });
  const v = vp.getUtteranceVoice();
  assert.strictEqual(v, null, 'cloud voice must be excluded with allowCloudVoices=false');

  vp._writePref({
    mode: 'specific',
    voice: { voiceURI: 'Google US English', name: 'Google US English', lang: 'en-US' },
    allowCloudVoices: true,
  });
  const v2 = vp.getUtteranceVoice();
  assert.ok(v2, 'cloud voice must resolve when allowCloudVoices=true');
  assert.strictEqual(v2.name, 'Google US English');
});

test('resolution: Windows Edge — gender male resolves via post-strip inference', () => {
  const { vp } = load('windowsEdge6');
  vp._writePref({ mode: 'gender', gender: 'male' });
  const v = vp.getUtteranceVoice();
  assert.ok(v);
  assert.match(v.name, /David|Mark|George/);
  assert.strictEqual(vp._inferGender(v.name), 'male');
});

test('resolution: iOS 2-voice — male resolves to Daniel', () => {
  const { vp } = load('ios2');
  vp._writePref({ mode: 'gender', gender: 'male' });
  const v = vp.getUtteranceVoice();
  assert.strictEqual(v.name, 'Daniel');
});

test('resolution: Linux eSpeak — no matching names → null for gender mode', () => {
  const { vp } = load('linuxFirefox3');
  vp._writePref({ mode: 'gender', gender: 'male' });
  assert.strictEqual(vp.getUtteranceVoice(), null);
});

test('resolution: gender-mode stable across list reordering', () => {
  const { vp, ss } = load('macos10');
  vp._writePref({ mode: 'gender', gender: 'female' });
  const first = vp.getUtteranceVoice();
  ss._setVoices(FIXTURES.macos10.slice().reverse());
  const second = vp.getUtteranceVoice();
  assert.strictEqual(second.voiceURI, first.voiceURI,
    'stable sort must resolve the same voice regardless of getVoices() order');
});

test('resolution: empty voice list → null', () => {
  const { vp } = load('empty');
  vp._writePref({ mode: 'gender', gender: 'male' });
  assert.strictEqual(vp.getUtteranceVoice(), null);
});
```

- [ ] **Step 2: Run — verify failure**

Run: `node --test frontend/tests/voice-picker/voice-resolution.test.mjs`

Expected: multiple test failures.

- [ ] **Step 3: Implement getUtteranceVoice in voice-picker.js**

Add to the IIFE, below `writePref`:

```js
  function candidateVoices(allowCloud) {
    var list;
    try { list = window.speechSynthesis.getVoices(); } catch (e) { return []; }
    if (!list || !list.length) return [];
    return list.filter(function (v) {
      if (!v || typeof v.lang !== 'string' || !/^en[-_]?/i.test(v.lang)) return false;
      if (!allowCloud && v.localService === false) return false;
      return true;
    }).sort(function (a, b) {
      return (a.voiceURI || '').localeCompare(b.voiceURI || '');
    });
  }

  function resolveVoice(pref, candidates) {
    if (pref.mode === 'default') return null;

    if (pref.mode === 'specific' && pref.voice) {
      var byURI = candidates.find(function (v) { return v.voiceURI === pref.voice.voiceURI; });
      if (byURI) return byURI;
      var byNameLang = candidates.find(function (v) {
        return v.name === pref.voice.name && v.lang === pref.voice.lang;
      });
      if (byNameLang) return byNameLang;
      if (pref.storedGenderHint) {
        var byHint = candidates.find(function (v) { return inferGender(v.name) === pref.storedGenderHint; });
        if (byHint) return byHint;
      }
      return null;
    }

    if (pref.mode === 'gender' && pref.gender) {
      return candidates.find(function (v) { return inferGender(v.name) === pref.gender; }) || null;
    }

    if (pref.mode === 'unavailable' && pref.voice) {
      var reappeared = candidates.find(function (v) { return v.voiceURI === pref.voice.voiceURI; });
      if (reappeared) return reappeared;
      return null;
    }

    return null;
  }

  function getUtteranceVoice() {
    var pref = readPref();
    var candidates = candidateVoices(pref.allowCloudVoices);
    var v = resolveVoice(pref, candidates);
    if (pref.mode === 'specific' && v === null && pref.voice) {
      writePref({ mode: 'unavailable', voice: pref.voice, storedGenderHint: pref.storedGenderHint });
    }
    return v;
  }
```

Update the public API:

```js
  window.VoicePicker = {
    init: function () {},
    getUtteranceVoice: getUtteranceVoice,
    onVoiceListChanged: function (_callback) {},
    _inferGender: inferGender,
    _KNOWN_VOICES: KNOWN_VOICES,
    _readPref: readPref,
    _writePref: writePref,
    _LS_KEY: LS_KEY,
    _candidateVoices: candidateVoices,
    _resolveVoice: resolveVoice,
  };
```

- [ ] **Step 4: Run tests — all 10 pass**

Run: `node --test frontend/tests/voice-picker/voice-resolution.test.mjs`

Expected: `# pass 10`.

- [ ] **Step 5: Commit**

```bash
git add frontend/voice-picker.js frontend/tests/voice-picker/voice-resolution.test.mjs
git commit -m "$(cat <<'EOF'
feat(voice-picker): core voice resolution with offline-first filter

Closes spec §7.1 + §7.2. Key behaviors:
- Default mode → null (browser picks).
- Gender mode → first candidate (stable sort by voiceURI) whose
  inferGender matches. Idempotent across voiceschanged fires (R2 F2.3).
- Specific mode → voiceURI match → name+lang fallback → gender hint.
  Three-tier lookup closes R1 F1.6.
- localService=false voices excluded unless allowCloudVoices=true.
  Closes R1 F1.8 / R5 F5.1.
- Unavailable state: specific voice missing + no hint fallback →
  auto-persist mode:"unavailable". Closes R5 F5.5.

10 tests covering macOS/iOS/Windows/Linux fixtures (R3 F3.9) plus
stable-sort idempotence.

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 1.5: fallback-behavior.test.mjs + edge-voice-shapes.test.mjs

**Files:**
- Create: `frontend/tests/voice-picker/fallback-behavior.test.mjs`
- Create: `frontend/tests/voice-picker/edge-voice-shapes.test.mjs`

- [ ] **Step 1: Write fallback-behavior test**

```js
// frontend/tests/voice-picker/fallback-behavior.test.mjs
import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { makeSpeechSynthesisMock, makeLocalStorageMock, FIXTURES } = require('./_fixtures.js');
const SOURCE = fs.readFileSync(path.join(__dirname, '../../voice-picker.js'), 'utf-8');

function load(voices) {
  const ss = makeSpeechSynthesisMock({ voices });
  const ls = makeLocalStorageMock();
  const win = { speechSynthesis: ss, localStorage: ls, navigator: { userAgent: 'test' } };
  const ctx = vm.createContext({ window: win, speechSynthesis: ss, localStorage: ls, console: console });
  vm.runInContext(SOURCE, ctx);
  return { vp: ctx.window.VoicePicker, ls };
}

test('fallback: voiceURI match fails, name+lang match succeeds (macOS upgrade case)', () => {
  const voices = [
    { voiceURI: 'com.apple.ttsbundle.siri_female_en-US_premium',
      name: 'Samantha', lang: 'en-US', localService: true, default: true },
  ];
  const { vp } = load(voices);
  vp._writePref({
    mode: 'specific',
    voice: { voiceURI: 'com.apple.ttsbundle.Samantha-compact',
             name: 'Samantha', lang: 'en-US' },
  });
  const v = vp.getUtteranceVoice();
  assert.ok(v, 'must find by name+lang when voiceURI is stale');
  assert.strictEqual(v.voiceURI, 'com.apple.ttsbundle.siri_female_en-US_premium');
});

test('fallback: all lookups fail, storedGenderHint rescues', () => {
  const voices = [
    { voiceURI: 'com.apple.alex', name: 'Alex', lang: 'en-US', localService: true },
    { voiceURI: 'com.apple.karen', name: 'Karen', lang: 'en-AU', localService: true },
  ];
  const { vp } = load(voices);
  vp._writePref({
    mode: 'specific',
    voice: { voiceURI: 'com.apple.gone', name: 'Gone Voice', lang: 'en-US' },
    storedGenderHint: 'female',
  });
  const v = vp.getUtteranceVoice();
  assert.ok(v, 'storedGenderHint fallback must find a voice');
  assert.strictEqual(v.name, 'Karen');
});

test('fallback: all three fail → unavailable state persisted', () => {
  const voices = [{ voiceURI: 'com.apple.alex', name: 'Alex', lang: 'en-US', localService: true }];
  const { vp, ls } = load(voices);
  vp._writePref({
    mode: 'specific',
    voice: { voiceURI: 'com.apple.gone', name: 'Gone', lang: 'en-US' },
    storedGenderHint: 'female',
  });
  assert.strictEqual(vp.getUtteranceVoice(), null);
  const persisted = JSON.parse(ls.getItem('nav-voice-pref'));
  assert.strictEqual(persisted.mode, 'unavailable');
  assert.strictEqual(persisted.voice.name, 'Gone');
});

test('fallback: unavailable → voice reappears → resolves without user action', () => {
  const voicesOriginal = [
    { voiceURI: 'com.apple.samantha', name: 'Samantha', lang: 'en-US', localService: true },
  ];
  const { vp } = load(voicesOriginal);
  vp._writePref({
    mode: 'unavailable',
    voice: { voiceURI: 'com.apple.samantha', name: 'Samantha', lang: 'en-US' },
    storedGenderHint: 'female',
  });
  const v = vp.getUtteranceVoice();
  assert.ok(v, 'voice present in list should resolve from unavailable state');
  assert.strictEqual(v.name, 'Samantha');
});
```

- [ ] **Step 2: Write edge-voice-shapes test**

```js
// frontend/tests/voice-picker/edge-voice-shapes.test.mjs
import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { makeSpeechSynthesisMock, makeLocalStorageMock, FIXTURES } = require('./_fixtures.js');
const SOURCE = fs.readFileSync(path.join(__dirname, '../../voice-picker.js'), 'utf-8');

function load(voices) {
  const ss = makeSpeechSynthesisMock({ voices });
  const ls = makeLocalStorageMock();
  const win = { speechSynthesis: ss, localStorage: ls, navigator: { userAgent: 'test' } };
  const ctx = vm.createContext({ window: win, speechSynthesis: ss, localStorage: ls, console: console });
  vm.runInContext(SOURCE, ctx);
  return { vp: ctx.window.VoicePicker };
}

test('edge: degenerate voices — getUtteranceVoice never throws', () => {
  const { vp } = load(FIXTURES.degenerate);
  assert.doesNotThrow(() => vp.getUtteranceVoice());
  vp._writePref({ mode: 'gender', gender: 'female' });
  assert.doesNotThrow(() => vp.getUtteranceVoice());
  const v = vp.getUtteranceVoice();
  assert.ok(v);
  assert.strictEqual(v.name, 'Samantha');
});

test('edge: inferGender handles empty string and undefined without throwing', () => {
  const { vp } = load([]);
  assert.strictEqual(vp._inferGender(''), null);
  assert.strictEqual(vp._inferGender(undefined), null);
  assert.strictEqual(vp._inferGender(null), null);
  assert.strictEqual(vp._inferGender(123), null);
});

test('edge: lang variations — en, en-US, en_US, EN, EN-gb all match filter', () => {
  const voices = [
    { voiceURI: 'a', name: 'A', lang: 'en', localService: true },
    { voiceURI: 'b', name: 'B', lang: 'en-US', localService: true },
    { voiceURI: 'c', name: 'C', lang: 'en_US', localService: true },
    { voiceURI: 'd', name: 'D', lang: 'EN', localService: true },
    { voiceURI: 'e', name: 'E', lang: 'EN-gb', localService: true },
    { voiceURI: 'f', name: 'F', lang: 'fr-FR', localService: true },
  ];
  const { vp } = load(voices);
  const candidates = vp._candidateVoices(false);
  assert.strictEqual(candidates.length, 5, 'all en-* variants accepted, fr-FR rejected');
});
```

- [ ] **Step 3: Run and verify green**

Run: `node --test frontend/tests/voice-picker/fallback-behavior.test.mjs frontend/tests/voice-picker/edge-voice-shapes.test.mjs`

Expected: `# pass 7` combined.

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/voice-picker/fallback-behavior.test.mjs frontend/tests/voice-picker/edge-voice-shapes.test.mjs
git commit -m "$(cat <<'EOF'
test(voice-picker): fallback chain + degenerate-voice defensive tests

Fallback (R1 F1.6, R5 F5.5): voiceURI → name+lang → storedGenderHint
→ unavailable-state persistence. Also tests unavailable→reappears
normalization path.

Edge shapes (R3 F3.10): empty/undefined/unicode voice names,
lang variants. getUtteranceVoice never throws per G6 contract.

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Phase 1 review loop

- [ ] **Pause and review Phase 0+1:** three rounds covering correctness (spec §7.1 step-for-step), test coverage (R1 F1.6/F1.7/F1.8, R3 F3.3/F3.4, R5 F5.1/F5.5), and pitfall check (async mock timing).

---

## Phase 2 — voiceschanged bootstrap

### Task 2.1: voiceschanged-bootstrap.test.mjs + bootstrap logic

**Files:**
- Create: `frontend/tests/voice-picker/voiceschanged-bootstrap.test.mjs`
- Modify: `frontend/voice-picker.js`

- [ ] **Step 1: Write the failing tests**

```js
// frontend/tests/voice-picker/voiceschanged-bootstrap.test.mjs
import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { makeSpeechSynthesisMock, makeLocalStorageMock, makeDocumentMock, makeNavigatorMock, FIXTURES } = require('./_fixtures.js');
const SOURCE = fs.readFileSync(path.join(__dirname, '../../voice-picker.js'), 'utf-8');

function loadWith(opts) {
  const ss = makeSpeechSynthesisMock({ voices: opts.voices || [] });
  const ls = makeLocalStorageMock();
  const doc = makeDocumentMock();
  const nav = makeNavigatorMock(opts.userAgent);
  const win = { speechSynthesis: ss, localStorage: ls, document: doc, navigator: nav };
  const ctx = vm.createContext({ window: win, speechSynthesis: ss, localStorage: ls,
    document: doc, navigator: nav, setTimeout, clearTimeout, setInterval, clearInterval,
    console: console });
  vm.runInContext(SOURCE, ctx);
  return { vp: ctx.window.VoicePicker, ss, doc, ls };
}

test('bootstrap: voices present on init → onVoiceListChanged fires once', async () => {
  const { vp } = loadWith({ voices: FIXTURES.macos10 });
  let calls = 0;
  vp.onVoiceListChanged(() => { calls++; });
  vp.init();
  await new Promise(r => setImmediate(r));
  assert.strictEqual(calls, 1);
});

test('bootstrap: empty voices → voiceschanged fires later → callback fires', async () => {
  const { vp, ss } = loadWith({ voices: [] });
  let calls = 0;
  vp.onVoiceListChanged(() => { calls++; });
  vp.init();
  await new Promise(r => setImmediate(r));
  assert.strictEqual(calls, 0, 'no callback yet on empty list');
  ss._setVoices(FIXTURES.macos10);
  await new Promise(r => setImmediate(r));
  assert.strictEqual(calls, 1);
});

test('bootstrap: idempotent — same list fires callback once (R1 F1.4)', async () => {
  const { vp, ss } = loadWith({ voices: [] });
  let calls = 0;
  vp.onVoiceListChanged(() => { calls++; });
  vp.init();
  ss._setVoices(FIXTURES.macos10);
  await new Promise(r => setImmediate(r));
  ss._setVoices(FIXTURES.macos10);
  await new Promise(r => setImmediate(r));
  assert.strictEqual(calls, 1, 'fingerprint dedup must prevent duplicate callbacks');
});

test('bootstrap: voice list changes → callback fires again', async () => {
  const { vp, ss } = loadWith({ voices: [] });
  let calls = 0;
  vp.onVoiceListChanged(() => { calls++; });
  vp.init();
  ss._setVoices(FIXTURES.macos10);
  await new Promise(r => setImmediate(r));
  ss._setVoices(FIXTURES.ios2);
  await new Promise(r => setImmediate(r));
  assert.strictEqual(calls, 2);
});

test('bootstrap: iOS UA + empty list → prime utterance fired', async () => {
  const { vp, ss } = loadWith({
    voices: [],
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
  });
  vp.init();
  vp._bootstrapPrime();
  assert.strictEqual(ss._speakCalls.length, 1, 'must fire a silent prime utterance');
  assert.strictEqual(ss._speakCalls[0].volume, 0, 'prime utterance must be volume 0');
});

test('bootstrap: non-iOS empty after timeout → stub state', async () => {
  const { vp, doc } = loadWith({
    voices: [],
    userAgent: 'Mozilla/5.0 (X11; Linux) Firefox/120.0',
  });
  let stubShown = false;
  doc._registerElement('pref-voice-stub', {
    classList: { add: () => {}, remove: (c) => { if (c === 'hidden') stubShown = true; }, contains: () => false, toggle: () => {} },
  });
  vp.init();
  vp._bootstrapTimeoutFired();
  assert.strictEqual(stubShown, true, 'stub element must be unhidden');
});
```

- [ ] **Step 2: Run — verify failure**

Run: `node --test frontend/tests/voice-picker/voiceschanged-bootstrap.test.mjs`

Expected: failures — `vp.init is not defined / undefined behavior`.

- [ ] **Step 3: Implement bootstrap in voice-picker.js**

Add module-private state near the top of the IIFE:

```js
  var voiceListFingerprint = '';
  var voiceListCallbacks = [];
  var bootstrapPrimedOnce = false;
  var bootstrapPollInterval = null;
  var bootstrapPollCount = 0;
  var BOOTSTRAP_POLL_MAX = 10;
  var BOOTSTRAP_POLL_MS = 500;
```

Add bootstrap functions below `getUtteranceVoice`:

```js
  function fingerprintVoices(list) {
    if (!list || !list.length) return '';
    return list.map(function (v) {
      return (v.voiceURI || '') + '|' + (v.name || '') + '|' + (v.lang || '');
    }).sort().join('\n');
  }

  function notifyVoiceListChanged() {
    var list;
    try { list = window.speechSynthesis.getVoices() || []; } catch (e) { list = []; }
    var fp = fingerprintVoices(list);
    if (fp === voiceListFingerprint) return;
    voiceListFingerprint = fp;
    voiceListCallbacks.forEach(function (cb) {
      try { cb(); } catch (e) { console.warn('[voice-picker] callback threw', e); }
    });
  }

  function isIOS() {
    try { return /iPad|iPhone|iPod/.test(window.navigator.userAgent); }
    catch (e) { return false; }
  }

  function bootstrapPrime() {
    if (bootstrapPrimedOnce) return;
    bootstrapPrimedOnce = true;
    try {
      var Utter = window.SpeechSynthesisUtterance || function (t) { this.text = t; };
      var u = new Utter(' ');
      u.volume = 0;
      window.speechSynthesis.speak(u);
    } catch (e) { /* autoplay policy may reject */ }
  }

  function bootstrapPollTick() {
    bootstrapPollCount++;
    notifyVoiceListChanged();
    if (voiceListFingerprint) {
      clearInterval(bootstrapPollInterval);
      bootstrapPollInterval = null;
      return;
    }
    if (bootstrapPollCount >= BOOTSTRAP_POLL_MAX) {
      clearInterval(bootstrapPollInterval);
      bootstrapPollInterval = null;
      if (isIOS()) {
        bootstrapPrime();
        bootstrapPollCount = 0;
        bootstrapPollInterval = setInterval(bootstrapPollTick, BOOTSTRAP_POLL_MS);
      } else {
        bootstrapTimeoutFired();
      }
    }
  }

  function bootstrapTimeoutFired() {
    var detecting = window.document && window.document.getElementById('pref-voice-detecting');
    var stub = window.document && window.document.getElementById('pref-voice-stub');
    var buttons = window.document && window.document.getElementById('pref-voice-buttons');
    if (detecting) detecting.classList.add('hidden');
    if (stub) stub.classList.remove('hidden');
    if (buttons) buttons.classList.add('hidden');
  }

  function initBootstrap() {
    notifyVoiceListChanged();
    try {
      window.speechSynthesis.addEventListener('voiceschanged', notifyVoiceListChanged);
    } catch (e) {}
    notifyVoiceListChanged();
    if (voiceListFingerprint) return;
    var detecting = window.document && window.document.getElementById('pref-voice-detecting');
    if (detecting) detecting.classList.remove('hidden');
    bootstrapPollCount = 0;
    bootstrapPollInterval = setInterval(bootstrapPollTick, BOOTSTRAP_POLL_MS);
  }
```

Update public API:

```js
    init: function () { initBootstrap(); },
    onVoiceListChanged: function (cb) {
      voiceListCallbacks.push(cb);
      if (voiceListFingerprint) { try { cb(); } catch (e) {} }
    },
    _bootstrapPrime: bootstrapPrime,
    _bootstrapTimeoutFired: bootstrapTimeoutFired,
```

- [ ] **Step 4: Run test — verify green**

Run: `node --test frontend/tests/voice-picker/voiceschanged-bootstrap.test.mjs`

Expected: `# pass 6`.

- [ ] **Step 5: Commit**

```bash
git add frontend/voice-picker.js frontend/tests/voice-picker/voiceschanged-bootstrap.test.mjs
git commit -m "$(cat <<'EOF'
feat(voice-picker): voiceschanged bootstrap (triple-check + poll + iOS prime)

MDN canonical pattern per spec §7.3. Closes R1 F1.4, R1 F1.5, R3 F3.1.
Idempotent handler: voice-list fingerprint prevents duplicate callbacks.
iOS detection via UA sniff triggers silent-prime utterance after poll
exhausts. Non-iOS empty-after-timeout transitions to stub state.

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3 — Preview lifecycle (the race-critical cluster)

### Task 3.1: preview-cleanup.test.mjs + generation counter

**Files:**
- Create: `frontend/tests/voice-picker/preview-cleanup.test.mjs`
- Modify: `frontend/voice-picker.js`

- [ ] **Step 1: Write the failing test**

```js
// frontend/tests/voice-picker/preview-cleanup.test.mjs
import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { makeSpeechSynthesisMock, makeLocalStorageMock, makeDocumentMock, makeNavigatorMock, FIXTURES } = require('./_fixtures.js');
const SOURCE = fs.readFileSync(path.join(__dirname, '../../voice-picker.js'), 'utf-8');

function load() {
  const ss = makeSpeechSynthesisMock({ voices: FIXTURES.macos10 });
  const ls = makeLocalStorageMock();
  const doc = makeDocumentMock();
  const nav = makeNavigatorMock('desktop');
  function Utter(text) { this.text = text; }
  const win = { speechSynthesis: ss, localStorage: ls, document: doc, navigator: nav,
    SpeechSynthesisUtterance: Utter };
  const ctx = vm.createContext({ window: win, speechSynthesis: ss, localStorage: ls,
    document: doc, navigator: nav, SpeechSynthesisUtterance: Utter,
    setTimeout, clearTimeout, setInterval, clearInterval, console });
  vm.runInContext(SOURCE, ctx);
  return { vp: ctx.window.VoicePicker, ss, doc };
}

test('preview: cancel fires onerror (not onend) — activePreview still clears via generation', async () => {
  const { vp, ss } = load();
  vp.init();
  vp._writePref({ mode: 'gender', gender: 'female' });
  vp._armPreview();
  vp._speakPreview();
  assert.ok(vp._activePreview(), 'preview should be active immediately after speak');
  ss.cancel();
  await new Promise(r => setImmediate(r));
  assert.strictEqual(vp._activePreview(), null);
});

test('preview: rapid click A then B — A.onerror does NOT null B', async () => {
  const { vp, ss } = load();
  vp.init();
  vp._writePref({ mode: 'gender', gender: 'female' });
  vp._armPreview();
  vp._speakPreview();
  const genA = vp._activePreview().gen;
  vp._speakPreview();
  const activeB = vp._activePreview();
  assert.ok(activeB);
  assert.notStrictEqual(activeB.gen, genA);
  await new Promise(r => setImmediate(r));
  assert.ok(vp._activePreview(), 'B must still be active after A.onerror drains');
  assert.strictEqual(vp._activePreview().gen, activeB.gen);
});

test('preview: nav-active → speakPreview is a no-op (R2 F2.6)', () => {
  const { vp, ss, doc } = load();
  vp.init();
  doc.body.classList.add('nav-active');
  vp._writePref({ mode: 'gender', gender: 'male' });
  vp._armPreview();
  vp._speakPreview();
  assert.strictEqual(ss._speakCalls.length, 0);
  assert.strictEqual(ss._cancelCalls, 0);
});

test('preview: sidebar-close with activePreview → cancel fires once', async () => {
  const { vp, ss, doc } = load();
  vp.init();
  vp._writePref({ mode: 'gender', gender: 'female' });
  vp._armPreview();
  vp._speakPreview();
  const cancelsBefore = ss._cancelCalls;
  doc.dispatchEvent({ type: 'geographica:sidebar', detail: { open: false } });
  await new Promise(r => setImmediate(r));
  assert.strictEqual(ss._cancelCalls, cancelsBefore + 1);
  assert.strictEqual(vp._activePreview(), null);
});

test('preview: sidebar-close with NO activePreview → cancel NOT called', () => {
  const { vp, ss, doc } = load();
  vp.init();
  const cancelsBefore = ss._cancelCalls;
  doc.dispatchEvent({ type: 'geographica:sidebar', detail: { open: false } });
  assert.strictEqual(ss._cancelCalls, cancelsBefore);
});
```

- [ ] **Step 2: Run — verify failure**

Run: `node --test frontend/tests/voice-picker/preview-cleanup.test.mjs`

Expected: failures from missing helpers.

- [ ] **Step 3: Implement preview lifecycle in voice-picker.js**

Add module-private state:

```js
  var previewGeneration = 0;
  var activePreview = null;
  var previewArmed = false;
  var idleResetTimer = null;
  var debounceTimer = null;
  var IDLE_RESET_MS = 30000;
  var DEBOUNCE_MS = 150;
```

Add preview functions:

```js
  function formatPreviewPhrase() {
    var imperial = true;
    try {
      var checked = window.document.querySelector('input[name="units"]:checked');
      if (checked && checked.value === 'metric') imperial = false;
    } catch (e) {}
    return imperial
      ? 'In 500 feet, turn right onto Main Street.'
      : 'In 150 meters, turn right onto Main Street.';
  }

  function speakPreview() {
    try {
      if (window.document.body && window.document.body.classList.contains('nav-active')) return;
    } catch (e) {}
    try { window.speechSynthesis.cancel(); } catch (e) {}
    var myGen = ++previewGeneration;
    var Utter = window.SpeechSynthesisUtterance;
    var utt = new Utter(formatPreviewPhrase());
    utt.rate = 1.0;
    var v = getUtteranceVoice();
    if (v) { utt.voice = v; utt.lang = v.lang || 'en-US'; }
    else   { utt.lang = 'en-US'; }
    utt.onend   = function () { if (myGen === previewGeneration) activePreview = null; };
    utt.onerror = function () { if (myGen === previewGeneration) activePreview = null; };
    activePreview = { utterance: utt, gen: myGen };
    try { window.speechSynthesis.speak(utt); } catch (e) { activePreview = null; }
  }

  function speakPreviewDebounced() {
    if (!previewArmed) return;
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () { debounceTimer = null; speakPreview(); }, DEBOUNCE_MS);
  }

  function armPreview() {
    previewArmed = true;
    if (idleResetTimer) clearTimeout(idleResetTimer);
    idleResetTimer = setTimeout(function () { previewArmed = false; idleResetTimer = null; }, IDLE_RESET_MS);
  }

  function onSidebarClose() {
    previewArmed = false;
    if (idleResetTimer) { clearTimeout(idleResetTimer); idleResetTimer = null; }
    if (activePreview !== null) {
      try { window.speechSynthesis.cancel(); } catch (e) {}
      activePreview = null;
    }
  }

  function onVisibilityHidden() {
    if (activePreview !== null) {
      try { window.speechSynthesis.cancel(); } catch (e) {}
      activePreview = null;
    }
  }
```

Extend public API:

```js
    _armPreview: armPreview,
    _speakPreview: speakPreview,
    _speakPreviewDebounced: speakPreviewDebounced,
    _activePreview: function () { return activePreview; },
    _onSidebarClose: onSidebarClose,
    _onVisibilityHidden: onVisibilityHidden,
```

Wire sidebar event listener via new `initEventListeners`:

```js
  function initEventListeners() {
    try {
      window.document.addEventListener('geographica:sidebar', function (e) {
        if (!e.detail || !e.detail.open) onSidebarClose();
      });
      window.document.addEventListener('visibilitychange', function () {
        if (window.document.hidden) onVisibilityHidden();
      });
    } catch (e) {}
  }
```

Extend `init`:

```js
    init: function () { initBootstrap(); initEventListeners(); },
```

- [ ] **Step 4: Run tests — all 5 pass**

Run: `node --test frontend/tests/voice-picker/preview-cleanup.test.mjs`

Expected: `# pass 5`.

- [ ] **Step 5: Commit**

```bash
git add frontend/voice-picker.js frontend/tests/voice-picker/preview-cleanup.test.mjs
git commit -m "$(cat <<'EOF'
feat(voice-picker): preview lifecycle with generation counter

Ports wake-lock.js acquireGeneration pattern. Closes driver-safety
class findings:
- R1 F1.1: cancelled utterance fires onerror per W3C, never onend
- R2 F2.1: cancel-then-speak clear race
- R2 F2.2: iOS Safari silent-cancel leak
- R2 F2.6: nav-active guard

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 3.2: preview-gate.test.mjs — previewArmed state machine + debounce

**Files:**
- Create: `frontend/tests/voice-picker/preview-gate.test.mjs`

- [ ] **Step 1: Write the failing tests**

```js
// frontend/tests/voice-picker/preview-gate.test.mjs
import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { makeSpeechSynthesisMock, makeLocalStorageMock, makeDocumentMock, makeNavigatorMock, FIXTURES } = require('./_fixtures.js');
const SOURCE = fs.readFileSync(path.join(__dirname, '../../voice-picker.js'), 'utf-8');

function load() {
  const ss = makeSpeechSynthesisMock({ voices: FIXTURES.macos10 });
  const ls = makeLocalStorageMock();
  const doc = makeDocumentMock();
  const nav = makeNavigatorMock('desktop');
  function Utter(text) { this.text = text; }
  const win = { speechSynthesis: ss, localStorage: ls, document: doc, navigator: nav, SpeechSynthesisUtterance: Utter };
  const ctx = vm.createContext({ window: win, speechSynthesis: ss, localStorage: ls,
    document: doc, navigator: nav, SpeechSynthesisUtterance: Utter,
    setTimeout, clearTimeout, setInterval, clearInterval, console });
  vm.runInContext(SOURCE, ctx);
  return { vp: ctx.window.VoicePicker, ss, doc };
}

test('gate: starts disarmed — page-load restore does not speak', () => {
  const { vp, ss } = load();
  vp.init();
  vp._writePref({ mode: 'gender', gender: 'female' });
  vp._speakPreviewDebounced();
  assert.strictEqual(ss._speakCalls.length, 0);
});

test('gate: arm → speak fires after debounce', async () => {
  const { vp, ss } = load();
  vp.init();
  vp._writePref({ mode: 'gender', gender: 'female' });
  vp._armPreview();
  vp._speakPreviewDebounced();
  await new Promise(r => setTimeout(r, 200));
  assert.strictEqual(ss._speakCalls.length, 1);
});

test('gate: 6 rapid clicks within debounce window → speak called <=1 time', async () => {
  const { vp, ss } = load();
  vp.init();
  vp._writePref({ mode: 'gender', gender: 'female' });
  vp._armPreview();
  for (let i = 0; i < 6; i++) vp._speakPreviewDebounced();
  await new Promise(r => setTimeout(r, 200));
  assert.ok(ss._speakCalls.length <= 1);
});

test('gate: sidebar-close disarms', () => {
  const { vp, doc } = load();
  vp.init();
  vp._armPreview();
  assert.strictEqual(vp._isArmed(), true);
  doc.dispatchEvent({ type: 'geographica:sidebar', detail: { open: false } });
  assert.strictEqual(vp._isArmed(), false);
});

test('gate: 30s idle resets previewArmed', () => {
  const { vp } = load();
  vp.init();
  vp._armPreview();
  vp._fireIdleTimer();
  assert.strictEqual(vp._isArmed(), false);
});
```

- [ ] **Step 2: Run — verify failure**

Run: `node --test frontend/tests/voice-picker/preview-gate.test.mjs`

Expected: failures — `_isArmed`, `_fireIdleTimer` undefined.

- [ ] **Step 3: Add test helpers**

Extend public API:

```js
    _isArmed: function () { return previewArmed; },
    _fireIdleTimer: function () {
      if (idleResetTimer) { clearTimeout(idleResetTimer); idleResetTimer = null; }
      previewArmed = false;
    },
```

- [ ] **Step 4: Run — verify green**

Run: `node --test frontend/tests/voice-picker/preview-gate.test.mjs`

Expected: `# pass 5`.

- [ ] **Step 5: Commit**

```bash
git add frontend/voice-picker.js frontend/tests/voice-picker/preview-gate.test.mjs
git commit -m "$(cat <<'EOF'
test(voice-picker): previewArmed state machine + rapid-click debounce

Closes R2 F2.11. Gate starts disarmed, arms on click, disarms on
sidebar-close or 30s idle.

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 3.3: cross-tab-sync.test.mjs + storage listener

**Files:**
- Create: `frontend/tests/voice-picker/cross-tab-sync.test.mjs`
- Modify: `frontend/voice-picker.js`

- [ ] **Step 1: Write the failing test**

```js
// frontend/tests/voice-picker/cross-tab-sync.test.mjs
import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { makeSpeechSynthesisMock, makeLocalStorageMock, makeDocumentMock, makeNavigatorMock, FIXTURES } = require('./_fixtures.js');
const SOURCE = fs.readFileSync(path.join(__dirname, '../../voice-picker.js'), 'utf-8');

test('cross-tab: foreign storage event triggers re-render', () => {
  const ss = makeSpeechSynthesisMock({ voices: FIXTURES.macos10 });
  const ls = makeLocalStorageMock();
  const doc = makeDocumentMock();
  const nav = makeNavigatorMock('desktop');
  let rerenderCalled = 0;
  const windowListeners = {};
  const win = {
    speechSynthesis: ss, localStorage: ls, document: doc, navigator: nav,
    SpeechSynthesisUtterance: function Utter(text) { this.text = text; },
    addEventListener: function (type, fn) { (windowListeners[type] = windowListeners[type] || []).push(fn); },
    removeEventListener: function (type, fn) {
      windowListeners[type] = (windowListeners[type] || []).filter(f => f !== fn);
    },
  };
  const ctx = vm.createContext({ window: win, speechSynthesis: ss, localStorage: ls,
    document: doc, navigator: nav, SpeechSynthesisUtterance: win.SpeechSynthesisUtterance,
    setTimeout, clearTimeout, setInterval, clearInterval, console });
  vm.runInContext(SOURCE, ctx);
  const vp = ctx.window.VoicePicker;
  vp._onStorageEventForTest = function () { rerenderCalled++; };
  vp.init();
  ls.setItem('nav-voice-pref', JSON.stringify({ mode: 'gender', gender: 'male', version: 1 }));
  const storageEvent = { key: 'nav-voice-pref', newValue: ls.getItem('nav-voice-pref') };
  (windowListeners.storage || []).forEach(fn => fn(storageEvent));
  assert.strictEqual(rerenderCalled, 1);
});
```

- [ ] **Step 2: Run — verify failure**

Run: `node --test frontend/tests/voice-picker/cross-tab-sync.test.mjs`

Expected: fails because storage listener not wired.

- [ ] **Step 3: Wire storage listener in voice-picker.js**

Inside `initEventListeners`:

```js
    try {
      window.addEventListener('storage', function (e) {
        if (!e || e.key !== LS_KEY) return;
        if (typeof window.VoicePicker._onStorageEventForTest === 'function') {
          window.VoicePicker._onStorageEventForTest(e);
        }
        rerenderPreferences();
      });
    } catch (e) {}
```

Add a stub `rerenderPreferences` function (Phase 5 implements it):

```js
  function rerenderPreferences() { /* implemented in Phase 5 */ }
```

- [ ] **Step 4: Run — verify green**

Run: `node --test frontend/tests/voice-picker/cross-tab-sync.test.mjs`

Expected: `# pass 1`.

- [ ] **Step 5: Commit**

```bash
git add frontend/voice-picker.js frontend/tests/voice-picker/cross-tab-sync.test.mjs
git commit -m "$(cat <<'EOF'
feat(voice-picker): cross-tab storage event listener

Closes R2 F2.9. Foreign-tab writes to nav-voice-pref trigger a
re-render pass. Key-filter is strict. rerenderPreferences is a
Phase 5 stub.

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Phase 3 review loop

- [ ] **Pause and review Phase 2+3:** three rounds on generation-counter correctness, MUST-FIX coverage (R1 F1.1/F1.4/F1.5, R2 F2.1/F2.2/F2.6/F2.11, R3 F3.1), and async-mock pitfall check.

---

## Phase 4 — DOM (markup + CSS + sidebar event)

### Task 4.1: Add Preferences section to index.html

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Locate the block to replace**

Search `frontend/index.html` for `<h3>Units</h3>`. Confirm the Units block ends at the Metric `<label>` and Coordinates block ends at the MGRS `<label>`.

- [ ] **Step 2: Replace with Preferences markup**

Replace the block with:

```html
      <h3>Preferences</h3>

      <div class="pref-group" id="pref-voice">
        <div class="pref-label">Nav voice</div>

        <div class="pref-voice-buttons" id="pref-voice-buttons">
          <button type="button" class="pref-voice-btn active" data-gender="default">Default</button>
          <button type="button" class="pref-voice-btn"        data-gender="male">Male</button>
          <button type="button" class="pref-voice-btn"        data-gender="female">Female</button>
        </div>

        <button type="button" class="pref-voice-advanced-toggle" id="pref-voice-advanced-toggle"
                aria-expanded="false" aria-controls="pref-voice-advanced">▾ Pick a specific voice…</button>

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
        <label class="radio-label">
          <input type="radio" name="units" value="imperial" checked> Imperial (ft, mi)
        </label>
        <label class="radio-label">
          <input type="radio" name="units" value="metric"> Metric (m, km)
        </label>
      </div>

      <div class="pref-group">
        <div class="pref-label">Coordinates</div>
        <label class="radio-label">
          <input type="radio" name="coordfmt" value="dd" checked> Decimal Degrees
        </label>
        <label class="radio-label">
          <input type="radio" name="coordfmt" value="dms"> Degrees/Minutes/Seconds
        </label>
        <label class="radio-label">
          <input type="radio" name="coordfmt" value="maidenhead"> Maidenhead Grid
        </label>
        <label class="radio-label">
          <input type="radio" name="coordfmt" value="mgrs"> MGRS
        </label>
      </div>
```

- [ ] **Step 3: Verify existing selector still works**

Run: `grep -c 'input\[name="units"\]' frontend/nav-ui.js frontend/app.js`

Expected: non-zero. No code change needed.

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html
git commit -m "$(cat <<'EOF'
feat(voice-picker): Preferences section in sidebar

Replaces standalone Units and Coordinates with a single Preferences
section containing Nav voice (new), Units (moved), Coordinates
(moved). Per spec §6.1 Q2.

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 4.2: Add CSS selectors + .sr-only global

**Files:**
- Modify: `frontend/style.css`

- [ ] **Step 1: Append CSS block at end of file**

```css
/* ==== Voice Picker / Preferences section ==== */

.pref-group {
  margin-bottom: 18px;
}

.pref-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--text-muted, #9aa0a6);
  margin: 8px 0 6px;
}

.pref-voice-buttons {
  display: flex;
  gap: 6px;
}

.pref-voice-btn {
  flex: 1;
  padding: 8px 4px;
  background: #2d3138;
  border: 1px solid #3a3f48;
  border-radius: 4px;
  color: #e8e8e8;
  font-size: 12px;
  cursor: pointer;
}

.pref-voice-btn:hover:not(:disabled) {
  background: #363b44;
}

.pref-voice-btn.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
  font-weight: 600;
}

.pref-voice-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.pref-voice-advanced-toggle {
  width: 100%;
  padding: 6px 0;
  background: transparent;
  border: none;
  color: var(--accent);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
  margin-top: 6px;
}

.pref-voice-advanced {
  margin-top: 8px;
}

.pref-voice-advanced select {
  width: 100%;
  padding: 6px;
  background: #2d3138;
  border: 1px solid #3a3f48;
  border-radius: 4px;
  color: #e8e8e8;
  font-size: 12px;
}

.pref-voice-hint,
.pref-voice-stub,
.pref-voice-detecting {
  display: block;
  font-size: 11px;
  font-style: italic;
  color: var(--text-muted, #9aa0a6);
  margin-top: 8px;
}

/* Screen-reader-only utility (previously undefined in codebase; closes R4 F4.3). */
.sr-only {
  position: absolute !important;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/style.css
git commit -m "$(cat <<'EOF'
feat(voice-picker): CSS for Preferences section + .sr-only global

Uses var(--accent) per codebase convention (R4 F4.8). Adds .sr-only
global utility (R4 F4.3).

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 4.3: Add voice-picker script tag

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: Locate wake-lock script tag**

Search `frontend/index.html` for `<script src="wake-lock.js`.

- [ ] **Step 2: Insert voice-picker tag immediately after**

```html
  <script src="wake-lock.js?v=20260420"></script>
  <script src="voice-picker.js?v=20260421"></script>
  <script src="navigation.js?v=20260420"></script>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "$(cat <<'EOF'
feat(voice-picker): load voice-picker.js script in index.html

Between wake-lock.js and navigation.js. ?v=20260421 cache-buster.
Plain script (no async, no defer).

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 4.4: Dispatch CustomEvent from app.js setSidebarOpen

**Files:**
- Modify: `frontend/app.js`

- [ ] **Step 1: Locate setSidebarOpen**

Search `frontend/app.js` for `function setSidebarOpen(open)`.

- [ ] **Step 2: Add dispatchEvent after the classList mutation**

Immediately after the last classList operation, before the function closes:

```js
      document.dispatchEvent(new CustomEvent('geographica:sidebar', {
        detail: { open: open }
      }));
```

- [ ] **Step 3: Verify no JS parse errors**

Run: `node --check frontend/app.js`

Expected: exits 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/app.js
git commit -m "$(cat <<'EOF'
feat(app): dispatch geographica:sidebar CustomEvent on open/close

Enables VoicePicker to observe sidebar open/close. Closes R2 F2.5
and R4 F4.4.

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 5 — Integration wiring

### Task 5.1: Wire nav-ui.js onVoice → VoicePicker.getUtteranceVoice

**Files:**
- Modify: `frontend/nav-ui.js`

- [ ] **Step 1: Locate onVoice function**

Search `frontend/nav-ui.js` for `new SpeechSynthesisUtterance(text)`.

- [ ] **Step 2: Insert voice resolution**

Between `utterance.lang = 'en-US';` and `speechSynthesis.speak(utterance);`:

```js
    var chosenVoice = window.VoicePicker && window.VoicePicker.getUtteranceVoice();
    if (chosenVoice) {
      utterance.voice = chosenVoice;
      utterance.lang = chosenVoice.lang || utterance.lang;
    }
```

- [ ] **Step 3: primeSpeech NOT changed**

Verify `primeSpeech` body does NOT reference `VoicePicker`. No edit required.

- [ ] **Step 4: Verify parse**

Run: `node --check frontend/nav-ui.js`

Expected: exits 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/nav-ui.js
git commit -m "$(cat <<'EOF'
feat(nav): integrate voice picker into nav-ui onVoice path

Surgical 5-line insertion. Null-guard preserves main behavior if
voice-picker.js fails to load. utterance.lang follows resolved voice
(closes R5 F5.4).

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 5.2: Call VoicePicker.init() from app.js

**Files:**
- Modify: `frontend/app.js`

- [ ] **Step 1: Locate DOMContentLoaded handler**

Search `frontend/app.js` for `DOMContentLoaded`.

- [ ] **Step 2: Add init call near other module inits**

```js
    if (window.VoicePicker && typeof window.VoicePicker.init === 'function') {
      window.VoicePicker.init();
    }
```

- [ ] **Step 3: Verify parse**

Run: `node --check frontend/app.js`

Expected: exits 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/app.js
git commit -m "$(cat <<'EOF'
feat(app): invoke VoicePicker.init from DOMContentLoaded handler

Null-guard + typeof check defends against load-order edge cases.

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 5.3: Implement DOM handlers in VoicePicker

**Files:**
- Modify: `frontend/voice-picker.js`

- [ ] **Step 1: Add rendering and event-wiring functions**

Add inside the IIFE, below the preview/event handlers:

```js
  function $(id) { try { return window.document.getElementById(id); } catch (e) { return null; } }

  function renderHint() {
    var hintEl = $('pref-voice-hint');
    if (!hintEl) return;
    var detectingEl = $('pref-voice-detecting');
    var stubEl = $('pref-voice-stub');
    if (detectingEl && !detectingEl.classList.contains('hidden')) { hintEl.classList.add('hidden'); return; }
    if (stubEl && !stubEl.classList.contains('hidden')) { hintEl.classList.add('hidden'); return; }
    var pref = readPref();
    var candidates = candidateVoices(pref.allowCloudVoices);
    if (pref.mode === 'unavailable' && pref.voice) {
      hintEl.textContent = 'Saved voice "' + pref.voice.name + '" is not installed on this device — using device default.';
      hintEl.classList.remove('hidden');
      return;
    }
    var effectiveGender = null;
    if (pref.mode === 'gender') effectiveGender = pref.gender;
    else if (pref.mode === 'specific' && pref.storedGenderHint) effectiveGender = pref.storedGenderHint;
    if (effectiveGender) {
      var match = candidates.find(function (v) { return inferGender(v.name) === effectiveGender; });
      if (!match) {
        var gLabel = effectiveGender === 'male' ? 'Male' : 'Female';
        hintEl.textContent = 'No ' + gLabel + ' voice detected on this device — using device default.';
        hintEl.classList.remove('hidden');
        return;
      }
    }
    if (isIOS() && candidates.length <= 3 && candidates.length > 0) {
      hintEl.textContent = 'Only a few voices detected. On iOS, add more via Settings → Accessibility → Spoken Content → Voices.';
      hintEl.classList.remove('hidden');
      return;
    }
    hintEl.classList.add('hidden');
  }

  function renderButtons() {
    var pref = readPref();
    var navActive = false;
    try { navActive = window.document.body.classList.contains('nav-active'); } catch (e) {}
    ['default', 'male', 'female'].forEach(function (g) {
      var btn = window.document && window.document.querySelector('.pref-voice-btn[data-gender="' + g + '"]');
      if (!btn) return;
      btn.disabled = navActive;
      if (navActive) btn.setAttribute('title', 'Voice can only be changed before or after navigation.');
      else btn.removeAttribute('title');
      var active = (pref.mode === 'default' && g === 'default') ||
                   (pref.mode === 'gender' && pref.gender === g);
      btn.classList.toggle('active', active);
    });
  }

  function renderDropdown() {
    var sel = $('pref-voice-select');
    if (!sel) return;
    var pref = readPref();
    var candidates = candidateVoices(pref.allowCloudVoices);
    while (sel.firstChild) sel.removeChild(sel.firstChild);
    candidates.forEach(function (v) {
      var opt = window.document.createElement('option');
      opt.value = v.voiceURI;
      opt.textContent = v.name + ' — ' + v.lang;
      if (pref.mode === 'specific' && pref.voice && pref.voice.voiceURI === v.voiceURI) {
        opt.selected = true;
      }
      sel.appendChild(opt);
    });
    var cb = $('pref-voice-allow-cloud');
    if (cb) cb.checked = !!pref.allowCloudVoices;
  }

  function rerenderPreferences() {
    renderButtons();
    renderDropdown();
    renderHint();
  }

  function onVoiceButtonClick(e) {
    var btn = e.currentTarget;
    var gender = btn.getAttribute('data-gender');
    if (btn.disabled) return;
    if (gender === 'default') writePref({ mode: 'default' });
    else writePref({ mode: 'gender', gender: gender });
    armPreview();
    rerenderPreferences();
    speakPreviewDebounced();
  }

  function onDropdownChange(e) {
    var sel = e.currentTarget;
    var candidates = candidateVoices(readPref().allowCloudVoices);
    var picked = candidates.find(function (v) { return v.voiceURI === sel.value; });
    if (!picked) return;
    writePref({
      mode: 'specific',
      voice: { voiceURI: picked.voiceURI, name: picked.name, lang: picked.lang },
    });
    armPreview();
    rerenderPreferences();
    speakPreviewDebounced();
  }

  function onCloudCheckboxChange(e) {
    writePref({ allowCloudVoices: e.currentTarget.checked });
    rerenderPreferences();
  }

  function onAdvancedToggleClick(e) {
    var toggle = e.currentTarget;
    var panel = $('pref-voice-advanced');
    if (!panel) return;
    var expanded = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', expanded ? 'false' : 'true');
    panel.classList.toggle('hidden', expanded);
  }

  function wireDOMHandlers() {
    try {
      var buttons = window.document.querySelectorAll('.pref-voice-btn');
      buttons.forEach(function (btn) { btn.addEventListener('click', onVoiceButtonClick); });
      var sel = $('pref-voice-select');
      if (sel) sel.addEventListener('change', onDropdownChange);
      var cb = $('pref-voice-allow-cloud');
      if (cb) cb.addEventListener('change', onCloudCheckboxChange);
      var toggle = $('pref-voice-advanced-toggle');
      if (toggle) toggle.addEventListener('click', onAdvancedToggleClick);
    } catch (e) {}
  }
```

Extend `init`:

```js
    init: function () {
      initBootstrap();
      initEventListeners();
      wireDOMHandlers();
      rerenderPreferences();
      voiceListCallbacks.push(rerenderPreferences);
    },
```

- [ ] **Step 2: Re-run full JS test suite**

Run: `node --test frontend/tests/voice-picker/`

Expected: all prior tests still pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/voice-picker.js
git commit -m "$(cat <<'EOF'
feat(voice-picker): DOM handlers for buttons, dropdown, advanced toggle

Wires button/dropdown/cloud-checkbox/advanced-toggle. rerenderPreferences
implements §8.1 hint priority chain: detecting/stub → unavailable →
no-gender-match → iOS-low-count.

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 5.4: nav-active class-change observer

**Files:**
- Modify: `frontend/voice-picker.js`

- [ ] **Step 1: Add MutationObserver**

Inside `initEventListeners`:

```js
    try {
      var mo = new window.MutationObserver(function () { renderButtons(); });
      mo.observe(window.document.body, { attributes: true, attributeFilter: ['class'] });
    } catch (e) {}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/voice-picker.js
git commit -m "$(cat <<'EOF'
feat(voice-picker): watch body.class for nav-active changes

MutationObserver ensures buttons transition to/from disabled state
as nav starts/stops.

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Phase 5 review loop

- [ ] **Pause and review Phase 4+5:** correctness of DOM wiring, Python structural test coverage (Phase 6), regression check (onVoice still works if voice-picker.js absent).

---

## Phase 6 — Python structural tests + CI verification

### Task 6.1: Create tests/test_frontend_voice_picker.py

**Files:**
- Create: `tests/test_frontend_voice_picker.py`

- [ ] **Step 1: Write all structural tests**

```python
"""Structural invariants for the voice-picker feature.

Pattern mirrors tests/test_wake_lock_static.py. Filename matches
.github/workflows/frontend-ci.yml path-filter glob test_frontend_*.py
(closes R3 F3.12).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _function_body(src: str, decl_pattern: str) -> str:
    match = re.search(decl_pattern, src)
    assert match, f"declaration not found: {decl_pattern}"
    start = match.end() - 1
    depth = 0
    end = start
    for i, ch in enumerate(src[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    return src[start : end + 1]


def test_voice_picker_js_exists_and_is_iife() -> None:
    src = read("frontend/voice-picker.js")
    head = src[:200]
    assert "(function () {" in head
    assert "'use strict'" in head
    assert "if (window.VoicePicker) return" in head


def test_voice_picker_js_exports_public_api() -> None:
    src = read("frontend/voice-picker.js")
    assert re.search(r"init\s*:\s*function", src)
    assert re.search(r"getUtteranceVoice\s*:", src)
    assert re.search(r"onVoiceListChanged\s*:\s*function", src)
    assert re.search(r"_inferGender\s*:", src)


def test_voice_picker_script_in_index_html() -> None:
    src = read("frontend/index.html")
    assert re.search(r'<script src="voice-picker\.js\?v=\d+">', src)
    wakelock_pos = src.index('src="wake-lock.js')
    vp_pos = src.index('src="voice-picker.js')
    nav_pos = src.index('src="navigation.js')
    assert wakelock_pos < vp_pos < nav_pos
    tag_match = re.search(r'<script[^>]*src="voice-picker\.js[^>]*>', src)
    assert tag_match
    assert " async" not in tag_match.group(0)


def test_preferences_section_markup_present() -> None:
    src = read("frontend/index.html")
    assert 'id="pref-voice"' in src
    for gender in ("default", "male", "female"):
        assert re.search(rf'class="pref-voice-btn[^"]*"\s+data-gender="{gender}"', src)
    for _id in (
        "pref-voice-advanced-toggle",
        "pref-voice-advanced",
        "pref-voice-select",
        "pref-voice-allow-cloud",
        "pref-voice-hint",
        "pref-voice-stub",
        "pref-voice-detecting",
    ):
        assert f'id="{_id}"' in src, f'element id="{_id}" missing'


def test_units_radios_exact_count() -> None:
    src = read("frontend/index.html")
    radios = re.findall(r'<input[^>]*type="radio"[^>]*name="units"[^>]*>', src)
    assert len(radios) == 2
    values = sorted(re.findall(r'name="units"[^>]*value="([^"]+)"', src))
    assert values == ["imperial", "metric"]


def test_coordfmt_radios_exact_count() -> None:
    src = read("frontend/index.html")
    radios = re.findall(r'<input[^>]*type="radio"[^>]*name="coordfmt"[^>]*>', src)
    assert len(radios) == 4
    values = set(re.findall(r'name="coordfmt"[^>]*value="([^"]+)"', src))
    assert values == {"dd", "dms", "maidenhead", "mgrs"}


def test_sr_only_class_defined_in_style_css() -> None:
    src = read("frontend/style.css")
    assert re.search(r"\.sr-only\s*\{", src)
    block_match = re.search(r"\.sr-only\s*\{([^}]+)\}", src)
    assert block_match
    block = block_match.group(1)
    assert "position: absolute" in block or "position:absolute" in block
    assert "clip:" in block or "clip :" in block


def test_app_js_dispatches_sidebar_event() -> None:
    src = read("frontend/app.js")
    body = _function_body(src, r"function\s+setSidebarOpen\s*\([^)]*\)\s*\{")
    assert "dispatchEvent" in body
    assert "geographica:sidebar" in body


def test_nav_ui_integrates_voice_picker() -> None:
    src = read("frontend/nav-ui.js")
    body = _function_body(src, r"function\s+onVoice\s*\([^)]*\)\s*\{")
    assert "VoicePicker" in body
    assert "getUtteranceVoice" in body
    assert "window.VoicePicker &&" in body
    speak_pos = body.find("speechSynthesis.speak(")
    cancel_pos = body.rfind("speechSynthesis.cancel()", 0, speak_pos)
    assert cancel_pos != -1, "speechSynthesis.cancel() must precede speak in onVoice"
    lines_between = body[cancel_pos:speak_pos].count("\n")
    assert lines_between <= 6


def test_prime_speech_not_modified() -> None:
    src = read("frontend/nav-ui.js")
    body = _function_body(src, r"function\s+primeSpeech\s*\([^)]*\)\s*\{")
    assert "volume" in body
    assert "SpeechSynthesisUtterance" in body
    assert "speak(" in body
    assert "VoicePicker" not in body
    assert "utterance.voice =" not in body
    assert "utterance.voice=" not in body


def test_no_shrek_references() -> None:
    for rel in ("frontend/voice-picker.js", "frontend/index.html", "frontend/style.css"):
        src = read(rel)
        assert "shrek" not in src.lower(), f'{rel}: "shrek" reference present'
```

- [ ] **Step 2: Run the tests**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_frontend_voice_picker.py -v`

Expected: `11 passed`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_frontend_voice_picker.py
git commit -m "$(cat <<'EOF'
test(voice-picker): Python structural tests

Mirrors tests/test_wake_lock_static.py. 11 tests. Filename matches
CI path-filter glob test_frontend_*.py — closes R3 F3.12.

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 6.2: Verify CI workflow triggers

**Files:**
- Read: `.github/workflows/frontend-ci.yml`

- [ ] **Step 1: Confirm path-filter matches**

Run: `grep -c 'tests/test_frontend_\*\.py' .github/workflows/frontend-ci.yml`

Expected: >= 2.

- [ ] **Step 2: Confirm frontend/** coverage**

Run: `grep -c "'frontend/\*\*'" .github/workflows/frontend-ci.yml`

Expected: >= 2.

- [ ] **Step 3: No commit needed if path filters match**

If both expectations hold, no edit is required. If either fails, STOP and ask the user before editing the workflow file.

---

## Phase 7 — Debug fixture override + CHANGELOG

### Task 7.1: Debug query-param fixture override

**Files:**
- Modify: `frontend/voice-picker.js`

- [ ] **Step 1: Add dev-mode fixture override**

Inside the IIFE near the top:

```js
  function isDevOrigin() {
    try {
      var h = window.location.hostname;
      return h === 'localhost' || h === '127.0.0.1' || /\.ts\.net$/.test(h);
    } catch (e) { return false; }
  }

  function maybeApplyDebugFixture() {
    if (!isDevOrigin()) return null;
    try {
      var p = new URLSearchParams(window.location.search);
      var fx = p.get('voice-picker-mock');
      if (!fx) return null;
      var FIXTURES = {
        empty: [],
        'low-ios': [
          { voiceURI: 'sam', name: 'Samantha', lang: 'en-US', localService: true },
          { voiceURI: 'dan', name: 'Daniel', lang: 'en-GB', localService: true },
        ],
        'no-male': [
          { voiceURI: 'sam', name: 'Samantha', lang: 'en-US', localService: true },
          { voiceURI: 'karen', name: 'Karen', lang: 'en-AU', localService: true },
        ],
        'no-female': [
          { voiceURI: 'alex', name: 'Alex', lang: 'en-US', localService: true },
          { voiceURI: 'fred', name: 'Fred', lang: 'en-US', localService: true },
        ],
        'unavailable-specific': 'UNAVAILABLE_STATE',
      };
      var data = FIXTURES[fx];
      if (data === undefined) return null;
      if (data === 'UNAVAILABLE_STATE') {
        writePref({
          mode: 'specific',
          voice: { voiceURI: 'synthetic-gone', name: 'Synthetic Gone Voice', lang: 'en-US' },
          storedGenderHint: 'female',
        });
        return null;
      }
      window.speechSynthesis.getVoices = function () { return data; };
      console.warn('[voice-picker] DEV MODE: getVoices() overridden with fixture "' + fx + '"');
      return data;
    } catch (e) { return null; }
  }
```

Call it once from `initBootstrap` as the first line:

```js
  function initBootstrap() {
    maybeApplyDebugFixture();
    notifyVoiceListChanged();
    // ... rest unchanged ...
  }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/voice-picker.js
git commit -m "$(cat <<'EOF'
feat(voice-picker): dev-only ?voice-picker-mock query param

Closes R3 F3.11. Gated on hostname: localhost / 127.0.0.1 / *.ts.net.
Fixtures: empty, low-ios, no-male, no-female, unavailable-specific.

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 7.2: CHANGELOG entry

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add entry under Unreleased**

Read `CHANGELOG.md`. Insert at the top of the ### Added sub-section (create if missing):

```markdown
- **Nav voice picker** — Preferences sidebar section with Default / Male / Female gender quick-pick and an advanced disclosure for picking a specific installed voice. Cloud voices are filtered out by default for offline-reliability; opt-in via a labeled checkbox. Per-device localStorage. Hard-refresh (Ctrl/Cmd-Shift-R) once after upgrade.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs(changelog): nav voice picker under Unreleased

User-facing: Preferences section with voice picker. Offline-first
defaults. Hard-refresh required once.

Agent: ocotillo
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Final integration review

- [ ] **Run the complete test suite:**

```bash
node --test frontend/tests/voice-picker/
python -m pytest tests/test_frontend_voice_picker.py -v
python -m pytest tests/test_wake_lock_static.py -v   # regression check
```

Expected: all green.

- [ ] **Verify git status is clean:**

```bash
git status
```

Expected: nothing to commit, working tree clean. Expected branch: `dev`.

- [ ] **Final review pass:** read every commit message in this session (`git log --oneline dev ^origin/dev` scoped to voice-picker commits) and confirm each carries `Agent: ocotillo`. Do NOT amend if one is missing — note it for the user.

- [ ] **Run the §10.3 manual acceptance checklist** from the spec. 14 items across desktop Chrome + iOS Safari + Android Chrome. Use debug query-param for synthetic cases.

If all pass → feature is ship-ready.
If any fail → file issues; stay on `dev` until triaged; do not merge to main.

---

## Self-review checklist (plan author)

1. **Spec coverage** — every section/goal maps to at least one task. ✓
2. **Placeholder scan** — no TBD, TODO, vague directives. Every code step has complete code. ✓
3. **Type consistency** — all `_` helper names used across tasks are defined once and referenced consistently. ✓
4. **Cross-task file conflicts** — same-file tasks sequenced within a phase; no parallel-subagent conflict surface. ✓
5. **Subagent moniker inheritance** — every commit example includes `Agent: ocotillo`; execution guardrails pin the subagent-prompt requirement. ✓
6. **TDD preamble and completion check** — applied per task. ✓
7. **Review loops** — three waypoints between Phases 1/2, 3/4, 5/6. ✓

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-21-nav-voice-picker-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks. Each subagent's prompt MUST include: *"You are agent ocotillo; use this in your commit trailers."* Required sub-skill: `superpowers:subagent-driven-development`.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`. Batch execution with checkpoints for review. Required sub-skill: `superpowers:executing-plans`.

Which approach?
