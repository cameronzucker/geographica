import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

test('initial state is idle, vertices empty', () => {
  const { test: t } = loadRuler();
  const s = t.getState();
  assert.strictEqual(s.status, 'idle');
  assert.strictEqual(s.vertices.length, 0);
  assert.strictEqual(s.selectedVertex, null);
  assert.strictEqual(s.insertSlot, null);
});

test('addVertex from idle transitions to drawing', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  const s = t.getState();
  assert.strictEqual(s.status, 'drawing');
  assert.strictEqual(s.vertices.length, 1);
  assert.strictEqual(s.vertices[0].label, 'V1');
  assert.strictEqual(s.totalDistance_m, 0);
});

test('addVertex twice produces 2 vertices and 1 segment', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 2);
  assert.strictEqual(s.segments.length, 1);
  assert.ok(s.totalDistance_m > 0, 'totalDistance_m should be > 0');
  assert.ok(s.segments[0].distance_m > 0);
  assert.ok(s.segments[0].bearing_deg >= 0 && s.segments[0].bearing_deg < 360);
});

test('popVertex from drawing with 1 vertex returns to idle', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.popVertex();
  const s = t.getState();
  assert.strictEqual(s.status, 'idle');
  assert.strictEqual(s.vertices.length, 0);
});

test('popVertex from drawing with multiple vertices stays in drawing', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.addVertex(-112.03, 33.47);
  t.popVertex();
  const s = t.getState();
  assert.strictEqual(s.status, 'drawing');
  assert.strictEqual(s.vertices.length, 2);
});

test('finishDrawing requires >=2 vertices, transitions to editing', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.finishDrawing();   // 1 vertex: should be a no-op
  assert.strictEqual(t.getState().status, 'drawing');
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  assert.strictEqual(t.getState().status, 'editing');
});

test('clearAll resets to idle from any state', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  t.clearAll();
  const s = t.getState();
  assert.strictEqual(s.status, 'idle');
  assert.strictEqual(s.vertices.length, 0);
  assert.strictEqual(s.selectedVertex, null);
  assert.strictEqual(s.insertSlot, null);
  assert.strictEqual(s.totalDistance_m, 0);
});

test('selectVertex requires editing state', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.selectVertex(0);  // still drawing — should be no-op
  assert.strictEqual(t.getState().selectedVertex, null);
  t.finishDrawing();
  t.selectVertex(0);
  assert.strictEqual(t.getState().selectedVertex, 0);
});

test('deselectVertex clears selection without leaving editing', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  t.deselectVertex();
  const s = t.getState();
  assert.strictEqual(s.selectedVertex, null);
  assert.strictEqual(s.status, 'editing');
});

test('startInsertAfter from editing transitions to inserting with slot=index+1', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  t.startInsertAfter();
  const s = t.getState();
  assert.strictEqual(s.status, 'inserting');
  assert.strictEqual(s.insertSlot.before, 1);
});

test('startInsertBefore from editing transitions to inserting with slot=index', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(1);
  t.startInsertBefore();
  const s = t.getState();
  assert.strictEqual(s.status, 'inserting');
  assert.strictEqual(s.insertSlot.before, 1);
});

test('cancelInsert returns to editing with previous selection preserved', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  t.startInsertAfter();
  t.cancelInsert();
  const s = t.getState();
  assert.strictEqual(s.status, 'editing');
  assert.strictEqual(s.selectedVertex, 0);
  assert.strictEqual(s.insertSlot, null);
});

test('shape invariant: vertices.length < 2 ⇒ segments.length === 0', () => {
  const { test: t } = loadRuler();
  let s = t.getState();
  assert.strictEqual(s.segments.length, 0);
  t.addVertex(-112.07, 33.45);
  s = t.getState();
  assert.strictEqual(s.segments.length, 0);
});

test('shape invariant: clearAll wipes everything atomically', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  t.clearAll();
  const s = t.getState();
  assert.strictEqual(s.selectedVertex, null);
  assert.strictEqual(s.status, 'idle');
});
