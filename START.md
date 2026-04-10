# Geographica — Session Start Prompt

Read this file to understand the current state of the project before beginning work.

## Project overview

Geographica is an offline-first GIS platform for AREDN amateur radio mesh networks, running on a Raspberry Pi 5 (16GB RAM, 896GB SATA SSD, GPS hat, Hailo 10H NPU). It combines aspects of Google Earth and Google Maps while being entirely self-hostable and offline-capable after initial data download.

**Owner:** Cameron Zucker (cameronzucker@gmail.com)
**Repo:** /home/administrator/Code/geographica (branch: dev)
**Design doc:** ~/.gstack/projects/geographica/administrator-dev-design-20260407-021424.md

## Critical context — read before making any changes

1. **Read MEMORY.md** at `~/.claude/projects/-home-administrator-Code-geographica/memory/MEMORY.md` — it indexes all session handoffs, user preferences, and project decisions. Read `handoff_20260409e.md` for the most recent session context (mega session: public lands, hybrid imagery, camera fix, style tuning).

2. **Read CLAUDE.md** in the repo root — it has the project structure, commands, hardware specs, and skill routing rules.

3. **Read TODOS.md** in the repo root — it has the full feature backlog with completed items, priorities, and context.

4. **Data lives OUTSIDE the repo** at `/srv/geographica/data/` (symlinked from `data/`). Never create large files inside the git repo tree. See `feedback_data_outside_repo.md` in memory.

5. **Git push doesn't work from terminal** — user syncs via VS Code UI. See `feedback_git_push.md` in memory. Git config: name "Cameron Zucker", email cameronzucker@gmail.com.

## Current system state

### Running services (Docker Compose)
- **TileServer GL** (:8090) — vector basemap + elevation (z0-14 complete) + aerial imagery (z0-16 complete)
- **Valhalla** (:8094) — routing engine, 11 Western US states
- **Nominatim** (:8092) — geocoding, 11 Western US states imported
- **GPS** (:8095) — FastAPI WebSocket, reads Pi's GPS hat via gpsd (0.36% CPU after busy-wait fix)
- **Search** (:8096) — spatial search (intent parser, corridor, proximity) + admin API + pipeline orchestration
- **STT** (:8098) — Whisper base.en CPU backend, push-to-hold mic button. Deployed and working on HTTP + HTTPS. NGINX uses resilient resolver pattern (frontend stays up if STT is down).
- **NGINX/Frontend** (:8093 HTTP, :443 HTTPS) — main app + config panel on localhost:8097

### Recently deployed (2026-04-09 mega session — 104 commits)

**Public Lands Overlay:**
- PAD-US 4.1 + Census AIANNH tribal boundaries, togglable fill overlay with 10 agency categories
- 412MB MBTiles, 1,077,968 tiles, 75,877 features (BLM, USFS, NPS, FWS, DOD, USBR, Tribal, State, Wilderness, Other)
- Tribal lands render with diagonal stripe pattern for visual distinction
- Legend with category swatches and footnotes (Military: restricted, Tribal: incomplete)
- Public land info merged into normal click popup (badge + name + agency — doesn't replace reverse geocode)
- Pipeline: `scripts/build_public_lands.py` (ogr2ogr + Tippecanoe, runs on HOST not Docker)

**Hybrid Imagery+Roads Mode:**
- Pre-authored MapLibre style: `tileserver/styles/hybrid/style.local.json` (35 layers)
- Imagery raster base + roads/labels/boundaries with Google Maps-inspired subtle rendering
- Smart imagery toggle: checkbox triggers `map.setStyle()` swap to/from hybrid
- Trunk roads (US-93, US-95) included with motorway filter
- Zoom-dependent road visibility: only motorways at z11, major roads z13, minor z13, labels z14-15
- Persistent `map.on('style.load')` handler replaces scattered `once()` calls
- Hybrid-aware guards in addPlaceholderSources + syncLayerVisibility + public lands z-order anchor

**Camera Free-Look Fix:**
- CTRL+drag free-look restored from original commit 3be5183
- Root cause: `map.dragRotate.disable()` must be called after every style swap (MapLibre resets it)
- Documented as Implementation Pitfall #11 with 6 failed approaches listed

**Parallel Agent Work (also deployed):**
- Sentinel-2 + NAIP imagery pipelines with admin panel integration
- City-aware spatial search ("gas stations in Flagstaff")
- Credential management fixes
- County boundary database for pipeline region detection

### Data downloads — all complete
- **Elevation z0-14**: 1,474,959 tiles — complete
- **Imagery z0-16**: 2,588,818 tiles — complete
- **Public lands**: 1,077,968 tiles — complete (412MB, PAD-US 4.1 + AIANNH tribal)
- **POI index**: 304,094 GNIS features — complete
- **OSM POIs**: Deployed

### TLS
- **Tailscale HTTPS active**: `https://pandora.twin-bramble.ts.net` (Let's Encrypt, valid until 2026-07-07)
- Systemd timer for daily cert renewal: `systemctl status geographica-tls-renew.timer`
- Dual-mode: HTTP on :8093 (LAN/AREDN) + HTTPS on :443 (Tailscale)

### Key files
- `docker-compose.yml` — 8 services (7 + pipeline with profiles), includes STT service
- `nginx/nginx.conf` — main app + config panel server blocks, sub_filter for TileJSON (including publiclands, imagery_naip, imagery_sentinel), /stt/ resilient proxy
- `tileserver/config.json` — 4 data sources (southwest5, elevation, imagery, publiclands), 3 styles (positron, darkmatter, hybrid)
- `tileserver/styles/hybrid/style.local.json` — hybrid imagery+roads style (35 layers, imagery base + vector roads/labels)
- `services/search/main.py` — Nominatim/POI/OSM POI query, admin API, pipeline orchestration
- `services/search/spatial.py` — intent parser, synonym table, corridor math, city-aware geocoding, `POST /search/spatial`
- `services/search/geocode.py` — async geocode helper with position-biased caching
- `frontend/app.js` — main frontend (~3200 lines), spatial search, hybrid toggle, public lands, GPS, STT
- `frontend/kmz-import.js` — KMZ/KML import pipeline (style resolution, icon loading, chunked processing)
- `frontend/navigation.js` — turn-by-turn engine (~790 lines)
- `frontend/nav-ui.js` — navigation UI bridge (~860 lines)
- `frontend/stt.js` — voice search module
- `scripts/build_public_lands.py` — PAD-US + AIANNH → public lands vector tiles (runs on HOST, needs Tippecanoe)
- `scripts/acquire_imagery.py` — imagery download (3 modes: direct/tnmaccess/m2m)
- `scripts/acquire_naip.py` — USDA NAIP aerial imagery pipeline
- `scripts/acquire_sentinel.py` — Sentinel-2 satellite imagery pipeline
- `scripts/build_poi_index.py` — GNIS POI indexer
- `scripts/build_osm_pois.py` — OSM amenity + public land extractor
- `scripts/download_elevation.py` — elevation tile download
- `docs/pitfalls/implementation-pitfalls.md` — 13 pitfalls (includes #11: MapLibre dragRotate)

### Tests
~200 tests across project:
- `services/stt/tests/` (30) — backend interface, CPU backend, endpoints, NPU, integration
- `services/gps/tests/` (4) — GPS /status endpoint (3D fix, 2D fix, no fix, no gpsd)
- `services/search/tests/` (33) — admin status, pipeline M2M, zoom validation, OSM POI pipeline
- `tests/test_intent_parser.py` (27) — intent detection, category extraction, fallback chain
- `tests/test_corridor.py` (19) — haversine, Douglas-Peucker, segment distance, corridor filter
- `tests/test_osm_poi_indexer.py` (33) — OSM extraction, operator normalization, dedup, brand fallback
- `tests/test_osm_poi_search.py` (15) — FTS5 queries, three-way dedup, graceful degradation
- `tests/test_spatial_osm.py` (21) — BLM/USFS/NPS synonyms, osm_operator, direct SQL queries
- `tests/test_spatial_endpoint.py` (7) — POST /search/spatial validation and response shape
- `tests/test_mbtiles_metadata.py` (6) — UNIQUE constraint, minzoom/maxzoom/bounds
- `tests/test_pipeline_orchestrator.py` (3) — command building for imagery vs elevation
- `tests/test_elevation_state.py` (3) — state file merge pattern
- `tests/test_m2m_api.py` (18) — login, scene search, download URLs, cancellation, progress, product selection
- `tests/test_m2m_progress.py` (5) — M2M phase-aware progress reporting

Run all: `python3 -m pytest tests/ services/stt/tests/ services/gps/tests/ -v`
Run search tests: `cd services/search && python -m pytest tests/ -v`

### Design & plan documents (2026-04-09 session)
- `docs/superpowers/specs/2026-04-09-public-lands-layer-design.md` — Public lands overlay spec (executed, adversarial+CSO reviewed)
- `docs/plans/2026-04-09-public-lands-layer-plan.md` — Public lands implementation plan (executed)
- `docs/superpowers/specs/2026-04-09-hybrid-imagery-roads-design.md` — Hybrid imagery+roads spec (executed, adversarial reviewed)
- `docs/plans/2026-04-09-hybrid-imagery-roads-plan.md` — Hybrid mode implementation plan (executed)
- `docs/superpowers/specs/2026-04-08-kmz-import-overhaul-design.md` — KMZ import overhaul spec (executed by parallel agent)
- `docs/superpowers/specs/2026-04-08-frontend-ux-fixes-design.md` — 7 UX fixes spec (executed by parallel agent)
- `docs/plans/2026-04-08-frontend-overhaul-plan.md` — Frontend overhaul plan (executed by parallel agent)
- `docs/pitfalls/testing-pitfalls.md` — 8 common testing mistakes
- `docs/pitfalls/implementation-pitfalls.md` — 13 common implementation mistakes (includes #11: MapLibre dragRotate)

### Bug hunt and review reports
- 30+ reports in `dev/bug-hunts/` — KMZ security, public lands security, STT, pipeline, GPS, corridor, TLS
- `dev/bug-hunts/2026-04-08-kmz-security-review.md` — CSO review: DOMPurify mandate, URL validation
- `dev/bug-hunts/2026-04-09-public-lands-security-review.md` — CSO review: shell injection via layer name (mitigate with shell=False)

## What to work on next

### High priority
- **Regenerate vector basemap** — `southwest5.mbtiles` needs rebuilding with Planetiler using a custom profile that lowers minzoom for minor/service/track roads. BLM/Forest Service roads (e.g., road to White Pocket, AZ) are invisible in hybrid mode until z14-15 because Planetiler drops them at lower zoom. Need: install JRE, download Planetiler JAR, create custom profile, rebuild from `western-us.osm.pbf`. See TODOS.md for full details.
- **Firefox WebGL performance** — hybrid + terrain + public lands is hitchy in Firefox but smooth in Chromium. This is a browser-specific WebGL limitation. Investigate MapLibre rendering optimizations or document Chromium recommendation.

### Medium priority
- **NGINX selective compression** — PBF tiles uncompressed over mesh due to sub_filter blanket
- **Setup CLI tool** — single `geographica-setup` command
- **GPS track recording** — record and export as GPX/KML
- **Public lands build on Pi 5 8GB** — current pipeline needs 6-9GB RAM. See TODOS.md.

### Blocked
- **Whisper NPU backend** — blocked on `hailo-10-all` reaching 5.3.0 for Pi 5

## Key architectural details

These are non-obvious implementation details a new agent must understand (accumulated across sessions):

1. **admin_status() is fully async.** All blocking calls (Docker API, openssl subprocess, SQLite, disk) run via `asyncio.to_thread()` through a single `asyncio.gather()` call alongside the async STT/GPS HTTP calls. Don't add synchronous calls directly — wrap them.

2. **Pipeline container detection uses wildcard.** `_is_pipeline_container_running()` matches `geographica-pipeline*` (not exact name) to detect both admin-panel-started containers (`geographica-pipeline`) and CLI-started ones (`geographica-pipeline-run-*`).

3. **Service list is whitelist-filtered.** `KNOWN_SERVICES` frozenset in search/main.py. Pipeline containers are excluded from `/admin/status` services list. Only the 7 core services appear.

4. **M2M pipeline writes phase-aware progress.** `acquire_imagery.py` `update_progress()` has 7 optional kwargs for M2M phases. `m2m_download_batched()` has an `on_batch_complete` callback. The state file gains `phase`, `scenes_total`, `geotiffs_downloaded/total/bytes`, `current_batch/total_batches`.

5. **GPS /status endpoint omits coordinates.** Security invariant: lat/lon/alt/speed/heading NEVER appear in admin panel responses. The `/status` endpoint returns only `{status, fix, accuracy_m}`.

6. **Frontend config panel has no build step.** Single HTML file (`frontend/config/index.html`, ~1150 lines) with inline CSS and JS. MapLibre loaded from `/vendor/`. All API calls go through `cfgFetch()` which adds `X-Geographica` header.

7. **Worktree branches must be gitignored.** `.claude/worktrees/` is in `.gitignore`. If you use subagent worktrees, verify `git status` doesn't show worktree entries before committing. See `feedback_worktree_gitignore.md` in memory.

8. **Two M2M staging directories exist.** `/data/m2m_staging/` (new, admin-panel-started) and `/data/m2m_maricopa_staging/` (old, CLI-started, 144 GeoTIFFs). The old one can be deleted after the new download completes.

9. **Hybrid imagery mode uses map.setStyle().** Toggling imagery ON swaps to `STYLES.hybrid`, OFF restores `previousStyle`. The persistent `map.on('style.load')` handler replays all overlays AND removes mouseRotate/mousePitch handlers (Pitfall #11).

10. **MapLibre dragRotate: disable() is INSUFFICIENT in v5.21.** Must surgically delete `mouseRotate` and `mousePitch` from `map._handlers._handlersById` and filter from `_handlers` array. This is done in BOTH `initFreeLookCamera()` and the `style.load` handler. `NavigationControl` must use `showCompass: false`. See Pitfall #11 for the full story — 7 failed approaches documented.

10. **Public lands uses 3 fill layers.** `public-lands-fill` (non-tribal, solid), `public-lands-fill-tribal` (striped pattern via fill-pattern), `public-lands-outline` (boundaries). All toggle together. In hybrid mode, z-order anchor finds the first `transportation` source-layer in the hybrid style to insert public lands below roads.

11. **Public lands pipeline runs on HOST, not Docker.** `scripts/build_public_lands.py` requires Tippecanoe (built from source on ARM64) and ogr2ogr (GDAL). It downloads PAD-US (~1.5GB, requires browser CAPTCHA) and Census AIANNH (~9MB, direct download). Stop Docker services for full Western US build (~6-9GB RAM needed).

12. **Imagery source in hybrid style needs tileSize: 256.** The imagery MBTiles contains 256px tiles but MapLibre defaults to 512 for raster sources. Without explicit `tileSize: 256`, imagery renders one zoom level too low (blurry).

13. **NAIP/Sentinel toggles hidden in hybrid mode.** The `#imagery-toggles` container is set to `display: none` when hybrid is active to prevent double-imagery stacking.

## Known issues to be aware of
- TileServer config uses `/srv/data/` paths for imagery/elevation (writable mount for WAL)
- sub_filter in NGINX MUST use `$scheme://$http_host` — relative URLs break MapLibre
- Config panel is localhost-only (127.0.0.1:8097) — access via SSH tunnel or Pi's local browser
- `depends_on: condition: service_healthy` on search blocks startup if Nominatim hasn't passed healthcheck — use `docker start geographica-search` to force start
- Nominatim free-text search for commercial POIs is sparse in rural areas — OSM POI extraction (once deployed) fills this gap
- `app.js` is ~2800 lines — approaching the threshold where extraction to separate modules should be considered
- STT service needs internet during Docker build to download the ~140MB Whisper model
- Total Docker memory allocation is ~15GB on 16GB hardware — tight but functional
- **Docker cgroup memory limits NOT enforced** on default Pi OS. Add `cgroup_enable=memory cgroup_memory=1` to `/boot/firmware/cmdline.txt` and reboot. Until then, ALL Docker `memory:` limits are silently ignored.
- **HTTP/2 enabled on HTTPS** (`listen 443 ssl http2` in `nginx/tls-include.conf`). Without this, browser queues search requests behind tile fetches (6-connection HTTP/1.1 limit).
- **M2M pipeline processes batches of 50 GeoTIFFs** with pipelined download+conversion. Batch N+1 downloads while batch N converts. Raw GeoTIFFs deleted after each batch conversion. Staging needs ~15-30 GB temporary.
- **Geocode timeout is 5 seconds** (was 1s, caused city-aware search to fail for all cities). Set in `services/search/geocode.py:69`.
- **Sentinel-2 pipeline exists but is untested.** Only M2M and direct tile scraper are confirmed working imagery acquisition modes.
- **NGINX bind mount footgun:** `nginx/nginx.conf` is file-mounted into the frontend container. Git operations (commit, checkout, rebase) create a new file inode — Docker tracks the old inode, so the container silently serves stale config. Always run `docker compose up -d --force-recreate frontend` after editing NGINX config files.
- **Vector basemap missing minor roads at low zoom.** BLM/Forest Service roads don't appear in `southwest5.mbtiles` until z14-15 because Planetiler drops them. Needs regeneration with custom profile. See TODOS.md.
- **Firefox WebGL performance.** Hybrid + terrain + public lands is hitchy in Firefox, smooth in Chromium. Browser-specific limitation.
- **Public lands build OOMs on Pi 5 8GB.** Needs 6-9GB RAM. Works on 16GB with services stopped.

## Cameron's preferences (from memory)
- Prioritizes correctness and completeness over speed
- Asks "what would 10/10 look like" before accepting shortcuts
- Values regulatory compliance details (Part 97, TLS cipher suites)
- Data must stay outside the git repo at /srv/geographica/data/
- Git push via VS Code UI only (terminal push fails)
- No unnecessary migration of existing deployments — they're reference only
- Prefers robust adversarial review (multiple rounds, cross-model) before implementing major features
- Prefers full brainstorm → adversarial review → implementation plan → TDD execution workflow
- M2M credentials must NEVER be written to any file — env vars only
- Doesn't want extended-width UI elements that stretch across full desktop viewport — keep 600px max-width centered
