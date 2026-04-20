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
