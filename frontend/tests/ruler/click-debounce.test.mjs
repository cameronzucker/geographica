import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

function fakeClickEvent(lng, lat, opts = {}) {
  return {
    lngLat: { lng: lng, lat: lat },
    point: opts.point || { x: 100, y: 100 },
    originalEvent: {
      ctrlKey: opts.ctrlKey || false,
      shiftKey: opts.shiftKey || false,
      altKey: opts.altKey || false,
      metaKey: opts.metaKey || false,
      timeStamp: opts.t !== undefined ? opts.t : 1000,
    },
  };
}

test('handleMapClick during idle starts drawing with V1', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45));
  const s = t.getState();
  assert.strictEqual(s.status, 'drawing');
  assert.strictEqual(s.vertices.length, 1);
});

test('handleMapClick during drawing appends', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { t: 1000 }));
  t.handleMapClick(fakeClickEvent(-112.05, 33.46, { t: 2000, point: { x: 200, y: 200 } }));
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 2);
});

test('handleMapClick debounces near-duplicate clicks within 5px AND 250ms', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { t: 1000, point: { x: 100, y: 100 } }));
  // Second click 3px away (technically 2.83px), 100ms later → debounced
  t.handleMapClick(fakeClickEvent(-112.0701, 33.4500001, { t: 1100, point: { x: 102, y: 102 } }));
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 1, 'second near-duplicate click should be debounced');
});

test('handleMapClick does NOT debounce a click >5px away', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { t: 1000, point: { x: 100, y: 100 } }));
  t.handleMapClick(fakeClickEvent(-112.06, 33.46, { t: 1100, point: { x: 110, y: 110 } }));
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 2);
});

test('handleMapClick does NOT debounce a click >250ms later', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { t: 1000, point: { x: 100, y: 100 } }));
  t.handleMapClick(fakeClickEvent(-112.0701, 33.4500001, { t: 1300, point: { x: 102, y: 102 } }));
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 2);
});

test('handleMapClick suppresses on Ctrl-click', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { ctrlKey: true }));
  assert.strictEqual(t.getState().vertices.length, 0);
});

test('handleMapClick suppresses on Shift-click', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { shiftKey: true }));
  assert.strictEqual(t.getState().vertices.length, 0);
});

test('handleMapClick suppresses on Meta-click (Cmd on macOS)', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { metaKey: true }));
  assert.strictEqual(t.getState().vertices.length, 0);
});

test('handleMapClick suppresses on Alt-click', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { altKey: true }));
  assert.strictEqual(t.getState().vertices.length, 0);
});

test('handleMapClick during editing is a no-op', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { t: 1000 }));
  t.handleMapClick(fakeClickEvent(-112.05, 33.46, { t: 2000, point: { x: 200, y: 200 } }));
  t.finishDrawing();
  // Now in editing — empty-map clicks should NOT add vertices.
  t.handleMapClick(fakeClickEvent(-112.03, 33.47, { t: 3000, point: { x: 300, y: 300 } }));
  assert.strictEqual(t.getState().vertices.length, 2);
});

test('clearAll resets lastClick — post-clear click within 5px+250ms is NOT debounced', () => {
  const { test: t } = loadRuler();
  // Place V1 at point P.
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { t: 1000, point: { x: 100, y: 100 } }));
  // Clear the measurement — should reset lastClick.
  t.clearAll();
  // A click 100 ms later within 3 px should NOT be debounced (lastClick is null).
  t.handleMapClick(fakeClickEvent(-112.0701, 33.4500001, { t: 1100, point: { x: 102, y: 102 } }));
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 1, 'click after clearAll should NOT be debounced');
  assert.strictEqual(s.status, 'drawing');
});
