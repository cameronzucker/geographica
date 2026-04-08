# Pipeline + Navigation Bug Hunt — Consolidated Findings

**Date:** 2026-04-08
**Scope:** Imagery pipeline management system + turn-by-turn navigation engine
**Hunters:** Exploratory, Holistic, Multipass

---

## Confirmed Bugs

### B1. Navigation UI reads wrong property names from engine state
**Consensus:** All 3 hunters (E1, M3, H4, H7)
**Location:** `frontend/nav-ui.js:342-397` vs `frontend/navigation.js:482-497`
**Evidence:** Engine emits `state.nextManeuver.instruction`, `state.nextManeuver.distanceTo`, `state.nextManeuver.type`, `state.afterNextManeuver`, `state.distanceRemaining`, `state.timeRemaining` (lowercase state strings). UI reads `state.instruction`, `state.distanceToManeuver`, `state.maneuverType`, `state.afterNext`, `state.remainingDistance`, `state.remainingTime` (uppercase state comparisons). All are `undefined`.
**Impact:** The entire navigation overlay is non-functional — shows blank instructions, no distance, no icons, no ETA. State banners for JOINING/REROUTING never appear.
**Blast radius:** nav-ui.js only
**Fix approach:** Update nav-ui.js `onNavUpdate()` to read the correct property paths from the engine's state object. Change uppercase state comparisons to lowercase.

### B2. File descriptor leak in write_pipeline_state
**Consensus:** All 3 hunters (E2, M1, H1)
**Location:** `scripts/acquire_imagery.py:81`
**Evidence:** `os.fsync(tmp_path.open().fileno())` opens a file handle that is never closed. Called every 2000 tiles. The sibling `download_elevation.py:66-67` does this correctly with `with open(tmp_path) as f: os.fsync(f.fileno())`.
**Impact:** Long downloads (millions of tiles) exhaust the OS file descriptor limit (~1024 on Pi 5) and crash.
**Blast radius:** acquire_imagery.py only
**Fix approach:** Use `with open(tmp_path) as f: os.fsync(f.fileno())` matching the elevation script.

### B3. buildRouteData omits totalDistance, totalTime, and costing
**Consensus:** All 3 hunters (E3, M2, H3)
**Location:** `frontend/nav-ui.js:236-241`
**Evidence:** Returns `{ coords, maneuvers, summary }` but engine reads `route.totalDistance`, `route.totalTime`, `route.costing`. All undefined.
**Impact:** ETA shows NaN/Invalid Date, speed history never recorded, voice thresholds always default to "auto" regardless of travel mode, reroutes always use auto costing.
**Blast radius:** nav-ui.js only
**Fix approach:** Add `totalDistance: summary.length * (useImperial ? 1609.344 : 1000)`, `totalTime: summary.time || 0`, `costing: trip.costing || 'auto'` to the returned object.

### B4. Pipeline cancel doesn't update state file
**Consensus:** All 3 hunters (E4, M4, M8, H2)
**Location:** `services/search/main.py:808-824`
**Evidence:** `pipeline_cancel()` stops the container but never writes to the state file. State stays "running" until next status poll reconciles to "interrupted". Cancel doesn't know the pipeline type (imagery vs elevation) so can't even target the right state file.
**Impact:** Confusing UI — shows "Running" after cancel for up to 30 seconds.
**Blast radius:** main.py only
**Fix approach:** Write "cancelling" status to both state files immediately on cancel. Track the pipeline type in the state file so cancel can target the right one.

### B5. Script progress overwrites API state metadata
**Consensus:** Holistic only (H8), verified by consolidation
**Location:** `scripts/acquire_imagery.py:91-102` overwrites `services/search/main.py:734-745`
**Evidence:** API writes config metadata (bbox, zoom, type, container_id, estimated_tiles) to state file. Script's first progress update atomically replaces the entire file with only progress fields (status, tiles_done, tiles_total, rate_per_sec). All config metadata is lost.
**Impact:** Status endpoint can't recalculate estimated_tiles because bbox/zoom are gone from the file.
**Blast radius:** acquire_imagery.py + main.py
**Fix approach:** Script progress writes should merge with existing state file content, not replace it. Read existing state, update progress fields, write back.

### B6. Volume mount resolution fallback uses container-internal path
**Consensus:** 2 hunters (M7, H6)
**Location:** `services/search/main.py:697-718`
**Evidence:** If mount introspection fails (bare except), fallback uses `"/data": {"bind": "/data"}` — container-internal paths, not host paths. Docker SDK needs host paths for volume mounts. Pipeline container gets an empty /data.
**Impact:** On introspection failure, pipeline silently downloads to throwaway filesystem. All data lost on container exit (remove=True).
**Blast radius:** main.py only
**Fix approach:** Use a well-known host path from an environment variable (e.g., DATA_HOST_PATH) instead of introspection. Fail loudly if not set rather than silent fallback.

### B7. Tile size estimate mismatch between frontend and backend
**Consensus:** All 3 hunters (E5, M5, H5)
**Location:** `services/search/main.py:619` (50KB), `frontend/app.js:2425` (15KB)
**Evidence:** 3.3x discrepancy. Users see smaller estimates than what the server validates.
**Impact:** Confusion when server rejects a download the user thought would fit.
**Blast radius:** Frontend + backend
**Fix approach:** Align on 20KB (actual average from our downloads is ~15-20KB for USGS imagery tiles). Use same constant in both places.

---

## Design Decisions Requiring User Input

### D1. remove=True on pipeline container prevents crash diagnosis
**Location:** `services/search/main.py:726`
**The concern:** Container auto-removes on exit, destroying logs and crash context.
**Why this needs a decision:** Keeping stopped containers accumulates disk usage. Removing them loses diagnostic info.
**Options:** (A) Keep remove=True, accept log loss. (B) Set remove=False, add manual cleanup. (C) Copy last N log lines to state file before container removal.
**Recommendation:** Option C — write last 50 log lines to the state file's `error` field when the container exits with non-zero status.

### D2. _pipeline_lock scope is incomplete
**Location:** `services/search/main.py:36, 757-824`
**The concern:** Lock protects start but not status reads/writes or cancel.
**Why this needs a decision:** Adding locks to status and cancel adds latency to polling. Current approach works due to Docker idempotency.
**Options:** (A) Accept current design — practical risk is minimal. (B) Add lock to cancel (not status, which is read-only).
**Recommendation:** Option B — lock cancel only.

### D3. No elevation pipeline UI path
**The concern:** Frontend hardcodes `type: 'imagery'`. Elevation pipeline endpoints exist but are unreachable from the browser.
**Options:** (A) Add elevation tab to imagery panel. (B) Defer — elevation download is a one-time setup task already handled via CLI.
**Recommendation:** Option B for now — elevation is infrequent and works fine via CLI.

---

## False Positives

### FP1. parse_zoom fragility with negative inputs
**Flagged by:** Exploratory (E6)
**Why invalid:** The CLI validates input before reaching this function. The API endpoint also validates zoom input. Negative zoom levels are unreachable through any user-facing path.

---

## Bugs Outside Primary Scope

None identified — all findings are within the scoped code.

---

## Test Gap Analysis

### B1. Nav UI field name mismatch
**Why missed:** No tests exist. The nav engine and UI were built by separate agents with no integration test.
**Catch test:** Verify that calling `GeographicaNav.getState()` after starting navigation returns an object whose properties match what `onNavUpdate()` reads.

### B2. File descriptor leak
**Why missed:** No unit tests for write_pipeline_state. The leak only manifests after hundreds of calls.
**Catch test:** Call write_pipeline_state 1100 times in a loop, verify no OSError from fd exhaustion.

### B3. buildRouteData missing fields
**Why missed:** No integration test between nav-ui.js buildRouteData() and navigation.js start().
**Catch test:** Verify buildRouteData output contains totalDistance, totalTime, costing fields.

### B4-B8: Pipeline API bugs
**Why missed:** No API tests exist for the new endpoints.
**Catch test:** Integration tests against the running search service.

### Testing Pitfalls Updates
- None (dev/testing-pitfalls.md does not exist)
