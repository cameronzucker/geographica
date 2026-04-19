#!/bin/bash
# tools/build-tippecanoe.sh — Reproducibly build ARM64 Tippecanoe for release assets.
# Run this on a Pi or ARM64 VM. Output: ./tippecanoe-arm64 ready to upload.
set -euo pipefail

TIPPECANOE_VERSION="${TIPPECANOE_VERSION:-2.79.0}"
BUILD_DIR="${BUILD_DIR:-/tmp/tippecanoe-build}"
OUTPUT_DIR="${OUTPUT_DIR:-$(pwd)}"

# Verify we're on ARM64
ARCH="$(uname -m)"
if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "arm64" ]; then
    echo "ERROR: This script builds for aarch64/arm64. Current arch: $ARCH"
    exit 1
fi

# Install build dependencies
sudo apt update
sudo apt install -y build-essential libsqlite3-dev zlib1g-dev git

# Clone and build
rm -rf "$BUILD_DIR"
git clone --depth=1 --branch="$TIPPECANOE_VERSION" \
    https://github.com/felt/tippecanoe.git "$BUILD_DIR"
cd "$BUILD_DIR"
make -j"$(nproc)"

# Strip and install
strip tippecanoe
cp tippecanoe "$OUTPUT_DIR/tippecanoe-arm64"

# Also tar the secondary binaries so the release asset is complete.
tar -czf "$OUTPUT_DIR/tippecanoe-${TIPPECANOE_VERSION}-linux-${ARCH}.tar.gz" \
    tippecanoe tippecanoe-decode tile-join 2>/dev/null || true

echo "Built: $OUTPUT_DIR/tippecanoe-arm64 (v$TIPPECANOE_VERSION)"
if [ -f "$OUTPUT_DIR/tippecanoe-${TIPPECANOE_VERSION}-linux-${ARCH}.tar.gz" ]; then
    echo "Tarball: $OUTPUT_DIR/tippecanoe-${TIPPECANOE_VERSION}-linux-${ARCH}.tar.gz"
    sha256sum "$OUTPUT_DIR/tippecanoe-${TIPPECANOE_VERSION}-linux-${ARCH}.tar.gz"
fi
echo ""
echo "To cut a release:"
echo "  1. gh release create v<tag> $OUTPUT_DIR/tippecanoe-arm64"
echo "  2. Update the URL in bootstrap.sh's tippecanoe-install block"
