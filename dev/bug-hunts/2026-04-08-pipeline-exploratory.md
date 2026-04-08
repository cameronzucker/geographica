# Bug Hunt Report

## Scope

**Deep analysis** of the imagery pipeline management system and navigation engine. Files explored:

- `services/search/main.py` — pipeline API endpoints, credential storage, admin auth
- `scripts/acquire_imagery.py` — SIGTERM handler, progress writing, M2M API flow, direct tile download
- `scripts/download_elevation.py` — SIGTERM handler, progress writing
- `frontend/app.js` — imagery management UI (initImageryPanel, adminFetch, pipeline status)
- `frontend/navigation.js` — turn-by-turn navigation engine
- `frontend/nav-ui.js` — navigation UI bridge
- `docker-compose.yml` — pipeline service definition
- `nginx/nginx.conf` — admin route proxying

**Why these were high-risk:** Pipeline orchestration coordinates between Docker SDK, filesystem state, and subprocess management across containers. Navigation engine has complex state machine with dead reckoning and rerouting. The UI bridge between nav engine and nav-ui is a classic contract mismatch hotspot.

## Bugs

### 1. File descriptor leak in `write_pipeline_state` (acquire_imagery.py)

**Location:** `scripts/acquire_imagery.py:80`
**Severity:** significant
**Evidence:**
```python
os.fsync(tmp_path.open().fileno())
```
`tmp_path.open()` creates a file object that is never closed. On CPython the refcount-based GC will eventually close it, but this function is called every 2000 tiles during a download that may process millions of tiles. Over a long run, hundreds of leaked file descriptors accumulate. On a Raspberry Pi 5 with default `ulimit -n 1024`, this will eventually hit the FD limit and crash the pipeline.

The `download_elevation.py:65-66` version has the same pattern but uses a slightly different form:
```python
with open(tmp_path) as f:
    os.fsync(f.fileno())
```
This is correct (uses `with` to close). The imagery script has the bug; the elevation script does not.

**Impact:** Long imagery downloads (millions of tiles) will exhaust file descriptors and crash, losing progress since the last batch commit.

---

### 2. Navigation UI reads wrong field names from engine state object

**Location:** `frontend/nav-ui.js:342-367` vs `frontend/navigation.js:482-497`
**Severity:** critical
**Evidence:**

The navigation engine's `buildState()` emits this shape:
```js
{
  nextManeuver: { instruction, type, distanceTo },
  afterNextManeuver: { instruction, type, distanceTo },
  distanceRemaining: ...,
  timeRemaining: ...,
  // ...
}
```

But `onNavUpdate` in `nav-ui.js` reads:
- `state.instruction` (should be `state.nextManeuver.instruction`) — line 347
- `state.distanceToManeuver` (should be `state.nextManeuver.distanceTo`) — line 351
- `state.afterNext` (should be `state.afterNextManeuver.instruction`) — line 356
- `state.maneuverType` (should be `state.nextManeuver.type`) — line 364
- `state.remainingDistance` (correct, matches `distanceRemaining`... actually this is also wrong: engine emits `distanceRemaining`, UI reads `remainingDistance`) — line 369
- `state.remainingTime` (correct, matches `timeRemaining`... same issue: engine emits `timeRemaining`, UI reads `remainingTime`) — line 372

**All of these will be `undefined`**, so the navigation overlay will show blank instruction text, no distance-to-maneuver, no maneuver icons, and no ETA/remaining distance. The navigation UI is completely non-functional — it renders but shows nothing.

**Impact:** Turn-by-turn navigation overlay is visually broken. All instruction, distance, time, and icon fields remain empty/unchanged during navigation.

---

### 3. `buildRouteData` omits `totalDistance`, `totalTime`, and `costing` needed by nav engine

**Location:** `frontend/nav-ui.js:236-240`
**Severity:** significant
**Evidence:**

`buildRouteData()` returns:
```js
{ coords, maneuvers, summary }
```

But the navigation engine accesses:
- `route.totalDistance` (line 445, 533) — used for ETA calculation and speed recording
- `route.totalTime` (line 447, 533) — used for ETA calculation
- `route.costing` (line 329, 608) — used for voice threshold selection and reroute requests

All three are `undefined`. Valhalla provides `trip.summary.length` (in the unit requested) and `trip.summary.time` (in seconds), but they're buried inside `summary` and never extracted.

**Impact:**
- `route.totalTime` being `undefined` means `(route.totalTime || 0)` = 0, so `baseTimeRemain` = 0 always, so ETA shows current time (0 seconds remaining).
- `route.totalDistance` being `undefined` falls back to `cumulativeDistances` (haversine-based), which is reasonable, but the speed recording at line 533 checks `route.totalDistance > 0` which is `undefined > 0` = `false`, so speed history is never recorded, and `speedRatio()` always returns 1.0. ETA adjustments based on actual speed never happen.
- `route.costing` being `undefined` falls back to `VOICE_THRESHOLDS.auto` (line 329), so voice thresholds default to `auto` even for bicycle/pedestrian. Minor but incorrect.
- On reroute, `info.costing` will be `undefined`, and `onReroute` in nav-ui.js defaults to `'auto'` (line 433). So reroutes always use auto costing regardless of original mode.

---

### 4. Pipeline cancel does not update state file — leaves stale "running" status

**Location:** `services/search/main.py:808-824`
**Severity:** significant
**Evidence:**

`pipeline_cancel()` stops the container but does not write to the state file (`.pipeline-state.json` or `.elevation-state.json`). After cancellation, the state file still says `"status": "running"`.

The `pipeline_status()` endpoint (line 783) has reconciliation logic: if state says "running" but container is dead, it marks "interrupted". However, there's a race: between `container.stop()` and Docker actually removing the container (`remove=True` was set on creation), the container might still be listed as running briefly. More importantly, `pipeline_cancel` returns `{"status": "cancelling"}` to the frontend, and the next status poll will say "interrupted" — but only after the 30-second stop timeout elapses.

The script's SIGTERM handler writes `status: "cancelled"` to the state file, but only if `_cancel_requested` is checked at a batch boundary. If the container is killed between batches (the 30-second timeout in `container.stop`), Docker sends SIGKILL after SIGTERM timeout, and the state file never gets updated.

**Impact:** After cancellation, the UI may show "interrupted" instead of "cancelled" for up to 30+ seconds, and if the process gets SIGKILLed, the state permanently shows "running" until the next status poll reconciles it to "interrupted".

---

### 5. Tile count estimate discrepancy: frontend shows ~3.3x smaller size than backend validates

**Location:** `frontend/app.js:2425` vs `services/search/main.py:619`
**Severity:** minor
**Evidence:**

Frontend confirmation dialog: `count * 15 * 1024` bytes (15 KB/tile)
Backend disk space check: `tile_count * 50 * 1024` bytes (50 KB/tile)

When the user clicks "Start Download", the confirmation dialog says (e.g.) "~30 GB" but the backend reserves disk space assuming ~100 GB. The user sees a much smaller number than the server's actual estimate. This could lead to user confusion when disk space rejections say "estimated need: 100 GB" but the dialog said 30 GB.

**Impact:** User confusion about actual disk usage. Could lead to operators being surprised by rejection on disk space grounds when the UI showed a much smaller estimate.

---

### 6. `_zoom` parsing silently breaks for negative bbox values passed via CLI

**Location:** `scripts/acquire_imagery.py:117` and `scripts/download_elevation.py:85`
**Severity:** minor (currently avoided by how the API calls the scripts)
**Evidence:**

```python
def parse_zoom(s: str) -> tuple[int, int]:
    if "-" in s:
        lo, hi = s.split("-", 1)
        return int(lo), int(hi)
```

This works for `"0-14"`, but the `--zoom` flag is a separate argument. No bug here in normal use. However, if `argparse` were ever to receive a zoom value like `"-1"` (negative), `"-" in s` would be True, and `s.split("-", 1)` would give `["", "1"]`, causing `int("")` to throw ValueError. This is a minor robustness issue since zoom is always 0+ in practice, and the main.py `_parse_zoom` validates `zoom_min < 0` anyway.

**Impact:** Minimal — defensive coding issue rather than a reachable bug.

## Design Concerns

### Stale state file as single source of truth for pipeline status

The pipeline orchestration relies on a JSON state file (`.pipeline-state.json`) as the coordination mechanism between the search service API and the pipeline container. Both the API server and the pipeline script write to this file, creating a potential for conflicting writes. The reconciliation logic in `pipeline_status()` (line 783) catches the case where state says "running" but the container is dead, but there's no reverse check: if the state file says "completed" but a new container is being started, the state file from the old run would be stale for a brief moment.

### Navigation engine/UI contract is implicit and undocumented

The field names emitted by `buildState()` in `navigation.js` and consumed by `onNavUpdate()` in `nav-ui.js` have no shared type definition or validation. The complete mismatch (Bug #2) went undetected because there is no runtime validation. This is a systemic design risk — any field rename in either file silently breaks the integration.

### Docker-in-Docker volume mount path discovery is fragile

The pipeline start logic (main.py lines 702-718) discovers the host's data path by inspecting the search container's own mounts and deriving the scripts path as a sibling directory. If the directory layout changes (e.g., scripts moved, or data mount path altered), this silently falls back to `/data:/data` (line 698-699), which won't work because `/data` inside the search container is not a host path — Docker SDK volume mounts require host paths. The fallback is silently wrong.
