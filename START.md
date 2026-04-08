# Geographica — Session Start Prompt

Read this file to understand the current state of the project before beginning work.

## Project overview

Geographica is an offline-first GIS platform for AREDN amateur radio mesh networks, running on a Raspberry Pi 5 (16GB RAM, 896GB SATA SSD, GPS hat, Hailo 10H NPU). It combines aspects of Google Earth and Google Maps while being entirely self-hostable and offline-capable after initial data download.

**Owner:** Cameron Zucker (cameronzucker@gmail.com)
**Repo:** /home/administrator/Code/geographica (branch: dev)
**Design doc:** ~/.gstack/projects/geographica/administrator-dev-design-20260407-021424.md

## Critical context — read before making any changes

1. **Read MEMORY.md** at `~/.claude/projects/-home-administrator-Code-geographica/memory/MEMORY.md` — it indexes all session handoffs, user preferences, and project decisions. Read the handoff at `handoff_20260408c.md` for the most recent session context.

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
- **NGINX/Frontend** (:8093 HTTP, :443 HTTPS) — main app + config panel on localhost:8097

### Data downloads — all complete
- **Elevation z0-14**: 1,474,959 tiles — complete
- **Imagery z0-16**: 2,588,818 tiles — complete
- **POI index**: 304,094 GNIS features — complete

### TLS
- **Tailscale HTTPS active**: `https://pandora.twin-bramble.ts.net` (Let's Encrypt, valid until 2026-07-07)
- Systemd timer for daily cert renewal: `systemctl status geographica-tls-renew.timer`
- Dual-mode: HTTP on :8093 (LAN/AREDN) + HTTPS on :443 (Tailscale)
- Three TLS modes in `entrypoint.sh`: `http` (default), `https` (self-signed), `tailscale` (Let's Encrypt)

### Key files
- `docker-compose.yml` — 7 services (6 + pipeline with profiles)
- `nginx/nginx.conf` — main app + config panel server blocks, sub_filter for TileJSON
- `nginx/entrypoint.sh` — TLS mode selection (http/https/tailscale)
- `services/search/main.py` — Nominatim/POI query, admin API, pipeline orchestration
- `services/search/spatial.py` — intent parser, synonym table (25 entries), corridor math, `POST /search/spatial`
- `services/gps/main.py` — GPS WebSocket with accuracy, 50ms poll sleep
- `frontend/app.js` — main frontend (~2800 lines), spatial search, numbered pins, GPS source switching
- `frontend/navigation.js` — turn-by-turn engine (~790 lines)
- `frontend/nav-ui.js` — navigation UI bridge (~860 lines)
- `frontend/config/index.html` — standalone config panel
- `scripts/acquire_imagery.py` — imagery download (3 modes: direct/tnmaccess/m2m)
- `scripts/download_elevation.py` — elevation tile download
- `scripts/build_poi_index.py` — GNIS POI indexer
- `scripts/provision_tailscale_tls.sh` — Tailscale cert provisioning

### Tests
65 tests across 6 files in `tests/`:
- `test_intent_parser.py` (27) — intent detection, category extraction, fallback chain
- `test_corridor.py` (19) — haversine, Douglas-Peucker, segment distance, corridor filter
- `test_spatial_endpoint.py` (7) — POST /search/spatial validation and response shape
- `test_mbtiles_metadata.py` (6) — UNIQUE constraint, minzoom/maxzoom/bounds
- `test_pipeline_orchestrator.py` (3) — command building for imagery vs elevation
- `test_elevation_state.py` (3) — state file merge pattern

Run all: `python3 -m pytest tests/ -v`

### Design & plan documents
- `docs/superpowers/specs/2026-04-08-tailscale-tls-design.md`
- `docs/superpowers/specs/2026-04-08-natural-language-spatial-search-design.md`
- `docs/superpowers/plans/2026-04-08-natural-language-spatial-search.md`

### Bug hunt reports
15 reports in `dev/bug-hunts/` covering: imagery pipeline, Tailscale TLS, GPS source switching (v1 + v2), corridor query quality.

## What to work on next

See `TODOS.md` for the full backlog with context. Summary:

### High priority
1. **Phase 2b: Whisper STT on Hailo 10H NPU** — audio→text feeds into `POST /search/spatial`. The text parser (Phase 2a) is complete and tested. Hailo 10H is installed but not yet used.
2. **Expanded POI sources** — most impactful improvement for spatial search quality. Rural I-10 between Buckeye and Blythe has a 240-mile gap with no results. Candidates: OSM amenity extraction from existing PBF, Overture Maps.
3. **M2M API download access** — ERS approval submitted, pending. Test `--mode m2m` once approved.

### Medium priority
4. **NGINX selective compression** — PBF tiles uncompressed over mesh due to sub_filter blanket
5. **Setup CLI tool** — single `geographica-setup` command
6. **GPS track recording** — record and export as GPX/KML
7. **Valhalla costing toggles** — verify UI checkboxes are wired up
8. **Light/dark mode toggle** — runtime basemap style switching

## Known issues to be aware of
- TileServer config uses `/srv/data/` paths for imagery/elevation (writable mount for WAL)
- sub_filter in NGINX MUST use `$scheme://$http_host` — relative URLs break MapLibre
- Config panel is localhost-only (127.0.0.1:8097) — access via SSH tunnel or Pi's local browser
- `depends_on: condition: service_healthy` on search blocks startup if Nominatim hasn't passed healthcheck — use `docker start geographica-search` to force start
- Nominatim free-text search for commercial POIs is sparse in rural areas — the spatial search uses brand-name queries and OSM type filtering as mitigations, but expanded POI sources is the real fix
- `app.js` is ~2800 lines — approaching the threshold where extraction to separate modules should be considered for the next major frontend feature

## Cameron's preferences (from memory)
- Prioritizes correctness and completeness over speed
- Asks "what would 10/10 look like" before accepting shortcuts
- Values regulatory compliance details (Part 97, TLS cipher suites)
- Data must stay outside the git repo at /srv/geographica/data/
- Git push via VS Code UI only (terminal push fails)
- No unnecessary migration of existing deployments — they're reference only
- Prefers robust adversarial review (multiple rounds, cross-model) before implementing major features
- Prefers full brainstorm → adversarial review → implementation plan → TDD execution workflow
