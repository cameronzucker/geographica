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

// Fixture: a 3-maneuver route (2 turns + arrival) for voice/snap testing.
// Coords are in [lng, lat] order per MapLibre/Valhalla convention.
export function fixtureRouteWithTwoTurns() {
  return {
    coords: [
      [-111.65, 35.20],  // start
      [-111.64, 35.20],  // maneuver 1 boundary (~1 km east)
      [-111.63, 35.20],  // maneuver 2 boundary (~1 km ENE)
      [-111.62, 35.21],  // end (~1 km NE)
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
        type: 2,
        instruction: 'Turn left onto Main Street',
        verbal_transition_alert_instruction: 'Prepare to turn left',
        verbal_pre_transition_instruction: 'Turn left onto Main Street',
        begin_shape_index: 1,
        end_shape_index: 2,
      },
      {
        type: 15,
        instruction: 'You have arrived at your destination',
        begin_shape_index: 2,
        end_shape_index: 3,
      },
    ],
    summary: { length: 3.0, time: 150 },
    totalDistance: 3000,
    totalTime: 150,
    costing: 'auto',
    remainingWaypoints: [],
  };
}

// Fixture: 4-maneuver route with 3 close-spaced turns ("Villa Rita class").
// maneuver[0] is the depart leg (not spoken).
// maneuver[1], maneuver[2], maneuver[3] are the 3 spoken turns.
// Coords in [lng, lat] order. Each turn is ~30m east of the previous at lat 35.20
// (1° longitude ≈ 91 km at lat 35, so 30 m ≈ 0.00033°).
export function fixtureVillaRitaCluster() {
  return {
    coords: [
      [-111.65000, 35.20],  // depart start (index 0)
      [-111.64967, 35.20],  // maneuver 1 boundary (30m east of depart)
      [-111.64934, 35.20],  // maneuver 2 boundary (30m east of maneuver 1)
      [-111.64901, 35.20],  // maneuver 3 boundary (30m east of maneuver 2)
      [-111.64868, 35.20],  // route end
    ],
    maneuvers: [
      {
        type: 1,
        instruction: 'Head east',
        verbal_transition_alert_instruction: 'In 100 feet, turn left',
        verbal_pre_transition_instruction: 'Head east',
        begin_shape_index: 0,
        end_shape_index: 1,
      },
      {
        type: 15,
        instruction: 'Turn left onto Mulberry',
        verbal_transition_alert_instruction: 'In 100 feet, turn left onto Mulberry',
        verbal_pre_transition_instruction: 'Turn left onto Mulberry',
        begin_shape_index: 1,
        end_shape_index: 2,
      },
      {
        type: 10,
        instruction: 'Turn right onto Oak',
        verbal_transition_alert_instruction: 'In 100 feet, turn right onto Oak',
        verbal_pre_transition_instruction: 'Turn right onto Oak',
        begin_shape_index: 2,
        end_shape_index: 3,
      },
      {
        type: 4,
        instruction: 'Turn left onto Villa Rita',
        verbal_transition_alert_instruction: 'In 100 feet, turn left onto Villa Rita',
        verbal_pre_transition_instruction: 'Turn left onto Villa Rita',
        begin_shape_index: 3,
        end_shape_index: 4,
      },
    ],
    summary: { length: 0.12, time: 12 },
    totalDistance: 120,
    totalTime: 12,
    costing: 'auto',
    remainingWaypoints: [],
  };
}

// Fixture: 4-maneuver route with turns spaced 80m apart — the "mixed cluster"
// regime the field-test found under-served by D1 suppression alone (40-90m
// spacing puts far-tier and near-tier on DIFFERENT ticks, so D1's same-tick
// gate misses). Exercises I11 chain-extension suppression: each near-tier
// with a chain should pre-mark the next-after-next's far-tier as announced.
// 80m at lat 35.20 ≈ 0.00088°.
export function fixtureMixedSpacingCluster() {
  return {
    coords: [
      [-111.65000, 35.20],  // depart start (index 0)
      [-111.64912, 35.20],  // M1 boundary (80m east)
      [-111.64824, 35.20],  // M2 boundary (80m east)
      [-111.64736, 35.20],  // M3 boundary (80m east)
      [-111.64648, 35.20],  // route end
    ],
    maneuvers: [
      {
        type: 1,
        instruction: 'Head east',
        verbal_transition_alert_instruction: 'In 300 feet, turn left',
        verbal_pre_transition_instruction: 'Head east',
        begin_shape_index: 0,
        end_shape_index: 1,
      },
      {
        type: 15,
        instruction: 'Turn left onto First Street',
        verbal_transition_alert_instruction: 'In 300 feet, turn left onto First Street',
        verbal_pre_transition_instruction: 'Turn left onto First Street',
        begin_shape_index: 1,
        end_shape_index: 2,
      },
      {
        type: 10,
        instruction: 'Turn right onto Second Road',
        verbal_transition_alert_instruction: 'In 300 feet, turn right onto Second Road',
        verbal_pre_transition_instruction: 'Turn right onto Second Road',
        begin_shape_index: 2,
        end_shape_index: 3,
      },
      {
        type: 4,
        instruction: 'Turn left onto Third Avenue',
        verbal_transition_alert_instruction: 'In 300 feet, turn left onto Third Avenue',
        verbal_pre_transition_instruction: 'Turn left onto Third Avenue',
        begin_shape_index: 3,
        end_shape_index: 4,
      },
    ],
    summary: { length: 0.32, time: 32 },
    totalDistance: 320,
    totalTime: 32,
    costing: 'auto',
    remainingWaypoints: [],
  };
}

// Backward-compat alias: earlier plan tasks reference the old name.
// Remove when all plan tasks have been converted.
export const fixtureTwoManeuverRoute = fixtureRouteWithTwoTurns;
