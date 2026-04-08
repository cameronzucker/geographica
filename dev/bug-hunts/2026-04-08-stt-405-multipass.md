# Bug Hunt Report: STT 405 (Method Not Allowed) over HTTPS

## Scope

**Files analyzed:**
- `nginx/nginx.conf` (lines 1-165) -- reverse proxy config
- `nginx/entrypoint.sh` (lines 1-60) -- TLS mode selection
- `nginx/tls-include.conf` (7 lines) -- TLS listener directives
- `nginx/tls-include-empty.conf` (1 line) -- HTTP-only stub
- `services/stt/main.py` (lines 1-304) -- FastAPI STT service
- `services/stt/backends/cpu.py` (lines 1-79) -- Whisper inference backend
- `services/stt/backends/__init__.py` (lines 1-16) -- TranscribeResult dataclass
- `frontend/stt.js` (lines 1-557) -- browser voice capture + API call
- `frontend/stt-worklet.js` (lines 1-52) -- AudioWorklet processor
- `frontend/app.js` (lines 2760-2773) -- initSTT call site
- `docker-compose.yml` (lines 1-217) -- service definitions

**Passes performed:** All 5 (contract violations, cross-sibling patterns, failure modes, concurrency, error propagation)

**Live investigation:** Compared on-disk config to running container config; reproduced 405 via curl on both HTTP and HTTPS.

## Bugs

### 1. NGINX container running stale config -- /stt/ location block missing entirely

**Location:** `nginx/nginx.conf:91-99` (exists on disk) vs container `/etc/nginx/conf.d/default.conf` (missing)
**Severity:** critical
**Evidence:**

The on-disk `nginx/nginx.conf` (165 lines) contains the `/stt/` location block:

```nginx
# Speech-to-text (Whisper)
location /stt/ {
    proxy_pass http://stt:8000/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    client_max_body_size 2m;
    proxy_read_timeout 30s;
}
```

The container's `/etc/nginx/conf.d/default.conf` (155 lines) does NOT contain this block. The 10-line difference exactly matches the missing `/stt/` block. Confirmed by:
- `docker exec geographica-frontend nginx -T` output lists all location blocks but no `/stt/`
- `docker exec geographica-frontend cat /etc/nginx/conf.d/default.conf | grep stt` returns nothing

Without the `/stt/` location, POST requests to `/stt/transcribe` fall through to `location / { try_files $uri $uri/ /index.html; }`. NGINX's static file handler only supports GET and HEAD methods, so it returns **405 Not Allowed** for POST requests.

**Root cause:** The frontend container was not recreated after the `/stt/` block was added to `nginx/nginx.conf`. Docker bind mounts can become stale when the host file is replaced via atomic rename (write-to-temp + rename, which most editors do). The bind mount continues pointing to the old inode. `docker compose up -d` only recreates containers when the compose definition changes, not when bind-mounted file contents change. A `docker compose up -d --force-recreate frontend` or `docker compose restart frontend` followed by `docker exec geographica-frontend nginx -s reload` is needed.

**Impact:** ALL STT requests fail with 405 -- on both HTTP and HTTPS, not just HTTPS as originally reported. The user likely tested HTTP from a local browser that had cached a working response, or HTTP was never tested after the container went stale.

**Fix:** `docker compose up -d --force-recreate frontend` (or `docker compose down && docker compose up -d`)

**Found in:** Pass 1 -- Contract Violations (nginx.conf promises to proxy /stt/ but the running config doesn't)

---

### 2. STT container not running

**Location:** `docker-compose.yml:142-163`
**Severity:** critical
**Evidence:**

`docker compose ps stt` returns an empty table -- the STT container is not running. Even after fixing Bug #1 (stale NGINX config), requests to `/stt/transcribe` would get 502 (Bad Gateway) instead of reaching the FastAPI service.

The STT service is defined with `restart: unless-stopped` and a healthcheck, but it appears to have been stopped or never started. The frontend service's `depends_on` only lists `stt` without a `condition: service_healthy` constraint, so the frontend can start even if STT fails to come up.

**Impact:** Even with the correct NGINX config, STT would fail with 502 until the container is started.

**Found in:** Pass 3 -- Failure Mode Reasoning (tracing what happens when the upstream is unreachable)

---

### 3. /stt/ location uses `$host` instead of `$http_host` -- inconsistent with all sibling proxy blocks

**Location:** `nginx/nginx.conf:95`
**Severity:** minor
**Evidence:**

Every other proxy location block uses `proxy_set_header Host $http_host`:
- `/tiles/` (line 66): `proxy_set_header Host $http_host`
- `/nominatim/` (line 73): `proxy_set_header Host $http_host`
- `/valhalla/` (line 80): `proxy_set_header Host $http_host`
- `/search/` (line 87): `proxy_set_header Host $http_host`
- `/gps/` (line 123): `proxy_set_header Host $http_host`
- `/admin/*` (lines 103, 109, 115): `proxy_set_header Host $http_host`

The `/stt/` block uses `proxy_set_header Host $host` (line 95).

`$host` strips the port number (returns just the hostname). `$http_host` preserves the port (returns `hostname:port`). On non-standard ports (like development port 8093), this means the STT backend would receive a Host header without the port, which could cause issues if the backend generates URLs or redirects based on the Host header. FastAPI's /transcribe endpoint doesn't currently do this, so the practical impact is nil, but it's a deviation from the established pattern that could cause subtle bugs if the backend behavior changes.

**Found in:** Pass 2 -- Cross-Sibling Pattern Violations

---

### 4. Frontend `_sendToSTT` does not handle 405 status code

**Location:** `frontend/stt.js:417-435`
**Severity:** significant
**Evidence:**

The `_sendToSTT` function handles specific HTTP status codes: 413, 422, 502, 503, 504. It does NOT handle 405. The 405 falls through to the generic `if (!resp.ok)` check at line 433, which produces the message `"STT request failed (405)"`. This is technically correct but unhelpful -- the user sees a generic error when the real problem is a misconfigured reverse proxy.

More importantly, a 405 from NGINX returns `text/html` content, not JSON. The `resp.json()` call after the `ok` check is unreachable for 405 (caught by `!resp.ok`), so there's no crash. But the generic error message provides no diagnostic value.

A more useful approach would be to detect 405 specifically and show something like "Voice search endpoint not configured" since 405 on this endpoint is always an NGINX routing problem, never a legitimate FastAPI response (FastAPI would return 405 only for wrong-method-on-valid-path, which can't happen since the only POST endpoint is the one being called).

**Found in:** Pass 5 -- Error Propagation

---

### 5. `frontend/stt.js` depends_on `stt` in docker-compose.yml lacks `condition: service_healthy`

**Location:** `docker-compose.yml:169-175`
**Severity:** minor
**Evidence:**

The `frontend` service's `depends_on` lists `stt` without a health condition:

```yaml
depends_on:
  - tileserver
  - nominatim
  - valhalla
  - gps
  - search
  - stt
```

Compare with the `search` service which properly waits:

```yaml
depends_on:
  nominatim:
    condition: service_healthy
```

Without `condition: service_healthy`, the frontend NGINX container starts as soon as the STT container is *created* (not healthy). If NGINX resolves the `stt` hostname at startup and the STT container hasn't fully started its FastAPI server yet, the DNS resolution succeeds (container exists on the network) but early requests would get connection refused (502).

This is a race condition during `docker compose up`. The STT service has a `start_period: 30s` on its healthcheck, meaning it takes up to 30 seconds before it's considered healthy. During that window, NGINX is live and accepting requests but the STT backend isn't ready.

However, NGINX resolves hostnames at config load time and caches the IP, so if the container is on the network, the hostname resolves. The real issue is that NGINX doesn't have a retry/fallback -- if the backend is down, NGINX immediately returns 502. This is standard NGINX behavior but worth noting as a startup race.

**Found in:** Pass 3 -- Failure Mode Reasoning

## Design Concerns

### Bind mount fragility for NGINX config

The root cause of the 405 (Bug #1) is a well-known Docker bind mount pitfall. When a file is replaced via atomic rename (which git checkout, most text editors, and sed -i all do), the container's bind mount continues pointing to the old inode. This is inherent to how Linux bind mounts work -- they bind to the inode, not the path.

**Mitigation options:**
1. Always run `docker compose up -d --force-recreate frontend` after editing nginx.conf (operational discipline)
2. Use a Docker volume with a copy step instead of a bind mount (adds build complexity)
3. Add NGINX config hash to a label or env var in docker-compose.yml so Docker detects changes (fragile)
4. Use `docker compose watch` (if available) to auto-recreate on file changes

### No NGINX upstream health awareness

NGINX (open source) resolves upstream hostnames once at config load time and caches the result. If the upstream container is recreated with a new IP, NGINX continues sending to the old IP, resulting in 502. NGINX Plus has upstream health checks and DNS re-resolution, but the open-source version does not. The `resolver` directive with a short `valid` TTL can help but requires Docker's internal DNS (127.0.0.11) and `set $upstream` variable-based proxy_pass, which is a significant config change.

### STT `client_max_body_size` mismatch with application limit

The NGINX `/stt/` block sets `client_max_body_size 2m` (2 MB) but the FastAPI service sets `MAX_FILE_SIZE = 1 * 1024 * 1024` (1 MB). The NGINX limit is 2x the application limit, so NGINX will pass through files up to 2 MB, but FastAPI will reject anything over 1 MB with a 413. This isn't a bug (double validation is fine), but the NGINX limit could be tightened to 1m to reject oversized uploads earlier and save bandwidth to the backend.
