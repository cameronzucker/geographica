# Geographica

Offline-first mapping platform for field operations on disconnected networks.
Runs a complete GIS stack on a Raspberry Pi 5 — vector basemaps, aerial imagery,
terrain, routing, geocoding, GPS tracking, and search — with zero cloud dependency
after initial data acquisition.

Built for [AREDN](https://www.arednmesh.org/) mesh networks, but works on any
isolated LAN or standalone device.

## Features

- **Vector basemaps** with three themes (Positron light, Dark Matter dark, Hybrid imagery+roads) and house number labels
- **Aerial imagery** overlay — USGS NAIP (0.6m, US), Sentinel-2 (10m, global) with per-source toggles and opacity slider
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
| GPS | — | Waveshare LC29H GPS HAT or similar gpsd-compatible receiver |
| NPU | — | Hailo 10H (for future NPU-accelerated STT) |

**Tested on:** Pi 5 16 GB, Debian Trixie (bookworm also works), Intel D3-S4610
896 GB SATA SSD.

**Storage budget** (Western US, 11 states):

| Dataset | Size |
|---------|------|
| Vector basemap (OpenMapTiles) | ~2.4 GB |
| Elevation tiles (zoom 0-14) | ~70 GB |
| Aerial imagery — NAIP (USGS, zoom 0-15) | ~30+ GB |
| Aerial imagery — Sentinel-2 (Copernicus, 10m) | varies by area |
| Public lands (PAD-US vector tiles) | ~1-2 GB |
| OSM extracts (merged PBF) | ~3.1 GB |
| Valhalla routing graph | ~4.3 GB |
| Nominatim geocoding DB | ~30-40 GB |
| POI index | ~80 MB |
| **Total** | **~150+ GB** |

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

## Setup guide

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
  git npm wget curl unzip
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

### 7b. Extract OSM amenities and public land

```bash
python scripts/build_osm_pois.py \
  --pbf /srv/geographica/data/valhalla/western-us.osm.pbf \
  --output /srv/geographica/data/poi.sqlite \
  --bbox "-124.8,31.3,-102.0,49.0"
```

Extracts named amenities (fuel, food, lodging, etc.) and public land boundaries
(BLM, USFS, NPS) from the OSM PBF into the same SQLite database. Requires
`osmium` and `shapely` (`pip install shapely`). Takes ~10 minutes.

### 8. Set up TileServer GL styles and fonts

**Fonts** (PBF glyph ranges for map label rendering):

```bash
wget -O /tmp/fonts.zip https://github.com/openmaptiles/fonts/releases/download/v2.0/v2.0.zip
unzip -q /tmp/fonts.zip -d tileserver/fonts-served
rm /tmp/fonts.zip
```

**Styles** — The `style.local.json` files are checked into the repo. Sprite and
icon assets are needed from the upstream OpenMapTiles style repos:

```bash
cd tileserver/styles

# Positron
git clone --depth 1 https://github.com/openmaptiles/positron-gl-style.git positron-tmp
cp positron-tmp/sprite* positron/
cp -r positron-tmp/icons positron/
rm -rf positron-tmp

# Dark Matter
git clone --depth 1 https://github.com/openmaptiles/dark-matter-gl-style.git darkmatter-tmp
cp darkmatter-tmp/sprite* darkmatter/
cp -r darkmatter-tmp/icons darkmatter/
rm -rf darkmatter-tmp

cd ../..
```

### 9. Install frontend vendor libraries

```bash
cd frontend/vendor

npm pack maplibre-gl@5.21.1
tar -xf maplibre-gl-*.tgz
cp package/dist/maplibre-gl.js .
cp package/dist/maplibre-gl.css .
rm -rf package maplibre-gl-*.tgz

npm pack @mapbox/togeojson@0.16.2
tar -xf mapbox-togeojson-*.tgz
cp package/togeojson.js .
rm -rf package mapbox-togeojson-*.tgz

npm pack jszip@3.10.1
tar -xf jszip-*.tgz
cp package/dist/jszip.min.js .
rm -rf package jszip-*.tgz

cd ../..
```

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
| **8093** | **NGINX (frontend)** | **Main entry point — UI + API proxy** |
| **8097** | **NGINX (config)** | **Config panel — localhost only** |
| 8090 | TileServer GL | Vector and raster tile API |
| 8092 | Nominatim | Geocoding and reverse geocoding |
| 8094 | Valhalla | Routing engine |
| 8095 | GPS | WebSocket GPS relay |
| 8096 | Search | Unified search API |
| 8098 | STT | Speech-to-text (Whisper) |
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
Check with `docker inspect <container> --format='{{.State.OOMKilled}}'`. The
per-container memory limits prevent system-wide OOM — only the offending
container restarts. If a service consistently OOMs, increase its limit in the
`deploy.resources.limits` section of `docker-compose.yml`.

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
If you see a hard crash (kernel OOM killer), the per-container memory limits in
`docker-compose.yml` should prevent this. If you modified the limits, ensure
they total less than your available RAM minus 2 GB for the OS. Nominatim is the
heaviest consumer — check its limit first.

## Project structure

```
geographica/
├── docker-compose.yml          # 7 persistent services + on-demand pipeline, with memory limits
├── .env.example                # Environment variable template
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
│   └── vendor/                 # Vendored JS/CSS (gitignored, see step 9)
├── tileserver/
│   ├── config.json             # TileServer GL data source config (basemap, elevation, imagery, public lands)
│   ├── styles/                 # Map styles
│   │   ├── positron/style.local.json
│   │   ├── darkmatter/style.local.json
│   │   └── hybrid/style.local.json   # Imagery base + roads/labels overlay
│   ├── fonts-served/           # PBF glyph ranges (gitignored, see step 8)
│   ├── sources/                # Natural Earth shapefiles (gitignored)
│   ├── southwest5.mbtiles      # Vector basemap (gitignored, ~2.4 GB)
│   └── elevation.mbtiles       # Terrain tiles (gitignored, ~70 GB)
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
    └── public-lands.mbtiles    # PAD-US public lands vector tiles
```

## License

TBD
