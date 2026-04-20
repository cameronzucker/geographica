/**
 * GeographicaNav — Turn-by-turn navigation engine for Geographica
 *
 * Event-driven, pure JS, no DOM or MapLibre dependencies.
 * The main app wires GPS updates in and UI updates out via callbacks.
 *
 * State machine:
 *   IDLE -> JOINING -> NAVIGATING -> ARRIVED
 *              |            |
 *           REROUTING    REROUTING
 */
(function () {
  "use strict";

  // ─── Constants ───────────────────────────────────────────────────────

  var DEG2RAD = Math.PI / 180;
  var RAD2DEG = 180 / Math.PI;
  var EARTH_RADIUS = 6371000; // meters

  var OFF_ROUTE_THRESHOLD = 50;       // meters
  var OFF_ROUTE_TICKS = 5;            // consecutive 1 Hz ticks (legacy, unused)
  var OFF_ROUTE_EXIT_THRESHOLD = 35;  // meters -- must drop below this to exit off-route
  var OFF_ROUTE_WINDOW = 5;           // rolling window size
  var OFF_ROUTE_MIN_COUNT = 3;        // minimum off-route ticks in window to trigger
  var REROUTE_COOLDOWN = 15000;       // ms between reroute triggers
  var REROUTE_TIMEOUT = 10000;        // ms -- max time to wait for reroute response
  var JOIN_TOLERANCE = 200;           // meters — give up joining if exceeded for 15s
  var JOIN_THRESHOLD = 50;            // meters — close enough to join route
  var ARRIVAL_GEOFENCE = 30;          // meters from destination
  var ARRIVAL_SEGMENTS = 3;           // must be snapped to final N segments
  var HEADING_SPEED_GATE = 3;         // m/s — below this, heading is unreliable
  var GPS_STALE_TIMEOUT = 3000;       // ms without GPS update
  var DEAD_RECKON_MAX = 30000;        // ms max extrapolation
  var SNAP_WINDOW_BEHIND = 3;
  var SNAP_WINDOW_AHEAD = 50;
  var SNAP_FALLBACK_THRESHOLD = 100;  // meters — trigger full-polyline search
  var SNAP_HEADING_RADIUS = 10;       // meters — heading disambiguation zone
  var SPEED_HISTORY_WINDOW = 60;      // seconds for rolling speed ratio

  // Voice thresholds per costing. Each entry is [far, near] in meters.
  //
  // BAND-AID (2026-04-20, Cameron decision post field test, juniper):
  // Previous tiering was [far, medium, near] = 3 announcements per
  // maneuver. In urban/surface-street driving with several close-together
  // turns (field-tested: Villa Rita → North Phoenix Costco with a
  // westerly detour), that produced up to 9 prompts in ~200 ft of
  // driving — dangerous, not helpful. Dropping the medium tier and
  // pulling the far tier inward (800m → 400m for auto; urban driving
  // rarely has 800m of advance notice anyway) caps the rate at 2
  // announcements per maneuver. Explicitly a stopgap: the full
  // time-to-maneuver (TTM) redesign is the real fix, queued in the
  // next-session START.md resume block.
  //
  // When the TTM redesign lands, remove this band-aid entirely
  // (VOICE_THRESHOLDS, VOICE_COOLDOWN, VOICE_SPEED_GATE, and
  // VOICE_NEAR_ANNOUNCE_DISTANCE all likely go away together).
  var VOICE_THRESHOLDS = {
    auto:       [400, 50],
    bicycle:    [200, 30],
    pedestrian: [75,  20]
  };

  var NEXT_AFTER_NEXT_DISTANCE = 500; // meters
  var VOICE_COOLDOWN = 5000;       // ms minimum between announcements
  var VOICE_SPEED_GATE = 2;        // m/s -- suppress below this
  var VOICE_NEAR_ANNOUNCE_DISTANCE = 50; // meters -- always announce within this distance

  // ─── TTM (time-to-maneuver) voice model — spec v2 ──────────────────────
  // Each VOICE_TTM entry is [far_seconds, near_seconds]. Announcement timing
  // is ttm = distToNext / smoothedSpeed. The distance floor ensures near-tier
  // still fires when stationary at a maneuver (TTM → ∞ when speed → 0).
  var VOICE_TTM = {
    auto:       [30, 3],
    bicycle:    [20, 3],
    pedestrian: [15, 2]
  };
  var VOICE_DISTANCE_FLOOR = {
    auto:       50,
    bicycle:    30,
    pedestrian: 15
  };
  var MIN_SPEED_FLOOR = 1.0;              // m/s — TTM denominator minimum
  var SPEED_WINDOW_SIZE = 3;              // median-of-3 rolling window
  var MAX_SPEED_DELTA_PER_TICK = 15;      // m/s — physically-implausible sample delta

  // ─── Geo math helpers ────────────────────────────────────────────────

  /** Haversine distance between two [lng, lat] points, returns meters. */
  function haversine(a, b) {
    var dLat = (b[1] - a[1]) * DEG2RAD;
    var dLng = (b[0] - a[0]) * DEG2RAD;
    var sinLat = Math.sin(dLat / 2);
    var sinLng = Math.sin(dLng / 2);
    var h = sinLat * sinLat +
            Math.cos(a[1] * DEG2RAD) * Math.cos(b[1] * DEG2RAD) * sinLng * sinLng;
    return 2 * EARTH_RADIUS * Math.asin(Math.sqrt(h));
  }

  /** Bearing from a to b in degrees [0, 360). */
  function bearing(a, b) {
    var dLng = (b[0] - a[0]) * DEG2RAD;
    var lat1 = a[1] * DEG2RAD;
    var lat2 = b[1] * DEG2RAD;
    var y = Math.sin(dLng) * Math.cos(lat2);
    var x = Math.cos(lat1) * Math.sin(lat2) -
            Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLng);
    return (Math.atan2(y, x) * RAD2DEG + 360) % 360;
  }

  /** Absolute angular difference in degrees [0, 180]. */
  function angleDiff(a, b) {
    var d = Math.abs(a - b) % 360;
    return d > 180 ? 360 - d : d;
  }

  /**
   * Project point P onto segment A-B.
   * Returns { point: [lng, lat], dist: meters from P, t: fraction along A-B }.
   */
  function projectOntoSegment(P, A, B) {
    // Work in approximate local meters (equirectangular)
    var cosLat = Math.cos(A[1] * DEG2RAD);
    var ax = 0, ay = 0;
    var bx = (B[0] - A[0]) * DEG2RAD * EARTH_RADIUS * cosLat;
    var by = (B[1] - A[1]) * DEG2RAD * EARTH_RADIUS;
    var px = (P[0] - A[0]) * DEG2RAD * EARTH_RADIUS * cosLat;
    var py = (P[1] - A[1]) * DEG2RAD * EARTH_RADIUS;

    var dx = bx - ax, dy = by - ay;
    var lenSq = dx * dx + dy * dy;
    var t = lenSq === 0 ? 0 : Math.max(0, Math.min(1, (px * dx + py * dy) / lenSq));

    var projX = ax + t * dx;
    var projY = ay + t * dy;
    var dist = Math.sqrt((px - projX) * (px - projX) + (py - projY) * (py - projY));

    // Convert projected point back to lng/lat
    var projLng = A[0] + (projX / (EARTH_RADIUS * cosLat)) * RAD2DEG;
    var projLat = A[1] + (projY / EARTH_RADIUS) * RAD2DEG;

    return { point: [projLng, projLat], dist: dist, t: t };
  }

  /** Cumulative along-route distance from coords[0] to coords[index] in meters. */
  function cumulativeDistance(coords, index) {
    var d = 0;
    for (var i = 1; i <= index && i < coords.length; i++) {
      d += haversine(coords[i - 1], coords[i]);
    }
    return d;
  }

  /** Distance along route from segmentIndex (at fraction t) to end. */
  function distanceToEnd(coords, segIndex, t) {
    // Partial distance in current segment
    var d = haversine(coords[segIndex], coords[segIndex + 1]) * (1 - t);
    for (var i = segIndex + 2; i < coords.length; i++) {
      d += haversine(coords[i - 1], coords[i]);
    }
    return d;
  }

  // ─── Navigation engine ──────────────────────────────────────────────

  var route = null;           // current routeData
  var state = "idle";         // state machine
  var lastIndex = 0;          // last snapped segment index
  var currentManeuverIdx = 0;
  var offRouteHistory = [];  // rolling window of booleans
  var inOffRouteState = false;
  var lastRerouteTime = 0;
  var rerouteSeq = 0;         // monotonic counter for aborting stale reroutes
  var rerouteTimeoutId = null;
  var joinStartTime = 0;      // timestamp when JOINING began

  // GPS state
  var lastGPS = null;         // most recent GPS data
  var lastGPSTime = 0;        // timestamp of last GPS message
  var lastValidHeading = 0;
  var headingValid = false;
  var lastSpeed = 0;
  var lastSnap = null;        // last snap result

  // Dead reckoning
  var drActive = false;

  // Voice
  var muted = false;
  var announcedSet = {};      // key: "maneuverIdx-threshold" -> true
  var lastAnnouncementTime = 0;

  // Speed history for ETA adjustment: [{time, actual, expected}]
  var speedHistory = [];

  // Callbacks
  var onUpdateCb = null;
  var onRerouteCb = null;
  var onArrivalCb = null;
  var onVoiceCb = null;

  // Precomputed segment distances for the current route
  var segmentDistances = null;   // segmentDistances[i] = distance from coords[i] to coords[i+1]
  var cumulativeDistances = null; // cumulativeDistances[i] = distance from start to coords[i]

  function precomputeDistances() {
    var coords = route.coords;
    segmentDistances = new Array(coords.length - 1);
    cumulativeDistances = new Array(coords.length);
    cumulativeDistances[0] = 0;
    for (var i = 0; i < coords.length - 1; i++) {
      segmentDistances[i] = haversine(coords[i], coords[i + 1]);
      cumulativeDistances[i + 1] = cumulativeDistances[i] + segmentDistances[i];
    }
  }

  /** Fast along-route distance from a snap point to the end of the route. */
  function remainingDistance(segIndex, t) {
    if (!segmentDistances) return 0;
    var d = segmentDistances[segIndex] * (1 - t);
    var total = cumulativeDistances[route.coords.length - 1];
    var atPoint = cumulativeDistances[segIndex] + segmentDistances[segIndex] * t;
    return total - atPoint;
  }

  /** Along-route distance from snap point to a specific coord index. */
  function distanceToCoordIndex(segIndex, t, targetIndex) {
    if (!cumulativeDistances) return 0;
    var current = cumulativeDistances[segIndex] + segmentDistances[segIndex] * t;
    var target = cumulativeDistances[targetIndex];
    return target - current;
  }

  // ─── Route snapping ─────────────────────────────────────────────────

  /**
   * Snap a point to the route polyline.
   *
   * Uses a sliding window around lastIndex for performance, with a
   * heading-weighted score to disambiguate parallel segments. Falls back
   * to full-polyline search if windowed best is >100m away.
   */
  function snapToRoute(lng, lat, heading) {
    var P = [lng, lat];
    var coords = route.coords;
    var maxSeg = coords.length - 2;

    // Windowed search bounds
    var lo = Math.max(0, lastIndex - SNAP_WINDOW_BEHIND);
    var hi = Math.min(maxSeg, lastIndex + SNAP_WINDOW_AHEAD);

    var best = searchSegments(P, heading, lo, hi, coords);

    // Fallback: if windowed best is too far, search entire polyline
    if (best.dist > SNAP_FALLBACK_THRESHOLD) {
      var full = searchSegments(P, heading, 0, maxSeg, coords);
      if (full.dist < best.dist) {
        best = full;
      }
    }

    lastIndex = best.segmentIndex;

    return {
      segmentIndex: best.segmentIndex,
      snappedLng: best.point[0],
      snappedLat: best.point[1],
      distanceFromRoute: best.dist,
      alongRouteDistance: cumulativeDistances[best.segmentIndex] +
        segmentDistances[best.segmentIndex] * best.t,
      t: best.t
    };
  }

  /** Search segments [lo..hi] and return best candidate with heading weighting. */
  function searchSegments(P, heading, lo, hi, coords) {
    var bestDist = Infinity;
    var bestScore = Infinity;
    var best = null;
    var candidates = [];

    for (var i = lo; i <= hi; i++) {
      var proj = projectOntoSegment(P, coords[i], coords[i + 1]);
      if (proj.dist < bestDist + SNAP_HEADING_RADIUS) {
        candidates.push({ segmentIndex: i, point: proj.point, dist: proj.dist, t: proj.t });
        if (proj.dist < bestDist) bestDist = proj.dist;
      }
    }

    // Score candidates — if two are within 10m, use heading to disambiguate
    for (var j = 0; j < candidates.length; j++) {
      var c = candidates[j];
      if (c.dist > bestDist + SNAP_HEADING_RADIUS) continue;

      var score = c.dist;
      if (heading !== null && heading !== undefined && candidates.length > 1) {
        var segBearing = bearing(coords[c.segmentIndex], coords[c.segmentIndex + 1]);
        var diff = angleDiff(heading, segBearing) * DEG2RAD;
        score = c.dist + 30 * (1 - Math.cos(diff));
      }

      if (score < bestScore) {
        bestScore = score;
        best = c;
      }
    }

    return best || { segmentIndex: lo, point: coords[lo], dist: Infinity, t: 0 };
  }

  // ─── Maneuver tracking ──────────────────────────────────────────────

  /** Find the maneuver that owns a given segment index. */
  function findManeuverForSegment(segIdx) {
    var maneuvers = route.maneuvers;
    for (var i = 0; i < maneuvers.length; i++) {
      if (segIdx >= maneuvers[i].begin_shape_index &&
          segIdx < maneuvers[i].end_shape_index) {
        return i;
      }
    }
    // Past the last maneuver — return final
    return maneuvers.length - 1;
  }

  /** Distance from snap point to the start of a maneuver (its begin_shape_index). */
  function distanceToManeuver(snap, maneuverIdx) {
    if (maneuverIdx >= route.maneuvers.length) return 0;
    var targetIdx = route.maneuvers[maneuverIdx].begin_shape_index;
    return distanceToCoordIndex(snap.segmentIndex, snap.t, targetIdx);
  }

  // ─── Speed ratio for ETA adjustment ─────────────────────────────────

  function recordSpeed(actualSpeed, expectedSpeed) {
    var now = Date.now();
    speedHistory.push({ time: now, actual: actualSpeed, expected: expectedSpeed });
    // Prune entries older than the window
    var cutoff = now - SPEED_HISTORY_WINDOW * 1000;
    while (speedHistory.length > 0 && speedHistory[0].time < cutoff) {
      speedHistory.shift();
    }
  }

  /** Rolling ratio of actual/expected speed over the window. Returns 1.0 if no data. */
  function speedRatio() {
    if (speedHistory.length < 5) return 1.0;
    var sumActual = 0, sumExpected = 0;
    for (var i = 0; i < speedHistory.length; i++) {
      sumActual += speedHistory[i].actual;
      sumExpected += speedHistory[i].expected;
    }
    if (sumExpected === 0) return 1.0;
    var ratio = sumActual / sumExpected;
    // Clamp to reasonable range
    return Math.max(0.2, Math.min(3.0, ratio));
  }

  // ─── Voice announcements ────────────────────────────────────────────

  function announce(text, key) {
    if (muted || !text || !onVoiceCb) return false;
    var now = Date.now();
    if (now - lastAnnouncementTime < VOICE_COOLDOWN) return false;
    lastAnnouncementTime = now;
    if (key) announcedSet[key] = true;
    onVoiceCb(text);
    return true;
  }

  /**
   * Check if we should fire a voice announcement for the upcoming maneuver.
   * Uses three distance thresholds (far, medium, near) based on costing.
   */
  function checkVoice(snap) {
    if (!route || !route.maneuvers) return;

    // Speed gate: suppress below 2 m/s UNLESS within 50m of next maneuver
    if (lastSpeed < VOICE_SPEED_GATE) {
      var nextCheckIdx = currentManeuverIdx + 1;
      if (nextCheckIdx < route.maneuvers.length) {
        var distCheck = distanceToManeuver(snap, nextCheckIdx);
        if (distCheck > VOICE_NEAR_ANNOUNCE_DISTANCE) return;
      } else {
        return;
      }
    }

    var thresholds = VOICE_THRESHOLDS[route.costing] || VOICE_THRESHOLDS.auto;
    var nextIdx = currentManeuverIdx + 1;
    if (nextIdx >= route.maneuvers.length) return;

    var distToNext = distanceToManeuver(snap, nextIdx);
    var m = route.maneuvers[nextIdx];

    for (var ti = 0; ti < thresholds.length; ti++) {
      var key = nextIdx + "-" + ti;
      if (announcedSet[key]) continue;

      if (distToNext <= thresholds[ti]) {
        var text;
        var isNearTier = ti === thresholds.length - 1;
        if (!isNearTier) {
          // Pre-final tier(s): use alert instruction ("in X meters, turn left").
          // Threshold-count-agnostic: works with [far, near] OR [far, medium, near].
          text = m.verbal_transition_alert_instruction || m.instruction;
        } else {
          // Near (final) tier: use pre-transition instruction ("turn left onto Oak").
          text = m.verbal_pre_transition_instruction || m.instruction;

          // Next-after-next: if maneuver[current+2] is close, append it.
          // Preserves the "turn left, then right" chain readout on the
          // near-tier only so it doesn't duplicate across tiers.
          var afterIdx = nextIdx + 1;
          if (afterIdx < route.maneuvers.length) {
            var distBetween = distanceToManeuver(
              { segmentIndex: m.begin_shape_index, t: 0 }, afterIdx
            );
            if (distBetween <= NEXT_AFTER_NEXT_DISTANCE) {
              var afterM = route.maneuvers[afterIdx];
              text += ", then " + (afterM.instruction || "");
            }
          }
        }

        if (!announce(text, key)) break;
      }
    }
  }

  // ─── Dead reckoning ─────────────────────────────────────────────────

  /**
   * Extrapolate position along the route polyline at last-known speed.
   * Returns a snap-like object or null if we can't extrapolate.
   */
  function deadReckon(elapsed) {
    if (!lastSnap || lastSpeed <= 0) return null;
    if (elapsed > DEAD_RECKON_MAX) return null;

    var extraDist = lastSpeed * (elapsed / 1000);
    var coords = route.coords;
    var segIdx = lastSnap.segmentIndex;

    // Start from the snapped position along the route
    var remaining = extraDist;
    // Distance left in current segment
    var segLen = segmentDistances[segIdx];
    var usedInSeg = segLen * lastSnap.t;
    var leftInSeg = segLen - usedInSeg;

    if (remaining <= leftInSeg) {
      // Still in current segment
      var newT = lastSnap.t + remaining / segLen;
      var frac = newT;
      var lng = coords[segIdx][0] + frac * (coords[segIdx + 1][0] - coords[segIdx][0]);
      var lat = coords[segIdx][1] + frac * (coords[segIdx + 1][1] - coords[segIdx][1]);
      return {
        segmentIndex: segIdx,
        snappedLng: lng,
        snappedLat: lat,
        distanceFromRoute: 0,
        alongRouteDistance: lastSnap.alongRouteDistance + remaining,
        t: newT
      };
    }

    remaining -= leftInSeg;
    segIdx++;

    while (segIdx < coords.length - 1 && remaining > 0) {
      segLen = segmentDistances[segIdx];
      if (remaining <= segLen) {
        var t = remaining / segLen;
        var lng2 = coords[segIdx][0] + t * (coords[segIdx + 1][0] - coords[segIdx][0]);
        var lat2 = coords[segIdx][1] + t * (coords[segIdx + 1][1] - coords[segIdx][1]);
        return {
          segmentIndex: segIdx,
          snappedLng: lng2,
          snappedLat: lat2,
          distanceFromRoute: 0,
          alongRouteDistance: lastSnap.alongRouteDistance + extraDist,
          t: t
        };
      }
      remaining -= segLen;
      segIdx++;
    }

    // Reached end of route
    var last = coords[coords.length - 1];
    return {
      segmentIndex: coords.length - 2,
      snappedLng: last[0],
      snappedLat: last[1],
      distanceFromRoute: 0,
      alongRouteDistance: cumulativeDistances[coords.length - 1],
      t: 1
    };
  }

  // ─── Build state object ─────────────────────────────────────────────

  function buildState(snap, estimated) {
    var distRemain = remainingDistance(snap.segmentIndex, snap.t);
    var totalDist = route.totalDistance || cumulativeDistances[route.coords.length - 1];
    var fraction = totalDist > 0 ? distRemain / totalDist : 0;
    var baseTimeRemain = (route.totalTime || 0) * fraction;
    var ratio = speedRatio();
    var timeRemain = ratio > 0 ? baseTimeRemain / ratio : baseTimeRemain;

    var eta = new Date(Date.now() + timeRemain * 1000);

    var nextM = null;
    var afterNextM = null;
    var nextIdx = currentManeuverIdx + 1;

    if (nextIdx < route.maneuvers.length) {
      var m = route.maneuvers[nextIdx];
      var dToNext = distanceToManeuver(snap, nextIdx);
      nextM = {
        instruction: m.instruction,
        type: m.type,
        distanceTo: dToNext,
        lanes: m.lanes || null
      };

      // After-next maneuver if within threshold
      var afterIdx = nextIdx + 1;
      if (afterIdx < route.maneuvers.length) {
        var dToAfter = distanceToManeuver(snap, afterIdx);
        if (dToAfter <= NEXT_AFTER_NEXT_DISTANCE) {
          var am = route.maneuvers[afterIdx];
          afterNextM = {
            instruction: am.instruction,
            type: am.type,
            distanceTo: dToAfter
          };
        }
      }
    }

    return {
      state: state,
      currentManeuverIndex: currentManeuverIdx,
      nextManeuver: nextM,
      afterNextManeuver: afterNextM,
      snappedPosition: { lng: snap.snappedLng, lat: snap.snappedLat },
      distanceRemaining: distRemain,
      timeRemaining: timeRemain,
      eta: eta,
      heading: headingValid ? lastValidHeading : null,
      headingValid: headingValid,
      speed: lastSpeed,
      estimated: !!estimated,
      gpsStale: (Date.now() - lastGPSTime) > GPS_STALE_TIMEOUT,
      offRouteDistance: snap.distanceFromRoute
    };
  }

  function emitUpdate(stateObj) {
    if (onUpdateCb) onUpdateCb(stateObj);
  }

  // ─── Core tick (called on each GPS update) ──────────────────────────

  function tick(gpsData) {
    if (state === "idle" || state === "arrived") return;

    var now = Date.now();
    var lng = gpsData.longitude;
    var lat = gpsData.latitude;
    var gpsHeading = gpsData.heading;
    var gpsSpeed = gpsData.speed || 0; // m/s

    // Speed gate for heading
    lastSpeed = gpsSpeed;
    if (gpsSpeed >= HEADING_SPEED_GATE && gpsHeading !== null && gpsHeading !== undefined) {
      lastValidHeading = gpsHeading;
      headingValid = true;
    } else {
      headingValid = false;
    }

    // Snap to route
    var snap = snapToRoute(lng, lat, headingValid ? lastValidHeading : null);
    lastSnap = snap;
    drActive = false;

    // Update maneuver index
    currentManeuverIdx = findManeuverForSegment(snap.segmentIndex);

    // Record speed for ETA adjustment
    if (route.totalDistance > 0 && route.totalTime > 0) {
      var expectedSpeed = route.totalDistance / route.totalTime;
      recordSpeed(gpsSpeed, expectedSpeed);
    }

    // ── State transitions ──

    if (state === "joining") {
      if (snap.distanceFromRoute <= JOIN_THRESHOLD) {
        state = "navigating";
      } else if (snap.distanceFromRoute > JOIN_TOLERANCE) {
        if (joinStartTime === 0) {
          joinStartTime = now;
        } else if (now - joinStartTime > 15000) {
          triggerReroute(lat, lng);
          joinStartTime = 0;
        }
      } else {
        joinStartTime = 0;
      }
      emitUpdate(buildState(snap, false));
      return;
    }

    if (state === "rerouting") {
      // While rerouting, keep emitting position updates but don't trigger more reroutes
      emitUpdate(buildState(snap, false));
      return;
    }

    // state === "navigating"

    // Check arrival
    var dest = route.coords[route.coords.length - 1];
    var distToDest = haversine([lng, lat], dest);
    var nearEnd = snap.segmentIndex >= route.coords.length - 1 - ARRIVAL_SEGMENTS;
    if (distToDest <= ARRIVAL_GEOFENCE && nearEnd) {
      state = "arrived";
      emitUpdate(buildState(snap, false));
      if (onArrivalCb) onArrivalCb();
      return;
    }

    // Off-route detection with hysteresis
    var offRouteThreshold = inOffRouteState ? OFF_ROUTE_EXIT_THRESHOLD : OFF_ROUTE_THRESHOLD;
    var isOffRoute = snap.distanceFromRoute > offRouteThreshold;

    offRouteHistory.push(isOffRoute);
    if (offRouteHistory.length > OFF_ROUTE_WINDOW) offRouteHistory.shift();

    if (!inOffRouteState && isOffRoute) {
      inOffRouteState = true;
    } else if (inOffRouteState && snap.distanceFromRoute <= OFF_ROUTE_EXIT_THRESHOLD) {
      inOffRouteState = false;
      offRouteHistory = [];
    }

    if (inOffRouteState) {
      var offCount = 0;
      for (var i = 0; i < offRouteHistory.length; i++) {
        if (offRouteHistory[i]) offCount++;
      }
      if (offCount >= OFF_ROUTE_MIN_COUNT && offRouteHistory.length >= OFF_ROUTE_WINDOW) {
        offRouteHistory = [];
        inOffRouteState = false;
        triggerReroute(lat, lng);
        emitUpdate(buildState(snap, false));
        return;
      }
    }

    // Voice announcements
    checkVoice(snap);

    emitUpdate(buildState(snap, false));
  }

  /** Trigger a reroute request via the onReroute callback. */
  function triggerReroute(lat, lng) {
    var now = Date.now();
    if (now - lastRerouteTime < REROUTE_COOLDOWN) return;
    lastRerouteTime = now;
    state = "rerouting";
    rerouteSeq++;
    rerouteTimeoutId = setTimeout(function () {
      rerouteTimeoutId = null;
      if (state === "rerouting") {
        state = "navigating";
        offRouteHistory = [];
        inOffRouteState = false;
        // Clear the cooldown too — the failure already burned 10 s;
        // don't penalize the user with another 5 s of blocked reroutes.
        lastRerouteTime = 0;
      }
    }, REROUTE_TIMEOUT);

    if (onRerouteCb) {
      onRerouteCb({
        currentLat: lat,
        currentLng: lng,
        remainingWaypoints: route.remainingWaypoints || [],
        costing: route.costing,
        costingOptions: route.costingOptions || null,
        _seq: rerouteSeq // caller passes back to confirmReroute
      });
    }
  }

  // ─── Dead reckoning tick (called when GPS is stale) ─────────────────

  function deadReckonTick() {
    if (state === "idle" || state === "arrived") return;
    if (!lastSnap) return;

    var elapsed = Date.now() - lastGPSTime;
    if (elapsed < GPS_STALE_TIMEOUT) return;

    var drSnap = deadReckon(elapsed);
    if (!drSnap) return;

    drActive = true;
    currentManeuverIdx = findManeuverForSegment(drSnap.segmentIndex);
    checkVoice(drSnap);
    emitUpdate(buildState(drSnap, true));
  }

  // ─── Stale GPS checker (runs on interval) ───────────────────────────

  var staleInterval = null;

  function startStaleChecker() {
    if (staleInterval) return;
    staleInterval = setInterval(function () {
      if (state === "idle" || state === "arrived") return;
      var elapsed = Date.now() - lastGPSTime;
      if (elapsed >= GPS_STALE_TIMEOUT) {
        deadReckonTick();
      }
    }, 1000);
  }

  function stopStaleChecker() {
    if (staleInterval) {
      clearInterval(staleInterval);
      staleInterval = null;
    }
  }

  // ─── Public API ─────────────────────────────────────────────────────

  function reset() {
    route = null;
    state = "idle";
    lastIndex = 0;
    currentManeuverIdx = 0;
    offRouteHistory = [];
    inOffRouteState = false;
    lastRerouteTime = 0;
    rerouteSeq = 0;
    joinStartTime = 0;
    lastGPS = null;
    lastGPSTime = 0;
    lastValidHeading = 0;
    headingValid = false;
    lastSpeed = 0;
    lastSnap = null;
    drActive = false;
    announcedSet = {};
    lastAnnouncementTime = 0;
    speedHistory = [];
    segmentDistances = null;
    cumulativeDistances = null;
    if (rerouteTimeoutId) { clearTimeout(rerouteTimeoutId); rerouteTimeoutId = null; }
    stopStaleChecker();
  }

  window.GeographicaNav = {

    /**
     * Enter navigation mode with a prepared route.
     * If GPS is >50m from route start, enters JOINING state.
     */
    start: function (routeData) {
      var savedGPS = window._geographicaGPSData;
      reset();
      route = routeData;
      precomputeDistances();
      startStaleChecker();

      if (savedGPS) {
        var lng = parseFloat(savedGPS.lon || savedGPS.lng || savedGPS.longitude);
        var lat = parseFloat(savedGPS.lat || savedGPS.latitude);
        if (!isNaN(lng) && !isNaN(lat)) {
          var snap = snapToRoute(lng, lat, null);
          lastSnap = snap;
          lastGPS = { latitude: lat, longitude: lng, heading: savedGPS.heading || 0, speed: savedGPS.speed || 0 };
          lastGPSTime = Date.now();
          if (snap.distanceFromRoute > JOIN_THRESHOLD) {
            state = "joining";
            joinStartTime = Date.now();
          } else {
            state = "navigating";
          }
          emitUpdate(buildState(snap, false));
          return;
        }
      }

      state = "joining";
      joinStartTime = Date.now();
      emitUpdate(buildState({
        segmentIndex: 0, snappedLng: route.coords[0][0],
        snappedLat: route.coords[0][1], distanceFromRoute: 0,
        alongRouteDistance: 0, t: 0
      }, false));
    },

    /** Exit navigation mode, return to idle. */
    stop: function () {
      reset();
    },

    /**
     * Feed a GPS update into the engine. Called at ~1 Hz.
     * gpsData: { latitude, longitude, heading, speed, timestamp }
     */
    updateGPS: function (data) {
      // Dedup on (lat, lng): the UI polls feedGPS every 500 ms but the
      // GPS source is ~1 Hz, so half the ticks carry an unchanged
      // position. The off-route hysteresis window (5-tick, 3-of-5) is
      // designed for 1 Hz; duplicate ticks would fill it in half the
      // intended time and cause false reroutes while stationary. (B7)
      //
      // We still refresh lastGPSTime so the stale-checker doesn't fire
      // DR on a stationary-but-fresh-GPS vehicle.
      var positionChanged = !lastGPS ||
        lastGPS.latitude !== data.latitude ||
        lastGPS.longitude !== data.longitude;

      lastGPS = data;
      lastGPSTime = Date.now();

      if (state !== "idle" && positionChanged) {
        tick(data);
      }
    },

    /**
     * Accept a new route after a reroute. The caller fetches the new route
     * and passes it here. seq must match the _seq from the reroute callback
     * to prevent stale reroutes from being applied.
     */
    applyReroute: function (routeData, seq) {
      // Ignore stale reroute responses
      if (seq !== rerouteSeq) return;
      if (rerouteTimeoutId) { clearTimeout(rerouteTimeoutId); rerouteTimeoutId = null; }

      route = routeData;
      lastIndex = 0;
      currentManeuverIdx = 0;
      offRouteHistory = [];
      inOffRouteState = false;
      // Full reset: old keys refer to a route that no longer exists.
      // Voice cooldown also resets so the new route's first announcement
      // isn't suppressed by the 5 s cooldown from the pre-reroute one.
      announcedSet = {};
      lastAnnouncementTime = 0;
      speedHistory = [];
      precomputeDistances();

      state = "navigating";

      if (lastGPS) {
        tick(lastGPS);
      }
    },

    /** Toggle voice announcements. */
    setMuted: function (val) {
      muted = !!val;
    },

    /** Get current navigation state snapshot. */
    getState: function () {
      if (state === "idle" || !route) {
        return { state: "idle", currentManeuverIndex: 0, nextManeuver: null,
          afterNextManeuver: null, snappedPosition: null, distanceRemaining: 0,
          timeRemaining: 0, eta: null, heading: 0, headingValid: false,
          speed: 0, estimated: false, gpsStale: true, offRouteDistance: 0 };
      }
      var snap = lastSnap || {
        segmentIndex: 0, snappedLng: route.coords[0][0],
        snappedLat: route.coords[0][1], distanceFromRoute: 0,
        alongRouteDistance: 0, t: 0
      };
      return buildState(snap, drActive);
    },

    /** Register callback for state updates (called on every GPS tick). */
    onUpdate: function (cb) { onUpdateCb = cb; },

    /** Register callback for reroute requests. */
    onReroute: function (cb) { onRerouteCb = cb; },

    /** Register callback for arrival. */
    onArrival: function (cb) { onArrivalCb = cb; },

    /** Register callback for voice announcement text. */
    onVoice: function (cb) { onVoiceCb = cb; }
  };

  // Test hook: expose tuning constants so tests can assert on the
  // band-aid threshold shape without re-parsing the source. No-op in
  // production (only read by unit tests). Remove when the TTM redesign
  // lands and replaces the threshold-distance model entirely.
  window._geographicaNavEngineInternals = {
    VOICE_THRESHOLDS: VOICE_THRESHOLDS,
    VOICE_COOLDOWN: VOICE_COOLDOWN,
    VOICE_SPEED_GATE: VOICE_SPEED_GATE,
    // TTM constants (spec v2) — old constants above are removed in T10:
    VOICE_TTM: VOICE_TTM,
    VOICE_DISTANCE_FLOOR: VOICE_DISTANCE_FLOOR,
    MIN_SPEED_FLOOR: MIN_SPEED_FLOOR,
    SPEED_WINDOW_SIZE: SPEED_WINDOW_SIZE,
    MAX_SPEED_DELTA_PER_TICK: MAX_SPEED_DELTA_PER_TICK
  };

})();
