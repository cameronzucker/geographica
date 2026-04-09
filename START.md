# Geographica — Session Start Prompt

Read this file to understand the current state of the project before beginning work.

## Project overview

Geographica is an offline-first GIS platform for AREDN amateur radio mesh networks, running on a Raspberry Pi 5 (16GB RAM, 896GB SATA SSD, GPS hat, Hailo 10H NPU). It combines aspects of Google Earth and Google Maps while being entirely self-hostable and offline-capable after initial data download.

**Owner:** Cameron Zucker (cameronzucker@gmail.com)
**Repo:** /home/administrator/Code/geographica (branch: dev)
**Design doc:** ~/.gstack/projects/geographica/administrator-dev-design-20260407-021424.md

## Critical context — read before making any changes

1. **Read MEMORY.md** at `~/.claude/projects/-home-administrator-Code-geographica/memory/MEMORY.md` — it indexes all session handoffs, user preferences, and project decisions. Read the handoff at `handoff_20260408e.md` for the most recent session context.

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

### Recently deployed (2026-04-08/09)
- **Voice search (STT)** — deployed and working on HTTP + HTTPS. 405 bug fixed (stale NGINX bind mount).
- **M2M imagery pipeline** — validated against live USGS API. Batched download system (50 scenes/batch) scales to state/regional areas. Maricopa County download currently running in background (~1022 GeoTIFFs).
- **OSM POI search** — code complete, not yet deployed to production. Run: `python3 scripts/build_osm_pois.py --pbf /srv/geographica/data/valhalla/western-us.osm.pbf --output /srv/geographica/data/poi.sqlite --bbox "-124.8,31.3,-102.0,49.0" && docker compose restart search`

### Background process
- **Maricopa County M2M download** is running in a pipeline container. Monitor: `docker logs -f $(docker ps -q --filter "name=pipeline")`. Output: `/data/maricopa_m2m.mbtiles`. Staging: `/data/m2m_maricopa_staging/`. This will take many hours — do not interrupt.

### Data downloads — all complete
- **Elevation z0-14**: 1,474,959 tiles — complete
- **Imagery z0-16**: 2,588,818 tiles — complete
- **POI index**: 304,094 GNIS features — complete
- **OSM POIs**: Not yet extracted (run `build_osm_pois.py` to populate)

### TLS
- **Tailscale HTTPS active**: `https://pandora.twin-bramble.ts.net` (Let's Encrypt, valid until 2026-07-07)
- Systemd timer for daily cert renewal: `systemctl status geographica-tls-renew.timer`
- Dual-mode: HTTP on :8093 (LAN/AREDN) + HTTPS on :443 (Tailscale)

### Key files
- `docker-compose.yml` — 8 services (7 + pipeline with profiles), includes STT service
- `docker-compose.hailo.yml` — override for Hailo NPU device passthrough
- `nginx/nginx.conf` — main app + config panel server blocks, sub_filter for TileJSON, /stt/ resilient proxy
- `services/search/main.py` — Nominatim/POI/OSM POI query, admin API, pipeline orchestration
- `services/search/spatial.py` — intent parser, synonym table (28 entries incl BLM/USFS/NPS), corridor math, `POST /search/spatial`
- `services/stt/main.py` — STT service: `POST /transcribe`, `GET /health`, WAV validation
- `services/stt/backends/cpu.py` — faster-whisper base.en INT8, hallucination filtering
- `services/stt/backends/npu.py` — HailoRT skeleton (ready for 5.3.0 firmware)
- `services/gps/main.py` — GPS WebSocket with accuracy, 50ms poll sleep, `GET /health`, `GET /position`
- `frontend/app.js` — main frontend (~2800 lines), spatial search, numbered pins, GPS, STT integration
- `frontend/stt.js` — voice search module (mic button, AudioWorklet, WAV encoding)
- `frontend/stt-worklet.js` — AudioWorklet processor (sample accumulation)
- `frontend/config/index.html` — standalone config panel (to be redesigned — see "What to work on next")
- `frontend/navigation.js` — turn-by-turn engine (~790 lines)
- `frontend/nav-ui.js` — navigation UI bridge (~860 lines)
- `scripts/acquire_imagery.py` — imagery download (3 modes: direct/tnmaccess/m2m, batched M2M)
- `scripts/build_poi_index.py` — GNIS POI indexer
- `scripts/build_osm_pois.py` — OSM amenity + public land extractor
- `scripts/download_elevation.py` — elevation tile download
- `scripts/provision_tailscale_tls.sh` — Tailscale cert provisioning

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

### Design & plan documents
- `docs/superpowers/specs/2026-04-09-admin-panel-redesign-design.md` — Admin panel redesign spec (executed)
- `docs/superpowers/specs/2026-04-09-pipeline-status-ux-design.md` — Pipeline status UX spec (executed)
- `docs/plans/2026-04-09-admin-panel-redesign-plan.md` — Admin panel redesign plan (executed)
- `docs/plans/2026-04-09-pipeline-status-ux-plan.md` — Pipeline status UX plan (executed)
- `docs/superpowers/specs/2026-04-08-whisper-stt-design.md` — STT design (executed)
- `docs/superpowers/specs/2026-04-08-expanded-poi-sources-design.md` — POI design (executed)
- `docs/superpowers/specs/2026-04-08-m2m-api-test-plan.md` — M2M test plan (executed)
- `docs/pitfalls/testing-pitfalls.md` — 8 common testing mistakes
- `docs/pitfalls/implementation-pitfalls.md` — 10 common implementation mistakes

### Bug hunt and review reports
- 20+ reports in `dev/bug-hunts/` — STT 405, pipeline, GPS, corridor, TLS, admin panel redesign
- `dev/bug-hunts/2026-04-09-admin-panel-consolidated.md` — 3 confirmed bugs, 2 design decisions (all fixed)
- `dev/reviews/2026-04-08-readme-adversarial-review.md` — 36 README issues (5 critical)
- `dev/reviews/2026-04-09-admin-panel-spec-adversarial-review.md` — 29 spec issues (4 critical, all addressed)
- `dev/m2m-test-results.md` — M2M API validation results

## What to work on next

### Recently completed (2026-04-09)
- **Admin panel redesign** — 3-tab layout (Dashboard/Pipelines/Settings), service health dots, MapLibre minimap bbox selection, enriched /admin/status (STT, GPS, TLS, search stats, disk), OSM POI pipeline type, frontend healthcheck
- **Pipeline status UX** — Phase-aware M2M progress (login→searching→downloading→converting→complete), service list filtering (7 known services only), stale state time-ago badges, M2M command construction, zoom disable for M2M
- **Bug hunt fixes** — osm_poi 500 crash, Docker client use-after-close, pipeline banner elevation/OSM progress, admin_status event loop blocking (asyncio.to_thread), pipeline_cancel path consistency

### Medium priority
- **Fix README issues** — 36 findings from adversarial review at `dev/reviews/2026-04-08-readme-adversarial-review.md`
- **OSM POI extraction** — deploy to production (code complete, just needs to run)
- **Public land use map layer** — add BLM/USFS/NPS boundaries as toggleable overlay
- **NGINX selective compression** — PBF tiles uncompressed over mesh due to sub_filter blanket
- **Setup CLI tool** — single `geographica-setup` command
- **GPS track recording** — record and export as GPX/KML
- **Valhalla costing toggles** — verify UI checkboxes are wired up
- **Light/dark mode toggle** — runtime basemap style switching

### Blocked
- **Whisper NPU backend** — blocked on `hailo-10-all` reaching 5.3.0 for Pi 5

## Known issues to be aware of
- TileServer config uses `/srv/data/` paths for imagery/elevation (writable mount for WAL)
- sub_filter in NGINX MUST use `$scheme://$http_host` — relative URLs break MapLibre
- Config panel is localhost-only (127.0.0.1:8097) — access via SSH tunnel or Pi's local browser
- `depends_on: condition: service_healthy` on search blocks startup if Nominatim hasn't passed healthcheck — use `docker start geographica-search` to force start
- Nominatim free-text search for commercial POIs is sparse in rural areas — OSM POI extraction (once deployed) fills this gap
- `app.js` is ~2800 lines — approaching the threshold where extraction to separate modules should be considered
- STT service needs internet during Docker build to download the ~140MB Whisper model
- Total Docker memory allocation is ~15GB on 16GB hardware — tight but functional
- **NGINX bind mount footgun:** `nginx/nginx.conf` is file-mounted into the frontend container. Git operations (commit, checkout, rebase) create a new file inode — Docker tracks the old inode, so the container silently serves stale config. Always run `docker compose up -d --force-recreate frontend` after editing NGINX config files.
- **Maricopa M2M download running** — do not stop the pipeline container. Monitor with `docker logs`.

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
