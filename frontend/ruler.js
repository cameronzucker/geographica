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
  };

  // ─── Public API ────────────────────────────────────────────────────
  function init(mapInstance) {
    if (initialized) return;       // idempotent per spec §A
    initialized = true;
    map = mapInstance;
    // Phase 1+ tasks fill in: source/layer wiring, click handlers,
    // keyboard handlers, units-changed subscription, etc.
  }

  function isActive() {
    return state.status === 'drawing' || state.status === 'inserting';
  }

  function clear() {
    if (view.abortController) {
      view.abortController.abort();
      view.abortController = null;
    }
    view.samplingGen++;
    state.status = 'idle';
    state.selectedVertex = null;
    state.insertSlot = null;
    state.vertices = [];
    state.segments = [];
    state.totalDistance_m = 0;
    state.elevationProfile = null;
    // Phase 1+ tasks fill in: source mutation, panel render, banner hide, cursor restore.
  }

  // Reattach hook called by app.js's addPlaceholderSources on style.load
  function reattachSources(mapInstance) {
    // Phase 1 fills this in: re-add ruler-line / ruler-vertices / ruler-vertex-hit-circles
    // sources + layers using the passed-in mapInstance after a style.load.
    // (Use `mapInstance` arg, not module `map`, so style swaps with a different map work.)
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
  };
})();
