#!/bin/sh
TLS_MODE="${TLS_MODE:-http}"
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
        fi
    fi
    cp /etc/nginx/tls-modes/tls-include.conf /etc/nginx/tls-include.conf
else
    cp /etc/nginx/tls-modes/tls-include-empty.conf /etc/nginx/tls-include.conf
fi

# Validate config
nginx -t 2>&1 || { echo "NGINX config test failed"; exit 1; }

echo "NGINX ready ($TLS_MODE mode)"
exec nginx -g 'daemon off;'
