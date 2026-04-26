import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

function fakeTouch(x, y) { return { clientX: x, clientY: y }; }
function fakeTouchEvent(touches, opts = {}) {
  let prevented = false;
  return {
    touches: touches,
    changedTouches: opts.changedTouches || touches,
    preventDefault: () => { prevented = true; },
    get prevented() { return prevented; },
  };
}

test('touchstart on a vertex with one finger initiates drag', () => {
  const { test: t, ctx } = loadRuler();
  // Stub map for the test
  ctx.window._geographicaTestMap = {
    getCanvas: () => ({
      getBoundingClientRect: () => ({ left: 0, top: 0 }),
      style: {},
    }),
    queryRenderedFeatures: () => [{ properties: { index: 0 } }],
    dragPan: { disable: () => { ctx.window._geographicaTestDragPanDisabled = true; },
               enable:  () => { ctx.window._geographicaTestDragPanDisabled = false; } },
    unproject: ([x, y]) => ({ lng: -112 + x / 1000, lat: 33 + y / 1000 }),
  };
  t.installTestMap(ctx.window._geographicaTestMap);

  t.startNewMeasurement();
  t.addVertex(-112, 33);
  t.addVertex(-112.01, 33.01);
  t.finishDrawing();
  t.handleTouchStart(fakeTouchEvent([fakeTouch(100, 100)]));
  const dragging = t.peekDragging();
  assert.ok(dragging, 'drag state should exist after touchstart on vertex');
  assert.strictEqual(dragging.mode, 'touch');
  assert.strictEqual(ctx.window._geographicaTestDragPanDisabled, true);
});

test('multitouch arriving during drag cancels the drag', () => {
  const { test: t, ctx } = loadRuler();
  ctx.window._geographicaTestMap = {
    getCanvas: () => ({ getBoundingClientRect: () => ({ left: 0, top: 0 }), style: {} }),
    queryRenderedFeatures: () => [{ properties: { index: 0 } }],
    dragPan: { disable: () => {}, enable: () => { ctx.window._geographicaTestDragPanReenabled = true; } },
    unproject: ([x, y]) => ({ lng: -112, lat: 33 }),
  };
  t.installTestMap(ctx.window._geographicaTestMap);
  t.startNewMeasurement();
  t.addVertex(-112, 33); t.addVertex(-112.01, 33.01); t.finishDrawing();
  t.handleTouchStart(fakeTouchEvent([fakeTouch(100, 100)]));
  // Now a second finger arrives:
  t.handleTouchMove(fakeTouchEvent([fakeTouch(100, 100), fakeTouch(150, 150)]));
  assert.strictEqual(t.peekDragging(), null, 'drag should be canceled by multitouch');
  assert.strictEqual(ctx.window._geographicaTestDragPanReenabled, true);
});

test('touchstart with two fingers does NOT start a drag', () => {
  const { test: t, ctx } = loadRuler();
  ctx.window._geographicaTestMap = {
    getCanvas: () => ({ getBoundingClientRect: () => ({ left: 0, top: 0 }), style: {} }),
    queryRenderedFeatures: () => [{ properties: { index: 0 } }],
    dragPan: { disable: () => {}, enable: () => {} },
    unproject: ([x, y]) => ({ lng: -112, lat: 33 }),
  };
  t.installTestMap(ctx.window._geographicaTestMap);
  t.startNewMeasurement();
  t.addVertex(-112, 33); t.addVertex(-112.01, 33.01); t.finishDrawing();
  t.handleTouchStart(fakeTouchEvent([fakeTouch(100, 100), fakeTouch(150, 150)]));
  assert.strictEqual(t.peekDragging(), null);
});

test('cancelActiveDrag during touch drag clears state and re-enables dragPan', () => {
  const { test: t, ctx } = loadRuler();
  ctx.window._geographicaTestMap = {
    getCanvas: () => ({ getBoundingClientRect: () => ({ left: 0, top: 0 }), style: {} }),
    queryRenderedFeatures: () => [{ properties: { index: 0 } }],
    dragPan: {
      disable: () => { ctx.window._geographicaTestDragPanDisabled = true; },
      enable:  () => { ctx.window._geographicaTestDragPanReenabled = true; },
    },
    unproject: ([x, y]) => ({ lng: -112, lat: 33 }),
  };
  t.installTestMap(ctx.window._geographicaTestMap);
  t.startNewMeasurement();
  t.addVertex(-112, 33); t.addVertex(-112.01, 33.01); t.finishDrawing();
  t.handleTouchStart(fakeTouchEvent([fakeTouch(100, 100)]));
  assert.ok(t.peekDragging());
  // Simulate visibilitychange / app-background / alt-tab:
  t.cancelActiveDrag();
  assert.strictEqual(t.peekDragging(), null);
  assert.strictEqual(ctx.window._geographicaTestDragPanReenabled, true);
});

test('cancelActiveDrag is idempotent when no drag is active', () => {
  const { test: t } = loadRuler();
  // Should not throw, should be a no-op.
  t.cancelActiveDrag();
  assert.strictEqual(t.peekDragging(), null);
});
