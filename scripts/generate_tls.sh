#!/bin/bash
# Generate TLS certificates for Geographica HTTPS mode.
#
# Creates a self-signed CA + server certificate with auto-detected
# hostname and IP as SANs. For production use with a real domain,
# use Let's Encrypt or Cloudflare origin certificates instead.
#
# Usage:
#   ./scripts/generate_tls.sh                    # auto-detect hostname/IP
#   ./scripts/generate_tls.sh --domain example.com  # add custom domain SAN

set -e

CERT_DIR="/srv/geographica/tls"
CA_DIR="$CERT_DIR/ca"
VALIDITY_DAYS=825

# Parse args
EXTRA_DOMAIN=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --domain) EXTRA_DOMAIN="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

mkdir -p "$CERT_DIR" "$CA_DIR"

# Auto-detect hostname and IP
HOSTNAME=$(hostname -f 2>/dev/null || hostname)
IP=$(hostname -I 2>/dev/null | awk '{print $1}')

echo "Generating TLS certificates..."
echo "  Hostname: $HOSTNAME"
echo "  IP: $IP"
[ -n "$EXTRA_DOMAIN" ] && echo "  Domain: $EXTRA_DOMAIN"

# Build SAN list
SANS="DNS:$HOSTNAME,DNS:localhost,IP:${IP:-127.0.0.1},IP:127.0.0.1"
[ -n "$EXTRA_DOMAIN" ] && SANS="$SANS,DNS:$EXTRA_DOMAIN"

# Generate CA (private key kept separate, never served)
openssl genrsa -out "$CA_DIR/ca.key" 2048 2>/dev/null
openssl req -new -x509 -days "$VALIDITY_DAYS" -key "$CA_DIR/ca.key" \
    -out "$CERT_DIR/ca.crt" \
    -subj "/CN=Geographica CA/O=Geographica" 2>/dev/null

# Generate server certificate signed by CA
openssl genrsa -out "$CERT_DIR/server.key" 2048 2>/dev/null
openssl req -new -key "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.csr" \
    -subj "/CN=$HOSTNAME/O=Geographica" 2>/dev/null

openssl x509 -req -days "$VALIDITY_DAYS" \
    -in "$CERT_DIR/server.csr" \
    -CA "$CERT_DIR/ca.crt" -CAkey "$CA_DIR/ca.key" \
    -CAcreateserial -out "$CERT_DIR/server.crt" \
    -extfile <(printf "subjectAltName=$SANS") 2>/dev/null

# Clean up intermediary files
rm -f "$CERT_DIR/server.csr" "$CERT_DIR/ca.srl"

# Set permissions
chmod 600 "$CA_DIR/ca.key"
chmod 644 "$CERT_DIR/server.crt" "$CERT_DIR/ca.crt"
chmod 600 "$CERT_DIR/server.key"

echo ""
echo "Certificates generated in $CERT_DIR:"
echo "  CA cert:     $CERT_DIR/ca.crt (distribute to clients)"
echo "  Server cert: $CERT_DIR/server.crt"
echo "  Server key:  $CERT_DIR/server.key"
echo "  CA key:      $CA_DIR/ca.key (KEEP PRIVATE)"
echo ""
echo "To use: set TLS_MODE=https in .env and restart the frontend container."
echo "Clients should install ca.crt to trust this server."
