#!/bin/bash
# Provision TLS certificates from Tailscale for Geographica HTTPS mode.
#
# Uses `tailscale cert` to obtain a real Let's Encrypt certificate for the
# Pi's MagicDNS hostname. Requires root and an active Tailscale connection.
#
# Usage:
#   sudo ./scripts/provision_tailscale_tls.sh                        # auto-detect hostname
#   sudo ./scripts/provision_tailscale_tls.sh --hostname pandora.twin-bramble.ts.net

set -e

CERT_DIR="/srv/geographica/tls/tailscale"
CONTAINER_NAME="geographica-frontend"

# Parse args
HOSTNAME=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --hostname) HOSTNAME="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# Auto-detect hostname from Tailscale if not provided
if [ -z "$HOSTNAME" ]; then
    if ! command -v tailscale >/dev/null 2>&1; then
        echo "ERROR: tailscale not found. Install Tailscale or pass --hostname."
        exit 1
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        echo "ERROR: python3 not found. Install python3 or pass --hostname <name>."
        exit 1
    fi
    # DNSName has a trailing dot — strip it
    HOSTNAME=$(tailscale status --json | python3 -c "import sys,json; print(json.load(sys.stdin)['Self']['DNSName'].rstrip('.'))" 2>/dev/null)
    if [ -z "$HOSTNAME" ]; then
        echo "ERROR: Could not detect Tailscale hostname. Is Tailscale running?"
        exit 1
    fi
fi

echo "Provisioning TLS certificate for: $HOSTNAME"
echo "  Cert dir: $CERT_DIR"

mkdir -p "$CERT_DIR"

# Provision certificate (idempotent — no-ops if cert is still valid)
tailscale cert \
    --cert-file "$CERT_DIR/server.crt" \
    --key-file "$CERT_DIR/server.key" \
    "$HOSTNAME"

# Set permissions
chmod 644 "$CERT_DIR/server.crt"
chmod 600 "$CERT_DIR/server.key"

echo "Certificate provisioned successfully."
echo "  Cert: $CERT_DIR/server.crt"
echo "  Key:  $CERT_DIR/server.key"

# Reload NGINX if the frontend container is running
if docker inspect "$CONTAINER_NAME" --format '{{.State.Running}}' 2>/dev/null | grep -q true; then
    echo "Reloading NGINX..."
    docker exec "$CONTAINER_NAME" nginx -s reload
    echo "NGINX reloaded with new certificate."
else
    echo "Frontend container not running — skipping NGINX reload."
    echo "Cert will be picked up on next 'docker compose up -d'."
fi
