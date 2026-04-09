# Bug Hunt Report — Admin Panel Redesign (Multi-Pass)

## Scope
Files analyzed:
- `services/gps/main.py` (256 lines) — GPS service with new `/status` endpoint
- `services/search/main.py` (1222 lines) — Admin status, pipeline orchestration, search
- `frontend/config/index.html` (1020 lines) — 3-tab config panel with MapLibre minimap
- `nginx/nginx.conf` (207 lines) — Config panel server block with tile proxy
- `docker-compose.yml` (218 lines) — Service definitions and volume mounts

All five passes performed: contract violations, cross-sibling patterns, failure modes, concurrency, error propagation.

## Bugs

### 1. Tile size estimate uses wrong unit calculation (20 KB stated, formula computes 20 KiB differently)
**Location:** frontend/config/index.html:333, services/search/main.py:937
**Severity:** minor
**Evidence:** The frontend estimate calculates `count * 20 * 1024 / (1024 * 1024 * 1024)` which equals `count * 20 / (1024 * 1024)` — this treats the 20 as "20 KiB per tile" (20,480 bytes). The backend uses the identical formula `tile_count * 20 * 1024 / (1024 ** 3)`. Both are consistent with each other, but the comment says "~20 KB per tile average" while the formula actually uses 20 KiB (20,480 bytes). This is cosmetic — the estimate is rough — but the frontend shows the size as "GB" while the math is in GiB, so the displayed size will be ~7% lower than the actual GB figure on large downloads.
**Impact:** Users see slightly misleading download size estimates. On a large western US download (~116M tiles), the difference is about 20 GB displayed as ~18.6 GB. Minor for a rough estimate.
**Found in:** Pass 1 — Contract Violations

### 2. `_parse_zoom` breaks on negative zoom strings like "-1-14"
**Location:** services/search/main.py:114-121
**Severity:** minor
**Evidence:** `_parse_zoom` splits on `-` and requires exactly 2 parts. An input like `"-1-14"` produces `[''', '1', '14']` — 3 parts, so it raises ValueError ("zoom must be in format 'min-max'"). However, the subsequent validation `zoom_min < 0` would have caught this anyway. The real concern: `_parse_zoom("12")` — a single zoom level with no dash — raises a confusing "must be in format 'min-max'" error. The frontend always sends dashed format, so this is minor.
**Impact:** Malformed zoom strings from API callers get a confusing but non-dangerous error. Frontend is unaffected since it sends select options in "min-max" format.
**Found in:** Pass 1 — Contract Violations

### 3. `pipeline_status` uses Docker client after `finally: client.close()` when reconciling interrupted state
**Location:** services/search/main.py:1132-1162
**Severity:** significant
**Evidence:** At line 1132, `client` is obtained. At lines 1138-1140, the `try/except/finally` block closes the client. Then at line 1156, the code checks `if client:` and attempts to use the closed client to fetch container logs (`client.containers.get("geographica-pipeline")`). The Docker SDK client is already closed at this point. This will either silently fail (caught by the `except Exception: pass`) or produce an error that gets swallowed.
**Impact:** When a pipeline container dies while running, the reconciliation path correctly marks it as "interrupted" but always fails to capture the last logs from the dead container. The `last_logs` field will never be populated, making crash diagnosis harder. The state file is still updated correctly otherwise.
**Found in:** Pass 3 — Failure Mode Reasoning

### 4. Race condition: `_lastStatus` may be stale when pipeline renderers consume it
**Location:** frontend/config/index.html:977-1002
**Severity:** minor
**Evidence:** In `fetchAll()`, four independent fetch calls fire concurrently. The elevation and OSM pipeline renders at lines 994-1001 use `_lastStatus` which is set by the `/admin/status` fetch at line 981. Because these are independent promises, the pipeline status responses may resolve before the admin status response, causing `renderElevation(_lastStatus, d)` and `renderOsmPoi(_lastStatus, d)` to use data from the *previous* polling cycle. On the first call ever, `_lastStatus` is `{}`, so `statusData.data_tasks` and `statusData.search_stats` will be undefined, but the code guards against this with `if (statusData && statusData.data_tasks)`.
**Impact:** During the first 10s after page load, elevation/OSM sections may briefly show stale or empty data. Self-corrects on next poll. Minor UX glitch.
**Found in:** Pass 4 — Concurrency Reasoning

### 5. GPS `_position` dict replaced non-atomically — readers can see partial state
**Location:** services/gps/main.py:127-137
**Severity:** minor
**Evidence:** In `_blocking_read_gpsd` (running in a thread via `asyncio.to_thread`), the global `_position` dict is reassigned as a whole dict literal at line 127. In CPython, dict assignment is atomic due to the GIL, so the reference swap is safe. However, in `_gps_reader` at line 157-162, `_position` is updated via `{**_position, "stale": True, ...}` — this reads `_position` from one thread context and writes it from the async context. Due to the GIL, this is safe in CPython, but the pattern is fragile.
**Impact:** No actual bug in CPython due to GIL. Would be a bug under any non-GIL Python implementation. Flagging as minor design concern.
**Found in:** Pass 4 — Concurrency Reasoning

### 6. `admin_status` runs synchronous Docker API calls, `subprocess.run`, and SQLite queries on the async event loop
**Location:** services/search/main.py:656-810
**Severity:** significant
**Evidence:** The `admin_status` endpoint is an `async def` handler. It calls `_get_docker_client()` and then `client.containers.list()`, `c.attrs`, `c.logs()` — all synchronous Docker SDK calls that perform HTTP requests to the Docker socket. It also calls `_detect_tls_status()` which runs `subprocess.run` twice (openssl commands), `_get_search_stats()` which opens a synchronous SQLite connection and runs COUNT queries, and `_get_disk_info()` which calls `shutil.disk_usage`. None of these are awaited or run in a thread executor. This blocks the entire async event loop during the call.
**Impact:** While `admin_status` is processing (Docker API calls can take 1-5s), the search service cannot handle any other requests — no search queries, no health checks, no other admin calls. The STT/GPS fetches are properly async (lines 700-701), but the Docker + TLS + stats section blocks. On a Pi 5 with only one event loop, this stalls the entire service. With 10s polling from the config panel, this means the search service is blocked for potentially 1-5s every 10s.
**Found in:** Pass 5 — Error Propagation (identified as blocking path)

### 7. `pipeline_cancel` writes state files without `indent=2` (inconsistent with `pipeline_start`)
**Location:** services/search/main.py:1204
**Severity:** minor
**Evidence:** `pipeline_start` writes state with `json.dumps(state_data, indent=2)` at line 1105, but `pipeline_cancel` writes with `json.dumps(existing)` (no indent) at line 1204. While this doesn't affect correctness, any code parsing the state file by line (log inspection, etc.) will see different formatting depending on which operation wrote last.
**Impact:** Minor inconsistency. No functional impact.
**Found in:** Pass 2 — Cross-Sibling Pattern Violations

### 8. Valhalla port conflict with config panel
**Location:** docker-compose.yml:26, docker-compose.yml:180
**Severity:** significant
**Evidence:** Valhalla is mapped to host port 8094 (`"8094:8002"` at line 26). The config panel NGINX server block listens on port 8094 inside the frontend container (nginx.conf line 148), and the frontend container maps it as `"127.0.0.1:8097:8094"` (docker-compose.yml line 180). These are different containers so they don't conflict directly — Valhalla binds 8094 on the host network interface, and the config panel binds 8094 inside the frontend container mapped to host 8097. However, this means external access to port 8094 goes to Valhalla, not the config panel. The NGINX config panel `allow` directives (172.18.0.1, 127.0.0.0/8) provide no security since they're inside the container — the real access restriction is the `127.0.0.1:8097:8094` Docker port binding. This is working as designed but confusing.
**Impact:** No functional bug — the port mapping is correct. The matching port number (8094) between Valhalla's host port and the config panel's internal port is coincidental and confusing for operators. Not a real bug, demoting.
**Found in:** Pass 2 — Cross-Sibling Pattern Violations

## Design Concerns

### Blocking async event loop in admin_status (Bug #6)
The most impactful finding. The search service is the only service handling POI/Nominatim/spatial queries, and its event loop is blocked every 10 seconds by the admin status poll. This creates periodic 1-5 second latency spikes for all search queries. The fix is straightforward: wrap the synchronous calls in `asyncio.to_thread()` or use an async Docker client.

### Docker client used after close (Bug #3)
The try/except/finally pattern in `pipeline_status` closes the Docker client before the reconciliation code tries to use it for log capture. This means crash logs from failed pipelines are silently lost. The fix is to move the `client.close()` after the reconciliation block.

### Single pipeline container name creates false negative on concurrent type checks
`_is_pipeline_container_running` checks for `geographica-pipeline` — a single container name. The `pipeline_start` lock and container check correctly prevent concurrent pipelines. But `pipeline_status` checks the same single container name regardless of type, meaning if imagery is running and you poll elevation status, the reconciliation logic won't mark elevation as interrupted (it sees a running container and assumes it's for the polled type). This is mitigated by the state file type check in `admin_status` imagery logic (line 763: `if ps.get("type") == "imagery"`), but the `pipeline_status` endpoint doesn't verify the container's type matches the requested type.

### No CSRF token on admin write endpoints
The `require_config_source` dependency checks for `X-Config-Source: internal` (added by NGINX) and `X-Geographica` header. The frontend's `cfgFetch` always adds `X-Geographica`. This provides defense-in-depth against cross-origin attacks. The `X-Geographica` header forces a CORS preflight, which browsers will block cross-origin. This is adequate for the localhost-only config panel.
