# STT 405 Bug Hunt — Consolidated Findings

**Date:** 2026-04-08
**Scope:** STT (speech-to-text) request path — phone browser over HTTPS → NGINX → FastAPI STT service. Reported symptom: HTTP 405 Method Not Allowed on POST /stt/transcribe.
**Hunters:** Exploratory, Holistic, Multipass

---

## Confirmed Bugs

### B1. Stale bind mount — NGINX container missing /stt/ location block

**Consensus:** All three hunters found this independently
**Location:** `nginx/nginx.conf:91-99` (on disk), `docker-compose.yml:189` (bind mount)
**Evidence:** On-disk nginx.conf has 165 lines including the `/stt/` proxy block. The running container's `/etc/nginx/conf.d/default.conf` has only 155 lines with zero occurrences of "stt". Verified via `docker exec geographica-frontend grep -c stt /etc/nginx/conf.d/default.conf` → 0. The container was created at 11:43 UTC; the commit adding the /stt/ block was at 16:17 UTC. Git replaced the file (new inode), but Docker's file bind mount tracks the original inode.
**Impact:** ALL requests to `/stt/*` fall through to `location / { try_files $uri $uri/ /index.html; }`. NGINX's static file handler rejects POST with 405. GET requests silently serve index.html (200 with HTML, not JSON). This affects both HTTP and HTTPS — the user only observed it on HTTPS because the phone connects exclusively via Tailscale.
**Blast radius:** Only the STT feature is affected. Fix is isolated to container restart.
**Fix approach:** `docker compose up -d --force-recreate frontend` to re-establish bind mount with current inode.

### B2. STT container not built or running

**Consensus:** All three hunters found this
**Location:** `docker-compose.yml:142-163`
**Evidence:** `docker compose ps stt` returns empty. `docker images | grep stt` returns nothing. The STT service was implemented in this session but never deployed — the handoff explicitly says "needs `docker compose build stt` to deploy."
**Impact:** Even after fixing B1, requests to /stt/transcribe would return 502 (Bad Gateway) because the upstream is unreachable. Additionally, NGINX may fail to start entirely if it can't resolve the `stt` hostname at config load time.
**Blast radius:** Only STT feature. No code changes needed — purely operational.
**Fix approach:** `docker compose build stt && docker compose up -d stt`

### B3. Inconsistent `$host` vs `$http_host` in /stt/ location block

**Consensus:** All three hunters identified this
**Location:** `nginx/nginx.conf:95`
**Evidence:** The /stt/ block uses `proxy_set_header Host $host` while every other proxy block uses `$http_host`. `$host` strips the port; `$http_host` preserves it. All 8 other proxy locations consistently use `$http_host`.
**Impact:** Currently cosmetic — on standard ports (80/443) they're equivalent, and the FastAPI backend doesn't use the Host header for routing. However, it deviates from the established pattern and could cause subtle issues on non-standard ports.
**Blast radius:** Single line change in nginx.conf.
**Fix approach:** Change `$host` to `$http_host` on line 95.

### B4. Frontend error handler does not handle 405 status

**Consensus:** Holistic + Multipass found this
**Location:** `frontend/stt.js:417-435`
**Evidence:** The `_sendToSTT` function handles 413, 422, 502, 503, 504 specifically but not 405. The 405 falls through to the generic `if (!resp.ok)` handler producing "STT request failed (405)" — a confusing message for users when the real problem is NGINX misconfiguration.
**Impact:** Poor user experience. The error message provides no diagnostic value. A 405 on this endpoint is always an NGINX routing problem (FastAPI won't return 405 for POST on /transcribe).
**Blast radius:** Single file, frontend only.
**Fix approach:** Add a specific 405 case: `if (resp.status === 405) { throw new Error('Voice search endpoint not configured'); }`

---

## Design Decisions Requiring User Input

### D1. NGINX hard-fails when any upstream service is unreachable

**Location:** `nginx/nginx.conf` (all proxy_pass directives)
**The concern:** NGINX resolves `proxy_pass` hostnames at config load time. If the `stt` container (or any upstream) is down when NGINX starts, it fails with "host not found in upstream" and refuses to start entirely — taking down ALL services, not just the unavailable one.
**Why this needs a decision:** The fix (resolver + variable-based proxy_pass) changes proxy behavior for all locations, not just /stt/. It's a broader architectural change.
**Options:**
  - A) Apply resolver pattern only to /stt/ (optional service, shouldn't take down the stack)
  - B) Apply resolver pattern to all proxy locations (fully resilient, but larger change + testing scope)
  - C) Leave as-is, accept operational discipline of starting services in order
**Recommendation:** Option A — apply only to /stt/ since it's the only truly optional service. The other services (tileserver, nominatim, valhalla, gps, search) are core and should fail-fast if missing.

### D2. File bind mounts break silently after git operations

**Location:** `docker-compose.yml:188-192` (all file-level bind mounts)
**The concern:** Any git operation that replaces a file (commit, checkout, rebase, merge) creates a new inode. Docker file bind mounts track the inode, not the path. The container silently serves stale content.
**Why this needs a decision:** Switching to directory mounts changes the NGINX config include structure.
**Options:**
  - A) Switch to directory mount: mount `./nginx/` → `/etc/nginx/geo/` and include from there
  - B) Accept operational discipline: always `docker compose restart frontend` after editing nginx configs
  - C) Add a deployment note to START.md/README.md documenting this footgun
**Recommendation:** Option B+C — the operational discipline is already needed (you restart after any config change anyway), and documenting it prevents future confusion. Directory mounts add complexity for marginal benefit.

### D3. `depends_on: stt` lacks `condition: service_healthy`

**Location:** `docker-compose.yml:169-175`
**The concern:** Frontend starts as soon as STT container is *created*, not when it's healthy. The STT service has `start_period: 30s` — during that window, requests may get 502.
**Why this needs a decision:** Adding the condition means `docker compose up` won't start the frontend until STT's healthcheck passes, which adds ~30s to startup. But if STT fails to start, the frontend also won't start.
**Options:**
  - A) Add `condition: service_healthy` — safer but couples frontend availability to STT health
  - B) Leave as-is — 502s during startup are transient and acceptable
  - C) Combine with D1 (resolver pattern) — frontend starts immediately, STT gets 502 until ready
**Recommendation:** Option B — transient 502s are acceptable for an optional feature. If D1 is implemented, this becomes moot.

### D4. NGINX `client_max_body_size 2m` vs application limit `1MB`

**Location:** `nginx/nginx.conf:97` (2m) vs `services/stt/main.py:31` (1MB)
**The concern:** NGINX allows 2MB uploads but the application rejects at 1MB. Files between 1-2MB pass NGINX but get rejected by FastAPI.
**Why this needs a decision:** Not technically a bug (defense in depth), but the mismatch wastes bandwidth for oversized files.
**Options:**
  - A) Tighten NGINX to `client_max_body_size 1m` to match the app
  - B) Leave as-is (NGINX provides a generous buffer, app enforces the real limit)
**Recommendation:** Option A — tighten to 1m. Rejecting at the proxy is faster and cheaper than forwarding to the app.

---

## False Positives

None identified. All findings from all three hunters were verified as valid.

---

## Bugs Outside Primary Scope

None. All findings are directly related to the STT 405 request path.

---

## Test Gap Analysis

### B1. Stale bind mount — NGINX container missing /stt/ block
**Why missed:** This is a deployment/infrastructure issue, not a code logic bug. No unit or integration test can catch a stale Docker bind mount. The existing STT endpoint tests (`services/stt/tests/test_endpoints.py`) test the FastAPI service directly via TestClient — they never go through NGINX.
**Pitfall coverage:** Covered by pitfall #6 (Docker-dependent tests). However, there's no E2E test that exercises the full NGINX → STT path. This is a gap but one that requires the full Docker stack running.
**Catch test:** A Docker-compose integration test that `curl -X POST http://localhost:8093/stt/transcribe` with a WAV fixture and asserts a non-405 status code. This would catch both the stale config and the missing container.

### B2. STT container not running
**Why missed:** Same as B1 — operational deployment issue. Covered by documentation (handoff says "needs docker compose build stt").
**Pitfall coverage:** Pitfall #6 applies. No update needed.
**Catch test:** Same Docker-compose integration test as B1 — asserting the STT health endpoint returns JSON, not HTML.

### B3. Inconsistent `$host` vs `$http_host`
**Why missed:** No NGINX config linting or consistency tests exist. The STT endpoint tests bypass NGINX.
**Pitfall coverage:** Not covered by existing pitfalls. However, this is a one-off — an NGINX config consistency check isn't generalizable enough to warrant a new pitfall.
**Catch test:** A shell-based config lint: `grep -c 'proxy_set_header Host \$host;' nginx/nginx.conf` should return 0 (all should use `$http_host`).

### B4. Frontend doesn't handle 405
**Why missed:** No frontend JavaScript tests exist. The STT endpoint tests are backend-only.
**Pitfall coverage:** Not covered. New pitfall candidate: "Test error handling for all HTTP status codes the proxy can return, not just the ones the backend returns."
**Catch test:** Frontend test (or E2E test) that mocks a 405 response from /stt/transcribe and asserts a user-friendly error message is shown.

### Testing Pitfalls Updates
- None added. The B4 gap is a one-off frontend testing concern, not generalizable to the backend-heavy Python test suite.
