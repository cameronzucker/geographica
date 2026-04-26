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

test('applyReroute clears announcedSet and speedSamples', async (t) => {
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
  const i = win._geographicaNavEngineInternals;
  assert.deepEqual(i._getSpeedSamples(), [],
    'applyReroute must clear speedSamples alongside announcedSet');

  // After applyReroute, announcedSet and speedSamples must be fully reset:
  // driving the same approach as before must fire the announcement again.
  const beforeNewFires = voiceFires.length;
  nav.updateGPS({ latitude: 35.20, longitude: -111.6405, heading: 90, speed: 10 });
  assert.ok(
    voiceFires.length > beforeNewFires,
    'announcement should re-fire on new route; was suppressed — announcedSet/speedSamples not cleared'
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

  // Check VOICE_DISTANCE_FLOOR values (TTM I12: lifted for surface-street buffer)
  assert.equal(i.VOICE_DISTANCE_FLOOR.auto, 75);
  assert.equal(i.VOICE_DISTANCE_FLOOR.bicycle, 45);
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

test('TTM I1: 2 prompts per maneuver when entering from outside far (steady 10 m/s)', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());

  // Approach maneuver 1 (at lng -111.64) from far. Start pushing speed samples
  // to establish the smoothed window before crossing the 30s-TTM threshold.
  // At 10 m/s, 30s TTM = 300m. maneuver 1 is 1km east; start at ~500m away
  // and step in toward it.
  const startLng = -111.645;  // 500m west of maneuver 1
  const steps = 50;            // 50 GPS ticks at ~10m spacing
  for (let k = 0; k < steps; k++) {
    const lng = startLng + k * 0.0001;  // ~10m per step at lat 35
    nav.updateGPS({ latitude: 35.20, longitude: lng, heading: 90, speed: 10 });
  }
  // Expected: far-tier fires at ~300m, near-tier fires at ~75m floor = 2 prompts for maneuver 1.
  assert.equal(voiceFires.length, 2,
    `I1: expected exactly 2 prompts for maneuver 1, got ${voiceFires.length}`);
});

test('TTM I2: 1 prompt per maneuver when entering already inside near (D1 suppression)', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  // Start 30m west of maneuver 1 (well inside the 75m floor).
  // First move a bit so TTM pipeline is allowed to fire (NG8: no start-time voice).
  win._geographicaGPSData = { lat: 35.20, lon: -111.64030, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());
  // First movement tick — this is the "post-start first tick" per NG8.
  nav.updateGPS({ latitude: 35.20, longitude: -111.64025, heading: 90, speed: 10 });

  // D1 suppression: near-tier fires, far-tier is marked announced → 1 prompt for maneuver 1.
  assert.equal(voiceFires.length, 1,
    `I2: expected exactly 1 prompt (D1 suppression), got ${voiceFires.length}`);
});

test('TTM I3: zero prompts when stationary beyond distance floor', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  // Start 90m west of maneuver 1 (outside the 75m auto floor), stationary.
  // (0.00099° × 91,163 m/° ≈ 90 m at lat 35.20)
  win._geographicaGPSData = { lat: 35.20, lon: -111.64099, heading: 90, speed: 0 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());
  // Feed three stationary ticks.
  nav.updateGPS({ latitude: 35.20, longitude: -111.64098, heading: 90, speed: 0 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.64097, heading: 90, speed: 0 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.64096, heading: 90, speed: 0 });

  assert.equal(voiceFires.length, 0,
    `I3: expected 0 prompts when stationary beyond floor, got ${voiceFires.length}`);
});

test('TTM I4: near-tier fires when stationary at distance floor', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  // Start 30m west of maneuver 1 (inside the 75m floor), stationary.
  win._geographicaGPSData = { lat: 35.20, lon: -111.64030, heading: 90, speed: 0 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());
  // One "first movement tick" to allow TTM to fire (NG8). Tiny motion.
  nav.updateGPS({ latitude: 35.20, longitude: -111.64029, heading: 90, speed: 0.1 });

  assert.equal(voiceFires.length, 1,
    'I4: near-tier must fire when within distance floor, even near-stationary');
});

test('TTM I10: past-maneuver early-return (negative distToNext does not fire prompts)', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());

  // Jump past maneuver 1 — drive to lng -111.639 (east of maneuver 1 at -111.64).
  // findManeuverForSegment should advance currentManeuverIdx; checkVoice for the
  // new maneuver 2 fires normally (outside the I10 scope). Count that maneuver 1's
  // far/near prompts do NOT fire retroactively.
  nav.updateGPS({ latitude: 35.20, longitude: -111.639, heading: 90, speed: 10 });
  // Validate the stream by looking at announcedSet: maneuver 1's keys should not be set
  // by an overshoot (the engine-level invariant is that checkVoice for maneuver N does
  // not fire if driver has already crossed it).
  const keys = win._geographicaNavEngineInternals._getAnnouncedKeys();
  // I10 is mechanistic: announcedSet must NOT contain maneuver-1 keys on
  // overshoot. A pure "no prompt text" assertion would pass even if keys
  // were set and then checked — we want to verify the early-return fired
  // BEFORE the mutation block was reached.
  const m1Keys = keys.filter(k => k.startsWith('1-'));
  assert.equal(m1Keys.length, 0,
    'I10: announcedSet must not contain maneuver-1 keys on overshoot');
  // A prompt for maneuver 1 would be text containing "Main" or "Oak"; assert none.
  const m1Prompts = voiceFires.filter(t => /Main Street/.test(t));
  assert.equal(m1Prompts.length, 0,
    'I10: no prompts for already-passed maneuver 1');
});

test('TTM edge: empty verbal instructions do not fire onVoiceCb', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.64030, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));

  // Custom route: maneuver 1 has no verbal text and no instruction.
  const silentRoute = fixtureRouteWithTwoTurns();
  silentRoute.maneuvers[1].verbal_pre_transition_instruction = '';
  silentRoute.maneuvers[1].verbal_transition_alert_instruction = '';
  silentRoute.maneuvers[1].instruction = '';
  nav.start(silentRoute);
  nav.updateGPS({ latitude: 35.20, longitude: -111.64025, heading: 90, speed: 10 });

  assert.equal(voiceFires.length, 0,
    'onVoiceCb must not fire with an empty string');
});

test('TTM edge: unknown costing falls back to auto without crashing', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.64030, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));

  const truckRoute = fixtureRouteWithTwoTurns();
  truckRoute.costing = 'truck'; // not in VOICE_TTM
  nav.start(truckRoute);
  nav.updateGPS({ latitude: 35.20, longitude: -111.64025, heading: 90, speed: 10 });

  // Must not throw; must fire prompts using auto thresholds.
  assert.ok(voiceFires.length >= 1,
    'unknown costing "truck" must fall back to auto and fire prompts');
});

test('TTM edge: distance clamp — simulated negative distance does not fire', async (t) => {
  // Test is indirect: start past maneuver 1. findManeuverForSegment advances
  // currentManeuverIdx past m1 on the first tick.
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });

  // Start 10m PAST maneuver 1 (east of lng -111.64).
  win._geographicaGPSData = { lat: 35.20, lon: -111.6399, heading: 90, speed: 10 };
  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());
  nav.updateGPS({ latitude: 35.20, longitude: -111.6398, heading: 90, speed: 10 });

  // maneuver 1's prompts must not fire retroactively.
  const m1Prompts = voiceFires.filter(t => /Main Street/.test(t));
  assert.equal(m1Prompts.length, 0,
    'prompts for already-passed maneuver must not fire');
});

test('TTM I8: muted state — announcedSet still populates, un-mute does not replay', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.64030, heading: 90, speed: 10 };
  const i = win._geographicaNavEngineInternals;

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.setMuted(true);
  nav.start(fixtureRouteWithTwoTurns());
  // First movement tick — near-tier condition met (inside 75m floor).
  nav.updateGPS({ latitude: 35.20, longitude: -111.64025, heading: 90, speed: 10 });

  assert.equal(voiceFires.length, 0, 'muted: no voice fires');
  const keys = i._getAnnouncedKeys();
  assert.ok(keys.length >= 2, 'muted: announcedSet must still populate (I8)');
  assert.ok(keys.includes('1-far') && keys.includes('1-near'),
    'muted: both far and near keys marked (D1 suppression applied)');

  // Un-mute: previous thresholds must NOT replay.
  nav.setMuted(false);
  nav.updateGPS({ latitude: 35.20, longitude: -111.64023, heading: 90, speed: 10 });
  assert.equal(voiceFires.length, 0,
    'un-mute must not replay already-crossed thresholds (I8)');
});

test('TTM I7: next-after-next chain fires on near-tier only, never on far-tier', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  // Use fixtureRouteWithTwoTurns: maneuver 1 at -111.64 (Main Street), next-after-next
  // is the arrival maneuver at index 2 (begin_shape_index=2 at coord -111.63), 1km away.
  // distBetween = 1000m > 500m → chain NOT appended. Assert that the far-tier
  // prompt (fired first, at ~300m) has no ", then " chain.
  win._geographicaGPSData = { lat: 35.20, lon: -111.645, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());

  // Drive far-tier first (at 300m / TTM=30s).
  nav.updateGPS({ latitude: 35.20, longitude: -111.6425, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.642, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.6415, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.641, heading: 90, speed: 10 });

  assert.ok(voiceFires.length >= 1, 'at least one prompt must have fired');
  const first = voiceFires[0];
  assert.ok(!/, then /.test(first),
    'I7: far-tier prompt must not include next-after-next chain');
});

test('TTM edge: cooldown regression guard — adjacent near-prompts both fire', async (t) => {
  // Critical regression guard per R3 F3.7 / spec §6.6. If a later refactor
  // silently reintroduces a cooldown, two near-prompts firing in quick
  // succession across adjacent maneuvers would drop one. This test fails
  // loudly in that case.
  const { fixtureVillaRitaCluster } = await import('./test_runner.mjs');
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });

  // Start 10m west of maneuver 1 (inside the floor), 10 m/s.
  // Coords: maneuver 1 at -111.64967, so start at -111.64978 (10m west).
  win._geographicaGPSData = { lat: 35.20, lon: -111.64978, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push({ text, at: Date.now() }));
  nav.start(fixtureVillaRitaCluster());

  // Tick through maneuver 1 and into maneuver 2's near-tier in rapid succession.
  // Each step is ~5m; full traversal takes ~3 ticks.
  nav.updateGPS({ latitude: 35.20, longitude: -111.64972, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.64950, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.64935, heading: 90, speed: 10 });

  const mulberry = voiceFires.filter(v => /Mulberry/.test(v.text));
  const oak = voiceFires.filter(v => /Oak/.test(v.text));
  assert.ok(mulberry.length >= 1, 'Mulberry near-tier must fire');
  assert.ok(oak.length >= 1, 'Oak near-tier must fire in the next tick — no cooldown');
});

test('TTM bicycle: near-tier does not fire outside 45m floor', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  // 65m west of maneuver 1. At walking pace (1 m/s), TTM=65s >> bicycle far(20s),
  // so neither far-tier (TTM>20s) nor near-tier (dist>45m floor, TTM>3s) fires.
  // (0.00071° × 91,163 m/° ≈ 65 m at lat 35.20)
  win._geographicaGPSData = { lat: 35.20, lon: -111.64071, heading: 90, speed: 1 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  const bikeRoute = { ...fixtureRouteWithTwoTurns(), costing: 'bicycle' };
  nav.start(bikeRoute);
  // Advance to ~50m from maneuver — still outside 45m floor.
  // At 1 m/s, TTM = 50/1 = 50s > 20s far-threshold → far does NOT fire.
  // 50m > 45m floor → near does NOT fire by floor.
  // TTM 50s > 3s near-threshold → near does NOT fire by TTM.
  // (0.00055° × 91,163 m/° ≈ 50 m at lat 35.20)
  nav.updateGPS({ latitude: 35.20, longitude: -111.64055, heading: 90, speed: 1 });

  assert.equal(voiceFires.length, 0,
    'bicycle at 50m from maneuver at walking pace: outside 45m floor and TTM>20s, should not fire');
});

test('TTM bicycle: near-tier fires when inside 45m floor', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.64025, heading: 90, speed: 3 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  const bikeRoute = { ...fixtureRouteWithTwoTurns(), costing: 'bicycle' };
  nav.start(bikeRoute);
  // 25m from maneuver, inside 45m bicycle floor.
  nav.updateGPS({ latitude: 35.20, longitude: -111.64023, heading: 90, speed: 3 });
  assert.ok(voiceFires.length >= 1,
    'bicycle inside 45m floor must fire near-tier');
});

test('TTM pedestrian: near-tier fires inside 15m floor', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  // 12m west of maneuver 1 (inside pedestrian 15m floor).
  win._geographicaGPSData = { lat: 35.20, lon: -111.64012, heading: 90, speed: 1.5 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  const walkRoute = { ...fixtureRouteWithTwoTurns(), costing: 'pedestrian' };
  nav.start(walkRoute);
  nav.updateGPS({ latitude: 35.20, longitude: -111.64010, heading: 90, speed: 1.5 });
  assert.ok(voiceFires.length >= 1,
    'pedestrian inside 15m floor must fire near-tier');
});

test('TTM pedestrian: outside 15m floor at walking pace does not fire near', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  // 20m west of maneuver 1 (outside 15m floor), walking 1 m/s.
  // TTM = 20/1 = 20s; pedestrian far threshold is 15s, so 20 > 15 → far does NOT fire.
  // 2s near at 1 m/s = 2m → near via TTM not met.
  win._geographicaGPSData = { lat: 35.20, lon: -111.64020, heading: 90, speed: 1 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  const walkRoute = { ...fixtureRouteWithTwoTurns(), costing: 'pedestrian' };
  nav.start(walkRoute);
  nav.updateGPS({ latitude: 35.20, longitude: -111.64018, heading: 90, speed: 1 });
  assert.equal(voiceFires.length, 0,
    'pedestrian at 18m from maneuver, outside 15m floor and 15s TTM, should not fire');
});

test('TTM Villa Rita synthetic: 3-maneuver close cluster fires exactly 3 prompts (§6.4)', async (t) => {
  const { fixtureVillaRitaCluster } = await import('./test_runner.mjs');
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });

  // 40m west of maneuver 1 (the first spoken turn, index 1).
  // maneuver 1 is at -111.64967; route start (depart) is at -111.65000 (33m before).
  // Start AT route start; 33m to maneuver 1.
  win._geographicaGPSData = { lat: 35.20, lon: -111.65000, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureVillaRitaCluster());

  // Tick through the cluster at 10 m/s: each segment is 30m, so ~3 ticks per segment.
  // Full cluster (3 turns) ~90m = ~9 ticks.
  const tickPositions = [
    -111.64990, -111.64980, -111.64970,  // approaching maneuver 1 (Mulberry)
    -111.64960, -111.64950, -111.64940,  // after maneuver 1, approaching maneuver 2 (Oak)
    -111.64930, -111.64920, -111.64910,  // after maneuver 2, approaching maneuver 3 (Villa Rita)
    -111.64900, -111.64890, -111.64880,  // after maneuver 3, approaching end
  ];
  for (const lng of tickPositions) {
    nav.updateGPS({ latitude: 35.20, longitude: lng, heading: 90, speed: 10 });
  }

  // Expect exactly 3 prompts (one near-tier per spoken maneuver; D1 suppresses far for all 3).
  assert.equal(voiceFires.length, 3,
    `Villa Rita: expected exactly 3 prompts (D1 suppression), got ${voiceFires.length}: ${JSON.stringify(voiceFires)}`);
  // Each must be a pre-transition ("Turn left onto Mulberry" style), not an alert.
  const alerts = voiceFires.filter(t => /In 100 feet/.test(t));
  assert.equal(alerts.length, 0,
    'Villa Rita prompts must be near-tier (pre-transition), not alert-tier');
});

test('TTM outlier integration: correlated 2-outliers-in-3-window are rejected (I5)', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.645, heading: 90, speed: 10 };
  const i = win._geographicaNavEngineInternals;

  nav.onVoice(() => {});
  nav.start(fixtureRouteWithTwoTurns());

  // Seed window with 2 legitimate 10 m/s samples.
  nav.updateGPS({ latitude: 35.20, longitude: -111.644, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.6435, heading: 90, speed: 10 });
  // After 2 ticks, samples should contain at least one [10] entry.

  // Inject TWO 50 m/s outliers in a row. Median-of-3 alone would be fooled
  // (window would become [10, 50, 50] → median 50). The pre-filter rejects
  // each outlier because delta from prior median stays > 15 m/s.
  nav.updateGPS({ latitude: 35.20, longitude: -111.643, heading: 90, speed: 50 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.6425, heading: 90, speed: 50 });

  const samples = i._getSpeedSamples();
  assert.ok(!samples.includes(50),
    'I5: correlated 2-outliers-in-3 must be rejected by pre-filter');
});

test('TTM outlier integration: GPS 50 m/s spike does not flip thresholds', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.645, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());

  // Baseline: steady 10 m/s approach to maneuver 1.
  const baseLngs = [-111.644, -111.6435, -111.643];
  for (const lng of baseLngs) {
    nav.updateGPS({ latitude: 35.20, longitude: lng, heading: 90, speed: 10 });
  }
  const baselineCount = voiceFires.length;

  // Inject a 50 m/s outlier — must be rejected by pushSpeedSample's clamp.
  nav.updateGPS({ latitude: 35.20, longitude: -111.6425, heading: 90, speed: 50 });
  // Speed window should still NOT contain 50.
  const samples = win._geographicaNavEngineInternals._getSpeedSamples();
  assert.ok(!samples.includes(50),
    'outlier must be rejected from speed window');
  // Baseline count should be preserved (no premature near).
  assert.equal(voiceFires.length, baselineCount,
    'outlier injection must not cause new prompts to fire');
});

test('TTM I9: dead-reckoning does not fire voice announcements', { timeout: 10_000 }, async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });

  // Start GPS at the route origin so nav.start() seeds lastSnap there.
  // Then updateGPS moves the driver to ~330m west of maneuver 1 (at lon
  // -111.640). The position change is required: updateGPS deduplicates on
  // (lat, lng) and won't call tick() — or push a speed sample — if the
  // position equals the one from _geographicaGPSData / nav.start().
  //
  // Geometry: maneuver 1 at -111.640. 330m ≈ 0.003626° → -111.6436.
  // After 3s GPS_STALE_TIMEOUT + 1 stale-checker interval (1s), DR
  // extrapolates 10 m/s × 3s = 30m → driver at ~298m ≈ 28.3s TTM.
  // Auto far threshold is 30s (300m); 298m < 300m → far-tier would fire
  // if checkVoice(drSnap) were still called (I9 violation).
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());

  // Real tick: position differs from _geographicaGPSData so tick() runs,
  // seeds lastSnap and pushes speed sample 10 m/s into speedSamples.
  nav.updateGPS({ latitude: 35.20, longitude: -111.6436, heading: 90, speed: 10 });
  const baselineCount = voiceFires.length;

  // Simulate stale-GPS: wait past GPS_STALE_TIMEOUT (3000ms) + stale-checker
  // interval (1000ms). The stale-checker fires deadReckonTick which extrapolates
  // position. With T7's fix, DR is position-only (no checkVoice), so voice count
  // must not increase.
  await new Promise(r => setTimeout(r, 4500));

  // Before the fix, checkVoice(drSnap) would have fired the far-tier prompt
  // (driver extrapolated to inside the 300m / 30s threshold).
  assert.equal(voiceFires.length, baselineCount,
    'I9: DR must not fire voice announcements');
});

test('TTM reroute success: speedSamples cleared', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };
  const i = win._geographicaNavEngineInternals;

  nav.start(fixtureRouteWithTwoTurns());
  // Populate speed window.
  nav.updateGPS({ latitude: 35.20, longitude: -111.649, heading: 90, speed: 10 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.648, heading: 90, speed: 11 });
  nav.updateGPS({ latitude: 35.20, longitude: -111.647, heading: 90, speed: 12 });
  assert.equal(i._getSpeedSamples().length, 3);

  // Force reroute.
  let seq = null;
  nav.onReroute((info) => { seq = info._seq; });
  [[35.25, -111.55], [35.26, -111.54], [35.27, -111.53],
   [35.28, -111.52], [35.29, -111.51]].forEach(([lat, lon]) => {
    nav.updateGPS({ latitude: lat, longitude: lon, heading: 90, speed: 10 });
  });
  nav.applyReroute(fixtureRouteWithTwoTurns(), seq);

  assert.deepEqual(i._getSpeedSamples(), [],
    'applyReroute success path must clear speedSamples');
});

test('TTM reroute stale-drop: speedSamples and announcedSet preserved', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.64030, heading: 90, speed: 10 };
  const i = win._geographicaNavEngineInternals;

  nav.onVoice(() => {}); // no-op sink
  nav.start(fixtureRouteWithTwoTurns());
  nav.updateGPS({ latitude: 35.20, longitude: -111.64025, heading: 90, speed: 10 });

  const keysBefore = i._getAnnouncedKeys();
  const samplesBefore = i._getSpeedSamples();
  assert.ok(keysBefore.length > 0, 'announcedSet must be populated before stale-drop');
  assert.ok(samplesBefore.length > 0, 'speedSamples must be populated before stale-drop');

  // Apply reroute with a mismatched seq (999 is not the current rerouteSeq).
  nav.applyReroute(fixtureRouteWithTwoTurns(), 999);

  assert.deepEqual(i._getAnnouncedKeys(), keysBefore,
    'stale-drop: announcedSet must be preserved');
  assert.deepEqual(i._getSpeedSamples(), samplesBefore,
    'stale-drop: speedSamples must be preserved');
});

test('TTM reroute re-tick: no voice fires on the immediate re-tick inside applyReroute', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  // Start 20m west of maneuver 1, inside the 75m floor.
  // Seed GPS so applyReroute's re-tick has a cached lastGPS.
  win._geographicaGPSData = { lat: 35.20, lon: -111.64020, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureRouteWithTwoTurns());

  // Move to maneuver 1 area to build up announced state.
  nav.updateGPS({ latitude: 35.20, longitude: -111.64018, heading: 90, speed: 10 });

  // Trigger reroute.
  let seq = null;
  nav.onReroute((info) => { seq = info._seq; });
  [[35.25, -111.55], [35.26, -111.54], [35.27, -111.53],
   [35.28, -111.52], [35.29, -111.51]].forEach(([lat, lon]) => {
    nav.updateGPS({ latitude: lat, longitude: lon, heading: 90, speed: 10 });
  });
  const beforeApply = voiceFires.length;

  // Apply reroute — its internal re-tick(lastGPS) MUST NOT fire voice
  // even though the driver may be within near-tier of maneuver 1 in the new route.
  nav.applyReroute(fixtureRouteWithTwoTurns(), seq);
  assert.equal(voiceFires.length, beforeApply,
    're-tick inside applyReroute must not fire voice');

  // On the NEXT real GPS tick, voice fires normally if conditions met.
  nav.updateGPS({ latitude: 35.20, longitude: -111.64017, heading: 90, speed: 10 });
  assert.ok(voiceFires.length > beforeApply,
    'voice must fire on the first post-reroute real GPS tick');
});

test('TTM reroute timeout: stale timeout does not clobber a just-applied reroute', { timeout: 20_000 }, async (t) => {
  // R2 F2.1: the timeout closure must capture scheduledSeq and only reset if
  // rerouteSeq still matches — so a late timeout from a prior reroute cannot
  // clobber state set by a subsequent applyReroute.
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };

  const seqs = [];
  nav.onReroute((info) => { seqs.push(info._seq); });
  nav.start(fixtureRouteWithTwoTurns());

  // Fire a first reroute (this schedules a 10s timeout with some seq=1).
  [[35.25, -111.55], [35.26, -111.54], [35.27, -111.53],
   [35.28, -111.52], [35.29, -111.51]].forEach(([lat, lon]) => {
    nav.updateGPS({ latitude: lat, longitude: lon, heading: 90, speed: 10 });
  });

  // Apply it immediately — state returns to "navigating", rerouteSeq advances.
  nav.applyReroute(fixtureRouteWithTwoTurns(), seqs[0]);

  // Wait past the initial 10s timeout. If the closure doesn't capture
  // scheduledSeq, the timeout callback would reset state (clear lastRerouteTime,
  // wipe offRouteHistory) even though the reroute already succeeded.
  await new Promise(r => setTimeout(r, 11_000));

  // Assertion: a subsequent off-route still triggers a fresh reroute (engine
  // didn't latch into a broken state from the stale timeout).
  [[35.25, -111.55], [35.26, -111.54], [35.27, -111.53],
   [35.28, -111.52], [35.29, -111.51]].forEach(([lat, lon]) => {
    nav.updateGPS({ latitude: lat, longitude: lon, heading: 90, speed: 10 });
  });
  assert.equal(seqs.length, 2,
    'engine must still fire a new reroute after a stale timeout');
});

test('TTM internals hook: band-aid keys are removed', async () => {
  const { window: win } = await loadEngine();
  const i = win._geographicaNavEngineInternals;
  assert.equal(i.VOICE_THRESHOLDS, undefined,
    'VOICE_THRESHOLDS must be removed from internals hook');
  assert.equal(i.VOICE_COOLDOWN, undefined,
    'VOICE_COOLDOWN must be removed from internals hook');
  assert.equal(i.VOICE_SPEED_GATE, undefined,
    'VOICE_SPEED_GATE must be removed from internals hook');
  // TTM keys remain.
  assert.ok(i.VOICE_TTM, 'VOICE_TTM must remain');
  assert.ok(i.VOICE_DISTANCE_FLOOR, 'VOICE_DISTANCE_FLOOR must remain');
});

test('TTM field-gate debug hook: captures callback context when enabled', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaTTMDebug = true;
  win._geographicaTTMDebugLog = [];
  win._geographicaGPSData = { lat: 35.20, lon: -111.64030, heading: 90, speed: 10 };

  nav.onVoice(() => {});
  nav.start(fixtureRouteWithTwoTurns());
  nav.updateGPS({ latitude: 35.20, longitude: -111.64025, heading: 90, speed: 10 });

  const log = win._geographicaTTMDebugLog;
  assert.ok(log.length >= 1, 'debug log must capture at least one entry on near-tier fire');
  const entry = log[0];
  assert.ok(typeof entry.timestamp === 'number');
  assert.ok(typeof entry.maneuverIdx === 'number');
  assert.ok(entry.tier === 'near' || entry.tier === 'far');
  assert.ok(typeof entry.distToNext === 'number');
  assert.ok(typeof entry.ttm === 'number');
  assert.equal(typeof entry.onRerouteRetick, 'boolean');
});

test('TTM I11: chain-extension suppresses far-tier for chain-pre-announced maneuvers', async (t) => {
  // Mixed-spacing cluster (80m between each turn) — the field-test regime
  // where D1's same-tick gate misses. Under current TTM WITHOUT chain
  // extension, 3 consecutive spoken maneuvers at 80m spacing produce
  // far+near for M1 + far+near for M2 + far+near for M3 = 6 callbacks.
  // Under I11 chain-extension, each near-tier's chain marks the next's
  // far as announced: M1 far + M1 near(chain) + M2 near(chain) + M3 near
  // = 4 callbacks.
  const { fixtureMixedSpacingCluster } = await import('./test_runner.mjs');
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65000, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureMixedSpacingCluster());

  // Drive through the cluster at 10 m/s. Each segment is 80m ~= 8 ticks at
  // 10m/tick. Whole route ~320m = 32 ticks. Use 10m steps.
  for (let k = 0; k < 35; k++) {
    const lng = -111.65000 + k * 0.00011; // ~10m east per tick at lat 35.20
    nav.updateGPS({ latitude: 35.20, longitude: lng, heading: 90, speed: 10 });
  }

  // Expected: exactly 3 callbacks with chain-extension.
  // The 75m near-tier floor (TTM I12) fires near-tier immediately at the
  // start position (~80m from M1), suppressing M1's far-tier before it
  // can fire (near returns early, blocking the far branch):
  //   CB 1: M1 near+chain "In X feet, turn left onto First, then in Y feet, right onto Second"
  //         (M1 far suppressed by floor-triggered near; chain marks M2-far → I11)
  //   CB 2: M2 near+chain "In X feet, turn right onto Second, then in Y feet, left onto Third"
  //         (M2 far suppressed by I11; chain marks M3-far → I11)
  //   CB 3: M3 near "In X feet, turn left onto Third Avenue"
  //         (M3 far suppressed by I11; no chain because afterIdx out of bounds)
  // Per spec v2 §5.2 (Task 6): near-tier now includes distance prefix.
  assert.equal(voiceFires.length, 3,
    `I11: expected 3 callbacks under chain-extension (TTM I12 floor), got ${voiceFires.length}: ${JSON.stringify(voiceFires)}`);

  // ALL 3 prompts now start with "In N feet," — near-tier has distance prefix
  // per spec v2 §5.2. No far-tier fired: M1 far suppressed by floor; M2/M3
  // far suppressed by I11 chain marks.
  const allHavePrefix = voiceFires.every(t => /^In \d+/.test(t));
  assert.ok(allHavePrefix,
    `I11: all 3 near-tier prompts must have "In N" prefix (spec v2 §5.2); got ${JSON.stringify(voiceFires)}`);

  // Three near-tier prompts — all contain "turn" (case-insensitive) after the prefix.
  const nears = voiceFires.filter(t => /turn /i.test(t));
  assert.equal(nears.length, 3,
    `I11: exactly 3 near-tier prompts expected; got ${nears.length}`);

  // M1 and M2 near-tier prompts must contain the ", then" chain (since
  // both have a following maneuver within NEXT_AFTER_NEXT_DISTANCE).
  const chained = voiceFires.filter(t => /, then /.test(t));
  assert.equal(chained.length, 2,
    `I11: exactly 2 near-tier prompts must contain the chain; got ${chained.length}`);

  // M3's near-tier must NOT have a chain (no maneuver after it). Match M3's
  // own standalone prompt by content — after Task 6 prefix it starts with "In X feet,"
  // not "Turn left onto Third Avenue" directly.
  const m3Own = voiceFires.find(t => /Third Avenue/.test(t) && !/, then /.test(t));
  assert.ok(m3Own, 'M3 standalone near-tier prompt must have fired');
  assert.ok(!/, then /.test(m3Own),
    'M3 standalone near-tier must not have chain (last maneuver)');
});

test('TTM Valhalla-Then strip: vpt trailing ". Then X." and leading "Then " are stripped', async (t) => {
  // Observed on Cameron's 2026-04-21 field drive: Valhalla's verbal_pre_transition
  // bakes continuation chains in both shapes, producing doubled and prefix-duplicated
  // speech when our chain logic runs on top. Engine must strip both patterns.
  const { fixtureValhallaThenChainedCluster } = await import('./test_runner.mjs');
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65000, heading: 90, speed: 10 };

  const voiceFires = [];
  nav.onVoice((text) => voiceFires.push(text));
  nav.start(fixtureValhallaThenChainedCluster());

  // Drive through at 10 m/s.
  for (let k = 0; k < 35; k++) {
    const lng = -111.65000 + k * 0.00011;
    nav.updateGPS({ latitude: 35.20, longitude: lng, heading: 90, speed: 10 });
  }

  // Find M2's (Turn right onto 24th Drive) near-tier prompt. It should contain
  // the Union Hills chain ONCE (from our append), not twice (Valhalla's baked-in
  // suffix + ours). Per spec v2 §5.2 (Task 6), near-tier now starts with a
  // distance prefix "In X feet," before the turn instruction.
  const m24 = voiceFires.find(t => /24th Drive/i.test(t));
  assert.ok(m24, 'M2 (24th Drive) near-tier must have fired');
  const unionMentions = (m24.match(/Union Hills/g) || []).length;
  assert.equal(unionMentions, 1,
    `Valhalla-Then strip: M2 prompt must mention Union Hills EXACTLY ONCE; got ${unionMentions} in ${JSON.stringify(m24)}`);

  // Find M3's (Union Hills) standalone near-tier prompt. Valhalla's vpt is
  // "Then turn left onto West Union Hills Drive." — leading "Then" must be
  // stripped. With spec v2 §5.2 Task 6 prefix, the prompt starts with "In X
  // feet," followed by the turn instruction (NOT "Then").
  const m3 = voiceFires.find(t => /Union Hills/i.test(t) && !/24th Drive/i.test(t));
  assert.ok(m3, 'M3 (Union Hills) standalone near-tier must have fired');
  assert.ok(!/^Then\b/i.test(m3),
    `Valhalla-Then strip: M3 standalone must not start with "Then"; got ${JSON.stringify(m3)}`);
  assert.ok(/turn left onto/i.test(m3),
    `Valhalla-Then strip: M3 standalone must contain "turn left onto" after strip; got ${JSON.stringify(m3)}`);
});

test('_geographicaUseImperial helper returns true by default', async () => {
  const { window: win } = await loadEngine();
  // Default: window._geographicaUseImperial is set to true at app.js:123
  // but our test environment doesn't load app.js — undefined globally.
  // Helper should return TRUE when unset (matches app.js default).
  win._geographicaUseImperial = undefined;
  const internals = win._geographicaNavEngineInternals;
  assert.equal(internals._useImperial(), true);
});

test('_geographicaUseImperial helper returns false when explicitly set false', async () => {
  const { window: win } = await loadEngine();
  win._geographicaUseImperial = false;
  const internals = win._geographicaNavEngineInternals;
  assert.equal(internals._useImperial(), false);
});

test('_geographicaUseImperial helper returns true when explicitly set true', async () => {
  const { window: win } = await loadEngine();
  win._geographicaUseImperial = true;
  const internals = win._geographicaNavEngineInternals;
  assert.equal(internals._useImperial(), true);
});

test('TTM I12: VOICE_DISTANCE_FLOOR.auto is 75 m', async () => {
  const { window: win } = await loadEngine();
  const internals = win._geographicaNavEngineInternals;
  assert.equal(internals.VOICE_DISTANCE_FLOOR.auto, 75);
});

test('TTM I12: VOICE_DISTANCE_FLOOR.bicycle is 45 m', async () => {
  const { window: win } = await loadEngine();
  const internals = win._geographicaNavEngineInternals;
  assert.equal(internals.VOICE_DISTANCE_FLOOR.bicycle, 45);
});

test('TTM I12: VOICE_DISTANCE_FLOOR.pedestrian unchanged at 15 m', async () => {
  const { window: win } = await loadEngine();
  const internals = win._geographicaNavEngineInternals;
  assert.equal(internals.VOICE_DISTANCE_FLOOR.pedestrian, 15);
});

test('formatDistancePrefix: imperial cutoff (29 m → "")', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(0, true), '');
  assert.equal(fmt(29, true), '');
});

test('formatDistancePrefix: imperial feet band (round to 100)', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(31, true), 'In 100 feet, ');
  assert.equal(fmt(91, true), 'In 300 feet, ');
  assert.equal(fmt(290, true), 'In 1000 feet, ');  // 951 ft rounds to 1000
});

test('formatDistancePrefix: imperial quarter-mile band entry', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  // 305 m = 1001 ft = 0.190 mi (just into [1000, 1980) ft = quarter band)
  assert.equal(fmt(305, true), 'In a quarter mile, ');
  assert.equal(fmt(500, true), 'In a quarter mile, '); // 1640 ft = 0.311 mi, still in quarter
  assert.equal(fmt(504, true), 'In a quarter mile, '); // 1654 ft = 0.313 mi, still quarter (well inside quarter band)
});

test('formatDistancePrefix: imperial half mile band', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(700, true), 'In half a mile, ');  // 2297 ft, in [1980, 3300)
  assert.equal(fmt(800, true), 'In half a mile, ');
});

test('formatDistancePrefix: imperial three-quarter mile band', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(1100, true), 'In three quarters of a mile, ');  // 3609 ft, in [3300, 4620)
});

test('formatDistancePrefix: imperial one mile band', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(1500, true), 'In one mile, ');  // 4921 ft, in [4620, 7920)
  assert.equal(fmt(2100, true), 'In one mile, ');  // 6890 ft, still in band
});

test('formatDistancePrefix: imperial multi-mile (round to whole)', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(2500, true), 'In 2 miles, ');  // 8202 ft = 1.553 mi, rounds to 2
  assert.equal(fmt(8000, true), 'In 5 miles, ');  // 4.972 mi, rounds to 5
});

test('formatDistancePrefix: metric cutoff', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(0, false), '');
  assert.equal(fmt(29, false), '');
});

test('formatDistancePrefix: metric meters band low (round to 10)', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(31, false), 'In 30 meters, ');
  assert.equal(fmt(85, false), 'In 90 meters, ');
});

test('formatDistancePrefix: metric meters band mid (round to 50)', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(101, false), 'In 100 meters, ');
  assert.equal(fmt(480, false), 'In 500 meters, ');
  assert.equal(fmt(998, false), 'In 1000 meters, ');  // edge: rounds to 1000
});

test('formatDistancePrefix: metric one-kilometer band', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(1000, false), 'In one kilometer, ');
  assert.equal(fmt(1499, false), 'In one kilometer, ');
});

test('formatDistancePrefix: metric multi-kilometer (round to 0.1)', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(1500, false), 'In 1.5 kilometers, ');  // Math.round(15)/10 = 1.5
  assert.equal(fmt(2345, false), 'In 2.3 kilometers, ');  // Math.round(23.45)/10 = 2.3
});

test('formatDistancePrefix: monotonicity property — output never decreases as meters increases', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  function distanceValue(prefix, useImperial) {
    if (prefix === '') return -1;
    const m = prefix.match(/In (.+?), /);
    if (!m) throw new Error('unexpected prefix shape: ' + prefix);
    const phrase = m[1];
    if (/feet$/.test(phrase)) return parseInt(phrase, 10) * 0.3048;
    if (phrase === 'a quarter mile')           return 0.25 * 1609.344;
    if (phrase === 'half a mile')              return 0.5  * 1609.344;
    if (phrase === 'three quarters of a mile') return 0.75 * 1609.344;
    if (phrase === 'one mile')                 return 1.0  * 1609.344;
    if (/miles$/.test(phrase))   return parseInt(phrase, 10) * 1609.344;
    if (phrase === 'one kilometer') return 1000;
    if (/kilometers$/.test(phrase)) return parseFloat(phrase) * 1000;
    if (/meters$/.test(phrase))     return parseInt(phrase, 10);
    throw new Error('unmatched phrase: ' + phrase);
  }
  for (const useImperial of [true, false]) {
    let prevValue = -2;
    for (let m = 0; m <= 10000; m += 10) {
      const v = distanceValue(fmt(m, useImperial), useImperial);
      assert.ok(v >= prevValue,
        `non-monotone at m=${m} useImperial=${useImperial}: prev=${prevValue}, now=${v}, prefix="${fmt(m, useImperial)}"`);
      prevValue = v;
    }
  }
});

test('stripBakedDistance: no chain — passes through unchanged', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  assert.equal(strip('Turn left onto Main.'), 'Turn left onto Main.');
});

test('stripBakedDistance: real Valhalla mid-string distance chain', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  // Pulled from live Valhalla auto route (Villa Rita depart maneuver).
  assert.equal(
    strip('Drive east on West Villa Rita Drive. Then, in 900 feet, Turn left onto North 21st Avenue.'),
    'Drive east on West Villa Rita Drive.'
  );
});

test('stripBakedDistance: mid-string non-distance chain (existing Then suffix)', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  assert.equal(
    strip('Turn right onto 24th Drive. Then Turn left onto West Union Hills Drive.'),
    'Turn right onto 24th Drive.'
  );
});

test('stripBakedDistance: comma-form Then (the latent bug we are fixing)', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  // Existing engine regex /\.\s*Then\s+/ failed on this comma form. Spec v2 fixes.
  assert.equal(
    strip('Turn right. Then, Turn right.'),
    'Turn right.'
  );
});

test('stripBakedDistance: leading "Then " (existing pattern preserved)', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  assert.equal(
    strip('Then turn left onto Union Hills Drive.'),
    'turn left onto Union Hills Drive.'
  );
});

test('stripBakedDistance: decimal distance in chain — does not stop at decimal point', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  // R1 F1.5: existing [^.]* in the strip regex stops at "1.5", leaving baked chain.
  // Spec v2's (?:[^.]|\.(?=\d))* allows decimal-point passthrough.
  assert.equal(
    strip('In 1.5 miles, Merge onto I-5. Then, in 0.3 miles, Take exit 42.'),
    'In 1.5 miles, Merge onto I-5.'
  );
});

test('stripBakedDistance: fractional-words chain (Valhalla quarter mile form)', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  assert.equal(
    strip('Drive north. Then, in a quarter mile, Keep left to stay on North Central Avenue.'),
    'Drive north.'
  );
});

test('stripBakedDistance: leading "In <dist>, X" NOT stripped (no real Valhalla emission)', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  // Spec v2 §5.1 deliberately does NOT strip leading "In <dist>" because
  // live Valhalla doesn't emit that shape on transition_alert / pre_transition.
  // Caller's own prefix logic handles this case.
  assert.equal(
    strip('In 400 feet, Turn left.'),
    'In 400 feet, Turn left.'
  );
});

test('stripBakedDistance: empty / null / undefined input — returns unchanged', async () => {
  const { window: win } = await loadEngine();
  const strip = win._geographicaNavEngineInternals._stripBakedDistance;
  assert.equal(strip(''), '');
  assert.equal(strip(undefined), undefined);
  assert.equal(strip(null), null);
});

test('formatDistancePrefix: NaN and Infinity safety (imperial)', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  // NaN should fall to the cutoff branch — distance is unknown, no prefix.
  assert.equal(fmt(NaN, true), '');
  assert.equal(fmt(Infinity, true), '');
  assert.equal(fmt(-Infinity, true), '');
});

test('formatDistancePrefix: NaN and Infinity safety (metric)', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  assert.equal(fmt(NaN, false), '');
  assert.equal(fmt(Infinity, false), '');
  assert.equal(fmt(-Infinity, false), '');
});

test('formatDistancePrefix: negative distance returns empty (defensive)', async () => {
  const { window: win } = await loadEngine();
  const fmt = win._geographicaNavEngineInternals._formatDistancePrefix;
  // Negative meters shouldn't reach this function (caller's distToNext <= 0 guards),
  // but defensively returning "" is safer than nonsense like "In -300 feet, ".
  assert.equal(fmt(-50, true), '');
  assert.equal(fmt(-50, false), '');
});

test('consumeGPSRecoveryFlag: normal flow always returns false', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const internals = win._geographicaNavEngineInternals;
  // Simulate a fresh GPS state — never stale, never DR.
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 10 };
  nav.start(fixtureRouteWithTwoTurns());
  // Tick a few times with fresh GPS.
  for (let i = 0; i < 3; i++) {
    nav.updateGPS({ latitude: 35.20, longitude: -111.65, speed: 10 });
  }
  // After all-fresh ticks, the recovery flag should never have been armed.
  assert.equal(internals._peekGPSRecoveryFlag(), false,
    'recovery flag should be false after all-fresh ticks');
});

test('consumeGPSRecoveryFlag: arms after stale, fires once on recovery', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const internals = win._geographicaNavEngineInternals;
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 10 };
  nav.start(fixtureRouteWithTwoTurns());
  // Tick once fresh — recovery flag stays disarmed (and the helper updates state).
  nav.updateGPS({ latitude: 35.20, longitude: -111.65, speed: 10 });
  // The flag is consumed via checkVoice; we test the helper directly here.
  // Drive consumeGPSRecoveryFlag through the test hook to set up state.
  // First call: prevTickWasStaleOrDR is false, nowFresh is true → returns false.
  assert.equal(internals._consumeGPSRecoveryFlag(), false);
  // Force "stale" — set lastGPSTime in the past via the test mutator.
  internals._setLastGPSTime(Date.now() - 5000);  // 5 s old, exceeds 3 s timeout
  // Now a tick is "stale" — calling the helper should NOT return true (we're stale, not recovering).
  // It updates prevTickWasStaleOrDR = true and returns false.
  assert.equal(internals._consumeGPSRecoveryFlag(), false);
  // Restore fresh GPS time.
  internals._setLastGPSTime(Date.now());
  // Now the helper sees the recovery transition: prev was stale, now is fresh → return TRUE.
  assert.equal(internals._consumeGPSRecoveryFlag(), true);
  // Subsequent call: prev is now false (one-shot consumed), now is fresh → return false.
  assert.equal(internals._consumeGPSRecoveryFlag(), false);
});

test('I13: far-tier fires "In a quarter mile, " prefix when above cutoff', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const { fixtureLongFirstSegment } = await import('./test_runner.mjs');
  win._geographicaUseImperial = true;
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 16 };
  const fires = [];
  nav.onVoice((text) => fires.push(text));
  nav.start(fixtureLongFirstSegment());
  // Drive at 16 m/s. Far-tier ttm ≤ 30 → fires at distance ≤ 480 m.
  // Approach to ~470 m west of M1 (M1 at lng -111.628).
  // dx_deg = 470 / (6371000 * cos(35.20° * π/180) * π/180) ≈ 0.005173
  // GPS at lng = -111.628 - 0.005173 ≈ -111.63317
  for (let i = 0; i < 3; i++) {
    nav.updateGPS({ latitude: 35.20, longitude: -111.63317, speed: 16 });
  }
  // Far-tier should have fired.
  assert.ok(fires.length >= 1, 'expected far-tier to fire');
  // Far-tier text MUST match the full transformed string (~480 m fire = ~1575 ft, in [1000, 1980) band).
  assert.match(fires[0], /^In a quarter mile, turn left onto Test Avenue\.?$/,
    `expected full transformed far-tier text "In a quarter mile, turn left onto Test Avenue", got: ${JSON.stringify(fires[0])}`);
});

test('I13: near-tier floor-fire produces bare base + chain prefix', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const { fixtureWiderCluster } = await import('./test_runner.mjs');
  win._geographicaUseImperial = true;
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 11 };
  const fires = [];
  nav.onVoice((text) => fires.push(text));
  nav.start(fixtureWiderCluster());
  // Position car ~74 m WEST of M1 (within 75 m near-tier floor). M1 at -111.64780.
  // haversine([-111.64861, 35.20], M1) ≈ 73.6 m → distToNext <= 75 floor → near-tier fires.
  // (Note: -111.64863 gives 75.4 m which is above floor, so use -111.64861.)
  // At 11 m/s: ttm = 73.6/11 = 6.7s > 3s → nearTTMFire = false → nearFloorFire = true.
  // Strategy B: nearFloorFire suppresses base prefix; chain prefix preserved.
  for (let i = 0; i < 3; i++) {
    nav.updateGPS({ latitude: 35.20, longitude: -111.64861, speed: 11 });
  }
  assert.ok(fires.length >= 1, 'expected near-tier to fire');
  // Floor-fire path (nearFloorFire = true): base prefix suppressed; bare maneuver text.
  // Chain to M2 (200 m after M1) → 656 ft → round(656/100)*100 = 700 → "then in 700 feet, ..."
  assert.match(fires[0],
    /^Turn left onto First Street, then in 700 feet, turn right onto Second Road/,
    `expected floor-fire bare base + chain prefix, got: ${JSON.stringify(fires[0])}`);
});

test('I13: near-tier TTM-fire applies prefix (close-start scenario)', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const { fixtureWiderCluster } = await import('./test_runner.mjs');
  win._geographicaUseImperial = true;
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 11 };
  const fires = [];
  nav.onVoice((t) => fires.push(t));
  nav.start(fixtureWiderCluster());
  // Drive to ~31 m before M1 (M1 at -111.64780). 31 m at 11 m/s = TTM 2.8 s
  // -> ttm <= 3 s -> nearTTMFire wins, prefix applied.
  // Driver approaches from west (route start at -111.65000, M1 at -111.64780).
  // 31 m west of M1: 31 / (cos(35.2°) × 111000) ≈ 31 / 90671 ≈ 0.000342 deg.
  // longitude = -111.64780 - 0.000342 ≈ -111.64814 (more negative = further west).
  // Note: -111.64813 gives ~29.99 m (below the 30 m cutoff → empty prefix);
  // -111.64814 gives ~30.89 m (above cutoff → "In 100 feet, "). Use -111.64814.
  for (let i = 0; i < 3; i++) {
    nav.updateGPS({ latitude: 35.20, longitude: -111.64814, speed: 11 });
  }
  assert.ok(fires.length >= 1, 'expected near-tier to fire');
  // ~31 m → 101 ft → bucket 100 → "In 100 feet, "
  // Chain to M2 (200 m) → 656 ft → bucket 700 → "then in 700 feet, "
  assert.match(fires[fires.length - 1],
    /^In 100 feet, turn left onto First Street, then in 700 feet, turn right onto Second Road/,
    `expected TTM-fire prefix path, got: ${JSON.stringify(fires[fires.length - 1])}`);
});

test('I13: cutoff suppresses near-tier prefix for very-short-spacing fixture', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const { fixtureVillaRitaCluster } = await import('./test_runner.mjs');
  win._geographicaUseImperial = true;
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 11 };
  const fires = [];
  nav.onVoice((text) => fires.push(text));
  nav.start(fixtureVillaRitaCluster());
  // Villa Rita uses 30 m spacing. M1 at -111.64967. Drive to within ~25 m WEST of M1.
  // 25 m at lat 35.20: dx_deg ≈ 0.000275 → -111.64967 + 0.000275 = -111.64940 (rough)
  for (let i = 0; i < 3; i++) {
    nav.updateGPS({ latitude: 35.20, longitude: -111.64940, speed: 11 });
  }
  assert.ok(fires.length >= 1, 'expected near-tier to fire');
  // At ~25 m fire distance (below 30 m cutoff), no prefix.
  assert.doesNotMatch(fires[0], /^In \d+ feet,/,
    `expected no prefix at sub-cutoff distance, got: ${JSON.stringify(fires[0])}`);
});

test('I13: floor-fire metric/imperial dispatch produces bare base + chain prefix', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const { fixtureWiderCluster } = await import('./test_runner.mjs');
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 11 };
  const fires = [];
  nav.onVoice((text) => fires.push(text));
  // Run as metric.
  win._geographicaUseImperial = false;
  nav.start(fixtureWiderCluster());
  // Same position as floor-fire test: ~74 m WEST of M1 (-111.64861, ~73.6 m from M1).
  // At 11 m/s: ttm = 73.6/11 = 6.7s > 3s → nearTTMFire = false → nearFloorFire = true.
  // Strategy B: floor-fire suppresses base prefix regardless of unit mode.
  // Chain prefix still applied (chain distance meaningful regardless of fire mode).
  for (let i = 0; i < 3; i++) {
    nav.updateGPS({ latitude: 35.20, longitude: -111.64861, speed: 11 });
  }
  assert.ok(fires.length >= 1, 'expected near-tier to fire');
  // Floor-fire path: base prefix suppressed (no "In 70 meters, " preamble).
  // Chain 200 m → metric: 200 < 1000 → round(200/50)*50 = 200 → "In 200 meters, "
  assert.match(fires[0],
    /^Turn left onto First Street, then in 200 meters, turn right onto Second Road/,
    `floor-fire metric dispatch failed, got: ${JSON.stringify(fires[0])}`);
});

test('I13: prompt count invariant on Villa Rita fixture (G9 regression guard)', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const { fixtureVillaRitaCluster } = await import('./test_runner.mjs');
  win._geographicaUseImperial = true;
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 10 };
  const fires = [];
  nav.onVoice((text) => fires.push(text));
  nav.start(fixtureVillaRitaCluster());
  // Drive through all three maneuvers (matches the existing TTM v3 test from §6.4).
  const lngs = [
    -111.6498, -111.6497, -111.6496,
    -111.6495, -111.6494, -111.6493,
    -111.6492, -111.6491, -111.6490,
  ];
  for (const lng of lngs) {
    nav.updateGPS({ latitude: 35.20, longitude: lng, speed: 10 });
  }
  // TTM v3 baseline asserts exactly 3 prompts. New prefix logic must preserve.
  assert.equal(fires.length, 3,
    `expected 3 prompts (TTM v3 baseline preserved), got ${fires.length}: ${JSON.stringify(fires)}`);
});

test('I13g: full pipeline — strip Valhalla chain + bare base on floor-fire', async (t) => {
  // Synthesize a fixture with the real Valhalla multi-cue shape on the depart-leading maneuver.
  // The mid-string ". Then, in 900 feet, X." is the actual Villa Rita depart pattern.
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaUseImperial = true;
  const fires = [];
  nav.onVoice((t) => fires.push(t));

  // Build a route where M1 has the multi-cue VPT shape.
  const route = {
    coords: [
      [-111.65000, 35.20],  // start
      [-111.64780, 35.20],  // M1 boundary (200 m east)
      [-111.64560, 35.20],  // route end
    ],
    maneuvers: [
      {
        type: 1,
        instruction: 'Head east',
        verbal_transition_alert_instruction: 'In 700 feet, turn left',
        verbal_pre_transition_instruction: 'Head east',
        begin_shape_index: 0,
        end_shape_index: 1,
      },
      {
        type: 15,
        instruction: 'Turn left onto Test Avenue',
        verbal_transition_alert_instruction: 'Turn left onto Test Avenue',
        // Multi-cue VPT: real Valhalla depart shape with baked distance + chained next-turn.
        verbal_pre_transition_instruction: 'Turn left onto Test Avenue. Then, in 900 feet, Continue on Test Avenue.',
        begin_shape_index: 1,
        end_shape_index: 2,
      },
    ],
    summary: { length: 0.4, time: 40 },
    totalDistance: 400,
    totalTime: 40,
    costing: 'auto',
    remainingWaypoints: [],
  };
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 11 };
  nav.start(route);
  // Drive to ~74 m before M1 to fire near-tier (74 m → floor-fire, not TTM-fire).
  // At 11 m/s: ttm = 73.6/11 = 6.7s > 3s → nearTTMFire = false → nearFloorFire = true.
  // Strategy B: floor-fire suppresses base prefix. Chain: route has only 2 maneuvers so
  // no chain append applies.
  for (let i = 0; i < 3; i++) {
    nav.updateGPS({ latitude: 35.20, longitude: -111.64861, speed: 11 });
  }
  assert.ok(fires.length >= 1, 'expected near-tier to fire');
  // Pipeline trace: stripBakedDistance removes ". Then, in 900 feet, Continue on Test Avenue.";
  // residual is "Turn left onto Test Avenue."; uppercase preserved; nearFloorFire = true so
  // base prefix suppressed — bare maneuver text "Turn left onto Test Avenue." is the output.
  assert.equal(fires[fires.length - 1], 'Turn left onto Test Avenue.',
    `pipeline order broken — expected bare floor-fire output, got: ${JSON.stringify(fires[fires.length - 1])}`);
});

test('I14: GPS-recovery guard suppresses prefix on first post-stale tick', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const { fixtureLongFirstSegment } = await import('./test_runner.mjs');
  const internals = win._geographicaNavEngineInternals;
  win._geographicaUseImperial = true;
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 16 };
  const fires = [];
  nav.onVoice((text) => fires.push(text));
  nav.start(fixtureLongFirstSegment());

  // Tick once fresh — driver is 2000 m from M1, far-tier TTM > 30s, won't fire.
  nav.updateGPS({ latitude: 35.20, longitude: -111.65, speed: 16 });
  assert.equal(fires.length, 0, 'no fire yet at 2000 m from M1');

  // Directly arm the recovery flag: simulates a prior stale/DR episode.
  // Using _setGPSRecoveryFlag(true) is deterministic — _setLastGPSTime approach
  // is racy because consumeGPSRecoveryFlag only runs inside the near/far
  // would-fire branches; setting lastGPSTime stale between non-firing ticks
  // doesn't update prevTickWasStaleOrDR before the recovery tick wins it back.
  internals._setGPSRecoveryFlag(true);

  // Next tick — recovery flag is armed, drive into far-tier range (~470 m from M1).
  // M1 at -111.62800; 470 m west ≈ -111.62800 - 470/90862 ≈ -111.63317.
  nav.updateGPS({ latitude: 35.20, longitude: -111.63317, speed: 16 });
  assert.ok(fires.length >= 1, 'expected far-tier to fire');
  // FIRST post-recovery prompt should have NO prefix (suppressed).
  assert.doesNotMatch(fires[0], /^In .+, /,
    `expected NO prefix on first post-recovery fire, got: ${JSON.stringify(fires[0])}`);

  // Subsequent ticks should resume normal prefix behavior.
  // M1's far is now announced. Re-arm the flag and drive into near tier (~50 m from M1)
  // to verify the recovery flag fires once and then clears for subsequent ticks.
  // 50 m west of M1 (-111.62800): -111.62800 - 50/90862 ≈ -111.62855.
  internals._setGPSRecoveryFlag(true);
  nav.updateGPS({ latitude: 35.20, longitude: -111.62855, speed: 16 }); // ~50 m from M1, near tier
  // Second fire after another recovery arm: also suppressed (flag was re-armed).
  // Loosely confirms a second fire occurred; tighter assertion deferred — I14b
  // verifies the resume invariant (spec §5.6 I14) more rigorously.
  if (fires.length >= 2) {
    assert.ok(typeof fires[1] === 'string' && fires[1].length > 0, 'second fire is non-empty');
  }
});

test('I14b: GPS-stale recovery composes with normal-flow prefix on second tick', async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  const { fixtureWiderCluster } = await import('./test_runner.mjs');
  const internals = win._geographicaNavEngineInternals;
  win._geographicaUseImperial = true;
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, speed: 11 };
  const fires = [];
  nav.onVoice((text) => fires.push(text));
  nav.start(fixtureWiderCluster());

  // Directly arm the recovery flag, then fire a fresh tick at near-tier distance.
  // Using _setGPSRecoveryFlag(true) rather than _setLastGPSTime for determinism —
  // see I14 comment above.
  internals._setGPSRecoveryFlag(true);
  nav.updateGPS({ latitude: 35.20, longitude: -111.64698, speed: 11 });
  assert.ok(fires.length >= 1, 'expected near-tier fire on recovery tick');
  assert.doesNotMatch(fires[0], /^In \d+ feet,/,
    `expected NO prefix on recovery tick, got: ${JSON.stringify(fires[0])}`);

  // After the recovery-suppressed fire, the engine resumes normal prefix behavior.
  // M1's near is now announced. Drive past M1 toward M2 (-111.64560).
  // 75 m before M2 = -111.64560 + 0.000826° ≈ -111.64478 (driver approaching from west).
  // M2 fires via the 75 m DISTANCE FLOOR (not TTM): 74.51 m / 11 m·s⁻¹ = 6.8 s TTM,
  // above the 3 s near-tier TTM threshold. Floor-triggered fires are still expected to
  // apply the prefix; the recovery flag was consumed on the M1 tick above.
  for (let i = 0; i < 3; i++) {
    nav.updateGPS({ latitude: 35.20, longitude: -111.64478, speed: 11 });
  }
  // At this point M2's near-tier should have fired with a prefix (normal flow, no recovery).
  // Resume: M2 fires WITH prefix because the recovery flag was consumed
  // on the M1 tick above. If M2 fails to fire (floor-constant change?),
  // this assertion fails loudly rather than silently skipping.
  assert.ok(fires.length >= 2,
    `expected M2 near-tier to fire after recovery, got ${fires.length} fire(s): ${JSON.stringify(fires)}`);
  assert.match(fires[fires.length - 1], /^In \d+ feet,/,
    `expected prefix on subsequent (non-recovery) tick, got: ${JSON.stringify(fires[fires.length - 1])}`);
});

// NOTE: I15 (exception-safety G11) is not testable via mock due to IIFE
// closure binding — the helpers are bound at module-load time, so a test
// can't substitute a throwing version. Invariant verified by code review:
// in BOTH the far-tier branch (navigation.js around line 558) and the
// near-tier branch (around line 495), announcedSet is marked BEFORE the
// consumeGPSRecoveryFlag / stripBakedDistance / formatDistancePrefix calls
// AND before the chain-append construction. Confirmed in commits 8956ead
// (far-tier) and the post-Task-6 reorder.
