# Geographica Companion — Data Ingestion Utility

**Date:** 2026-04-15 (revised after adversarial review)
**Scope:** Cross-platform (Windows/Linux) desktop tool for downloading and processing all Geographica data pipelines on a fast workstation, then transferring results to a Pi via rsync/SFTP over LAN.
**Repo:** Separate repository (`geographica-companion`), independent versioning.

## Problem

Processing imagery on the Pi 5 is slow — NOAA NAIP takes ~6 min/tile for download+reproject+convert, and gdaladdo took 5+ hours for 259K tiles. For serious deployments covering multiple large regions, this means weeks of continuous processing. A workstation with more cores, faster disk, and better network can do this 10-50x faster.

The Pi must remain fully capable of running all pipelines natively. The companion is an optional "fast path" for bulk data preparation.

## Architecture

```
WORKSTATION                                    PI 5 (LAN)
┌─────────────────────────────────┐           ┌─────────────────────────┐
│  geographica-companion/         │           │  Geographica Stack      │
│                                 │           │                         │
│  companion.py  (FastAPI :9000)  │           │  TileServer GL (:8090)  │
│  ├─ Bind 127.0.0.1 ONLY        │  ◄─tiles──│  ├─ basemap.mbtiles     │
│  ├─ CORS: localhost:9000 only   │           │  └─ vector tiles API    │
│  ├─ CSRF token on mutations     │           │                         │
│  ├─ Pipeline orchestration      │──rsync──► │  /srv/geographica/data/ │
│  ├─ Progress WebSocket          │  or SFTP  │  ├─ imagery_noaa.mbtiles│
│  ├─ Transfer (rsync/SFTP)       │  MBTiles  │  ├─ elevation.mbtiles   │
│  └─ GDAL subprocess mgmt       │           │  └─ ...                 │
│                                 │           │                         │
│  static/  (Browser UI)          │           │  tileserver_config.py   │
│  ├─ index.html                  │           │  └─ CLI: add/remove     │
│  ├─ companion.js                │           │     source entries      │
│  ├─ companion.css               │           └─────────────────────────┘
│  └─ MapLibre GL JS              │
│                                 │           CDN (fallback)
│  bin/  (Bundled GDAL)           │           ┌─────────────────────────┐
│  ├─ linux-x64/                  │  ◄─tiles──│  MapTiler / OSM tiles   │
│  │   └─ + shared libs, proj.db  │  (if Pi   │  (only if Pi basemap    │
│  └─ windows-x64/                │   offline)│   unreachable)          │
│      └─ + DLLs, proj.db         │           └─────────────────────────┘
│                                 │
│  pipelines/  (adapted scripts)  │
│  ├─ acquire_imagery.py          │
│  ├─ acquire_naip.py             │
│  ├─ download_elevation.py       │
│  ├─ pipeline_progress.py        │
│  ├─ build_county_index.py       │
│  └─ orchestrator.py (NEW)       │
│                                 │
│  output/  (configurable)        │
│  └─ *.mbtiles (ready to send)   │
└─────────────────────────────────┘
```

### Data Flow

1. **Connect** — User enters Pi hostname/IP. Companion fetches basemap tiles from Pi's TileServer (port 8090) for the minimap. No authentication required. Falls back to CDN tiles if Pi unreachable.
2. **Configure** — User draws bbox on the map, selects pipeline sources, enters API credentials when prompted (for sources that require them).
3. **Download** — Pipeline scripts fetch imagery/elevation to local output directory. Multiple pipelines run as parallel subprocesses.
4. **Convert** — Bundled GDAL reprojects and converts to MBTiles.
5. **Transfer** — User enters SSH credentials on the Transfer tab. SSH key auth uses rsync (fast, resumable). Password auth uses paramiko SFTP (programmatic, no TTY needed).
6. **Deploy** — SSH exec registers sources in TileServer config (container-internal paths) and restarts TileServer.

## Separate Repository

The companion lives in its own repository (`geographica-companion`), independent from the main Geographica repo.

### Rationale

- Clean distribution — users clone/download just the companion, not the full Geographica stack
- Independent versioning — companion releases don't need to track Pi releases
- Pipeline scripts can diverge for workstation use (parallel execution, higher concurrency, cross-platform fixes) without affecting the Pi's versions

### Pipeline Code Management

Pipeline scripts are copied from the main repo and adapted for workstation use. The companion versions share the same core logic (download, retry, checkpoint, GDAL conversion, MBTiles merge) but diverge on:

- Orchestration (parallel subprocesses vs sequential in-container)
- Concurrency limits (workstation has more resources)
- Output path handling (configurable vs hardcoded `/data/`)
- GDAL binary resolution (bundled vs system, PATH prepend)
- Platform compatibility (Windows process groups, no `nice`, no `/dev/stdout`, no `os.setsid`)
- Credential loading (CLI args/env vars, not `/secrets` tmpfs mount)
- Progress reporting (per-pipeline state files with unique names)

A `scripts/sync_pipelines.sh` in the companion repo lists each pipeline file's origin (e.g., `geographica/scripts/acquire_naip.py → pipelines/acquire_naip.py`) and summarizes the workstation-specific changes applied. This is documentation for manual sync, not an automated tool.

### Required Adaptations from Pi Scripts

These changes must be applied when copying pipeline scripts to the companion fork:

1. **Remove `os.setsid` / `os.killpg`** — replace with `subprocess.CREATE_NEW_PROCESS_GROUP` on Windows, `os.setsid` on Linux (platform-gated)
2. **Remove `nice -n 19`** — omit on Windows, optional on Linux
3. **Replace `/dev/stdout` in ogr2ogr** — use GDAL's `/vsistdout/` virtual filesystem (cross-platform)
4. **Remove `/secrets` path** — pass credentials via CLI args or env vars from orchestrator
5. **Remove `_cancel_requested` global** — not needed since pipelines run as subprocesses (orchestrator sends signals per-process)
6. **Remove `_child_pid` global** — same reason
7. **Remove signal handlers at module level** — orchestrator manages child process lifecycle
8. **Unique state file names** — use `.<pipeline_name>-state.json` to avoid collisions when multiple pipelines share an output directory
9. **Remove TileServer config imports** — companion doesn't interact with TileServer during processing
10. **Disable `tqdm` progress bars** — output goes to state files, not terminal

## Browser UI

Full browser interface at `http://127.0.0.1:9000`, using the Catppuccin Mocha theme to match the Pi's admin panel.

### Security

- **Bind `127.0.0.1` only** — never `0.0.0.0` or `localhost` (which may resolve to `::` on some systems)
- **CORS middleware** — restrict origins to `http://127.0.0.1:9000` only
- **CSRF token** — generated at startup, injected into served HTML, required on all state-changing API endpoints
- **Credential form fields** — `autocomplete="off"` and `autocomplete="new-password"` to prevent browser autofill/storage
- **SSH key auth recommended** — UI should recommend key-based auth as the primary method, with password as fallback

### Tab 1: Connect (Auth-Free)

Left panel:
- Pi hostname/IP text field
- "Connect" button — fetches basemap tiles from Pi's TileServer (port 8090)
- Connection status indicator (reachable / unreachable)
- CDN fallback button if Pi unreachable
- "Skip Map" option for text-only bbox entry

Right panel:
- MapLibre GL JS minimap with bbox drawing (click + drag)
- Basemap tiles sourced from Pi's TileServer (or CDN fallback)
- Editable bbox coordinate fields (west, south, east, north) synced with map
- Output directory selector with browse button

### Tab 2: Pipelines (Parallel Execution)

Top bar:
- GDAL threads control (default: CPU count)
- Download concurrency control (default: 4)

2-column card grid (same layout as Pi admin panel):
- **USGS Basemap** — z0-14, 256px tiles, FREE
- **NOAA NAIP** — z14-18, county mosaics with gdaladdo, FREE. Expandable config: state selector chips.
- **USGS M2M** — z15-19, high-res NAIP, API KEY required. Expandable config: credentials prompt.
- **Sentinel-2** — 10m multispectral, API KEY required. Expandable config: credentials prompt, date range.
- **Elevation** — z0-14, terrain-rgb, FREE
- **Import Custom** — GeoTIFF, JP2, MBTiles. Dashed border. File browser / drag-drop.

Each card:
- Click to expand configuration
- Estimate button (tile count, download size, ETA)
- Start / Cancel buttons
- Progress bar with percentage, bytes transferred, and cancel option
- Multiple pipelines can run simultaneously with independent progress

API credentials (M2M, Sentinel) are prompted inline when the user starts a pipeline that requires them. Credentials are used for that session only and never stored.

### Tab 3: Transfer (SSH Auth Here Only)

Left panel — SSH Authentication:
- Pi hostname/IP (pre-filled from Connect tab)
- SSH username field
- Auth method toggle: Password / SSH Key (key recommended)
- Password field (or key file browser)
- "Test Connection" button — verifies: SSH access, rsync availability (both ends), data dir writable, docker permissions, disk space on Pi
- Transfer method indicator: "rsync (key auth)" or "SFTP (password auth)"
- Clear note: "Credentials are used for this transfer only and not stored."

Right panel — File List:
- List of MBTiles files in output directory with sizes
- Total size + available space on Pi
- "Transfer All" button

Transfer process:
1. SSH key auth → rsync each file with per-file byte-level progress
2. Password auth → paramiko SFTP each file with per-file byte-level progress callback
3. After all files transferred, SSH exec deployment commands

Bottom section — Manual Fallback:
- Copyable rsync command
- Copyable SSH deploy command

### Tab 4: Status

- Active downloads/conversions per pipeline
- Disk usage (output directory + estimated Pi usage)
- Completed files ready for transfer
- Scrolling log viewer (tail of pipeline output)

## Pipeline Orchestration

### orchestrator.py (NEW)

Central coordinator for parallel pipeline execution. Each pipeline runs as a **separate subprocess** (not in-process), which avoids global state conflicts, signal handler collisions, and module-level side effects.

- Launches each pipeline as `python pipelines/<script>.py --bbox ... --output ... --staging ...`
- Manages child PIDs — cancel sends `SIGTERM` (Linux) or `TerminateProcess` (Windows) per-process
- Each pipeline writes its own uniquely-named JSON state file (e.g., `.noaa-state.json`, `.basemap-state.json`)
- FastAPI backend polls all state files for the UI
- Sets environment for child processes: `PATH` (prepend GDAL bin dir), `PROJ_LIB`, `GDAL_DATA`, `GDAL_NUM_THREADS`
- Download concurrency configurable per-pipeline via CLI args

### Why Subprocesses (Not In-Process)

The Pi pipeline scripts use module-level globals (`_cancel_requested`, `_child_pid`) and register `SIGTERM` handlers at import time. Running multiple pipelines in a single Python process would cause:
- Signal handler collisions (last import wins)
- Shared cancellation state (cancel one = cancel all)
- Child PID tracking races

Subprocesses provide natural isolation with no refactoring of the core pipeline logic.

### Script Adaptations

Changes from the Pi versions:

- **GDAL path:** Orchestrator prepends `bin/{platform}/` to child process `PATH` env var. Scripts invoke GDAL tools by bare name as before — PATH resolution handles it.
- **GDAL environment:** Orchestrator sets `PROJ_LIB` and `GDAL_DATA` pointing to bundled data files.
- **Output directory:** Always passed via `--output` CLI arg, not hardcoded to `/data/`.
- **Staging directory:** Always passed via `--staging` CLI arg, not defaulting to `/data/staging_*`.
- **No Docker:** Scripts run as direct subprocesses.
- **No TileServer interaction:** TileServer config imports removed/guarded.
- **No `/secrets` path:** Credentials passed via CLI args or env vars.
- **Platform compatibility:** POSIX-specific code gated behind `sys.platform` checks.

## Transfer & Deployment

### Transfer Method Selection

The companion auto-detects the best transfer method during "Test Connection":

| Auth Method | Transfer | Progress | Resume |
|-------------|----------|----------|--------|
| SSH Key | rsync `-avP` | Byte-level (stdout parsing) | Yes (--partial) |
| Password | paramiko SFTP | Byte-level (callback) | No |

**SSH key auth is recommended in the UI** because it enables rsync (faster, resumable). Password auth falls back to paramiko SFTP, which provides equivalent progress reporting but no resume capability.

### Rsync (SSH Key Auth)

Uses `subprocess.Popen` to invoke rsync with `-avP` flags. Key path passed via `RSYNC_RSH="ssh -i /path/to/key"`. Progress parsed from stdout for the UI.

Requires rsync installed on both workstation and Pi. The "Test Connection" step verifies this.

### Paramiko SFTP (Password Auth)

Pure-Python SFTP transfer via paramiko. Password passed programmatically — no TTY required (unlike rsync over SSH, which needs `/dev/tty` for password prompts and would hang in a headless FastAPI process).

Uses `SFTPClient.putfo()` with a progress callback for byte-level progress reporting.

### Pre-Transfer Checks

"Test Connection" verifies all of:
1. SSH access with provided credentials
2. Rsync availability on both ends (if key auth)
3. `/srv/geographica/data/` exists and is writable by SSH user
4. SSH user is in `docker` group (can run `docker compose`)
5. Available disk space on Pi (`df` output parsed)
6. Geographica repo path discoverable (from TileServer container mount config)

### Post-Transfer Deployment

After all files land on the Pi:

1. SSH exec: `cd <repo_path> && python3 scripts/tileserver_config.py add <source_name> /srv/data/<filename>`
   - Source name derived from filename: strip `.mbtiles` extension (e.g., `imagery_noaa.mbtiles` → `imagery_noaa`)
   - Path uses **container-internal** mount path (`/srv/data/`), not host path (`/srv/geographica/data/`)
   - If source name already exists in config, skip with a warning
2. SSH exec: `cd <repo_path> && docker compose restart tileserver`
3. Show completion summary with note about brief TileServer downtime during restart

**Prerequisite:** `tileserver_config.py` in the main Geographica repo must have a CLI entry point added (`if __name__ == "__main__"` with argparse). This is a small change that benefits both projects.

### Repo Path Discovery

The companion discovers the Geographica repo path on the Pi by:
1. `docker inspect` the tileserver container to find the bind mount source for `/srv/data`
2. The bind mount source (e.g., `/home/administrator/Code/geographica/data`) → parent is the repo root
3. Fallback: user-editable field in Transfer tab, defaulting to `/home/administrator/Code/geographica`

### deploy.sh (Manual Fallback)

Generated alongside output files with `set -euo pipefail`. Accepts repo path as argument:

```bash
#!/bin/bash
set -euo pipefail
# Generated by Geographica Companion
REPO_DIR="${1:-/home/administrator/Code/geographica}"
DATA_DIR="/srv/geographica/data"

for f in *.mbtiles; do
  name="${f%.mbtiles}"
  echo "Registering $name..."
  python3 "$REPO_DIR/scripts/tileserver_config.py" add "$name" "/srv/data/$f"
done

cd "$REPO_DIR" && docker compose restart tileserver
echo "Done. TileServer restarted with new sources."
```

Note: this script assumes files are already in `$DATA_DIR` (transferred via rsync/SCP). It only does registration + restart.

## Bundled GDAL

### Strategy

Pre-compiled GDAL tools bundled per platform:

- `bin/linux-x64/` — extracted from Ubuntu/Debian GDAL packages (executables + shared libs + proj.db + GDAL_DATA files)
- `bin/windows-x64/` — extracted from GISInternals or conda-forge builds (executables + DLLs + proj.db + GDAL_DATA)

Required binaries: `gdalwarp`, `gdal_translate`, `gdaladdo`, `gdalbuildvrt`, `ogr2ogr`

### Environment Setup

The launcher and orchestrator must set these environment variables for GDAL to work with bundled binaries:

**Linux (`companion.sh`):**
```bash
export PATH="$COMPANION_DIR/bin/linux-x64:$PATH"
export PROJ_LIB="$COMPANION_DIR/bin/linux-x64/share/proj"
export GDAL_DATA="$COMPANION_DIR/bin/linux-x64/share/gdal"
```

**Windows (`companion.bat`):**
```bat
set PATH=%COMPANION_DIR%\bin\windows-x64;%PATH%
set PROJ_LIB=%COMPANION_DIR%\bin\windows-x64\share\proj
set GDAL_DATA=%COMPANION_DIR%\bin\windows-x64\share\gdal
```

The orchestrator passes these same env vars to child subprocess `env` dicts.

### Resolution Order

1. Check `GDAL_BIN_DIR` env var (user override)
2. Check bundled `bin/{platform}/` directory
3. Fall back to system PATH
4. Error with platform-specific install instructions if nothing found

### Fallback Plan

If bundling raw GDAL binaries proves too painful (DLL hell on Windows, proj.db paths, shared lib versioning), we can fall back to requiring system GDAL on PATH. The companion would show clear install instructions per platform. This is a reasonable compromise for v1 given the small user base.

## Credential Handling

**No credentials are stored.** All credentials are prompted per-session:

- **SSH (Transfer tab):** Password or key file provided in the browser form. Password passed programmatically to paramiko (never hits a terminal). Form fields have `autocomplete="off"` to prevent browser storage.
- **M2M / Sentinel (Pipelines tab):** API credentials prompted inline when user starts a pipeline that requires them. Passed to pipeline subprocess via env vars (not CLI args, to avoid `ps` exposure).
- **Pi TileServer (Connect tab):** No authentication required — tile access is unauthenticated.

## Packaging & Distribution

### Directory Structure

```
geographica-companion/
├── companion.py          # Entry point (FastAPI + browser launch)
├── companion.sh          # Linux launcher
├── companion.bat         # Windows launcher
├── companion.desktop     # Linux desktop entry (launches in terminal)
├── requirements.txt      # Python deps
├── pipelines/            # Adapted pipeline scripts
│   ├── acquire_imagery.py
│   ├── acquire_naip.py
│   ├── acquire_sentinel.py
│   ├── download_elevation.py
│   ├── import_imagery.py
│   ├── pipeline_progress.py
│   ├── build_county_index.py
│   └── orchestrator.py   # NEW — parallel pipeline coordinator
├── static/               # Browser UI
│   ├── index.html
│   ├── companion.js
│   └── companion.css
├── bin/                  # Bundled GDAL
│   ├── linux-x64/
│   │   ├── gdalwarp, gdal_translate, ...
│   │   ├── lib/          # Shared libraries
│   │   └── share/        # proj.db, GDAL_DATA
│   └── windows-x64/
│       ├── gdalwarp.exe, gdal_translate.exe, ...
│       ├── *.dll         # GDAL, PROJ, GEOS, etc.
│       └── share/        # proj.db, GDAL_DATA
├── scripts/              # Build/maintenance scripts
│   └── sync_pipelines.sh # Documents pipeline code provenance
└── geographica-data/     # Default output dir (created on first run)
```

### Prerequisites

- Python 3.10+ (pre-installed on most Linux; downloadable for Windows)
- No Docker required
- No GDAL install required (bundled, with system PATH fallback)

### First Run — Linux

1. `chmod +x companion.sh && ./companion.sh` (or use the `.desktop` file)
2. Launcher checks Python 3.10+ via `python3 --version`
3. Creates venv, installs pip deps
4. Checks for bundled GDAL, warns if missing and no system GDAL on PATH
5. Sets `PATH`, `PROJ_LIB`, `GDAL_DATA` env vars
6. Starts FastAPI server bound to `127.0.0.1:9000`
7. Opens default browser via `xdg-open`

Note: double-clicking `.sh` files does not reliably launch them on Linux desktops. The README documents `chmod +x && ./companion.sh` as the primary method. The `.desktop` file provides a double-click option for GNOME/KDE.

### First Run — Windows

1. Double-click `companion.bat`
2. Launcher checks `py -3 --version` (Windows Python Launcher), falls back to `python --version`, validates 3.10+
3. Reports clear error with python.org download link if not found
4. Creates venv (using `Scripts\activate.bat`, not `bin/activate`)
5. Installs pip deps
6. Sets `PATH`, `PROJ_LIB`, `GDAL_DATA` env vars
7. Starts FastAPI server bound to `127.0.0.1:9000`
8. Opens browser via `start http://127.0.0.1:9000`

### Python Dependencies

```
fastapi
uvicorn
paramiko          # SFTP transfer (password auth)
aiohttp           # Pipeline HTTP downloads
aiofiles          # Async file I/O
aiosqlite         # MBTiles SQLite operations
tqdm              # Pipeline progress (disabled in companion, but imported)
shapely           # Spatial operations
```

MapLibre GL JS is vendored in `static/` (no CDN dependency at runtime).

## Scope Boundaries

### In Scope

- All imagery pipelines (USGS basemap, NOAA NAIP, M2M, Sentinel-2, National Map, custom import)
- Elevation pipeline
- Parallel pipeline execution (subprocesses)
- Rsync (key auth) / SFTP (password auth) transfer to Pi over LAN
- Post-transfer TileServer deployment (source registration + restart)
- Bundled GDAL binaries (Linux + Windows)
- Disk space pre-flight checks (workstation + Pi)
- CLI entry point for `tileserver_config.py` (in main repo, prerequisite)

### Out of Scope

- Running any Geographica services (no TileServer, Valhalla, Nominatim)
- Vector basemap generation (Planetiler requires separate setup)
- POI index building (requires OSM PBF, done on Pi)
- Valhalla routing data (built from OSM PBF on Pi)
- Nominatim geocoding data (imported from OSM PBF on Pi)
- Map viewing or navigation (companion only produces data)
- Credential storage of any kind
- Transfer over AREDN mesh (LAN only — mesh transfer would be inconsiderate to other operators)
- macOS support (system GDAL via Homebrew works as an undocumented fallback)

## Future Enhancements (Not in v1)

- **Auto-discovery:** Detect Pi on local network via mDNS/Bonjour
- **Bidirectional sync:** Download inventory from Pi, show what's already transferred
- **Resume transfer:** Track which files have been transferred, skip duplicates
- **PyInstaller packaging:** Single .exe for Windows, single binary for Linux
- **Valhalla + Nominatim data:** Download pre-built extracts from Geofabrik
- **macOS GDAL bundles:** `bin/darwin-arm64/` and `bin/darwin-x64/`
- **Atomic transfer:** rsync to staging path, `mv` into place before TileServer registration
