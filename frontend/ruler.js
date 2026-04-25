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
    // Phase 1 fills this in.
  }

  // ─── Expose ────────────────────────────────────────────────────────
  window._ruler = {
    init: init,
    isActive: isActive,
    clear: clear,
    reattachSources: reattachSources,
  };
})();
