# Pipeline Status UX — Design Spec

**Date:** 2026-04-09
**Goal:** Make the admin panel accurately represent and control M2M imagery download pipelines with phase-aware progress, fix the service list to exclude pipeline containers, and add a frontend healthcheck.

---

## Problem Statement

The admin panel has four interconnected UX failures:

1. **Pipeline containers pollute the service list.** Docker containers matching `geographica-pipeline*` (both the dormant profile container and active one-off M2M containers) appear as services showing "none" health. They aren't services — they're background jobs.

2. **Frontend shows yellow/none.** The NGINX frontend container has no Docker healthcheck, so it reports `health=none`. The color logic maps `running + none` to yellow, which reads as "degraded" when the service is fine.

3. **M2M progress is invisible.** The pipeline state file tracks `tiles_done/tiles_total`, which is meaningless during M2M's two main phases (scene search and GeoTIFF download). The state file has stale data from a previous run, so the Pipelines tab shows "Resume Download" with a full progress bar — conveying zero useful information.

4. **M2M has a fundamentally different progress model.** Direct mode downloads tiles in one phase. M2M has three phases: search for scenes → download GeoTIFFs in batches → convert to MBTiles via GDAL. Each phase has different units and durations. The GeoTIFF download phase dominates runtime (hours) while tile conversion is fast (minutes).

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| M2M progress model | Phase-aware fields in state file | Shows what's actually happening: "50/1022 GeoTIFFs, batch 2/21" |
| External pipeline tracking | Don't track — admin panel only manages what it starts | CLI-started containers appear nowhere; admin panel is the canonical interface |
| Pipeline containers in service list | Filter to 7 known services | Service list is a health dashboard, not a container list |
| Frontend healthcheck | Add curl-based healthcheck to docker-compose.yml | Every other service has one; catches real NGINX failures |
| Zoom selector for M2M | Disabled with explanation | M2M auto-detects zoom from source GeoTIFF resolution |
| Resume vs Start button | Always "Start Download" | Resume is handled transparently by checkpoint files |

---

## 1. Phase-Aware M2M Progress (acquire_imagery.py)

### State File Schema

The M2M pipeline writes progress to `.pipeline-state.json` via the existing `update_progress()` function. The state file gains phase-aware fields. All fields are always present when `mode=m2m`; fields irrelevant to the current phase are null or 0.

```json
{
  "status": "running",
  "type": "imagery",
  "mode": "m2m",
  "phase": "downloading",
  "bbox": "-113.33,32.51,-111.04,34.04",
  "zoom": "n/a",
  "scenes_total": 1022,
  "geotiffs_downloaded": 50,
  "geotiffs_total": 1022,
  "geotiffs_bytes": 14926643200,
  "current_batch": 2,
  "total_batches": 21,
  "tiles_done": 0,
  "tiles_total": 0,
  "rate_per_sec": 0,
  "started_at": "2026-04-09T02:45:24.872586+00:00",
  "last_updated": "2026-04-09T04:06:19.533520+00:00",
  "error": null,
  "container_id": "abc123"
}
```

### Phase Transitions

The script calls `update_progress()` at each phase boundary:

| Phase | Trigger | Key fields updated |
|-------|---------|-------------------|
| `login` | After `m2m_login()` succeeds | `phase="login"` |
| `searching` | Before `m2m_scene_search()` | `phase="searching"` |
| `downloading` | After scene search, before batch loop | `phase="downloading"`, `scenes_total`, `geotiffs_total`, `total_batches` |
| `downloading` (progress) | After each batch completes | `geotiffs_downloaded += batch_size`, `current_batch`, `geotiffs_bytes` |
| `converting` | After all GeoTIFFs downloaded, before GDAL | `phase="converting"` |
| `converting` (progress) | During GDAL tile conversion (if feasible) | `tiles_done`, `tiles_total` |
| `complete` | After MBTiles written | `phase="complete"`, `status="completed"` |
| `error` | On any fatal error | `phase="error"`, `status="error"`, `error="message"` |

### Changes to `update_progress()`

The function signature gains optional keyword arguments for the new fields. Existing callers (direct mode) are unaffected — they don't pass the new args, so the fields default to null. The function detects `mode="m2m"` and includes the extended fields.

```python
def update_progress(output_path, mode, bbox, zoom,
                    tiles_done, tiles_total, rate=0,
                    status="running", error=None,
                    # M2M-specific fields
                    phase=None,
                    scenes_total=None,
                    geotiffs_downloaded=None, geotiffs_total=None,
                    geotiffs_bytes=None,
                    current_batch=None, total_batches=None):
```

### Changes to `run_m2m()`

Insert `update_progress()` calls at each phase boundary. The function already has natural boundaries (login, scene search, batch loop, GDAL conversion).

For geotiff byte tracking: after each file downloads in `download_geotiffs()`, accumulate the file size. Pass it up to `run_m2m()` via the return value or a shared counter.

For the converting phase: the GDAL conversion in `geotiffs_to_mbtiles()` currently runs as a subprocess. Progress tracking during conversion is optional for this iteration — the converting phase is typically minutes, not hours. Show an indeterminate "Converting GeoTIFFs to tiles..." state. If `gdal2tiles` or the custom conversion writes progress, capture it in a future iteration.

### Changes to `download_geotiffs()`

The function currently returns a list of downloaded file paths. It needs to also report progress during the batch. Two options:

- **Callback approach:** Accept a `progress_callback` that `run_m2m` passes. Called after each file completes with `(downloaded_count, total_count, bytes_so_far)`. The callback calls `update_progress()`.
- **Return-value approach:** Return a richer result object.

Use the callback approach — it integrates naturally with the existing `tqdm` progress bar and allows real-time state file updates during the long download phase.

---

## 2. Service List Filtering (services/search/main.py)

### Known Services Whitelist

Add a module-level constant:

```python
KNOWN_SERVICES = frozenset({
    "frontend", "gps", "nominatim", "search", "stt", "tileserver", "valhalla"
})
```

### Filter in `_list_docker_services()`

After the `for c in sorted(containers, ...)` loop, before appending to `services`, check:

```python
svc_name = c.name.replace("geographica-", "")
if svc_name not in KNOWN_SERVICES:
    continue
```

This filters out `pipeline`, `pipeline-run-*`, and any future one-off containers.

### Skip `estimated_tiles` for M2M in `pipeline_status()`

The B1 bug fix already changed the condition to `if state_data.get("bbox") and state_data.get("zoom")`. M2M state files have `zoom: "n/a"`, which is truthy. Add an additional check:

```python
if state_data.get("bbox") and state_data.get("zoom") and state_data.get("zoom") != "n/a":
```

### Handle M2M in `pipeline_start()`

Currently `pipeline_start()` requires `mode`, `bbox`, and `zoom` for imagery/elevation types. For M2M imagery, zoom is irrelevant (the script determines zoom from GeoTIFF resolution). The validation block needs an M2M branch:

**Validation logic for imagery type:**
```
if body.type == "imagery" and body.mode == "m2m":
    # M2M: bbox required, zoom NOT required
    if not body.bbox:
        raise HTTPException(422, "bbox is required")
    # Skip zoom validation — script auto-detects from GeoTIFF resolution
    zoom = "n/a"
elif body.type in ("imagery", "elevation"):
    # Direct/elevation: bbox AND zoom required
    if not body.mode or body.mode not in ("direct", "m2m"):
        raise HTTPException(422, "mode must be 'direct' or 'm2m'")
    if not body.bbox:
        raise HTTPException(422, "bbox is required")
    if not body.zoom:
        raise HTTPException(422, "zoom is required")
    # ... existing zoom/bbox parse ...
```

**M2M command construction** (different from direct mode):
```python
if body.type == "imagery" and body.mode == "m2m":
    command = [
        "python3", "/scripts/acquire_imagery.py",
        "--mode", "m2m",
        f"--bbox={body.bbox}",
        "--output", "/data/imagery.mbtiles",
        "--staging", "/data/m2m_staging",
        "--concurrency", str(body.concurrency),
    ]
    # M2M credentials passed via env vars (already handled by existing env block)
    # --zoom is intentionally omitted — script auto-detects from source
```

Note: `--staging /data/m2m_staging` provides the GeoTIFF download directory. This is separate from the final MBTiles output.

**State file for M2M:**
```python
state_data = {
    "status": "running",
    "type": body.type,
    "mode": body.mode,
    "phase": "login",  # M2M starts at login phase
    "bbox": body.bbox,
    "zoom": "n/a",
    # ... other fields ...
}
```

### Fix reconciliation for completed-but-exited containers

In `pipeline_status()`, when reconciling `status=running` with a dead container, check the `last_logs` for success indicators before marking as interrupted:

```python
if "MBTiles written to" in (state_data.get("last_logs") or ""):
    new_status = "completed"
else:
    new_status = "interrupted"
```

This handles the case where the script finished successfully but the container exited before the orchestrator could observe it.

---

## 3. Frontend Rendering (frontend/config/index.html)

### Imagery Progress Rendering — Mode Branch

The `renderImageryProgress(data)` function branches on `data.mode`:

**When `mode !== "m2m"` (direct mode):**
Existing behavior — tile progress bar with `tiles_done / tiles_total`.

**When `mode === "m2m"`:**
Render based on `data.phase`:

| Phase | Rendering |
|-------|-----------|
| `login` | Text: "Logging in to USGS M2M API..." No progress bar. |
| `searching` | Text: "Searching for NAIP scenes..." No progress bar. |
| `downloading` | Progress bar: `geotiffs_downloaded / geotiffs_total`. Detail: "Downloading GeoTIFFs: 50/1022 (batch 2/21) — 14.2 GB". Percentage: `geotiffs_downloaded / geotiffs_total * 100`. Byte display formatted as `(geotiffs_bytes / 1e9).toFixed(1) + ' GB'`. |
| `converting` | Indeterminate progress bar (animated, full width, pulsing opacity). Text: "Converting GeoTIFFs to tiles..." |
| `complete` | Green status badge: "M2M imagery complete — 1,206,388 tiles" |
| `error` | Red status badge with `data.error` message |
| (no phase, stale state) | See stale state handling below |

### Stale State Handling

When the pipeline status shows a terminal state (`completed`, `interrupted`, `cancelled`, `error`) with a `completed_at` timestamp:

- Calculate time ago: "2 hours ago", "yesterday", etc.
- Show appropriate badge:
  - `completed`: Green — "Completed 2h ago — 1.2M tiles"
  - `interrupted`: Yellow — "Interrupted 2h ago"
  - `cancelled`: Yellow — "Cancelled 2h ago"
  - `error`: Red — "Failed 2h ago — {error message}"
- Button text is always **"Start Download"** (never "Resume" — checkpoint-based resume is transparent to the user).

When there is no state file at all (fresh install, or state was cleared):
- Show "No imagery downloaded" with the Start button.

### Dashboard Banner — M2M Aware

The `renderPipelineBanner()` function (already updated to accept all three pipeline types' data) adapts for M2M:

- During `downloading` phase: Title "M2M imagery: 50/1022 GeoTIFFs (batch 2/21)". Progress bar: `geotiffs_downloaded / geotiffs_total * 100` (guard: if `geotiffs_total === 0`, show 0%).
- During `converting` phase: "M2M imagery: Converting to tiles..." with indeterminate progress bar.
- During `login`/`searching`: "M2M imagery: Initializing..." with no progress bar.

### Zoom Selector Interaction with M2M

When source select changes to `m2m`:
- Disable the zoom `<select>` element (add `disabled` attribute)
- Show note below: "M2M mode auto-detects zoom from source imagery (~z17-z19 for NAIP)"
- The zoom value is NOT sent in the pipeline start request for M2M
- **Hide the tile/size/time estimate** (`#cfg-estimate`), or replace its text with: "M2M: download size depends on source imagery coverage"

When source changes back to `direct`:
- Re-enable the zoom selector
- Clear the note
- Re-show the tile/size/time estimate and call `updateEstimate()`

### Concurrency Options (no change)

M2M concurrency options stay as-is: 3 (default), 5 (max). Direct mode: 10, 20 (default), 50, 80.

### Edge Case Guards

- **Division by zero:** When `geotiffs_total` is 0, display 0% progress (guard `geotiffs_total > 0` before division).
- **Missing `completed_at`:** On terminal states without `completed_at`, show status without time-ago (e.g., "Completed" instead of "Completed 2h ago").
- **Partial batch completion:** The `download_geotiffs` callback counts only successfully downloaded files. If 48/50 in a batch succeed and 2 get HTTP errors, `geotiffs_downloaded` shows 48, not 50. The errors are logged but don't stop the batch.
- **Legacy state files:** State files without `mode` or `phase` fields render using the existing direct-mode logic (backward compatible).

### Concurrent Pipeline Prevention (no change)

When any pipeline is running (imagery, elevation, osm_poi — any mode), all Start/Extract buttons are disabled.

---

## 4. Frontend Healthcheck (docker-compose.yml)

Add to the `frontend` service definition:

```yaml
healthcheck:
  test: ["CMD", "curl", "-sf", "http://localhost:8094/config/", "-o", "/dev/null"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 10s
```

This uses the config panel's internal port (8094) which is the NGINX listen address inside the container. The path `/config/` is a static file serve — proves NGINX is running and serving content. `curl` is available in the `nginx:alpine` image.

After this change, the frontend service will report `health=healthy` when NGINX is serving, and the service list dot will be green.

---

## Files Modified

| File | Change |
|------|--------|
| `scripts/acquire_imagery.py` | Phase-aware `update_progress()`, callback in `download_geotiffs()`, phase transitions in `run_m2m()` |
| `services/search/main.py` | `KNOWN_SERVICES` whitelist in `_list_docker_services()`, skip estimated_tiles for M2M, reconciliation fix for completed-but-exited |
| `frontend/config/index.html` | M2M phase rendering, stale state time-ago, zoom disable for M2M, "Start Download" button |
| `docker-compose.yml` | Frontend healthcheck |

## Files NOT Modified

- `nginx/nginx.conf` — no changes needed
- `services/gps/main.py` — no changes needed
- No new files created

---

## Testing Strategy

### Backend Tests (automated)

- `services/search/tests/test_admin_status.py`: Add test verifying pipeline containers are filtered from services list.
- `services/search/tests/test_pipeline_status_m2m.py` (new): Test phase-aware state file rendering — verify `estimated_tiles` not computed for M2M, verify reconciliation detects "MBTiles written" as completed.
- `services/search/tests/test_zoom_validation.py`: Add test for `zoom="n/a"` not triggering tile estimation.

### Script Tests

- Test `update_progress()` with M2M-specific fields — verify state file contains all phase fields.
- Test `download_geotiffs()` callback is invoked with correct counts.

### Frontend (manual)

1. Start an M2M download via admin panel — verify phase transitions render correctly (login → searching → downloading with progress bar → converting → complete).
2. During downloading phase — verify batch counter increments, GeoTIFF count increases, byte count shown.
3. Cancel during download — verify "Cancelled" badge with time-ago.
4. Service list — verify only 7 services shown, no pipeline containers.
5. Frontend dot — verify green (healthy) after healthcheck passes.
6. Select M2M source — verify zoom selector disabled with explanation note.
7. Select direct source — verify zoom selector re-enabled, note cleared.
8. Stale state from previous run — verify "Completed Xh ago" or "Interrupted Xh ago" with "Start Download" button.
9. Dashboard banner during M2M download — verify "M2M imagery: 50/1022 GeoTIFFs (batch 2/21)".
