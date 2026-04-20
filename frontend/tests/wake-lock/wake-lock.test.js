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
