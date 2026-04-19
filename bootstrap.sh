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
  echo "  git clone https://github.com/cameronzucker/geographica.git ~/geographica"
  exit 1
fi

echo "[1/6] Installing system packages..."
# Add Docker's official apt repository (idempotent — skipped if key already present)
if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/debian \
$(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
fi
apt update
apt install -y \
  docker-ce docker-ce-cli containerd.io docker-compose-plugin \
  python3 python3-venv python3-pip \
  gdal-bin osmium-tool \
  gpsd gpsd-clients \
  git wget curl unzip

echo "[2/6] Installing keyring dependencies..."
apt install -y gnome-keyring libsecret-tools dbus-x11

# Configure PAM auto-unlock for GNOME Keyring
if ! grep -q pam_gnome_keyring /etc/pam.d/common-auth 2>/dev/null; then
    echo "auth optional pam_gnome_keyring.so" >> /etc/pam.d/common-auth
    echo "  Added PAM auto-unlock to common-auth"
fi
if ! grep -q pam_gnome_keyring /etc/pam.d/common-session 2>/dev/null; then
    echo "session optional pam_gnome_keyring.so auto_start" >> /etc/pam.d/common-session
    echo "  Added PAM auto-start to common-session"
fi

# Enable cgroup memory controller for Docker memory limits
if ! grep -q "cgroup_enable=memory" /boot/firmware/cmdline.txt 2>/dev/null; then
    sed -i 's/$/ cgroup_enable=memory cgroup_memory=1/' /boot/firmware/cmdline.txt
    echo "  Enabled cgroup memory controller (reboot required to take effect)"
    NEEDS_REBOOT=1
fi

echo "[3/6] Adding $ACTUAL_USER to docker group..."
usermod -aG docker "$ACTUAL_USER"

echo "[4/6] Starting Docker..."
systemctl start docker
systemctl enable docker

echo "[5/6] Creating data directory..."
DATA_DIR="/srv/geographica/data"
mkdir -p "$DATA_DIR"/{pbf,nominatim,valhalla}
chown -R "$ACTUAL_USER":"$ACTUAL_USER" /srv/geographica

echo "      Creating data symlink..."
ln -sf "$DATA_DIR" "$REPO_DIR/data"

echo "[6/6] Installing keyring agent service..."
cp "$REPO_DIR/services/keyring-agent/geographica-keyring.service" /etc/systemd/system/
# Update paths to match actual repo location and user
sed -i "s|/home/administrator/Code/geographica|$REPO_DIR|g" /etc/systemd/system/geographica-keyring.service
sed -i "s|User=administrator|User=$ACTUAL_USER|g" /etc/systemd/system/geographica-keyring.service
systemctl daemon-reload
systemctl enable geographica-keyring
systemctl start geographica-keyring
echo "  Keyring agent installed and started"

echo ""
echo "============================================"
echo "Bootstrap complete."
echo "============================================"
echo ""
echo "Next step:"
if [ "${NEEDS_REBOOT:-0}" = "1" ]; then
    echo "  A reboot is required (cgroup memory controller was enabled)."
    echo ""
    echo "  1. sudo reboot"
    echo "  2. Log out and back in before running ./setup.sh (docker group membership needs to take effect)."
    echo "  3. cd \"$REPO_DIR\" && ./setup.sh"
    echo ""
    echo "If you're connected over SSH, reconnect after the reboot and re-run ./setup.sh."
else
    echo "  Log out and back in before running ./setup.sh (docker group membership needs to take effect)."
    echo "  Then: cd \"$REPO_DIR\" && ./setup.sh"
    echo ""
    echo "If you're connected over SSH, you can log out and reconnect to the same session."
fi
