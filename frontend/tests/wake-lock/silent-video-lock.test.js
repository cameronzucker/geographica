import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { makeDocumentMock } from './_fixtures.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(
  path.join(__dirname, '../../silent-video-lock.js'),
  'utf-8'
);

function loadModule({ document } = {}) {
  const doc = document || makeDocumentMock();
  const win = { document: doc, console: { warn: () => {} }, SilentVideoLock: undefined };
  const ctx = vm.createContext({ window: win, document: doc, console: win.console });
  vm.runInContext(SOURCE, ctx);
  // The IIFE assigns to window.SilentVideoLock
  return { module: win.SilentVideoLock, doc, win };
}

test('enable() creates a <video>, appends to body, calls play()', async () => {
  const { module, doc } = loadModule();
  await module.enable();
  assert.strictEqual(doc._videoElements.length, 1);
  const v = doc._videoElements[0];
  assert.strictEqual(v.tagName, 'VIDEO');
  assert.strictEqual(v.play.mock.callCount(), 1);
});

test('enable() is idempotent — second call does not create a second video', async () => {
  const { module, doc } = loadModule();
  await module.enable();
  await module.enable();
  assert.strictEqual(doc._videoElements.length, 1);
});

test('disable() pauses the video, removes it from DOM, and clears internal state', async () => {
  const { module, doc } = loadModule();
  await module.enable();
  const v = doc._videoElements[0];
  module.disable();
  assert.strictEqual(v.pause.mock.callCount(), 1);
  assert.strictEqual(v.remove.mock.callCount(), 1);
});

test('disable() before enable() is a no-op (no throw)', () => {
  const { module } = loadModule();
  assert.doesNotThrow(() => module.disable());
});

test('isActive() returns false before enable(), true after, false after disable()', async () => {
  const { module } = loadModule();
  assert.strictEqual(module.isActive(), false);
  await module.enable();
  assert.strictEqual(module.isActive(), true);
  module.disable();
  assert.strictEqual(module.isActive(), false);
});
