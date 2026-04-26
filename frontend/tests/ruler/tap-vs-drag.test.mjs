import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

test('isTap: 0px 0ms is a tap', () => {
  const { test: t } = loadRuler();
  assert.strictEqual(t.isTap({ x: 100, y: 100, t: 1000 }, { x: 100, y: 100, t: 1000 }, 'mouse'), true);
});

test('isTap mouse: 4px 150ms is a tap (under both thresholds)', () => {
  const { test: t } = loadRuler();
  assert.strictEqual(t.isTap({ x: 100, y: 100, t: 1000 }, { x: 104, y: 100, t: 1150 }, 'mouse'), true);
});

test('isTap mouse: 6px 150ms is a drag (over distance threshold)', () => {
  const { test: t } = loadRuler();
  assert.strictEqual(t.isTap({ x: 100, y: 100, t: 1000 }, { x: 106, y: 100, t: 1150 }, 'mouse'), false);
});

test('isTap mouse: 4px 250ms is a drag (over time threshold)', () => {
  const { test: t } = loadRuler();
  assert.strictEqual(t.isTap({ x: 100, y: 100, t: 1000 }, { x: 104, y: 100, t: 1250 }, 'mouse'), false);
});

test('isTap touch: 7px 240ms is a tap (looser thresholds)', () => {
  const { test: t } = loadRuler();
  assert.strictEqual(t.isTap({ x: 100, y: 100, t: 1000 }, { x: 107, y: 100, t: 1240 }, 'touch'), true);
});

test('isTap touch: 9px 240ms is a drag', () => {
  const { test: t } = loadRuler();
  assert.strictEqual(t.isTap({ x: 100, y: 100, t: 1000 }, { x: 109, y: 100, t: 1240 }, 'touch'), false);
});
