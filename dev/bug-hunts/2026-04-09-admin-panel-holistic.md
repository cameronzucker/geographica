# Bug Hunt Report

## Scope
Analyzed the admin panel redesign implementation across 5 source files:
- `services/gps/main.py` (GPS `/status` endpoint)
- `services/search/main.py` (admin_status, pipeline orchestration, helpers)
- `frontend/config/index.html` (3-tab config panel with MapLibre minimap)
- `nginx/nginx.conf` (config panel server block, tile proxy)
- `docker-compose.yml` (search service volumes, TLS cert mount)

Also reviewed adjacent scripts (`acquire_imagery.py`, `download_elevation.py`, `build_osm_pois.py`) for argument-interface compatibility with pipeline_start command construction.

Approach: read all source files end-to-end, then traced data flows across service boundaries (GPS -> search -> frontend, pipeline state files -> status endpoints -> frontend rendering).

## Bugs

### 1. Docker client used after close in pipeline_status log capture
**Location:** `services/search/main.py:1156-1162`
**Severity:** significant
**Evidence:** At line 1140, `client.close()` is called in a `finally` block. At line 1156, `if client:` evaluates to True (the closed DockerClient object is still truthy), then line 1158 attempts `client.containers.get("geographica-pipeline")` on the closed client. The Docker SDK's `DockerClient.close()` closes the underlying HTTP session, so subsequent API calls raise an error (or produce undefined behavior), which is silently swallowed by the `except Exception: pass` on line 1161.
**Impact:** When a pipeline container crashes, the reconciliation logic at lines 1142-1169 correctly detects the crash and marks the state as "interrupted", but the log capture at lines 1156-1162 will never succeed. The `last_logs` field will never be populated in the state file, making crash diagnosis impossible through the admin panel. The fix is to move the log capture inside the `if client:` block before `client.close()`, or to not close the client until after the reconciliation logic completes.

### 2. Frontend fetchAll race: _lastStatus may be empty when pipeline renderers execute
**Location:** `frontend/config/index.html:979-1002`
**Severity:** minor
**Evidence:** `fetchAll()` fires 5 parallel HTTP requests. The `/admin/status` callback (line 980-986) sets `_lastStatus = d`. The elevation and OSM POI callbacks (lines 994-1001) call `renderElevation(_lastStatus, d)` and `renderOsmPoi(_lastStatus, d)`, which read `_lastStatus.data_tasks` and `_lastStatus.search_stats`. On the very first call after page load, `_lastStatus` is `{}`, and the pipeline status responses can arrive before the admin status response.
**Impact:** On first page load, `renderElevation` and `renderOsmPoi` may receive an empty `_lastStatus`, causing them to show "No elevation data yet" and "No OSM POIs extracted yet" even when data exists. This self-corrects within ~1 second when either the admin status response arrives (if slightly delayed) or on the next 10-second poll cycle. It's a visual flicker on first load, not data loss.

### 3. Pipeline banner only renders imagery progress, ignores elevation/OSM state data shape
**Location:** `frontend/config/index.html:448-475`
**Severity:** minor
**Evidence:** `renderPipelineBanner(imageryData)` is only called with imagery pipeline data (line 990: `renderPipelineBanner(d)` where `d` is from `type=imagery`). For elevation and OSM, the banner only shows a title string ("Elevation download in progress" / "OSM POI extraction in progress") with no progress bar (pct stays 0). The `_elevRunning` and `_osmRunning` flags are set by their respective renderers, but the banner function is only invoked from the imagery callback.
**Impact:** When an elevation or OSM pipeline is running, the dashboard banner will show the correct title but the progress bar will be stuck at 0% and the detail text will be empty. The pipelines tab shows correct progress. This is a UX issue where the banner is less useful for non-imagery pipelines, but it's not misleading since it does indicate *something* is running.

## Design Concerns

### Docker client lifecycle in pipeline_status is fragile
The `pipeline_status` endpoint creates a Docker client, uses it to check container status, closes it in a `finally` block, then later needs it again for log capture. This pattern invites the use-after-close bug found above. A cleaner pattern would be a single `try/finally` that wraps all Docker operations, closing the client only once at the end.

### Synchronous blocking calls in admin_status async endpoint
`admin_status` (line 656) is an async endpoint but calls several synchronous functions that block the event loop: `_get_docker_client()` + container listing/inspection (line 661-697), `_detect_tls_status()` with subprocess calls to openssl (line 709), `_get_search_stats()` with synchronous SQLite (line 710), and `_get_disk_info()` with `shutil.disk_usage` (line 711). On a Pi 5, the Docker API calls in particular can take 1-2 seconds, during which the entire event loop is blocked. This means other endpoints (search queries, health checks) are unresponsive during admin status polls (every 10 seconds from the config panel). These should be wrapped in `asyncio.to_thread()` or run concurrently with the existing `asyncio.gather()` for STT/GPS.

### No CSRF header check on read-only admin endpoints through public NGINX
The public NGINX server block (lines 107-123) proxies `/admin/status`, `/admin/pipeline/status`, and `/admin/credentials/status` directly to the search service without the `X-Config-Source: internal` header. These endpoints don't require `require_config_source` (they're read-only), which is an intentional design decision. However, `/admin/credentials/status` reveals whether M2M credentials are configured, which is a minor information leak on the public port. This is likely acceptable given the mesh-network deployment context.
