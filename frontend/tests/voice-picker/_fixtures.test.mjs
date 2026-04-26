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
