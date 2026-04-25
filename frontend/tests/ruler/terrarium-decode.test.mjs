import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(path.join(__dirname, '../../ruler.js'), 'utf-8');

function loadRuler() {
  const win = {};
  const ctx = vm.createContext({ window: win, document: {}, console });
  vm.runInContext(SOURCE, ctx);
  return ctx.window._ruler._test;
}

// Encoder helper for clean test inputs
function encodeTerrarium(meters) {
  // Mapzen terrarium: meters = (r*256 + g + b/256) - 32768
  // So the 16.8-bit unsigned int is (meters + 32768) * 256.
  var raw = Math.round((meters + 32768) * 256);
  var r = (raw >> 16) & 0xff;
  var g = (raw >> 8) & 0xff;
  var b = raw & 0xff;
  return [r, g, b];
}

test('elevationFromRGB: sea level (~0m) decodes near 0', () => {
  const t = loadRuler();
  const [r, g, b] = encodeTerrarium(0);
  const e = t.elevationFromRGB(r, g, b, 255);
  assert.ok(Math.abs(e - 0) < 0.01, `expected ~0m, got ${e}`);
});

test('elevationFromRGB: Mt Whitney (~4421m)', () => {
  const t = loadRuler();
  const [r, g, b] = encodeTerrarium(4421);
  const e = t.elevationFromRGB(r, g, b, 255);
  assert.ok(Math.abs(e - 4421) < 0.01, `expected ~4421m, got ${e}`);
});

test('elevationFromRGB: Death Valley (~-86m)', () => {
  const t = loadRuler();
  const [r, g, b] = encodeTerrarium(-86);
  const e = t.elevationFromRGB(r, g, b, 255);
  assert.ok(Math.abs(e - (-86)) < 0.01, `expected ~-86m, got ${e}`);
});

test('elevationFromRGB: alpha-zero pixel returns null', () => {
  const t = loadRuler();
  const [r, g, b] = encodeTerrarium(1000);
  const e = t.elevationFromRGB(r, g, b, 0);
  assert.strictEqual(e, null);
});

test('elevationFromRGB: (0,0,0,255) sentinel returns null (out of range)', () => {
  const t = loadRuler();
  // Raw decode: -32768m, way below -500m guard
  const e = t.elevationFromRGB(0, 0, 0, 255);
  assert.strictEqual(e, null);
});

test('elevationFromRGB: > 9000m returns null (out of plausible range)', () => {
  const t = loadRuler();
  const [r, g, b] = encodeTerrarium(10000);
  const e = t.elevationFromRGB(r, g, b, 255);
  assert.strictEqual(e, null);
});

test('elevationFromRGB: < -500m returns null', () => {
  const t = loadRuler();
  const [r, g, b] = encodeTerrarium(-1000);
  const e = t.elevationFromRGB(r, g, b, 255);
  assert.strictEqual(e, null);
});

test('elevationFromRGB: -500m at boundary is allowed (strict <, returns -500)', () => {
  // Spec says < -500 → null. -500 exactly is allowed.
  const t = loadRuler();
  const [r, g, b] = encodeTerrarium(-500);
  const e = t.elevationFromRGB(r, g, b, 255);
  assert.ok(Math.abs(e - (-500)) < 0.01, `expected -500m, got ${e}`);
});

test('elevationFromRGB: 9000m at boundary returns 9000 (strict >)', () => {
  const t = loadRuler();
  const [r, g, b] = encodeTerrarium(9000);
  const e = t.elevationFromRGB(r, g, b, 255);
  assert.ok(Math.abs(e - 9000) < 0.01, `expected 9000m, got ${e}`);
});
