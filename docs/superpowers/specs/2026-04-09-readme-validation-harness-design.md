# README Validation Harness

**Date:** 2026-04-09
**Status:** Approved (revised after 5-round adversarial review: Opus, Haiku, Codex)

## Problem

As Geographica approaches release, the README setup instructions grow stale as features are added. There's no automated way to verify that a fresh user can follow the README from step 1 through a working deployment. Manual testing is tedious and error-prone. We need a repeatable validation process that an AI agent can execute in an isolated environment without affecting the running production stack.

## Design

An LXD-based test harness that creates a clean Debian container, then has an agent follow the README setup instructions step-by-step as if it were a first-time user with no project knowledge. The agent captures screenshots at key milestones and produces a structured pass/fail report.

### Two Modes

| Mode | Data strategy | Duration (first run) | Duration (cached) | When to use |
|------|--------------|---------------------|-------------------|-------------|
| **Quick** | Bind-mount host's data read-only + overlay for writable dirs | ~30 min | ~15 min | After README edits, frequent validation |
| **Full** | Download everything from scratch (Arizona-only bbox) | Hours | Hours | Pre-release dress rehearsal |

Note: First run in either mode pulls Docker images (~10 GB, 15-30 min). Subsequent runs with a reused LXD storage pool skip image pulls.

### Host Prerequisites

One-time setup performed by the agent on first run:

1. Add current user to `lxd` group: `sudo usermod -aG lxd $USER`
2. Run `lxd init` with a **`dir`-backed storage pool** rooted on the existing SSD (avoids the undersized default loop file). Use `--minimal` but verify the pool type is `dir`, not `btrfs` or `zfs` loop.
3. Verify with `lxc list`

The agent is authorized to run these commands. If permissions are needed, the user will approve interactively.

### Pre-Flight Checks

Before launching the container, the agent MUST verify:

1. **Prod stack is stopped:** `docker compose ps` in the geographica repo — if any containers are running, abort with: "Stop the production stack first: `docker compose down`". The Pi has 16 GB RAM; running two full stacks simultaneously will OOM.
2. **Disk space:** `df -h /srv/geographica` — abort if less than 50 GB free (full mode needs ~40 GB for images + Nominatim import + tiles).
3. **LXD daemon running:** `lxc list` succeeds.

### LXC Container Configuration

```bash
lxc launch images:debian/13 geographica-test \
  -c security.nesting=true \
  -c security.syscalls.intercept.mknod=true \
  -c security.syscalls.intercept.setxattr=true
```

- **Base image:** `images:debian/13` (Trixie arm64, matches Pi's OS)
- **Container name:** `geographica-test`
- **Nesting + cgroup v2 delegation:** `security.nesting=true` alone is NOT sufficient for Docker-in-LXC on kernel 6.12 with cgroup v2. The `security.syscalls.intercept.mknod` and `security.syscalls.intercept.setxattr` flags are also required. If Docker still fails to start inside the container, add `raw.lxc: lxc.cgroup.relative = 0` as a fallback.
- **Network:** Default LXD bridge (`lxdbr0`) — container gets its own IP, routable from host. Docker port bindings inside the container do NOT conflict with host ports because LXC provides network namespace isolation.
- **Memory:** `limits.memory=14GB` — prevents the container from consuming all host RAM.
- **Storage:** `dir`-backed LXD pool on existing SSD (shares full filesystem space).

**Container network verification (run immediately after launch):**
```bash
lxc exec geographica-test -- ping -c1 8.8.8.8        # internet connectivity
lxc exec geographica-test -- apt update               # DNS + HTTPS working
```
If either fails, abort — the container can't install packages or pull images.

**Quick mode only — bind-mount + writable overlay:**
```bash
lxc config device add geographica-test hostdata disk \
  source=/srv/geographica/data path=/srv/geographica/data readonly=true
```

For services that need write access (Nominatim PostgreSQL, SQLite WAL files), the agent creates container-local copies of writable directories:
```bash
lxc exec geographica-test -- mkdir -p /srv/geographica/data-writable/nominatim
lxc exec geographica-test -- cp -a /srv/geographica/data/nominatim/* /srv/geographica/data-writable/nominatim/
```
Then uses a docker-compose override to mount the writable copy for Nominatim. Alternatively, quick mode may skip the Nominatim import entirely (the read-only database is already populated) and verify the service starts with the existing data.

### Quick Mode — File Verification Checklist

When bind-mounted data is used, the agent verifies these paths exist before proceeding:

| Path | Created by step |
|------|----------------|
| `/srv/geographica/data/pbf/western-us.osm.pbf` | Step 4 |
| `/srv/geographica/data/nominatim/region.osm.pbf` | Step 4 |
| `/srv/geographica/data/valhalla/western-us.osm.pbf` | Step 4 |
| `/srv/geographica/data/poi.sqlite` | Steps 7 + 7b |
| `/srv/geographica/data/elevation.mbtiles` or `tileserver/elevation.mbtiles` | Step 6 |

If any are missing, the agent reports the gap and continues (some services may still start without all data).

### Getting the Code Into the Container

The README step 1 uses a placeholder URL (`https://github.com/your-org/geographica.git`). Since the repo may be private and the container has no git credentials, the agent copies the code from the host:

```bash
# On host: create a tarball of the current repo (respecting .gitignore)
cd /home/administrator/Code/geographica
git archive HEAD --format=tar.gz -o /tmp/geographica.tar.gz

# Push into container
lxc file push /tmp/geographica.tar.gz geographica-test/root/

# Inside container: extract
lxc exec geographica-test -- bash -c "mkdir -p /root/geographica && tar -xzf /root/geographica.tar.gz -C /root/geographica"
```

The agent notes in the report that step 1 (git clone) was replaced with a tarball copy, and flags the placeholder URL as a README issue.

### HOST_IP Inside the Container

README step 3 says "set HOST_IP to your Pi's LAN address." Inside the container, the agent sets HOST_IP to the container's own LXD bridge IP:

```bash
CONTAINER_IP=$(lxc exec geographica-test -- hostname -I | awk '{print $1}')
lxc exec geographica-test -- sed -i "s/HOST_IP=.*/HOST_IP=${CONTAINER_IP}/" /root/geographica/.env
```

### GPS Service Handling

The docker-compose.yml maps `/dev/ttyAMA0` and `/run/gpsd.sock` into the GPS container. These devices don't exist inside LXC. The agent creates a compose override to remove hardware dependencies:

```bash
# Inside container: create override
cat > /root/geographica/docker-compose.override.yml << 'EOF'
services:
  gps:
    devices: []
    privileged: false
EOF
```

The GPS service will start in no-fix mode (no GPS data). The report notes: "GPS — started in no-fix mode (no hardware in container, expected)."

### lxc exec and Shell State

`lxc exec` runs each command as a separate process — environment variables and `cd` don't persist between calls. The agent uses `bash -lc` for commands that need shell context:

```bash
lxc exec geographica-test -- bash -lc "cd /root/geographica && source .venv/bin/activate && python scripts/build_poi_index.py ..."
```

Alternatively, install Python packages globally inside the container (no venv) to simplify command execution.

### TLS Validation

The README documents three TLS modes. The agent tests **self-signed** mode:

1. Run `scripts/generate_tls.sh` inside the container (generates certs for the container's hostname/IP)
2. Set `TLS_MODE=https` and `TLS_CERT_DIR=/srv/geographica/tls` in `.env`
3. Restart the frontend service: `docker compose up -d frontend`
4. NGINX binds port 443 with the generated cert

**Note:** The README does not currently document the self-signed TLS setup path in detail. If the agent finds the instructions insufficient, this is a valid README finding.

Tailscale TLS cannot be tested in isolation (requires Tailscale auth + domain). The report notes this as "not tested — requires manual Tailscale setup."

### Validation Screenshots

Captured via Playwright's `browser_run_code` tool (NOT `browser_navigate`) to enable `acceptInsecureCerts: true` for self-signed TLS:

```javascript
const context = await browser.newContext({ 
  acceptInsecureCerts: true,
  viewport: { width: 1280, height: 800 }
});
const page = await context.newPage();
await page.goto('https://<container-ip>');
```

**WebGL consideration:** MapLibre GL JS requires WebGL. Headless Chromium on Pi 5 may lack GPU acceleration inside LXC, causing tiles to render via software rasterization (slow) or not at all. If the map canvas is blank, the agent documents this as an environment limitation, not a README bug.

**Tile loading timing:** Before capturing map screenshots, wait for MapLibre's `idle` event:
```javascript
await page.waitForFunction(() => {
  const map = window.map;  // MapLibre instance exposed on window
  return map && map.loaded() && !map.isMoving();
}, { timeout: 30000 });
```
If the map doesn't expose `window.map`, wait for the canvas element to stabilize (no pixel changes for 2 seconds).

**Guard against testing host stack:** Before taking screenshots, verify the response is from the test container by checking the container IP matches the URL being tested. Never use the host's LAN IP.

| # | Milestone | Modes | Filename |
|---|-----------|-------|----------|
| 01 | Stack healthy (`docker compose ps`) | Both | `01-stack-healthy.png` |
| 02 | Map loads (Positron default view) | Both | `02-map-loads.png` |
| 03 | Dark Matter style | Full | `03-dark-matter.png` |
| 04 | Hybrid imagery+roads style | Full | `04-hybrid-style.png` |
| 05 | Search results ("Phoenix") | Both | `05-search-results.png` |
| 06 | Spatial search ("gas stations in Flagstaff") | Full | `06-spatial-search.png` |
| 07 | Route rendered (Phoenix → Flagstaff) | Full | `07-route-rendered.png` |
| 08 | 3D terrain view | Full | `08-terrain-3d.png` |
| 09 | Public lands layer | Full | `09-public-lands.png` |
| 10 | Admin panel Dashboard | Full | `10-admin-dashboard.png` |
| 11 | Geocode verification (curl) | Both | `11-geocode-verify.png` |

Screenshots saved to `docs/validation/<date>-<mode>/`.

### Test Report Format

Output: `docs/validation/<date>-<mode>-report.md`

```markdown
# README Validation Report — <date> (<mode>)

**Duration:** X minutes
**Container:** geographica-test (Debian 13, arm64)
**Mode:** quick | full

## Results Summary

| Step | Description | Status | Duration | Notes |
|------|-------------|--------|----------|-------|
| Prerequisites | apt install, Docker setup | PASS | 2m | |
| 1. Clone | git clone (tarball copy) | PASS | 0.5m | Placeholder URL flagged |
| ... | ... | ... | ... | |

## Steps Skipped (quick mode only)
- Step 4: OSM download — bind-mounted from host
- ...

## Ambiguities Found
- [any README instructions that were unclear or required interpretation]

## Errors Encountered
- [any commands that failed, with actual error output]

## Screenshots
![Stack healthy](01-stack-healthy.png)
...

## TLS Notes
- Self-signed TLS tested via generate_tls.sh
- Tailscale TLS not tested (requires manual auth)
- HTTPS-dependent features (STT) validated under self-signed cert

## Environment Limitations
- GPS: no hardware, started in no-fix mode (expected)
- WebGL: [rendered / software fallback / blank canvas]
- Hailo NPU: not available in container

## Verdict
PASS / FAIL (with explanation)
```

### Container Lifecycle

1. **Pre-flight:** Verify prod stack stopped, disk space, LXD running
2. **Create:** `lxc launch images:debian/13 geographica-test -c security.nesting=true -c security.syscalls.intercept.mknod=true -c security.syscalls.intercept.setxattr=true`
3. **Verify networking:** ping + apt update inside container
4. **Copy code:** `git archive` tarball pushed into container
5. **Run test:** Agent uses `lxc exec geographica-test -- bash -lc "<command>"` for each README step
6. **Screenshots:** Playwright `browser_run_code` with `acceptInsecureCerts: true` on host hits container IP
7. **Report:** Written to `docs/validation/`
8. **Cleanup:** `lxc delete geographica-test --force` — removes container and all Docker images/volumes within it

The container is disposable. Each test run starts fresh.

**Post-cleanup verification:** After deleting the container, verify no residue remains:
- `lxc list` — no containers
- `lxc image list` — delete cached Debian image if not needed (`lxc image delete <fingerprint>`)
- `ss -tlnp | grep ':809'` — only prod stack ports, no stale test bindings
- `ls /tmp/geographica*` — no temp files
- Prod stack restored: `docker compose up -d`

### Disk Estimates (Full Mode)

| Component | Size |
|-----------|------|
| Docker images (tileserver, valhalla, nominatim, custom builds) | ~10 GB |
| Arizona OSM extract | ~0.3 GB |
| Valhalla routing graph (Arizona) | ~0.5 GB |
| Nominatim import (Arizona) | ~5-10 GB |
| Elevation tiles (Arizona bbox, z0-14) | ~5 GB |
| Vector basemap (Arizona, Planetiler) | ~0.2 GB |
| POI index | ~10 MB |
| **Total** | **~25-30 GB** |

### What This Tests

- Every `apt install` package is correct
- Every `wget`/`curl` URL is reachable (full mode)
- Every script runs without errors
- Every Docker image builds successfully
- Every service starts and passes health checks
- The frontend loads and renders correctly
- Search, routing, and geocoding work end-to-end
- TLS (self-signed) works
- The README instructions are unambiguous and followable

### What This Does NOT Test

- Tailscale TLS (requires auth)
- GPS hardware integration (requires physical GPS hat)
- Hailo NPU acceleration (requires hardware)
- Performance under load
- Multi-user scenarios
- Cert distribution to clients (Playwright bypasses with acceptInsecureCerts)

### Known Environment Differences from Real Deployment

The test container differs from a real Pi deployment in these ways. These are NOT README bugs:

1. Code copied via tarball, not `git clone` (placeholder URL in README)
2. GPS runs in no-fix mode (no hardware)
3. Self-signed TLS instead of Tailscale
4. WebGL may use software rasterization (no GPU in container)
5. Smaller bbox (Arizona only) in full mode
