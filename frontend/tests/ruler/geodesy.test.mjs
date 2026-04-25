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

test('bearingDeg: due north is ~0°', () => {
  const t = loadRuler();
  // From [0, 0] to [0, 1] (1° due north)
  const b = t.bearingDeg([0, 0], [0, 1]);
  assert.ok(Math.abs(b - 0) < 0.01, `expected ~0°, got ${b}`);
});

test('bearingDeg: due east is ~90°', () => {
  const t = loadRuler();
  // From [0, 0] to [1, 0]
  const b = t.bearingDeg([0, 0], [1, 0]);
  assert.ok(Math.abs(b - 90) < 0.01, `expected ~90°, got ${b}`);
});

test('bearingDeg: due south is ~180°', () => {
  const t = loadRuler();
  const b = t.bearingDeg([0, 0], [0, -1]);
  assert.ok(Math.abs(b - 180) < 0.01, `expected ~180°, got ${b}`);
});

test('bearingDeg: due west is ~270°', () => {
  const t = loadRuler();
  const b = t.bearingDeg([0, 0], [-1, 0]);
  assert.ok(Math.abs(b - 270) < 0.01, `expected ~270°, got ${b}`);
});

test('bearingDeg: result always in [0, 360)', () => {
  const t = loadRuler();
  // Random angles
  const samples = [
    [[10, 20], [30, 40]], [[-100, 33], [-110, 35]],
    [[0, 0], [-1, -1]], [[112, 33], [113, 32]],
  ];
  for (const [a, b] of samples) {
    const r = t.bearingDeg(a, b);
    assert.ok(r >= 0 && r < 360, `expected [0,360), got ${r} for ${JSON.stringify([a, b])}`);
  }
});

test('bearingDeg: reciprocal differs by ~180°', () => {
  const t = loadRuler();
  // For short segments at modest latitudes the reciprocal is within 0.5°.
  // Normalize: wrap |fwd - rev| to [0°, 360°) then measure distance from 180°.
  const a = [-112.07, 33.45];
  const b = [-112.05, 33.46];
  const fwd = t.bearingDeg(a, b);
  const rev = t.bearingDeg(b, a);
  const diff = Math.abs(((fwd - rev) + 360) % 360 - 180);
  assert.ok(diff < 0.5, `reciprocal mismatch: fwd=${fwd} rev=${rev} diff=${diff}`);
});

test('bearingDeg: AZ→CO reference (Phoenix → Denver) ~40° (NE)', () => {
  const t = loadRuler();
  // Phoenix Sky Harbor [-112.0117, 33.4342] → Denver DIA [-104.6739, 39.8617]
  // Standard great-circle initial bearing: ~40.35° (verified against FAA coords
  // and multiple geodesy calculators — the NE quadrant is correct).
  // Note: the spec cited ~37°; the correct spherical-Earth value is ~40.35°.
  const b = t.bearingDeg([-112.0117, 33.4342], [-104.6739, 39.8617]);
  assert.ok(Math.abs(b - 40.35) < 1.0, `expected ~40.35°, got ${b}`);
});
