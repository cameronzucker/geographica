import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

function fakeKey(key, opts = {}) {
  let prevented = false;
  return {
    key: key,
    target: {
      tagName: opts.tagName || 'BODY',
      isContentEditable: opts.isContentEditable || false,
    },
    preventDefault: () => { prevented = true; },
    get prevented() { return prevented; },
  };
}

test('Backspace during drawing pops last vertex', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.handleKeydown(fakeKey('Backspace'));
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 1);
  assert.strictEqual(s.status, 'drawing');
});

test('Backspace inside an INPUT does NOT pop a vertex', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.handleKeydown(fakeKey('Backspace', { tagName: 'INPUT' }));
  assert.strictEqual(t.getState().vertices.length, 2);
});

test('Backspace inside a TEXTAREA does NOT pop a vertex', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.handleKeydown(fakeKey('Backspace', { tagName: 'TEXTAREA' }));
  assert.strictEqual(t.getState().vertices.length, 2);
});

test('Backspace inside contentEditable does NOT pop a vertex', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.handleKeydown(fakeKey('Backspace', { isContentEditable: true }));
  assert.strictEqual(t.getState().vertices.length, 2);
});

test('Esc during drawing with >=2 vertices transitions to editing', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.handleKeydown(fakeKey('Escape'));
  assert.strictEqual(t.getState().status, 'editing');
});

test('Esc during drawing with <2 vertices returns to idle', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.handleKeydown(fakeKey('Escape'));
  assert.strictEqual(t.getState().status, 'idle');
});

test('Esc during drawing-empty (no vertices) returns to idle', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  // No vertices yet; user pressed Esc to cancel out of measure mode.
  t.handleKeydown(fakeKey('Escape'));
  assert.strictEqual(t.getState().status, 'idle');
});

test('Esc during inserting returns to editing', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  t.startInsertAfter();
  t.handleKeydown(fakeKey('Escape'));
  assert.strictEqual(t.getState().status, 'editing');
});

test('Esc during editing with selection deselects vertex', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  t.handleKeydown(fakeKey('Escape'));
  const s = t.getState();
  assert.strictEqual(s.status, 'editing');
  assert.strictEqual(s.selectedVertex, null);
});

test('Enter during drawing with >=2 vertices finishes', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.handleKeydown(fakeKey('Enter'));
  assert.strictEqual(t.getState().status, 'editing');
});

test('Enter during drawing with <2 vertices is a no-op', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.handleKeydown(fakeKey('Enter'));
  assert.strictEqual(t.getState().status, 'drawing');
});

test('Backspace during idle is a no-op', () => {
  const { test: t } = loadRuler();
  t.handleKeydown(fakeKey('Backspace'));  // must not throw
  assert.strictEqual(t.getState().status, 'idle');
});
