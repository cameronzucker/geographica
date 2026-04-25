import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(path.join(__dirname, '../../ruler.js'), 'utf-8');

function loadRuler(useImperial) {
  const win = { _geographicaUseImperial: useImperial };
  const ctx = vm.createContext({ window: win, document: {}, console });
  vm.runInContext(SOURCE, ctx);
  return { t: ctx.window._ruler._test, win };
}

test('formatRulerDistance: imperial < 1 mile shows feet', () => {
  const { t } = loadRuler(true);
  assert.strictEqual(t.formatRulerDistance(100), '328 ft');
  assert.strictEqual(t.formatRulerDistance(500), '1640 ft');
});

test('formatRulerDistance: imperial >= 1 mile shows miles to 2 decimals', () => {
  const { t } = loadRuler(true);
  assert.strictEqual(t.formatRulerDistance(1609.34), '1.00 mi');
  assert.strictEqual(t.formatRulerDistance(8046.7), '5.00 mi');
});

test('formatRulerDistance: metric < 1 km shows meters', () => {
  const { t } = loadRuler(false);
  assert.strictEqual(t.formatRulerDistance(500), '500 m');
});

test('formatRulerDistance: metric >= 1 km shows km to 2 decimals', () => {
  const { t } = loadRuler(false);
  assert.strictEqual(t.formatRulerDistance(1000), '1.00 km');
  assert.strictEqual(t.formatRulerDistance(12345), '12.35 km');
});

test('formatRulerDistance: live read — toggle propagates', () => {
  const { t, win } = loadRuler(true);
  assert.strictEqual(t.formatRulerDistance(1609.34), '1.00 mi');
  win._geographicaUseImperial = false;
  assert.strictEqual(t.formatRulerDistance(1609.34), '1.61 km');
});
