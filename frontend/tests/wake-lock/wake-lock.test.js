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

function loadModule({
  hasWakeLock = true,
  wakeLockOpts = {},
  silentVideoLock = makeSilentVideoLockMock(),
  document: docParam,
  matchMedia,
} = {}) {
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
