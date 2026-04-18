# Pipeline Completion & Finalization Bug Hunt

**Date:** 2026-04-17
**Scope:** What happens AFTER all tiles are merged — post-processing, cleanup, and handoff to TileServer
**Trigger:** Production run completed 496/496 tiles but imagery was invisible to users

---

## Bug 1: TileServer Never Restarted After Pipeline Completion (CRITICAL)

**Files:** `services/search/main.py` (line 1406-1414), `scripts/acquire_imagery.py` (line 2266-2285)

**What:** The pipeline updates `tileserver/config.json` via `add_mbtiles_to_config()` in Phase 6 (line 2273), but TileServer GL v5.5.0 only reads config.json at startup. Nobody restarts the TileServer container after config changes. The search service (which orchestrates pipeline containers) has no `_restart_tileserver()` helper — the plan at `docs/superpowers/plans/2026-04-14-noaa-naip-byo-imagery.md:1486` specified one but it was never implemented.

**Impact:** After a multi-hour NOAA download completes successfully, the user sees nothing. The frontend's `_tryAddTileJSONSource('imagery-noaa', ...)` gets 404 forever because TileServer doesn't know about the new source. Manual `docker compose restart tileserver` is required.

**Fix:** The search service's `pipeline_status` endpoint (line 1447) already detects when a pipeline container has exited and reconciles state. Add TileServer restart logic there: when status transitions from "running" to "completed", restart the TileServer container via the Docker socket (already mounted at `/var/run/docker.sock`). Alternatively, add a dedicated `/admin/pipeline/finalize` endpoint or have the status reconciliation do it automatically.

---

## Bug 2: TILESERVER_CONFIG Not Passed to Pipeline Container (CRITICAL)

**Files:** `services/search/main.py` (line 1334-1338), `scripts/acquire_imagery.py` (line 1775, 2267)

**What:** The pipeline container's environment is built at line 1334-1338 with only `GDAL_CACHEMAX` and `PYTHONUNBUFFERED`. The `TILESERVER_CONFIG` env var is never set. The `tileserver/config.json` file is never mounted into the pipeline container (volumes at line 1390-1396 only include `/data` and `/scripts`).

This means `os.environ.get("TILESERVER_CONFIG")` returns `None` in both:
- The unregister at startup (line 1775) — entire block is skipped
- The re-register at completion (line 2267) — entire Phase 6 is skipped

**Impact:** Even Bug 1 aside, the config.json is never actually updated by the pipeline when launched from the admin panel. The unregister/re-register flow is completely dead code when run via Docker. It only works when `acquire_imagery.py` is run directly on the host with `TILESERVER_CONFIG` set manually.

**Fix:** Mount `./tileserver/config.json` into the pipeline container at a known path (e.g., `/tileserver/config.json` writable, not `:ro`) and add `TILESERVER_CONFIG: /tileserver/config.json` to the pipeline container's environment. OR: move the config update responsibility to the search service (which already has the config mounted, though currently `:ro`).

---

## Bug 3: Search Service Config Mount Is Read-Only (MODERATE)

**File:** `docker-compose.yml` (line 130)

**What:** The search service mounts tileserver config.json as read-only:
```yaml
- ./tileserver/config.json:/tileserver/config.json:ro
```

The delete imagery endpoint (line 876-898) calls `remove_mbtiles_from_config()` which tries to write a `.tmp` file and `os.replace()` it. This will fail on the read-only mount. The error is silently swallowed by `except Exception: pass` at line 895.

**Impact:** Deleting imagery sources via the admin panel appears to succeed (file is deleted at line 888) but TileServer config is not updated — TileServer will crash-loop trying to serve a deleted MBTiles file.

**Fix:** Change the mount to `:rw` or move config management to a volume that's writable by the search service.

---

## Bug 4: WAL Checkpoint Runs AFTER TileServer Re-registration (MODERATE)

**File:** `scripts/acquire_imagery.py` (line 2266-2305)

**What:** The code sequence is:
1. Phase 6 (line 2266): Re-register `imagery_noaa` in TileServer config
2. Final WAL checkpoint (line 2287): TRUNCATE + switch to DELETE journal mode

The comment at line 2292 says: *"no other process has the file open (TileServer source was unregistered)"* — but Phase 6 just re-registered it. If TileServer were actually restarted (Bug 1 being fixed), it would open the database and hold a read lock, causing `PRAGMA wal_checkpoint(TRUNCATE)` to fail with "database is locked" — exactly the error the user observed.

**Impact:** With Bug 1 fixed, the WAL checkpoint will fail reliably. The WAL file stays large (potentially GB), and `journal_mode=DELETE` never gets set. TileServer may serve stale or incomplete tiles from the WAL.

**Fix:** Move the WAL checkpoint and journal mode switch BEFORE Phase 6 (re-registration). The correct order is: (1) checkpoint + journal mode, (2) update config, (3) restart TileServer.

---

## Bug 5: Pipeline Crash Leaves Source Permanently Unregistered (MODERATE)

**File:** `scripts/acquire_imagery.py` (line 1773-1786, 2266-2285)

**What:** At startup, `run_noaa()` unregisters `imagery_noaa` from TileServer config (line 1781). Re-registration only happens in Phase 6 (line 2273) after successful completion. If the pipeline crashes, is OOM-killed, or is cancelled at any point between, the source stays unregistered.

**Impact:** Users lose existing imagery permanently until manual intervention (`python3 scripts/tileserver_config.py add tileserver/config.json imagery_noaa /srv/data/imagery_noaa.mbtiles && docker compose restart tileserver`). This is especially bad because the pipeline runs in a container with a 2GB/4GB memory limit and OOM kills are realistic during gdaladdo/inpaint phases.

**Fix:** Options:
- Don't unregister at startup. Instead, use advisory locking or PRAGMA busy_timeout to coexist with TileServer's read-only access.
- Add a finally/atexit handler that re-registers on crash.
- Have the search service's status reconciliation re-register when it detects "interrupted" status and the MBTiles file still exists.

---

## Bug 6: Status Reconciliation Missing Completion Strings (MINOR)

**File:** `services/search/main.py` (line 1496-1500)

**What:** The status reconciliation checks container logs for success strings to distinguish completion from crash:
```python
elif any(s in (state_data.get("last_logs") or "") for s in (
    "MBTiles written to",
    "NOAA pipeline complete",
    "Import complete",
)):
```

This is fragile and incomplete. Missing patterns include:
- `"M2M pipeline complete"` — M2M mode logs this at line 1649
- `"Sentinel"` / acquire_sentinel completion messages
- `"Completed:"` — NAIP pipeline (acquire_naip.py)
- The state file itself already has `status: "completed"` written by the pipeline script before exit — but the reconciliation code only runs when `state_data.get("status") in ("running", "cancelling")`, meaning it only fires when the pipeline script did NOT update the state file before exiting.

**Impact:** If a pipeline completes successfully but exits before the state file is written (e.g., SIGTERM during the brief window between `update_progress(status="completed")` and process exit), the reconciliation may incorrectly mark it as "interrupted" for M2M, Sentinel, or NAIP modes.

**Fix:** Add the missing completion strings. Better: also check if the output MBTiles file exists and has a reasonable size as a completion heuristic.

---

## Bug 7: No "needs_restart" State for Admin Panel (MINOR)

**Files:** `services/search/main.py` (line 1447-1531), admin panel frontend

**What:** The pipeline status endpoint returns `status: "completed"` but has no concept of "TileServer needs restart" or "tiles ready but not yet visible." The admin panel has no UI to indicate this or offer a restart button.

**Impact:** After pipeline completion, the admin panel shows "completed" but the user must know to manually restart TileServer. There's no indication that this step is required, and no button to do it.

**Fix:** When the status transitions to "completed" for imagery/sentinel/naip/import types, add a `needs_tileserver_restart: true` field. The admin panel can show a "Restart TileServer" button or do it automatically.

---

## Bug 8: Other Pipeline Modes Have Same or Worse Gaps

### acquire_sentinel.py — No TileServer config management at all
- No `TILESERVER_CONFIG` handling
- No config.json registration
- No WAL checkpoint
- No unregister/re-register
- Completion status is written, but TileServer knows nothing about new data

### acquire_naip.py — No TileServer config management at all
- Same gaps as Sentinel

### download_elevation.py — No TileServer config management
- Uses WAL during download but doesn't checkpoint or switch journal mode at end
- No config.json registration (elevation tiles may be handled separately by TileServer)

### import_imagery.py — Partial support, dead code path
- Has `--tileserver-config` CLI arg and calls `add_mbtiles_to_config` (line 189-195)
- But the search service's import endpoint (line 1747) never passes `--tileserver-config` in the command
- No WAL checkpoint after import
- Result: config.json update is dead code when launched from admin panel

### run_direct / run_m2m (acquire_imagery.py)
- `run_direct` (line 941): No TileServer config handling, no WAL checkpoint at end
- `run_m2m` (line 1477): No TileServer config handling, no WAL checkpoint at end
- Only `run_noaa` has these features, and they're broken (Bugs 2, 4, 5)

---

## Bug 9: Stale Pipeline Container Not Cleaned Up (MINOR)

**File:** `services/search/main.py` (line 1398-1403, 1406-1416)

**What:** The container is started with `remove=False` (line 1411) to allow log capture after exit. A stale container is cleaned up when a NEW pipeline starts (line 1398-1403), but if no new pipeline is started, the dead container persists indefinitely, consuming Docker resources.

**Impact:** Minor resource leak. Dead containers accumulate if pipelines are run repeatedly without starting new ones. The status endpoint reads logs from dead containers (good), but never cleans them up.

**Fix:** Clean up the dead container after log capture in the status reconciliation path, or add a TTL-based cleanup.

---

## Recommended Fix Order

1. **Bug 2** (TILESERVER_CONFIG not passed) — Without this fix, Phase 6 is entirely dead code. Must fix first.
2. **Bug 4** (WAL checkpoint ordering) — Must reorder before fixing Bug 1, or the restart will cause checkpoint failures.
3. **Bug 1** (TileServer restart) — The primary user-facing issue. Implement `_restart_tileserver()` in the search service.
4. **Bug 3** (read-only config mount) — Blocks the search service from managing TileServer config.
5. **Bug 5** (crash leaves source unregistered) — Safety net for OOM/crash scenarios.
6. **Bug 8** (other modes) — Extend config management to all pipeline modes.
7. **Bug 6** (reconciliation strings) — Hardening.
8. **Bug 7** (needs_restart state) — UX improvement.
9. **Bug 9** (container cleanup) — Minor resource hygiene.

---

## Architecture Recommendation

Rather than fixing each pipeline script independently, centralize TileServer management in the search service:

1. **Search service owns TileServer config**: Change mount from `:ro` to `:rw`. The search service already has `tileserver_config.py` on its scripts mount.
2. **Post-completion hook in status reconciliation**: When `pipeline_status` detects completion, the search service:
   - Runs WAL checkpoint on the output MBTiles (no concurrent readers since it controls the lifecycle)
   - Adds the source to TileServer config.json
   - Restarts the TileServer container via Docker socket
3. **Remove TileServer management from pipeline scripts**: The pipeline container should only write tiles. Config management is an orchestration concern.

This eliminates Bugs 1-5, 7, and 8 in one architectural change, and avoids the env var / mount / ordering issues entirely.
