import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(path.join(__dirname, '../../ruler.js'), 'utf-8');

test('ruler.js exposes window._ruler with init / isActive / clear', () => {
  const win = {};
  const ctx = vm.createContext({ window: win, document: {}, console });
  vm.runInContext(SOURCE, ctx);
  assert.ok(ctx.window._ruler, 'window._ruler must be defined');
  assert.strictEqual(typeof ctx.window._ruler.init, 'function');
  assert.strictEqual(typeof ctx.window._ruler.isActive, 'function');
  assert.strictEqual(typeof ctx.window._ruler.clear, 'function');
});

test('isActive returns false before init', () => {
  const win = {};
  const ctx = vm.createContext({ window: win, document: {}, console });
  vm.runInContext(SOURCE, ctx);
  assert.strictEqual(ctx.window._ruler.isActive(), false);
});

test('init is idempotent — second call is a no-op (does not throw)', () => {
  const win = {};
  const ctx = vm.createContext({ window: win, document: { getElementById: () => null, addEventListener: () => {} }, console });
  vm.runInContext(SOURCE, ctx);
  const fakeMap = { on: () => {}, getSource: () => null, addSource: () => {}, addLayer: () => {}, getLayer: () => null, getCanvas: () => ({ style: {}, addEventListener: () => {} }) };
  ctx.window._ruler.init(fakeMap);
  ctx.window._ruler.init(fakeMap);  // must not throw
  assert.ok(true);
});
