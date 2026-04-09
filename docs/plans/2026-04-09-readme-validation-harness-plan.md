# README Validation Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a repeatable LXD-based test harness that validates the README setup instructions by following them from scratch in an isolated container, with two modes: quick (~15-30 min, bind-mounted data) and full (hours, downloads everything).

**Architecture:** The harness is a sequence of shell commands executed via `lxc exec` against a disposable Debian 13 container. The agent follows README steps literally inside the container, captures Playwright screenshots from the host, and writes a structured pass/fail report. No new code is written — this is an operational procedure.

**Tech Stack:** LXD/LXC, Docker-in-LXC, Playwright (MCP tools), bash

**Spec:** `docs/superpowers/specs/2026-04-09-readme-validation-harness-design.md`

**MODE PARAMETER:** This plan uses `$MODE` to indicate where quick and full modes diverge. The executing agent must be told which mode to run at dispatch time. Sections marked `[FULL ONLY]` are skipped in quick mode. Sections marked `[QUICK ONLY]` are skipped in full mode.

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `docs/validation/<date>-<mode>-report.md` | Test report output |
| Create | `docs/validation/<date>-<mode>/` | Screenshot directory |

No source code is created or modified. This plan validates existing code and documentation.

---

## Task 1: Host — LXD Bootstrap and Pre-Flight

**Files:** None (host system configuration only)

- [ ] **Step 1: Verify LXD group membership**

```bash
groups | grep -q lxd && echo "OK: user in lxd group" || echo "NEED: sudo usermod -aG lxd $USER"
```

If not in group:
```bash
sudo usermod -aG lxd $USER
```

Then **start a new shell** (or `newgrp lxd`) for the group to take effect. Verify:
```bash
groups | grep -q lxd && echo "OK"
```

- [ ] **Step 2: Initialize LXD (if not already done)**

```bash
lxc list 2>&1 | grep -q "error" && echo "NEED: lxd init" || echo "OK: LXD already initialized"
```

If needed:
```bash
sudo lxd init --minimal
```

After init, verify the storage pool is `dir`-backed (not a loop file):
```bash
lxc storage list
lxc storage show default | grep driver
```

If driver is `btrfs` or `zfs` (loop-backed), reconfigure:
```bash
lxc storage delete default
lxc storage create default dir source=/var/lib/lxd/storage-pools/default
```

Expected: `driver: dir`

- [ ] **Step 3: Pre-flight — stop production stack**

```bash
cd /home/administrator/Code/geographica
docker compose ps --format '{{.Names}}' 2>/dev/null | head -5
```

If any containers are listed:
```bash
docker compose down
```

Expected: No geographica containers running. **If the user declines to stop prod, ABORT the test — two stacks will OOM the Pi.**

- [ ] **Step 4: Pre-flight — check disk space**

```bash
df -h /srv/geographica | tail -1
```

Expected: >50 GB available. If less, warn and ask user whether to proceed (quick mode needs less).

- [ ] **Step 5: Pre-flight — verify LXD daemon**

```bash
lxc list
```

Expected: Empty table or existing containers listed. No errors.

---

## Task 2: Create and Configure LXC Container

- [ ] **Step 1: Delete any previous test container**

```bash
lxc delete geographica-test --force 2>/dev/null; echo "Clean"
```

- [ ] **Step 2: Launch container with Docker-in-LXC flags**

```bash
lxc launch images:debian/13 geographica-test \
  -c security.nesting=true \
  -c security.syscalls.intercept.mknod=true \
  -c security.syscalls.intercept.setxattr=true \
  -c limits.memory=14GB
```

Expected: Container starts. If it fails with a cgroup error, try adding:
```bash
lxc config set geographica-test raw.lxc "lxc.cgroup.relative = 0"
lxc restart geographica-test
```

- [ ] **Step 3: Verify container networking**

```bash
lxc exec geographica-test -- ping -c1 8.8.8.8
lxc exec geographica-test -- bash -c "apt update 2>&1 | tail -3"
```

Expected: Ping succeeds, apt update fetches package lists. If DNS fails, check `lxdbr0` configuration.

- [ ] **Step 4: Record container IP**

```bash
CONTAINER_IP=$(lxc exec geographica-test -- hostname -I | awk '{print $1}')
echo "Container IP: $CONTAINER_IP"
```

Save this — needed for Playwright screenshots and HOST_IP configuration.

- [ ] **Step 5: [QUICK ONLY] Bind-mount host data**

```bash
lxc config device add geographica-test hostdata disk \
  source=/srv/geographica/data path=/srv/geographica/data readonly=true
```

Verify:
```bash
lxc exec geographica-test -- ls /srv/geographica/data/
```

Expected: `pbf/`, `nominatim/`, `valhalla/`, `poi.sqlite`, etc.

- [ ] **Step 6: Copy repo into container**

On host:
```bash
cd /home/administrator/Code/geographica
git archive HEAD --format=tar.gz -o /tmp/geographica.tar.gz
lxc file push /tmp/geographica.tar.gz geographica-test/root/
lxc exec geographica-test -- bash -c "mkdir -p /root/geographica && tar -xzf /root/geographica.tar.gz -C /root/geographica"
rm /tmp/geographica.tar.gz
```

Verify:
```bash
lxc exec geographica-test -- ls /root/geographica/docker-compose.yml
```

Expected: File exists. **Note in report:** README step 1 (`git clone`) was replaced with tarball copy because the README uses a placeholder URL (`https://github.com/your-org/geographica.git`).

---

## Task 3: README Prerequisites (Inside Container)

From this task onward, all commands run inside the container via `lxc exec geographica-test -- bash -lc "<command>"`. For brevity, this is written as `EXEC: <command>`.

**IMPORTANT:** Each `lxc exec` is a separate process. Environment variables and `cd` do NOT persist. Always use full paths or chain commands with `&&`.

- [ ] **Step 1: Install prerequisites (README: Prerequisites)**

```bash
lxc exec geographica-test -- bash -lc "apt update && apt install -y \
  docker.io docker-compose-v2 \
  python3 python3-venv python3-pip \
  gdal-bin osmium-tool \
  gpsd gpsd-clients \
  git npm \
  wget curl unzip"
```

Expected: All packages install successfully. Record any errors — they indicate a missing package in the README.

**Note:** `wget curl unzip` are not in the README prerequisites but are used in later steps (fonts, vendor libs). If these fail to install, flag as README gap: "wget/curl/unzip needed but not listed in prerequisites."

- [ ] **Step 2: Configure Docker group (README: Prerequisites)**

```bash
lxc exec geographica-test -- bash -lc "usermod -aG docker root"
```

(Running as root inside the container, so no sudo needed.)

- [ ] **Step 3: Start Docker daemon**

```bash
lxc exec geographica-test -- bash -lc "systemctl start docker && systemctl enable docker"
```

Verify:
```bash
lxc exec geographica-test -- bash -lc "docker run --rm hello-world 2>&1 | tail -3"
```

Expected: "Hello from Docker!" If Docker fails to start, this is the cgroup v2 issue. Record the error and abort — Docker-in-LXC doesn't work with current config.

```bash
lxc exec geographica-test -- bash -lc "docker compose version"
```

Expected: `Docker Compose version v2.x.x`

---

## Task 4: README Steps 2-3 — Data Directory and Environment

- [ ] **Step 1: Create data directory (README: Step 2)**

**[QUICK MODE]** — data is bind-mounted, just create the symlink:
```bash
lxc exec geographica-test -- bash -lc "cd /root/geographica && ln -s /srv/geographica/data data"
```

**[FULL MODE]** — create fresh directories:
```bash
lxc exec geographica-test -- bash -lc "mkdir -p /srv/geographica/data/{pbf,nominatim,valhalla} && chown -R root:root /srv/geographica && cd /root/geographica && ln -s /srv/geographica/data data"
```

Verify:
```bash
lxc exec geographica-test -- bash -lc "ls -la /root/geographica/data"
```

Expected: Symlink to `/srv/geographica/data`.

- [ ] **Step 2: Configure environment (README: Step 3)**

```bash
lxc exec geographica-test -- bash -lc "cd /root/geographica && cp .env.example .env"
```

Set HOST_IP to the container's IP:
```bash
CONTAINER_IP=$(lxc exec geographica-test -- hostname -I | awk '{print $1}')
lxc exec geographica-test -- bash -lc "cd /root/geographica && sed -i 's/HOST_IP=.*/HOST_IP=${CONTAINER_IP}/' .env"
```

Verify:
```bash
lxc exec geographica-test -- bash -lc "grep HOST_IP /root/geographica/.env"
```

Expected: `HOST_IP=10.x.x.x` (container's lxdbr0 IP). **Note in report:** README says "set HOST_IP to your Pi's LAN address" — inside a container, this must be the container's IP.

---

## Task 5: README Steps 4-7 — Data Acquisition

### [QUICK MODE] — Verify Bind-Mounted Data

- [ ] **Step 1: Verify data files exist**

```bash
lxc exec geographica-test -- bash -lc "
echo '=== File verification ==='
for f in \
  /srv/geographica/data/pbf/western-us.osm.pbf \
  /srv/geographica/data/nominatim/region.osm.pbf \
  /srv/geographica/data/valhalla/western-us.osm.pbf \
  /srv/geographica/data/poi.sqlite; do
  if [ -f \"\$f\" ]; then echo \"OK: \$f\"; else echo \"MISSING: \$f\"; fi
done
# Elevation may be in tileserver/ or data/
if [ -f /srv/geographica/data/elevation.mbtiles ] || [ -f /root/geographica/tileserver/elevation.mbtiles ]; then
  echo 'OK: elevation.mbtiles'
else
  echo 'MISSING: elevation.mbtiles'
fi
"
```

Record results. Missing files mean the bind-mount doesn't cover all paths — flag as a gap.

- [ ] **Step 2: Skip steps 4-7, document in report**

Note in report:
```
## Steps Skipped (quick mode)
- Step 4: OSM download — bind-mounted from host (/srv/geographica/data/pbf/)
- Step 5: Vector basemap — bind-mounted (tileserver/southwest5.mbtiles)
- Step 6: Elevation tiles — bind-mounted
- Step 7: POI index — bind-mounted (/srv/geographica/data/poi.sqlite)
- Step 7b: OSM POI extraction — bind-mounted (same poi.sqlite)
```

### [FULL MODE] — Download and Build

- [ ] **Step 1: Download Arizona OSM data (README: Step 4)**

```bash
lxc exec geographica-test -- bash -lc "
cd /srv/geographica/data/pbf
wget 'https://download.geofabrik.de/north-america/us/arizona-latest.osm.pbf'
cp arizona-latest.osm.pbf /srv/geographica/data/nominatim/region.osm.pbf
cp arizona-latest.osm.pbf /srv/geographica/data/valhalla/
"
```

Expected: Download completes (~300 MB). If URL fails, flag as README issue.

**Note:** README shows downloading 11 states and merging with `osmium merge`. Full mode only downloads Arizona (single file, no merge needed). Note this deviation in report.

- [ ] **Step 2: Generate vector basemap (README: Step 5)**

```bash
lxc exec geographica-test -- bash -lc "
cd /root/geographica
docker run --rm \
  -e JAVA_TOOL_OPTIONS='-Xmx8g' \
  -v /srv/geographica/data/pbf:/pbf \
  -v \$(pwd)/tileserver:/data \
  ghcr.io/onthegomap/planetiler:0.10.2 \
  --download \
  --osm-path=/pbf/arizona-latest.osm.pbf \
  --output=/data/southwest5.mbtiles \
  --force
"
```

Expected: Planetiler runs, downloads Natural Earth data, produces MBTiles. Takes 10-30 min for Arizona.

- [ ] **Step 3: Set up Python venv and download elevation (README: Step 6)**

```bash
lxc exec geographica-test -- bash -lc "
cd /root/geographica
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/download_elevation.py \
  --bbox '-114.8,31.3,-109.0,37.0' \
  --zoom 0-12 \
  --output /srv/geographica/data/elevation.mbtiles
"
```

Expected: Elevation tiles download. Note: using zoom 0-12 (not 0-14) and Arizona bbox to reduce download size. Report the deviation.

- [ ] **Step 4: Build POI index (README: Step 7)**

```bash
lxc exec geographica-test -- bash -lc "
cd /root/geographica
source .venv/bin/activate
python scripts/build_poi_index.py \
  --bbox '-114.8,31.3,-109.0,37.0' \
  --states 'AZ' \
  --output /srv/geographica/data/poi.sqlite
"
```

- [ ] **Step 5: Extract OSM amenities (README: Step 7b)**

```bash
lxc exec geographica-test -- bash -lc "
cd /root/geographica
source .venv/bin/activate
python scripts/build_osm_pois.py \
  --pbf /srv/geographica/data/valhalla/arizona-latest.osm.pbf \
  --output /srv/geographica/data/poi.sqlite \
  --bbox '-114.8,31.3,-109.0,37.0'
"
```

---

## Task 6: README Steps 8-9 — Fonts, Styles, and Vendor Libraries

- [ ] **Step 1: Download fonts (README: Step 8)**

```bash
lxc exec geographica-test -- bash -lc "
cd /root/geographica
wget -O /tmp/fonts.zip https://github.com/openmaptiles/fonts/releases/download/v2.0/v2.0.zip
unzip -q /tmp/fonts.zip -d tileserver/fonts-served
rm /tmp/fonts.zip
"
```

Expected: Fonts extracted. If `wget` or `unzip` not found, flag: "README prerequisites missing wget/unzip."

- [ ] **Step 2: Download style sprites (README: Step 8)**

```bash
lxc exec geographica-test -- bash -lc "
cd /root/geographica/tileserver/styles

git clone --depth 1 https://github.com/openmaptiles/positron-gl-style.git positron-tmp
cp positron-tmp/sprite* positron/
cp -r positron-tmp/icons positron/
rm -rf positron-tmp

git clone --depth 1 https://github.com/openmaptiles/dark-matter-gl-style.git darkmatter-tmp
cp darkmatter-tmp/sprite* darkmatter/
cp -r darkmatter-tmp/icons darkmatter/
rm -rf darkmatter-tmp
"
```

Expected: Sprites and icons copied. GitHub clones succeed (requires internet).

- [ ] **Step 3: Install frontend vendor libraries (README: Step 9)**

```bash
lxc exec geographica-test -- bash -lc "
cd /root/geographica/frontend/vendor

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
"
```

Expected: Three JS libraries vendored. If `npm` not found, flag missing prerequisite.

---

## Task 7: README Steps 10-11 — GPS Override, Build, and Launch

- [ ] **Step 1: Create GPS compose override (not in README — container workaround)**

```bash
lxc exec geographica-test -- bash -lc "
cat > /root/geographica/docker-compose.override.yml << 'OVERRIDE'
services:
  gps:
    devices: []
    privileged: false
OVERRIDE
"
```

**Note in report:** This override is needed because the container lacks GPS hardware (`/dev/ttyAMA0`). The README correctly states GPS is optional and the service starts in no-fix mode, but docker-compose.yml may fail on the missing device without this override.

- [ ] **Step 2: Build Docker images (README: Step 11)**

```bash
lxc exec geographica-test -- bash -lc "
cd /root/geographica
docker compose build
docker compose --profile pipeline build
"
```

Expected: All images build successfully. This pulls base images (~10 GB first time) and builds custom services (gps, search, stt). Takes 5-15 minutes.

- [ ] **Step 3: Launch the stack (README: Step 11)**

```bash
lxc exec geographica-test -- bash -lc "
cd /root/geographica
docker compose up -d
"
```

Expected: All 7 services start. Check status:
```bash
lxc exec geographica-test -- bash -lc "cd /root/geographica && docker compose ps"
```

**[FULL MODE]:** Valhalla and Nominatim need processing time (Valhalla: ~15 min for Arizona, Nominatim: ~1-2 hours for Arizona). Monitor:
```bash
lxc exec geographica-test -- bash -lc "cd /root/geographica && docker compose logs --tail=5 valhalla"
lxc exec geographica-test -- bash -lc "cd /root/geographica && docker compose logs --tail=5 nominatim"
```

Wait for both to reach healthy status before proceeding to verification. Check periodically:
```bash
lxc exec geographica-test -- bash -lc "cd /root/geographica && docker compose ps --format '{{.Name}} {{.Health}}'"
```

**[QUICK MODE]:** Services should start quickly since data is pre-built. Nominatim may still need a few minutes to start PostgreSQL with the existing data.

---

## Task 8: README Step 12 — Verification (curl)

- [ ] **Step 1: Tile serving health check**

```bash
lxc exec geographica-test -- bash -lc "curl -sf http://localhost:8090/health && echo 'PASS: tileserver' || echo 'FAIL: tileserver'"
```

- [ ] **Step 2: Geocoding check**

```bash
lxc exec geographica-test -- bash -lc "curl -s 'http://localhost:8092/search?q=Phoenix&format=json' | python3 -m json.tool | head -20"
```

Expected: JSON response with Phoenix, AZ result. If empty, Nominatim isn't ready yet (full mode) or data is missing (quick mode).

- [ ] **Step 3: Routing check**

```bash
lxc exec geographica-test -- bash -lc "
curl -sf -X POST http://localhost:8094/route \
  -H 'Content-Type: application/json' \
  -d '{\"locations\":[{\"lat\":33.45,\"lon\":-112.07},{\"lat\":34.05,\"lon\":-111.09}],\"costing\":\"auto\"}' \
  | python3 -m json.tool | head -20
"
```

Expected: JSON route response. If Valhalla is still building, wait and retry.

- [ ] **Step 4: Search check**

```bash
lxc exec geographica-test -- bash -lc "curl -s 'http://localhost:8096/search?q=Grand+Canyon' | python3 -m json.tool | head -20"
```

- [ ] **Step 5: STT health check**

```bash
lxc exec geographica-test -- bash -lc "curl -sf http://localhost:8098/health && echo 'PASS: stt' || echo 'FAIL: stt'"
```

Note: STT may report degraded if Whisper model download is slow. Record the actual response.

- [ ] **Step 6: Record all results in report table**

For each check, record PASS/FAIL and any error output in the report's Results Summary table.

---

## Task 9: TLS Setup (Self-Signed)

- [ ] **Step 1: Generate self-signed certificates**

```bash
lxc exec geographica-test -- bash -lc "cd /root/geographica && bash scripts/generate_tls.sh"
```

Expected: Certs generated in `/srv/geographica/tls/`. If the script fails or doesn't exist, flag as README gap.

- [ ] **Step 2: Configure TLS mode in .env**

```bash
lxc exec geographica-test -- bash -lc "
cd /root/geographica
sed -i 's/TLS_MODE=.*/TLS_MODE=tls-standard/' .env
"
```

Note: Check `.env.example` for the exact TLS_MODE values. The value might be `https`, `tls-standard`, or something else. Use whatever the `.env.example` documents. If the README doesn't document self-signed TLS setup, flag this as a README gap.

- [ ] **Step 3: Restart frontend to pick up TLS**

```bash
lxc exec geographica-test -- bash -lc "cd /root/geographica && docker compose up -d frontend"
```

- [ ] **Step 4: Verify HTTPS works**

```bash
lxc exec geographica-test -- bash -lc "curl -kf https://localhost/ | head -5 && echo 'PASS: HTTPS' || echo 'FAIL: HTTPS'"
```

Expected: HTML response from NGINX over HTTPS. The `-k` flag ignores the self-signed cert.

---

## Task 10: Playwright Screenshots from Host

All screenshots are taken from the HOST machine connecting to the container's IP. The container must be running with HTTPS (from Task 9).

- [ ] **Step 1: Get container IP on host**

```bash
CONTAINER_IP=$(lxc exec geographica-test -- hostname -I | awk '{print $1}')
echo "Screenshots will target: https://${CONTAINER_IP}"
```

- [ ] **Step 2: Screenshot — Stack healthy (01)**

Use Playwright MCP `browser_navigate` to `about:blank` first, then use `browser_run_code`:

```javascript
// Navigate to docker compose ps output isn't possible in browser.
// Instead, capture the frontend loading as the "stack healthy" proof.
// The fact that the page loads means nginx + tileserver are up.
```

Actually, for `01-stack-healthy.png`, capture the terminal output instead:
```bash
lxc exec geographica-test -- bash -lc "cd /root/geographica && docker compose ps" > docs/validation/$(date +%Y-%m-%d)-${MODE}/01-stack-healthy.txt
```

This is a text file, not a screenshot. Include it in the report as a code block.

- [ ] **Step 3: Screenshot — Map loads (02)**

Use Playwright MCP `browser_navigate` to `https://${CONTAINER_IP}`. Then use `browser_run_code` to set up the context with `acceptInsecureCerts`:

Note: If the MCP Playwright tools don't support `acceptInsecureCerts` directly, use `browser_navigate` and see if it works (Playwright MCP may handle self-signed certs differently). If it fails with a cert error, fall back to HTTP (`http://${CONTAINER_IP}:8093`).

After page loads, wait for map tiles to render:
```
Use browser_wait_for with a timeout of 30 seconds, waiting for the canvas element.
```

Then use `browser_take_screenshot` to capture `02-map-loads.png`.

Save to `docs/validation/<date>-<mode>/02-map-loads.png`.

- [ ] **Step 4: Screenshot — Search results (05)**

Use `browser_fill_form` to type "Phoenix" into the search input (`#search-input`), then press Enter via `browser_press_key`.

Wait for results to appear, then `browser_take_screenshot` → `05-search-results.png`.

- [ ] **Step 5: [FULL ONLY] Screenshots — Additional milestones**

For each of these, interact with the UI and screenshot:

- **03 Dark Matter:** Click the style switcher, select Dark Matter, wait for tiles, screenshot.
- **04 Hybrid:** Click the style switcher, select Hybrid, wait for tiles, screenshot.
- **06 Spatial search:** Type "gas stations in Flagstaff" in search, press Enter, screenshot results.
- **07 Route:** Set route start (Phoenix) and end (Flagstaff), click Get Route, wait for line, screenshot.
- **08 Terrain:** Toggle 3D terrain on, tilt the view, screenshot.
- **09 Public lands:** Toggle public lands layer on, screenshot.
- **10 Admin panel:** Navigate to `https://${CONTAINER_IP}/config/`, screenshot Dashboard tab.

Each screenshot is saved to `docs/validation/<date>-<mode>/`.

**WebGL note:** If the map canvas is blank (WebGL not available in headless mode), document this as "Environment limitation: WebGL unavailable in headless Chromium inside LXC" — NOT a README bug.

- [ ] **Step 6: Geocode verification screenshot (11)**

```bash
lxc exec geographica-test -- bash -lc "
curl -s 'http://localhost:8092/search?q=Phoenix&format=json' | python3 -m json.tool
" > docs/validation/$(date +%Y-%m-%d)-${MODE}/11-geocode-verify.txt
```

Text output, not a browser screenshot.

---

## Task 11: Write the Report

- [ ] **Step 1: Create report directory**

```bash
mkdir -p docs/validation/$(date +%Y-%m-%d)-${MODE}
```

- [ ] **Step 2: Write the report file**

Create `docs/validation/<date>-<mode>-report.md` with the following structure, filled in from all observations gathered during Tasks 1-10:

```markdown
# README Validation Report — <date> (<mode>)

**Duration:** X minutes
**Container:** geographica-test (Debian 13, arm64)
**Mode:** quick | full
**Container IP:** <container_ip>

## Results Summary

| Step | Description | Status | Duration | Notes |
|------|-------------|--------|----------|-------|
| Prerequisites | apt install, Docker setup | | | |
| 1. Clone | Tarball copy (placeholder URL) | | | Flag: placeholder URL |
| 2. Data dir | mkdir + symlink | | | |
| 3. Environment | .env configuration | | | Note: HOST_IP = container IP |
| 4. OSM data | [downloaded / bind-mounted] | | | |
| 5. Basemap | [Planetiler / bind-mounted] | | | |
| 6. Elevation | [downloaded / bind-mounted] | | | |
| 7. POI index | [built / bind-mounted] | | | |
| 7b. OSM POIs | [extracted / bind-mounted] | | | |
| 8. Fonts/styles | Downloaded from GitHub | | | |
| 9. Vendor libs | npm pack | | | |
| 10. GPS | Override (no hardware) | | | Expected: no-fix mode |
| 11. Build+Launch | docker compose build/up | | | |
| 12. Verify | curl health checks | | | |
| TLS | Self-signed cert | | | |
| Screenshots | Playwright validation | | | |

## Steps Skipped (quick mode only)
[list steps that were skipped with reason]

## Ambiguities Found
[list any README instructions that were unclear, incomplete, or required interpretation]

## Errors Encountered
[list any commands that failed, with the actual error output]

## Screenshots
[embed or link each screenshot]

## TLS Notes
- Self-signed TLS tested via generate_tls.sh
- Tailscale TLS not tested (requires manual auth)
- HTTPS-dependent features validated under self-signed cert: [list which worked]

## Environment Limitations
- GPS: no hardware, started in no-fix mode (expected)
- WebGL: [rendered / software fallback / blank canvas]
- Hailo NPU: not available in container
- Git clone: used tarball copy (README has placeholder URL)

## Verdict
PASS / FAIL (with explanation of any failures)
```

- [ ] **Step 3: Commit the report and screenshots**

```bash
cd /home/administrator/Code/geographica
git add docs/validation/
git commit -m "docs: README validation report — <date> (<mode>)

<one-line summary: PASS/FAIL with key findings>"
```

---

## Task 12: Cleanup

- [ ] **Step 1: Destroy the test container**

```bash
lxc delete geographica-test --force
```

This removes the container and ALL Docker images, volumes, and data within it. Nothing leaks to the host.

- [ ] **Step 2: Optionally restart production stack**

```bash
cd /home/administrator/Code/geographica
docker compose up -d
```

Verify:
```bash
docker compose ps
```

- [ ] **Step 3: Report complete**

Present the report to the user with a summary of findings:
- Total PASS/FAIL count
- Key README gaps found
- Key ambiguities found
- Whether the README is release-ready based on the results
