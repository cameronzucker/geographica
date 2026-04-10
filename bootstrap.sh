#!/bin/bash
set -e

echo "Geographica Bootstrap"
echo "====================="
echo "This script installs system prerequisites. It requires sudo."
echo ""

# Check we're running as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run with sudo: sudo ./bootstrap.sh"
  exit 1
fi

# Detect the actual user (not root)
ACTUAL_USER="${SUDO_USER:-$USER}"

# Check repo dir is not world-writable (security)
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PERMS=$(stat -c %a "$REPO_DIR")
if [ "${PERMS: -1}" -ge 6 ]; then
  echo "WARNING: Repository directory ($REPO_DIR) is world-writable."
  echo "This is a security risk. Clone into your home directory instead."
  echo "  git clone https://github.com/cdzucker/geographica.git ~/geographica"
  exit 1
fi

echo "[1/5] Installing system packages..."
apt update
apt install -y \
  docker.io docker-compose \
  python3 python3-venv python3-pip \
  gdal-bin osmium-tool \
  gpsd gpsd-clients \
  git wget curl unzip

echo "[2/5] Adding $ACTUAL_USER to docker group..."
usermod -aG docker "$ACTUAL_USER"

echo "[3/5] Starting Docker..."
systemctl start docker
systemctl enable docker

echo "[4/5] Creating data directory..."
DATA_DIR="/srv/geographica/data"
mkdir -p "$DATA_DIR"/{pbf,nominatim,valhalla}
chown -R "$ACTUAL_USER":"$ACTUAL_USER" /srv/geographica

echo "[5/5] Creating data symlink..."
ln -sf "$DATA_DIR" "$REPO_DIR/data"

echo ""
echo "=========================================="
echo "Bootstrap complete!"
echo ""
echo "Next step:"
echo ""
echo "  ./setup"
echo ""
echo "This opens a browser-based setup wizard at:"
echo "  http://localhost:8099"
echo ""
echo "If you're accessing this Pi remotely, use VNC"
echo "or SSH tunnel:"
echo "  ssh -L 8099:localhost:8099 $ACTUAL_USER@$(hostname -I | awk '{print $1}')"
echo "Then open http://localhost:8099 in your local browser."
echo "=========================================="
