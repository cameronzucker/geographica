# Bug Hunt Report

## Scope

**Files analyzed:**
- `services/search/main.py` — pipeline API endpoints, credential management, admin status
- `scripts/acquire_imagery.py` — imagery download pipeline (TNMAccess, direct, M2M modes)
- `scripts/download_elevation.py` — elevation tile download pipeline
- `frontend/app.js` — imagery management UI (lines 2225+)
- `frontend/navigation.js` — turn-by-turn navigation engine
- `frontend/nav-ui.js` — navigation UI bridge
- `docker-compose.yml` — service definitions
- `nginx/nginx.conf` — reverse proxy config

**All five passes performed:** Contract Violations, Cross-Sibling Pattern Violations, Failure Mode Reasoning, Concurrency Reasoning, Error Propagation.

## Bugs

### 1. File descriptor leak in `write_pipeline_state` (acquire_imagery.py)
**Location:** `scripts/acquire_imagery.py:81`
**Severity:** significant
**Evidence:** The function calls `os.fsync(tmp_path.open().fileno())`. This opens a new file handle via `tmp_path.open()` which is never closed. The transient `open()` returns a file object that goes out of scope without being closed. On CPython the GC will eventually close it, but in a long-running pipeline writing state every 2000 tiles, this leaks file descriptors continuously. Additionally, `tmp_path.open()` opens in text mode by default; after `write_text()` has already closed, this opens a *second* file handle just for fsync.
**Impact:** In a long pipeline downloading millions of tiles, the process will accumulate hundreds of leaked file descriptors, potentially hitting OS limits and crashing. The elevation script (`download_elevation.py:66-67`) fixes this correctly by using a `with open(tmp_path) as f:` context manager, proving this is a known pattern the imagery script deviated from.
**Found in:** Pass 2 — Cross-Sibling Pattern Violations

### 2. `buildRouteData` omits `totalDistance`, `totalTime`, and `costing` — navigation engine produces wrong ETA
**Location:** `frontend/nav-ui.js:236-241`
**Severity:** significant
**Evidence:** `buildRouteData()` returns `{ coords, maneuvers, summary }` but does NOT set `totalDistance`, `totalTime`, or `costing`. The navigation engine (`navigation.js:444-449`) reads `route.totalDistance`, `route.totalTime`, and `route.costing`. Without `totalDistance`/`totalTime`, the ETA calculation in `buildState` (line 446-448) uses `undefined * fraction` = `NaN`. Without `costing`, the voice threshold lookup (line 329) falls back to `VOICE_THRESHOLDS.auto` (minor), but the ETA/time display is broken. The Valhalla trip object has `trip.summary.length` (meters) and `trip.summary.time` (seconds) and the costing is available from the request, but none are extracted.
**Impact:** Time remaining shows NaN or 0 during navigation. ETA display is broken. Speed ratio recording (line 533-535) divides by 0 (`route.totalTime` is undefined), producing `Infinity`, which pollutes the speed history.
**Found in:** Pass 1 — Contract Violations

### 3. `onNavUpdate` reads wrong property names from engine state object
**Location:** `frontend/nav-ui.js:342-397`
**Severity:** significant
**Evidence:** The `onNavUpdate` callback receives the state object from `buildState()` in `navigation.js:482-497`. The engine emits: `nextManeuver: { instruction, type, distanceTo, lanes }`, `afterNextManeuver: { instruction, type, distanceTo }`, `state` (lowercase string like `"navigating"`). But `onNavUpdate` reads: `state.instruction` (undefined — it's `state.nextManeuver.instruction`), `state.distanceToManeuver` (undefined — it's `state.nextManeuver.distanceTo`), `state.afterNext` (undefined — it's `state.afterNextManeuver`), `state.maneuverType` (undefined — it's `state.nextManeuver.type`), `state.remainingDistance` (correct: `distanceRemaining`... wait, the property is `distanceRemaining` and the UI reads `remainingDistance` — these don't match), `state.remainingTime` (correct: `timeRemaining` in engine, `remainingTime` in UI — mismatch). Also, engine emits lowercase state names (`"rerouting"`, `"joining"`) but the UI compares to uppercase (`"REROUTING"`, `"JOINING"`).
**Impact:** The navigation UI instruction card, distance-to-maneuver, after-next hint, maneuver icon, remaining distance, remaining time, and state banners are all broken — they read `undefined` or never match, rendering the nav overlay essentially non-functional.
**Found in:** Pass 1 — Contract Violations

### 4. Pipeline cancel does not update state file — leaves stale "running" state
**Location:** `services/search/main.py:808-824`
**Severity:** significant
**Evidence:** `pipeline_cancel()` stops the Docker container but never writes to the state file. The state file still says `"status": "running"`. The next call to `pipeline_status()` will check `_is_pipeline_container_running()`, find it dead, and write `"interrupted"` to the state file (line 783-789). However, the cancel endpoint returns `{"status": "cancelling"}` and the frontend UI calls `fetchPipelineStatus()` immediately after cancel succeeds (app.js:2547). Since Docker `container.stop(timeout=30)` is synchronous and may take up to 30 seconds, the status endpoint races: it may check before the container actually exits, find it still "running", and report "running" to the frontend. The user sees the pipeline as still running despite cancelling.
**Impact:** After clicking cancel, the UI may continue showing "Running..." for up to 30 seconds until the next poll detects the container is dead. The cancel endpoint should write "cancelling" to the state file immediately.
**Found in:** Pass 3 — Failure Mode Reasoning

### 5. Disk space estimate uses wrong per-tile size (50 KB server vs 15 KB frontend)
**Location:** `services/search/main.py:619`, `frontend/app.js:2425`
**Severity:** minor
**Evidence:** The server estimates `50 * 1024` bytes per tile (50 KB) for the disk space guard, but the frontend estimates `15 * 1024` bytes per tile (15 KB) in `formatTileEstimate`. These are 3.3x apart. An operator sees an estimated 15 GB download in the UI but the server may reject it for insufficient disk space as if it were 50 GB.
**Impact:** Confusing UX — the user sees an estimate of N GB but the server rejects it claiming it needs 3.3x more space. Not a correctness bug per se, but causes unexpected pipeline start failures with misleading error messages.
**Found in:** Pass 2 — Cross-Sibling Pattern Violations

### 6. Pipeline start sends `remove=True` — container auto-removes on stop, preventing log retrieval
**Location:** `services/search/main.py:721-731`
**Severity:** minor
**Evidence:** The pipeline container is started with `remove=True` (auto-remove on exit). When the pipeline fails or is cancelled, the container and its logs are immediately destroyed. The `pipeline_status` endpoint checks `_is_pipeline_container_running()` which calls `client.containers.get("geographica-pipeline")` — but if the container exited (even normally), `remove=True` means it no longer exists, and the pipeline state file is the only record. If the script crashes before writing "failed" to the state file, the state remains "running" forever (orphaned state).
**Impact:** On script crash (OOM, unhandled exception), the state file stays at "running", the container is gone, and `pipeline_status` will set it to "interrupted" on next poll. But any error details in the container logs are lost. The operator cannot diagnose what went wrong.
**Found in:** Pass 3 — Failure Mode Reasoning

### 7. Volume mount resolution falls back to container-internal paths, which won't work for Docker SDK
**Location:** `services/search/main.py:697-718`
**Severity:** significant
**Evidence:** The Docker SDK `client.containers.run()` needs HOST paths for bind mounts. The fallback at line 697-699 uses `"/data": {"bind": "/data", "mode": "rw"}`, which is the *container-internal* path of the search service, not the host path. If the search container introspection at lines 703-716 fails (the `try/except` catches all exceptions), the pipeline container would be started with a bind mount from the search container's internal path — which doesn't exist on the host. The pipeline container would start with an empty `/data` directory.
**Impact:** If `client.containers.get("geographica-search")` fails or the mount introspection fails, the pipeline runs in a container with no data access, silently writing tiles to a container-local `/data` that is discarded on exit (due to `remove=True`). All downloaded tiles are lost.
**Found in:** Pass 3 — Failure Mode Reasoning

### 8. Concurrent SQLite writes in `run_direct` — multiple coroutines write to single aiosqlite connection without batching guarantees
**Location:** `scripts/acquire_imagery.py:394-414`
**Severity:** minor
**Evidence:** In `run_direct`, up to 2000 `_fetch_tile` coroutines are gathered concurrently (line 437-438). Each coroutine calls `db.execute()` for INSERT into tiles and INSERT into _checkpoint. `aiosqlite` serializes these through a background thread, so there's no actual SQLite concurrency issue. However, the progress bar and commit only happen after the entire batch completes. If the process is killed mid-batch (e.g., OOM), all tiles fetched in that batch are lost because `db.commit()` hasn't been called yet. The elevation script has the same pattern.
**Impact:** On crash mid-batch, up to 2000 tiles (imagery) or 500 tiles (elevation) of work is lost. Not a data corruption risk, just wasted bandwidth on resume.
**Found in:** Pass 4 — Concurrency Reasoning

### 9. `_pipeline_lock` only guards the start path — status and cancel operate without the lock
**Location:** `services/search/main.py:36`, `services/search/main.py:757-824`
**Severity:** minor
**Evidence:** `_pipeline_lock` is acquired in `pipeline_start()` to prevent concurrent starts. But `pipeline_status()` reads and writes the state file without holding the lock, and `pipeline_cancel()` stops the container without holding the lock. If two cancel requests arrive simultaneously, `container.stop()` is called twice. The second call will hit the `except Exception: pass` block, which is safe. If a start and cancel race, the start holds the lock, so cancel proceeds immediately while start is still setting up. The cancel finds no container (hasn't started yet), silently passes, and the start proceeds. This is mostly safe but the lock gives a false sense of protection.
**Impact:** Low practical impact — the races resolve safely due to Docker's own idempotency. But the state file could be corrupted if `pipeline_start` writes "running" while `pipeline_status` simultaneously writes "interrupted".
**Found in:** Pass 4 — Concurrency Reasoning

### 10. `estimate_tile_count` uses `int()` truncation producing off-by-one vs actual pipeline tile count
**Location:** `services/search/main.py:72-87` vs `scripts/acquire_imagery.py:124-138`
**Severity:** minor
**Evidence:** Both the server (`estimate_tile_count`) and the pipeline (`tile_ranges` + `deg2tile`) use `int()` for coordinate-to-tile conversion, which truncates toward zero. This is correct for positive values but wrong for negative longitudes in the western hemisphere where `int()` truncates toward zero (e.g., `int(-0.3)` = 0, but `math.floor(-0.3)` = -1). However, the `(lon + 180) / 360 * n` formula always produces positive values for valid longitudes, so this is actually fine. The latitude formula `(1 - log(...) / pi) / 2 * n` also produces positive values for valid latitudes. No actual bug here upon closer analysis — the `int()` truncation matches `math.floor()` for positive values.

*Retracted — not a bug.*

## Design Concerns

### State file as coordination mechanism
The pipeline state file (`.pipeline-state.json`) is used as the communication channel between the pipeline script (writer), the search service (reader/writer), and the frontend (reader via API). There's no file locking, and the search service both reads and writes to it. The pipeline script's atomic write (write tmp + os.replace) protects against partial reads, but the search service's reconciliation write (`pipeline_status` writing "interrupted") can race with the pipeline script's progress writes. This is mitigated by the fact that reconciliation only happens when the container is dead, but the pattern is fragile.

### No authentication on pipeline status endpoint
`/admin/pipeline/status` and `/admin/credentials/status` have no auth requirement. While these are read-only, they expose operational details (bbox, zoom, disk space, whether credentials exist) to any network client. On an AREDN mesh network, this may be acceptable, but it's worth noting.

### Navigation engine/UI interface contract is undocumented and mismatched
The nav engine (`navigation.js`) and nav UI (`nav-ui.js`) communicate through callback objects with specific property names, but there's no shared type definition or contract. The current mismatch (Bug #3) shows this is fragile. Any change to the engine's state object shape silently breaks the UI.

### Container orchestration from inside a container
The search service starts pipeline containers by talking to the Docker socket from inside its own container. This requires resolving host paths from container mount metadata, which is fragile (Bug #7). A more robust approach would be `docker compose run --no-deps pipeline ...` from a host-level orchestrator, but the current design works when mount introspection succeeds.
