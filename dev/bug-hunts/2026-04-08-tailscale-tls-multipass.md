# Bug Hunt Report — Tailscale TLS Integration

## Scope
Files analyzed:
- `nginx/entrypoint.sh` (57 lines) — TLS mode branching logic
- `scripts/provision_tailscale_tls.sh` (67 lines) — Cert provisioning script
- `systemd/geographica-tls-renew.service` (9 lines) — Systemd oneshot unit
- `systemd/geographica-tls-renew.timer` (10 lines) — Daily timer

Adjacent files read for context:
- `nginx/tls-include.conf`, `nginx/tls-include-empty.conf`, `nginx/nginx.conf`, `docker-compose.yml`, `.env`

All five passes performed: Contract Violations, Cross-Sibling Pattern Violations, Failure Mode Reasoning, Concurrency Reasoning, Error Propagation.

## Bugs

### 1. HTTPS fallback to HTTP still copies TLS config — NGINX crashes on startup
**Location:** `nginx/entrypoint.sh:35`
**Severity:** critical
**Evidence:** When `TLS_MODE=https` and openssl is not available, the code correctly sets `TLS_MODE="http"` on line 32 and prints "Falling back to HTTP mode." However, line 35 (`cp /etc/nginx/tls-modes/tls-include.conf /etc/nginx/tls-include.conf`) executes unconditionally within the outer `if [ "$TLS_MODE" = "https" ]` block. It copies the TLS config (which includes `listen 443 ssl` and `ssl_certificate` directives) even though no certificates exist. NGINX will fail to start because the referenced cert files do not exist.
**Impact:** On any system where `TLS_MODE=https` and openssl is not installed in the nginx:alpine image, NGINX fails to start entirely. The container enters a crash loop. No frontend is available — not even HTTP fallback. This is a pre-existing bug in the `https` branch, not introduced by the tailscale changeset, but it is the same pattern the tailscale branch had to handle and did handle correctly (lines 42-43).
**Found in:** Pass 1 — Contract Violations

### 2. Systemd service runs without root — `tailscale cert` will fail
**Location:** `systemd/geographica-tls-renew.service:8`
**Severity:** significant
**Evidence:** The provision script requires root (`tailscale cert` writes to a privileged directory, `docker exec` requires Docker group or root). The systemd unit does not specify `User=root` — by default systemd runs `Type=oneshot` services as root, which is correct. However, the `ExecStart` path is hardcoded to `/home/administrator/Code/geographica/scripts/provision_tailscale_tls.sh`. The script uses `set -e` and calls `tailscale cert` then `docker exec`. If the script is not executable (`chmod +x`), systemd will fail silently. The service file has no `ExecStartPre` to verify prerequisites, no `StandardOutput`/`StandardError` directive for logging, and no `Restart` on failure. A daily timer that fails silently means certs expire without warning.
**Impact:** If the script is not marked executable after checkout, the daily renewal will fail silently. The 90-day Let's Encrypt cert will eventually expire and NGINX will serve an expired cert or fail on reload. The user gets no indication the timer is failing because there's no logging configured.
**Found in:** Pass 3 — Failure Mode Reasoning

### 3. TLS cert directory volume mount is read-write — entrypoint.sh writes into it
**Location:** `docker-compose.yml:169` and `nginx/entrypoint.sh:13-27`
**Severity:** minor
**Evidence:** The volume mount `${TLS_CERT_DIR:-./tls}:/etc/nginx/tls` is read-write. In `https` mode, the entrypoint generates self-signed certs directly into `/etc/nginx/tls/` (lines 13-27), which writes back to the host's `TLS_CERT_DIR`. When `TLS_MODE=tailscale`, the tailscale branch does not write to this directory (good), but the mount being read-write means the container could modify or delete provisioned Tailscale certs. This is not a correctness bug per se, but combined with Bug #1's fallback logic, a misconfigured container could corrupt the cert directory.
**Impact:** Low direct impact. The tailscale branch correctly avoids writing to the cert directory. But the `https` branch's self-signed cert generation writes back to the host, which means switching from `https` to `tailscale` mode could leave stale self-signed certs in the tailscale cert directory if `TLS_CERT_DIR` wasn't changed.
**Found in:** Pass 2 — Cross-Sibling Pattern Violations

### 4. Provisioning script hardcodes container name — breaks if user customizes it
**Location:** `scripts/provision_tailscale_tls.sh:14`
**Severity:** minor
**Evidence:** `CONTAINER_NAME="geographica-frontend"` is hardcoded. The `docker-compose.yml` also hardcodes `container_name: geographica-frontend` (line 144), so these match today. But there is no mechanism to keep them in sync. If a user changes the container name in docker-compose.yml (e.g., for running multiple instances), the provisioning script will silently skip the NGINX reload (line 63: "Frontend container not running") even though the container IS running under a different name.
**Impact:** After cert renewal, NGINX continues serving the old cert until the next container restart. The user sees a misleading "Frontend container not running" message when the container is actually running.
**Found in:** Pass 1 — Contract Violations

### 5. Provisioning script uses python3 for JSON parsing — not guaranteed available
**Location:** `scripts/provision_tailscale_tls.sh:32`
**Severity:** minor
**Evidence:** The hostname auto-detection uses `python3 -c "import sys,json; ..."` to parse `tailscale status --json`. The script runs on the host (not in a container). While the Raspberry Pi OS likely has python3 installed, the script already checks for `tailscale` (line 27) but does not check for `python3`. If python3 is missing, the command fails silently (stderr redirected to `/dev/null`), `HOSTNAME` becomes empty, and the script exits with "Could not detect Tailscale hostname. Is Tailscale running?" — a misleading error message.
**Impact:** Misleading error message if python3 is not installed. The user is told Tailscale isn't running when the actual problem is a missing python3 dependency. Could also use `jq` which is more conventional for shell JSON parsing, or Tailscale's own `tailscale status --json | jq -r '.Self.DNSName'`.
**Found in:** Pass 5 — Error Propagation

## Design Concerns

### Fallback-to-HTTP pattern is fragile across all TLS branches
The entrypoint.sh has three TLS modes and two of them have HTTP fallback logic. The `tailscale` branch (lines 41-43) correctly copies the empty TLS config when falling back, but the `https` branch (lines 30-35) does not. This inconsistency suggests the fallback pattern was not designed as a reusable operation. A helper function like `fallback_to_http()` that sets `TLS_MODE=http` AND copies the empty config would prevent the class of bug found in Bug #1.

### No health signal from renewal timer to monitoring
The systemd timer/service pair has no mechanism to report success or failure. There is no `OnFailure=` unit, no integration with a monitoring system, and no status file written. For a security-critical operation (cert renewal), silent failure is a dangerous default. A minimal improvement would be writing a timestamp to a status file that the search service's admin endpoint could expose.

### Race window during cert renewal
When `provision_tailscale_tls.sh` writes new cert files (lines 45-48) and then reloads NGINX (line 60), there is a brief window where `server.crt` has been overwritten but `server.key` has not (or vice versa). If NGINX receives a reload signal during this window, it could load a mismatched cert/key pair and fail. `tailscale cert` likely writes atomically per-file, but the two files are not written atomically as a pair. In practice, the window is microseconds and the reload happens after both writes, so this is theoretical — but worth noting for robustness.

### Timer RandomizedDelaySec=6h means renewal can happen at any time of day
The timer uses `OnCalendar=daily` (midnight) with `RandomizedDelaySec=6h`, so the actual execution window is 00:00-06:00. This is fine for a headless Pi, but if the Pi is being used interactively during those hours, the `tailscale cert` and `docker exec nginx -s reload` commands could cause a brief service interruption. Not a bug, but worth documenting.
