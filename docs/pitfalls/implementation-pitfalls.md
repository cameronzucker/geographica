# Implementation Pitfalls

Common implementation mistakes in the Geographica codebase.

## 1. Data inside the git repo

Large data files MUST go to `/srv/geographica/data/` (symlinked as `./data`). Never create large files inside the git repo tree. Model weights, MBTiles, PBF files, SQLite databases — all outside the repo.

## 2. Docker Compose service naming

Container names follow the pattern `geographica-<service>`. Port allocation: 8090 (tileserver), 8092 (nominatim), 8093 (frontend HTTP), 8094 (valhalla), 8095 (gps), 8096 (search), 8097 (config panel), 8098 (stt). Check for conflicts before adding services.

## 3. NGINX sub_filter interactions

The `sub_filter` directive in NGINX replaces URLs in responses. It requires `Accept-Encoding ""` to disable gzip (can't filter compressed content). Only apply sub_filter to style JSON and TileJSON endpoints — not to tile data or JSON API responses.

## 4. Memory limits on Pi 5

The Pi 5 has 16GB RAM. Current service allocations approach this limit. When adding new services, check total memory: `docker stats --no-stream`. Exceeding available RAM causes OOM kills.

## 5. HTTPS requirement for browser APIs

Web Audio API, getUserMedia, and other sensitive browser APIs require HTTPS (or localhost). Geographica has HTTPS via Tailscale TLS. Test features on HTTPS, not HTTP.

## 6. Offline-first design

All features must work without internet after initial setup. Don't add runtime dependencies on external APIs or CDNs. Model weights, fonts, icons — everything must be bundled or pre-downloaded.

## 7. GPS service busy-wait

The gps3 library uses a busy-wait polling loop. Always include `time.sleep(0.05)` in the loop body to prevent 100% CPU usage. This was a production bug that was fixed — don't regress it.

## 8. SQLite WAL mode for concurrent access

When multiple processes read/write the same SQLite database (e.g., pipeline writing tiles while TileServer reads them), use WAL mode. Readers never block writers in WAL mode.

## 9. Frontend module boundaries

`app.js` is ~2800 lines and approaching the threshold for extraction. New frontend features should go in separate modules (e.g., `stt.js`, `navigation.js`, `nav-ui.js`) and integrate via callbacks, not by adding more code to `app.js`.

## 10. Config panel is localhost-only

The config panel on port 8097 is bound to 127.0.0.1. Admin endpoints require the `X-Config-Source: internal` header (set by NGINX). Direct API calls from external clients will be rejected.

## 11. MapLibre dragRotate: use .disable()/.enable() AFTER init, NOT constructor options

**Critical:** To override MapLibre's CTRL+drag rotation behavior (e.g., for custom free-look camera), call `map.dragRotate.disable()` in a setup function AFTER the map is created. Do NOT use `dragRotate: false` in the `new maplibregl.Map()` constructor options.

**Why:** Constructor-level `dragRotate: false` prevents the initial `.enable()` call but the internal handler objects (mouseRotate, mousePitch, mouseRoll) are still registered in MapLibre's HandlerManager. The `.disable()` / `.enable()` toggle pattern after init correctly gates these handlers. Constructor options do not.

**Working pattern (from commit 3be5183):**
```js
// In initFreeLookCamera(), called on map.on('load'):
map.dragRotate.disable();  // Disable built-in CTRL+drag rotation

// CTRL+left drag: custom free-look via jumpTo
canvas.addEventListener('mousedown', function(e) {
  if (e.ctrlKey && e.button === 0) {
    e.preventDefault();
    e.stopPropagation();
    freeLookActive = true;
    map.dragPan.disable();
    // ... capture start state
  }
});

// SHIFT/right-click: temporarily re-enable MapLibre's orbit
canvas.addEventListener('mousedown', function(e) {
  if (e.shiftKey && e.button === 0) {
    orbitActive = true;
    map.dragRotate.enable();  // Temporarily re-enable for orbit
  }
});

// Mouseup: re-disable dragRotate so next CTRL+drag gets free-look
window.addEventListener('mouseup', function() {
  if (orbitActive) {
    orbitActive = false;
    map.dragRotate.disable();  // MUST re-disable
  }
});
```

**Broken patterns (all tried and failed):**
- `new Map({ dragRotate: false })` — handlers still registered internally
- `new Map({ boxZoom: false })` — CTRL+drag is dragRotate, not boxZoom
- `canvas.addEventListener(..., true)` capture phase — MapLibre's HandlerManager bypasses DOM events
- `stopImmediatePropagation` — MapLibre's handlers registered first, fire first
- `map.jumpTo({ center, bearing, pitch })` center compensation — wrong abstraction, not the bug
