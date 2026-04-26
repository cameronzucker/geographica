# Setup

The fastest way to get Geographica running on a fresh Raspberry Pi 5. This document covers the wizard-driven install path that handles system configuration, data acquisition, credentials, and the stack itself end-to-end.

For the manual install (advanced users, recovery scenarios, AI agents needing a step-by-step reference), see [MANUAL_SETUP.md](MANUAL_SETUP.md).

## Before you start

| Component | Notes |
|---|---|
| Raspberry Pi 5 | 16 GB RAM recommended; 8 GB works for single-state coverage |
| Storage | 256 GB SSD minimum (single-state); 1 TB SSD recommended for multi-state |
| Network | Internet connection required during initial data acquisition only — Geographica runs fully offline after setup |
| Time | ~30 minutes of attended time + several hours of background data download |

For accounts needed during setup (USGS M2M, Copernicus), see [Step 3 — Credentials](#step-3--credentials).

## Step 1 — Bootstrap

Install system prerequisites (apt packages, Docker, docker group membership). Requires sudo.

```bash
git clone https://github.com/cameronzucker/geographica.git
cd geographica
sudo ./bootstrap.sh
```

After this completes, **log out and back in** so the docker group membership takes effect. Without this step, every subsequent command that calls Docker fails with a permission error.

## Step 2 — Launch the wizard

```bash
./setup.sh
```

This creates a Python virtual environment and starts the wizard server at `http://localhost:8099`. Open that URL in any browser on the Pi (or via SSH port-forward from a workstation).

<!-- TODO: Phase 5 Task 5.6 — gallery: wizard screenshot -->

## Step 3 — Walk the wizard

The wizard has 5 steps:

1. **Network & System** — set the TLS mode (HTTP, HTTPS with self-signed cert, or Tailscale), review the auto-detected RAM profile, and choose where imagery and tile data will be stored (drive + subpath). Defaults are auto-detected from the system.

2. **Region & Data** — pick a coverage region by preset or by typing a bounding box. Then choose which data layers to download:
   - **Basemap** — OSM vector tiles + geocoding + routing (Planetiler, Valhalla, Nominatim)
   - **Base imagery** — NAIP aerial (0.6 m, US only) or Sentinel-2 (10 m, global)
   - **Detail imagery** — high-resolution via USGS M2M API or Copernicus (requires credentials)
   - **Elevation** — terrain tiles z0-z14 from AWS Terrain Tiles (free, no account)

3. **Credentials** — paste API credentials for any credential-gated imagery sources selected in Step 2. Credentials are stored in the system keyring, never in plaintext files. See [Step 3 — Credentials](#credentials-detail) below if accounts don't exist yet.

4. **Download & Build** — the wizard runs preflight dependency checks, then kicks off the data pipeline. Progress streams step-by-step. This phase runs largely unattended and may take several hours depending on region size and chosen layers.

5. **Launch & Verify** — the wizard brings up the Docker Compose stack and shows per-service health status. A "Setup Complete" card appears when all 7 services reach healthy state.

<a name="credentials-detail"></a>
## Step 4 — Credentials

Some imagery sources require a free account. The wizard shows which sources need credentials and accepts them in Step 3. For the smoothest experience, sign up **before** starting the wizard:

- **USGS EarthExplorer account** (for USGS M2M API — high-resolution NAIP via the M2M API): free at <https://ers.cr.usgs.gov/register>
- **Copernicus Data Space account** (for Copernicus detail imagery): free at <https://dataspace.copernicus.eu/>

Skipping credential-gated sources is fine — the wizard falls back to unauthenticated sources. NAIP base imagery (no account, moderate resolution) and AWS elevation tiles (no account) alone produce a fully functional stack.

## Step 5 — Verify

After the wizard completes, the stack is accessible at `http://localhost:8093` (or on the Pi's LAN IP at the same port, or via Tailscale hostname if that TLS mode was chosen).

```bash
docker compose ps
```

Expected: 7 services in `Up (healthy)` state — `tileserver`, `valhalla`, `nominatim`, `gps`, `search`, `stt`, `frontend`.

Open `http://localhost:8093` in a browser. The map renders centered on the chosen coverage area with basemap tiles loading.

## Common issues

**Wizard says "docker not in PATH" or "permission denied running docker"** — the docker group membership hasn't applied because the session wasn't logged out and back in after `bootstrap.sh`. Log out, log back in, and retry `./setup.sh`.

**Preflight check fails for `rasterio` / `shapely` / `scipy` / `numpy`** — `bootstrap.sh` installs these to the system Python, not the wizard's virtual environment. The preflight check deliberately tests the system Python. If the check fails, rerun `sudo ./bootstrap.sh` and confirm it exits without errors.

**Download & Build hangs at the Planetiler step** — Planetiler is CPU-intensive; expect 30–60 minutes for a multi-state region on a Pi 5. The progress bar updates infrequently during this step. Check `docker compose logs -f` for activity or watch CPU usage.

**"bbox does not intersect any supported region"** — Geographica currently supports the 48 contiguous US states + DC for basemap and OSM-based layers. Adjust the bounding box in the wizard's Region step to fall within that area.

**Stack starts but the map is blank** — check `docker compose logs frontend` and `docker compose logs tileserver`. Most blank-map issues are missing tile data. Use the admin panel at `http://localhost:8097` to inspect data inventory, or rerun `./setup.sh` to resume the pipeline from the last checkpoint.

**Wizard 403 errors after restarting `setup.sh`** — the CSRF token survives restarts via a tmpfs file at `/run/geographica-setup/csrf-token`. If this path is unwritable (unusual), a fresh token is issued and any open browser tab must reload before POSTing again.

For additional troubleshooting, see [MANUAL_SETUP.md](MANUAL_SETUP.md#troubleshooting).

## When to use MANUAL_SETUP.md instead

The wizard covers ~95% of cases. The manual path is needed when:

- Importing BYO GeoTIFF imagery (data acquired outside the wizard)
- Specifying a custom bounding box that the wizard's preset list doesn't cover
- Reproducing the install on a second Pi (the wizard's saved state lives in keyring + `.env`; the manual path is more portable)
- Recovering from a partial install where the wizard cannot make forward progress
- Running Geographica without Docker (undocumented but referenced in the manual for AI agents that need a step-by-step grounding)
