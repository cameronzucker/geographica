# Bug Hunt Report: Tailscale TLS Integration

## Scope

Holistic analysis of the Tailscale TLS changeset and its interaction with existing TLS modes.

**Files read (primary):**
- `nginx/entrypoint.sh` (57 lines) -- TLS mode branching, container entrypoint
- `scripts/provision_tailscale_tls.sh` (67 lines) -- host-side cert provisioning
- `systemd/geographica-tls-renew.service` (9 lines) -- oneshot renewal unit
- `systemd/geographica-tls-renew.timer` (10 lines) -- daily timer

**Files read (adjacent):**
- `nginx/tls-include.conf` -- TLS listener directives
- `nginx/tls-include-empty.conf` -- empty placeholder for HTTP mode
- `nginx/nginx.conf` -- full NGINX config (156 lines)
- `docker-compose.yml` -- service definitions and volume mounts
- `.env` -- current deployment config (TLS_MODE=tailscale)

**Verification performed:**
- Confirmed `nginx:alpine` does NOT ship `openssl` (`docker run --rm nginx:alpine which openssl` returns not found)

## Bugs

### 1. HTTPS fallback copies TLS config without certificates, crashing NGINX

**Location:** `nginx/entrypoint.sh:35`
**Severity:** critical
**Pre-existing:** Yes -- this bug exists independently of the tailscale changeset

**Evidence:**

```sh
# entrypoint.sh lines 5-35 (simplified)
if [ "$TLS_MODE" = "https" ]; then          # line 5: outer if
    if [ ! -f /etc/nginx/tls/server.crt ]; then   # line 6: no certs
        if command -v openssl >/dev/null 2>&1; then  # line 10: openssl check
            # ... generate self-signed certs ...
        else
            TLS_MODE="http"                  # line 32: fallback to HTTP
        fi
    fi
    cp /etc/nginx/tls-modes/tls-include.conf /etc/nginx/tls-include.conf  # line 35: ALWAYS runs
```

Line 35 is inside the outer `if` but outside the inner `if/else`. When the fallback at line 32 sets `TLS_MODE="http"`, execution still reaches line 35 because the outer `if` already matched. This copies `tls-include.conf` (containing `listen 443 ssl` and `ssl_certificate` directives) into place even though no certificates exist.

NGINX then fails `nginx -t` at line 53, but the script ignores the failure (`|| echo "WARNING: ..."`) and proceeds to `exec nginx -g 'daemon off;'`, which also fails. The container crash-loops.

**Compounding factor:** `nginx:alpine` does NOT include `openssl`. Verified by running `docker run --rm nginx:alpine which openssl`. The `command -v openssl` check on line 10 always evaluates to false in this container image. Therefore, `TLS_MODE=https` without pre-provisioned certificates is ALWAYS broken -- the self-signed cert generation path is dead code in the current container image.

**Impact:** Any user who sets `TLS_MODE=https` without manually pre-provisioning certificates at `$TLS_CERT_DIR/server.crt` will get a crash-looping frontend container. The error messages mention self-signed cert generation and HTTP fallback, but neither actually works.

**Contrast with tailscale branch:** The new tailscale branch (lines 36-47) handles this correctly -- it copies `tls-include-empty.conf` in its fallback path. The https branch should do the same.

**Fix:**

```sh
# Move the cp inside the branches:
if [ "$TLS_MODE" = "https" ]; then
    if [ ! -f /etc/nginx/tls/server.crt ]; then
        ...
        if command -v openssl >/dev/null 2>&1; then
            ...
        else
            echo "Falling back to HTTP mode."
            TLS_MODE="http"
            cp /etc/nginx/tls-modes/tls-include-empty.conf /etc/nginx/tls-include.conf
        fi
    fi
    # Only copy TLS config if we didn't fall back
    if [ "$TLS_MODE" = "https" ]; then
        cp /etc/nginx/tls-modes/tls-include.conf /etc/nginx/tls-include.conf
    fi
```

---

### 2. Self-signed cert generation is dead code on nginx:alpine (no openssl)

**Location:** `nginx/entrypoint.sh:10-28`
**Severity:** significant
**Pre-existing:** Yes

**Evidence:** Lines 10-28 generate self-signed certificates using `openssl`. However, `nginx:alpine` does not include `openssl`:

```
$ docker run --rm nginx:alpine which openssl
(empty -- not found)
```

The entire self-signed generation block (19 lines of careful openssl commands) can never execute. The `command -v openssl` guard on line 10 always fails, falling through to the broken fallback path described in Bug 1.

**Impact:** The documented behavior ("auto-generates self-signed certs if missing") is a lie for the current container image. Users reading the entrypoint comments or log messages will be misled about what happened. Combined with Bug 1, this means the https mode only works if certs are pre-provisioned externally.

**Fix options:**
1. Add `openssl` to the container by using a custom Dockerfile instead of stock `nginx:alpine`, or
2. Remove the dead code and document that `TLS_MODE=https` requires pre-provisioned certificates (same as `tailscale` mode), or
3. Install openssl in the entrypoint at runtime (`apk add --no-cache openssl`), though this defeats offline-first goals.

---

## Design Concerns

### Hardcoded cert path in provisioning script vs configurable docker-compose mount

`provision_tailscale_tls.sh` hardcodes `CERT_DIR="/srv/geographica/tls/tailscale"` (line 13). `docker-compose.yml` uses `${TLS_CERT_DIR:-./tls}` (line 169). These are coordinated only by convention and the `.env` file. If a user changes `TLS_CERT_DIR` in `.env` without updating the provisioning script (or vice versa), certs end up in the wrong directory. Consider making the provisioning script read from the same `.env` file, or accept `--cert-dir` as a flag.

### Systemd unit hardcodes absolute path to project checkout

`geographica-tls-renew.service` line 9: `ExecStart=/home/administrator/Code/geographica/scripts/provision_tailscale_tls.sh` -- This path is specific to this particular host's directory layout. If the project is cloned elsewhere or another user sets up a new Pi, the systemd unit won't work. Consider using a variable, a symlink from a standard path (e.g., `/usr/local/bin/geographica-tls-renew`), or documenting that users must edit this path.

### No root guard in provisioning script

`provision_tailscale_tls.sh` comments say "Requires root" and the systemd unit will run it as root, but the script itself doesn't verify `$EUID -eq 0`. If a user runs it without sudo, `tailscale cert` may fail with a cryptic error. A simple guard at the top would improve the user experience.

### Timer randomization window is very wide

`geographica-tls-renew.timer` has `RandomizedDelaySec=6h` with `OnCalendar=daily`. This means renewal could happen anywhere in a 6-hour window after midnight. For a single-device deployment (not a fleet), this randomization serves no purpose and could delay cert renewal. Tailscale certs from Let's Encrypt are valid for 90 days and Tailscale renews them when they have less than 14 days remaining, so the 6-hour jitter is harmless in practice -- but it's cargo-culted from fleet deployment patterns.

---

## Tailscale Branch Verdict

The new `tailscale` branch in `entrypoint.sh` (lines 36-47) is **correctly implemented**. It:

1. Checks for existing certs (does not auto-generate) -- correct per requirements
2. On missing certs: prints actionable error, falls back to HTTP, copies empty TLS config -- correct
3. On existing certs: copies TLS config -- correct
4. Does not interfere with the `https` or `http` branches -- confirmed by structural analysis

The `provision_tailscale_tls.sh` script is straightforward and has proper error handling via `set -e`. The JSON parsing has a correct fallback (empty string detected on line 33). The Docker reload is conditional on container state.

The only bugs found are pre-existing issues in the `https` branch that the tailscale changeset exposes by contrast but does not introduce.
