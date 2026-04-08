# Bug Hunt Report: Tailscale TLS Integration

## Scope

**Primary files explored deeply:**
- `nginx/entrypoint.sh` (50 lines) -- The highest-risk file. Traced all three TLS_MODE branches (`https`, `tailscale`, `http`) line by line, including fallback paths. Verified the new `elif` doesn't break existing branches.
- `scripts/provision_tailscale_tls.sh` (65 lines) -- Cert provisioning script. Traced auto-detect, cert write, permissions, and NGINX reload flow.
- `systemd/geographica-tls-renew.service` and `.timer` -- Systemd units for daily renewal.

**Adjacent files read for context:**
- `nginx/tls-include.conf` -- SSL directives and cert paths.
- `nginx/tls-include-empty.conf` -- Empty file for HTTP mode.
- `nginx/nginx.conf` -- Full NGINX config using `include /etc/nginx/tls-include.conf`.
- `docker-compose.yml` -- Frontend service definition, volume mounts, TLS_MODE env.

**Key investigation:** Verified that `nginx:alpine` does NOT ship with `openssl` installed (`docker run --rm nginx:alpine which openssl` returns not found). This is critical context for Bug #1.

## Bugs

### 1. HTTPS mode HTTP fallback is broken -- NGINX crashes instead of degrading to HTTP

**Location:** `nginx/entrypoint.sh:35`
**Severity:** critical (pre-existing, NOT introduced by tailscale changeset)

**Evidence:** When `TLS_MODE=https` and no certificates are pre-mounted, the entrypoint is supposed to auto-generate self-signed certs or fall back to HTTP. However:

1. `nginx:alpine` does not include `openssl`, so `command -v openssl` (line 10) always fails.
2. The `else` branch at line 29 sets `TLS_MODE="http"` (line 32) and logs "Falling back to HTTP mode."
3. But execution continues to line 35: `cp /etc/nginx/tls-modes/tls-include.conf /etc/nginx/tls-include.conf`
4. This line is **outside** the inner `if/else` block but **inside** the outer `if [ "$TLS_MODE" = "https" ]` block. Setting `TLS_MODE="http"` mid-execution does not re-evaluate the shell's already-entered branch.
5. Result: NGINX gets the TLS-enabled config (`listen 443 ssl` + cert paths) but has no cert files. `nginx -t` reports an error, and `exec nginx -g 'daemon off;'` fails. The container crashes.

The **new tailscale branch** (lines 36-47) handles this correctly by calling `cp` of the empty config inside its fallback path. The pre-existing `https` branch does not.

**Impact:** Any user who sets `TLS_MODE=https` without pre-mounting certificates gets a crashed frontend container with a misleading "Falling back to HTTP mode" log message. The self-signed cert auto-generation is dead code in the `nginx:alpine` image.

**Fix:** Move the `cp` on line 35 inside the `if/else` blocks, mirroring the pattern used in the tailscale branch:

```sh
if [ "$TLS_MODE" = "https" ]; then
    if [ ! -f /etc/nginx/tls/server.crt ]; then
        ...
        if command -v openssl >/dev/null 2>&1; then
            ...  # generate certs
            cp /etc/nginx/tls-modes/tls-include.conf /etc/nginx/tls-include.conf
        else
            echo "Falling back to HTTP mode."
            TLS_MODE="http"
            cp /etc/nginx/tls-modes/tls-include-empty.conf /etc/nginx/tls-include.conf
        fi
    else
        cp /etc/nginx/tls-modes/tls-include.conf /etc/nginx/tls-include.conf
    fi
```

## Design Concerns

### The tailscale branch itself is well-implemented

The new `elif [ "$TLS_MODE" = "tailscale" ]` branch (lines 36-47) correctly handles both the happy path (certs found -> copy TLS config) and fallback path (certs missing -> copy empty config + set TLS_MODE to http). It avoids the structural mistake present in the pre-existing `https` branch. The `elif` placement between `if` and `else` does not alter the behavior of existing branches.

### Self-signed cert generation is dead code

The entire `openssl` block (lines 10-28) in the `https` branch can never execute in `nginx:alpine` because `openssl` is not installed. If self-signed cert auto-generation is desired, the Dockerfile would need to install openssl, or the approach should be removed in favor of requiring pre-mounted certs (like the tailscale branch does).

### No validation of unknown TLS_MODE values

If `TLS_MODE` is set to an unrecognized value (e.g., `tls`, `TLS`, `HTTPS`), the `else` branch catches it and NGINX starts in HTTP mode. The startup log will say "Geographica NGINX starting in HTTPS mode" and "NGINX ready (HTTPS mode)" while actually running HTTP-only. This is confusing but not a crash. A warning for unknown values would prevent misconfiguration.

### Hardcoded absolute path in systemd unit

`systemd/geographica-tls-renew.service` hardcodes `ExecStart=/home/administrator/Code/geographica/scripts/provision_tailscale_tls.sh`. If the repo is cloned to a different location or by a different user, the unit file must be manually updated. This is standard for systemd units but worth noting in deployment docs.

### Cert provisioning has no atomic write guarantee

`provision_tailscale_tls.sh` calls `tailscale cert` which writes `server.crt` and `server.key` as two separate files. If `tailscale cert` is interrupted between writing the two files, NGINX could pick up a mismatched cert/key pair on the next reload. In practice, `tailscale cert` is reliable and this is theoretical.
