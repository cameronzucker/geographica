import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createContext, runInContext } from 'node:vm';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));

function loadNavUIInternals() {
  // nav-ui.js runs init() at IIFE end (`if (document.readyState === 'loading') ...
  // else init()`). We stub enough DOM and browser globals so init() doesn't
  // throw. Even if it did, window._geographicaNavUIInternals is assigned
  // BEFORE the bootstrap section (see Task 4 Step 4) so the internals are
  // captured regardless.
  const code = readFileSync(join(__dirname, '..', '..', 'nav-ui.js'), 'utf8');
  const stubEl = () => ({
    addEventListener: () => {},
    removeEventListener: () => {},
    classList: { contains: () => true, remove: () => {}, add: () => {}, toggle: () => {} },
    appendChild: () => {},
    removeChild: () => {},
    querySelector: () => null,
    closest: () => null,
    style: {},
    firstChild: null,
    offsetHeight: 100,
    dispatchEvent: () => {},
    setAttribute: () => {},
  });
  const doc = {
    readyState: 'complete', // avoid the DOMContentLoaded path
    getElementById: () => stubEl(),
    querySelector: () => null,
    querySelectorAll: () => [],
    documentElement: { style: { setProperty: () => {} } },
    createElement: () => stubEl(),
    createElementNS: () => stubEl(),
    addEventListener: () => {},
  };
  const win = {
    _geographicaMap: {
      on: () => {}, off: () => {}, easeTo: () => {}, getBearing: () => 0,
      getContainer: () => ({ clientHeight: 900 }),
      getSource: () => ({ setData: () => {} }),
      fitBounds: () => {},
    },
    _geographicaUseImperial: true,
    _geographicaGPSData: null,
    innerWidth: 1280,
    innerHeight: 900,
    localStorage: { getItem: () => null, setItem: () => {} },
    speechSynthesis: null,
    SpeechSynthesisUtterance: null,
    GeographicaNav: { // dummy — not used by buildRouteData
      onUpdate: () => {}, onVoice: () => {}, onArrival: () => {}, onReroute: () => {},
      start: () => {}, setMuted: () => {},
    },
  };
  // MutationObserver stub — observeRouteAvailability uses it.
  class StubMutationObserver {
    constructor(cb) { this.cb = cb; }
    observe() {}
    disconnect() {}
  }
  const sandbox = {
    window: win, document: doc,
    MutationObserver: StubMutationObserver,
    setTimeout, clearTimeout, setInterval, clearInterval,
    Date, Math, Object, Array, Number, String, parseInt, parseFloat, console,
  };
  const ctx = createContext(sandbox);
  try {
    runInContext(code, ctx, { filename: 'nav-ui.js' });
  } catch (err) {
    // init() may throw on degenerate stubs; internals should already be set.
    if (!win._geographicaNavUIInternals) throw err;
  }
  return win._geographicaNavUIInternals;
}

test('buildRouteData extracts remainingWaypoints from trip.locations', () => {
  const internals = loadNavUIInternals();
  const trip = {
    legs: [
      {
        shape: 'gxz_}Anbf}E',  // decodable stub — any polyline
        maneuvers: [{
          type: 1, instruction: 'Head east', begin_shape_index: 0, end_shape_index: 0,
        }],
      },
    ],
    summary: { length: 10, time: 600 },
    locations: [
      { lat: 35.20, lon: -111.65, type: 'break' },
      { lat: 35.21, lon: -111.64, type: 'through' },
      { lat: 35.22, lon: -111.63, type: 'through' },
      { lat: 35.23, lon: -111.62, type: 'break' },
    ],
    _costing: 'auto',
  };

  const result = internals.buildRouteData(trip);
  // Spread into outer-realm arrays so deepStrictEqual works cross-realm.
  const got = Array.from(result.remainingWaypoints).map((w) => ({ ...w }));
  assert.deepEqual(
    got,
    [
      { lat: 35.21, lon: -111.64, type: 'through' },
      { lat: 35.22, lon: -111.63, type: 'through' },
    ],
    'intermediate locations must be populated as remainingWaypoints'
  );
});

test('buildRouteData returns empty remainingWaypoints for 2-location trip', () => {
  const internals = loadNavUIInternals();
  const trip = {
    legs: [{ shape: 'gxz_}Anbf}E', maneuvers: [{ type: 1, instruction: 'go', begin_shape_index: 0, end_shape_index: 0 }] }],
    summary: { length: 1, time: 60 },
    locations: [
      { lat: 35.20, lon: -111.65, type: 'break' },
      { lat: 35.21, lon: -111.64, type: 'break' },
    ],
    _costing: 'auto',
  };
  const result = internals.buildRouteData(trip);
  // Use length check: vm sandbox arrays are cross-realm and fail deepStrictEqual([]).
  assert.equal(result.remainingWaypoints.length, 0);
});

test('buildRouteData propagates costing_options to route payload', () => {
  const internals = loadNavUIInternals();
  const trip = {
    legs: [{ shape: 'gxz_}Anbf}E', maneuvers: [{ type: 1, instruction: 'go', begin_shape_index: 0, end_shape_index: 0 }] }],
    summary: { length: 1, time: 60 },
    locations: [
      { lat: 35.20, lon: -111.65, type: 'break' },
      { lat: 35.21, lon: -111.64, type: 'break' },
    ],
    _costing: 'bicycle',
    _costingOptions: { bicycle: { bicycle_type: 'road' } },
  };
  const result = internals.buildRouteData(trip);
  assert.deepEqual(
    result.costingOptions,
    { bicycle: { bicycle_type: 'road' } },
    'costingOptions must be preserved on the engine route payload'
  );
});

test('buildRouteData defaults costingOptions to null when absent', () => {
  const internals = loadNavUIInternals();
  const trip = {
    legs: [{ shape: 'gxz_}Anbf}E', maneuvers: [{ type: 1, instruction: 'go', begin_shape_index: 0, end_shape_index: 0 }] }],
    summary: { length: 1, time: 60 },
    locations: [{ lat: 35.20, lon: -111.65 }, { lat: 35.21, lon: -111.64 }],
    _costing: 'auto',
  };
  const result = internals.buildRouteData(trip);
  assert.equal(result.costingOptions, null);
});

test('buildRouteData handles missing trip.locations gracefully', () => {
  const internals = loadNavUIInternals();
  const trip = {
    legs: [{ shape: 'gxz_}Anbf}E', maneuvers: [{ type: 1, instruction: 'go', begin_shape_index: 0, end_shape_index: 0 }] }],
    summary: { length: 1, time: 60 },
    _costing: 'auto',
  };
  const result = internals.buildRouteData(trip);
  // Use length check: vm sandbox arrays are cross-realm and fail deepStrictEqual([]).
  assert.equal(result.remainingWaypoints.length, 0);
});
