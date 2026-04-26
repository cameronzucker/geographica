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

// Fixture: mimics Valhalla's actual verbal_pre_transition shape when a
// maneuver is part of a quick-succession cluster. Valhalla sometimes bakes
// its own chain into the current maneuver's vpt as a trailing ". Then X."
// sentence, and/or prefixes the next maneuver's vpt with "Then " to signal
// continuation. Observed in Cameron's 2026-04-21 field drive (Wagoner → 24th
// → Union Hills Dr segment). Used to verify the engine strips these to avoid
// double-announcing the same next turn. 80m spacing between turns.
export function fixtureValhallaThenChainedCluster() {
  return {
    coords: [
      [-111.65000, 35.20],  // depart start (index 0)
      [-111.64912, 35.20],  // M1 boundary (80m east)
      [-111.64824, 35.20],  // M2 boundary
      [-111.64736, 35.20],  // M3 boundary
      [-111.64648, 35.20],  // route end
    ],
    maneuvers: [
      {
        type: 1,
        instruction: 'Head east',
        verbal_transition_alert_instruction: 'In 300 feet, turn left onto 24th Drive',
        verbal_pre_transition_instruction: 'Head east',
        begin_shape_index: 0,
        end_shape_index: 1,
      },
      {
        type: 10,
        instruction: 'Turn right onto 24th Drive',
        verbal_transition_alert_instruction: 'In 300 feet, turn right onto 24th Drive',
        // Valhalla-style: vpt ends with ". Then X." chain baked in.
        verbal_pre_transition_instruction: 'Turn right onto 24th Drive. Then Turn left onto West Union Hills Drive.',
        begin_shape_index: 1,
        end_shape_index: 2,
      },
      {
        type: 15,
        instruction: 'Turn left onto West Union Hills Drive',
        verbal_transition_alert_instruction: 'In 300 feet, turn left onto West Union Hills Drive',
        // Valhalla-style: vpt has "Then " prefix because this is a quick-
        // succession continuation. After I11 chain-extension, the prefix is
        // redundant and should be stripped by the engine.
        verbal_pre_transition_instruction: 'Then turn left onto West Union Hills Drive.',
        begin_shape_index: 2,
        end_shape_index: 3,
      },
      {
        type: 6,
        instruction: 'Your destination is on the left',
        verbal_transition_alert_instruction: 'Your destination is on the left',
        verbal_pre_transition_instruction: 'Your destination is on the left.',
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

// Fixture: 4-maneuver route with 200 m maneuver spacing — wide enough that
// near-tier fires above the new 30 m cutoff AND chain-append distance is
// also above cutoff. For I13 prefix-firing assertions.
// 200 m at lat 35.20 ≈ 0.0022°.
export function fixtureWiderCluster() {
  return {
    coords: [
      [-111.65000, 35.20],
      [-111.64780, 35.20],     // M1 boundary (200 m east)
      [-111.64560, 35.20],     // M2 boundary
      [-111.64340, 35.20],     // M3 boundary
      [-111.64120, 35.20],     // route end
    ],
    maneuvers: [
      {
        type: 1,
        instruction: 'Head east',
        // M0 is the depart; checkVoice reads M[1]'s alert text, not M[0]'s.
        // This field is dead data — kept for fixture-shape symmetry.
        verbal_transition_alert_instruction: 'In 700 feet, turn left',
        verbal_pre_transition_instruction: 'Head east',
        begin_shape_index: 0,
        end_shape_index: 1,
      },
      {
        type: 15,
        instruction: 'Turn left onto First Street',
        verbal_transition_alert_instruction: 'Turn left onto First Street',
        verbal_pre_transition_instruction: 'Turn left onto First Street',
        begin_shape_index: 1,
        end_shape_index: 2,
      },
      {
        type: 10,
        instruction: 'Turn right onto Second Road',
        verbal_transition_alert_instruction: 'Turn right onto Second Road',
        verbal_pre_transition_instruction: 'Turn right onto Second Road',
        begin_shape_index: 2,
        end_shape_index: 3,
      },
      {
        type: 4,
        instruction: 'Turn left onto Third Avenue',
        verbal_transition_alert_instruction: 'Turn left onto Third Avenue',
        verbal_pre_transition_instruction: 'Turn left onto Third Avenue',
        begin_shape_index: 3,
        end_shape_index: 4,
      },
    ],
    summary: { length: 0.8, time: 80 },
    totalDistance: 800,
    totalTime: 80,
    costing: 'auto',
    remainingWaypoints: [],
  };
}

// Fixture: 2-maneuver route with a long first segment so far-tier fires at
// a TTM-governed distance well above the cutoff. Used for I13 prefix tests.
// 2000 m segment at lat 35.20 (1° longitude ≈ 91 km at lat 35, so 2000 m ≈ 0.022°).
export function fixtureLongFirstSegment() {
  return {
    coords: [
      [-111.65000, 35.20],     // depart start
      [-111.62800, 35.20],     // M1 boundary (2000 m east)
      [-111.62700, 35.20],     // route end (100 m past M1)
    ],
    maneuvers: [
      {
        type: 1,
        instruction: 'Head east',
        // M0 is the depart; checkVoice reads M[1]'s alert text, not M[0]'s. This
        // field is dead data — kept for fixture-shape symmetry, do NOT rely on it.
        verbal_transition_alert_instruction: 'In 2000 feet, turn left',
        verbal_pre_transition_instruction: 'Head east',
        begin_shape_index: 0,
        end_shape_index: 1,
      },
      {
        type: 15,
        instruction: 'Turn left onto Test Avenue',
        verbal_transition_alert_instruction: 'Turn left onto Test Avenue',
        verbal_pre_transition_instruction: 'Turn left onto Test Avenue',
        begin_shape_index: 1,
        end_shape_index: 2,
      },
    ],
    summary: { length: 2.1, time: 130 },
    totalDistance: 2100,
    totalTime: 130,
    costing: 'auto',
    remainingWaypoints: [],
  };
}
