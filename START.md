# Geographica — Session Start Prompt

Read this file to understand the current state of the project before beginning work.

## Project overview

Geographica is an offline-first GIS platform for AREDN amateur radio mesh networks, running on a Raspberry Pi 5 (16GB RAM, 896GB SATA SSD, GPS hat, Hailo 10H NPU). It combines aspects of Google Earth and Google Maps while being entirely self-hostable and offline-capable after initial data download.

**Owner:** Cameron Zucker (cameronzucker@gmail.com)
**Repo:** /home/administrator/Code/geographica (branch: dev)

## Critical context — read before making any changes

1. **Read MEMORY.md** at `~/.claude/projects/-home-administrator-Code-geographica/memory/MEMORY.md` — it indexes all session handoffs. Start with the most recent:
   - `handoff_20260414c.md` — gh auth, keyring, nav 14-bug fix, setup improvements, imagery 11-bug fix, export bundle
   - `handoff_20260414b.md` — Bug hunt (9 fixes), concurrent downloads, cancel fix, retry hardening
   - `handoff_20260414.md` — NAIP research, National Map mode, NOAA pipeline + BYO import

2. **Read CLAUDE.md** in the repo root — it has the project structure, commands, hardware specs, and skill routing rules.

3. **Read TODOS.md** in the repo root — it has the full feature backlog with completed items, priorities, and context.

4. **Data lives OUTSIDE the repo** at `/srv/geographica/data/` (symlinked from `data/`). Never create large files inside the git repo tree.

5. **Git push works from terminal** — `gh auth git-credential` is configured. Push freely.

6. **Never stop the production stack** (`docker compose down`) without explicit user permission.

## Current system state

### Running services (Docker Compose)
- **TileServer GL** (:8090) — vector basemap + elevation + aerial imagery + public lands
- **Valhalla** (:8094) — routing engine, 11 Western US states
- **Nominatim** (:8092) — geocoding, 11 Western US states imported
- **GPS** (:8095) — FastAPI WebSocket, reads Pi's GPS hat via gpsd
- **Search** (:8096) — spatial search (intent parser, corridor, proximity, city-aware) + admin API + pipeline orchestration
- **STT** (:8098) — Whisper base.en (CPU + NPU backends), push-to-hold mic button
- **NGINX/Frontend** (:8093 HTTP, :443 HTTPS) — main app + config panel on localhost:8097

### Setup wizard
- `bootstrap.sh` — system prerequisites (sudo): apt install, docker group, data dir
- `setup.sh` — launches browser-based setup wizard on localhost:8099
- `setup/` — FastAPI app with CSRF, WebSocket progress, 5-step guided deployment
- **New (2026-04-14):** Custom storage path input with allowlist validation, pre-flight dependency checker with auto-fix buttons (FIX_REGISTRY, no shell injection), categorized pipeline error handling with exponential backoff
- Dark mode, MapLibre region picker, skip-all for networking-only deployments

### Navigation system (2026-04-14 overhaul — 14 bugs fixed + compass button)
The turn-by-turn navigation system was extensively field-tested and bug-hunted. Major changes:
- **Event-driven GPS feed** — replaced 500ms polling with callback from GPS WebSocket (was causing double-processing)
- **Off-route detection** — 3-of-5 rolling window with hysteresis (50m enter, 35m exit)
- **Reroute recovery** — 10s engine timeout + 3 retries with exponential backoff
- **Voice announcements** — 5s cooldown, 2 m/s speed gate (50m near-maneuver exemption), mute-aware thresholds
- **GPS position** — offset below nav overlay with dynamic padding + 5px hysteresis
- **Compass button** — global north-up button, rotates with bearing, avoids Pitfall #11
- **Mobile layout** — sidebar/search repositioned below nav overlay via `body.nav-active`
- Bug hunt reports: `dev/bug-hunts/2026-04-14-navigation-*.md`

### Imagery pipeline (2026-04-14 overhaul — 11 bugs fixed)
The imagery acquisition pipeline was bug-hunted after a job got stuck "stopping" for over an hour. Major changes:
- **Interruptible GDAL** — new `scripts/gdal_subprocess.py` using Popen + os.setsid process groups + signal forwarding (was: subprocess.run blocked SIGTERM indefinitely)
- **Batch MBTiles merge** — per-batch conversion to temp MBTiles + SQLite ATTACH append (was: each batch overwrote the output, only last batch survived)
- **Streaming downloads** — iter_chunked(64KB) to disk (was: resp.read() loading entire multi-GB files into 2GB container)
- **Sentinel concurrent downloads** — asyncio.gather with semaphore (was: sequential despite semaphore)
- **Token refresh** — Sentinel OAuth2 token refreshed inside retry loop (was: stale token after 10min)
- Plus: atomic checkpoints, UnboundLocalError fix, poll math fix, NAIP concurrency wired up
- Bug hunt reports: `dev/bug-hunts/2026-04-14-imagery-pipeline-*.md`
- **The stuck imagery job was killed. Needs re-run with the new fixes.**

### LXD validation harness
- Automated README testing in isolated Debian 13 LXC containers
- Quick mode (~15 min, bind-mount data, works WITH prod stack running)
- Full mode (hours, downloads everything from scratch)

### Imagery downloads status
- The M2M sequential pipeline was killed (stuck gdal_translate). Needs restart with fixed code.
- Tile scraper z0-z14 Western US — COMPLETE (25 GB)
- **After re-running pipeline:** merge with `tile-join -o imagery_merged.mbtiles imagery.mbtiles imagery_az.mbtiles imagery_maricopa.mbtiles imagery_phoenix.mbtiles`

### Data
- **Elevation z0-14**: 1,474,959 tiles (~120 GB)
- **Imagery z0-14**: 25 GB tile scraper (z15+ needs re-run via fixed M2M pipeline)
- **Public lands**: 1,077,968 tiles (412MB, PAD-US 4.1 + AIANNH tribal, 365 tribal boundaries)
- **POI index**: 304,094 GNIS features + OSM amenities
- **Vector basemap**: 2.4GB (southwest5.mbtiles — needs regeneration for minor road visibility, see TODOS)

### TLS
- **Tailscale HTTPS active**: `https://pandora.twin-bramble.ts.net` (Let's Encrypt)
- Dual-mode: HTTP on :8093 (LAN/AREDN) + HTTPS on :443 (Tailscale)

### Tests
446 tests across project. Run: `python -m pytest tests/ -v`

Key test files:
- `tests/test_intent_parser.py` (54) — spatial search intent parsing + city-aware extraction
- `tests/test_setup_config.py` (39+) — system detection, .env generation, bbox validation, path validation
- `tests/test_setup_main.py` (31+) — FastAPI wizard endpoints, CSRF, preflight, fix-dependency
- `tests/test_setup_runner.py` (17) — subprocess runner, checkpoint management
- `tests/test_gdal_subprocess.py` (9) — interruptible GDAL subprocess management
- `tests/test_mbtiles_merge.py` (6) — batch-level MBTiles merge via SQLite
- `tests/test_acquire_imagery_streaming.py` (6) — streaming download to disk
- `tests/test_acquire_imagery_fixes.py` (6) — UnboundLocalError, atomic checkpoint, poll math
- `tests/test_sentinel_fixes.py` (2) — token refresh, concurrent downloads
- `tests/test_naip_concurrency.py` (3) — concurrency parameter wiring
- `tests/test_geocode.py` (10) — city geocoding with position-biased cache
- `tests/test_spatial_endpoint.py` (15) — spatial search endpoint integration
- `tests/test_spatial_osm.py` (21) — OSM POI search
- `tests/test_corridor.py` (19) — corridor math

### Key files
- `docker-compose.yml` — 7 persistent services + pipeline
- `setup/main.py` — Setup wizard FastAPI app (CSRF, WebSocket, path validation, preflight, fix registry)
- `setup/config.py` — System detection, .env generation, RAM profiles, validate_path
- `setup/runner.py` — Async subprocess executor, checkpoint management
- `services/search/spatial.py` — Intent parser, corridor math, city-aware geocoding
- `services/search/main.py` — Search API, admin API, pipeline orchestration
- `frontend/app.js` — Main frontend (~3900 lines), compass button, costing propagation
- `frontend/navigation.js` — Navigation engine (off-route, reroute, voice, dead reckoning)
- `frontend/nav-ui.js` — Navigation UI (event-driven GPS, padding, heading, mobile layout)
- `scripts/acquire_imagery.py` — M2M/TNMAccess/Sentinel orchestrator, batch MBTiles merge
- `scripts/gdal_subprocess.py` — Shared interruptible GDAL subprocess module
- `scripts/acquire_naip.py` — NAIP M2M download with streaming + concurrency
- `scripts/acquire_sentinel.py` — Sentinel-2 download with token refresh + concurrent
- `docs/pitfalls/implementation-pitfalls.md` — 13 pitfalls
- `docs/pitfalls/testing-pitfalls.md` — 12 testing pitfalls

### Custom skills
- `~/.claude/skills/build-robust-features/` — Brainstorm → adversarial → subagent-proof plan
- `~/.claude/skills/gstack/` — Full gstack toolkit
- `.claude/skills/bug-hunt-cycle/` — 3-hunter parallel dispatch + consolidation
- `.claude/skills/code-bug-hunter-*/` — Exploratory, holistic, multipass analysis
- `.claude/skills/lxd-validation/` — LXD container doc testing

## What to work on next

See TODOS.md for the full backlog. Top priorities:

### Immediate
- **Re-run imagery pipeline** — The stuck M2M job was killed. Rebuild the pipeline container and re-run with the fixed code (interruptible GDAL, batch merge, streaming downloads)
- **Merge dev to main** — dev is ahead with all the fixes from this session

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

1. **Setup wizard security:** CSRF token generated at startup, validated on all POST endpoints. CORS restricted to localhost. Credential path hardcoded (never from client). Binds localhost:8099 only. Path validation uses ALLOWLIST (/srv, /mnt, /media, /home). Fix-dependency uses FIX_REGISTRY (no shell=True, no user strings in subprocess).

2. **City-aware search:** `_extract_place()` uses space-bounded "in" detection (NOT `\b` word boundary). Compound phrase table prevents splitting on "drive-in". Geocode cache keyed by (name, position_bucket) to prevent cross-city contamination.

3. **Navigation engine architecture:** Event-driven GPS feed from WebSocket callback (NOT polling). Engine (`navigation.js`) computes all state (heading validity at 3 m/s gate, off-route with hysteresis, voice thresholds). UI (`nav-ui.js`) consumes engine state for map bearing, padding, and instructions. Voice has 5s global cooldown + 2 m/s speed gate with 50m near-maneuver exemption.

4. **GDAL subprocess management:** All GDAL calls go through `scripts/gdal_subprocess.py` which uses Popen + os.setsid process groups. SIGTERM is forwarded via os.killpg. Configurable timeouts. The `_cancel_requested` global is checked between poll cycles.

5. **MBTiles batch merge:** M2M pipeline converts each batch to a temp MBTiles, then merges into the main output via SQLite ATTACH + INSERT OR REPLACE. Overviews (gdaladdo) run once at the end, not per batch. This keeps memory bounded and allows interruption between batches.

6. **Compass button (Pitfall #11 safe):** Custom button using map.easeTo({ bearing: 0 }). Does NOT use NavigationControl compass (which re-enables dragRotate). Does NOT call dragRotate.enable/disable. During navigation, compass click pauses auto-center for 10s.

7. **LXD validation:** Quick mode needs `security.nesting=true`, `security.syscalls.intercept.mknod=true`, `security.syscalls.intercept.setxattr=true` for Docker-in-LXC. Works with prod stack running (6GB container limit).

8. **Vendor JS committed:** `frontend/vendor/` contains maplibre-gl.js, togeojson.js, jszip.min.js, dompurify.min.js. No npm needed.

9. **Hybrid imagery mode uses map.setStyle().** The persistent `style.load` handler replays all overlays AND removes mouseRotate/mousePitch handlers from MapLibre's internal `_handlers._handlersById` (Pitfall #11).

10. **Docker cgroup memory limits NOT enforced** on default Pi OS. Add `cgroup_enable=memory cgroup_memory=1` to `/boot/firmware/cmdline.txt` and reboot.

11. **HTTP/2 enabled on HTTPS** (`listen 443 ssl http2` in `nginx/tls-include.conf`).

12. **Public lands uses 3 fill layers.** Non-tribal solid, tribal striped pattern, outline. Pipeline runs on HOST (requires Tippecanoe + ogr2ogr).

## Cameron's preferences (from memory)
- Prioritizes correctness and completeness over speed
- Values robust adversarial review (multiple rounds, cross-model) before implementing
- Prefers full brainstorm → adversarial → plan → TDD execution workflow (see build-robust-features skill)
- Data must stay outside the git repo at /srv/geographica/data/
- UI elements bounded to ~800px max-width (not edge-to-edge)
- Never stop prod stack without asking
- Dark mode support expected on new UI features
- Terminal git push works (gh CLI configured)

## Environment export

A portable bundle of Claude Code configuration exists at `~/claude-code-export/` for migrating to Cameron's laptop. See `~/claude-code-export/MANIFEST.md` for contents. Run `bash export.sh` on the target machine.
