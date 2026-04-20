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
