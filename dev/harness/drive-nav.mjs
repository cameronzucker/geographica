// Playwright-driven nav integration test.
//
// Mocks /valhalla/route + window._geographicaGPSData, then asserts:
//   1. Initial route renders blue line + sidebar directions.
//   2. Off-route GPS triggers reroute.
//   3. After reroute resolves, map source 'route' setData was called
//      with new coords (polyline updated — the B2 assertion).
//
// Usage: node drive-nav.mjs [--url=http://localhost:8088]

import { chromium } from 'playwright';

const argv = process.argv.slice(2);
const urlArg = argv.find((a) => a.startsWith('--url='));
const baseUrl = urlArg ? urlArg.slice(6) : 'http://localhost:8088';
const modeArg = argv.find((a) => a.startsWith('--mode='));
const mode = modeArg ? modeArg.slice(7) : 'b2';  // default: B2 assertion

const ORIGINAL_ROUTE_SHAPE = 'gxz_}Anbf}E_|@_|@';  // stub polyline
const REROUTE_SHAPE = 'abc123reroute_shape_different_from_original';

async function mockValhalla(page) {
  await page.route('**/valhalla/route', async (route, req) => {
    const body = JSON.parse(req.postData() || '{}');
    const isReroute = body.locations && body.locations.length > 0 &&
                       Math.abs(body.locations[0].lat - 35.25) < 0.1;

    // In error mode, reroute requests return 200 with { error: "..." }
    if (mode === 'error' && isReroute) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'No route found' }),
      });
      return;
    }

    // Default behavior: return valid route (B2 mode or initial route fetch)
    const shape = isReroute ? REROUTE_SHAPE : ORIGINAL_ROUTE_SHAPE;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        trip: {
          legs: [{
            shape: shape,
            maneuvers: [
              { type: 1, instruction: 'Head east', begin_shape_index: 0, end_shape_index: 1,
                verbal_transition_alert_instruction: 'In half a mile, turn left',
                verbal_pre_transition_instruction: 'Turn left on Oak Street' },
              { type: 15, instruction: 'Arrived', begin_shape_index: 2, end_shape_index: 2 },
            ],
          }],
          summary: { length: 1.0, time: 60 },
          locations: [
            { lat: 35.20, lon: -111.65, type: 'break' },
            { lat: 35.21, lon: -111.64, type: 'break' },
          ],
        },
      }),
    });
  });
}

async function mainAsserts() {
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();

  await mockValhalla(page);
  await page.goto(baseUrl);

  // Wait for map to be ready.
  await page.waitForFunction(() => !!window._geographicaMap, null, { timeout: 10_000 });

  // Inject GPS data.
  await page.evaluate(() => {
    window._geographicaGPSData = { lat: 35.20, lon: -111.65, heading: 90, speed: 10 };
  });

  // Request a route via the exposed API.
  // (Assumes the route-request DOM entry points are present; we call the
  //  setActiveRoute path directly for deterministic testing.)
  await page.evaluate(() => {
    // Simulate: the initial route fetch happened and setActiveRoute was called.
    return fetch('/valhalla/route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ locations: [{ lat: 35.20, lon: -111.65 }, { lat: 35.21, lon: -111.64 }], costing: 'auto' }),
    }).then((r) => r.json()).then((data) => {
      window._geographicaSetActiveRoute(data.trip, { refitBounds: true, costing: 'auto' });
    });
  });

  // Assert map 'route' source data has initial shape.
  const initialCoords = await page.evaluate(() => {
    const s = window._geographicaMap.getSource('route');
    return s && s._data && s._data.geometry ? s._data.geometry.coordinates.length : 0;
  });
  if (initialCoords === 0) {
    console.error('ASSERT FAIL: map route source never received initial coords');
    process.exit(1);
  }

  // Start nav and trigger reroute via off-route GPS.
  await page.evaluate(() => {
    // Manually feed the start trigger:
    const trip = window._geographicaLastTrip;
    // Use navigation.js's applyReroute directly isn't representative;
    // instead simulate by calling startNavigation via the DOM button.
    document.getElementById('start-nav-btn').click();
  });

  // Wait for nav-active class on body.
  await page.waitForFunction(() => document.body.classList.contains('nav-active'), null, { timeout: 5_000 });

  // B12 mode: assert no reroute fetches fire after stopNavigation.
  // Set up slow mock override BEFORE off-route tick loop so we catch the reroute in-flight.
  let rerouteCallCount = 0;
  let rerouteHitsAfterStop = 0;
  let navStoppedAt = null;

  if (mode === 'stop-mid-reroute') {
    // Unroute the default fast mock and install slow-mock override before the tick loop.
    await page.unroute('**/valhalla/route');
    await page.route('**/valhalla/route', async (route, req) => {
      rerouteCallCount++;
      const now = Date.now();
      if (navStoppedAt && now > navStoppedAt) {
        rerouteHitsAfterStop++;
      }
      // Delay the response by 3 s so we can stop nav mid-flight.
      await new Promise((r) => setTimeout(r, 3000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          trip: {
            legs: [{
              shape: REROUTE_SHAPE,
              maneuvers: [
                { type: 1, instruction: 'Head east', begin_shape_index: 0, end_shape_index: 1,
                  verbal_transition_alert_instruction: 'In half a mile, turn left',
                  verbal_pre_transition_instruction: 'Turn left on Oak Street' },
                { type: 15, instruction: 'Arrived', begin_shape_index: 2, end_shape_index: 2 },
              ],
            }],
            summary: { length: 1.0, time: 60 },
            locations: [
              { lat: 35.25, lon: -111.55, type: 'break' },
              { lat: 35.21, lon: -111.64, type: 'break' },
            ],
          },
        }),
      });
    });
  }

  // Force off-route GPS for several ticks (engine hysteresis 3-of-5).
  for (let i = 0; i < 8; i++) {
    await page.evaluate(() => {
      window._geographicaGPSData = { lat: 35.25, lon: -111.55, heading: 90, speed: 10 };
    });
    await page.waitForTimeout(600);  // > 500 ms feedGPS interval
  }

  // B12 mode: assert no reroute fetches fire after stopNavigation.
  if (mode === 'stop-mid-reroute') {
    // Verify a reroute was in-flight at stop time. If not, the test passes vacuously.
    if (rerouteCallCount < 1) {
      console.error('ASSERT FAIL (B12): no reroute fetch was initiated during off-route ticks (vacuous pass)');
      process.exit(1);
    }

    // Wait 500 ms for the reroute fetch to complete or be aborted, then stop nav.
    await page.waitForTimeout(500);
    navStoppedAt = Date.now();
    await page.evaluate(() => document.getElementById('stop-nav-btn').click());

    // Wait 10 s and assert no further /valhalla/route calls were made post-stop.
    await page.waitForTimeout(10_000);
    if (rerouteHitsAfterStop > 0) {
      console.error(`ASSERT FAIL (B12): ${rerouteHitsAfterStop} reroute fetches fired after stopNavigation`);
      process.exit(1);
    }
    console.log('PASS: no reroute fetches after stopNavigation (B12)');
    await browser.close();
    return;
  }

  // If mode === 'error', assert banner surfaces after MAX_REROUTE_RETRIES backoff.
  if (mode === 'error') {
    // Retries: 2s + 4s + 8s = 14s maximum. Add fudge for async propagation.
    await page.waitForFunction(() => {
      const b = document.getElementById('nav-banner');
      return b && !b.classList.contains('hidden') && b.textContent.includes('Reroute failed');
    }, null, { timeout: 20_000 }).catch(() => {
      console.error('ASSERT FAIL (B11): no Reroute failed banner after error-mode reroute');
      process.exit(1);
    });
    console.log('PASS: Reroute failed banner surfaces on Valhalla 200-with-error (B11)');
    await browser.close();
    return;
  }

  // Default B2 mode: wait for map 'route' source to be updated with REROUTE_SHAPE's coords.
  await page.waitForFunction((originalCount) => {
    const s = window._geographicaMap.getSource('route');
    const coords = s && s._data && s._data.geometry ? s._data.geometry.coordinates : [];
    return coords.length > 0 && coords.length !== originalCount;
  }, initialCoords, { timeout: 15_000 }).catch(() => {
    console.error('ASSERT FAIL (B2): map route source did not update after reroute');
    process.exit(1);
  });

  console.log('PASS: map route source updates after reroute (B2)');
  await browser.close();
}

mainAsserts().catch((err) => {
  console.error('Harness crashed:', err);
  process.exit(1);
});
