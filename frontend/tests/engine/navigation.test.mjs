import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadEngine, fixtureRouteWithTwoTurns } from './test_runner.mjs';

test('engine loads and exposes the expected API', async () => {
  const { nav } = await loadEngine();
  assert.equal(typeof nav.start, 'function');
  assert.equal(typeof nav.stop, 'function');
  assert.equal(typeof nav.updateGPS, 'function');
  assert.equal(typeof nav.applyReroute, 'function');
  assert.equal(typeof nav.setMuted, 'function');
  assert.equal(typeof nav.onUpdate, 'function');
  assert.equal(typeof nav.onReroute, 'function');
  assert.equal(typeof nav.getState, 'function');
});

test('start enters navigating when GPS is on-route', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = {
    lat: 35.20, lon: -111.65, heading: 90, speed: 5,
  };
  const updates = [];
  nav.onUpdate((s) => updates.push(s));
  nav.start(fixtureRouteWithTwoTurns());
  assert.equal(updates.length, 1);
  assert.equal(updates[0].state, 'navigating');
});

test('applyReroute clears announcedSet and lastAnnouncementTime', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((voiceText) => voiceFires.push({ text: voiceText, at: Date.now() }));

  nav.start(fixtureRouteWithTwoTurns());

  // Drive close enough to trigger the 'near' announcement for maneuver 1.
  // Maneuver 1 is at coord[1] = [-111.64, 35.20].
  // Approach to within 40m: use [-111.6405, 35.20].
  nav.updateGPS({ latitude: 35.20, longitude: -111.6405, heading: 90, speed: 10 });
  const firstFireCount = voiceFires.length;
  assert.ok(firstFireCount >= 1, 'expected at least one announcement on approach');

  // Simulate reroute: engine receives a new route via applyReroute.
  let capturedSeq = null;
  nav.onReroute((info) => { capturedSeq = info._seq; });
  // Force an off-route trigger by feeding distinct off-route GPS positions;
  // engine's hysteresis requires 3 of 5 ticks off-route. Engine now deduplicates
  // by (lat, lng), so we must feed distinct positions.
  const offRoutePositions = [
    [35.25, -111.55], [35.26, -111.54], [35.27, -111.53],
    [35.28, -111.52], [35.29, -111.51],
  ];
  offRoutePositions.forEach(([lat, lon]) => {
    nav.updateGPS({ latitude: lat, longitude: lon, heading: 90, speed: 10 });
  });
  assert.ok(capturedSeq != null, 'engine should have fired onReroute callback');

  // New route — same shape, just a stand-in.
  const newRoute = fixtureRouteWithTwoTurns();
  nav.applyReroute(newRoute, capturedSeq);

  // After applyReroute, announcedSet and lastAnnouncementTime must be fully reset:
  // driving the same approach as before must fire the announcement again.
  const beforeNewFires = voiceFires.length;
  nav.updateGPS({ latitude: 35.20, longitude: -111.6405, heading: 90, speed: 10 });
  assert.ok(
    voiceFires.length > beforeNewFires,
    'announcement should re-fire on new route; was suppressed — announcedSet/lastAnnouncementTime not cleared'
  );
});

test('triggerReroute preserves remainingWaypoints in the callback info', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };

  // Route with two intermediate waypoints.
  const multiStopRoute = {
    ...fixtureRouteWithTwoTurns(),
    remainingWaypoints: [
      { lat: 35.21, lon: -111.64, type: 'through' },
      { lat: 35.22, lon: -111.63, type: 'through' },
    ],
  };

  const rerouteCalls = [];
  nav.onReroute((info) => rerouteCalls.push(info));

  nav.start(multiStopRoute);

  // Feed distinct off-route positions (engine now deduplicates by lat,lng).
  const offRoutePositions = [
    [35.25, -111.55], [35.26, -111.54], [35.27, -111.53],
    [35.28, -111.52], [35.29, -111.51],
  ];
  offRoutePositions.forEach(([lat, lon]) => {
    nav.updateGPS({ latitude: lat, longitude: lon, heading: 90, speed: 10 });
  });

  assert.equal(rerouteCalls.length, 1);
  assert.deepEqual(
    rerouteCalls[0].remainingWaypoints,
    [
      { lat: 35.21, lon: -111.64, type: 'through' },
      { lat: 35.22, lon: -111.63, type: 'through' },
    ],
    'remainingWaypoints must be passed through to the onReroute callback'
  );
});

test('duplicate GPS positions do not fill off-route hysteresis (B7)', async () => {
  const { nav, window: win } = await loadEngine();
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };

  const rerouteCalls = [];
  nav.onReroute((info) => rerouteCalls.push(info));

  nav.start(fixtureRouteWithTwoTurns());

  // Feed the SAME off-route position 10 times — simulates feedGPS()
  // ticking every 500 ms on a stationary vehicle whose backend-pushed
  // GPS data object hasn't changed. Engine must dedup by (lat,lng)
  // and only tick once per unique position, so hysteresis cannot fill.
  for (let i = 0; i < 10; i++) {
    nav.updateGPS({ latitude: 35.25, longitude: -111.55, heading: 90, speed: 10 });
  }
  assert.equal(rerouteCalls.length, 0, 'duplicate positions must not fill hysteresis');

  // Feed 5 distinct positions — each must count, hysteresis fills, reroute fires.
  const offRoutePositions = [
    [35.25, -111.55], [35.26, -111.54], [35.27, -111.53],
    [35.28, -111.52], [35.29, -111.51],
  ];
  offRoutePositions.forEach(([lat, lon]) => {
    nav.updateGPS({ latitude: lat, longitude: lon, heading: 90, speed: 10 });
  });
  assert.equal(rerouteCalls.length, 1, 'distinct positions fill hysteresis as designed');
});

test('reroute timeout clears lastRerouteTime for immediate re-reroute', { timeout: 15_000 }, async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };

  const rerouteCalls = [];
  nav.onReroute((info) => rerouteCalls.push(info));

  nav.start(fixtureRouteWithTwoTurns());

  // Trigger reroute #1 by feeding distinct off-route positions (3-of-5 hysteresis).
  // Engine now deduplicates by (lat, lng), so we must feed distinct positions.
  const offRoutePositions1 = [
    [35.25, -111.55], [35.26, -111.54], [35.27, -111.53],
    [35.28, -111.52], [35.29, -111.51],
  ];
  offRoutePositions1.forEach(([lat, lon]) => {
    nav.updateGPS({ latitude: lat, longitude: lon, heading: 90, speed: 10 });
  });
  assert.equal(rerouteCalls.length, 1, 'first reroute should fire');

  // Wait 10.5 seconds: this exceeds REROUTE_TIMEOUT (10_000ms) but is
  // BELOW REROUTE_COOLDOWN (15_000ms) from the first trigger. If the
  // fix is applied (lastRerouteTime cleared on timeout), a second off-
  // route trigger fires a new reroute. If the fix is NOT applied, the
  // cooldown blocks until 15 s from the first trigger (an additional
  // 4.5 s beyond our wait).
  await new Promise((r) => setTimeout(r, 10_500));

  // Feed 5 more off-route positions at DIFFERENT coords. Using distinct
  // coords makes the 5-tick hysteresis window unambiguously off-route
  // and is forward-compatible with the Task 12 engine-side position
  // dedup that will land later in this plan.
  for (let i = 0; i < 5; i++) {
    nav.updateGPS({
      latitude: 35.30 + i * 0.001,
      longitude: -111.50 - i * 0.001,
      heading: 90, speed: 10,
    });
  }
  assert.equal(
    rerouteCalls.length, 2,
    'second reroute should fire after engine timeout (lastRerouteTime cleared)'
  );
});

test('B1 band-aid: voice tiers capped at 2 per costing (remove when TTM ships)', async () => {
  const { window: win } = await loadEngine();
  const internals = win._geographicaNavEngineInternals;
  assert.ok(internals, 'engine must expose _geographicaNavEngineInternals test hook');

  // The band-aid's entire point: drop from 3 tiers to 2. If the TTM
  // redesign lands and replaces the distance-threshold model entirely,
  // this test goes away with it. If someone instead re-adds a medium
  // tier without the redesign, this test fails and forces a conversation.
  const t = internals.VOICE_THRESHOLDS;
  assert.equal(t.auto.length, 2, 'auto costing: expected [far, near] 2-tier shape');
  assert.equal(t.bicycle.length, 2, 'bicycle costing: expected [far, near] 2-tier shape');
  assert.equal(t.pedestrian.length, 2, 'pedestrian costing: expected [far, near] 2-tier shape');

  // Floor guards: the band-aid's "far" tier exists so the driver has
  // meaningful advance notice. Tuning below ~300m for auto would leave
  // <15s of notice at highway speed, making the tier useless.
  assert.ok(t.auto[0] >= 300, 'auto far tier: must retain >=300m for advance notice');
  // "Near" is the execution tier — must stay >= 20m so the driver has
  // physical time to complete the turn after hearing it.
  assert.ok(t.auto[1] >= 20, 'auto near tier: must retain >=20m for execution');

  // Tier ordering must be descending (far > near).
  assert.ok(t.auto[0] > t.auto[1]);
  assert.ok(t.bicycle[0] > t.bicycle[1]);
  assert.ok(t.pedestrian[0] > t.pedestrian[1]);
});

test('TTM constants have expected shape and per-costing keys', async () => {
  const { window: win } = await loadEngine();
  const i = win._geographicaNavEngineInternals;
  assert.ok(i, 'internals hook must exist');

  // Check VOICE_TTM shape and values
  assert.ok(Array.isArray(i.VOICE_TTM.auto) && i.VOICE_TTM.auto.length === 2);
  assert.equal(i.VOICE_TTM.auto[0], 30);
  assert.equal(i.VOICE_TTM.auto[1], 3);

  assert.ok(Array.isArray(i.VOICE_TTM.bicycle) && i.VOICE_TTM.bicycle.length === 2);
  assert.equal(i.VOICE_TTM.bicycle[0], 20);
  assert.equal(i.VOICE_TTM.bicycle[1], 3);

  assert.ok(Array.isArray(i.VOICE_TTM.pedestrian) && i.VOICE_TTM.pedestrian.length === 2);
  assert.equal(i.VOICE_TTM.pedestrian[0], 15);
  assert.equal(i.VOICE_TTM.pedestrian[1], 2);

  // Check VOICE_DISTANCE_FLOOR values
  assert.equal(i.VOICE_DISTANCE_FLOOR.auto, 50);
  assert.equal(i.VOICE_DISTANCE_FLOOR.bicycle, 30);
  assert.equal(i.VOICE_DISTANCE_FLOOR.pedestrian, 15);

  // Check speed model constants
  assert.equal(i.MIN_SPEED_FLOOR, 1.0);
  assert.equal(i.SPEED_WINDOW_SIZE, 3);
  assert.equal(i.MAX_SPEED_DELTA_PER_TICK, 15);

  // Costing keys must match across VOICE_TTM and VOICE_DISTANCE_FLOOR (lint).
  const ttmKeys = Object.keys(i.VOICE_TTM).sort();
  const floorKeys = Object.keys(i.VOICE_DISTANCE_FLOOR).sort();
  assert.deepStrictEqual(ttmKeys, floorKeys,
    'VOICE_TTM and VOICE_DISTANCE_FLOOR must have identical costing keys');
});

test('pushSpeedSample: updateGPS populates speedSamples', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };
  nav.start(fixtureRouteWithTwoTurns());

  const i = win._geographicaNavEngineInternals;
  assert.equal(typeof i._getSpeedSamples, 'function',
    '_getSpeedSamples hook required for speed-window tests');

  nav.updateGPS({ latitude: 35.20, longitude: -111.649, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.648, heading: 90, speed: 11 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.647, heading: 90, speed: 12 });

  const samples = i._getSpeedSamples();
  assert.deepEqual(samples, [10, 11, 12],
    'speedSamples should contain the three post-start speeds in order');
});

test('pushSpeedSample: window size is capped at SPEED_WINDOW_SIZE (3)', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 5 };
  nav.start(fixtureRouteWithTwoTurns());
  const i = win._geographicaNavEngineInternals;

  for (let k = 0; k < 10; k++) {
    nav.updateGPS({
      latitude: 35.20, longitude: -111.65 + k * 0.0001,
      heading: 90, speed: 8 + k,
    });
  }
  assert.equal(i._getSpeedSamples().length, 3,
    'speedSamples must be bounded at SPEED_WINDOW_SIZE=3');
  assert.deepEqual(i._getSpeedSamples(), [15, 16, 17],
    'speedSamples must keep the most recent 3 accepted samples');
});

test('pushSpeedSample: physically-implausible delta is rejected (outlier clamp)', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };
  nav.start(fixtureRouteWithTwoTurns());
  const i = win._geographicaNavEngineInternals;

  // Seed window with two legitimate samples.
  nav.updateGPS({ latitude: 35.20, longitude: -111.649, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.648, heading: 90, speed: 10 });
  // Inject a 50 m/s outlier: delta = |50 - 10| = 40 > MAX_SPEED_DELTA_PER_TICK(15) → rejected.
  nav.updateGPS({ latitude: 35.20, longitude: -111.647, heading: 90, speed: 50 });
  // Inject a 10 m/s-delta sample (within threshold) → accepted.
  nav.updateGPS({ latitude: 35.20, longitude: -111.646, heading: 90, speed: 20 });

  const samples = i._getSpeedSamples();
  assert.ok(!samples.includes(50),
    'outlier 50 m/s must be rejected — delta from prior median exceeded 15 m/s');
  assert.ok(samples.includes(20),
    'legitimate delta <=15 m/s must be accepted');
});

test('pushSpeedSample: negative and NaN samples are sanitized to 0', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 0 };
  nav.start(fixtureRouteWithTwoTurns());
  const i = win._geographicaNavEngineInternals;

  nav.updateGPS({ latitude: 35.20, longitude: -111.649, heading: 90, speed: -5 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.648, heading: 90, speed: NaN });
  nav.updateGPS({ latitude: 35.20, longitude: -111.647, heading: 90, speed: 1 });

  const samples = i._getSpeedSamples();
  assert.ok(!samples.some(s => s < 0 || Number.isNaN(s)),
    'negative and NaN samples must be sanitized');
});

test('speedMedian: returns MIN_SPEED_FLOOR when window is empty', async () => {
  const { window: win } = await loadEngine();
  const i = win._geographicaNavEngineInternals;
  assert.equal(typeof i._speedMedian, 'function',
    '_speedMedian hook required for median tests');
  assert.equal(i._speedMedian(), i.MIN_SPEED_FLOOR);
});
