#!/bin/bash
# dev/harness/import-raspios.sh — idempotent import of Raspberry Pi OS Trixie
# (arm64 lite) as an LXD image aliased `raspios-trixie-lite`.
#
# Why: the plain `images:debian/trixie/cloud` LXD image is what our harness
# used through 2026-04-19, but beta testers run Raspberry Pi OS. That
# distribution ships a different default package set (raspi-config, wpa
# config, systemd-networkd vs dhcpcd, rpi-update, etc.) AND pulls apt from
# BOTH `deb.debian.org` and `archive.raspberrypi.org`. Bugs that live at
# the intersection of those two repos (e.g. the 2026-04-19 dpkg file
# conflict between Debian's `docker-buildx` and Docker's `-plugin`) only
# show up against a real raspios base.
#
# Usage:
#   ./import-raspios.sh            — import if not already present (idempotent)
#   ./import-raspios.sh --force    — re-import even if present
#
# Requires: sudo (for losetup + mount); curl; xz-utils; lxd.
#
# Takes ~5-10 min on first run (download + decompress + tarball + import).
# Subsequent runs return immediately.
set -euo pipefail

FORCE=0
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        --help|-h)
            echo "usage: $0 [--force]"
            exit 0
            ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

ALIAS="raspios-trixie-lite"
CACHE_DIR="${RASPIOS_CACHE_DIR:-/var/cache/geographica-harness}"
URL_REDIRECT="https://downloads.raspberrypi.org/raspios_lite_arm64_latest"
WORKDIR="$(mktemp -d -t raspios-import-XXXXXX)"

cleanup() {
    # Unmount + loop-release on exit, even if the script crashes partway.
    [ -n "${MOUNTPOINT:-}" ] && mountpoint -q "$MOUNTPOINT" && sudo umount "$MOUNTPOINT" || true
    [ -n "${LOOPDEV:-}" ] && sudo losetup -d "$LOOPDEV" 2>/dev/null || true
    rm -rf "$WORKDIR"
}
trap cleanup EXIT

if [ "$FORCE" -eq 0 ] && lxc image info "$ALIAS" >/dev/null 2>&1; then
    echo "[import-raspios] '$ALIAS' already imported; skipping (use --force to re-import)."
    exit 0
fi

# --- step 1: resolve latest raspios-lite-arm64 image URL -----------------
echo "[import-raspios] Resolving latest raspios-lite-arm64 URL..."
RESOLVED_URL="$(curl -sI "$URL_REDIRECT" | awk '/^[Ll]ocation:/ { print $2 }' | tr -d '\r\n')"
if [ -z "$RESOLVED_URL" ]; then
    echo "FAIL: could not resolve $URL_REDIRECT via 302" >&2
    exit 1
fi
IMG_XZ_NAME="$(basename "$RESOLVED_URL")"
echo "[import-raspios]   latest = $IMG_XZ_NAME"

# --- step 2: download (cached) -------------------------------------------
sudo install -d -m 0755 "$CACHE_DIR"
sudo chown "$USER:$USER" "$CACHE_DIR"
IMG_XZ="$CACHE_DIR/$IMG_XZ_NAME"
if [ -f "$IMG_XZ" ]; then
    echo "[import-raspios] Using cached $IMG_XZ"
else
    echo "[import-raspios] Downloading ($RESOLVED_URL)..."
    curl -fsSL --retry 3 -o "$IMG_XZ.partial" "$RESOLVED_URL"
    mv "$IMG_XZ.partial" "$IMG_XZ"
fi

# --- step 3: decompress to a temp .img ------------------------------------
IMG="$WORKDIR/raspios.img"
echo "[import-raspios] Decompressing .xz → .img (this takes a minute)..."
xz --decompress --stdout "$IMG_XZ" > "$IMG"

# --- step 4: losetup + mount root partition ------------------------------
echo "[import-raspios] Mounting root partition..."
LOOPDEV="$(sudo losetup -P -f --show "$IMG")"
# Raspberry Pi OS images have 2 partitions: [1]=/boot (FAT), [2]=/ (ext4).
ROOT_PART="${LOOPDEV}p2"
if [ ! -b "$ROOT_PART" ]; then
    echo "FAIL: $ROOT_PART not found — partition layout unexpected" >&2
    ls -la "${LOOPDEV}"* >&2
    exit 1
fi
MOUNTPOINT="$WORKDIR/rootfs"
mkdir -p "$MOUNTPOINT"
sudo mount -o ro "$ROOT_PART" "$MOUNTPOINT"

# --- step 5: tarball the rootfs -------------------------------------------
# Exclude kernel + boot firmware (LXD containers use host kernel) and any
# large data bloat that's not needed for apt/test exercise.
ROOTFS_TAR="$WORKDIR/rootfs.tar"
echo "[import-raspios] Creating rootfs tarball (this takes a minute)..."
sudo tar --numeric-owner \
    --exclude=./boot/firmware \
    --exclude=./boot/kernel\*.img \
    --exclude=./lib/modules \
    --exclude=./var/cache/apt/archives/\*.deb \
    --exclude=./var/lib/apt/lists/\* \
    -cf "$ROOTFS_TAR" -C "$MOUNTPOINT" .

# --- step 6: LXD metadata.tar ---------------------------------------------
META_DIR="$WORKDIR/meta"
mkdir -p "$META_DIR"
cat > "$META_DIR/metadata.yaml" <<EOF
architecture: aarch64
creation_date: $(date +%s)
properties:
  architecture: aarch64
  description: Raspberry Pi OS Lite (trixie arm64) imported from $IMG_XZ_NAME
  os: raspios
  release: trixie
  variant: lite
EOF
META_TAR="$WORKDIR/metadata.tar"
tar -cf "$META_TAR" -C "$META_DIR" metadata.yaml

# --- step 7: import to LXD ------------------------------------------------
if [ "$FORCE" -eq 1 ] && lxc image info "$ALIAS" >/dev/null 2>&1; then
    echo "[import-raspios] --force: deleting existing alias $ALIAS"
    lxc image delete "$ALIAS"
fi
echo "[import-raspios] Importing as LXD image (alias=$ALIAS)..."
lxc image import "$META_TAR" "$ROOTFS_TAR" --alias "$ALIAS"

echo ""
echo "[import-raspios] DONE. Image available as '$ALIAS'. Sample usage:"
echo "    lxc launch $ALIAS my-pi-container"
