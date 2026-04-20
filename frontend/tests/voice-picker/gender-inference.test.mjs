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
