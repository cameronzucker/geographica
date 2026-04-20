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
  // Force an off-route trigger by feeding far-off GPS; engine's hysteresis
  // requires 3 of 5 ticks off-route. Feed 5 in a row.
  for (let i = 0; i < 5; i++) {
    nav.updateGPS({ latitude: 35.25, longitude: -111.55, heading: 90, speed: 10 });
  }
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

test('reroute timeout clears lastRerouteTime for immediate re-reroute', { timeout: 15_000 }, async (t) => {
  const { nav, window: win } = await loadEngine();
  t.after(() => { try { nav.stop(); } catch (_) {} });
  win._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };

  const rerouteCalls = [];
  nav.onReroute((info) => rerouteCalls.push(info));

  nav.start(fixtureRouteWithTwoTurns());

  // Trigger reroute #1 by feeding 5 off-route positions (3-of-5 hysteresis).
  for (let i = 0; i < 5; i++) {
    nav.updateGPS({ latitude: 35.25, longitude: -111.55, heading: 90, speed: 10 });
  }
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
