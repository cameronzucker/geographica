# Geographica

Offline-first mapping platform for field operations on disconnected networks.
Runs a complete GIS stack on a Raspberry Pi 5 — vector basemaps, aerial imagery,
terrain, routing, geocoding, GPS tracking, and search — with zero cloud dependency
after initial data acquisition.

Built for [AREDN](https://www.arednmesh.org/) mesh networks, but works on any
isolated LAN or standalone device.

## Features

- **Vector basemaps** with three themes (Positron light, Dark Matter dark, Hybrid imagery+roads) and house number labels
- **Aerial imagery** overlay — USGS NAIP (0.6m, US) via M2M API or tile scraper. Sentinel-2 pipeline code exists but is untested. Per-source toggles and opacity slider.
- **Public lands layer** — BLM, National Forest, National Park, Fish & Wildlife, Military, Bureau of Reclamation, Tribal, State Trust, and Wilderness boundaries with agency-colored fills and legend. Tribal boundaries rendered with diagonal stripe pattern.
- **3D terrain** with hillshade and adjustable exaggeration slider (z0-14 elevation data)
- **Free-look camera** for 3D terrain exploration (pitch/bearing control)
- **Turn-by-turn navigation** with voice guidance, off-route detection, and dead reckoning
- **Multi-stop waypoint routing** with map click point selection for car, bicycle, and pedestrian
- **Natural language spatial search** — "nearest gas station", "hospitals near me", "gas stations along my route", "fuel every 50 miles", "gas stations in Flagstaff", "restaurants in Phoenix along my route" with distance-ranked results, numbered map pins, and city-aware geocoding
- **Voice search (STT)** — push-to-hold mic button for hands-free spatial queries via Whisper (base.en, CPU). Say "gas stations near me" and get results. Requires HTTPS.
- **OSM POI search** — commercial amenities (fuel, food, lodging, pharmacy, grocery) and public land boundaries (BLM, USFS, NPS) extracted from OSM data. Fills the rural coverage gap where GNIS-only data returned no commercial results.
- **Geocoding** — search for addresses, cities, landmarks
- **POI search** — GNIS gazetteer with full-text search (data sourced from S3: `prd-tnm.s3.amazonaws.com`)
- **Live GPS** — hardware GPS streaming over WebSocket with accuracy circle display
- **KML/KMZ import** — drag-and-drop file overlay with layer management panel and IndexedDB session persistence
- **Coordinate display** — Maidenhead grid locator and MGRS in addition to lat/lon
- **Imperial and metric units** — switchable distance/elevation units
- **Draw-on-map bounding box selection** for imagery downloads
- **Admin config panel** (localhost-only, separated from main app) with 3-tab layout: Dashboard (service health with color-coded status dots, disk/TLS info), Pipelines (imagery with MapLibre minimap bbox selection, elevation, OSM POI extraction, Sentinel-2, NAIP), Settings (M2M + Copernicus credentials, TLS config, STT status)
- **Pipeline management** — start/cancel imagery (direct + M2M), NAIP, Sentinel-2, elevation, public lands, and OSM POI extraction from the browser with phase-aware progress tracking
- **Print/export directions** (Mapquest-style printable page)
- **ATAK integration** — serves as a WMS map source for TAK clients
- **TLS support** — three modes: HTTP, HTTPS (self-signed), or Tailscale (Let's Encrypt)
- **No build step** — vanilla JS + MapLibre GL JS frontend, no bundler required

## Hardware requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Board | Raspberry Pi 5, 8 GB | Raspberry Pi 5, 16 GB |
| Storage | 256 GB SSD (single-state coverage) | 1 TB SSD (multi-state coverage) |
| GPS | — | Any gpsd-compatible receiver: Waveshare LC29H HAT, USB GPS dongle (u-blox, BU-353S4), etc. |
| NPU | — | Hailo 10H (for future NPU-accelerated STT) |

**Tested on:** Pi 5 16 GB, Debian Trixie (bookworm also works), Intel D3-S4610
896 GB SATA SSD.

**Storage budget** (Western US, 11 states):

| Dataset | Size |
|---------|------|
| Vector basemap (OpenMapTiles via Planetiler) | ~2.4 GB |
| Elevation tiles (zoom 0-14) | ~70-120 GB |
| Aerial imagery — scraper z0-z14 (USGS tile cache) | ~25 GB |
| Aerial imagery — NAIP z15-z19 (USGS M2M, per region) | ~30-270 GB |
| Public lands (PAD-US + Census AIANNH tribal) | ~0.4 GB |
| OSM extracts (merged PBF) | ~3.1 GB |
| Valhalla routing graph | ~4.3 GB |
| Nominatim geocoding DB | ~30-40 GB |
| POI index (GNIS + OSM) | ~80 MB |
| **Total** | **~170-470 GB** |

Imagery size varies by region and max zoom. z0-z14 scraper covers the full
region at ~25 GB. Each additional zoom level roughly quadruples tile count.
Arizona at z16 adds ~23 GB, at z17 adds ~91 GB. NAIP GeoTIFFs are downloaded
in batches and deleted after conversion — staging requires ~15 GB temporary.

POI index includes GNIS geographic features + OSM commercial amenities + public land boundaries.

## Architecture

```
Browser ──> NGINX (:8093) ──┬──> TileServer GL (:8090)   vector/raster/elevation tiles
                            ├──> Valhalla (:8094)         routing engine
                            ├──> Nominatim (:8092)        geocoding (PostgreSQL)
                            ├──> Search (:8096)           spatial search + admin API
                            ├──> STT (:8098)              speech-to-text (Whisper)
                            └──> GPS (:8095)              WebSocket GPS relay

Config ──> NGINX (:8097) ──┬──> Search (:8096)           pipeline mgmt (localhost only)
                          ├──> TileServer GL (:8090)   minimap tile proxy
                          └──> /vendor/                MapLibre GL JS/CSS

Pipeline container (on-demand) ──> acquire_imagery.py     imagery downloads (direct + M2M)
                               ──> build_osm_pois.py      OSM POI extraction
                               ──> download_elevation.py   elevation tile downloads
```

Seven persistent Docker Compose services plus an on-demand pipeline container,
with per-container memory limits to prevent OOM on constrained hardware. NGINX
reverse-proxies all services behind a single port with URL rewriting for
TileServer GL style/TileJSON endpoints.

---

## Quick Start

For a guided setup experience, use the setup wizard:

```bash
git clone https://github.com/cdzucker/geographica.git
cd geographica
sudo ./bootstrap.sh    # Install system prerequisites
# Log out and back in so the docker group takes effect, then:
./setup.sh             # Launch browser-based setup wizard
```

Then open http://localhost:8099 in your browser. The wizard will guide you through
region selection, data downloads, and stack deployment.

> **Headless access:** If accessing the Pi remotely via SSH, use a VNC session
> or SSH tunnel: `ssh -L 8099:localhost:8099 user@your-pi-ip`, then open
> http://localhost:8099 locally.

The manual setup steps below are still available for advanced users or automation.

---

## Manual setup guide

This guide walks through a complete deployment from a fresh Pi. The process has
two phases: **data acquisition** (requires internet, takes several hours) and
**stack deployment** (runs offline from then on).

### Prerequisites

```bash
sudo apt update
sudo apt install -y \
  docker.io docker-compose \
  python3 python3-venv python3-pip \
  gdal-bin osmium-tool \
  gpsd gpsd-clients \
  git wget curl unzip
```

Add your user to the `docker` group:

```bash
sudo usermod -aG docker $USER
# Log out and back in for this to take effect
```

Verify Docker is working:

```bash
docker run --rm hello-world
docker compose version   # needs v2.x+
```

### 1. Clone the repo

```bash
git clone https://github.com/cdzucker/geographica.git
cd geographica
```

### 2. Create the data directory

Data files are large (150+ GB) and live outside the git repo. Create a directory
on your SSD and symlink it:

```bash
sudo mkdir -p /srv/geographica/data/{pbf,nominatim,valhalla}
sudo chown -R $USER:$USER /srv/geographica
ln -s /srv/geographica/data data
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set `HOST_IP` to your Pi's primary LAN IP address — the one
other devices on your network use to reach it. Find it with:

```bash
ip -4 addr show | grep 'inet ' | grep -v '127.0.0.1\|docker' | awk '{print $2}' | cut -d/ -f1
```

Use this IP, not `localhost`, `127.0.0.1`, or a Docker bridge address
(172.x.x.x). The defaults are tuned for a 16 GB Pi 5. For 8 GB, reduce
the PostgreSQL memory settings:

```bash
# .env adjustments for 8 GB RAM
POSTGRES_SHARED_BUFFERS=512MB
POSTGRES_MAINTENANCE_WORK_MEM=512MB
POSTGRES_EFFECTIVE_CACHE_SIZE=2GB
```

### 4. Download OSM data

Download state-level extracts from [Geofabrik](https://download.geofabrik.de/north-america/us.html)
for your coverage area. Example for the Western US:

```bash
cd /srv/geographica/data/pbf

for state in arizona california colorado idaho montana nevada \
             new-mexico oregon utah washington wyoming; do
  wget "https://download.geofabrik.de/north-america/us/${state}-latest.osm.pbf"
done
```

Merge into a single file:

```bash
osmium merge *-latest.osm.pbf -o western-us.osm.pbf
```

Copy to the service data directories:

```bash
cp western-us.osm.pbf /srv/geographica/data/nominatim/region.osm.pbf
cp western-us.osm.pbf /srv/geographica/data/valhalla/
cd -
```

### 5. Generate vector basemap tiles

The vector basemap is generated from the merged PBF using
[Planetiler](https://github.com/onthegomap/planetiler) with the OpenMapTiles
profile. Planetiler downloads required source data (Natural Earth, water
polygons) automatically.

Generate tiles (1-3 hours on a Pi 5 depending on coverage area):

```bash
docker run --rm \
  -e JAVA_TOOL_OPTIONS="-Xmx8g" \
  -v /srv/geographica/data/pbf:/pbf \
  -v $(pwd)/tileserver:/data \
  ghcr.io/onthegomap/planetiler:0.10.2 \
  --download \
  --osm-path=/pbf/western-us.osm.pbf \
  --output=/data/southwest5.mbtiles \
  --force
```

### 6. Download elevation tiles

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt

python scripts/download_elevation.py \
  --bbox "-124.8,31.3,-102.0,49.0" \
  --zoom 0-14 \
  --output /srv/geographica/data/elevation.mbtiles
```

Downloads Terrain-RGB tiles from AWS (free, no API key). ~70 GB for the Western
US at zoom 0-14. The script supports checkpoint resume — if interrupted, re-run
the same command.

### 7. Build the POI search index

```bash
python scripts/build_poi_index.py \
  --bbox "-124.8,31.3,-102.0,49.0" \
  --states "AZ,CA,CO,ID,MT,NV,NM,OR,UT,WA,WY" \
  --output /srv/geographica/data/poi.sqlite
```

Downloads GNIS gazetteer data from USGS via S3
(`prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/`).
Free, no API key required. Produces a small SQLite FTS5 database.

### 7b. Extract OSM amenities and public land boundaries

```bash
python scripts/build_osm_pois.py \
  --pbf /srv/geographica/data/valhalla/western-us.osm.pbf \
  --output /srv/geographica/data/poi.sqlite \
  --bbox "-124.8,31.3,-102.0,49.0"
```

Extracts named amenities (fuel, food, lodging, etc.) and public land boundaries
(BLM, USFS, NPS) from the OSM PBF into the same SQLite database. Requires
`osmium` and `shapely` (`pip install shapely`). Takes ~10 minutes.

### 7c. Build public lands vector tiles (optional)

Requires Tippecanoe (built from source on ARM64) and GDAL:

```bash
# Install Tippecanoe (if not already installed)
sudo apt install -y build-essential libsqlite3-dev zlib1g-dev
git clone https://github.com/felt/tippecanoe.git /tmp/tippecanoe
cd /tmp/tippecanoe && make -j4 && sudo make install

# Build public lands tiles (downloads PAD-US ~1.5 GB, requires CAPTCHA in browser)
# First: download PAD-US GeoPackage manually from
#   https://www.sciencebase.gov/catalog/item/652d4fc5d34e44db0e2ee45e
# Save as /srv/geographica/data/padus_cache/padus.zip

# Then run the pipeline (stop Docker services first on 8 GB Pi):
python scripts/build_public_lands.py \
  --output /srv/geographica/data/public-lands.mbtiles \
  --cache-dir /srv/geographica/data/padus_cache/
```

Generates ~400 MB of vector tiles covering BLM, National Forest, National Park,
Fish & Wildlife, Military, Bureau of Reclamation, Tribal (from Census AIANNH),
State Trust, and Wilderness boundaries. The pipeline runs on the **host** (not
Docker) because Tippecanoe is a compiled binary. Needs ~6-9 GB free RAM for
the full Western US; on 8 GB Pi 5, stop Docker services first.

### 8. Set up TileServer GL styles and fonts

**Fonts** (PBF glyph ranges for map label rendering):

```bash
wget -O /tmp/fonts.zip https://github.com/openmaptiles/fonts/releases/download/v2.0/v2.0.zip
unzip -q /tmp/fonts.zip -d tileserver/fonts-served
rm /tmp/fonts.zip
```

**Styles** — Style files (`style.local.json`) and sprite assets are checked into
the repo. Icon directories are needed from the upstream OpenMapTiles style repos:

```bash
cd tileserver/styles

# Positron — icons only (sprites are already in the repo)
git clone --depth 1 https://github.com/openmaptiles/positron-gl-style.git positron-tmp
cp -r positron-tmp/icons positron/
rm -rf positron-tmp

# Dark Matter — icons only (sprites are already in the repo)
git clone --depth 1 https://github.com/openmaptiles/dark-matter-gl-style.git darkmatter-tmp
cp -r darkmatter-tmp/icons darkmatter/
rm -rf darkmatter-tmp

cd ../..
```

### 9. Frontend vendor libraries

Vendor libraries (MapLibre GL JS, togeojson, jszip, DOMPurify) are committed to
the repo in `frontend/vendor/`. No installation step is needed.

> **Note:** If you need to update vendor library versions, download the new
> tarballs directly from the npm registry and extract the dist files:
> ```bash
> cd frontend/vendor
> wget https://registry.npmjs.org/maplibre-gl/-/maplibre-gl-5.21.1.tgz
> tar -xf maplibre-gl-5.21.1.tgz
> cp package/dist/maplibre-gl.js . && cp package/dist/maplibre-gl.css .
> rm -rf package maplibre-gl-5.21.1.tgz
> cd ../..
> ```

### 10. Configure GPS (optional)

If you have a GPS HAT or USB GPS receiver:

```bash
sudo systemctl enable gpsd
sudo systemctl start gpsd

# Verify fix (outdoors or near a window)
gpsmon
```

**Important:** gpsd must listen on TCP `0.0.0.0:2947` for the Docker GPS service
to connect. By default, gpsd only listens on localhost. Create a systemd socket
override:

```bash
sudo systemctl edit gpsd.socket
```

Add the following content:

```ini
[Socket]
ListenStream=
ListenStream=0.0.0.0:2947
```

Then restart the socket:

```bash
sudo systemctl restart gpsd.socket gpsd
```

The GPS service connects to gpsd on the host via `host.docker.internal:2947`.
If you don't have GPS hardware, the service starts cleanly and reports no-fix
status — it won't block the rest of the stack.

### 11. Launch the stack

```bash
docker compose build    # build gps, search, and stt service images
docker compose --profile pipeline build  # also build pipeline image (for admin panel downloads)
docker compose up -d    # start all 7 services
```

**First-run processing times** (Pi 5, 16 GB, Western US 11 states):

| Service | Task | Duration |
|---------|------|----------|
| Valhalla | Build routing graph from PBF | 1-2 hours |
| Nominatim | Import OSM data into PostgreSQL | 6-12 hours |

All other services (TileServer, GPS, frontend) start immediately. The search
service waits for Nominatim to complete before starting.

Monitor progress:

```bash
docker compose logs -f valhalla     # watch routing graph build
docker compose logs -f nominatim    # watch geocoding import (rank 30 is the final stage)
docker compose ps                   # check health status
```

> **Memory limits:** The stack has per-container memory limits to prevent
> system-wide OOM on 16 GB hardware: Nominatim 8 GB, Valhalla 4 GB,
> Pipeline 2 GB, STT 1.5 GB, TileServer 1 GB, Search 256 MB, GPS 128 MB,
> Frontend 128 MB (~17 GB total ceiling, but pipeline is on-demand).
> If a container exceeds its limit, Docker restarts just that container —
> the system stays up.

### 12. Verify the deployment

Once all services show healthy in `docker compose ps`:

```bash
# Tile serving
curl -s http://localhost:8090/health

# Geocoding
curl -s "http://localhost:8092/search?q=Phoenix&format=json" | python3 -m json.tool | head -20

# Routing
curl -s -X POST http://localhost:8094/route \
  -H "Content-Type: application/json" \
  -d '{"locations":[{"lat":33.45,"lon":-112.07},{"lat":34.05,"lon":-111.09}],"costing":"auto"}' \
  | python3 -m json.tool | head -20

# Unified search
curl -s "http://localhost:8096/search?q=Grand+Canyon" | python3 -m json.tool | head -20

# Speech-to-text
curl -s http://localhost:8093/stt/health | python3 -m json.tool
```

Open a browser to **http://&lt;your-pi-ip&gt;:8093** to use the map.

---

## Stack management

```bash
docker compose up -d       # start
docker compose down        # stop
docker compose ps          # health check
docker compose logs -f     # tail all logs
docker compose restart X   # restart one service

# Rebuild after code changes to gps, search, or stt
docker compose build && docker compose up -d

# Rebuild pipeline image (needed for admin panel downloads)
docker compose --profile pipeline build
```

## Config panel

The admin config panel is accessible at **http://localhost:8097/config/** from
the Pi only. It provides a 3-tab interface:

**Dashboard** — Service health with color-coded status dots (green/yellow/red),
disk usage (used/free/% full), TLS mode and certificate status, and a pipeline
progress banner linking to the Pipelines tab.

**Pipelines** — Imagery acquisition (direct USGS or M2M API with phase-aware
progress), elevation tile downloads, and OSM POI extraction. Includes a MapLibre
minimap with draw-to-select bounding box. M2M downloads show real-time progress:
GeoTIFFs downloaded, batch counter, total bytes. Only one pipeline runs at a time.

**Settings** — M2M API credentials (USGS EarthExplorer), TLS configuration
display, and STT service status.

Security is handled via Docker port binding — port 8097 is bound to `127.0.0.1`,
so no password is needed. The panel is unreachable from the network.

To access the config panel remotely, use an SSH tunnel:

```bash
ssh -L 8097:localhost:8097 user@pi-ip
# Then open http://localhost:8097/config/ in your local browser
```

## HTTPS via Tailscale

If Tailscale is installed on the Pi, you can get trusted HTTPS with a real
Let's Encrypt certificate — no self-signed CA distribution needed. This enables
browser Geolocation API (device GPS) and secure remote access.

The Pi serves both protocols simultaneously:
- **HTTP on :8093** — for LAN and AREDN mesh clients (unchanged)
- **HTTPS on :443** — for Tailscale clients via `https://<hostname>.ts.net`

### Setup

```bash
# 1. Provision the certificate (requires root)
sudo ./scripts/provision_tailscale_tls.sh

# 2. Configure the environment
echo 'TLS_MODE=tailscale' >> .env
echo 'TLS_CERT_DIR=/srv/geographica/tls/tailscale' >> .env

# 3. Restart the frontend
docker compose restart frontend

# 4. Enable automatic certificate renewal
sudo cp systemd/geographica-tls-renew.service /etc/systemd/system/
sudo cp systemd/geographica-tls-renew.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now geographica-tls-renew.timer
```

Visit `https://<your-tailscale-hostname>` — green padlock, GPS works.

## Customizing coverage area

To cover a different region, adjust these values consistently:

1. **`.env`** — set `BBOX` to your region's bounding box (`lon_min,lat_min,lon_max,lat_max`)
2. **Download PBFs** — get the relevant state/country extracts from Geofabrik
3. **Re-run data pipeline** — vector tiles, elevation, POI index
4. **Update `tileserver/config.json`** — change `tilejson.bounds` in each style entry
5. **Nominatim** — remove the DB volume and restart:
   ```bash
   docker compose down
   docker volume rm geographica_nominatim-db geographica_nominatim-flatnode
   docker compose up -d
   ```
6. **Valhalla** — delete generated graph and restart:
   ```bash
   rm -f data/valhalla/valhalla_tiles.tar data/valhalla/valhalla_tiles -rf
   docker compose restart valhalla
   ```

## Ports

| Port | Service | Purpose |
|------|---------|---------|
| **8093** | **NGINX (frontend)** | **Main entry point — UI + API proxy (HTTP)** |
| **443** | **NGINX (frontend)** | **HTTPS — when TLS is configured** |
| **8097** | **NGINX (config)** | **Config panel — localhost only (127.0.0.1)** |
| 8090 | TileServer GL | Vector and raster tile API |
| 8092 | Nominatim | Geocoding and reverse geocoding |
| 8094 | Valhalla | Routing engine |
| 8095 | GPS | WebSocket GPS relay |
| 8096 | Search | Unified search API |
| 8098 | STT | Speech-to-text (Whisper) |
| 8099 | Setup wizard | Browser-based setup (localhost only, ephemeral) |
| — | Pipeline (on-demand) | Imagery/elevation/OSM POI pipeline container |

All services are proxied through NGINX on port 8093. The config panel on port
8097 is bound to 127.0.0.1 and only accessible from the Pi itself. Direct port
access is only needed for debugging.

## Troubleshooting

**Nominatim shows "unhealthy" during first run**
Normal. The import takes 6-12 hours. The web server doesn't start until import
completes. Monitor with `docker compose logs -f nominatim`. Rank 30 is the
final (and longest) indexing stage.

**Valhalla shows "unhealthy" during first run**
Normal. Graph building takes 1-2 hours. Watch with
`docker compose logs -f valhalla`.

**Container killed by OOM**
Check with `docker inspect <container> --format='{{.State.OOMKilled}}'`.
**Important:** Docker memory limits require kernel cgroup support. On Raspberry Pi OS,
this is NOT enabled by default. Run `docker info | grep "memory limit"` — if it says
"No memory limit support," add `cgroup_enable=memory cgroup_memory=1` to
`/boot/firmware/cmdline.txt` and reboot. Until then, the per-container `memory:` limits
in `docker-compose.yml` are silently ignored.

**GPS service can't connect to gpsd**
gpsd defaults to listening on localhost only. Docker containers can't reach
localhost on the host. Apply the systemd socket override in step 10 so gpsd
listens on `0.0.0.0:2947`.

**GPS shows "Expecting value" errors**
Intermittent JSON parse errors from gpsd. Harmless — the service reconnects
automatically. Verify gpsd is running: `systemctl status gpsd`.

**Search service won't start**
Search depends on Nominatim being healthy. It won't start until the Nominatim
import completes. This is expected on first run.

**"No route found" from Valhalla**
The routing graph only covers the region in your PBF. Ensure your start/end
points are within the coverage area.

**TileServer crashes with SQLITE_READONLY**
The imagery or elevation MBTiles is in WAL mode from an active download.
TileServer reads from `/srv/data/` which must be mounted read-write in
`docker-compose.yml`.

**STT returns 405 or HTML instead of JSON**
The NGINX config is stale. Docker file bind mounts track inodes — git operations
that replace `nginx/nginx.conf` leave the container serving the old version.
Fix: `docker compose up -d --force-recreate frontend`.

**System crashed / OOM during first run**
Ensure cgroup memory limits are enabled (see above). The M2M imagery pipeline
is the most memory-intensive process — it holds all scene metadata in memory
(~1.5 GB for Arizona's 16,000+ scenes). On 8 GB Pi 5, stop Docker services
before running large M2M downloads: `docker compose stop`.

**Slow spatial search (5+ seconds)**
If spatial search is slow only in the browser (curl is fast), enable HTTP/2 on
NGINX: change `listen 443 ssl;` to `listen 443 ssl http2;` in
`nginx/tls-include.conf`. Without HTTP/2, the browser queues search requests
behind dozens of concurrent tile fetches (6-connection limit on HTTP/1.1).

**Free-look camera (CTRL+drag) does ground orbit instead of sky rotation**
MapLibre's internal `dragRotate` handler intercepts CTRL+drag even when
disabled via the public API. The fix is to remove `mouseRotate` and
`mousePitch` from MapLibre's internal `_handlers._handlersById`. This is done
in `initFreeLookCamera()` and the `style.load` handler. If broken after code
changes, see `docs/pitfalls/implementation-pitfalls.md` Pitfall #11.

**Imagery appears blurry in hybrid mode**
The hybrid style's imagery source needs `"tileSize": 256`. Without it, MapLibre
defaults to 512 and requests tiles one zoom level too low. Check
`tileserver/styles/hybrid/style.local.json` sources section.

**M2M pipeline fills disk**
The pipeline downloads GeoTIFFs in batches of 50, converts each batch to
MBTiles, then deletes the raw files. If disk fills, the per-batch cleanup may
have failed — check staging directories: `du -sh data/m2m_staging_*`. Clean
with `sudo rm -rf data/m2m_staging_*`.

## Project structure

```
geographica/
├── bootstrap.sh                # System prerequisites (sudo): apt, docker group, data dir
├── setup.sh                    # Setup wizard launcher (creates venv, starts FastAPI on :8099)
├── docker-compose.yml          # 7 persistent services + on-demand pipeline, with memory limits
├── .env.example                # Environment variable template
├── setup/
│   ├── main.py                 # FastAPI wizard: CSRF, WebSocket progress, API routes
│   ├── config.py               # System detection, .env generation, RAM profiles, bbox validation
│   ├── runner.py               # Async subprocess executor, checkpoint management
│   ├── requirements.txt        # fastapi, uvicorn, httpx
│   └── static/                 # Wizard frontend (HTML/JS/CSS, dark mode, MapLibre map picker)
├── nginx/
│   └── nginx.conf              # Reverse proxy with URL rewriting
├── frontend/
│   ├── index.html              # Single-page app entry point
│   ├── app.js                  # MapLibre GL JS application (~3900 lines)
│   ├── navigation.js           # Turn-by-turn navigation engine
│   ├── nav-ui.js               # Navigation UI bridge
│   ├── stt.js                  # Voice search module (mic button, audio capture)
│   ├── stt-worklet.js          # AudioWorklet processor
│   ├── kmz-import.js           # KML/KMZ file import with icon support
│   ├── import-store.js         # IndexedDB session persistence for imports
│   ├── style.css               # UI styles
│   ├── config/
│   │   └── index.html          # Admin config panel (3-tab: Dashboard/Pipelines/Settings)
│   └── vendor/                 # Vendored JS/CSS (maplibre-gl, togeojson, jszip, dompurify)
├── tileserver/
│   ├── config.json             # TileServer GL data source config (basemap, elevation, imagery, public lands)
│   ├── styles/                 # Map styles
│   │   ├── positron/style.local.json
│   │   ├── darkmatter/style.local.json
│   │   └── hybrid/style.local.json   # Imagery base + roads/labels overlay
│   ├── fonts-served/           # PBF glyph ranges (gitignored, see step 8)
│   ├── sources/                # Natural Earth shapefiles (gitignored)
│   └── southwest5.mbtiles      # Vector basemap (gitignored, ~2.4 GB)
├── services/
│   ├── gps/                    # FastAPI GPS WebSocket service
│   │   ├── Dockerfile
│   │   ├── main.py             # WebSocket relay, /health, /position, /status endpoints
│   │   ├── requirements.txt
│   │   └── tests/              # GPS endpoint tests
│   ├── stt/                    # FastAPI speech-to-text service (Whisper)
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── backends/           # CPU (faster-whisper) + NPU (HailoRT) backends
│   │   └── requirements.txt
│   └── search/                 # FastAPI spatial search + admin service
│       ├── Dockerfile
│       ├── main.py             # Nominatim/POI query, admin API, pipeline orchestration
│       ├── spatial.py          # Intent parser, synonym table, corridor math, spatial endpoint
│       ├── geocode.py          # Async geocode helper with position-biased caching
│       ├── requirements.txt
│       └── tests/              # Admin status, pipeline, zoom validation tests
├── scripts/
│   ├── requirements.txt        # Python deps for data pipeline
│   ├── download_elevation.py   # Terrain-RGB tile downloader
│   ├── build_poi_index.py      # GNIS POI indexer (FTS5)
│   ├── build_osm_pois.py       # OSM amenity + public land extractor
│   ├── build_public_lands.py   # PAD-US public lands vector tile generator
│   ├── build_county_index.py   # Census TIGER/Line county lookup database
│   ├── acquire_imagery.py      # USGS legacy imagery downloader
│   ├── acquire_naip.py         # USGS NAIP county mosaic downloader
│   ├── acquire_sentinel.py     # Copernicus Sentinel-2 imagery downloader
│   ├── pipeline_progress.py    # Shared progress reporting module
│   ├── pipeline_security.py    # Pipeline input validation and security checks
│   ├── provision_tailscale_tls.sh  # Tailscale TLS cert provisioning
│   └── generate_tls.sh         # Self-signed TLS cert generation
├── tests/                      # Top-level test suite (331 tests)
│   ├── test_intent_parser.py   # Spatial search intent parser (54 tests)
│   ├── test_geocode.py         # City geocode with cache (10 tests)
│   ├── test_spatial_endpoint.py # Endpoint integration (15 tests)
│   ├── test_spatial_osm.py     # OSM POI + operator queries
│   ├── test_corridor.py        # Douglas-Peucker + corridor math
│   └── ...                     # Pipeline, security, sentinel, county tests
├── systemd/
│   ├── geographica-tls-renew.service  # Cert renewal oneshot
│   └── geographica-tls-renew.timer    # Daily renewal timer
└── data -> /srv/geographica/data/
    ├── pbf/                    # OSM state extracts + merged PBF
    ├── nominatim/region.osm.pbf
    ├── valhalla/               # PBF + generated routing graph
    ├── poi.sqlite              # FTS5 search database
    ├── elevation.mbtiles       # Terrain-RGB tiles (~70 GB, gitignored)
    └── public-lands.mbtiles    # PAD-US public lands vector tiles
```

## License

TBD
