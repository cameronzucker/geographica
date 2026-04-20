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
