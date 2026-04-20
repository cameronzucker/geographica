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
