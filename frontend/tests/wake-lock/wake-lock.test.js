import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  makeDocumentMock,
  makeWakeLockNavigatorMock,
  makeSilentVideoLockMock,
} from './_fixtures.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(
  path.join(__dirname, '../../wake-lock.js'),
  'utf-8'
);

function loadModule(opts = {}) {
  const {
    hasWakeLock = true,
    wakeLockOpts = {},
    document: docParam,
    matchMedia,
  } = opts;
  // Respect an explicit `silentVideoLock: undefined` (to simulate absence)
  // rather than letting default-parameter semantics substitute a mock.
  const silentVideoLock = 'silentVideoLock' in opts
    ? opts.silentVideoLock
    : makeSilentVideoLockMock();
  const doc = docParam || makeDocumentMock();
  const win = {
    document: doc,
    console: { warn: () => {} },
    navigator: hasWakeLock ? { wakeLock: makeWakeLockNavigatorMock(wakeLockOpts) } : {},
    SilentVideoLock: silentVideoLock,
    matchMedia: matchMedia || (() => ({ matches: false })),
    WakeLock: undefined,
  };
  const ctx = vm.createContext({
    window: win,
    document: doc,
    navigator: win.navigator,
    console: win.console,
  });
  vm.runInContext(SOURCE, ctx);
  return { module: win.WakeLock, doc, win };
}

test('primary available — acquire() calls navigator.wakeLock.request and stores sentinel', async () => {
  const { module, win } = loadModule();
  await module.acquire();
  // Allow any microtasks to settle
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(win.navigator.wakeLock.request.mock.callCount(), 1);
  assert.strictEqual(module.status(), 'wakelock');
});

test('primary available — acquire() does NOT engage SilentVideoLock', async () => {
  const silentVideoLock = makeSilentVideoLockMock();
  const { module } = loadModule({ silentVideoLock });
  await module.acquire();
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(silentVideoLock.enable.mock.callCount(), 0);
});

test('acquire() is idempotent — calling twice issues only one request', async () => {
  const { module, win } = loadModule();
  await module.acquire();
  await new Promise((r) => setImmediate(r));
  await module.acquire();
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(win.navigator.wakeLock.request.mock.callCount(), 1);
});

test('status() returns "idle" initially', () => {
  const { module } = loadModule();
  assert.strictEqual(module.status(), 'idle');
});

test('primary unavailable — acquire() falls to SilentVideoLock', async () => {
  const silentVideoLock = makeSilentVideoLockMock();
  const { module } = loadModule({ hasWakeLock: false, silentVideoLock });
  await module.acquire();
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(silentVideoLock.enable.mock.callCount(), 1);
  assert.strictEqual(module.status(), 'fallback');
});

test('primary rejects — acquire() falls to SilentVideoLock', async () => {
  const silentVideoLock = makeSilentVideoLockMock();
  const err = new Error('NotAllowedError');
  const { module } = loadModule({
    wakeLockOpts: { rejectWith: err },
    silentVideoLock,
  });
  await module.acquire();
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(silentVideoLock.enable.mock.callCount(), 1);
  assert.strictEqual(module.status(), 'fallback');
});

test('SilentVideoLock missing — acquire() degrades silently with warning', async () => {
  const { module } = loadModule({
    hasWakeLock: false,
    silentVideoLock: undefined,
  });
  await module.acquire();
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(module.status(), 'none');
});

test('SilentVideoLock.enable() rejects — acquire() degrades silently', async () => {
  const silentVideoLock = makeSilentVideoLockMock({ rejectWith: new Error('autoplay blocked') });
  const { module } = loadModule({ hasWakeLock: false, silentVideoLock });
  await module.acquire();
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(module.status(), 'none');
});

test('release() calls sentinel.release() on primary path', async () => {
  // Use a custom sentinel factory so we can observe release calls cleanly
  let capturedSentinel = null;
  const navigator = {
    wakeLock: {
      request: (type) => {
        const s = {
          type,
          released: false,
          release: () => { s.released = true; return Promise.resolve(); },
          addEventListener: () => {},
          removeEventListener: () => {},
        };
        capturedSentinel = s;
        return Promise.resolve(s);
      },
    },
  };
  const doc = makeDocumentMock();
  const win = {
    document: doc,
    console: { warn: () => {} },
    navigator,
    SilentVideoLock: makeSilentVideoLockMock(),
    matchMedia: () => ({ matches: false }),
    WakeLock: undefined,
  };
  const ctx = vm.createContext({ window: win, document: doc, navigator, console: win.console });
  vm.runInContext(SOURCE, ctx);
  const module = win.WakeLock;

  await module.acquire();
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(capturedSentinel.released, false);
  await module.release();
  assert.strictEqual(capturedSentinel.released, true);
  assert.strictEqual(module.status(), 'idle');
});

test('release() disables SilentVideoLock on fallback path', async () => {
  const silentVideoLock = makeSilentVideoLockMock();
  const { module } = loadModule({ hasWakeLock: false, silentVideoLock });
  await module.acquire();
  await new Promise((r) => setImmediate(r));
  await module.release();
  assert.strictEqual(silentVideoLock.disable.mock.callCount(), 1);
  assert.strictEqual(module.status(), 'idle');
});

test('release() without prior acquire() is a no-op', async () => {
  const { module } = loadModule();
  await assert.doesNotReject(() => module.release());
  assert.strictEqual(module.status(), 'idle');
});

test('release() called twice is a no-op the second time', async () => {
  const silentVideoLock = makeSilentVideoLockMock();
  const { module } = loadModule({ hasWakeLock: false, silentVideoLock });
  await module.acquire();
  await new Promise((r) => setImmediate(r));
  await module.release();
  await module.release(); // second call
  assert.strictEqual(silentVideoLock.disable.mock.callCount(), 1); // still only 1
});

// Helper: a navigator.wakeLock that returns a Promise resolvable on command
function deferredNavigator() {
  const resolvers = [];
  const sentinels = [];
  return {
    navigator: {
      wakeLock: {
        request: (type) => {
          return new Promise((resolve) => {
            const s = {
              type,
              released: false,
              release: () => { s.released = true; return Promise.resolve(); },
              addEventListener: () => {},
              removeEventListener: () => {},
            };
            sentinels.push(s);
            resolvers.push(() => resolve(s));
          });
        },
      },
    },
    // Call index-th resolver to deliver a sentinel
    resolveAt: (i) => resolvers[i]?.(),
    sentinels,
  };
}

function loadModuleWithDeferred(deferred) {
  const doc = makeDocumentMock();
  const win = {
    document: doc,
    console: { warn: () => {} },
    navigator: deferred.navigator,
    SilentVideoLock: makeSilentVideoLockMock(),
    matchMedia: () => ({ matches: false }),
    WakeLock: undefined,
  };
  const ctx = vm.createContext({
    window: win,
    document: doc,
    navigator: deferred.navigator,
    console: win.console,
  });
  vm.runInContext(SOURCE, ctx);
  return { module: win.WakeLock, win, doc };
}

test('release during pending acquire releases the eventually-resolved sentinel', async () => {
  const deferred = deferredNavigator();
  const { module } = loadModuleWithDeferred(deferred);
  module.acquire(); // fire-and-forget (do not await)
  await module.release(); // runs synchronously before request resolves
  deferred.resolveAt(0); // now resolve the pending request
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(deferred.sentinels[0].released, true, 'pending-acquire sentinel must be released');
  assert.strictEqual(module.status(), 'idle');
});

test('rapid Start -> Stop -> Start -> resolves first pending, no orphan', async () => {
  const deferred = deferredNavigator();
  const { module } = loadModuleWithDeferred(deferred);

  module.acquire(); // P1 pending
  await module.release(); // bumps generation
  module.acquire(); // P2 pending

  // Resolve P1 first: stale generation, must be released
  deferred.resolveAt(0);
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(deferred.sentinels[0].released, true, 'P1 stale sentinel must be released');

  // Now resolve P2: current generation, must be stored
  deferred.resolveAt(1);
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(deferred.sentinels[1].released, false, 'P2 current sentinel must be held');
  assert.strictEqual(module.status(), 'wakelock');

  // Clean up
  await module.release();
  assert.strictEqual(deferred.sentinels[1].released, true);
});

test('stale release event does not null current sentinel', async () => {
  // This test exercises the "if (wakeLockSentinel === sentinel)" guard in the release-listener
  const listeners = [];
  const sentinels = [];
  const navigator = {
    wakeLock: {
      request: (type) => {
        const s = {
          type,
          released: false,
          release: () => { s.released = true; return Promise.resolve(); },
          addEventListener: (name, cb) => {
            if (name === 'release') listeners.push({ sentinel: s, cb });
          },
          removeEventListener: () => {},
        };
        sentinels.push(s);
        return Promise.resolve(s);
      },
    },
  };
  const doc = makeDocumentMock();
  const win = {
    document: doc,
    console: { warn: () => {} },
    navigator,
    SilentVideoLock: makeSilentVideoLockMock(),
    matchMedia: () => ({ matches: false }),
    WakeLock: undefined,
  };
  const ctx = vm.createContext({ window: win, document: doc, navigator, console: win.console });
  vm.runInContext(SOURCE, ctx);
  const module = win.WakeLock;

  await module.acquire();
  await new Promise((r) => setImmediate(r));
  await module.release(); // sentinels[0] now released, wakeLockSentinel is null

  await module.acquire();
  await new Promise((r) => setImmediate(r));
  // sentinels[1] is now the current wakeLockSentinel

  // Fire a stale release event on sentinels[0] (from the first acquire)
  listeners[0].cb(); // should NOT null the current sentinel

  assert.strictEqual(module.status(), 'wakelock', 'current sentinel must remain held');
});
