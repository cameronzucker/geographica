# Bug Hunt Report

## Scope
Deep-first analysis of the admin panel redesign (5-task implementation). Started with the highest-risk code: the `pipeline_status` endpoint in `services/search/main.py` (cross-service coordination, state reconciliation, error paths), followed by the GPS `/status` endpoint, frontend polling logic, and NGINX proxy configuration.

**Files explored deeply:**
- `services/search/main.py` (full read: lines 1-1222) -- admin_status, pipeline_start, pipeline_status, pipeline_cancel, helper functions
- `services/gps/main.py` (full read: lines 1-256) -- /status endpoint, shared state
- `frontend/config/index.html` (full read: lines 1-1020) -- all rendering, polling, event handlers
- `nginx/nginx.conf` (full read: lines 1-207) -- config panel server block
- `docker-compose.yml` (full read) -- volume mounts, port mappings

**Files read for context:**
- All 4 test files (`test_status.py`, `test_admin_status.py`, `test_pipeline_osm.py`, `test_zoom_validation.py`)

## Bugs

### 1. pipeline_status crashes with 500 error for osm_poi pipelines (AttributeError escapes exception handler)
**Location:** `services/search/main.py:1175-1181`
**Severity:** significant

**Evidence:** When an `osm_poi` pipeline is started, the state file is written with `"bbox": null` and `"zoom": null` (line 1098-1101 of `pipeline_start`). When `pipeline_status` is later called for this pipeline type, the code at line 1175 checks `if "bbox" in state_data and "zoom" in state_data` -- both keys exist (they're just null), so the condition is True. It then calls `_parse_bbox(state_data["bbox"])` which is `_parse_bbox(None)`. Inside `_parse_bbox` (line 107), `None.split(",")` raises `AttributeError`. The except clause at line 1180 only catches `(ValueError, TypeError)`, not `AttributeError`.

The same applies to `_parse_zoom(None)` which would also raise `AttributeError`.

**Impact:** Any GET request to `/admin/pipeline/status?type=osm_poi` returns a 500 Internal Server Error whenever an osm_poi pipeline has been started (state file exists with null bbox/zoom). The frontend polls this endpoint every 10 seconds, so the OSM POI progress section in the config panel is broken as soon as an extraction is started or has completed. The error would repeat indefinitely since the state file persists.

### 2. Docker client used after close in pipeline_status -- crash logs never captured
**Location:** `services/search/main.py:1140,1156-1162`
**Severity:** significant

**Evidence:** At line 1140, `client.close()` is called in a `finally` block. At line 1156, the code checks `if client:` (the closed object is still truthy -- it's not None) and then attempts `client.containers.get("geographica-pipeline")` on the closed client. The Docker SDK may raise an exception on the closed connection, which is silently swallowed by the broad `except Exception: pass` at line 1161.

**Impact:** When a pipeline container crashes (exits unexpectedly), the reconciliation code correctly marks the state as "interrupted" and adds `completed_at`/`duration_seconds`, but the `last_logs` field is never populated. This means crash diagnosis information is silently lost. Operators investigating a failed pipeline job would see the interrupted status but no logs to explain why it failed, making troubleshooting significantly harder on an offline system where logs may not be persisted elsewhere.

### 3. Frontend fetchAll race condition causes stale data on first render
**Location:** `frontend/config/index.html:977-1002`
**Severity:** minor

**Evidence:** `fetchAll()` fires 5 parallel HTTP requests (lines 980-1006). `_lastStatus` is initialized to `{}` (line 977). The elevation and OSM POI render functions (`renderElevation`, `renderOsmPoi`) receive `_lastStatus` as their first argument. These are called from separate `.then()` callbacks that depend on the `/admin/pipeline/status` responses. If these pipeline status responses resolve before the `/admin/status` response, they render with `_lastStatus = {}`.

In `renderElevation` (line 535-536): `statusData.data_tasks` is undefined when `_lastStatus` is `{}`, so `elevTask` stays null, and the UI shows "No elevation data yet" even if elevation data exists.

**Impact:** On initial page load (and potentially during any poll cycle if timing varies), the elevation and OSM POI sections briefly show incorrect status information. Self-corrects on the next poll cycle (10 seconds later). Minor visual flicker, no data corruption.

## Design Concerns

### Hardcoded paths in pipeline_cancel diverge from DATA_DIR
`pipeline_cancel()` (line 1193-1196) uses hardcoded `Path("/data/.pipeline-state.json")` etc., while `_state_file_for_type()` (line 865-871) constructs paths from `DATA_DIR`. In production these are identical (`DATA_DIR = Path("/data")`), but this inconsistency means the cancel function cannot be properly tested with `tmp_path` overrides and would break if `DATA_DIR` were ever changed.

### No bbox/latitude validation in estimate_tile_count
`estimate_tile_count()` (line 87-102) uses `math.tan(math.radians(lat))` and `1/math.cos(math.radians(lat))` without clamping latitude. Values at or near +/-90 degrees would cause division by zero or math domain errors. The Western US bbox prevents this in practice, but there's no guard against user-drawn bboxes that extend to extreme latitudes via the minimap drawing feature.

### Broad exception silencing throughout pipeline orchestration
Multiple code paths in `pipeline_start`, `pipeline_status`, and `pipeline_cancel` use `except Exception: pass` patterns that silently discard all errors. This makes debugging difficult when things go wrong. For example, if Docker socket permissions change, the admin status endpoint silently returns empty service lists rather than reporting the error.
