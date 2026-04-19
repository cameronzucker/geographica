#!/bin/sh
TLS_MODE="${TLS_MODE:-http}"

# Compatibility: map deprecated TLS_MODE vocabulary from pre-1.2 .env files
# to the canonical set. See B1/B19 in the setup remediation plan.
case "$TLS_MODE" in
    self-signed)
        echo "WARN: TLS_MODE=self-signed is deprecated; treating as 'https'. Please update .env."
        TLS_MODE=https
        ;;
    external)
        echo "WARN: TLS_MODE=external is deprecated; treating as 'tailscale'. Please update .env."
        TLS_MODE=tailscale
        ;;
    existing)
        echo "WARN: TLS_MODE=existing is deprecated and has been removed. Falling back to http. Update .env to 'https' (for self-signed) or 'tailscale' (for Let's Encrypt)."
        TLS_MODE=http
        ;;
esac

echo "Geographica NGINX starting in $TLS_MODE mode"

if [ "$TLS_MODE" = "https" ]; then
    if [ ! -f /etc/nginx/tls/server.crt ]; then
        echo "WARNING: TLS_MODE=https but no certificates found."
        echo "Generating self-signed certificates..."
        # Auto-generate if openssl available
        if command -v openssl >/dev/null 2>&1; then
            HOSTNAME=$(hostname -f 2>/dev/null || hostname)
            IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
            mkdir -p /etc/nginx/tls/ca
            openssl genrsa -out /etc/nginx/tls/ca/ca.key 2048 2>/dev/null
            openssl req -new -x509 -days 825 -key /etc/nginx/tls/ca/ca.key \
                -out /etc/nginx/tls/ca.crt -subj "/CN=Geographica CA" 2>/dev/null
            openssl genrsa -out /etc/nginx/tls/server.key 2048 2>/dev/null
            openssl req -new -key /etc/nginx/tls/server.key \
                -out /tmp/server.csr -subj "/CN=$HOSTNAME" 2>/dev/null
            cat > /tmp/san.cnf <<SANEOF
subjectAltName=DNS:$HOSTNAME,DNS:localhost,IP:$IP,IP:127.0.0.1
SANEOF
            openssl x509 -req -days 825 -in /tmp/server.csr \
                -CA /etc/nginx/tls/ca.crt -CAkey /etc/nginx/tls/ca/ca.key \
                -CAcreateserial -out /etc/nginx/tls/server.crt \
                -extfile /tmp/san.cnf 2>/dev/null
            rm -f /tmp/server.csr /tmp/san.cnf /etc/nginx/tls/ca.srl
            echo "Self-signed certificates generated for $HOSTNAME ($IP)"
        else
            echo "ERROR: openssl not found. Install certificates manually or use HTTP mode."
            echo "Falling back to HTTP mode."
            TLS_MODE="http"
            cp /etc/nginx/tls-modes/tls-include-empty.conf /etc/nginx/tls-include.conf
        fi
    fi
    # Only copy TLS config if we didn't fall back to HTTP above
    if [ "$TLS_MODE" = "https" ]; then
        cp /etc/nginx/tls-modes/tls-include.conf /etc/nginx/tls-include.conf
    fi
elif [ "$TLS_MODE" = "tailscale" ]; then
    if [ ! -f /etc/nginx/tls/server.crt ]; then
        echo "ERROR: TLS_MODE=tailscale but no certificates found."
        echo "Run: sudo ./scripts/provision_tailscale_tls.sh"
        echo "Then set TLS_CERT_DIR=/srv/geographica/tls/tailscale in .env"
        echo "Falling back to HTTP mode."
        TLS_MODE="http"
        cp /etc/nginx/tls-modes/tls-include-empty.conf /etc/nginx/tls-include.conf
    else
        echo "Tailscale TLS certificates found."
        cp /etc/nginx/tls-modes/tls-include.conf /etc/nginx/tls-include.conf
    fi
else
    cp /etc/nginx/tls-modes/tls-include-empty.conf /etc/nginx/tls-include.conf
fi

# Validate config (warn but don't fail — DNS may not be available yet)
nginx -t 2>&1 || echo "WARNING: NGINX config test failed (may resolve on startup)"

echo "NGINX ready ($TLS_MODE mode)"
exec nginx -g 'daemon off;'
