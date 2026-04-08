# Tailscale TLS Integration Bug Hunt — Consolidated Findings

**Date:** 2026-04-08
**Scope:** Tailscale TLS integration — validation that the changeset introduces no breaking changes to existing HTTP/HTTPS modes
**Hunters:** Exploratory, Holistic, Multipass

**Verdict: The Tailscale changeset itself is clean.** All three hunters independently confirmed that the new `tailscale` branch in `entrypoint.sh` is correctly implemented and does not alter behavior of existing `http` or `https` paths. The bugs found are pre-existing or minor design concerns.

---

## Confirmed Bugs

### B1. HTTPS fallback copies TLS config without certificates, crashing NGINX
**Consensus:** All three hunters found this (critical, unanimous)
**Location:** `nginx/entrypoint.sh:35`
**Evidence:** When `TLS_MODE=https` and openssl is not available (which is always the case on `nginx:alpine`), the code sets `TLS_MODE="http"` on line 32 but line 35 unconditionally copies `tls-include.conf` (which contains `listen 443 ssl` and `ssl_certificate` directives). NGINX receives TLS directives with no cert files and crashes. The new `tailscale` branch (lines 42-43) handles the equivalent case correctly by copying `tls-include-empty.conf` inside the fallback path.
**Impact:** `TLS_MODE=https` without pre-provisioned certificates is completely broken. NGINX crash-loops. Since `nginx:alpine` lacks openssl, the self-signed cert auto-generation never executes, so the fallback path is always taken.
**Blast radius:** `nginx/entrypoint.sh` only.
**Fix approach:** Move line 35's `cp` inside the success path (after cert generation or when certs already exist), and add `cp tls-include-empty.conf` in the openssl-not-found fallback — matching the pattern the tailscale branch already uses.

### B2. Self-signed cert generation is dead code on nginx:alpine
**Consensus:** Holistic found explicitly, Exploratory and Multipass implied via the fallback analysis
**Location:** `nginx/entrypoint.sh:10-28`
**Evidence:** `docker run --rm nginx:alpine which openssl` returns empty. The 19-line cert generation block can never execute on the container image used by docker-compose.yml.
**Impact:** The auto-generation feature advertised in the code and docs does not work. Combined with B1, this means `TLS_MODE=https` without manual cert provisioning is always broken.
**Blast radius:** Same file. Fix requires either installing openssl in the container (add to a Dockerfile or use a different base image) or removing the dead code and documenting that certs must be pre-provisioned.
**Fix approach:** Add `apk add --no-cache openssl` to the entrypoint.sh before the cert generation block (lightweight, ~1 MB), OR document that `https` mode requires pre-provisioned certs and remove the auto-generation. Recommend the former — it matches the documented intent.

---

## Design Decisions Requiring User Input

### D1. Should the HTTPS self-signed auto-generation be fixed or removed?
**Location:** `nginx/entrypoint.sh:10-28`
**The concern:** The auto-generation is dead code (no openssl in container). Fixing it requires adding openssl to the container.
**Options:**
1. **Fix:** Add `apk add --no-cache openssl` at the start of the entrypoint. Self-signed certs work as documented. Adds ~1 MB and a few seconds to container startup on first run.
2. **Remove:** Delete the auto-generation code, document that `https` mode requires `scripts/generate_tls.sh` to be run first. Simpler, but changes the documented behavior.
3. **Dockerfile approach:** Create a custom NGINX Dockerfile that includes openssl. Avoids runtime package install but adds build complexity.
**Recommendation:** Option 1. It's the smallest change, matches documented behavior, and the runtime cost is negligible.

---

## False Positives

### FP1. Cross-mode cert contamination
**Flagged by:** Multipass
**Why invalid:** The `TLS_CERT_DIR` env var changes the host mount point. Switching from `https` (./tls) to `tailscale` (/srv/geographica/tls/tailscale) uses completely different directories. Contamination only occurs if the user deliberately points both modes at the same directory, which is user error, not a code bug.

### FP2. 6-hour randomized delay is unnecessary for single device
**Flagged by:** Holistic
**Why invalid:** The delay is harmless (timer still fires daily), and is good practice even on a single device — it prevents the cert renewal from hitting Let's Encrypt at a predictable time. Removing it gains nothing.

---

## Bugs Outside Primary Scope

### O1. Hardcoded container name in provisioning script
**Location:** `scripts/provision_tailscale_tls.sh:14`
**Blast radius:** Script-only. If container name changes, reload silently skips.
**Recommendation:** Minor. Document for later. Container name is set in docker-compose.yml and unlikely to change.

### O2. python3 dependency not checked in provisioning script
**Location:** `scripts/provision_tailscale_tls.sh:32`
**Blast radius:** Script-only. Misleading error message if python3 missing.
**Recommendation:** Minor. Add a `command -v python3` check before the auto-detection. Quick fix.

### O3. Systemd service has no journald logging or failure notification
**Location:** `systemd/geographica-tls-renew.service`
**Blast radius:** Systemd unit only. If renewal fails silently, certs expire after 90 days.
**Recommendation:** Add `StandardOutput=journal` and `StandardError=journal`. Quick fix.

### O4. Hardcoded repo path in systemd service
**Location:** `systemd/geographica-tls-renew.service:8`
**Blast radius:** Won't work on another machine with a different install path.
**Recommendation:** Document that the path must be edited during setup. Acceptable for a single-Pi deployment.

---

## Test Gap Analysis

### B1. HTTPS fallback copies TLS config
**Why missed:** No tests exist for the entrypoint.sh script. Shell entrypoints in Docker containers are typically tested manually, not via automated tests.
**Pitfall coverage:** No `dev/testing-pitfalls.md` exists.
**Catch test:** A shell test that sets `TLS_MODE=https`, removes `/etc/nginx/tls/server.crt`, and verifies that `/etc/nginx/tls-include.conf` contains the empty config (not the TLS directives). Could be run with `docker run --rm -e TLS_MODE=https ...`.

### B2. Dead code on nginx:alpine
**Why missed:** The openssl availability was assumed but never tested against the actual container image.
**Catch test:** `docker run --rm nginx:alpine which openssl` — a one-liner that would have caught this immediately.

### Testing Pitfalls Updates
- None (no `dev/testing-pitfalls.md` exists yet)
