# Geographica

Offline-first mapping platform for field operations on disconnected networks.
Runs a complete GIS stack on a Raspberry Pi 5 — vector basemaps, aerial imagery,
terrain, routing, geocoding, GPS tracking, and search — with zero cloud dependency
after initial data acquisition.

Built for [AREDN](https://www.arednmesh.org/) mesh networks, but works on any
isolated LAN or standalone device.

## What you get

- **Vector basemaps** with two themes (Positron light, Dark Matter dark)
- **Aerial imagery** overlay (USGS NAIP orthophotos)
- **3D terrain** with hillshade and adjustable exaggeration
- **Turn-by-turn routing** for car, bicycle, and pedestrian
- **Geocoding** — search for addresses, cities, landmarks
- **POI search** — GNIS gazetteer with full-text search
- **Live GPS** — hardware GPS streaming over WebSocket
- **KML/KMZ import** — drag-and-drop file overlay
- **ATAK integration** — serves as a WMS map source for TAK clients

## Hardware requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Board | Raspberry Pi 5, 8 GB | Raspberry Pi 5, 16 GB |
| Storage | 256 GB SSD (single-state coverage) | 1 TB SSD (multi-state coverage) |
| GPS | — | Waveshare LC29H GPS HAT or similar gpsd-compatible receiver |

**Tested on:** Pi 5 16 GB, Debian Trixie (bookworm also works), Intel D3-S4610
896 GB SATA SSD.

**Storage budget** (Western US, 11 states):

| Dataset | Size |
|---------|------|
| Vector basemap (OpenMapTiles) | ~2.4 GB |
| Elevation tiles (zoom 0-12) | ~9 GB |
| OSM extracts (state PBFs) | ~6.2 GB |
| Valhalla routing graph | ~4.3 GB |
| Nominatim geocoding DB | ~20 GB |
| POI index | < 1 MB |
| **Total** | **~42 GB** |

## Architecture

```
Browser ──> NGINX (:8093) ──┬──> TileServer GL (:8090)   vector/raster tiles
                            ├──> Valhalla (:8094)         routing engine
                            ├──> Nominatim (:8092)        geocoding (PostgreSQL)
                            ├──> Search (:8096)           unified search API
                            └──> GPS (:8095)              WebSocket GPS relay
```

Six Docker Compose services with per-container memory limits to prevent OOM on
constrained hardware. NGINX reverse-proxies all services behind a single port
with URL rewriting for TileServer GL style/TileJSON endpoints.

---

## Setup guide

This guide walks through a complete deployment from a fresh Pi. The process has
two phases: **data acquisition** (requires internet, takes several hours) and
**stack deployment** (runs offline from then on).

### Prerequisites

```bash
sudo apt update
sudo apt install -y \
  docker.io docker-compose-v2 \
  python3 python3-venv python3-pip \
  gdal-bin osmium-tool tilemaker \
  gpsd gpsd-clients \
  git npm
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
git clone https://github.com/your-org/geographica.git
cd geographica
```

### 2. Create the data directory

Data files are large (40+ GB) and live outside the git repo. Create a directory
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

Edit `.env` and set `HOST_IP` to your Pi's LAN address. The defaults are tuned
for a 16 GB Pi 5. For 8 GB, reduce the PostgreSQL memory settings:

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

The vector basemap is generated from the merged PBF using tilemaker with the
OpenMapTiles schema. The Natural Earth source data is included in
`tileserver/sources/`.

Unzip the source data:

```bash
cd tileserver/sources
unzip -o natural_earth_vector.sqlite.zip
unzip -o water-polygons-split-3857.zip
unzip -o lake_centerline.shp.zip
cd ../..
```

Generate tiles (1-3 hours on a Pi 5 depending on coverage area):

```bash
tilemaker \
  --input /srv/geographica/data/pbf/western-us.osm.pbf \
  --output tileserver/southwest5.mbtiles \
  --config resources/config-openmaptiles.json \
  --process resources/process-openmaptiles.lua
```

> **Config files:** tilemaker ships with OpenMapTiles config and process files.
> Find them with `dpkg -L tilemaker | grep resources`. The `--config` and
> `--process` paths above assume tilemaker's bundled resources. Adjust if your
> installation places them elsewhere.

### 6. Download elevation tiles

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt

python scripts/download_elevation.py \
  --bbox "-124.6,31.2,-103.0,42.2" \
  --zoom 0-12 \
  --output tileserver/elevation.mbtiles
```

Downloads Terrain-RGB tiles from AWS (free, no API key). ~9 GB for the Western
US at zoom 0-12. The script supports checkpoint resume — if interrupted, re-run
the same command.

### 7. Build the POI search index

```bash
python scripts/build_poi_index.py \
  --bbox "-124.6,31.2,-103.0,42.2" \
  --states "AZ,CA,CO,ID,MT,NV,NM,OR,UT,WA,WY" \
  --output /srv/geographica/data/poi.sqlite
```

Downloads GNIS gazetteer data from USGS (free, no API key). Produces a small
SQLite FTS5 database.

### 8. Set up TileServer GL styles and fonts

**Fonts** (PBF glyph ranges for map label rendering):

```bash
cd tileserver
wget https://github.com/openmaptiles/fonts/releases/download/v3.0/fonts-served.tar.gz
tar -xzf fonts-served.tar.gz
rm fonts-served.tar.gz
cd ..
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

The GPS service connects to gpsd on the host via `host.docker.internal:2947`.
If you don't have GPS hardware, the service starts cleanly and reports no-fix
status — it won't block the rest of the stack.

### 11. Launch the stack

```bash
docker compose build    # build the gps and search service images
docker compose up -d    # start all 6 services
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

> **Memory limits:** The stack has per-container memory limits (13.5 GB total
> ceiling) to prevent system-wide OOM on 16 GB hardware. If a container exceeds
> its limit, Docker restarts just that container — the system stays up.

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

# Rebuild after code changes to gps or search
docker compose build && docker compose up -d
```

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
| 8090 | TileServer GL | Vector and raster tile API |
| 8092 | Nominatim | Geocoding and reverse geocoding |
| 8094 | Valhalla | Routing engine |
| 8095 | GPS | WebSocket GPS relay |
| 8096 | Search | Unified search API |

All services are proxied through NGINX on port 8093. Direct port access is only
needed for debugging.

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

**GPS shows "Expecting value" errors**
Intermittent JSON parse errors from gpsd. Harmless — the service reconnects
automatically. Verify gpsd is running: `systemctl status gpsd`.

**Search service won't start**
Search depends on Nominatim being healthy. It won't start until the Nominatim
import completes. This is expected on first run.

**"No route found" from Valhalla**
The routing graph only covers the region in your PBF. Ensure your start/end
points are within the coverage area.

**System crashed / OOM during first run**
If you see a hard crash (kernel OOM killer), the per-container memory limits in
`docker-compose.yml` should prevent this. If you modified the limits, ensure
they total less than your available RAM minus 2 GB for the OS. Nominatim is the
heaviest consumer — check its limit first.

## Project structure

```
geographica/
├── docker-compose.yml          # 6-service stack with memory limits
├── .env.example                # Environment variable template
├── nginx/
│   └── nginx.conf              # Reverse proxy with URL rewriting
├── frontend/
│   ├── index.html              # Single-page app entry point
│   ├── app.js                  # MapLibre GL JS application (~1100 lines)
│   ├── style.css               # UI styles
│   └── vendor/                 # Vendored JS/CSS (gitignored, see step 9)
├── tileserver/
│   ├── config.json             # TileServer GL data source config
│   ├── styles/                 # Positron + Dark Matter map styles
│   │   ├── positron/style.local.json
│   │   └── darkmatter/style.local.json
│   ├── fonts-served/           # PBF glyph ranges (gitignored, see step 8)
│   ├── sources/                # Natural Earth shapefiles (gitignored)
│   ├── southwest5.mbtiles      # Vector basemap (gitignored, ~2.4 GB)
│   └── elevation.mbtiles       # Terrain tiles (gitignored, ~9 GB)
├── services/
│   ├── gps/                    # FastAPI GPS WebSocket service
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   └── requirements.txt
│   └── search/                 # FastAPI unified search service
│       ├── Dockerfile
│       ├── main.py
│       └── requirements.txt
├── scripts/
│   ├── requirements.txt        # Python deps for data pipeline
│   ├── download_elevation.py   # Terrain-RGB tile downloader
│   ├── build_poi_index.py      # GNIS POI indexer (FTS5)
│   └── acquire_imagery.py      # USGS imagery downloader
└── data -> /srv/geographica/data/
    ├── pbf/                    # OSM state extracts + merged PBF
    ├── nominatim/region.osm.pbf
    ├── valhalla/               # PBF + generated routing graph
    └── poi.sqlite              # FTS5 search database
```

## License

TBD
