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
