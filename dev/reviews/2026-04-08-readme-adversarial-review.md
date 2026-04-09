# README.md Adversarial Review -- 2026-04-08

Five-round adversarial review of the Geographica README setup guide.
Target audience: technical users deploying to a fresh Raspberry Pi OS install.

---

## Round 1 -- Fresh OS Deployer

**Persona:** Someone following the guide on a brand-new Raspberry Pi OS install (Debian Trixie or Bookworm). Looking for missing OS-level dependencies, kernel config, boot config requirements, missing kernel modules, systemd services.

### Issues Found

**1.1 [CRITICAL] No `/boot/firmware/config.txt` instructions for GPS HAT UART**

The Waveshare LC29H GPS HAT uses the Pi 5's UART (`/dev/ttyAMA0`). On a fresh Pi OS install, the primary UART is assigned to the Bluetooth modem. The README says nothing about:
- Adding `dtoverlay=disable-bt` or `dtoverlay=uart0` to `/boot/firmware/config.txt`
- Adding `enable_uart=1` to `/boot/firmware/config.txt`
- Disabling the Bluetooth modem's claim on the serial port (`sudo systemctl disable hciuart`)
- Rebooting after config.txt changes

Without these, `/dev/ttyAMA0` either doesn't exist or is consumed by Bluetooth, and `gpsd` will get garbage data or fail to open the device.

**Fix:** Add a subsection before step 10 with the required `config.txt` entries:
```
# /boot/firmware/config.txt additions for GPS HAT
enable_uart=1
dtoverlay=disable-bt  # Free /dev/ttyAMA0 from Bluetooth
```
Then `sudo reboot`.

**1.2 [MAJOR] Docker compose hardcodes `/dev/ttyAMA0` -- fails without GPS hardware**

`docker-compose.yml` line 95 has:
```yaml
devices:
  - "/dev/ttyAMA0:/dev/ttyAMA0"
```

If the user has no GPS HAT (it's listed as optional in the hardware table), `docker compose up -d` will fail with a device-not-found error. The `privileged: true` flag does not help if the device node doesn't exist.

**Fix:** Either:
- Use an environment variable (`GPS_DEVICE` is defined in `.env.example` but never referenced in `docker-compose.yml`) and make the device mapping conditional, or
- Document that users without GPS hardware must comment out the `devices:` and volume lines in the GPS service, or
- Use a docker-compose override file for GPS hardware.

**1.3 [MAJOR] GPS container mount `/run/gpsd.sock` may not exist**

`docker-compose.yml` mounts `/run/gpsd.sock:/run/gpsd.sock:ro`, but this Unix socket only exists if `gpsd` is running on the host. On a fresh install before `gpsd` is started (or if the user has no GPS), this path doesn't exist and Docker will create it as a directory, which can cause confusing errors later.

**Fix:** Document that this is only needed with GPS hardware, or make it conditional.

**1.4 [MAJOR] No mention of enabling I2C/SPI if GPS HAT uses them**

Some GPS HATs (including Waveshare models) use I2C for PPS or configuration. The README doesn't mention `raspi-config` or `dtoverlay=i2c` entries.

**Fix:** Add a note about checking the specific GPS HAT documentation for required overlays.

**1.5 [MINOR] Missing `pip install shapely` in prerequisites**

Step 7b says "Requires `osmium` and `shapely` (`pip install shapely`)" but doesn't include `shapely` in a pip install command that's part of the flow. The `scripts/requirements.txt` does include `shapely`, so if the user activated the venv from step 6, it's installed. But if they didn't, or if they're running step 7b independently, this silently fails.

**Fix:** The note is adequate since `shapely` is in `scripts/requirements.txt`, but clarify that the venv from step 6 must be active.

**1.6 [MINOR] `npm` installed but only used for `npm pack` -- `npx` alternative not mentioned**

The prerequisites install `npm` as a system package. On Debian Trixie/Bookworm, the `npm` package from apt is often extremely old (npm 9.x). The `npm pack` commands should work regardless, but it's worth noting the version doesn't matter.

**1.7 [MINOR] No mention of Docker daemon auto-start**

Fresh installs need `sudo systemctl enable docker` to ensure Docker starts on boot. The README only installs `docker.io` but doesn't enable the service.

**Fix:** Add `sudo systemctl enable docker` after the install step.

---

## Round 2 -- Literal Instruction Follower

**Persona:** Someone who does EXACTLY what the README says, nothing more. Looking for ambiguous steps, missing `cd` commands, undefined variables, copy-paste errors.

### Issues Found

**2.1 [CRITICAL] Step 4 `cd /srv/geographica/data/pbf` but step 5 uses `$(pwd)/tileserver`**

Step 4 ends with `cd -` which returns to the repo root (assuming the user was there). BUT if the user didn't `cd` into the repo after step 1's `cd geographica`, or if any intermediate step changed directories, `cd -` goes to the wrong place.

Step 5's Planetiler command uses `$(pwd)/tileserver` -- if the user is still in `/srv/geographica/data/pbf` (forgot `cd -` or it went to wrong dir), the tileserver volume mount points to a nonexistent directory and Planetiler writes the output to the wrong place.

**Fix:** Replace `cd -` with an explicit `cd ~/geographica` (or whatever the clone path is). Better: use absolute paths throughout step 4 to avoid `cd` entirely:
```bash
osmium merge /srv/geographica/data/pbf/*-latest.osm.pbf \
  -o /srv/geographica/data/pbf/western-us.osm.pbf
```

**2.2 [CRITICAL] Step 1 clone URL is a placeholder**

`git clone https://github.com/your-org/geographica.git` -- a literal follower will get a 404 from GitHub. This needs to be the actual repository URL or clearly marked as a placeholder to replace.

**Fix:** Either use the real URL or add a prominent note: "Replace `your-org` with the actual GitHub organization/user."

**2.3 [MAJOR] `.env.example` has `HOST_IP=192.168.20.122` but `HOST_IP` is never used**

The README says "set `HOST_IP` to your Pi's LAN address" but `HOST_IP` is not referenced anywhere in `docker-compose.yml` or `nginx.conf`. It appears to be a vestigial variable from an older architecture. A literal follower sets it and expects it to matter.

**Fix:** Either wire `HOST_IP` into the stack where needed, or remove it from `.env.example` and the README.

**2.4 [MAJOR] `.env.example` TLS mode values don't match `entrypoint.sh`**

`.env.example` documents TLS modes as: `http | tls-published | tls-standard`
But `entrypoint.sh` checks for: `http`, `https`, `tailscale`

A user who sets `TLS_MODE=tls-standard` (per the `.env.example` comment) gets the `else` branch in the entrypoint, which means HTTP-only mode with no error message. The self-signed cert generation never triggers.

**Fix:** Update `.env.example` comment to match actual valid values: `http | https | tailscale`.

**2.5 [MAJOR] Step 6 venv activation scope is ambiguous**

Step 6 creates and activates a venv:
```bash
python3 -m venv .venv
source .venv/bin/activate
```
Steps 7 and 7b use `python scripts/...` which requires the venv to still be active. But step 8 starts with `wget` and step 9 uses `npm pack` -- does the user need to deactivate? The guide never says. If the user opens a new terminal between steps, the venv is gone and steps 7/7b fail with missing imports.

**Fix:** Add a note: "The venv must remain active for steps 7 and 7b. If you open a new terminal, re-activate with `source .venv/bin/activate`."

**2.6 [MAJOR] Step 8 `cd tileserver/styles` then `cd ../..` -- fragile**

If any command in step 8 fails (e.g., `git clone` network error), the user is left in `tileserver/styles` and `cd ../..` may not have run. Subsequent steps assume the repo root.

**Fix:** Use absolute paths or add an explicit `cd /path/to/geographica` at the start of step 9.

**2.7 [MINOR] Step 9 `cd frontend/vendor` then `cd ../..`**

Same pattern as step 8. If any `npm pack` fails, the user is stranded in the wrong directory.

**2.8 [MINOR] Step 4 `wget` loop doesn't fail on download errors**

If a state download 404s or the network drops, the loop continues silently. The `osmium merge` will fail later with a confusing error about corrupt files.

**Fix:** Add `set -e` or `wget ... || exit 1`, or at minimum note that all downloads should be verified.

**2.9 [MINOR] The README says "7 services" but the architecture diagram shows 7 plus the pipeline**

The architecture text says "Seven Docker Compose services" but the pipeline is an 8th service (with a profile). Minor confusion for a literal reader.

---

## Round 3 -- .env and Configuration Skeptic

**Persona:** Focus on `.env` dependencies, undocumented env vars, configuration gaps.

### Issues Found

**3.1 [CRITICAL] `SCRIPTS_HOST_PATH` defaults to `/home/administrator/Code/geographica/scripts`**

`docker-compose.yml` line 125:
```yaml
SCRIPTS_HOST_PATH: "${SCRIPTS_HOST_PATH:-/home/administrator/Code/geographica/scripts}"
```

This is a hardcoded path specific to the developer's machine. Any other deployer's clone will be at a different path, and the pipeline orchestrator will fail to find scripts. The README never mentions `SCRIPTS_HOST_PATH`.

**Fix:** Either:
- Add `SCRIPTS_HOST_PATH` to `.env.example` with a note to set it to the absolute path of the scripts directory, or
- Change the default to a relative derivation that works generically.

**3.2 [MAJOR] `DATA_HOST_PATH` not documented in README or `.env.example`**

`docker-compose.yml` line 124 uses `DATA_HOST_PATH` with default `/srv/geographica/data`. This is passed to the search service for pipeline orchestration (starting Docker containers with host path mounts). It's not in `.env.example` and not mentioned in the README. If the user uses a different data directory, pipelines will fail.

**Fix:** Add `DATA_HOST_PATH` to `.env.example`.

**3.3 [MAJOR] `TLS_PORT` not documented**

`docker-compose.yml` line 178: `"${TLS_PORT:-443}:443"`. Not in `.env.example`, not in README. Port 443 requires root or `CAP_NET_BIND_SERVICE`. Docker handles this, but if the user wants a different port (e.g., 8443), they have no idea this variable exists.

**Fix:** Add `TLS_PORT=443` to `.env.example` with a comment.

**3.4 [MAJOR] `TLS_CERT_DIR` not in `.env.example`**

The Tailscale setup section tells users to `echo 'TLS_CERT_DIR=...' >> .env` but `.env.example` doesn't include this variable. The docker-compose default is `./tls` (a directory with only `.gitkeep`). If TLS_MODE is set to `https` or `tailscale` without `TLS_CERT_DIR`, the entrypoint looks in `./tls/` which has no certs.

**Fix:** Add `TLS_CERT_DIR` to `.env.example` with a comment explaining when to set it.

**3.5 [MAJOR] `STT_BACKEND` not documented in README**

`docker-compose.yml` passes `STT_BACKEND` (default: `cpu`) to the STT service. Not in `.env.example`, not explained in the README. When NPU support lands, users won't know how to switch.

**Fix:** Add `STT_BACKEND=cpu` to `.env.example` with comment: `# cpu | npu (npu requires Hailo 10H)`.

**3.6 [MAJOR] `GPS_DEVICE` defined in `.env.example` but never referenced**

`.env.example` defines `GPS_DEVICE=/dev/ttyAMA0`, but `docker-compose.yml` hardcodes the device path. The variable is dead. A user who changes `GPS_DEVICE` in `.env` will expect it to work, but it won't.

**Fix:** Either reference `${GPS_DEVICE}` in `docker-compose.yml` or remove it from `.env.example`.

**3.7 [MINOR] `POSTGRES_WORK_MEM` is in `.env.example` but the 8 GB adjustment section in the README doesn't mention it**

The README's 8 GB guidance lists `POSTGRES_SHARED_BUFFERS`, `POSTGRES_MAINTENANCE_WORK_MEM`, and `POSTGRES_EFFECTIVE_CACHE_SIZE`, but `.env.example` also has `POSTGRES_AUTOVACUUM_WORK_MEM` and `POSTGRES_WORK_MEM`. These might also need reduction for 8 GB.

**3.8 [MINOR] `BBOX` in `.env.example` is never consumed by docker-compose.yml**

`BBOX` is defined in `.env.example` but not referenced by any service in `docker-compose.yml`. It's a documentation convenience, but a skeptic would expect it to actually configure something.

**Fix:** Add a comment in `.env.example`: `# Reference only -- used manually in pipeline commands, not auto-consumed by services`.

**3.9 [MINOR] `MODEL_PATH` env var in STT service**

The STT Dockerfile bakes in the model at `/opt/models/faster-whisper-base.en`, and the code falls back to that baked path. But `MODEL_PATH=/data/models` is set in docker-compose.yml. If `/data/models` doesn't contain a model, the code silently falls back to the baked-in model. Not a bug, but undocumented behavior.

---

## Round 4 -- Storage and Filesystem Edge Cases

**Persona:** Focus on data directory setup, symlinks, permissions, disk format, Docker storage driver, large file operations.

### Issues Found

**4.1 [CRITICAL] No SSD mount instructions -- `/srv/geographica` may be on the SD card**

The README says "Create a directory on your SSD" but never tells users HOW to mount their SSD. On a fresh Pi OS install, the boot SSD may or may not be the only drive. If the user has:
- NVMe via PCIe HAT: needs `/boot/firmware/config.txt` PCIe entry (`dtparam=pciex1_gen=3`)
- SATA via USB adapter: may need `usb-storage` quirks
- A separate data SSD: needs `fstab` entry with mount options

If the SSD isn't mounted, `sudo mkdir -p /srv/geographica/data/...` creates directories on the SD card or root filesystem, and the user silently fills their boot drive with 150+ GB of data until it's full.

**Fix:** Add a section on verifying SSD mount:
```bash
lsblk                          # identify your SSD
df -h /srv/geographica         # verify it's on the SSD, not the SD card
```
And note that if using a separate data drive, it should be mounted with `noatime,discard` in `/etc/fstab`.

**4.2 [MAJOR] No mention of filesystem format recommendations**

150+ GB of data with heavy random reads (tile serving), WAL-mode SQLite, and Docker overlay2. The guide should recommend:
- `ext4` with `noatime` mount option
- `discard` mount option for SSD TRIM support (the Intel D3-S4610 supports TRIM)
- Avoiding `btrfs` due to Docker overlay2 issues on some kernels

**Fix:** Brief note on recommended filesystem: ext4, `noatime,discard`.

**4.3 [MAJOR] Symlink `data -> /srv/geographica/data/` breaks if repo is moved**

Step 2 creates a relative symlink: `ln -s /srv/geographica/data data`. This is actually an absolute symlink (target is absolute), so it survives repo moves. However, `docker-compose.yml` references `./data` which resolves through the symlink. Docker follows symlinks for bind mounts on most platforms, but this should be noted as a potential issue if Docker's storage configuration changes.

Actual risk: `docker compose` on some Docker versions does NOT follow symlinks for bind mounts (depends on the Docker storage driver and version). The `docker-compose-v2` package from Debian may behave differently from Docker's official packages.

**Fix:** Add a troubleshooting note: "If services can't see data files, verify Docker follows the symlink: `docker compose exec tileserver ls /srv/data/`"

**4.4 [MAJOR] Elevation tiles output path vs. TileServer expectation**

The README (step 6) outputs elevation tiles to `/srv/geographica/data/elevation.mbtiles`.
TileServer's `config.json` expects elevation at `/srv/data/elevation.mbtiles`.
The `./data` symlink -> `/srv/geographica/data/` is mounted as `/srv/data` in the tileserver container.

This IS correct (host `/srv/geographica/data/elevation.mbtiles` = container `/srv/data/elevation.mbtiles`), but it's non-obvious. A confused user might try to put the file in `tileserver/elevation.mbtiles` (as documented in the project structure tree at the bottom of the README, line 571: `elevation.mbtiles # Terrain tiles (gitignored, ~70 GB)`).

The project structure tree shows `elevation.mbtiles` under `tileserver/` but the setup instructions put it in `/srv/geographica/data/`. These are different locations.

**Fix:** Reconcile the project structure tree with the actual setup instructions. The tree should show `data/elevation.mbtiles` not `tileserver/elevation.mbtiles`.

**4.5 [MAJOR] Docker storage driver -- no guidance on overlay2 vs. vfs**

On Raspberry Pi OS, Docker might default to `vfs` if `overlay2` kernel support isn't available (rare on modern kernels, but possible on minimal installs). `vfs` is dramatically slower and wastes disk space.

**Fix:** Add a verification step: `docker info | grep "Storage Driver"` -- should show `overlay2`.

**4.6 [MINOR] No `tmpdir` guidance for large GDAL/Planetiler operations**

Planetiler (step 5) and the elevation/imagery pipelines create large temporary files. If `/tmp` is a tmpfs (common on Debian), a 70 GB elevation download will fail when tmp fills RAM. Planetiler defaults to `/tmp` for sort files.

**Fix:** Note that `TMPDIR` should point to the SSD if `/tmp` is a tmpfs:
```bash
export TMPDIR=/srv/geographica/tmp
mkdir -p $TMPDIR
```

**4.7 [MINOR] SQLite WAL mode and TileServer**

The troubleshooting section mentions "WAL mode from an active download" but the solution ("mount read-write") is already the default in docker-compose.yml. The real fix is to ensure the pipeline container and TileServer don't both have the file open with incompatible locking.

**4.8 [MINOR] Docker volume `nominatim-db` can grow very large**

The Nominatim PostgreSQL database lives in a Docker named volume (`nominatim-db`). This is on the Docker storage root, which is typically `/var/lib/docker/` on the boot drive. For Western US, this can be 30-40 GB. If the boot drive is a small SD card, this fills it.

**Fix:** Document that Docker's data root should be on the SSD, or use a bind mount for `nominatim-db` pointing to `/srv/geographica/data/nominatim-db/`.

---

## Round 5 -- Networking and Service Startup

**Persona:** Focus on Docker networking, port conflicts, service startup order, DNS, firewall, AREDN mesh, Tailscale, docker compose v1 vs v2.

### Issues Found

**5.1 [CRITICAL] Port 443 binding fails without root/capabilities on non-Docker-Desktop**

`docker-compose.yml` binds `${TLS_PORT:-443}:443`. On Linux (not Docker Desktop), binding to port 443 requires either:
- Running Docker as root (default, but some users configure rootless Docker)
- `net.ipv4.ip_unprivileged_port_start=0` sysctl

The default Docker daemon runs as root, so this works. But if the user has rootless Docker (increasingly common security recommendation), port 443 fails silently -- NGINX starts but HTTPS is unreachable.

**Fix:** Note in the TLS section that port 443 requires Docker running as root (default), or adjust `TLS_PORT` if using rootless Docker.

**5.2 [MAJOR] Config panel `allow 172.18.0.1/32` is Docker-network-dependent**

The NGINX config panel (line 152) allows `172.18.0.1/32`. This is the default Docker bridge gateway IP, but:
- If Docker Compose creates a custom network (which it does by default: `geographica_default`), the gateway might be `172.19.0.1`, `172.20.0.1`, etc., depending on other Docker networks on the system.
- The CIDR `/32` means it's a single IP -- if the gateway is on a different subnet, localhost access via Docker port forwarding is blocked.

**Fix:** Either use a broader allow range (`172.16.0.0/12`) or dynamically detect the gateway. Alternatively, since port 8097 is already bound to `127.0.0.1`, the NGINX allow/deny is defense-in-depth and the gateway IP mismatch would lock out even localhost access through Docker.

**5.3 [MAJOR] `docker compose` vs `docker-compose` -- Debian package name confusion**

The prerequisites install `docker-compose-v2` (Debian package name), but the README uses `docker compose` (space, v2 syntax). On some Debian versions:
- `docker-compose-v2` provides the `docker compose` subcommand (correct)
- But older Debian repos might only have `docker-compose` (v1, hyphenated, Python-based)
- On Trixie, the package may be named differently

The README correctly uses `docker compose` (space) throughout and verifies with `docker compose version`, so v1 users will catch it. But the package installation line could fail on Bookworm if `docker-compose-v2` isn't in the default repos.

**Fix:** Add a note: "If `docker-compose-v2` isn't available, install Docker's official apt repository per https://docs.docker.com/engine/install/debian/"

**5.4 [MAJOR] No firewall (ufw/iptables) guidance**

The Pi serves on ports 8093 (HTTP), 443 (HTTPS), and 8097 (config, localhost only). On AREDN mesh networks, the mesh interface may have its own firewall rules. The README doesn't mention:
- `ufw allow 8093/tcp` if ufw is enabled
- AREDN mesh interface IP conflicts (AREDN uses 10.x.x.x ranges)
- Whether Docker's iptables manipulation conflicts with AREDN's firewall

**Fix:** Add a brief networking section noting that Docker manages its own iptables rules, and if `ufw` is active, ports 8093 and 443 need to be allowed.

**5.5 [MAJOR] Service dependency: search waits for nominatim, but first-run takes 6-12 hours**

`docker-compose.yml` has `search` depending on `nominatim: condition: service_healthy`. On first run, Nominatim takes 6-12 hours to import. During this time:
- Search is completely unavailable (not just geocoding -- all POI search is down)
- The frontend loads but search/spatial features silently fail
- There's no user-visible indicator except checking `docker compose ps`

The README mentions this in the Troubleshooting section but not in the first-run instructions (step 11). A user following the guide will think the deployment is broken.

**Fix:** Add a prominent note in step 11: "The search service will NOT start until Nominatim completes its import (6-12 hours on first run). The map, tiles, GPS, and routing work immediately. Search and geocoding become available after the import."

**5.6 [MAJOR] Tailscale setup -- installation not covered**

The "HTTPS via Tailscale" section assumes Tailscale is already installed and authenticated. There's no link to Tailscale installation instructions, no `curl -fsSL https://tailscale.com/install.sh | sh`, and no mention of `tailscale up` authentication flow (which requires a browser or auth key).

**Fix:** Add: "Install Tailscale: `curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up`". Link to Tailscale docs for headless/SSH-only auth.

**5.7 [MINOR] `host.docker.internal` requires Docker 20.10+**

The GPS service uses `extra_hosts: host.docker.internal:host-gateway`. This feature requires Docker Engine 20.10 or later. The `docker.io` package on Bookworm should be recent enough, but Buster/Bullseye won't work.

**Fix:** The Docker version check (`docker compose version`) catches most issues, but add a minimum Docker version note (20.10+).

**5.8 [MINOR] Frontend depends on all services including STT**

```yaml
depends_on:
  - tileserver
  - nominatim
  - valhalla
  - gps
  - search
  - stt
```

The frontend (NGINX) depends on all services, but most of these aren't hard dependencies. NGINX has a resolver workaround for STT, but `depends_on` without `condition: service_healthy` just means "start after." If any service fails to start, the frontend still comes up -- which is correct. But the dependency list creates confusion: it doesn't mean "wait until healthy."

**5.9 [MINOR] No DNS resolution guidance for AREDN mesh**

AREDN mesh nodes use `.local.mesh` DNS suffix. If the Pi is both on AREDN and a regular LAN, DNS resolution inside Docker containers (which use Docker's internal DNS) won't resolve `.local.mesh` hostnames. This only matters if services need to reach AREDN nodes (they don't currently), but it's worth a note.

**5.10 [MINOR] gpsd TCP socket override may conflict with AREDN**

Step 10 configures gpsd to listen on `0.0.0.0:2947`. If the Pi has an AREDN mesh interface, gpsd is now accessible from the mesh network. This is probably fine (gpsd is read-only), but security-conscious deployers should know.

---

## Consolidated Issue List

Issues deduplicated and sorted by severity.

### CRITICAL (5)

| ID | Summary | Round |
|----|---------|-------|
| 1.1 | No `/boot/firmware/config.txt` UART instructions for GPS HAT | R1 |
| 4.1 | No SSD mount verification -- data may silently go to SD card | R4 |
| 2.2 | Clone URL is a placeholder (`your-org`) | R2 |
| 3.1 | `SCRIPTS_HOST_PATH` defaults to developer's home directory | R3 |
| 2.1 | `cd -` after step 4 is fragile; step 5 `$(pwd)` may resolve wrong | R2 |

### MAJOR (17)

| ID | Summary | Round |
|----|---------|-------|
| 1.2 | GPS device hardcoded -- `docker compose up` fails without GPS hardware | R1 |
| 1.3 | `/run/gpsd.sock` mount fails if gpsd not running | R1 |
| 2.3 | `HOST_IP` in `.env.example` is dead -- never referenced | R2/R3 |
| 2.4 | `.env.example` TLS mode values don't match `entrypoint.sh` (`tls-standard` vs `https`) | R2/R3 |
| 2.5 | venv activation scope ambiguous across steps 6-7b | R2 |
| 2.6 | Step 8 `cd tileserver/styles` fragile on failure | R2 |
| 3.2 | `DATA_HOST_PATH` not in `.env.example` or README | R3 |
| 3.3 | `TLS_PORT` not documented | R3 |
| 3.4 | `TLS_CERT_DIR` not in `.env.example` | R3 |
| 3.5 | `STT_BACKEND` not documented | R3 |
| 3.6 | `GPS_DEVICE` in `.env.example` but not referenced in docker-compose.yml | R3 |
| 4.2 | No filesystem format/mount option recommendations | R4 |
| 4.4 | Project structure tree shows `elevation.mbtiles` under `tileserver/` but setup puts it in `data/` | R4 |
| 4.5 | No Docker storage driver verification | R4 |
| 5.2 | Config panel `allow 172.18.0.1/32` is network-dependent | R5 |
| 5.5 | No first-run warning that search is unavailable for 6-12 hours | R5 |
| 5.6 | Tailscale installation not covered | R5 |

### MINOR (14)

| ID | Summary | Round |
|----|---------|-------|
| 1.4 | No I2C/SPI guidance for GPS HAT | R1 |
| 1.5 | `shapely` dependency implicit on venv | R1 |
| 1.6 | System npm version from apt may be old | R1 |
| 1.7 | Docker service not explicitly enabled at boot | R1 |
| 2.7 | Step 9 `cd frontend/vendor` fragile on failure | R2 |
| 2.8 | wget loop doesn't fail on download errors | R2 |
| 2.9 | "7 services" count doesn't include pipeline | R2 |
| 3.7 | 8 GB RAM guidance incomplete (missing WORK_MEM, AUTOVACUUM) | R3 |
| 3.8 | `BBOX` in `.env.example` not consumed by services | R3 |
| 3.9 | `MODEL_PATH` vs baked-in model fallback undocumented | R3 |
| 4.6 | No TMPDIR guidance for large operations | R4 |
| 4.8 | Nominatim Docker volume may fill boot drive | R4 |
| 5.7 | `host.docker.internal` requires Docker 20.10+ | R5 |
| 5.8 | Frontend `depends_on` list misleading | R5 |

### Total: 5 critical, 17 major, 14 minor = 36 issues
