# Tailscale TLS Integration

**Date:** 2026-04-08
**Status:** Approved
**Approach:** `tailscale cert` provisioning + new `TLS_MODE=tailscale` value

## Problem

Geographica needs trusted HTTPS for two reasons:
1. Browser Geolocation API requires a secure context — device GPS fails on HTTP with "Only secure origins are allowed."
2. Remote access to the Pi via Tailscale needs HTTPS for a usable experience.

The original plan called for Cloudflare Tunnel, but Tailscale is already installed and running on the Pi (`pandora.twin-bramble.ts.net`). Tailscale can provision real Let's Encrypt certificates for the MagicDNS hostname, giving us trusted HTTPS without self-signed CA distribution.

## Design

### Dual-mode operation

The Pi serves both protocols simultaneously:
- **HTTP on :8093** — for LAN and AREDN mesh clients (unchanged)
- **HTTPS on :443** — for Tailscale clients via `https://pandora.twin-bramble.ts.net`

The config panel remains localhost-only on `127.0.0.1:8097` (unchanged).

### Cert provisioning

A new script `scripts/provision_tailscale_tls.sh` that:
1. Auto-detects the Tailscale hostname via `tailscale status --json | jq -r '.Self.DNSName'` (strips trailing dot). Accepts `--hostname <name>` override.
2. Creates `/srv/geographica/tls/tailscale/` if it doesn't exist
3. Runs `tailscale cert --cert-file /srv/geographica/tls/tailscale/server.crt --key-file /srv/geographica/tls/tailscale/server.key <hostname>`
4. Sets file permissions (644 for cert, 600 for key)
5. Reloads NGINX if the frontend container is running: `docker exec geographica-frontend nginx -s reload`

Requires root (for `tailscale cert`). The command is idempotent — re-running it when the cert is still valid is a no-op.

### TLS_MODE=tailscale

The existing `TLS_MODE` toggle in `entrypoint.sh` gains a third value:

| TLS_MODE | Behavior | Cert source |
|----------|----------|-------------|
| `http` (default) | No TLS directives, HTTP only | None |
| `https` | TLS enabled, auto-generates self-signed if missing | Self-signed CA |
| `tailscale` | TLS enabled, fails if certs missing (no auto-generation) | `tailscale cert` |

Both `https` and `tailscale` modes use the same `tls-include.conf` (same `listen 443 ssl`, same cipher config). The difference is in `entrypoint.sh` behavior:
- `https` mode: if `server.crt` is missing, auto-generate a self-signed cert
- `tailscale` mode: if `server.crt` is missing, print an error message ("Run scripts/provision_tailscale_tls.sh first") and fall back to HTTP mode

### .env configuration

```
TLS_MODE=tailscale
TLS_CERT_DIR=/srv/geographica/tls/tailscale
```

The existing `${TLS_CERT_DIR:-./tls}:/etc/nginx/tls` volume mount in docker-compose.yml handles this — no compose changes needed.

### Systemd timer for cert renewal

Let's Encrypt certs expire after 90 days. A systemd timer runs the provisioning script daily.

**`/etc/systemd/system/geographica-tls-renew.service`:**
- Type=oneshot
- ExecStart=/home/administrator/Code/geographica/scripts/provision_tailscale_tls.sh
- Runs `tailscale cert` (idempotent) + NGINX reload

**`/etc/systemd/system/geographica-tls-renew.timer`:**
- OnCalendar=daily
- RandomizedDelaySec=6h (spread load on Let's Encrypt)
- Persistent=true (catches up if Pi was powered off)

Enabled with: `sudo systemctl enable --now geographica-tls-renew.timer`

## Files changed

| File | Change |
|------|--------|
| `scripts/provision_tailscale_tls.sh` | **New.** Cert provisioning + NGINX reload. |
| `nginx/entrypoint.sh` | Add `tailscale` branch to the TLS_MODE case. |
| `systemd/geographica-tls-renew.service` | **New.** Oneshot unit for cert renewal. |
| `systemd/geographica-tls-renew.timer` | **New.** Daily timer with randomized delay. |
| `README.md` | Add Tailscale TLS setup section. |

Files **not** changed: `nginx.conf`, `tls-include.conf`, `docker-compose.yml`, any service code, any frontend code.

## Setup flow

1. `sudo ./scripts/provision_tailscale_tls.sh`
2. Add `TLS_MODE=tailscale` and `TLS_CERT_DIR=/srv/geographica/tls/tailscale` to `.env`
3. `docker compose up -d` (or `docker compose restart frontend`)
4. `sudo systemctl enable --now geographica-tls-renew.timer`
5. Visit `https://pandora.twin-bramble.ts.net` — green padlock, GPS works

## What this does NOT include

- Cloudflare Tunnel (deferred — Tailscale covers the use case for now)
- AREDN TLS 1.2 published-key mode (deferred per TODOS.md — regulatory ambiguity)
- Tailscale Funnel / public internet exposure (not needed, can be added later with `tailscale funnel`)
- Changes to the config panel access model (stays localhost-only)
