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
