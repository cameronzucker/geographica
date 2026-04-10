# Geographica — Session Start Prompt

Read this file to understand the current state of the project before beginning work.

## Project overview

Geographica is an offline-first GIS platform for AREDN amateur radio mesh networks, running on a Raspberry Pi 5 (16GB RAM, 896GB SATA SSD, GPS hat, Hailo 10H NPU). It combines aspects of Google Earth and Google Maps while being entirely self-hostable and offline-capable after initial data download.

**Owner:** Cameron Zucker (cameronzucker@gmail.com)
**Repo:** /home/administrator/Code/geographica (branch: dev)

## Critical context — read before making any changes

1. **Read MEMORY.md** at `~/.claude/projects/-home-administrator-Code-geographica/memory/MEMORY.md` — it indexes all session handoffs. Read BOTH:
   - `handoff_20260410.md` — setup wizard, LXD validation, docs overhaul (parallel agent)
   - `handoff_20260409f.md` — public lands, hybrid imagery, camera fix, M2M pipeline improvements, style tuning (this agent's mega session — 120+ commits)

2. **Read CLAUDE.md** in the repo root — it has the project structure, commands, hardware specs, and skill routing rules.

3. **Read TODOS.md** in the repo root — it has the full feature backlog with completed items, priorities, and context.

4. **Data lives OUTSIDE the repo** at `/srv/geographica/data/` (symlinked from `data/`). Never create large files inside the git repo tree. See `feedback_data_outside_repo.md` in memory.

5. **Git push doesn't work from terminal** — user syncs via VS Code UI. See `feedback_git_push.md` in memory. Git config: name "Cameron Zucker", email cameronzucker@gmail.com.

6. **Never stop the production stack** (`docker compose down`) without explicit user permission. See `feedback_prod_stack.md` in memory.

## Current system state

### Running services (Docker Compose)
- **TileServer GL** (:8090) — vector basemap + elevation + aerial imagery + public lands
- **Valhalla** (:8094) — routing engine, 11 Western US states
- **Nominatim** (:8092) — geocoding, 11 Western US states imported
- **GPS** (:8095) — FastAPI WebSocket, reads Pi's GPS hat via gpsd
- **Search** (:8096) — spatial search (intent parser, corridor, proximity, city-aware) + admin API + pipeline orchestration
- **STT** (:8098) — Whisper base.en (CPU + NPU backends), push-to-hold mic button
- **NGINX/Frontend** (:8093 HTTP, :443 HTTPS) — main app + config panel on localhost:8097

### Setup wizard (2026-04-10)
- `bootstrap.sh` — system prerequisites (sudo): apt install, docker group, data dir
- `setup.sh` — launches browser-based setup wizard on localhost:8099
- `setup/` — FastAPI app with CSRF, WebSocket progress, 5-step guided deployment
- Dark mode, MapLibre region picker, skip-all for networking-only deployments
- Spec: `docs/superpowers/specs/2026-04-10-setup-wizard-design.md`

### LXD validation harness (2026-04-10)
- Automated README testing in isolated Debian 13 LXC containers
- Quick mode (~15 min, bind-mount data, works WITH prod stack running)
- Full mode (hours, downloads everything from scratch)
- Spec: `docs/superpowers/specs/2026-04-09-readme-validation-harness-design.md`
- Reports: `docs/validation/2026-04-09-quick-report.md`, `docs/validation/2026-04-10-quick-report.md`

### Active imagery downloads (started 2026-04-09)
**M2M sequential pipeline running in Docker** (check: `tail -5 /tmp/m2m-sequential.log`):
- Stage 1: Arizona z0-z16 — IN PROGRESS (~16,442 scenes, pipelined batch download+conversion)
- Stage 2: Maricopa z17 — queued (starts after Arizona)
- Stage 3: Phoenix metro z18-z19 — queued (starts after Maricopa)
- Tile scraper z0-z14 Western US — COMPLETE (25 GB, `/srv/geographica/data/imagery.mbtiles`)
- Output files: `imagery.mbtiles` (scraper), `imagery_az.mbtiles`, `imagery_maricopa.mbtiles`, `imagery_phoenix.mbtiles`
- **After all complete:** merge with `tile-join -o imagery_merged.mbtiles imagery.mbtiles imagery_az.mbtiles imagery_maricopa.mbtiles imagery_phoenix.mbtiles`
- Per-file progress visible in admin panel. Pipeline converts+deletes GeoTIFFs per batch (~15 GB staging max).

### Data
- **Elevation z0-14**: 1,474,959 tiles (~120 GB)
- **Imagery z0-14**: 25 GB tile scraper (z15+ downloading via M2M — see above)
- **Public lands**: 1,077,968 tiles (412MB, PAD-US 4.1 + AIANNH tribal, 365 tribal boundaries)
- **POI index**: 304,094 GNIS features + OSM amenities
- **Vector basemap**: 2.4GB (southwest5.mbtiles — needs regeneration for minor road visibility, see TODOS)

### TLS
- **Tailscale HTTPS active**: `https://pandora.twin-bramble.ts.net` (Let's Encrypt)
- Dual-mode: HTTP on :8093 (LAN/AREDN) + HTTPS on :443 (Tailscale)

### Tests
396 tests across project. Run: `python -m pytest tests/ -v`

Key test files:
- `tests/test_intent_parser.py` (54) — spatial search intent parsing + city-aware extraction
- `tests/test_setup_config.py` (25) — system detection, .env generation, bbox validation
- `tests/test_setup_main.py` (23) — FastAPI wizard endpoints, CSRF
- `tests/test_setup_runner.py` (17) — subprocess runner, checkpoint management
- `tests/test_geocode.py` (10) — city geocoding with position-biased cache
- `tests/test_spatial_endpoint.py` (15) — spatial search endpoint integration
- `tests/test_spatial_osm.py` (21) — OSM POI search
- `tests/test_corridor.py` (19) — corridor math

### Key files
- `docker-compose.yml` — 7 persistent services + pipeline
- `setup/main.py` — Setup wizard FastAPI app (CSRF, WebSocket, API routes)
- `setup/config.py` — System detection, .env generation, RAM profiles
- `setup/runner.py` — Async subprocess executor, checkpoint management
- `services/search/spatial.py` — Intent parser, corridor math, city-aware geocoding
- `services/search/geocode.py` — Async geocode helper with position-biased cache
- `services/search/main.py` — Search API, admin API, pipeline orchestration
- `frontend/app.js` — Main frontend (~3900 lines)
- `scripts/build_public_lands.py` — PAD-US public lands pipeline
- `docs/pitfalls/implementation-pitfalls.md` — 13 pitfalls
- `docs/pitfalls/testing-pitfalls.md` — 8 testing pitfalls

## What to work on next

See TODOS.md for the full backlog. Top priorities:

### High priority
- **Credential management overhaul** — unify credentials.json + .env into one source of truth
- **USB GPS support** — auto-detect /dev/ttyUSB*, /dev/ttyACM* alongside HAT
- **Regenerate vector basemap** — Planetiler custom profile for minor road visibility at lower zoom
- **Relax Nominatim dependency** — change service_healthy to service_started in docker-compose.yml

### Medium priority
- **Full LXD dress rehearsal** — run validation harness in full download mode
- **Remove npm prerequisite** — replace remaining npm references with direct wget
- **Enable cgroup memory limits** — add kernel parameters to /boot/firmware/cmdline.txt
- **NGINX selective compression** — compress PBF tiles over mesh

### Blocked
- **Whisper NPU backend** — blocked on hailo-10-all 5.3.0 for Pi 5

## Key architectural details

1. **Setup wizard security:** CSRF token generated at startup, validated on all POST endpoints. CORS restricted to localhost. Credential path hardcoded (never from client). Binds localhost:8099 only.

2. **City-aware search:** `_extract_place()` uses space-bounded "in" detection (NOT `\b` word boundary). Compound phrase table prevents splitting on "drive-in". Geocode cache keyed by (name, position_bucket) to prevent cross-city contamination.

3. **LXD validation:** Quick mode needs `security.nesting=true`, `security.syscalls.intercept.mknod=true`, `security.syscalls.intercept.setxattr=true` for Docker-in-LXC. Works with prod stack running (6GB container limit).

4. **Vendor JS committed:** `frontend/vendor/` contains maplibre-gl.js, togeojson.js, jszip.min.js, dompurify.min.js. No npm needed. Update via wget from npm registry.

5. **Pipeline container detection uses wildcard.** `_is_pipeline_container_running()` matches `geographica-pipeline*`.

6. **admin_status() is fully async.** All blocking calls use `asyncio.to_thread()`.

7. **GPS /status endpoint omits coordinates.** Security invariant: lat/lon never in admin responses.

8. **Hybrid imagery mode uses map.setStyle().** Toggling imagery ON swaps to `STYLES.hybrid`, OFF restores `previousStyle`. The persistent `map.on('style.load')` handler replays all overlays AND removes mouseRotate/mousePitch handlers from MapLibre's internal `_handlers._handlersById` (Pitfall #11). `NavigationControl` uses `showCompass: false`. NAIP/Sentinel toggles hidden in hybrid mode.

9. **MapLibre dragRotate: disable() is INSUFFICIENT in v5.21.** Must surgically delete `mouseRotate` and `mousePitch` from `map._handlers._handlersById` and filter from `_handlers` array. Done in BOTH `initFreeLookCamera()` AND the `style.load` handler. See Pitfall #11 for 7 documented failed approaches.

10. **M2M pipeline: pipelined batch processing.** Downloads batch N+1 while converting batch N. Per-file progress updates to state file for admin panel. Raw GeoTIFFs deleted after each batch conversion (~15-30 GB staging max). Runs in Docker with `GDAL_CACHEMAX=1024`.

11. **Docker cgroup memory limits NOT enforced** on default Pi OS. Add `cgroup_enable=memory cgroup_memory=1` to `/boot/firmware/cmdline.txt` and reboot. Without this ALL Docker `memory:` limits are silently ignored.

12. **HTTP/2 enabled on HTTPS** (`listen 443 ssl http2` in `nginx/tls-include.conf`). Required to prevent browser connection pool contention (search requests queued behind tile fetches on HTTP/1.1).

13. **Geocode timeout is 5 seconds** (`services/search/geocode.py:69`). Was 1s, causing all city-aware searches to fail (Nominatim cold queries take 1.3s+).

14. **Sentinel-2 pipeline exists but is UNTESTED.** Only M2M and direct tile scraper are confirmed working imagery modes.

15. **Public lands uses 3 fill layers.** Non-tribal solid (`public-lands-fill`), tribal striped pattern (`public-lands-fill-tribal`), outline. All toggle together. In hybrid mode, z-order anchor finds first `transportation` source-layer to insert below roads.

16. **Public lands pipeline runs on HOST, not Docker.** Requires Tippecanoe (built from source on ARM64) + ogr2ogr. PAD-US download needs browser CAPTCHA. Census AIANNH is direct download (~9 MB). Stop Docker services for full build (~6-9 GB RAM).

17. **NGINX bind mount footgun:** Git operations create new file inodes — Docker serves stale config. Always `--force-recreate frontend` after editing NGINX config.

## Cameron's preferences (from memory)
- Prioritizes correctness and completeness over speed
- Values robust adversarial review (multiple rounds, cross-model) before implementing
- Prefers full brainstorm → adversarial → plan → TDD execution workflow
- Data must stay outside the git repo at /srv/geographica/data/
- UI elements bounded to ~800px max-width (not edge-to-edge)
- Never stop prod stack without asking
- Dark mode support expected on new UI features
