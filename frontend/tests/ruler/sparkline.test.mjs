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

test('sparklinePath: empty samples returns empty string', () => {
  const t = loadRuler();
  assert.strictEqual(t.sparklinePath([], 250, 80), '');
});

test('sparklinePath: single sample returns one point', () => {
  const t = loadRuler();
  const r = t.sparklinePath([{ distance_m: 0, elevation_m: 100 }], 250, 80);
  assert.match(r, /^\d+(\.\d+)?,\d+(\.\d+)?$/);
});

test('sparklinePath: monotonic increase produces monotonic SVG y', () => {
  const t = loadRuler();
  const samples = [
    { distance_m: 0,    elevation_m: 0 },
    { distance_m: 500,  elevation_m: 500 },
    { distance_m: 1000, elevation_m: 1000 },
  ];
  const r = t.sparklinePath(samples, 250, 80);
  const points = r.split(' ').map(p => p.split(',').map(parseFloat));
  assert.strictEqual(points.length, 3);
  assert.ok(points[0][1] > points[1][1]);
  assert.ok(points[1][1] > points[2][1]);
});

test('sparklinePath: max elevation maps near top (y near 0)', () => {
  const t = loadRuler();
  const samples = [
    { distance_m: 0,    elevation_m: 0 },
    { distance_m: 1000, elevation_m: 1000 },
  ];
  const r = t.sparklinePath(samples, 250, 80);
  const points = r.split(' ').map(p => p.split(',').map(parseFloat));
  assert.ok(points[1][1] < 10, `max elevation y should be near 0, got ${points[1][1]}`);
});

test('sparklinePath: skips null elevation samples', () => {
  const t = loadRuler();
  const samples = [
    { distance_m: 0,    elevation_m: 0 },
    { distance_m: 500,  elevation_m: null },
    { distance_m: 1000, elevation_m: 100 },
  ];
  const r = t.sparklinePath(samples, 250, 80);
  const points = r.split(' ');
  assert.strictEqual(points.length, 2);
});
