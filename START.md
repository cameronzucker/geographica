# Geographica — Session Start Prompt

Read this file to understand the current state of the project before beginning work.

## Project overview

Geographica is an offline-first GIS platform for AREDN amateur radio mesh networks, running on a Raspberry Pi 5 (16GB RAM, 896GB SATA SSD, GPS hat, Hailo 10H NPU). It combines aspects of Google Earth and Google Maps while being entirely self-hostable and offline-capable after initial data download.

**Owner:** Cameron Zucker (cameronzucker@gmail.com)
**Repo:** /home/administrator/Code/geographica (branch: dev)
**Design doc:** ~/.gstack/projects/geographica/administrator-dev-design-20260407-021424.md

## Critical context — read before making any changes

1. **Read MEMORY.md** at `~/.claude/projects/-home-administrator-Code-geographica/memory/MEMORY.md` — it indexes all session handoffs, user preferences, and project decisions. Read the handoff at `handoff_20260408d.md` for the most recent session context.

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
- **STT** (:8098) — **NEW, needs `docker compose build stt` to deploy** — Whisper base.en CPU backend, push-to-hold mic button
- **NGINX/Frontend** (:8093 HTTP, :443 HTTPS) — main app + config panel on localhost:8097

### New features (implemented 2026-04-08, not yet deployed)
- **Voice search (STT)** — push-to-hold mic button, AudioWorklet capture, Whisper base.en INT8 transcription → spatial search pipeline. Deploy: `docker compose build stt && docker compose up -d`
- **OSM POI search** — commercial amenities + public land boundaries extracted from OSM PBF. Deploy: `python3 scripts/build_osm_pois.py --pbf /srv/geographica/data/valhalla/western-us.osm.pbf --output /srv/geographica/data/poi.sqlite --bbox "-124.8,31.3,-102.0,49.0" && docker compose restart search`
- **NPU investigation complete** — Whisper-Base.hef (5.3.0) loads metadata on 5.1.1 but fails `configure()` with HAILO_NOT_IMPLEMENTED. Ship CPU, revisit at 5.3.0. See `dev/npu-investigation-results.md`.

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
- `docker-compose.yml` — 8 services (7 + pipeline with profiles), includes new STT service
- `docker-compose.hailo.yml` — override for Hailo NPU device passthrough
- `nginx/nginx.conf` — main app + config panel server blocks, sub_filter for TileJSON, /stt/ proxy
- `services/search/main.py` — Nominatim/POI/OSM POI query, admin API, pipeline orchestration
- `services/search/spatial.py` — intent parser, synonym table (28 entries incl BLM/USFS/NPS), corridor math, `POST /search/spatial`
- `services/stt/main.py` — STT service: `POST /transcribe`, `GET /health`, WAV validation
- `services/stt/backends/cpu.py` — faster-whisper base.en INT8, hallucination filtering
- `services/stt/backends/npu.py` — HailoRT skeleton (ready for 5.3.0 firmware)
- `services/gps/main.py` — GPS WebSocket with accuracy, 50ms poll sleep
- `frontend/app.js` — main frontend (~2800 lines), spatial search, numbered pins, GPS, STT integration
- `frontend/stt.js` — voice search module (mic button, AudioWorklet, WAV encoding)
- `frontend/stt-worklet.js` — AudioWorklet processor (sample accumulation)
- `frontend/navigation.js` — turn-by-turn engine (~790 lines)
- `frontend/nav-ui.js` — navigation UI bridge (~860 lines)
- `frontend/config/index.html` — standalone config panel
- `scripts/acquire_imagery.py` — imagery download (3 modes: direct/tnmaccess/m2m)
- `scripts/build_poi_index.py` — GNIS POI indexer
- `scripts/build_osm_pois.py` — **NEW** — OSM amenity + public land extractor
- `scripts/download_elevation.py` — elevation tile download
- `scripts/provision_tailscale_tls.sh` — Tailscale cert provisioning

### Tests
164 tests across project:
- `services/stt/tests/` (30) — backend interface, CPU backend, endpoints, NPU, integration
- `tests/test_intent_parser.py` (27) — intent detection, category extraction, fallback chain
- `tests/test_corridor.py` (19) — haversine, Douglas-Peucker, segment distance, corridor filter
- `tests/test_osm_poi_indexer.py` (33) — OSM extraction, operator normalization, dedup, brand fallback
- `tests/test_osm_poi_search.py` (15) — FTS5 queries, three-way dedup, graceful degradation
- `tests/test_spatial_osm.py` (21) — BLM/USFS/NPS synonyms, osm_operator, direct SQL queries
- `tests/test_spatial_endpoint.py` (7) — POST /search/spatial validation and response shape
- `tests/test_mbtiles_metadata.py` (6) — UNIQUE constraint, minzoom/maxzoom/bounds
- `tests/test_pipeline_orchestrator.py` (3) — command building for imagery vs elevation
- `tests/test_elevation_state.py` (3) — state file merge pattern

Run all: `python3 -m pytest tests/ services/stt/tests/ -v`

### Design & plan documents
- `docs/superpowers/specs/2026-04-08-whisper-stt-design.md` — STT design (adversarial reviewed)
- `docs/superpowers/specs/2026-04-08-expanded-poi-sources-design.md` — POI design (adversarial reviewed)
- `docs/superpowers/specs/2026-04-08-m2m-api-test-plan.md` — M2M test plan (adversarial reviewed)
- `docs/plans/2026-04-08-whisper-stt-plan.md` — STT implementation plan (12 tasks, executed)
- `docs/plans/2026-04-08-expanded-poi-sources-plan.md` — POI implementation plan (8 tasks, executed)
- `docs/plans/2026-04-08-m2m-api-test-plan.md` — M2M implementation plan (7 tasks, ready to execute)
- `docs/pitfalls/testing-pitfalls.md` — 8 common testing mistakes
- `docs/pitfalls/implementation-pitfalls.md` — 10 common implementation mistakes

### Bug hunt reports
15 reports in `dev/bug-hunts/` + NPU investigation at `dev/npu-investigation-results.md`

## What to work on next

See `TODOS.md` for the full backlog with context. Summary:

### High priority
1. **M2M API end-to-end test** — ERS approval received, plan ready at `docs/plans/2026-04-08-m2m-api-test-plan.md`. Requires live credentials via env vars (NEVER write to file). Fixes code gaps (SIGTERM, progress reporting) then runs phased live API testing.
2. **Deploy STT + POI** — `docker compose build stt && docker compose up -d` for STT; run `build_osm_pois.py` for POI extraction; restart search service.
3. **Whisper NPU backend** — blocked on `hailo-10-all` reaching 5.3.0 for Pi 5. HEF loads metadata on 5.1.1 but fails configure. See `dev/npu-investigation-results.md`.

### Medium priority
4. **Public land use map layer** — add BLM/USFS/NPS boundaries as toggleable overlay
5. **NGINX selective compression** — PBF tiles uncompressed over mesh due to sub_filter blanket
6. **Setup CLI tool** — single `geographica-setup` command
7. **GPS track recording** — record and export as GPX/KML
8. **Valhalla costing toggles** — verify UI checkboxes are wired up
9. **Light/dark mode toggle** — runtime basemap style switching

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
