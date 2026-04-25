import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(path.join(__dirname, '../../ruler.js'), 'utf-8');

function loadRuler(opts = {}) {
  const win = {};
  const ctx = vm.createContext({
    window: win,
    document: opts.document || {},
    console,
  });
  vm.runInContext(SOURCE, ctx);
  return ctx.window._ruler;
}

test('ruler.js exposes window._ruler with init / isActive / clear', () => {
  const r = loadRuler();
  assert.ok(r, 'window._ruler must be defined');
  assert.strictEqual(typeof r.init, 'function');
  assert.strictEqual(typeof r.isActive, 'function');
  assert.strictEqual(typeof r.clear, 'function');
});

test('isActive returns false before init', () => {
  const r = loadRuler();
  assert.strictEqual(r.isActive(), false);
});

test('init is idempotent — second call is a no-op (does not throw)', () => {
  const r = loadRuler({ document: { getElementById: () => null, addEventListener: () => {} } });
  const fakeMap = { on: () => {}, getSource: () => null, addSource: () => {}, addLayer: () => {}, getLayer: () => null, getCanvas: () => ({ style: {}, addEventListener: () => {} }) };
  r.init(fakeMap);
  r.init(fakeMap);
  assert.ok(true);
});
