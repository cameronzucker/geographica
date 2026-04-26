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
  const ctx = vm.createContext({ window: win, localStorage: ls, console: console, JSON: JSON });
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
