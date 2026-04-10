# Geographica — Session Start Prompt

Read this file to understand the current state of the project before beginning work.

## Project overview

Geographica is an offline-first GIS platform for AREDN amateur radio mesh networks, running on a Raspberry Pi 5 (16GB RAM, 896GB SATA SSD, GPS hat, Hailo 10H NPU). It combines aspects of Google Earth and Google Maps while being entirely self-hostable and offline-capable after initial data download.

**Owner:** Cameron Zucker (cameronzucker@gmail.com)
**Repo:** /home/administrator/Code/geographica (branch: dev)

## Critical context — read before making any changes

1. **Read MEMORY.md** at `~/.claude/projects/-home-administrator-Code-geographica/memory/MEMORY.md` — it indexes all session handoffs, user preferences, and project decisions. Read `handoff_20260410.md` for the most recent session context (setup wizard, LXD validation, docs overhaul).

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

### Data — all complete
- **Elevation z0-14**: 1,474,959 tiles
- **Imagery z0-16**: 2,588,818 tiles
- **Public lands**: 1,077,968 tiles (412MB, PAD-US 4.1 + AIANNH tribal)
- **POI index**: 304,094 GNIS features + OSM amenities
- **Vector basemap**: 2.4GB (southwest5.mbtiles)

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

8. **Hybrid imagery mode uses map.setStyle().** Must re-disable dragRotate after style swap (Pitfall #11).

9. **Public lands uses 3 fill layers.** Non-tribal solid, tribal striped pattern, outline.

10. **NGINX bind mount footgun:** Git operations create new file inodes — Docker serves stale config. Always `--force-recreate frontend` after editing NGINX config.

## Cameron's preferences (from memory)
- Prioritizes correctness and completeness over speed
- Values robust adversarial review (multiple rounds, cross-model) before implementing
- Prefers full brainstorm → adversarial → plan → TDD execution workflow
- Data must stay outside the git repo at /srv/geographica/data/
- UI elements bounded to ~800px max-width (not edge-to-edge)
- Never stop prod stack without asking
- Dark mode support expected on new UI features
