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

test('cross-tab: foreign storage event triggers re-render', () => {
  const ss = makeSpeechSynthesisMock({ voices: FIXTURES.macos10 });
  const ls = makeLocalStorageMock();
  const doc = makeDocumentMock();
  const nav = makeNavigatorMock('desktop');
  let rerenderCalled = 0;
  const windowListeners = {};
  const win = {
    speechSynthesis: ss, localStorage: ls, document: doc, navigator: nav,
    SpeechSynthesisUtterance: function Utter(text) { this.text = text; },
    addEventListener: function (type, fn) { (windowListeners[type] = windowListeners[type] || []).push(fn); },
    removeEventListener: function (type, fn) {
      windowListeners[type] = (windowListeners[type] || []).filter(f => f !== fn);
    },
  };
  const ctx = vm.createContext({ window: win, speechSynthesis: ss, localStorage: ls,
    document: doc, navigator: nav, SpeechSynthesisUtterance: win.SpeechSynthesisUtterance,
    setTimeout, clearTimeout, setInterval, clearInterval, console });
  vm.runInContext(SOURCE, ctx);
  const vp = ctx.window.VoicePicker;
  vp._onStorageEventForTest = function () { rerenderCalled++; };
  vp.init();
  ls.setItem('nav-voice-pref', JSON.stringify({ mode: 'gender', gender: 'male', version: 1 }));
  const storageEvent = { key: 'nav-voice-pref', newValue: ls.getItem('nav-voice-pref') };
  (windowListeners.storage || []).forEach(fn => fn(storageEvent));
  assert.strictEqual(rerenderCalled, 1);
});
