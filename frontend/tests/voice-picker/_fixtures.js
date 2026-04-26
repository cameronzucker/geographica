// frontend/tests/voice-picker/_fixtures.js
// Shared mocks for voice-picker unit tests. Pattern mirrors frontend/tests/wake-lock/_fixtures.js.

// speechSynthesis mock with ASYNC event delivery (R2 F2.12).
// onstart/onend/onerror fire via queueMicrotask, not synchronously.
function makeSpeechSynthesisMock(opts) {
  opts = opts || {};
  var queue = [];
  var speaking = false;
  var listeners = {};  // { voiceschanged: [fn, ...] }
  var cancelFiresEnd = opts.cancelFiresEnd === true;  // default false (W3C-correct)

  var api = {
    _voices: opts.voices || [],
    _speakCalls: [],
    _cancelCalls: 0,

    getVoices: function () { return api._voices.slice(); },

    speak: function (utt) {
      api._speakCalls.push(utt);
      queue.push(utt);
      speaking = true;
      queueMicrotask(function () {
        if (typeof utt.onstart === 'function') utt.onstart({});
      });
      queueMicrotask(function () {
        if (queue.indexOf(utt) === -1) return;  // cancelled
        queue = queue.filter(function (q) { return q !== utt; });
        if (queue.length === 0) speaking = false;
        if (typeof utt.onend === 'function') utt.onend({});
      });
    },

    cancel: function () {
      api._cancelCalls++;
      var wasQueue = queue.slice();
      queue = [];
      speaking = false;
      // W3C: cancelled utterance fires error, NOT end (R1 F1.1).
      wasQueue.forEach(function (utt) {
        queueMicrotask(function () {
          if (cancelFiresEnd) {
            if (typeof utt.onend === 'function') utt.onend({});
          } else {
            if (typeof utt.onerror === 'function') utt.onerror({ error: 'interrupted' });
          }
        });
      });
    },

    addEventListener: function (type, fn) {
      (listeners[type] = listeners[type] || []).push(fn);
    },
    removeEventListener: function (type, fn) {
      listeners[type] = (listeners[type] || []).filter(function (f) { return f !== fn; });
    },
    _fire: function (type) {
      (listeners[type] || []).forEach(function (fn) { fn({}); });
    },
    _setVoices: function (voices) {
      api._voices = voices;
      api._fire('voiceschanged');
    },
    get speaking() { return speaking; },
    get pending() { return queue.length > 0; },
  };
  return api;
}

// localStorage mock.
function makeLocalStorageMock() {
  var store = {};
  return {
    getItem: function (k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
    setItem: function (k, v) { store[k] = String(v); },
    removeItem: function (k) { delete store[k]; },
    clear: function () { store = {}; },
    get _raw() { return store; },
  };
}

// Minimal document mock with event dispatch + classList on body.
function makeDocumentMock() {
  var listeners = {};
  var body = {
    _classes: new Set(),
    classList: {
      add: function (c) { body._classes.add(c); },
      remove: function (c) { body._classes.delete(c); },
      contains: function (c) { return body._classes.has(c); },
      toggle: function (c) { body._classes.has(c) ? body._classes.delete(c) : body._classes.add(c); },
    },
    className: '',
  };
  Object.defineProperty(body, 'className', {
    get: function () { return Array.from(body._classes).join(' '); },
    set: function (v) {
      body._classes.clear();
      String(v).split(/\s+/).filter(Boolean).forEach(function (c) { body._classes.add(c); });
    },
  });

  var elements = {};  // id → minimal element mock

  return {
    body: body,
    addEventListener: function (type, fn) {
      (listeners[type] = listeners[type] || []).push(fn);
    },
    removeEventListener: function (type, fn) {
      listeners[type] = (listeners[type] || []).filter(function (f) { return f !== fn; });
    },
    dispatchEvent: function (ev) {
      (listeners[ev.type] || []).forEach(function (fn) { fn(ev); });
      return true;
    },
    getElementById: function (id) { return elements[id] || null; },
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; },
    createElement: function (tag) {
      return {
        tagName: String(tag || '').toUpperCase(),
        value: '',
        textContent: '',
        selected: false,
        appendChild: function () {},
      };
    },
    _registerElement: function (id, el) { elements[id] = el; },
    _listeners: listeners,
  };
}

// navigator mock with configurable UA (for iOS detection tests).
function makeNavigatorMock(userAgent) {
  return { userAgent: userAgent || 'Mozilla/5.0 (node test)' };
}

// Voice-list fixtures. Each voice is a plain object matching SpeechSynthesisVoice shape.
var FIXTURES = {
  macos10: [
    { voiceURI: 'com.apple.ttsbundle.Samantha-compact', name: 'Samantha', lang: 'en-US', localService: true, default: true },
    { voiceURI: 'com.apple.speech.synthesis.voice.alex', name: 'Alex', lang: 'en-US', localService: true, default: false },
    { voiceURI: 'com.apple.ttsbundle.Daniel-compact', name: 'Daniel', lang: 'en-GB', localService: true, default: false },
    { voiceURI: 'com.apple.speech.synthesis.voice.karen', name: 'Karen', lang: 'en-AU', localService: true, default: false },
    { voiceURI: 'com.apple.ttsbundle.Moira-compact', name: 'Moira', lang: 'en-IE', localService: true, default: false },
    { voiceURI: 'com.apple.ttsbundle.Tom-compact', name: 'Tom', lang: 'en-US', localService: true, default: false },
    { voiceURI: 'com.apple.ttsbundle.Victoria-compact', name: 'Victoria', lang: 'en-US', localService: true, default: false },
    { voiceURI: 'com.apple.ttsbundle.Fred-compact', name: 'Fred', lang: 'en-US', localService: true, default: false },
    { voiceURI: 'com.apple.ttsbundle.Samantha-enhanced', name: 'Samantha (Enhanced)', lang: 'en-US', localService: true, default: false },
    { voiceURI: 'Google US English', name: 'Google US English', lang: 'en-US', localService: false, default: false },
  ],
  ios2: [
    { voiceURI: 'com.apple.ttsbundle.Samantha-compact', name: 'Samantha', lang: 'en-US', localService: true, default: true },
    { voiceURI: 'com.apple.ttsbundle.Daniel-compact', name: 'Daniel', lang: 'en-GB', localService: true, default: false },
  ],
  windowsEdge6: [
    { voiceURI: 'Microsoft Zira Desktop', name: 'Microsoft Zira - English (United States)', lang: 'en-US', localService: true, default: true },
    { voiceURI: 'Microsoft David Desktop', name: 'Microsoft David - English (United States)', lang: 'en-US', localService: true, default: false },
    { voiceURI: 'Microsoft Mark Mobile', name: 'Microsoft Mark - English (United States)', lang: 'en-US', localService: true, default: false },
    { voiceURI: 'Microsoft Hazel Desktop', name: 'Microsoft Hazel - English (Great Britain)', lang: 'en-GB', localService: true, default: false },
    { voiceURI: 'Microsoft George Mobile', name: 'Microsoft George - English (Great Britain)', lang: 'en-GB', localService: true, default: false },
    { voiceURI: 'Microsoft Susan Desktop', name: 'Microsoft Susan - English (Great Britain)', lang: 'en-GB', localService: true, default: false },
  ],
  linuxFirefox3: [
    { voiceURI: 'urn:moz-tts:speechd:english', name: 'english', lang: 'en', localService: true, default: true },
    { voiceURI: 'urn:moz-tts:speechd:english-us', name: 'english-us', lang: 'en-US', localService: true, default: false },
    { voiceURI: 'urn:moz-tts:speechd:english-rp', name: 'english-rp', lang: 'en-GB', localService: true, default: false },
  ],
  empty: [],
  degenerate: [
    { voiceURI: 'weird-1', name: '', lang: 'en-US', localService: true },
    { voiceURI: 'weird-2', name: undefined, lang: 'en-US', localService: true },
    { voiceURI: 'com.apple.samantha', name: 'Samantha', lang: 'en-US', localService: true, default: true },
    { voiceURI: 'com.apple.daniel', name: 'Daniel', lang: 'en-GB', localService: true, default: true },
    { voiceURI: 'weird-3', name: '日本語', lang: 'en-US', localService: true },
  ],
};

module.exports = {
  makeSpeechSynthesisMock: makeSpeechSynthesisMock,
  makeLocalStorageMock: makeLocalStorageMock,
  makeDocumentMock: makeDocumentMock,
  makeNavigatorMock: makeNavigatorMock,
  FIXTURES: FIXTURES,
};
