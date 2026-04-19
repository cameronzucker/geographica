# tools/

Operator utilities for building and releasing Geographica dependencies.
These scripts are not part of the runtime stack — they are run manually by
maintainers when a new binary release is needed.

---

## build-tippecanoe.sh

Reproducibly compiles [Tippecanoe](https://github.com/felt/tippecanoe) for
ARM64 (aarch64) from source, producing a stripped binary and a tarball
suitable for upload to a GitHub release.

### When to use

Run this whenever you need to ship a new Tippecanoe version as a
Geographica release asset. `bootstrap.sh` downloads the binary from a
tagged release URL rather than building at setup time, so this script is
the upstream supplier for that artifact.

### Prerequisites

- A Raspberry Pi 5 (or any aarch64/arm64 Linux VM).
- `sudo` access for `apt install` (build deps: `build-essential`,
  `libsqlite3-dev`, `zlib1g-dev`, `git`).
- `gh` CLI authenticated to the `geographica` repo.

### Usage

```bash
# Default: build Tippecanoe 2.79.0 in /tmp, output to current directory
./tools/build-tippecanoe.sh

# Override version or output directory
TIPPECANOE_VERSION=2.80.0 OUTPUT_DIR=/tmp/release ./tools/build-tippecanoe.sh

# Verify the tag exists at https://github.com/felt/tippecanoe/tags before running — upstream does not pre-create future tags.
```

The script will:

1. Verify you are running on aarch64/arm64 (exits 1 otherwise).
2. Install build dependencies via `apt`.
3. Clone the exact tagged version from `https://github.com/felt/tippecanoe`.
4. Compile with all available cores (`make -j$(nproc)`).
5. Strip the binary and copy it to `./tippecanoe-arm64`.
6. Create a tarball `tippecanoe-<VERSION>-linux-aarch64.tar.gz` containing
   `tippecanoe`, `tippecanoe-decode`, and `tile-join`.
7. Print the SHA-256 checksum of the tarball.

### Cutting a release

After the build succeeds:

```bash
# 1. Create a GitHub release and upload both artifacts
gh release create v2.79.0 \
    ./tippecanoe-arm64 \
    ./tippecanoe-2.79.0-linux-aarch64.tar.gz \
    --title "Tippecanoe v2.79.0 (ARM64)" \
    --notes "Pre-built ARM64 Tippecanoe binary for Geographica bootstrap."

# 2. Copy the asset URL from the gh output, then update bootstrap.sh:
#    Look for the TIPPECANOE_RELEASE_URL variable and point it at the new tag.
```

After updating `bootstrap.sh`, open a PR so the new binary URL lands in
`main` before the next setup run.

### Verifying the binary

```bash
./tippecanoe-arm64 --version
# Expected output: tippecanoe v2.79.0
```

---

## Adding new tools

Drop scripts here with a short header comment explaining purpose and usage.
Update this README with a `##` section for each new tool.
