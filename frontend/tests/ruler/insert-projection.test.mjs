import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

test('commitInsert mid-path projects onto adjacent segment', () => {
  const { test: t } = loadRuler();
  // Two vertices along latitude 33.45 (east-west segment)
  t.startNewMeasurement();
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.00, 33.45);
  t.finishDrawing();
  t.selectVertex(0);
  t.startInsertAfter();   // slot.before = 1 → projects onto V1→V2 segment
  // Tap slightly north of segment midpoint
  t.commitInsert(-112.05, 33.46);
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 3);
  assert.strictEqual(s.status, 'editing');
  // Inserted vertex should be on the segment (lat ≈ 33.45) at the midpoint
  // longitude. Both axes are tight: the segment is east-west, so projection
  // returns exact lat=a[1]+t*0=33.45, and lng=a[0]+t*dx with t=0.5 → exact
  // -112.05 (operands are clean half-multiples, no fp drift).
  assert.ok(Math.abs(s.vertices[1].lat - 33.45) < 1e-9);
  assert.ok(Math.abs(s.vertices[1].lng - (-112.05)) < 1e-9);
});

test('commitInsert at path endpoint (Insert After Vlast) places at raw tap', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.00, 33.45);
  t.finishDrawing();
  t.selectVertex(1);  // last vertex
  t.startInsertAfter();   // slot.before = 2 → no segment to project onto
  t.commitInsert(-111.90, 33.50);  // tap somewhere off-axis
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 3);
  // Inserted at raw tap (no projection)
  assert.ok(Math.abs(s.vertices[2].lng - (-111.90)) < 1e-6);
  assert.ok(Math.abs(s.vertices[2].lat - 33.50) < 1e-6);
});

test('commitInsert at path start (Insert Before V1) places at raw tap', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.00, 33.45);
  t.finishDrawing();
  t.selectVertex(0);
  t.startInsertBefore();   // slot.before = 0 → no segment before V1
  t.commitInsert(-112.20, 33.50);
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 3);
  assert.ok(Math.abs(s.vertices[0].lng - (-112.20)) < 1e-6);
  assert.ok(Math.abs(s.vertices[0].lat - 33.50) < 1e-6);
});

test('commitInsert relabels V1..Vn contiguously after splice', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.00, 33.45);
  t.finishDrawing();
  t.selectVertex(0);
  t.startInsertAfter();
  t.commitInsert(-112.05, 33.46);
  const s = t.getState();
  assert.strictEqual(s.vertices[0].label, 'V1');
  assert.strictEqual(s.vertices[1].label, 'V2');
  assert.strictEqual(s.vertices[2].label, 'V3');
});

test('commitInsert leaves selection on the new vertex', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.00, 33.45);
  t.finishDrawing();
  t.selectVertex(0);
  t.startInsertAfter();
  t.commitInsert(-112.05, 33.46);
  assert.strictEqual(t.getState().selectedVertex, 1);
});
