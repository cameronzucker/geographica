# Bug Hunt Report: STT 405 Method Not Allowed

## Scope

**Investigated bug:** STT feature returns HTTP 405 (Method Not Allowed) when POSTing to `/stt/transcribe`.

**Files analyzed deeply:**
- `nginx/nginx.conf` -- reverse proxy config, specifically the `/stt/` location block (lines 91-99)
- `nginx/entrypoint.sh` -- TLS mode selection and config copying
- `nginx/tls-include.conf` / `nginx/tls-include-empty.conf` -- TLS directives
- `services/stt/main.py` -- FastAPI STT service (POST /transcribe, GET /health)
- `frontend/stt.js` -- browser-side voice capture and _sendToSTT
- `frontend/stt-worklet.js` -- AudioWorklet processor
- `docker-compose.yml` -- service definitions and volume mounts (stt at lines 142-163, frontend at 165-193)
- `services/stt/backends/cpu.py` -- Whisper inference backend
- `services/stt/backends/__init__.py` -- TranscribeResult dataclass
- `services/stt/Dockerfile` -- container build
- `services/stt/tests/test_endpoints.py` -- endpoint tests
- `.env` -- TLS_MODE=tailscale, TLS_CERT_DIR

**Exploration rationale:** Started at the NGINX proxy config (highest risk for a 405 from a reverse proxy), then followed the request path through to the FastAPI backend, then investigated the container runtime state to understand the discrepancy between the source file and loaded config.

## Bugs

### 1. NGINX config missing /stt/ location block due to stale bind mount inode

**Location:** `nginx/nginx.conf:91-99` (source), `docker-compose.yml:189` (bind mount definition)
**Severity:** critical
**Evidence:**

The NGINX config file on the host at `/home/administrator/Code/geographica/nginx/nginx.conf` contains the `/stt/` location block (165 lines, MD5 `475f40f2...`). However, the file inside the running container at `/etc/nginx/conf.d/default.conf` does NOT contain it (155 lines, MD5 `6bceb3c0...`). The 10-line difference exactly matches the `/stt/` location block plus its comment.

Verified via:
```
Host:      165 lines, MD5 475f40f2be445ae208c66a3f9a7e8116
Container: 155 lines, MD5 6bceb3c0536eca494f05a6d706009be6
```

`nginx -T` inside the container confirms the `/stt/` location block is absent -- the config jumps from `/search/` directly to `/admin/status`.

The container was created at `2026-04-08T11:43:26 UTC`. The commit adding the `/stt/` block (`ef505d7`) was at `2026-04-08T16:17:51 UTC` (4.5 hours later). Git commit operations create new file inodes. Docker bind mounts track the inode, not the path. When git wrote the new version of `nginx/nginx.conf`, the container's bind mount continued pointing to the old inode's content.

**Impact:** Without the `/stt/` location block, requests to `/stt/transcribe` fall through to the `location /` block (line 10), which uses `try_files $uri $uri/ /index.html`. For GET requests, `try_files` serves `index.html` (which is why `GET /stt/health` returns 200 with HTML content). For POST requests, NGINX's `try_files` returns **405 Not Allowed** because static file serving does not accept POST. This is the source of the reported 405.

**Fix:** Restart the frontend container: `docker compose restart frontend` (or `docker compose up -d --force-recreate frontend`). This re-establishes the bind mount with the current inode.

### 2. STT container not running

**Location:** `docker-compose.yml:142-163`
**Severity:** critical (operational, not code)
**Evidence:**

`docker ps` shows no `geographica-stt` container. `docker logs geographica-stt` returns "No such container." The STT container was never started in the current session or has been removed.

Since the NGINX config (even the stale version) doesn't have the `/stt/` block, NGINX started fine without needing to resolve the `stt` hostname. But even after fixing Bug #1, the STT container must be running for requests to succeed.

**Impact:** Even with the correct NGINX config loaded, requests to `/stt/transcribe` would return 502 Bad Gateway (connection refused to upstream `stt:8000`).

## Design Concerns

### NGINX startup fails if any upstream service is down

NGINX resolves `proxy_pass` hostnames at configuration load time. If the `stt` container is not running when the frontend container starts, NGINX will fail with `host not found in upstream "stt:8000"` and refuse to start entirely. This takes down the entire frontend, not just the STT feature.

The `docker-compose.yml` has `depends_on: [stt]` for the frontend, which ensures ordering during `docker compose up`. But if the STT container subsequently crashes and the frontend is restarted, NGINX will fail to come back up.

**Mitigation options:**
1. Use a `resolver` directive with a variable in the proxy_pass to make resolution dynamic:
   ```nginx
   location /stt/ {
       resolver 127.0.0.11 valid=30s;
       set $stt_upstream http://stt:8000;
       proxy_pass $stt_upstream;
       ...
   }
   ```
   This defers DNS resolution to request time, so NGINX starts even if the upstream is down. Requests return 502 (not a hard crash) when the service is unavailable.

2. Alternatively, use `proxy_pass` with an explicit upstream block and the `resolve` flag (requires nginx-plus or the `ngx_http_upstream_module`).

### Stale bind mounts after git operations

Any git operation that replaces `nginx/nginx.conf` (checkout, rebase, cherry-pick, merge) will change the file inode and break the bind mount. The container will silently serve a stale config. This is not specific to the STT block -- any future config change is vulnerable to the same issue.

**Mitigation options:**
1. Use a directory bind mount instead of a file bind mount: mount `./nginx/` to `/etc/nginx/geo-conf/` and `include` from there. Directory mounts survive inode changes.
2. Add a healthcheck or startup script that verifies the loaded NGINX config matches expectations.
3. Always run `docker compose restart frontend` after modifying `nginx/nginx.conf`.

### Inconsistent Host header in /stt/ location block

The `/stt/` location block (line 95) uses `proxy_set_header Host $host`, while all other proxy locations use `$http_host`. `$host` omits the port number; `$http_host` preserves it. For the current setup where everything runs on standard ports this is cosmetic, but it's an inconsistency that could cause subtle issues if the deployment ever uses non-standard ports.
