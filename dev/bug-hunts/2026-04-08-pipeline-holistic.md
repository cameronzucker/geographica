# Bug Hunt Report

## Scope
Analyzed the imagery pipeline management system across 8 source files:
- `services/search/main.py` — Pipeline API endpoints (credential storage, start/stop/status, auth)
- `scripts/acquire_imagery.py` — SIGTERM handler, progress output, 3 download modes
- `scripts/download_elevation.py` — SIGTERM handler, progress output, tile download
- `frontend/app.js` — Imagery management UI (admin panel, pipeline controls, status display)
- `frontend/navigation.js` — Turn-by-turn navigation engine
- `frontend/nav-ui.js` — Navigation UI bridge
- `docker-compose.yml` — Service definitions including pipeline
- `nginx/nginx.conf` — Reverse proxy configuration

Approach: Read all files into context, then traced data flows across boundaries — API contracts between frontend and backend, state file semantics between scripts and the search service, Docker container lifecycle, volume mount resolution, and the navigation engine's state machine.

## Bugs

### 1. File descriptor leak in `write_pipeline_state` (acquire_imagery.py)
**Location:** `scripts/acquire_imagery.py:81`
**Severity:** significant
**Evidence:** The `os.fsync(tmp_path.open().fileno())` call opens a new file handle via `tmp_path.open()` but never closes it. The `open()` return value is a temporary object — its file descriptor is passed to `fsync`, but the file object itself is not stored or closed. In CPython this relies on garbage collection to close the fd, but during a long-running download with periodic progress updates, this leaks a file descriptor on every batch (every 2000 tiles). Over a large download of millions of tiles, this accumulates hundreds of leaked fds.
**Impact:** On a Raspberry Pi with default ulimits (~1024 fds), a large download could hit the fd limit and crash with `OSError: [Errno 24] Too many open files`. The elevation script (`download_elevation.py:66`) correctly avoids this by using `with open(tmp_path) as f: os.fsync(f.fileno())`.

### 2. Pipeline cancel does not update state file — status stuck as "running" until next poll
**Location:** `services/search/main.py:808-824`
**Severity:** significant
**Evidence:** `pipeline_cancel()` calls `container.stop()` but does not update the state file (`.pipeline-state.json` or `.elevation-state.json`). The state file reconciliation only happens in `pipeline_status()` (line 783), which checks if the container is dead and then marks it "interrupted". This means:
1. After cancellation, the state file still says `"status": "running"` until someone GETs `/admin/pipeline/status`.
2. If the script's SIGTERM handler runs and writes `"status": "cancelled"`, that write and the status endpoint's "interrupted" overwrite race. The status endpoint always overwrites to "interrupted" because it checks `state == "running" and not container_running`, but the script may have already written "cancelled".
3. The cancel endpoint returns `{"status": "cancelling"}` immediately, but the frontend calls `fetchPipelineStatus()` right after — which may read the stale "running" state before the container has actually stopped (the stop has a 30-second timeout).
**Impact:** The UI may briefly show "Running..." after cancellation, then flip to "Interrupted" instead of "Cancelled". The user sees confusing intermediate states.

### 3. `buildRouteData` missing `totalDistance`, `totalTime`, and `costing` — navigation ETA broken
**Location:** `frontend/nav-ui.js:216-241`
**Severity:** critical
**Evidence:** `buildRouteData(trip)` constructs the route object passed to `GeographicaNav.start()`. The navigation engine reads `route.totalDistance` (navigation.js:445), `route.totalTime` (navigation.js:448), and `route.costing` (navigation.js:329). However, `buildRouteData` returns `{ coords, maneuvers, summary }` — it never sets `totalDistance`, `totalTime`, or `costing`. Valhalla puts these in `trip.summary.length` (meters) and `trip.summary.time` (seconds), and the costing is at `trip.legs[0].summary.costing` or as a request parameter.

Without `totalDistance` and `totalTime`:
- `route.totalDistance` is `undefined`, so `speedRatio()` recording (navigation.js:533-535) has `route.totalDistance > 0` evaluating to `false` (undefined > 0 is false), so speed history is never recorded.
- `buildState` (navigation.js:445): `totalDist` falls back to `cumulativeDistances[route.coords.length - 1]` which works, but `route.totalTime` is `undefined`, so `baseTimeRemain = undefined * fraction = NaN`. The ETA becomes `new Date(Date.now() + NaN)` which is `Invalid Date`.
- `route.costing` is `undefined`, so `VOICE_THRESHOLDS[route.costing]` is `undefined`, falling back to `VOICE_THRESHOLDS.auto` — this works but is always "auto" even for bicycle/pedestrian routes.

**Impact:** ETA display shows "Invalid Date" or "NaN" for every navigation session. Voice thresholds are always auto-mode regardless of actual travel mode. The time remaining display in the nav overlay shows "NaN min".

### 4. `onNavUpdate` reads wrong property names from engine state object
**Location:** `frontend/nav-ui.js:342-397`
**Severity:** critical
**Evidence:** The navigation engine's `buildState()` (navigation.js:482-497) emits state objects with these property names:
- `nextManeuver.instruction` and `nextManeuver.distanceTo` for the next turn
- `afterNextManeuver.instruction` for the after-next hint
- `nextManeuver.type` for the maneuver icon type
- `distanceRemaining` for remaining route distance
- `timeRemaining` for remaining time

But `onNavUpdate` in nav-ui.js reads:
- `state.instruction` (line 347) — should be `state.nextManeuver.instruction`
- `state.distanceToManeuver` (line 351) — should be `state.nextManeuver.distanceTo`
- `state.afterNext` (line 356) — should be `state.afterNextManeuver ? state.afterNextManeuver.instruction : null`
- `state.maneuverType` (line 364) — should be `state.nextManeuver ? state.nextManeuver.type : null`
- `state.remainingDistance` (line 369) — correct, matches engine
- `state.remainingTime` (line 372) — correct, matches engine

The mismatch means the instruction text, distance-to-next-turn, after-next hint, and maneuver icon are never populated because the properties read are always `undefined`.
**Impact:** During navigation, the instruction card is blank — no turn instructions, no distance to next turn, no turn icon, and no "then..." hint are ever displayed. The nav overlay is effectively empty except for the status bar (remaining distance/time/speed).

### 5. Disk space estimate uses 50 KB/tile in backend but 15 KB/tile in frontend
**Location:** `services/search/main.py:619` and `frontend/app.js:2425`
**Severity:** minor
**Evidence:** The backend estimates `50 * 1024` bytes per tile for disk space checks (main.py:619). The frontend estimates `15 * 1024` bytes per tile for the user-facing estimate display (app.js:2425). This 3.3x discrepancy means: the frontend tells the user "estimated 45 GB" but the backend rejects it with "insufficient disk space" because it calculates 150 GB needed.
**Impact:** Users may be confused when a download they're told needs ~X GB is rejected by the server for needing ~3.3X GB. The guard is overly conservative or the estimate is misleading — either way they disagree.

### 6. Volume mount resolution assumes scripts dir is a sibling of data dir on host
**Location:** `services/search/main.py:709-715`
**Severity:** significant
**Evidence:** When starting the pipeline container, the search service inspects its own mounts to find the host path for `/data`, then derives the scripts path as `os.path.dirname(host_data_path) + "/scripts"` (line 711). This assumes the host directory layout has `scripts/` as a sibling of the `data/` directory. However, per the project's CLAUDE.md and `feedback_data_outside_repo.md`, data lives at `/srv/geographica/data/` while the repo (containing `scripts/`) is at `/home/administrator/Code/geographica/`. The docker-compose maps `./data:/data` and `./scripts:/scripts:ro`, but if the data volume is reconfigured to point to `/srv/geographica/data/`, then `os.path.dirname("/srv/geographica/data")` is `/srv/geographica`, and `/srv/geographica/scripts` doesn't exist.

The code falls back to the passthrough `{"/data": {"bind": "/data", "mode": "rw"}}` (line 698) on exception, but that mapping from inside the container's `/data` to the pipeline container's `/data` won't work because Docker SDK bind mounts require host paths, not container paths. Passing a container-internal path like `/data` as a host path will create a new empty directory on the host.
**Impact:** If the mount inspection fails (which is the fallback path), the pipeline container starts with an empty `/data` directory and an absent `/scripts` directory, causing the download script to fail immediately with a file-not-found error. Even on the happy path, the scripts path derivation is fragile and will break if data is stored outside the repo tree.

### 7. Navigation engine state values use lowercase but UI checks uppercase
**Location:** `frontend/navigation.js:482` and `frontend/nav-ui.js:390-395`
**Severity:** significant
**Evidence:** The navigation engine's `buildState()` returns `state: state` (navigation.js:483) where `state` is the engine's internal variable, which uses lowercase values: `"idle"`, `"joining"`, `"navigating"`, `"rerouting"`, `"arrived"` (see navigation.js line 11 comment and lines 541, 547, 560, 569, 600, 699, 749).

But `onNavUpdate` in nav-ui.js checks for uppercase values:
- `state.state === 'REROUTING'` (line 391)
- `state.state === 'JOINING'` (line 393)

These comparisons will never match, so the "Recalculating..." and "Joining route..." banners are never shown via the state check (though the reroute banner is separately triggered by `onReroute` callback at line 414).
**Impact:** During the JOINING phase (approaching the route from an off-route position), no "Joining route..." banner is displayed. The "Recalculating..." banner from state checks is also missed, though the `onReroute` callback partially compensates for this.

### 8. Elevation pipeline status read from wrong state file path by search service
**Location:** `services/search/main.py:559-563` vs `scripts/download_elevation.py:62`
**Severity:** significant
**Evidence:** `_state_file_for_type("elevation")` in the search service returns `DATA_DIR / ".elevation-state.json"` (main.py:562). The elevation download script writes to `Path(output_path).parent / ".elevation-state.json"` (download_elevation.py:62). These match only if `output_path` is in `/data/`. 

However, the imagery script's `write_pipeline_state` (acquire_imagery.py:77) always writes to `.pipeline-state.json` regardless of pipeline type. When the search service starts an imagery pipeline, the state file is `.pipeline-state.json` (main.py:563), and the script also writes `.pipeline-state.json` (acquire_imagery.py:77) — these match. But the state file written at pipeline start (main.py:745) uses `_state_file_for_type(body.type)`, while the imagery script's `update_progress` always writes to `.pipeline-state.json`. So the initial state from the API and the progress updates from the script go to the same file — that's fine.

The real bug is more subtle: the pipeline start endpoint writes a state file with `container_id`, `bbox`, `zoom`, etc. (main.py:734-744), then the script overwrites this same file with just `status`, `tiles_done`, `tiles_total`, `rate_per_sec` (acquire_imagery.py:91-102 or download_elevation.py:303-308). The overwrite loses the `bbox`, `zoom`, `type`, `mode`, `concurrency`, `update`, and `estimated_tiles` fields. When `pipeline_status()` later reads the state file, it tries to recalculate `estimated_tiles` from `bbox` and `zoom` (main.py:796-800), but those fields are gone — the recalculation silently fails and `estimated_tiles` is whatever the script wrote (which is nothing, so it uses the frontend's `tiles_total` from the script's progress output).
**Impact:** After the first progress update from the script, the state file loses most of its metadata. The `estimated_tiles` recalculation in the status endpoint fails silently. The `type`, `mode`, and `update` fields vanish, making it impossible to determine what kind of pipeline is running from the state file alone. The frontend's renderPipelineStatus falls back to `data.estimated_tiles` which works only because the script writes `tiles_total`.

## Design Concerns

### State file as IPC between the API and scripts is fragile
The pipeline state file (`.pipeline-state.json`) serves dual duty: the search API writes it at pipeline start (with config metadata), and the download script overwrites it during execution (with progress data). There's no schema versioning, no merge semantics, and no locking. The script's `write_pipeline_state` does an atomic replace, which means every progress update obliterates the API's initial metadata. A better design would separate the API-managed config from the script-managed progress, or have the script append/merge rather than replace.

### Volume mount resolution for the pipeline container is inherently fragile
The search service introspects its own container's mount table to derive host paths for Docker SDK calls. This creates a tight coupling between the compose file layout and the runtime introspection logic. Any change to volume paths (e.g., moving data to `/srv/geographica/data/` as documented) silently breaks the scripts mount derivation. The fallback path (`/data:/data`) is also incorrect because it passes container paths as host paths.

### No elevation pipeline type support in the UI
The frontend's `initImageryPanel` hardcodes `type: 'imagery'` (app.js:2513), `fetchPipelineStatus` queries without a type parameter (app.js:2599) defaulting to `"imagery"`, and the backend's `pipeline_status` defaults to `type="imagery"` (main.py:758). There's no UI path to start, monitor, or cancel an elevation download. The elevation pipeline endpoints exist in the backend but are unreachable from the frontend.

### Pipeline cancel has no correlation to pipeline type
`pipeline_cancel()` (main.py:808-824) stops the `geographica-pipeline` container regardless of which pipeline type is running, and updates no state file. If both imagery and elevation share the same container name (they do — both use `geographica-pipeline`), then cancel is unambiguous, but neither state file gets updated with "cancelled" status. The reconciliation to "interrupted" only happens on the next status poll.
