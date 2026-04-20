/* =====================================================================
   Geographica — Navigation UI Integration
   =====================================================================
   Bridges GeographicaNav (navigation.js engine) with the DOM and
   MapLibre map. Loaded after app.js and navigation.js.
   ===================================================================== */

(function () {
  'use strict';

  // =====================================================================
  //  STATE
  // =====================================================================

  var map = null;
  var nav = null;                   // GeographicaNav instance
  var active = false;               // is navigation running?
  var muted = false;                // voice muted?
  var speechAvailable = false;      // Web Speech API available?
  var autoCenterPaused = false;     // manual pan pauses auto-center
  var autoCenterTimer = null;       // timer to resume auto-center
  var gpsHeartbeatTimer = null;     // 3-second GPS timeout
  var savedMapState = null;         // saved map state on nav enter
  var savedTerrainChecked = false;
  var savedHillshadeChecked = false;
  var useImperial = true;           // synced from app.js unit radios

  var AUTO_CENTER_PAUSE_MS = 10000;
  var GPS_HEARTBEAT_MS = 3000;
  var lastNavPaddingTop = 0;
  var PADDING_RECALC_THRESHOLD = 5; // px -- ignore changes smaller than this
  var rerouteRetries = 0;
  var MAX_REROUTE_RETRIES = 3;
  var pendingRerouteTimeouts = [];
  var rerouteAbortController = null;
  var lastNavState = null;  // latest state from engine callback
  var lastGPSSignature = null;

  // =====================================================================
  //  DOM REFS
  // =====================================================================

  var overlay, instrMain, instrDist, instrAfter, iconEl;
  var statusDist, statusEta, statusTime, statusSpeed;
  var banner, startBtn, stopBtn, recenterBtn, muteBtn;

  // =====================================================================
  //  INITIALIZATION
  // =====================================================================

  function init() {
    map = window._geographicaMap;
    if (!map) {
      // Retry until map is ready
      setTimeout(init, 200);
      return;
    }

    // Cache DOM refs
    overlay     = document.getElementById('nav-overlay');
    // Prevent nav overlay clicks from reaching sidebar overlay behind it
    overlay.addEventListener('click', function (e) { e.stopPropagation(); });
    instrMain   = document.getElementById('nav-instruction-main');
    instrDist   = document.getElementById('nav-instruction-distance');
    instrAfter  = document.getElementById('nav-instruction-after');
    iconEl      = document.getElementById('nav-icon');
    statusDist  = document.getElementById('nav-remaining-dist');
    statusEta   = document.getElementById('nav-eta');
    statusTime  = document.getElementById('nav-remaining-time');
    statusSpeed = document.getElementById('nav-speed');
    banner      = document.getElementById('nav-banner');
    startBtn    = document.getElementById('start-nav-btn');
    stopBtn     = document.getElementById('stop-nav-btn');
    recenterBtn = document.getElementById('nav-recenter-btn');

    // Check speech synthesis
    speechAvailable = !!(window.speechSynthesis && window.SpeechSynthesisUtterance);

    // Load mute preference
    muted = localStorage.getItem('nav-muted') === 'true';

    // Create mute button inside overlay
    createMuteButton();

    // Sync unit preference
    syncUnits();
    document.querySelectorAll('input[name="units"]').forEach(function (r) {
      r.addEventListener('change', syncUnits);
    });

    // Button events
    startBtn.addEventListener('click', startNavigation);
    stopBtn.addEventListener('click', stopNavigation);
    recenterBtn.addEventListener('click', recenter);

    // Show start button when a route is calculated
    observeRouteAvailability();

    // Listen for manual pan during navigation
    map.on('dragstart', onManualPan);
    map.on('wheel', onManualPan);

    // Compass click pauses auto-center during navigation
    var compassBtn = document.getElementById('compass-north-btn');
    if (compassBtn) {
      compassBtn.addEventListener('click', function () {
        if (active) {
          onManualPan();  // pause auto-center for 10 seconds
        }
      });
    }
  }

  function syncUnits() {
    var checked = document.querySelector('input[name="units"]:checked');
    useImperial = checked ? checked.value === 'imperial' : true;
  }

  // =====================================================================
  //  ROUTE AVAILABILITY OBSERVER
  // =====================================================================

  function observeRouteAvailability() {
    // Watch for export button becoming visible as a signal that a route exists
    var exportBtn = document.getElementById('export-route-btn');
    if (!exportBtn) return;

    var observer = new MutationObserver(function () {
      if (!exportBtn.classList.contains('hidden') && !active) {
        startBtn.classList.remove('hidden');
      } else if (exportBtn.classList.contains('hidden')) {
        startBtn.classList.add('hidden');
        if (active) stopNavigation();
      }
    });
    observer.observe(exportBtn, { attributes: true, attributeFilter: ['class'] });
  }

  // =====================================================================
  //  START / STOP NAVIGATION
  // =====================================================================

  function startNavigation() {
    var trip = window._geographicaLastTrip;
    if (!trip || !window.GeographicaNav) return;

    // Build route data for engine
    var routeData = buildRouteData(trip);
    if (!routeData) return;

    // Save map state
    saveMapState();

    // Register engine callbacks and start navigation
    nav = window.GeographicaNav;
    nav.onUpdate(onNavUpdate);
    nav.onVoice(onVoice);
    nav.onArrival(onArrival);
    nav.onReroute(onReroute);
    nav.start(routeData);
    nav.setMuted(muted);  // B14: sync UI mute preference into engine

    active = true;
    document.body.classList.add('nav-active');

    // Prime speech audio on user gesture
    primeSpeech();

    // UI swap
    startBtn.classList.add('hidden');
    stopBtn.classList.remove('hidden');
    overlay.classList.remove('hidden');

    // Disable terrain/hillshade during navigation
    disableTerrain();

    // Start GPS feed loop
    startGPSFeed();

    // Enter heads-up view
    var gps = window._geographicaGPSData;
    if (gps) {
      var lng = parseFloat(gps.lon || gps.lng || gps.longitude);
      var lat = parseFloat(gps.lat || gps.latitude);
      if (!isNaN(lng) && !isNaN(lat)) {
        map.easeTo({
          center: [lng, lat],
          zoom: 17,
          pitch: 60,
          bearing: gps.heading || 0,
          duration: 800,
          padding: getNavPadding()
        });
      }
    }
  }

  function stopNavigation() {
    if (nav && nav.stop) nav.stop();
    nav = null;
    active = false;
    document.body.classList.remove('nav-active');

    // Cancel any pending speech
    if (speechAvailable) speechSynthesis.cancel();

    // UI swap
    stopBtn.classList.add('hidden');
    overlay.classList.add('hidden');
    banner.classList.add('hidden');
    recenterBtn.classList.add('hidden');

    // Show start if route still exists
    var exportBtn = document.getElementById('export-route-btn');
    if (exportBtn && !exportBtn.classList.contains('hidden')) {
      startBtn.classList.remove('hidden');
    }

    // Re-enable terrain
    enableTerrain();

    // Restore map state
    restoreMapState();

    // Clear timers
    clearTimeout(autoCenterTimer);
    clearTimeout(gpsHeartbeatTimer);
    if (gpsFeedInterval) clearInterval(gpsFeedInterval);
    gpsFeedInterval = null;
    autoCenterPaused = false;
    lastNavPaddingTop = 0;
    lastNavState = null;
    lastGPSSignature = null;

    // B12: cancel in-flight reroute fetches and clear pending retries.
    if (rerouteAbortController) {
      rerouteAbortController.abort();
      rerouteAbortController = null;
    }
    pendingRerouteTimeouts.forEach(function (id) { clearTimeout(id); });
    pendingRerouteTimeouts = [];
    rerouteRetries = 0;
  }

  // =====================================================================
  //  BUILD ROUTE DATA FROM VALHALLA TRIP
  // =====================================================================

  function buildRouteData(trip) {
    if (!trip || !trip.legs) return null;

    var allCoords = [];
    var allManeuvers = [];
    var shapeOffset = 0;

    trip.legs.forEach(function (leg, i) {
      var coords = decodePolyline(leg.shape);
      var indexAdjust = 0;
      // Skip first point of subsequent legs (shared with previous leg's last point)
      if (i > 0 && coords.length > 0) {
        coords = coords.slice(1);
        indexAdjust = 1; // Valhalla indices are 1 too high for the sliced array
      }
      if (leg.maneuvers) {
        leg.maneuvers.forEach(function (m) {
          var mc = Object.assign({}, m);
          // Clamp at zero before offsetting: a leg-start maneuver has
          // begin_shape_index=0 and we slice off the first coord for
          // legs after the first (indexAdjust=1). Without clamp, the
          // index would land in the previous leg's last segment.
          var beginRaw = Math.max(0, (mc.begin_shape_index || 0) - indexAdjust);
          var endRaw = Math.max(0, (mc.end_shape_index || 0) - indexAdjust);
          mc.begin_shape_index = beginRaw + shapeOffset;
          mc.end_shape_index = endRaw + shapeOffset;
          allManeuvers.push(mc);
        });
      }
      allCoords = allCoords.concat(coords);
      shapeOffset += coords.length; // Use sliced length
    });

    var summary = trip.summary || {};
    // Convert distance from display units to meters for the engine
    var distMeters = (summary.length || 0) * (window._geographicaUseImperial ? 1609.344 : 1000);

    // Extract intermediate waypoints from trip.locations.
    // Valhalla returns: [start, ...throughs, end].
    // Reroute will re-plan from current GPS → throughs → end.
    var locs = trip.locations || [];
    var intermediates = locs.length > 2 ? locs.slice(1, -1) : [];
    var remainingWaypoints = intermediates.map(function (loc) {
      return {
        lat: loc.lat,
        lon: loc.lon,
        type: loc.type || 'through',
      };
    });

    return {
      coords: allCoords,
      maneuvers: allManeuvers,
      summary: summary,
      totalDistance: distMeters,
      totalTime: summary.time || 0,
      costing: trip._costing || 'auto',
      costingOptions: trip._costingOptions || null,
      remainingWaypoints: remainingWaypoints,
    };
  }

  /**
   * Decode an encoded polyline string into an array of [lng, lat] coordinates.
   * Valhalla uses precision 6.
   */
  function decodePolyline(encoded) {
    var coords = [];
    var index = 0;
    var lat = 0;
    var lng = 0;
    var len = encoded.length;

    while (index < len) {
      var b, shift = 0, result = 0;
      do {
        b = encoded.charCodeAt(index++) - 63;
        result |= (b & 0x1f) << shift;
        shift += 5;
      } while (b >= 0x20);
      var dlat = (result & 1) ? ~(result >> 1) : (result >> 1);
      lat += dlat;

      shift = 0;
      result = 0;
      do {
        b = encoded.charCodeAt(index++) - 63;
        result |= (b & 0x1f) << shift;
        shift += 5;
      } while (b >= 0x20);
      var dlng = (result & 1) ? ~(result >> 1) : (result >> 1);
      lng += dlng;

      coords.push([lng / 1e6, lat / 1e6]);
    }
    return coords;
  }

  // =====================================================================
  //  GPS FEED
  // =====================================================================

  var gpsFeedInterval = null;

  function startGPSFeed() {
    if (gpsFeedInterval) clearInterval(gpsFeedInterval);
    gpsFeedInterval = setInterval(feedGPS, 500);
  }

  function feedGPS() {
    if (!active || !nav) return;

    var data = window._geographicaGPSData;
    if (!data) return;

    var lng = parseFloat(data.lon || data.lng || data.longitude);
    var lat = parseFloat(data.lat || data.latitude);
    if (isNaN(lng) || isNaN(lat)) return;

    var heading = data.heading != null ? data.heading : (data.bearing != null ? data.bearing : 0);
    var speed = data.speed || 0; // m/s

    // Feed to engine
    if (nav && nav.updateGPS) {
      nav.updateGPS({
        latitude: lat,
        longitude: lng,
        heading: heading,
        speed: speed,
        accuracy: data.accuracy || 10,
        timestamp: Date.now()
      });
    }

    // GPS heartbeat -- only reset timer when position actually changes
    var sig = lat + ',' + lng;
    if (sig !== lastGPSSignature) {
      lastGPSSignature = sig;
      clearTimeout(gpsHeartbeatTimer);
      gpsHeartbeatTimer = setTimeout(function () {
        showBanner('GPS signal delayed', 'gps-stale');
      }, GPS_HEARTBEAT_MS);
    }

    // Auto-center map if not paused
    if (!autoCenterPaused) {
      var speedMps = speed || 0;
      var zoom = clamp(18 - speedMps * 0.15, 14, 18);
      var navBearing;
      if (lastNavState && lastNavState.headingValid) {
        navBearing = lastNavState.heading;
      } else {
        navBearing = map.getBearing();  // freeze at current bearing
      }

      map.easeTo({
        center: [lng, lat],
        bearing: navBearing,
        zoom: zoom,
        pitch: 60,
        duration: 500,
        padding: getNavPadding()
      });
    }
  }

  // =====================================================================
  //  ENGINE CALLBACKS
  // =====================================================================

  function onNavUpdate(state) {
    if (!active) return;
    lastNavState = state;

    // Read from engine's state object structure:
    // state.nextManeuver: { instruction, type, distanceTo, lanes }
    // state.afterNextManeuver: { instruction, type, distanceTo } | null
    // state.distanceRemaining, state.timeRemaining, state.speed
    // state.state: 'idle'|'joining'|'navigating'|'rerouting'|'arrived' (lowercase)

    var nm = state.nextManeuver;

    // Update instruction card
    if (nm && nm.instruction) {
      instrMain.textContent = nm.instruction;
    }

    // Distance to next maneuver
    if (nm && nm.distanceTo != null) {
      instrDist.textContent = formatNavDistance(nm.distanceTo);
    }

    // After-next hint
    var anm = state.afterNextManeuver;
    if (anm && anm.instruction) {
      instrAfter.textContent = 'then ' + anm.instruction;
      instrAfter.style.display = '';
    } else {
      instrAfter.style.display = 'none';
    }

    // Maneuver icon
    if (nm && nm.type != null) {
      setManeuverIcon(nm.type);
    }

    // Status bar
    if (state.distanceRemaining != null) {
      statusDist.textContent = formatNavDistance(state.distanceRemaining);
    }
    if (state.timeRemaining != null) {
      statusTime.textContent = formatDuration(state.timeRemaining);
      var eta = new Date(Date.now() + state.timeRemaining * 1000);
      statusEta.textContent = 'ETA ' + formatTime(eta);
    }
    if (state.speed != null) {
      if (useImperial) {
        statusSpeed.textContent = Math.round(state.speed * 2.237) + ' mph';
      } else {
        statusSpeed.textContent = Math.round(state.speed * 3.6) + ' km/h';
      }
    }

    // State banners (engine uses lowercase state strings)
    if (state.gpsStale) {
      showBanner('GPS signal delayed', 'gps-stale');
    } else if (state.estimated) {
      showBanner('Estimated position', 'estimated');
    } else if (state.state === 'rerouting') {
      showBanner('Recalculating...', 'recalculating');
    } else if (state.state === 'joining') {
      showBanner('Joining route...', 'joining');
    } else {
      hideBanner();
    }

    document.documentElement.style.setProperty('--nav-overlay-height', overlay.offsetHeight + 'px');
  }

  function onVoice(text) {
    if (!speechAvailable || muted || !text) return;
    speechSynthesis.cancel();
    var utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.0;
    utterance.lang = 'en-US';
    speechSynthesis.speak(utterance);
  }

  function onArrival() {
    onVoice('You have arrived at your destination.');
    setTimeout(stopNavigation, 3000);
  }

  function onReroute(info) {
    showBanner('Recalculating...', 'recalculating');

    // Build Valhalla reroute request from current GPS to destination,
    // preserving remaining waypoints
    var locations = [{ lat: info.currentLat, lon: info.currentLng }];
    if (info.remainingWaypoints) {
      info.remainingWaypoints.forEach(function (wp) {
        locations.push({ lat: wp.lat, lon: wp.lon, type: 'through' });
      });
    }
    // Original destination is the last coord of the current route
    var lastTrip = window._geographicaLastTrip;
    if (lastTrip && lastTrip.locations) {
      var dest = lastTrip.locations[lastTrip.locations.length - 1];
      locations.push({ lat: dest.lat, lon: dest.lon });
    }

    var body = {
      locations: locations,
      costing: info.costing || 'auto',
      directions_options: { units: window._geographicaUseImperial ? 'miles' : 'kilometers' }
    };
    if (info.costingOptions) {
      body.costing_options = info.costingOptions;
    }

    var seq = info._seq;

    rerouteRetries = 0;
    attemptReroute(body, seq, info);
  }

  function attemptReroute(body, seq, info) {
    if (rerouteAbortController) rerouteAbortController.abort();
    rerouteAbortController = new AbortController();
    var signal = rerouteAbortController.signal;

    fetch('/valhalla/route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: signal
    })
    .then(function (res) { return res.json(); })
    .then(function (data) {
      if (signal.aborted) return;
      if (data && data.error) {
        // Valhalla returned 200 with {error: "..."} — no trip field.
        // Treat as a retryable failure, not a silent no-op. (B11)
        throw new Error('Valhalla error: ' + data.error);
      }
      if (data.trip && nav) {
        // Update all four state slots via the unified owner (B2).
        window._geographicaSetActiveRoute(data.trip, {
          refitBounds: false,          // keep camera locked during nav
          costing: info.costing,
          costingOptions: info.costingOptions || null,
        });
        var newRouteData = buildRouteData(data.trip);
        if (newRouteData) {
          rerouteRetries = 0;
          nav.applyReroute(newRouteData, seq);
          hideBanner();
        }
      }
    })
    .catch(function (err) {
      if (err.name === 'AbortError') return;  // silent on user-initiated abort
      console.error('Reroute failed:', err);
      rerouteRetries++;
      if (rerouteRetries <= MAX_REROUTE_RETRIES) {
        var delay = Math.pow(2, rerouteRetries) * 1000; // 2s, 4s, 8s
        var timeoutId = setTimeout(function () {
          attemptReroute(body, seq, info);
        }, delay);
        pendingRerouteTimeouts.push(timeoutId);
      } else {
        rerouteRetries = 0;
        showBanner('Reroute failed \u2014 using current route', 'reroute-failed');
        setTimeout(hideBanner, 5000);
        // Engine timeout will handle state recovery
      }
    });
  }

  // =====================================================================
  //  MAP STATE SAVE / RESTORE
  // =====================================================================

  function saveMapState() {
    savedMapState = {
      center: map.getCenter(),
      zoom: map.getZoom(),
      pitch: map.getPitch(),
      bearing: map.getBearing()
    };
    savedTerrainChecked = document.getElementById('toggle-terrain').checked;
    savedHillshadeChecked = document.getElementById('toggle-hillshade').checked;
  }

  function restoreMapState() {
    if (!savedMapState) return;
    map.easeTo({
      center: savedMapState.center,
      zoom: savedMapState.zoom,
      pitch: savedMapState.pitch,
      bearing: savedMapState.bearing,
      duration: 800,
      // B8: clear the nav-era padding so post-nav fitBounds/flyTo
      // aren't offset into the bottom of the screen.
      padding: { top: 0, bottom: 0, left: 0, right: 0 },
    });
    savedMapState = null;
  }

  function disableTerrain() {
    var terrainCb = document.getElementById('toggle-terrain');
    var hillshadeCb = document.getElementById('toggle-hillshade');

    if (terrainCb && terrainCb.checked) {
      terrainCb.checked = false;
      terrainCb.dispatchEvent(new Event('change'));
    }
    if (hillshadeCb && hillshadeCb.checked) {
      hillshadeCb.checked = false;
      hillshadeCb.dispatchEvent(new Event('change'));
    }

    // Gray out with tooltip
    var terrainLabel = terrainCb ? terrainCb.closest('.checkbox-label') : null;
    var hillshadeLabel = hillshadeCb ? hillshadeCb.closest('.checkbox-label') : null;
    if (terrainLabel) {
      terrainLabel.classList.add('nav-disabled-toggle');
      terrainLabel.title = 'Disabled during navigation';
    }
    if (hillshadeLabel) {
      hillshadeLabel.classList.add('nav-disabled-toggle');
      hillshadeLabel.title = 'Disabled during navigation';
    }
  }

  function enableTerrain() {
    var terrainCb = document.getElementById('toggle-terrain');
    var hillshadeCb = document.getElementById('toggle-hillshade');

    var terrainLabel = terrainCb ? terrainCb.closest('.checkbox-label') : null;
    var hillshadeLabel = hillshadeCb ? hillshadeCb.closest('.checkbox-label') : null;
    if (terrainLabel) {
      terrainLabel.classList.remove('nav-disabled-toggle');
      terrainLabel.title = '';
    }
    if (hillshadeLabel) {
      hillshadeLabel.classList.remove('nav-disabled-toggle');
      hillshadeLabel.title = '';
    }

    // Restore previous state
    if (savedTerrainChecked && terrainCb) {
      terrainCb.checked = true;
      terrainCb.dispatchEvent(new Event('change'));
    }
    if (savedHillshadeChecked && hillshadeCb) {
      hillshadeCb.checked = true;
      hillshadeCb.dispatchEvent(new Event('change'));
    }
  }

  // =====================================================================
  //  MANUAL PAN HANDLING
  // =====================================================================

  function onManualPan() {
    if (!active) return;
    autoCenterPaused = true;
    recenterBtn.classList.remove('hidden');
    clearTimeout(autoCenterTimer);
    autoCenterTimer = setTimeout(function () {
      recenter();
    }, AUTO_CENTER_PAUSE_MS);
  }

  function recenter() {
    autoCenterPaused = false;
    recenterBtn.classList.add('hidden');
    clearTimeout(autoCenterTimer);
    // Snap back to GPS position
    feedGPS();
  }

  // Expose pause/recenter for search integration
  window._navPauseAutoCenter = function () { onManualPan(); };
  window._navRecenter = function () { recenter(); };

  // =====================================================================
  //  VOICE / SPEECH
  // =====================================================================

  function primeSpeech() {
    if (!speechAvailable) return;
    var u = new SpeechSynthesisUtterance('');
    u.volume = 0;
    speechSynthesis.speak(u);
  }

  function createMuteButton() {
    muteBtn = document.createElement('button');
    muteBtn.id = 'nav-mute-btn';
    muteBtn.title = muted ? 'Unmute voice' : 'Mute voice';
    updateMuteIcon();
    muteBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      toggleMute();
    });

    if (!speechAvailable) {
      muteBtn.style.display = 'none';
    }

    overlay.appendChild(muteBtn);
  }

  function toggleMute() {
    muted = !muted;
    if (nav && nav.setMuted) nav.setMuted(muted);
    localStorage.setItem('nav-muted', muted ? 'true' : 'false');
    muteBtn.title = muted ? 'Unmute voice' : 'Mute voice';
    muteBtn.classList.toggle('muted', muted);
    updateMuteIcon();
  }

  function updateMuteIcon() {
    // Build mute/unmute SVG icon using DOM methods
    while (muteBtn.firstChild) muteBtn.removeChild(muteBtn.firstChild);
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', '18');
    svg.setAttribute('height', '18');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '2');

    var speaker = document.createElementNS(ns, 'path');
    speaker.setAttribute('d', 'M11 5L6 9H2v6h4l5 4V5z');
    svg.appendChild(speaker);

    if (muted) {
      var x1 = document.createElementNS(ns, 'line');
      x1.setAttribute('x1', '23'); x1.setAttribute('y1', '9');
      x1.setAttribute('x2', '17'); x1.setAttribute('y2', '15');
      svg.appendChild(x1);
      var x2 = document.createElementNS(ns, 'line');
      x2.setAttribute('x1', '17'); x2.setAttribute('y1', '9');
      x2.setAttribute('x2', '23'); x2.setAttribute('y2', '15');
      svg.appendChild(x2);
    } else {
      var wave1 = document.createElementNS(ns, 'path');
      wave1.setAttribute('d', 'M19.07 4.93a10 10 0 0 1 0 14.14');
      svg.appendChild(wave1);
      var wave2 = document.createElementNS(ns, 'path');
      wave2.setAttribute('d', 'M15.54 8.46a5 5 0 0 1 0 7.07');
      svg.appendChild(wave2);
    }

    muteBtn.appendChild(svg);
  }

  // =====================================================================
  //  BANNERS
  // =====================================================================

  function showBanner(text, className) {
    banner.textContent = text;
    banner.className = className || '';
    banner.classList.remove('hidden');
  }

  function hideBanner() {
    banner.classList.add('hidden');
    banner.className = 'hidden';
  }

  // =====================================================================
  //  FORMATTING HELPERS
  // =====================================================================

  function formatNavDistance(meters) {
    if (useImperial) {
      var miles = meters / 1609.34;
      if (miles < 0.1) {
        var feet = Math.round(meters * 3.281);
        return feet + ' ft';
      }
      return miles.toFixed(1) + ' mi';
    } else {
      if (meters < 1000) {
        return Math.round(meters) + ' m';
      }
      return (meters / 1000).toFixed(1) + ' km';
    }
  }

  function formatDuration(seconds) {
    if (seconds < 60) return '< 1 min';
    var h = Math.floor(seconds / 3600);
    var m = Math.round((seconds % 3600) / 60);
    if (h > 0) return h + 'h ' + m + ' min';
    return m + ' min';
  }

  function formatTime(date) {
    var h = date.getHours();
    var m = date.getMinutes();
    var ampm = h >= 12 ? 'PM' : 'AM';
    h = h % 12 || 12;
    return h + ':' + (m < 10 ? '0' : '') + m + ' ' + ampm;
  }

  function clamp(val, min, max) {
    return Math.max(min, Math.min(max, val));
  }

  /**
   * Returns MapLibre `padding` suitable for placing the GPS marker at ~78%
   * from the top of the map container — below the nav overlay and well
   * into the bottom third so the user can see ahead of their direction of
   * travel.
   *
   * MapLibre `padding` is an *inset*: effective center is
   *   ((top + (H - bottom)) / 2, ...)
   * For a target y = f * H:
   *   f = (top + H - bottom) / (2*H)
   *   top - bottom = H * (2f - 1)
   * With bottom=0 and f=0.78: top = H * 0.56. Add overlayH so the overlay
   * itself doesn't cover the marker at extreme aspect ratios.
   */
  function getNavPadding() {
    if (!overlay || overlay.classList.contains('hidden')) {
      return { top: 0, bottom: 0, left: 0, right: 0 };
    }
    var overlayH = overlay.offsetHeight;
    var mapH = (map && map.getContainer) ? map.getContainer().clientHeight : window.innerHeight;
    if (!mapH || mapH < 100) mapH = window.innerHeight; // degenerate container
    // Target: marker at y = 0.78 * mapH
    //   top = mapH * (2 * 0.78 - 1) = mapH * 0.56
    // Use max(overlayH + 20, proportional target): proportional places the
    // marker at ~78% from top on typical viewports; max(overlayH) ensures
    // the marker is never hidden under the overlay on short viewports.
    var desiredTop = Math.max(overlayH + 20, Math.round(mapH * 0.56));
    if (Math.abs(desiredTop - lastNavPaddingTop) > PADDING_RECALC_THRESHOLD) {
      lastNavPaddingTop = desiredTop;
    }
    return { top: lastNavPaddingTop, bottom: 0, left: 0, right: 0 };
  }

  // =====================================================================
  //  MANEUVER ICONS (SVG via DOM API)
  // =====================================================================

  /**
   * Build a maneuver direction SVG icon for the given Valhalla type.
   * Uses safe DOM construction (no innerHTML).
   * @param {number} type - Valhalla maneuver type 0-29
   * @returns {SVGElement}
   */
  function buildManeuverSVG(type) {
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 40 40');
    svg.setAttribute('width', '40');
    svg.setAttribute('height', '40');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'white');
    svg.setAttribute('stroke-width', '3');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');

    function addLine(x1, y1, x2, y2) {
      var el = document.createElementNS(ns, 'line');
      el.setAttribute('x1', x1); el.setAttribute('y1', y1);
      el.setAttribute('x2', x2); el.setAttribute('y2', y2);
      svg.appendChild(el);
    }

    function addPath(d) {
      var el = document.createElementNS(ns, 'path');
      el.setAttribute('d', d);
      svg.appendChild(el);
    }

    function addPolyline(points) {
      var el = document.createElementNS(ns, 'polyline');
      el.setAttribute('points', points);
      svg.appendChild(el);
    }

    function addCircle(cx, cy, r) {
      var el = document.createElementNS(ns, 'circle');
      el.setAttribute('cx', cx); el.setAttribute('cy', cy);
      el.setAttribute('r', r);
      svg.appendChild(el);
    }

    function addRect(x, y, w, h, rx) {
      var el = document.createElementNS(ns, 'rect');
      el.setAttribute('x', x); el.setAttribute('y', y);
      el.setAttribute('width', w); el.setAttribute('height', h);
      if (rx) el.setAttribute('rx', rx);
      svg.appendChild(el);
    }

    switch (type) {
      // Straight
      case 0: case 7: case 8: case 17: case 22:
        addLine(20, 36, 20, 6);
        addPolyline('12,14 20,6 28,14');
        break;

      // Slight right
      case 9: case 23:
        addPath('M20 36 L20 20 L28 8');
        addPolyline('22,16 28,8 32,16');
        break;

      // Right
      case 10: case 18:
        addPath('M20 36 L20 20 L34 20');
        addPolyline('28,14 34,20 28,26');
        break;

      // Sharp right
      case 11:
        addPath('M20 36 L20 20 L30 30');
        addPolyline('30,22 30,30 22,30');
        break;

      // U-turn right
      case 12:
        addPath('M16 36 L16 16 A8 8 0 0 1 32 16 L32 28');
        addPolyline('26,22 32,28 38,22');
        break;

      // U-turn left
      case 13:
        addPath('M24 36 L24 16 A8 8 0 0 0 8 16 L8 28');
        addPolyline('14,22 8,28 2,22');
        break;

      // Sharp left
      case 14:
        addPath('M20 36 L20 20 L10 30');
        addPolyline('10,22 10,30 18,30');
        break;

      // Left
      case 15: case 19:
        addPath('M20 36 L20 20 L6 20');
        addPolyline('12,14 6,20 12,26');
        break;

      // Slight left
      case 16: case 24:
        addPath('M20 36 L20 20 L12 8');
        addPolyline('18,16 12,8 8,16');
        break;

      // Start / depart (flag)
      case 1: case 2: case 3:
        addLine(12, 36, 12, 6);
        addPath('M12 6 L30 12 L12 18');
        break;

      // Destination (checkered flag)
      case 4: case 5: case 6:
        addLine(12, 36, 12, 6);
        addRect(12, 6, 18, 12, 1);
        addLine(18, 6, 18, 18);
        addLine(24, 6, 24, 18);
        addLine(12, 12, 30, 12);
        break;

      // Merge
      case 25:
        addPath('M12 36 L12 20 L20 12 L20 6');
        addPath('M28 36 L28 20 L20 12');
        addPolyline('14,10 20,6 26,10');
        break;

      // Roundabout
      case 26: case 27:
        addCircle(20, 16, 8);
        addLine(20, 24, 20, 36);
        addPolyline('14,10 20,4 26,10');
        break;

      // Ferry
      case 28: case 29:
        addPath('M6 28 Q13 22 20 28 Q27 34 34 28');
        addPath('M6 22 Q13 16 20 22 Q27 28 34 22');
        addLine(20, 8, 20, 22);
        addPolyline('14,14 20,8 26,14');
        break;

      // Default: straight arrow
      default:
        addLine(20, 36, 20, 6);
        addPolyline('12,14 20,6 28,14');
    }

    return svg;
  }

  /**
   * Set the maneuver icon in the nav overlay.
   * @param {number} type - Valhalla maneuver type
   */
  function setManeuverIcon(type) {
    while (iconEl.firstChild) iconEl.removeChild(iconEl.firstChild);
    iconEl.appendChild(buildManeuverSVG(type));
  }

  // Test hook: expose internal helpers for unit tests. Must sit before
  // BOOTSTRAP so the assignment happens even if init() throws in a
  // degenerate (e.g. Node vm) environment.
  window._geographicaNavUIInternals = {
    buildRouteData: buildRouteData,
  };

  // =====================================================================
  //  BOOTSTRAP
  // =====================================================================

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
