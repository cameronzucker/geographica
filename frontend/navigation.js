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

  var NEXT_AFTER_NEXT_DISTANCE = 500; // meters

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
  var suppressVoiceOnNextTick = false;
  var announcedSet = {};      // key: "maneuverIdx-threshold" -> true

  // Speed smoothing (spec v2 §4.2) — median-of-3 with outlier clamp.
  // MAX_SPEED_DELTA_PER_TICK rejects samples that differ from the prior median
  // by a physically-implausible amount. Catches GPS multipath bursts that a
  // median alone cannot reject.
  var speedSamples = [];

  function pushSpeedSample(s) {
    var clamped = (typeof s === 'number' && s >= 0 && isFinite(s)) ? s : 0;
    if (speedSamples.length >= 1) {
      var priorMedian = speedMedian();
      if (Math.abs(clamped - priorMedian) > MAX_SPEED_DELTA_PER_TICK) {
        return; // drop physically-implausible outlier
      }
    }
    speedSamples.push(clamped);
    if (speedSamples.length > SPEED_WINDOW_SIZE) speedSamples.shift();
  }

  function speedMedian() {
    if (speedSamples.length === 0) return MIN_SPEED_FLOOR;
    var sorted = speedSamples.slice().sort(function (a, b) { return a - b; });
    return sorted[Math.floor(sorted.length / 2)];
  }

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

  /**
   * Check if we should fire a voice announcement for the upcoming maneuver.
   * TTM algorithm (spec v2 §4.3): ttm = distToNext / speedMedian.
   * Two tiers per maneuver: far (alert) and near (pre-transition).
   * D1 suppression: when near fires, far is also marked to skip duplicates.
   */
  function checkVoice(snap) {
    if (suppressVoiceOnNextTick) {
      suppressVoiceOnNextTick = false;
      return;
    }
    if (!route || !route.maneuvers) return;

    var nextIdx = currentManeuverIdx + 1;
    if (nextIdx >= route.maneuvers.length) return;

    var m = route.maneuvers[nextIdx];
    var costing = route.costing || "auto";
    var ttmPair = VOICE_TTM[costing] || VOICE_TTM.auto;
    var floor = VOICE_DISTANCE_FLOOR[costing] || VOICE_DISTANCE_FLOOR.auto;

    // distanceToManeuver can return negative on overshoot / U-turn / GPS
    // jitter at maneuver boundaries. Guard by early-returning on AT-or-past
    // — we don't want to fire near-tier for a maneuver the driver is
    // crossing right now; findManeuverForSegment() advances currentManeuverIdx
    // on the next tick.
    var distToNext = distanceToManeuver(snap, nextIdx);
    if (distToNext <= 0) return;

    var speed = Math.max(speedMedian(), MIN_SPEED_FLOOR);
    var ttm = distToNext / speed;

    var farKey = nextIdx + "-far";
    var nearKey = nextIdx + "-near";

    var nearWouldFire = !announcedSet[nearKey] &&
      (ttm <= ttmPair[1] || distToNext <= floor);
    var farWouldFire = !announcedSet[farKey] && ttm <= ttmPair[0];

    if (nearWouldFire) {
      var text = m.verbal_pre_transition_instruction || m.instruction || "";

      // Valhalla bakes its own continuation into verbal_pre_transition in two
      // shapes when the maneuver is part of a quick-succession sequence:
      //   (a) trailing ". Then X." — current maneuver's vpt already ends with
      //       ", Then turn right onto Oak Road." pre-announcing the next turn.
      //       Our chain-append below would then re-announce X — doubled speech.
      //   (b) leading "Then turn left onto Union Hills Drive." — current
      //       maneuver's vpt is phrased as a continuation of a prior prompt.
      //       When I11 already chain-pre-announced this maneuver, the leading
      //       "Then" sounds like a new instruction to the driver who just
      //       heard it 3-8s ago in the prior near-tier's chain.
      // Strip both, in order. (a) first so (b) can't accidentally match the
      // sentence-boundary "Then"; (b) after to normalize the leading token.
      text = text.replace(/\.\s*Then\s+[^.]*\.?\s*$/i, '.');
      text = text.replace(/^Then\s+/i, '');
      if (text.length > 0) {
        text = text.charAt(0).toUpperCase() + text.slice(1);
      }

      // Next-after-next chain — preserved from prior behavior.
      // Chain extension (I11): when the chain actually appends, mark
      // announcedSet[(afterIdx)-far] so the next-after-next maneuver's
      // far-tier is suppressed on subsequent ticks. The chain prompt
      // already informally announced the upcoming turn; firing its
      // own "In 80m, turn …" 3-8 seconds later duplicates information
      // the driver just heard (the 40-90m mixed-spacing cluster case).
      var afterIdx = nextIdx + 1;
      if (afterIdx < route.maneuvers.length) {
        var distBetween = distanceToManeuver(
          { segmentIndex: m.begin_shape_index, t: 0 }, afterIdx
        );
        if (distBetween <= NEXT_AFTER_NEXT_DISTANCE) {
          var afterText = route.maneuvers[afterIdx].instruction || "";
          if (afterText) {
            // Strip trailing period from base text so the comma-chain reads
            // naturally as one sentence ("X, then Y" not "X., then Y").
            text = text.replace(/\.\s*$/, '') + ", then " + afterText;
            announcedSet[afterIdx + "-far"] = true;  // I11 chain extension
          }
        }
      }
      announcedSet[nearKey] = true;
      announcedSet[farKey] = true;  // D1 suppression
      if (!muted && text && onVoiceCb) {
        if (typeof window !== 'undefined' && window._geographicaTTMDebug) {
          (window._geographicaTTMDebugLog = window._geographicaTTMDebugLog || []).push({
            timestamp: Date.now(),
            maneuverIdx: nextIdx,
            tier: 'near',
            distToNext: distToNext,
            ttm: ttm,
            // Always false: re-tick suppression early-returns at the top of
            // checkVoice before reaching this branch. If true ever appears in
            // a field-test log, suppressVoiceOnNextTick semantics broke.
            onRerouteRetick: false
          });
        }
        onVoiceCb(text);
      }
      return;
    }

    if (farWouldFire) {
      var farText = m.verbal_transition_alert_instruction || m.instruction || "";
      announcedSet[farKey] = true;
      if (!muted && farText && onVoiceCb) {
        if (typeof window !== 'undefined' && window._geographicaTTMDebug) {
          (window._geographicaTTMDebugLog = window._geographicaTTMDebugLog || []).push({
            timestamp: Date.now(),
            maneuverIdx: nextIdx,
            tier: 'far',
            distToNext: distToNext,
            ttm: ttm,
            // Always false: re-tick suppression early-returns at the top of
            // checkVoice before reaching this branch. If true ever appears in
            // a field-test log, suppressVoiceOnNextTick semantics broke.
            onRerouteRetick: false
          });
        }
        onVoiceCb(farText);
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
    pushSpeedSample(gpsSpeed);
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
    var scheduledSeq = rerouteSeq; // R2 F2.1: capture at scheduling time.
    rerouteTimeoutId = setTimeout(function () {
      rerouteTimeoutId = null;
      // Only reset if the seq we captured still matches — prevents a late
      // timeout from clobbering a just-applied reroute's state.
      if (scheduledSeq !== rerouteSeq) return;
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
    // G11 (spec v2): dead-reckoning is position-only. No voice — DR cannot
    // reliably distinguish a legitimate TTM threshold crossing from an
    // extrapolation artifact, and pre-locking announcedSet keys would
    // silently skip prompts on GPS recovery.
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
    suppressVoiceOnNextTick = false;
    speedSamples = [];
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

      // Advance rerouteSeq: any in-flight timeout that captured the old seq
      // will now see scheduledSeq !== rerouteSeq and bail out harmlessly.
      // Also clear lastRerouteTime so the next legitimate off-route event
      // is not blocked by the cooldown that was set when the reroute fired.
      rerouteSeq++;
      lastRerouteTime = 0;

      route = routeData;
      lastIndex = 0;
      currentManeuverIdx = 0;
      offRouteHistory = [];
      inOffRouteState = false;
      // Full reset: old keys refer to a route that no longer exists.
      // announcedSet clears so TTM tiers re-arm on the new route.
      announcedSet = {};
      speedHistory = [];
      precomputeDistances();

      state = "navigating";

      // suppressVoiceOnNextTick: the re-tick below fires checkVoice which
      // would announce from a 1-sample warmup window at the worst moment.
      // Skip voice on this synthetic tick; the next real GPS update fires
      // normally. (R1 F1.3)
      suppressVoiceOnNextTick = true;
      if (lastGPS) tick(lastGPS);

      // Clear speedSamples AFTER the re-tick so the single warmup sample
      // pushed by tick() does not persist into the new route's smoothing
      // window. On the first real GPS update the window starts fresh.
      speedSamples = [];
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

  // Test hook: expose tuning constants + minimal state inspectors so tests
  // can assert on behavior without re-parsing the source. No-op in production
  // (only read by unit tests).
  window._geographicaNavEngineInternals = {
    VOICE_TTM: VOICE_TTM,
    VOICE_DISTANCE_FLOOR: VOICE_DISTANCE_FLOOR,
    MIN_SPEED_FLOOR: MIN_SPEED_FLOOR,
    SPEED_WINDOW_SIZE: SPEED_WINDOW_SIZE,
    MAX_SPEED_DELTA_PER_TICK: MAX_SPEED_DELTA_PER_TICK,
    _getSpeedSamples: function () { return Array.from(speedSamples); },
    _speedMedian: function () { return speedMedian(); },
    _getAnnouncedKeys: function () { return Object.keys(announcedSet).sort(); }
  };

})();
