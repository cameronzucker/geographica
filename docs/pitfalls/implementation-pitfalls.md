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

## 11. MapLibre dragRotate: must DELETE handlers from _handlersById (disable() alone is insufficient in v5.21+)

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

**The REAL fix (MapLibre v5.21+):** `dragRotate.disable()` alone is INSUFFICIENT. The internal handler pipeline still processes CTRL+mousedown even when disabled. You must surgically remove the handlers from the HandlerManager:

```js
map.dragRotate.disable();
if (map._handlers && map._handlers._handlersById) {
  delete map._handlers._handlersById['mouseRotate'];
  delete map._handlers._handlersById['mousePitch'];
  map._handlers._handlers = map._handlers._handlers.filter(function (h) {
    return h.handlerName !== 'mouseRotate' && h.handlerName !== 'mousePitch';
  });
}
```

This must be done BOTH at init (in initFreeLookCamera) AND in the `map.on('style.load')` handler (MapLibre re-registers handlers on style swap).

**Also:** `NavigationControl` with `showCompass: true` (default) calls `dragRotate.enable()` when added. Use `showCompass: false`.

**Broken patterns (all tried and failed):**
- `map.dragRotate.disable()` alone — handler pipeline still runs in v5.21
- `new Map({ dragRotate: false })` — handlers still registered internally
- `new Map({ boxZoom: false })` — CTRL+drag is dragRotate, not boxZoom
- `canvas.addEventListener(..., true)` capture phase — MapLibre's HandlerManager bypasses DOM events
- `stopImmediatePropagation` — both our handler and MapLibre's fire, both update camera simultaneously
- `map.jumpTo({ center, bearing, pitch })` center compensation — wrong abstraction, not the bug

## 12. Pydantic max_length on route polylines

**Critical:** Valhalla route polylines can have 8000-12000+ points for long multi-stop routes (e.g., PHX → Reno with waypoints). The `SpatialSearchBody.route` field's `max_length` must accommodate this — a limit of 10000 caused silent 422 errors that the frontend displayed as "No results found nearby."

**Current limit:** 50000 (sufficient for any realistic route, ~800KB at max).

**Why this is a pitfall:** The 422 response has a JSON body (`{"detail": [...]}`) that the frontend parsed as a normal response. Since `data.results` is undefined in a 422 body, the UI rendered empty results with no error indication. The frontend now handles non-OK responses explicitly, but if you add new Pydantic validation constraints, test with realistic long-route payloads.

## 13. Frontend must handle non-2xx from spatial endpoint

The `performSearch()` function in `app.js` only special-cased 404/405 (fallback to legacy endpoint). Any other error status (422, 500, 503) was parsed as JSON and treated as a normal response, causing misleading UI. Always check `res.ok` before parsing spatial endpoint responses.

## 14. Git worktrees are BANNED (until further notice)

**Do NOT create `git worktree add` entries under `.claude/worktrees/`** or anywhere else in this project. Do all branch work via `git checkout` in the main repo at `/home/administrator/Code/geographica`.

**Why (two near-misses in 2026-04):**
1. Subagent dispatched to a worktree silently `cd`'d out to the main repo mid-session and committed NOAA work on `dev` instead of the feature branch, contaminating a parallel agent's history. Recovered via `git revert`.
2. A later subagent ran `git reset --hard feat/noaa-conus` on `dev` while the parallel agent had accumulated 19 commits there. Wiped the reachable tip pointer to nav-remediation merges, voice-picker spec, field-test screenshots, and a duplicate peak-disk commit. All recoverable via reflog, but only because the agent paused before pushing.

The common failure mode: subagents treat "current directory" as ambient state and lose track of which checkout they're operating on. Worktree topology multiplies the surface area of the bug: you have two checkouts of the same repo, and ref updates in one are visible to the other, and the "bash session" in an agent can quietly walk from the worktree into the main repo.

**If you see `.claude/worktrees/` in the repo:**
- Treat its existence as a bug, not a feature.
- Do not dispatch subagents into it.
- Do not commit there. Move branch work back to the main repo checkout and delete the worktree with `git worktree remove`.

**When a session handoff says "work in the worktree at X"**, override that instruction: check out the branch in the main repo instead, and note the deviation to the user.
