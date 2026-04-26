import { mock } from 'node:test';

export function makeSentinelMock() {
  const listeners = Object.create(null);
  const sentinel = {
    type: 'screen',
    released: false,
    release: mock.fn(() => {
      sentinel.released = true;
      (listeners.release || []).forEach(cb => cb());
      return Promise.resolve();
    }),
    addEventListener: (name, cb) => {
      (listeners[name] = listeners[name] || []).push(cb);
    },
    removeEventListener: () => {},
    _fire: (name) => { (listeners[name] || []).forEach(cb => cb()); },
    _listeners: listeners,
  };
  return sentinel;
}

export function makeWakeLockNavigatorMock({ rejectWith, sentinelFactory } = {}) {
  const factory = sentinelFactory || makeSentinelMock;
  return {
    request: mock.fn((type) => {
      if (rejectWith) return Promise.reject(rejectWith);
      return Promise.resolve(factory());
    }),
  };
}

export function makeSilentVideoLockMock({ rejectWith } = {}) {
  const m = {
    _active: false,
    enable: mock.fn(() => {
      if (rejectWith) return Promise.reject(rejectWith);
      m._active = true;
      return Promise.resolve();
    }),
    disable: mock.fn(() => { m._active = false; }),
    isActive: mock.fn(() => m._active),
  };
  return m;
}

export function makeDocumentMock() {
  const listeners = Object.create(null);
  const videoElements = [];
  const doc = {
    visibilityState: 'visible',
    hidden: false,
    addEventListener: (name, cb) => {
      (listeners[name] = listeners[name] || []).push(cb);
    },
    removeEventListener: () => {},
    body: {
      appendChild: mock.fn((el) => { videoElements.push(el); }),
      classList: { add: mock.fn(), remove: mock.fn() },
    },
    createElement: mock.fn((tag) => {
      const el = {
        tagName: tag.toUpperCase(),
        _attrs: Object.create(null),
        muted: false,
        playsInline: false,
        loop: false,
        disablePictureInPicture: false,
        disableRemotePlayback: false,
        paused: false,
        style: { cssText: '' },
        src: '',
        setAttribute: mock.fn(function (name, value) { this._attrs[name] = value; }),
        getAttribute: function (name) { return this._attrs[name]; },
        play: mock.fn(() => Promise.resolve()),
        pause: mock.fn(function () { this.paused = true; }),
        remove: mock.fn(),
      };
      return el;
    }),
    _fire: (name) => { (listeners[name] || []).forEach(cb => cb()); },
    _videoElements: videoElements,
    _listeners: listeners,
  };
  return doc;
}

export function makeWindowMock({ wakeLock = null, silentVideoLock = null, matchMedia = null } = {}) {
  const navigator = wakeLock ? { wakeLock } : {};
  return {
    navigator,
    SilentVideoLock: silentVideoLock,
    WakeLock: undefined, // populated by module load
    matchMedia: matchMedia || mock.fn(() => ({ matches: false })),
    console: { warn: mock.fn(), error: mock.fn() },
  };
}
