// Loads frontend/navigation.js into a vm sandbox exposing a fake window
// object and returns { nav, reset } where `nav` is window.GeographicaNav.
//
// Usage:
//   import { loadEngine } from './test_runner.mjs';
//   const { nav } = await loadEngine();
//   nav.start(routeData);
//
// Each call returns a FRESH engine instance (the IIFE is re-executed in a
// fresh vm.Context, so module-level mutable state — announcedSet,
// rerouteSeq, route, etc — starts clean).

import { readFileSync } from 'node:fs';
import { createContext, runInContext } from 'node:vm';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const NAV_JS_PATH = join(__dirname, '..', '..', 'navigation.js');

export async function loadEngine() {
  const code = readFileSync(NAV_JS_PATH, 'utf8');
  const win = {};
  const sandbox = {
    window: win,
    Date,
    Math,
    Object,
    Array,
    Number,
    String,
    parseInt,
    parseFloat,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    console,
  };
  const ctx = createContext(sandbox);
  runInContext(code, ctx, { filename: 'navigation.js' });
  if (!win.GeographicaNav) {
    throw new Error('GeographicaNav was not attached to window');
  }
  return { nav: win.GeographicaNav, window: win };
}

// Fixture: a minimal 2-maneuver straight-line route for general testing.
// Coords are in [lng, lat] order per MapLibre/Valhalla convention.
export function fixtureTwoManeuverRoute() {
  return {
    coords: [
      [-111.65, 35.20],  // start
      [-111.64, 35.20],  // maneuver 1 boundary (~1 km east)
      [-111.63, 35.21],  // end (~1 km NE)
    ],
    maneuvers: [
      {
        type: 1,
        instruction: 'Head east on Route 66',
        verbal_transition_alert_instruction: 'In half a mile, turn left',
        verbal_pre_transition_instruction: 'Turn left onto Oak Street',
        begin_shape_index: 0,
        end_shape_index: 1,
      },
      {
        type: 15,
        instruction: 'You have arrived at your destination',
        begin_shape_index: 2,
        end_shape_index: 2,
      },
    ],
    summary: { length: 2.0, time: 120 },
    totalDistance: 2000,
    totalTime: 120,
    costing: 'auto',
    remainingWaypoints: [],
  };
}
