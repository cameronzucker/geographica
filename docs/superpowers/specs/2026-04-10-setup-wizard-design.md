# Setup Wizard

**Date:** 2026-04-10
**Status:** Draft
**Replaces:** Manual README steps 2-12

## Problem

README validation testing (2026-04-09, two independent runs) showed that deploying Geographica requires intermediate Linux skills: editing `.env` files, understanding bbox parameters, running 10+ sequential shell commands with consistent arguments, and waiting 6-12 hours for Nominatim with no progress indicator. The setup process has 12 steps, 5 of which involve error-prone manual configuration. Two critical README bugs were found, and the "skill level required" assessment concluded that a motivated amateur radio operator could do it but would need a full weekend.

A browser-based setup wizard can collapse the manual steps into a guided 5-step flow, reducing the required skill level to "can clone a git repo and run two commands."

## Quick Start (user experience)

```bash
git clone https://github.com/cdzucker/geographica.git
cd geographica
sudo ./bootstrap.sh
./setup
```

Then open http://localhost:8099 in a browser (VNC or SSH tunnel for headless Pi).

## Architecture

### Two Scripts

| Script | Runs as | What it does |
|--------|---------|-------------|
| `bootstrap.sh` | `sudo` | apt install, docker group, data directory, symlink. The ONLY script that requires root. |
| `setup` | User | Launches FastAPI wizard on `localhost:8099`. Handles everything else. |

### Security Model

- **`bootstrap.sh`** requires sudo and handles all privilege-escalated operations. It is a plain bash script with no network listeners, no web server, no user input beyond confirmation prompts. It runs and exits.
- **`./setup` wizard** binds to `127.0.0.1:8099` (localhost only). Not accessible from the LAN by default. No authentication needed because only local processes can reach it. The wizard runs user-level commands only — Docker (via group membership), pip, wget, file writes to user-owned directories.
- **No sudo in the wizard.** If the wizard discovers it needs something that requires root (e.g., missing apt package), it tells the user to run `bootstrap.sh` again and exits.
- **Auto-exit:** The wizard server exits after setup completes or after 30 minutes of inactivity.
- **Headless access:** Users accessing the Pi via SSH must use VNC or an SSH tunnel (`ssh -L 8099:localhost:8099 user@pi`). `bootstrap.sh` prints this guidance on completion.

### File Structure

```
bootstrap.sh                 # System prerequisites (sudo)
setup                        # Thin wrapper: creates venv, installs deps, starts wizard
setup/
├── main.py                  # FastAPI app: API routes, WebSocket progress, subprocess runner
├── static/
│   ├── index.html           # Single-page wizard app
│   ├── setup.js             # Wizard logic, WebSocket client, map picker
│   └── setup.css            # Dark-mode-aware styles (prefers-color-scheme)
└── requirements.txt         # fastapi, uvicorn, httpx (minimal)
```

### Technology

- **Backend:** Python + FastAPI (matches existing codebase). WebSocket for real-time progress streaming.
- **Frontend:** Vanilla HTML/JS/CSS (matches existing codebase — no build step). MapLibre GL JS for region picker (loaded from CDN during setup — internet is required anyway for data downloads).
- **Subprocess execution:** `asyncio.create_subprocess_exec` for all external commands. Output streamed line-by-line over WebSocket.

## The Five Wizard Steps

### Step 1: Network & System Configuration

**Auto-detected (user confirms or overrides):**

| Setting | Detection method | Override |
|---------|-----------------|----------|
| HOST_IP | Primary LAN interface IP (excludes docker0, lo) via `ip route get 1` | Text field |
| Total RAM | `/proc/meminfo` | — (display only) |
| Available disk | `shutil.disk_usage()` on data path | — (display only) |

**TLS configuration:**

| Option | What happens | When to use |
|--------|-------------|-------------|
| **HTTP only** (default) | No TLS. NGINX serves port 80 only. | LAN-only deployments, AREDN mesh |
| **Generate self-signed** | Wizard runs `generate_tls.sh`, NGINX serves on 443. Browser shows cert warning. | Quick HTTPS for testing, local development |
| **Use existing certificate** | User provides cert + key file paths, OR browses detected certs. Wizard validates PEM format. | User has a cert from a CA, corporate PKI, etc. |
| **External proxy / tunnel** | NGINX stays on HTTP. TLS is terminated by an external service. | Cloudflare Tunnel, Tailscale Funnel, reverse proxy |

**Certificate discovery:** The wizard scans common cert locations and presents any found certificates:
- `/etc/ssl/certs/` and `/etc/ssl/private/`
- `/etc/letsencrypt/live/*/`
- `/srv/geographica/tls/` and `/srv/geographica/tls/tailscale/`
- User-specified custom path

For each found cert, show: filename, subject CN, issuer, expiration date. User selects one or enters a custom path.

**ACME / CA polling (optional):** User can specify an ACME directory URL (e.g., Let's Encrypt, ZeroSSL, internal CA). Wizard uses a lightweight ACME client to request a cert for the configured hostname. This is how Tailscale's `tailscale cert` works under the hood — but generalized. If the user has Tailscale installed, the wizard can detect it and offer to run `provision_tailscale_tls.sh` automatically.

**"External proxy" option explained:** When the user selects this, the wizard explains: "Your reverse proxy (Cloudflare, Tailscale Funnel, etc.) handles TLS termination. NGINX will serve HTTP only. Your proxy forwards traffic to this Pi's HTTP port (8093). No certificate configuration needed here."

**RAM profile:**

The wizard detects total RAM and presents two profiles with explicit explanations of what changes and why:

| Setting | 16 GB profile | 8 GB profile | Impact of 8 GB |
|---------|--------------|-------------|----------------|
| Nominatim memory limit | 8 GB | 4 GB | Geocoding import takes ~2x longer |
| Nominatim shared_buffers | 1 GB | 512 MB | Slightly slower geocoding queries |
| Nominatim effective_cache_size | 4 GB | 2 GB | Less query plan optimization |
| Valhalla memory limit | 4 GB | 2 GB | Routing graph build slower |
| Valhalla threads | 4 | 2 | Fewer parallel routing calculations |
| TileServer memory limit | 1 GB | 512 MB | May slow tile serving under heavy load |
| STT (Whisper) memory limit | 1.5 GB | 768 MB | May fail on longer speech utterances |
| Pipeline memory limit | 2 GB | 1 GB | GeoTIFF conversion slower |
| Pipeline GDAL cache | 1024 MB | 256 MB | Slower raster processing |
| Imagery download concurrency | NAIP: 2, Sentinel: 3, direct: 5 | NAIP: 1, Sentinel: 1, direct: 3 | Downloads take longer (fewer parallel connections) |
| M2M batch size | 50 scenes | 20 scenes | More download rounds for same total data |
| Planetiler heap | `-Xmx8g` | `-Xmx4g` | Basemap tile generation ~2x slower |

The user sees this table with a clear header: "Your Pi has X GB RAM. Here's what we'll configure:" They can accept the auto-detected profile or switch between them.

**Storage selection:**

The wizard scans mounted filesystems and presents options:

```
Detected storage:
  ● /dev/sda2 (880 GB, 382 GB free) — /srv/geographica/data  [recommended]
  ○ /dev/sdb1 (2 TB, 1.8 TB free) — /mnt/external
  ○ //nas.local/maps (NFS, 4 TB free) — /mnt/nas
  ○ Custom path: [________________]
```

Detection: `psutil.disk_partitions()` or parsing `/proc/mounts`, filtered to real filesystems (excludes tmpfs, devtmpfs, proc, etc.). Shows device, total size, free space, and mount point.

Manual entry: user types a path. Wizard validates:
1. Path exists (or can be created)
2. Path is writable (creates a test file, then removes it)
3. Sufficient free space (warns if <50 GB, blocks if <20 GB)

If validation fails, show a clear error: "Cannot write to /mnt/nas — Permission denied. Check mount options or choose a different path." Does not proceed until storage is confirmed.

The wizard creates `/srv/geographica/data/` subdirectories on the chosen path and sets up the symlink.

### Step 2: Region & Data Configuration

Four data layers, each independently configurable. Presented in broadest-to-narrowest order.

**Map picker:** MapLibre GL JS map with a draggable rectangle for bbox selection. During setup, tiles come from an online source (OSM raster tiles or similar) since the local basemap isn't built yet. Internet is required for setup anyway (downloading data).

**Layer 1: Basemap** (green)
- Preset dropdown: Western US, Eastern US, Full US, individual states, custom
- Presets auto-fill the bbox rectangle on the map; user can adjust
- Shows estimates: OSM download size, basemap tile size, routing graph size, Nominatim DB size, download time, import time
- Includes: vector tiles, geocoding (Nominatim), routing (Valhalla), POI index, OSM POI extraction

**Layer 2: Base Imagery** (blue)
- Source selector: NAIP (0.6m, US only) | Sentinel-2 (10m, global) | Skip
- Zoom level slider (z10-z17) with size estimate that updates dynamically
- Independent bbox (defaults to basemap bbox, can be narrowed)
- Shows: estimated tile count, download size, download time

**Layer 3: Detail Imagery** (purple)
- Source selector: USGS M2M API | Copernicus | Skip
- Warning: "Requires API credentials (configured in next step)"
- Independent bbox (defaults to a smaller area)
- Shows: estimated size range (varies by scene availability)

**Layer 4: Elevation** (orange)
- Toggle: Download (z0-14) | Skip
- Coverage matches basemap bbox (not independently configurable)
- Shows: estimated size (~70 GB for Western US), download time
- Note: "Without elevation, 3D terrain and hillshade will be unavailable"

**Skip All option:**
- Amber warning box at bottom
- Explains: "Deploy the stack with no map data. The browser will show an empty canvas. Geocoding, routing, and spatial search will not function. GPS tracking and the admin panel will still work. You can download data later from the admin panel."
- Button: "Skip data setup →" advances directly to Step 5

**Running totals bar** at bottom: total disk space, total download time, total processing time — updates as user changes selections.

### Step 3: Credentials (conditional)

Only shown if Step 2 selected M2M or Copernicus imagery sources.

**M2M credentials:**
- Username + API token fields
- "Test connection" button: calls USGS M2M login endpoint, reports success/failure
- Link to USGS EarthExplorer registration page

**Copernicus credentials:**
- Client ID + Client Secret fields
- "Test connection" button: calls Copernicus OAuth token endpoint
- Link to Copernicus registration page

**Storage:** Writes to `/srv/geographica/data/credentials.json` (same file the admin panel uses). This is outside the git repo (gitignored via data/ symlink).

**Skip:** User can skip and add credentials later via the admin panel. If they selected M2M/Copernicus imagery in Step 2 but skip credentials here, imagery download is skipped with a note in the summary.

### Step 4: Download & Build

Sequential execution with real-time WebSocket progress streaming. Each substep shows:
- Current operation name
- Progress bar (bytes downloaded / total, or step N of M)
- ETA based on current throughput
- Live log output (collapsible)

**Substep sequence:**

1. **OSM data download** — wget from Geofabrik for each state in the region
2. **OSM merge** — `osmium merge` if multiple states (skip if single state)
3. **Copy PBF** to Nominatim and Valhalla data directories
4. **Planetiler basemap build** — Docker run with `-Xmx` set by RAM profile
5. **POI index build** — `python scripts/build_poi_index.py`
6. **OSM POI extraction** — `python scripts/build_osm_pois.py`
7. **Public lands build** — `python scripts/build_public_lands.py` (if basemap selected)
8. **Elevation download** — `python scripts/download_elevation.py` (if selected, checkpoint resume)
9. **Base imagery download** — `python scripts/acquire_naip.py` or `acquire_sentinel.py` (if selected)
10. **Detail imagery download** — `python scripts/acquire_imagery.py --mode m2m` (if selected + credentials)
11. **Fonts download** — wget from GitHub
12. **Vendor libraries** — wget from npm registry (direct download, no npm needed)
13. **Docker compose build** — builds GPS, search, STT service images

**Error handling:**
- If a substep fails: show error output, offer "Retry" or "Skip this step"
- Skipped steps are noted in the final summary
- Downloads with checkpoint resume (elevation, imagery) can be safely interrupted and restarted

**Pause/Resume:**
- "Pause" button stops the current download between checkpoint boundaries
- "Resume" continues from the last checkpoint
- Long-running downloads (elevation: 8-12 hours) benefit from this

### Step 5: Launch & Verify

1. Write `.env` with all configuration from Steps 1-3
2. `docker compose up -d`
3. Real-time health dashboard polling `docker compose ps` every 5 seconds
4. Service-by-service status with color-coded indicators (red → yellow → green)
5. Special handling for Nominatim: show "Importing OSM data — this takes several hours" with a note that other services are usable now (search works via POI database, routing works, map renders — only geocoding is unavailable until import completes)
6. Once all services are healthy (or Nominatim is still importing but everything else is green): "Setup complete! Open http://<HOST_IP>:8093 in your browser."
7. Wizard server exits

**Note on Nominatim dependency:** The wizard generates a docker-compose.override.yml that relaxes the Nominatim dependency from `service_healthy` to `service_started`, so the frontend and search start immediately. This was identified as a major UX issue in validation testing.

## UI Design

- **Max width:** 800px centered (prevents stretching on wide screens)
- **Dark mode:** Automatic via `prefers-color-scheme: dark` media query. Full dark palette, not just inverted colors.
- **Layer color coding:** Green (basemap), blue (base imagery), purple (detail imagery), orange (elevation) — consistent across steps
- **Typography:** System font stack (`-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`)
- **No external CSS frameworks.** Vanilla CSS matching the existing frontend pattern.

## bootstrap.sh

```bash
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
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
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
```

## ./setup wrapper

```bash
#!/bin/bash
set -e
cd "$(dirname "$0")"

# Check Docker is accessible
if ! docker info > /dev/null 2>&1; then
  echo "Docker is not accessible. You may need to:"
  echo "  1. Run: sudo ./bootstrap.sh"
  echo "  2. Log out and back in (for docker group to take effect)"
  exit 1
fi

# Create/reuse Python venv
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r setup/requirements.txt

echo ""
echo "Starting Geographica Setup Wizard..."
echo "Open http://localhost:8099 in your browser."
echo ""
echo "If accessing remotely via SSH, use:"
echo "  ssh -L 8099:localhost:8099 $(whoami)@$(ip route get 1 | awk '{print $7; exit}')"
echo ""

python3 -m uvicorn setup.main:app --host 127.0.0.1 --port 8099
```

## What This Replaces

| README Step | Wizard handles it? | How |
|-------------|-------------------|-----|
| Prerequisites (apt install) | `bootstrap.sh` | Automated |
| 1. Clone repo | User (manual) | Still `git clone` |
| 2. Data directory | `bootstrap.sh` | Automated |
| 3. Configure .env | Step 1 | Auto-detect + confirm |
| 4. Download OSM data | Step 4 | Automated with progress |
| 5. Generate basemap | Step 4 | Automated with progress |
| 6. Download elevation | Step 4 | Automated with progress (skippable) |
| 7. Build POI index | Step 4 | Automated |
| 7b. Extract OSM POIs | Step 4 | Automated |
| 8. Fonts + styles | Step 4 | Automated |
| 9. Vendor libraries | Step 4 | Automated (wget, no npm) |
| 10. GPS config | Not needed | GPS service auto-starts in no-fix mode |
| 11. Docker build + launch | Step 5 | Automated with health monitoring |
| 12. Verify deployment | Step 5 | Automated health checks |

## What This Does NOT Replace

- `git clone` — user still clones the repo manually
- Tailscale TLS setup — manual, documented separately
- GPS hardware configuration (gpsd socket override) — manual, optional
- Hailo NPU setup — future, requires hardware

## Testing

- Unit tests for config generation (.env output, RAM profile selection, bbox validation)
- Integration test: run wizard in LXD container (reuse existing validation harness)
- No Playwright tests for the wizard UI itself (vanilla JS, manual verification)
