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
CMDLINE=""
if [ -f /boot/firmware/cmdline.txt ]; then
    CMDLINE=/boot/firmware/cmdline.txt
elif [ -f /boot/cmdline.txt ]; then
    CMDLINE=/boot/cmdline.txt
fi
if [ -n "$CMDLINE" ]; then
    if ! grep -q "cgroup_enable=memory" "$CMDLINE"; then
        sed -i 's/$/ cgroup_enable=memory cgroup_memory=1/' "$CMDLINE"
        echo "  Enabled cgroup memory controller via $CMDLINE (reboot required)"
        NEEDS_REBOOT=1
    fi
else
    echo "  [skip] cgroup memory enable: no cmdline.txt found (not a Raspberry Pi OS install — Docker memory limits may not work)"
fi

echo "[3/6] Adding $ACTUAL_USER to docker group..."
usermod -aG docker "$ACTUAL_USER"

echo "[4/6] Starting Docker..."
systemctl start docker
systemctl enable docker

echo "[5/6] Creating data directory..."
DATA_DIR="/srv/geographica/data"
mkdir -p "$DATA_DIR"/{pbf,nominatim,valhalla}
# Non-recursive chown of the top-level dir and the three immediate data subdirs.
# Do NOT chown recursively — container-owned data (UID 1000 valhalla, UID 999 postgres)
# would be clobbered to host-user ownership.
chown "$ACTUAL_USER":"$ACTUAL_USER" /srv/geographica 2>/dev/null || true
chown "$ACTUAL_USER":"$ACTUAL_USER" /srv/geographica/data 2>/dev/null || true
for sub in pbf nominatim valhalla; do
    [ -d "/srv/geographica/data/$sub" ] && \
        chown "$ACTUAL_USER":"$ACTUAL_USER" "/srv/geographica/data/$sub" 2>/dev/null || true
done

echo "      Creating data symlink..."
# Create/update ./data symlink. If a real directory exists where ./data should be,
# refuse to clobber it — require manual cleanup.
if [ -e "$REPO_DIR/data" ] && [ ! -L "$REPO_DIR/data" ]; then
    echo "ERROR: $REPO_DIR/data exists as a regular directory. Remove it manually before re-running bootstrap."
    exit 1
fi
ln -sfn "$DATA_DIR" "$REPO_DIR/data"

echo "[N/M] Installing Python packages for data pipeline..."
if [ -f "$REPO_DIR/scripts/requirements.txt" ]; then
    # Install as the actual user (not root). break-system-packages is needed on
    # Debian Trixie+ which PEP 668 ships with an externally-managed marker.
    sudo -u "$ACTUAL_USER" -H pip install --user --break-system-packages -r "$REPO_DIR/scripts/requirements.txt"
    echo "  Pipeline Python packages installed for user $ACTUAL_USER"
else
    echo "  WARNING: $REPO_DIR/scripts/requirements.txt not found — pipeline scripts will fail at import time"
fi

echo "[N/M] Installing Tippecanoe (ARM64 binary from GitHub Release)..."
# Pin to the Geographica release tag for reproducibility. Update this version when cutting a new release.
TIPPECANOE_RELEASE_URL="https://github.com/cameronzucker/geographica/releases/download/v1.1.0/tippecanoe-arm64"
if command -v tippecanoe >/dev/null 2>&1; then
    echo "  tippecanoe already on PATH: $(tippecanoe --version 2>&1 | head -1) — skipping install"
    echo "  (If public-lands pipeline fails due to too-old tippecanoe: sudo rm \$(command -v tippecanoe) && re-run bootstrap)"
else
    if wget -q --show-progress -O /tmp/tippecanoe "$TIPPECANOE_RELEASE_URL"; then
        chmod +x /tmp/tippecanoe
        if mv /tmp/tippecanoe /usr/local/bin/tippecanoe; then
            echo "  Installed tippecanoe to /usr/local/bin/tippecanoe"
        else
            echo "  WARNING: Downloaded tippecanoe but could not move to /usr/local/bin (insufficient permissions?)"
            echo "  The binary is still at /tmp/tippecanoe — move it manually with:"
            echo "    sudo mv /tmp/tippecanoe /usr/local/bin/tippecanoe"
        fi
    else
        echo "  WARNING: Could not download tippecanoe from $TIPPECANOE_RELEASE_URL"
        echo "  Public lands pipeline will fail until you install tippecanoe manually:"
        echo "    Option A: sudo apt install build-essential libsqlite3-dev zlib1g-dev"
        echo "              git clone https://github.com/felt/tippecanoe.git /tmp/tippecanoe-src"
        echo "              cd /tmp/tippecanoe-src && make -j4 && sudo make install"
        echo "    Option B: Download a release asset from https://github.com/cameronzucker/geographica/releases"
        echo "    Option C: Build via ./tools/build-tippecanoe.sh (see tools/README.md)"
    fi
fi

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
