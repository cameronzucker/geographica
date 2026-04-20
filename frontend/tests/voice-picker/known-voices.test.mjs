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
