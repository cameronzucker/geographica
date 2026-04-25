import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(path.join(__dirname, '../../ruler.js'), 'utf-8');

function loadRuler() {
  const win = {
    _haversineDistance: function (a, b) {
      // Real haversine, R = 6,371,000 m
      var R = 6371000;
      var dLat = (b[1] - a[1]) * Math.PI / 180;
      var dLng = (b[0] - a[0]) * Math.PI / 180;
      var lat1 = a[1] * Math.PI / 180;
      var lat2 = b[1] * Math.PI / 180;
      var sinDLat = Math.sin(dLat / 2);
      var sinDLng = Math.sin(dLng / 2);
      var h = sinDLat * sinDLat + Math.cos(lat1) * Math.cos(lat2) * sinDLng * sinDLng;
      return 2 * R * Math.asin(Math.sqrt(h));
    },
  };
  const ctx = vm.createContext({ window: win, document: {}, console });
  vm.runInContext(SOURCE, ctx);
  return ctx.window._ruler._test;
}

test('samplePath: returns N samples for non-degenerate input', () => {
  const t = loadRuler();
  const vertices = [
    { lng: -112.07, lat: 33.45 },
    { lng: -112.05, lat: 33.46 },
    { lng: -112.03, lat: 33.47 },
  ];
  const samples = t.samplePath(vertices, 50);
  assert.strictEqual(samples.length, 50);
});

test('samplePath: first sample is exactly at first vertex; last at last', () => {
  const t = loadRuler();
  const vertices = [
    { lng: -112.07, lat: 33.45 },
    { lng: -112.05, lat: 33.46 },
  ];
  const samples = t.samplePath(vertices, 50);
  assert.ok(Math.abs(samples[0].lng - vertices[0].lng) < 1e-9);
  assert.ok(Math.abs(samples[0].lat - vertices[0].lat) < 1e-9);
  assert.ok(Math.abs(samples[49].lng - vertices[1].lng) < 1e-9);
  assert.ok(Math.abs(samples[49].lat - vertices[1].lat) < 1e-9);
});

test('samplePath: distance_m increases monotonically', () => {
  const t = loadRuler();
  const vertices = [
    { lng: -112.07, lat: 33.45 },
    { lng: -112.04, lat: 33.50 },
    { lng: -112.00, lat: 33.55 },
  ];
  const samples = t.samplePath(vertices, 100);
  for (let i = 1; i < samples.length; i++) {
    assert.ok(samples[i].distance_m >= samples[i - 1].distance_m,
      `distance_m not monotonic at ${i}: ${samples[i - 1].distance_m} → ${samples[i].distance_m}`);
  }
});

test('samplePath: samples cross segment boundaries correctly', () => {
  const t = loadRuler();
  // Two equal segments — middle sample should be near the middle vertex
  const vertices = [
    { lng: 0, lat: 0 },
    { lng: 0, lat: 1 },
    { lng: 0, lat: 2 },
  ];
  const samples = t.samplePath(vertices, 51);
  const middle = samples[25];
  assert.ok(Math.abs(middle.lat - 1.0) < 0.05, `middle lat ~1.0, got ${middle.lat}`);
});

test('samplePath: single vertex returns empty array (no segments)', () => {
  const t = loadRuler();
  const samples = t.samplePath([{ lng: -112, lat: 33 }], 50);
  assert.strictEqual(samples.length, 0);
});

test('samplePath: zero-length path (duplicate vertices) returns N at same point', () => {
  const t = loadRuler();
  const v = { lng: -112, lat: 33 };
  const samples = t.samplePath([v, { ...v }], 5);
  assert.strictEqual(samples.length, 5);
  for (const s of samples) {
    assert.ok(Math.abs(s.lng - v.lng) < 1e-9);
    assert.ok(Math.abs(s.lat - v.lat) < 1e-9);
    assert.strictEqual(s.distance_m, 0);
  }
});

test('samplePath: empty input returns empty array', () => {
  const t = loadRuler();
  assert.strictEqual(t.samplePath([], 10).length, 0);
});
