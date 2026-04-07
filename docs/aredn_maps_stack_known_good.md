# AREDN Maps Stack on Raspberry Pi 5 — Known-Good Deployment Guide

This guide documents the deployment that was actually brought up successfully on a Raspberry Pi 5 running current Raspberry Pi OS, using Docker Compose.

It reflects the practical corrections that were required in the real build:

- Planetiler must build from the merged regional `.osm.pbf` and needs `--download` for the standard basemap profile because auxiliary datasets are required.
- TileServer GL must have valid local style paths, valid sprite files, and valid font glyph `.pbf` files.
- OpenMapTiles fonts should be taken from the prebuilt release zip rather than built locally on the Pi.
- The frontend reverse proxy must rewrite both style JSON and TileJSON so URLs remain under the frontend origin and `/tiles/...` path.
- Valhalla must build from the `.osm.pbf` on first run (`use_tiles_ignore_pbf=False`) and persist its generated data in `/custom_files`.
- MapProxy works for aerial imagery, but needs explicit seeding and its own endpoint testing.

---

## Working architecture

- **Planetiler** builds `southwest5.mbtiles`
- **TileServer GL** serves OSM vector/raster/WMTS
- **MapProxy** caches aerial imagery
- **Nominatim** handles search/reverse geocoding
- **Valhalla** handles routing
- **NGINX frontend** serves the UI and proxies all backends through one origin

## Host ports

- `8090` TileServer GL
- `8091` MapProxy imagery
- `8092` Nominatim
- `8093` frontend
- `8094` Valhalla

## Directory layout

```text
/srv/aredn-maps/
  compose.yaml
  pbf/
  tileserver/
    config.json
    southwest5.mbtiles
    fonts-served/
    styles/
      positron/
      darkmatter/
  mapproxy/
    Dockerfile
    app.py
    mapproxy.yaml
    seed.yaml
    cache_data/
  valhalla/
    custom_files/
  nominatim/
    data/
  frontend/
    nginx.conf
    site/
      index.html
      vendor/
        maplibre-gl.js
        maplibre-gl.css
```

---

## 1) Host prerequisites

```bash
sudo apt update
sudo apt install -y osmium-tool git python3 python3-venv nodejs npm unzip wget
```

---

## 2) Create the project layout

```bash
sudo install -d -m 0755 /srv/aredn-maps
sudo chown "$USER:$USER" /srv/aredn-maps

install -d -m 0755 /srv/aredn-maps/{pbf,tileserver,tileserver/styles,tileserver/fonts-served,mapproxy,mapproxy/cache_data,valhalla/custom_files,nominatim/data,frontend/site/vendor}
```

---

## 3) Download and merge the OSM extracts

```bash
cd /srv/aredn-maps/pbf

wget -O arizona-latest.osm.pbf      https://download.geofabrik.de/north-america/us/arizona-latest.osm.pbf
wget -O california-latest.osm.pbf   https://download.geofabrik.de/north-america/us/california-latest.osm.pbf
wget -O nevada-latest.osm.pbf       https://download.geofabrik.de/north-america/us/nevada-latest.osm.pbf
wget -O new-mexico-latest.osm.pbf   https://download.geofabrik.de/north-america/us/new-mexico-latest.osm.pbf
wget -O utah-latest.osm.pbf         https://download.geofabrik.de/north-america/us/utah-latest.osm.pbf

osmium merge \
  arizona-latest.osm.pbf \
  california-latest.osm.pbf \
  nevada-latest.osm.pbf \
  new-mexico-latest.osm.pbf \
  utah-latest.osm.pbf \
  -o southwest5-latest.osm.pbf
```

---

## 4) Build the MBTiles with Planetiler

**Important:** use `--download`. That was required for the standard basemap/OpenMapTiles profile to succeed.

```bash
docker run --rm -it \
  -e JAVA_TOOL_OPTIONS="-Xmx8g" \
  -v /srv/aredn-maps/pbf:/pbf \
  -v /srv/aredn-maps/tileserver:/data \
  ghcr.io/onthegomap/planetiler:0.10.2 \
  --download \
  --osm-path=/pbf/southwest5-latest.osm.pbf \
  --output=/data/southwest5.mbtiles \
  --force
```

Verify:

```bash
ls -lh /srv/aredn-maps/tileserver/southwest5.mbtiles
```

---

## 5) Fetch styles and sprites

```bash
cd /srv/aredn-maps/tileserver

git clone --depth=1 https://github.com/openmaptiles/positron-gl-style.git styles/positron
git clone --depth=1 https://github.com/openmaptiles/dark-matter-gl-style.git styles/darkmatter
```

Download the sprite assets explicitly:

```bash
cd /srv/aredn-maps/tileserver/styles/positron
wget -O sprite.json    https://openmaptiles.github.io/positron-gl-style/sprite.json
wget -O sprite.png     https://openmaptiles.github.io/positron-gl-style/sprite.png
wget -O sprite@2x.json https://openmaptiles.github.io/positron-gl-style/sprite@2x.json
wget -O sprite@2x.png  https://openmaptiles.github.io/positron-gl-style/sprite@2x.png

cd /srv/aredn-maps/tileserver/styles/darkmatter
wget -O sprite.json    https://openmaptiles.github.io/dark-matter-gl-style/sprite.json
wget -O sprite.png     https://openmaptiles.github.io/dark-matter-gl-style/sprite.png
wget -O sprite@2x.json https://openmaptiles.github.io/dark-matter-gl-style/sprite@2x.json
wget -O sprite@2x.png  https://openmaptiles.github.io/dark-matter-gl-style/sprite@2x.png
```

---

## 6) Install prebuilt font glyphs

Do **not** build `openmaptiles/fonts` locally on the Pi. The reliable path is to use the prebuilt release zip.

```bash
wget -O /tmp/openmaptiles-fonts-v2.0.zip \
  https://github.com/openmaptiles/fonts/releases/download/v2.0/v2.0.zip

unzip -q /tmp/openmaptiles-fonts-v2.0.zip -d /srv/aredn-maps/tileserver/fonts-served
rm -f /tmp/openmaptiles-fonts-v2.0.zip
```

---

## 7) Patch the styles for local MBTiles, sprites, and glyphs

```bash
python3 - <<'PY'
import json
from pathlib import Path

base = Path("/srv/aredn-maps/tileserver/styles")

for style_name in ("positron", "darkmatter"):
    src = base / style_name / "style.json"
    dst = base / style_name / "style.local.json"

    data = json.loads(src.read_text())
    data["sources"]["openmaptiles"]["url"] = "mbtiles://{southwest5}"
    data["sprite"] = "{styleJsonFolder}/sprite"
    data["glyphs"] = "{fontstack}/{range}.pbf"

    dst.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote {dst}")
PY
```

---

## 8) TileServer GL config

**Important correction:** `style` paths are relative to `paths.styles`.

```bash
cat > /srv/aredn-maps/tileserver/config.json <<'EOF'
{
  "options": {
    "paths": {
      "root": "/data",
      "fonts": "fonts-served",
      "styles": "styles"
    },
    "serveAllFonts": true,
    "serveAllStyles": true
  },
  "data": {
    "southwest5": {
      "mbtiles": "southwest5.mbtiles"
    }
  },
  "styles": {
    "positron": {
      "style": "positron/style.local.json",
      "tilejson": {
        "bounds": [-124.6, 31.2, -103.0, 42.2]
      }
    },
    "darkmatter": {
      "style": "darkmatter/style.local.json",
      "tilejson": {
        "bounds": [-124.6, 31.2, -103.0, 42.2]
      }
    }
  }
}
EOF
chmod 0644 /srv/aredn-maps/tileserver/config.json
```

---

## 9) MapProxy for imagery

### `mapproxy/Dockerfile`

```bash
cat > /srv/aredn-maps/mapproxy/Dockerfile <<'EOF'
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg62-turbo-dev \
    zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "MapProxy==6.0.1" gunicorn

WORKDIR /mapproxy
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "app:application"]
EOF
chmod 0644 /srv/aredn-maps/mapproxy/Dockerfile
```

### `mapproxy/app.py`

```bash
cat > /srv/aredn-maps/mapproxy/app.py <<'EOF'
from mapproxy.wsgiapp import make_wsgi_app

application = make_wsgi_app("/mapproxy/mapproxy.yaml", ignore_config_warnings=True)
EOF
chmod 0644 /srv/aredn-maps/mapproxy/app.py
```

### `mapproxy/mapproxy.yaml`

```bash
cat > /srv/aredn-maps/mapproxy/mapproxy.yaml <<'EOF'
services:
  demo:
  tms:
    use_grid_names: true
    origin: 'nw'
  wmts:
  wms:
    md:
      title: Southwest US Imagery Cache
      abstract: Cached USGS imagery for offline AREDN/TAK use

layers:
  - name: usgs_imagery
    title: USGS Imagery Only
    sources: [usgs_imagery_cache]

caches:
  usgs_imagery_cache:
    grids: [webmercator]
    sources: [usgs_imagery_source]
    cache:
      type: sqlite
      directory: /mapproxy/cache_data/usgs_imagery
    format: image/jpeg
    request_format: image/jpeg
    bulk_meta_tiles: true
    meta_size: [4,4]
    meta_buffer: 0

sources:
  usgs_imagery_source:
    type: tile
    grid: GLOBAL_WEBMERCATOR
    url: https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/%(z)s/%(y)s/%(x)s
    # Uncomment after seeding for strict offline service:
    # seed_only: true

grids:
  webmercator:
    base: GLOBAL_WEBMERCATOR
EOF
chmod 0644 /srv/aredn-maps/mapproxy/mapproxy.yaml
```

### `mapproxy/seed.yaml`

```bash
cat > /srv/aredn-maps/mapproxy/seed.yaml <<'EOF'
coverages:
  southwest_context:
    bbox: [-124.6, 31.2, -103.0, 42.2]
    srs: EPSG:4326

seeds:
  regional_context:
    caches: [usgs_imagery_cache]
    coverages: [southwest_context]
    levels:
      from: 0
      to: 16

cleanups:
  refresh_context:
    caches: [usgs_imagery_cache]
    coverages: [southwest_context]
    levels:
      from: 0
      to: 16
    refresh_before:
      weeks: 52
EOF
chmod 0644 /srv/aredn-maps/mapproxy/seed.yaml
```

---

## 10) Stage the merged PBF for Nominatim and Valhalla

```bash
cp /srv/aredn-maps/pbf/southwest5-latest.osm.pbf /srv/aredn-maps/nominatim/data/
cp /srv/aredn-maps/pbf/southwest5-latest.osm.pbf /srv/aredn-maps/valhalla/custom_files/
sudo chmod -R 0777 /srv/aredn-maps/valhalla/custom_files
```

---

## 11) Frontend reverse proxy — known-good config

Replace `192.168.20.122` below with the Pi’s actual static LAN IP.

```bash
cat > /srv/aredn-maps/frontend/nginx.conf <<'EOF'
server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /tiles/styles/ {
        proxy_pass http://192.168.20.122:8090/styles/;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Port $server_port;
        proxy_http_version 1.1;

        proxy_set_header Accept-Encoding "";

        sub_filter_once off;
        sub_filter_types application/json text/plain;

        sub_filter 'http://192.168.20.122/data/'   'http://192.168.20.122:8093/tiles/data/';
        sub_filter 'http://192.168.20.122/styles/' 'http://192.168.20.122:8093/tiles/styles/';
        sub_filter 'http://192.168.20.122/fonts/'  'http://192.168.20.122:8093/tiles/fonts/';
    }

    location = /tiles/data/southwest5.json {
        proxy_pass http://192.168.20.122:8090/data/southwest5.json;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Port $server_port;
        proxy_http_version 1.1;

        proxy_set_header Accept-Encoding "";

        sub_filter_once off;
        sub_filter_types application/json text/plain;

        sub_filter 'http://192.168.20.122/data/' 'http://192.168.20.122:8093/tiles/data/';
    }

    location /tiles/ {
        proxy_pass http://192.168.20.122:8090/;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Port $server_port;
        proxy_http_version 1.1;
    }

    location /imagery/ {
        proxy_pass http://192.168.20.122:8091/;
        proxy_set_header Host $http_host;
        proxy_http_version 1.1;
    }

    location /nominatim/ {
        proxy_pass http://192.168.20.122:8092/;
        proxy_set_header Host $http_host;
        proxy_http_version 1.1;
    }

    location /valhalla/ {
        proxy_pass http://192.168.20.122:8094/;
        proxy_set_header Host $http_host;
        proxy_http_version 1.1;
    }
}
EOF
chmod 0644 /srv/aredn-maps/frontend/nginx.conf
```

---

## 12) Local MapLibre assets

```bash
cd /srv/aredn-maps/frontend
npm pack maplibre-gl@5.21.1
tar -xf maplibre-gl-5.21.1.tgz

install -m 0644 package/dist/maplibre-gl.js  /srv/aredn-maps/frontend/site/vendor/maplibre-gl.js
install -m 0644 package/dist/maplibre-gl.css /srv/aredn-maps/frontend/site/vendor/maplibre-gl.css

rm -rf package maplibre-gl-5.21.1.tgz
```

---

## 13) `compose.yaml`

```bash
cat > /srv/aredn-maps/compose.yaml <<'EOF'
services:
  tileserver:
    image: maptiler/tileserver-gl:v5.5.0-arm64
    container_name: tileserver
    restart: unless-stopped
    ports:
      - "8090:8080"
    volumes:
      - ./tileserver:/data
    command: ["--config", "/data/config.json"]

  imagery:
    build:
      context: ./mapproxy
    container_name: mapproxy-imagery
    restart: unless-stopped
    ports:
      - "8091:8080"
    volumes:
      - ./mapproxy:/mapproxy

  valhalla:
    image: ghcr.io/gis-ops/docker-valhalla/valhalla:3.5.1
    container_name: valhalla
    restart: unless-stopped
    ports:
      - "8094:8002"
    environment:
      server_threads: "4"
      serve_tiles: "True"
      use_tiles_ignore_pbf: "False"
      build_elevation: "False"
      build_admins: "False"
      build_time_zones: "False"
      build_transit: "False"
      build_tar: "True"
      force_rebuild: "False"
      update_existing_config: "True"
      tileset_name: "valhalla_tiles"
    volumes:
      - ./valhalla/custom_files:/custom_files

  nominatim:
    image: mediagis/nominatim:5.2.0
    container_name: nominatim
    restart: unless-stopped
    shm_size: "8gb"
    ports:
      - "8092:8080"
    environment:
      PBF_PATH: /nominatim/data/southwest5-latest.osm.pbf
      UPDATE_MODE: none
      FREEZE: "true"
      IMPORT_STYLE: full
      THREADS: "4"
      WARMUP_ON_STARTUP: "true"
      POSTGRES_SHARED_BUFFERS: 2GB
      POSTGRES_MAINTENANCE_WORK_MEM: 2GB
      POSTGRES_AUTOVACUUM_WORK_MEM: 512MB
      POSTGRES_WORK_MEM: 32MB
      POSTGRES_EFFECTIVE_CACHE_SIZE: 8GB
    volumes:
      - ./nominatim/data:/nominatim/data
      - nominatim-db:/var/lib/postgresql/16/main
      - nominatim-flatnode:/nominatim/flatnode

  frontend:
    image: nginx:alpine
    container_name: maps-frontend
    restart: unless-stopped
    depends_on:
      - tileserver
      - imagery
      - nominatim
      - valhalla
    ports:
      - "8093:80"
    volumes:
      - ./frontend/site:/usr/share/nginx/html:ro
      - ./frontend/nginx.conf:/etc/nginx/conf.d/default.conf:ro

volumes:
  nominatim-db:
  nominatim-flatnode:
EOF
chmod 0644 /srv/aredn-maps/compose.yaml
```

---

## 14) Build the frontend site

Use the already-working `index.html` from the live deployment. If regenerating from scratch, reuse the known-good copy from the running system or your saved local copy.

---

## 15) Seed imagery

```bash
cd /srv/aredn-maps
docker compose up -d imagery
docker compose run --rm imagery \
  mapproxy-seed -f /mapproxy/mapproxy.yaml -s /mapproxy/seed.yaml --concurrency 2
```

After seeding, uncomment `seed_only: true` in `mapproxy.yaml` and restart imagery:

```bash
docker compose restart imagery
```

---

## 16) Bring up the stack in order

```bash
cd /srv/aredn-maps
docker compose up -d tileserver imagery nominatim
docker compose up -d valhalla
docker compose up -d frontend
```

---

## 17) Tests that should pass

### TileServer GL

```bash
curl -I http://192.168.20.122:8090/styles/positron/style.json
curl -I http://192.168.20.122:8090/styles/positron/sprite@2x.json
curl -I http://192.168.20.122:8090/data/southwest5.json
```

### Frontend-proxied style JSON and TileJSON

```bash
curl -s http://192.168.20.122:8093/tiles/styles/positron/style.json | grep -E '"url"|"sprite"|"glyphs"'
curl -s http://192.168.20.122:8093/tiles/data/southwest5.json
```

The style JSON should point to `:8093/tiles/...` URLs, not raw backend root URLs.

### Nominatim

```bash
curl 'http://192.168.20.122:8092/search?q=Flagstaff&format=jsonv2'
curl 'http://192.168.20.122:8092/reverse?lat=33.4484&lon=-112.0740&format=jsonv2'
```

### Valhalla

```bash
curl http://192.168.20.122:8094/status
curl 'http://192.168.20.122:8094/route?json={"locations":[{"lat":33.4484,"lon":-112.0740},{"lat":35.1983,"lon":-111.6513}],"costing":"auto"}'
```

---

## 18) Known frontend behavior

In the current frontend, the **Route** button only arms route mode. The user must then click the **map itself twice**:

1. first click = start
2. second click = end

Clicking a geocode marker does not currently set route endpoints.

---

## 19) Practical notes from the real deployment

1. **Planetiler needed `--download`.**
2. **TileServer GL would not work until sprites and glyphs were present locally.**
3. **The prebuilt OpenMapTiles font zip was reliable; local font generation on the Pi was not.**
4. **Frontend proxying only became reliable once style JSON and TileJSON were rewritten to stay under `/tiles/...`.**
5. **Valhalla’s first build must use `use_tiles_ignore_pbf=False` so it actually builds from the PBF.**
6. **Valhalla appearing idle after startup is normal. Use `/status` and `/route` to confirm readiness.**
7. **Optional traffic warnings from Valhalla can be ignored if no live traffic tiles were configured.**
