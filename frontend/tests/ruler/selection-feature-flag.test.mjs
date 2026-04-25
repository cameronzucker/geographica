import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

test('buildVertexFeatures: selectedVertex=null → no Features have selected=true', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  const fc = t.buildVertexFeatures();
  assert.strictEqual(fc.features.length, 2);
  for (const f of fc.features) {
    assert.strictEqual(f.properties.selected, false);
  }
});

test('buildVertexFeatures: selectedVertex=1 → exactly one Feature has selected=true', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.addVertex(-112.03, 33.47);
  t.finishDrawing();
  t.selectVertex(1);
  const fc = t.buildVertexFeatures();
  const selectedFlags = fc.features.map(f => f.properties.selected);
  assert.strictEqual(selectedFlags.length, 3);
  assert.strictEqual(selectedFlags[0], false);
  assert.strictEqual(selectedFlags[1], true);
  assert.strictEqual(selectedFlags[2], false);
});

test('buildVertexFeatures: each Feature carries its index property', () => {
  const { test: t } = loadRuler();
  t.startNewMeasurement();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  const fc = t.buildVertexFeatures();
  assert.strictEqual(fc.features[0].properties.index, 0);
  assert.strictEqual(fc.features[1].properties.index, 1);
});
