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

test('projectPointToSegment: point already on segment returns same point', () => {
  const t = loadRuler();
  const r = t.projectPointToSegment([0.5, 0.5], [0, 0], [1, 1]);
  assert.ok(Math.abs(r[0] - 0.5) < 1e-6);
  assert.ok(Math.abs(r[1] - 0.5) < 1e-6);
});

test('projectPointToSegment: point off-side projects perpendicularly', () => {
  const t = loadRuler();
  const r = t.projectPointToSegment([5, 5], [0, 0], [10, 0]);
  assert.ok(Math.abs(r[0] - 5) < 1e-6, `expected x≈5, got ${r[0]}`);
  assert.ok(Math.abs(r[1] - 0) < 1e-6, `expected y≈0, got ${r[1]}`);
});

test('projectPointToSegment: point past start clamps to start', () => {
  const t = loadRuler();
  const r = t.projectPointToSegment([-5, 5], [0, 0], [10, 0]);
  assert.ok(Math.abs(r[0] - 0) < 1e-6, `expected x=0, got ${r[0]}`);
  assert.ok(Math.abs(r[1] - 0) < 1e-6, `expected y=0, got ${r[1]}`);
});

test('projectPointToSegment: point past end clamps to end', () => {
  const t = loadRuler();
  const r = t.projectPointToSegment([15, 5], [0, 0], [10, 0]);
  assert.ok(Math.abs(r[0] - 10) < 1e-6);
  assert.ok(Math.abs(r[1] - 0) < 1e-6);
});

test('projectPointToSegment: zero-length segment returns segment point', () => {
  const t = loadRuler();
  const r = t.projectPointToSegment([5, 5], [3, 3], [3, 3]);
  assert.ok(Math.abs(r[0] - 3) < 1e-6);
  assert.ok(Math.abs(r[1] - 3) < 1e-6);
});

test('projectPointToSegment: AZ-scale realistic case', () => {
  const t = loadRuler();
  const seg_a = [-112.07, 33.45];
  const seg_b = [-112.00, 33.45];
  const tap = [-112.035, 33.46];
  const r = t.projectPointToSegment(tap, seg_a, seg_b);
  assert.ok(Math.abs(r[0] - (-112.035)) < 0.01);
  assert.ok(Math.abs(r[1] - 33.45) < 0.001);
});
