# Nav Engine Tests

Node 20+ `node:test` unit tests for [frontend/navigation.js](../../navigation.js).

## Run

```bash
node --test frontend/tests/engine/
```

## Design

The engine is a browser IIFE that attaches to `window.GeographicaNav`.
`test_runner.mjs` loads it via `node:vm` into a sandbox exposing a fake
`window`. Each `loadEngine()` call returns a FRESH engine — the IIFE
re-executes, so all module-level mutable state (announcedSet,
rerouteSeq, route) starts clean.

Tests import fixtures from `test_runner.mjs` — e.g. `fixtureTwoManeuverRoute`
gives a known 2-maneuver straight-line route for predictable snapping.
