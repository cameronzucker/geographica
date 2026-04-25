/* =====================================================================
   Geographica — Ruler / Measurement Tool
   =====================================================================
   Self-contained measurement tool for the MapLibre frontend.
   Distance + true bearing + elevation profile from Mapzen Terrarium tiles.
   Ephemeral (no save) — the data shape is KMZ-geometry-serializable so
   a future "My Places" cycle can persist measurements without refactor.

   Spec: docs/superpowers/specs/2026-04-24-ruler-design.md (v3)
   ===================================================================== */

(function () {
  'use strict';

  // Duplicate-load guard. If ruler.js is included twice (stale <script> tag,
  // service-worker double-cache), skip the second load — the live module
  // owns window._ruler and re-running the IIFE would blow away in-progress
  // state. We check for the canonical .init function rather than just the
  // truthy presence of window._ruler so that a sibling page-stub setting
  // window._ruler = {} (e.g. a test harness) does not block real init.
  if (window._ruler && typeof window._ruler.init === 'function') return;

  // ─── Module-private state ──────────────────────────────────────────
  var initialized = false;
  var map = null;
  var state = {
    status: 'idle',           // idle | drawing | editing | inserting
    selectedVertex: null,
    insertSlot: null,
    vertices: [],
    segments: [],
    totalDistance_m: 0,
    elevationProfile: null,
  };

  // View-state — DOM / map handles. NOT serialized.
  var view = {
    abortController: null,
    samplingGen: 0,
    tileCache: null,          // LRU; created in init()
    rafHandle: null,
    domListenerCleanups: [],
    lastClick: null,          // { x, y, t } — debounce reference (Phase 2.5)
  };

  // Click-debounce parameters per spec §F (5 px AND 250 ms).
  var DEBOUNCE_PX = 5;
  var DEBOUNCE_PX_SQ = DEBOUNCE_PX * DEBOUNCE_PX;
  var DEBOUNCE_MS = 250;

  // ─── Public API ────────────────────────────────────────────────────
  function init(mapInstance) {
    if (initialized) return;       // idempotent per spec §A
    initialized = true;
    map = mapInstance;
    // Style may not be loaded yet at init time — ensureSources/ensureLayers
    // can throw "Style is not done loading" from MapLibre. They're idempotent,
    // and app.js's addPlaceholderSources callback (registered on map.on('load'))
    // re-invokes reattachSources after the style is ready, so a deferred
    // failure here is safely retried. Catch and log so init() finishes
    // registering listeners + buttons + tab handlers either way.
    try { ensureSources(); ensureLayers(); }
    catch (err) {
      if (typeof console !== 'undefined' && console.warn) {
        console.warn('[ruler] deferring source/layer setup until style.load:', err && err.message);
      }
    }
    map.on('click', handleMapClick);
    document.addEventListener('keydown', handleKeydown);

    // ── Footer button wiring ──
    // [+ New measurement] is the single explicit-activation entry point.
    // In idle state it transitions to drawing; in editing it discards the
    // current measurement and starts fresh. Either way: clearAll() then
    // status='drawing' (drawing-empty, ready for first map tap).
    var newBtn = document.getElementById('ruler-new');
    if (newBtn) newBtn.addEventListener('click', function () {
      startNewMeasurement();
      refreshMapData();
      renderPanel();
    });
    var clearBtn = document.getElementById('ruler-clear');
    if (clearBtn) clearBtn.addEventListener('click', function () {
      clear();
    });
    var finishBtn = document.getElementById('ruler-finish');
    if (finishBtn) finishBtn.addEventListener('click', function () {
      finishDrawing();
      refreshMapData();
      renderPanel();
      // Phase 4.7 wires startSampling() here.
    });
    var undoBtn = document.getElementById('ruler-undo');
    if (undoBtn) undoBtn.addEventListener('click', function () {
      popVertex();
      refreshMapData();
      renderPanel();
    });
    var inlineCancel = document.getElementById('ruler-banner-inline-cancel');
    var floatCancel = document.getElementById('ruler-mode-banner-cancel');
    function cancelBannerHandler() {
      if (state.status === 'drawing') {
        if (state.vertices.length >= 2) state.status = 'editing';
        else clearAll();
      } else if (state.status === 'inserting') {
        cancelInsert();
      }
      refreshMapData();
      renderPanel();
    }
    if (inlineCancel) inlineCancel.addEventListener('click', cancelBannerHandler);
    if (floatCancel)  floatCancel.addEventListener('click', cancelBannerHandler);

    // Initial render.
    renderPanel();
    updateCursor();
    // Phase 5.2 wires units-changed redraw.
  }

  function isActive() {
    return state.status === 'drawing' || state.status === 'inserting';
  }

  function clear() {
    clearAll();
    refreshMapData();
    renderPanel();
  }

  // ─── Geodesy ───────────────────────────────────────────────────────
  // Initial bearing (forward azimuth) from a → b in decimal degrees [0, 360).
  // Standard great-circle formula. NOT rhumb-line.
  function bearingDeg(a, b) {
    var lat1 = a[1] * Math.PI / 180;
    var lat2 = b[1] * Math.PI / 180;
    var dLng = (b[0] - a[0]) * Math.PI / 180;
    var y = Math.sin(dLng) * Math.cos(lat2);
    var x = Math.cos(lat1) * Math.sin(lat2) -
            Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLng);
    return ((Math.atan2(y, x) * 180 / Math.PI) + 360) % 360;
  }

  // ─── Elevation decode ──────────────────────────────────────────────
  // Mapzen Terrarium encoding: meters = (r*256 + g + b/256) - 32768.
  // Reference: https://github.com/tilezen/joerd/blob/master/docs/formats.md
  //
  // Per spec v3 §E.3 (R5 M4 guards):
  // - alpha-zero pixel  → null (transparent / no-data)
  // - decoded < -500m   → null (below plausible CONUS DEM range)
  // - decoded > 9000m   → null (above plausible CONUS DEM range)
  function elevationFromRGB(r, g, b, a) {
    if (a === 0) return null;
    var elev = (r * 256 + g + b / 256) - 32768;
    if (elev < -500 || elev > 9000) return null;
    return elev;
  }

  // ─── Path sampling ─────────────────────────────────────────────────
  // Sample N points evenly distributed by cumulative distance along
  // the path, using linear interpolation within each segment.
  // Returns [{ lng, lat, distance_m }, ...]. Empty path → []. Single
  // vertex → []. Zero-length path → N copies at the same point.
  function samplePath(vertices, numSamples) {
    if (!vertices || vertices.length < 2) return [];
    if (numSamples < 2) numSamples = 2;

    var hav = window._haversineDistance;
    var segLengths = [];
    var totalLen = 0;
    for (var i = 0; i < vertices.length - 1; i++) {
      var a = [vertices[i].lng, vertices[i].lat];
      var b = [vertices[i + 1].lng, vertices[i + 1].lat];
      var d = hav(a, b);
      segLengths.push(d);
      totalLen += d;
    }

    var samples = [];
    if (totalLen === 0) {
      for (var k = 0; k < numSamples; k++) {
        samples.push({ lng: vertices[0].lng, lat: vertices[0].lat, distance_m: 0 });
      }
      return samples;
    }

    for (var s = 0; s < numSamples; s++) {
      var frac = s / (numSamples - 1);
      var target = frac * totalLen;
      // Find segment containing target distance
      var accum = 0;
      var segIdx = 0;
      for (segIdx = 0; segIdx < segLengths.length; segIdx++) {
        if (accum + segLengths[segIdx] >= target) break;
        accum += segLengths[segIdx];
      }
      if (segIdx >= segLengths.length) segIdx = segLengths.length - 1;
      var local = segLengths[segIdx] === 0 ? 0 : (target - accum) / segLengths[segIdx];
      var v1 = vertices[segIdx];
      var v2 = vertices[segIdx + 1];
      samples.push({
        lng: v1.lng + (v2.lng - v1.lng) * local,
        lat: v1.lat + (v2.lat - v1.lat) * local,
        distance_m: target,
      });
    }
    return samples;
  }

  // ─── Segment projection ────────────────────────────────────────────
  // Closest point on segment a→b to point p, in lng/lat (linear,
  // not geodesic — at segment scales we use for Insert After, the
  // difference is sub-meter).
  // Clamps to segment endpoints (no extrapolation).
  function projectPointToSegment(p, a, b) {
    var dx = b[0] - a[0];
    var dy = b[1] - a[1];
    var len2 = dx * dx + dy * dy;
    if (len2 === 0) return [a[0], a[1]];   // zero-length segment
    var t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2;
    if (t < 0) t = 0;
    if (t > 1) t = 1;
    return [a[0] + t * dx, a[1] + t * dy];
  }

  // ─── Distance formatting ───────────────────────────────────────────
  // Live-reads window._geographicaUseImperial at format time so unit
  // toggle propagates immediately (per spec §A).
  function formatRulerDistance(meters) {
    var imperial = window._geographicaUseImperial;
    if (imperial) {
      if (meters < 1609.34) return Math.round(meters * 3.28084) + ' ft';
      return (meters / 1609.34).toFixed(2) + ' mi';
    } else {
      if (meters < 1000) return Math.round(meters) + ' m';
      return (meters / 1000).toFixed(2) + ' km';
    }
  }

  // ─── Sparkline path generation ─────────────────────────────────────
  // Returns an SVG `points` attribute string (space-separated x,y pairs)
  // mapping samples to a width×height viewBox. Skips null-elevation
  // samples (gap rendering is a separate concern handled by the panel
  // renderer using multiple polylines).
  function sparklinePath(samples, width, height) {
    if (!samples || samples.length === 0) return '';
    var valid = samples.filter(function (s) { return s.elevation_m != null; });
    if (valid.length === 0) return '';

    var minE = Infinity, maxE = -Infinity;
    var minD = Infinity, maxD = -Infinity;
    for (var i = 0; i < valid.length; i++) {
      if (valid[i].elevation_m < minE) minE = valid[i].elevation_m;
      if (valid[i].elevation_m > maxE) maxE = valid[i].elevation_m;
      if (valid[i].distance_m  < minD) minD = valid[i].distance_m;
      if (valid[i].distance_m  > maxD) maxD = valid[i].distance_m;
    }
    var dRange = (maxD - minD) || 1;
    var eRange = (maxE - minE) || 1;
    var marginY = 4;
    var usableY = height - 2 * marginY;

    var points = [];
    for (var j = 0; j < valid.length; j++) {
      var x = ((valid[j].distance_m - minD) / dRange) * width;
      var y = marginY + (1 - (valid[j].elevation_m - minE) / eRange) * usableY;
      points.push(x.toFixed(1) + ',' + y.toFixed(1));
    }
    return points.join(' ');
  }

  // ─── State recompute / relabel ─────────────────────────────────────
  function relabel() {
    for (var i = 0; i < state.vertices.length; i++) {
      state.vertices[i].label = 'V' + (i + 1);
    }
  }

  function recompute() {
    state.segments = [];
    state.totalDistance_m = 0;
    var hav = window._haversineDistance;
    for (var i = 0; i < state.vertices.length - 1; i++) {
      var a = [state.vertices[i].lng,     state.vertices[i].lat];
      var b = [state.vertices[i + 1].lng, state.vertices[i + 1].lat];
      var d = hav(a, b);
      var brg = bearingDeg(a, b);
      state.segments.push({
        distance_m: d, bearing_deg: brg,
        from: state.vertices[i].label, to: state.vertices[i + 1].label,
      });
      state.totalDistance_m += d;
    }
  }

  // ─── State-machine transitions (spec §B) ───────────────────────────
  // Activation is explicit: idle→drawing happens via startNewMeasurement()
  // (the [+ New measurement] button), NOT via the first map tap. Cameron
  // 2026-04-25: tab-as-activation breaks the project's UI metaphor
  // (Layers tab doesn't auto-enable layers; Measure tab shouldn't auto-
  // enable measurement). Map clicks only place vertices once the user
  // has explicitly entered drawing mode.
  function startNewMeasurement() {
    clearAll();
    state.status = 'drawing';
  }

  function addVertex(lng, lat) {
    if (state.status !== 'drawing') return;
    state.vertices.push({ lng: lng, lat: lat, label: '' });
    relabel();
    recompute();
  }

  function popVertex() {
    if (state.status !== 'drawing') return;
    if (state.vertices.length === 0) return;
    state.vertices.pop();
    relabel();
    recompute();
    // Stay in drawing-empty when the last vertex is popped — user is
    // still actively measuring; they'd press Esc to truly cancel.
  }

  function finishDrawing() {
    if (state.status !== 'drawing') return;
    if (state.vertices.length < 2) return;
    state.status = 'editing';
    state.elevationProfile = null;  // sampling kicks off in Phase 4
  }

  function clearAll() {
    if (view.abortController) {
      view.abortController.abort();
      view.abortController = null;
    }
    view.samplingGen++;
    view.lastClick = null;
    state.status = 'idle';
    state.selectedVertex = null;
    state.insertSlot = null;
    state.vertices = [];
    state.segments = [];
    state.totalDistance_m = 0;
    state.elevationProfile = null;
  }

  function selectVertex(index) {
    if (state.status !== 'editing') return;
    if (index < 0 || index >= state.vertices.length) return;
    state.selectedVertex = index;
  }

  function deselectVertex() {
    if (state.status !== 'editing') return;
    state.selectedVertex = null;
  }

  function startInsertBefore() {
    if (state.status !== 'editing') return;
    if (state.selectedVertex === null) return;
    state.status = 'inserting';
    state.insertSlot = { before: state.selectedVertex };
  }

  function startInsertAfter() {
    if (state.status !== 'editing') return;
    if (state.selectedVertex === null) return;
    state.status = 'inserting';
    state.insertSlot = { before: state.selectedVertex + 1 };
  }

  function cancelInsert() {
    if (state.status !== 'inserting') return;
    state.status = 'editing';
    state.insertSlot = null;
  }

  // Read-only state snapshot for tests + view-layer rendering.
  function getStateSnapshot() {
    return {
      status: state.status,
      selectedVertex: state.selectedVertex,
      insertSlot: state.insertSlot ? { before: state.insertSlot.before } : null,
      vertices: state.vertices.map(function (v) {
        return { lng: v.lng, lat: v.lat, label: v.label };
      }),
      segments: state.segments.map(function (s) {
        return { distance_m: s.distance_m, bearing_deg: s.bearing_deg, from: s.from, to: s.to };
      }),
      totalDistance_m: state.totalDistance_m,
      elevationProfile: state.elevationProfile,
    };
  }

  // ─── Click handler (drawing state only) ────────────────────────────
  function handleMapClick(e) {
    var oe = e.originalEvent || {};
    // Modifier keys → pass-through (map-pan/select gesture).
    if (oe.ctrlKey || oe.shiftKey || oe.altKey || oe.metaKey) return;

    if (state.status === 'inserting') {
      // Phase 3.5 wires this branch to commitInsert(). Stub for now.
      return;
    }
    // Idle is no longer a click-receiving state — the user must explicitly
    // enter drawing mode via [+ New measurement] (spec §B post-2026-04-25).
    if (state.status !== 'drawing') return;

    // Debounce: 5px AND 250ms vs the previous accepted click.
    var t = oe.timeStamp != null ? oe.timeStamp : Date.now();
    var pt = e.point || { x: 0, y: 0 };
    if (view.lastClick) {
      var dx = pt.x - view.lastClick.x;
      var dy = pt.y - view.lastClick.y;
      var dt = t - view.lastClick.t;
      if ((dx * dx + dy * dy) < DEBOUNCE_PX_SQ && dt < DEBOUNCE_MS) return;
    }
    view.lastClick = { x: pt.x, y: pt.y, t: t };

    addVertex(e.lngLat.lng, e.lngLat.lat);
    refreshMapData();
    renderPanel();
  }

  // ─── Keyboard handler (spec §C.6) ──────────────────────────────────
  function handleKeydown(e) {
    // Don't steal keys from text inputs.
    var tag = e.target && e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;
    if (e.target && e.target.isContentEditable) return;

    if (e.key === 'Backspace' || e.key === 'Delete') {
      if (state.status === 'drawing') {
        if (state.vertices.length === 0) return;
        popVertex();
        if (e.preventDefault) e.preventDefault();
        refreshMapData();
        renderPanel();
        return;
      }
      // Phase 3.7 extends this to handle editing-state vertex deletion.
      return;
    }

    if (e.key === 'Escape') {
      if (state.status === 'drawing') {
        if (state.vertices.length >= 2) state.status = 'editing';
        else clearAll();
        if (e.preventDefault) e.preventDefault();
        refreshMapData();
        renderPanel();
        return;
      }
      if (state.status === 'inserting') {
        cancelInsert();
        if (e.preventDefault) e.preventDefault();
        refreshMapData();
        renderPanel();
        return;
      }
      if (state.status === 'editing' && state.selectedVertex !== null) {
        deselectVertex();
        if (e.preventDefault) e.preventDefault();
        refreshMapData();
        renderPanel();
        return;
      }
      return;
    }

    if (e.key === 'Enter') {
      if (state.status === 'drawing' && state.vertices.length >= 2) {
        finishDrawing();
        if (e.preventDefault) e.preventDefault();
        refreshMapData();
        renderPanel();
        // Phase 4.7 wires startSampling() here.
        return;
      }
      return;
    }
    // Phase 5.3 extends to Tab/Space/Arrows.
  }

  // ─── DOM rendering — panel + banner ────────────────────────────────
  // Single source-of-truth: every state mutation calls renderPanel().
  // NEVER use innerHTML. textContent only. Safe-clear via removeChild.

  function $id(id) { return document.getElementById(id); }

  function setHidden(el, hidden) {
    if (!el) return;
    el.hidden = !!hidden;
    // Project convention: some default-hidden elements (e.g. #ruler-mode-banner)
    // use class="hidden" rather than the [hidden] attribute. The global
    // .hidden { display: none !important } rule wins over the [hidden] UA
    // style, so toggling el.hidden alone leaves them visually unchanged.
    // Toggle both — handles either convention safely.
    if (hidden) el.classList.add('hidden');
    else el.classList.remove('hidden');
  }

  function clearChildren(el) {
    if (!el) return;
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function renderVertexList() {
    var listEl = $id('ruler-vertex-list');
    if (!listEl) return;
    clearChildren(listEl);
    for (var i = 0; i < state.vertices.length; i++) {
      var v = state.vertices[i];
      var row = document.createElement('li');
      row.className = 'ruler-vertex-row';
      row.setAttribute('role', 'listitem');
      row.setAttribute('tabindex', '0');
      row.setAttribute('data-vertex-index', String(i));
      if (state.selectedVertex === i) {
        row.classList.add('selected');
        row.setAttribute('aria-selected', 'true');
      } else {
        row.setAttribute('aria-selected', 'false');
      }
      var top = document.createElement('div');
      top.className = 'ruler-vertex-row-top';
      var labelEl = document.createElement('span');
      labelEl.className = 'ruler-vertex-row-label';
      labelEl.textContent = v.label;
      var coordsEl = document.createElement('span');
      coordsEl.className = 'ruler-vertex-row-coords';
      coordsEl.textContent =
        window._formatDD(v.lat, 'NS') + ', ' + window._formatDD(v.lng, 'EW');
      top.appendChild(labelEl);
      top.appendChild(coordsEl);
      row.appendChild(top);

      if (i < state.vertices.length - 1 && state.segments[i]) {
        var seg = state.segments[i];
        var segEl = document.createElement('div');
        segEl.className = 'ruler-vertex-row-seg';
        var dEl = document.createElement('span');
        dEl.textContent = '↓ ' + formatRulerDistance(seg.distance_m);
        var bEl = document.createElement('span');
        bEl.textContent = seg.bearing_deg.toFixed(1) + '°';
        segEl.appendChild(dEl);
        segEl.appendChild(bEl);
        row.appendChild(segEl);
      }

      // Click handler closes over the index for this row.
      row.addEventListener('click', (function (idx) {
        return function () {
          if (state.status === 'editing') {
            if (state.selectedVertex === idx) deselectVertex();
            else selectVertex(idx);
            refreshMapData();
            renderPanel();
          }
        };
      })(i));

      listEl.appendChild(row);
    }
  }

  function renderBanners() {
    var floating = $id('ruler-mode-banner');
    var floatingTxt = $id('ruler-mode-banner-text');
    var inline = $id('ruler-banner-inline');
    var inlineTxt = $id('ruler-banner-inline-text');
    if (state.status === 'drawing') {
      var msg = state.vertices.length === 0
        ? 'Tap map to place first vertex'
        : 'Tap map to add more, or [Finish] when done';
      if (floatingTxt) floatingTxt.textContent = msg;
      if (inlineTxt) inlineTxt.textContent = msg;
      setHidden(floating, false);
      setHidden(inline, false);
    } else if (state.status === 'inserting') {
      var slot = state.insertSlot ? state.insertSlot.before : 0;
      var msg2 = 'Tap map to insert vertex (slot V' + (slot + 1) + ')';
      if (floatingTxt) floatingTxt.textContent = msg2;
      if (inlineTxt) inlineTxt.textContent = msg2;
      setHidden(floating, false);
      setHidden(inline, false);
    } else {
      setHidden(floating, true);
      setHidden(inline, true);
    }
  }

  function renderHeadline() {
    var headlineSection = $id('ruler-headline-section');
    var totalEl = $id('ruler-headline-total');
    var visible = state.vertices.length >= 2;
    setHidden(headlineSection, !visible);
    if (visible && totalEl) totalEl.textContent = formatRulerDistance(state.totalDistance_m);
  }

  function renderActionRow() {
    var actionRow = $id('ruler-action-row');
    var actionEmpty = $id('ruler-action-empty');
    var visible = state.status === 'editing' && state.selectedVertex !== null;
    setHidden(actionRow, !visible);
    setHidden(actionEmpty, visible || state.status !== 'editing');
  }

  function renderFooter() {
    var undo = $id('ruler-undo');
    var clearBtn = $id('ruler-clear');
    var finish = $id('ruler-finish');
    var newBtn = $id('ruler-new');
    if (state.status === 'drawing') {
      setHidden(undo, false);
      setHidden(clearBtn, false);
      setHidden(finish, state.vertices.length < 2);
      setHidden(newBtn, true);
    } else if (state.status === 'editing') {
      setHidden(undo, true);
      setHidden(clearBtn, false);
      setHidden(finish, true);
      setHidden(newBtn, false);
    } else if (state.status === 'inserting') {
      setHidden(undo, true); setHidden(clearBtn, true);
      setHidden(finish, true); setHidden(newBtn, true);
    } else {
      // idle: the [+ New measurement] button is the explicit-activation
      // entry point. Map clicks are inert until the user clicks it.
      setHidden(undo, true); setHidden(clearBtn, true);
      setHidden(finish, true); setHidden(newBtn, false);
    }
  }

  // ─── Cursor management ─────────────────────────────────────────────
  function updateCursor() {
    if (!map) return;
    var canvas = map.getCanvas && map.getCanvas();
    if (!canvas) return;
    if (state.status === 'drawing' || state.status === 'inserting') {
      canvas.style.cursor = 'crosshair';
      return;
    }
    if (state.status === 'editing') {
      // pointer-on-hover handled by mouseenter/mouseleave on the hit layer
      // (Phase 3.1+ wires the hover transitions). Default cursor for now.
      canvas.style.cursor = '';
      return;
    }
    canvas.style.cursor = '';
  }

  function renderPanel() {
    var vertexSection = $id('ruler-vertex-section');
    var visible = state.vertices.length > 0;
    setHidden(vertexSection, !visible);
    var countEl = $id('ruler-vertex-count');
    if (countEl) countEl.textContent = String(state.vertices.length);

    // Idle-state hint visible only when there's nothing to show otherwise.
    setHidden($id('ruler-idle-hint'), state.status !== 'idle');

    renderVertexList();
    renderBanners();
    renderHeadline();
    renderActionRow();
    renderFooter();
    // Phase 4.5+ adds renderElevation().
    updateCursor();

    // Body class for active-mode CSS hooks. While drawing/inserting, the
    // sidebar overlay's pointer-events are suppressed so map clicks reach
    // the MapLibre canvas instead of the overlay's close-sidebar handler.
    if (typeof document !== 'undefined' && document.body && document.body.classList) {
      if (state.status === 'drawing' || state.status === 'inserting') {
        document.body.classList.add('ruler-active');
      } else {
        document.body.classList.remove('ruler-active');
      }
    }
  }

  // ─── Map source/layer wiring (spec §D) ─────────────────────────────
  // Layer IDs (also referenced by app.js queryRenderedFeatures exclusion
  // edit in addPlaceholderSources's sibling reverse-geocode click handler — keep in sync).
  var SOURCE_LINE = 'ruler-line-source';
  var SOURCE_VERTEX = 'ruler-vertex-source';
  var LAYER_LINE_SHADOW = 'ruler-line-shadow';
  var LAYER_LINE = 'ruler-line';
  var LAYER_VERTEX_CIRCLES = 'ruler-vertex-circles';
  var LAYER_VERTEX_CIRCLES_SELECTED = 'ruler-vertex-circles-selected';
  var LAYER_VERTEX_HIT_CIRCLES = 'ruler-vertex-hit-circles';
  var LAYER_VERTEX_LABELS = 'ruler-vertex-labels';

  function buildLineFeature() {
    if (state.vertices.length < 2) {
      return { type: 'Feature', geometry: { type: 'LineString', coordinates: [] }, properties: {} };
    }
    var coords = state.vertices.map(function (v) { return [v.lng, v.lat]; });
    return { type: 'Feature', geometry: { type: 'LineString', coordinates: coords }, properties: {} };
  }

  function buildVertexFeatures() {
    return {
      type: 'FeatureCollection',
      features: state.vertices.map(function (v, i) {
        return {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [v.lng, v.lat] },
          properties: {
            index: i,
            label: v.label,
            selected: state.selectedVertex === i,
          },
        };
      }),
    };
  }

  function refreshMapData() {
    if (!map) return;
    var lineSrc = map.getSource(SOURCE_LINE);
    var vertSrc = map.getSource(SOURCE_VERTEX);
    if (lineSrc) lineSrc.setData(buildLineFeature());
    if (vertSrc) vertSrc.setData(buildVertexFeatures());
  }

  function ensureSources() {
    if (!map) return;
    if (!map.getSource(SOURCE_LINE)) {
      map.addSource(SOURCE_LINE, { type: 'geojson', data: buildLineFeature() });
    }
    if (!map.getSource(SOURCE_VERTEX)) {
      map.addSource(SOURCE_VERTEX, { type: 'geojson', data: buildVertexFeatures() });
    }
  }

  function ensureLayers() {
    if (!map) return;
    // Order matters: shadow → line → circles → selected circles → hit circles → labels.
    if (!map.getLayer(LAYER_LINE_SHADOW)) {
      map.addLayer({
        id: LAYER_LINE_SHADOW, type: 'line', source: SOURCE_LINE,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': 'rgba(0,0,0,0.55)', 'line-width': 7 },
      });
    }
    if (!map.getLayer(LAYER_LINE)) {
      map.addLayer({
        id: LAYER_LINE, type: 'line', source: SOURCE_LINE,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#ffd400', 'line-width': 4, 'line-opacity': 0.95 },
      });
    }
    if (!map.getLayer(LAYER_VERTEX_CIRCLES)) {
      map.addLayer({
        id: LAYER_VERTEX_CIRCLES, type: 'circle', source: SOURCE_VERTEX,
        paint: {
          'circle-radius': 8,
          'circle-color': '#ffd400',
          'circle-stroke-width': 2,
          'circle-stroke-color': '#ffffff',
        },
      });
    }
    if (!map.getLayer(LAYER_VERTEX_CIRCLES_SELECTED)) {
      map.addLayer({
        id: LAYER_VERTEX_CIRCLES_SELECTED, type: 'circle', source: SOURCE_VERTEX,
        // MapLibre v3+ requires the explicit ['get', ...] expression form.
        filter: ['==', ['get', 'selected'], true],
        paint: {
          'circle-radius': 11,
          'circle-color': '#ff7a00',
          'circle-stroke-width': 3,
          'circle-stroke-color': '#ffffff',
        },
      });
    }
    if (!map.getLayer(LAYER_VERTEX_HIT_CIRCLES)) {
      // Visible-but-transparent: 44px diameter (WCAG 2.5.5). MUST NOT be
      // visibility:'none' — that would skip queryRenderedFeatures.
      map.addLayer({
        id: LAYER_VERTEX_HIT_CIRCLES, type: 'circle', source: SOURCE_VERTEX,
        paint: { 'circle-radius': 22, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-width': 0 },
      });
    }
    if (!map.getLayer(LAYER_VERTEX_LABELS)) {
      map.addLayer({
        id: LAYER_VERTEX_LABELS, type: 'symbol', source: SOURCE_VERTEX,
        layout: {
          'text-field': ['get', 'label'],
          // Two-font fallback per spec §D / R5 M3 — matches positron/darkmatter/hybrid.
          'text-font': ['Metropolis Regular', 'Noto Sans Regular'],
          'text-size': 12,
          'text-offset': [0, -1.4],
          'text-anchor': 'bottom',
          'text-allow-overlap': true,
        },
        paint: {
          'text-color': '#ffffff',
          'text-halo-color': '#000000',
          'text-halo-width': 2,
        },
      });
    }
  }

  function reattachSources(mapInstance) {
    // Called by app.js's addPlaceholderSources() on initial load and on
    // every style.load (basemap toggle / 3D enable). Idempotent.
    map = mapInstance;
    ensureSources();
    ensureLayers();
    refreshMapData();
  }

  // ─── Expose ────────────────────────────────────────────────────────
  window._ruler = {
    init: init,
    isActive: isActive,
    clear: clear,
    reattachSources: reattachSources,
  };

  // Test-only: expose pure functions for unit testing. Production code
  // never reaches into _test.
  window._ruler._test = {
    bearingDeg: bearingDeg,
    elevationFromRGB: elevationFromRGB,
    samplePath: samplePath,
    projectPointToSegment: projectPointToSegment,
    formatRulerDistance: formatRulerDistance,
    sparklinePath: sparklinePath,
    startNewMeasurement: startNewMeasurement,
    addVertex: addVertex,
    popVertex: popVertex,
    finishDrawing: finishDrawing,
    clearAll: clearAll,
    selectVertex: selectVertex,
    deselectVertex: deselectVertex,
    startInsertBefore: startInsertBefore,
    startInsertAfter: startInsertAfter,
    cancelInsert: cancelInsert,
    getState: getStateSnapshot,
    relabel: relabel,
    recompute: recompute,
    refreshMapData: refreshMapData,
    handleMapClick: handleMapClick,
    handleKeydown: handleKeydown,
    renderPanel: renderPanel,
    updateCursor: updateCursor,
  };
})();
