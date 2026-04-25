# Manual setup

> **Most users want [docs/SETUP.md](SETUP.md) instead** — it covers the wizard-driven happy path that takes ~5 minutes.
>
> This document is for advanced users, recovery scenarios, and AI agents that need a fully-explicit step-by-step reference. Every step the wizard takes for you is documented here so it can be reproduced or audited by hand.

> **The browser-based setup wizard (launched via `./setup.sh` after `sudo ./bootstrap.sh`) is the recommended path.** This manual section exists for debugging and automated-deployment purposes — follow these steps only if the wizard fails on your system, or if you're driving installation from a script.

This guide walks through a complete deployment from a fresh Pi. The process has
two phases: **data acquisition** (requires internet, takes several hours) and
**stack deployment** (runs offline from then on).

## Prerequisites

```bash
sudo apt update
sudo apt install -y \
  docker.io docker-compose-plugin \
  python3 python3-venv python3-pip \
  gdal-bin libgdal-dev osmium-tool \
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

**Enable Docker memory limits** (Raspberry Pi OS only — without this, all
`memory:` limits in docker-compose.yml are silently ignored):

```bash
# Check: does Docker support memory limits?
docker info 2>&1 | grep "memory limit"
# If it says "No memory limit support", fix with:
sudo sed -i 's/$/ cgroup_enable=memory cgroup_memory=1/' /boot/firmware/cmdline.txt
sudo reboot
```

**Optional: USGS M2M credentials** (for highest-resolution z19 NAIP aerial imagery):
Register at https://ers.cr.usgs.gov/register and generate an API token at
https://ers.cr.usgs.gov/profile/access. Enter credentials in the admin panel
(Settings tab) after the stack is running. Credentials are stored securely via
GNOME Keyring (not plaintext files).

> **Free alternatives:** NOAA Digital Coast (z17 with overviews to z0, unthrottled,
> no account needed) and National Map ImageServer (z15+, rate-limited) provide NAIP
> imagery without credentials. NOAA is the recommended source — it's the fastest
> and produces the best results. M2M is only needed for z19 resolution.

## 1. Clone the repo

```bash
git clone https://github.com/cameronzucker/geographica.git
cd geographica
```

## 2. Create the data directory

Data files are large (150+ GB) and live outside the git repo. Create a directory
on your SSD and symlink it:

```bash
sudo mkdir -p /srv/geographica/data/{pbf,nominatim,valhalla}
sudo chown -R $USER:$USER /srv/geographica
ln -s /srv/geographica/data data
```

## 3. Configure environment

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

## 4. Download OSM data

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

## 5. Generate vector basemap tiles

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

## 6. Download elevation tiles

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

## 7. Build the POI search index

```bash
python scripts/build_poi_index.py \
  --bbox "-124.8,31.3,-102.0,49.0" \
  --states "AZ,CA,CO,ID,MT,NV,NM,OR,UT,WA,WY" \
  --output /srv/geographica/data/poi.sqlite
```

Downloads GNIS gazetteer data from USGS via S3
(`prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/`).
Free, no API key required. Produces a small SQLite FTS5 database.

## 7b. Extract OSM amenities and public land boundaries

```bash
python scripts/build_osm_pois.py \
  --pbf /srv/geographica/data/valhalla/western-us.osm.pbf \
  --output /srv/geographica/data/poi.sqlite \
  --bbox "-124.8,31.3,-102.0,49.0"
```

Extracts named amenities (fuel, food, lodging, etc.) and public land boundaries
(BLM, USFS, NPS) from the OSM PBF into the same SQLite database. Requires
`osmium` and `shapely` (`pip install shapely`). Takes ~10 minutes.

## 7c. Build public lands vector tiles (optional)

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

## 8. Set up TileServer GL styles and fonts

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

## 9. Frontend vendor libraries

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

## 10. Configure GPS (optional)

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

## 11. Launch the stack

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
> Pipeline 4 GB, STT 1.5 GB, TileServer 1 GB, Search 256 MB, GPS 128 MB,
> Frontend 128 MB (~19 GB total ceiling, but pipeline is on-demand).
> The pipeline container needs 4 GB because the NOAA rasterio-based
> reproject runs in-process with multiple threads, each handling ~486 MB
> GeoTIFFs.
> If a container exceeds its limit, Docker restarts just that container —
> the system stays up.

## 12. Verify the deployment

Once all services show healthy in `docker compose ps`:

```bash
# Tile serving
curl -s http://localhost:8093/tiles/data/southwest5.json | python3 -m json.tool | head -20

# Geocoding
curl -s "http://localhost:8093/nominatim/search?q=Phoenix&format=json" | python3 -m json.tool | head -20

# Routing
curl -s -X POST http://localhost:8093/valhalla/route \
  -H "Content-Type: application/json" \
  -d '{"locations":[{"lat":33.45,"lon":-112.07},{"lat":34.05,"lon":-111.09}],"costing":"auto"}' \
  | python3 -m json.tool | head -20

# Unified search
curl -s "http://localhost:8093/search/search?q=Grand+Canyon" | python3 -m json.tool | head -20

# Speech-to-text
curl -s http://localhost:8093/stt/health | python3 -m json.tool
```

Open a browser to **http://&lt;your-pi-ip&gt;:8093** to use the map.
