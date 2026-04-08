# Geographica — Session Start Prompt

Read this file to understand the current state of the project before beginning work.

## Project overview

Geographica is an offline-first GIS platform for AREDN amateur radio mesh networks, running on a Raspberry Pi 5 (16GB RAM, 896GB SATA SSD, GPS hat, Hailo 10H NPU). It combines aspects of Google Earth and Google Maps while being entirely self-hostable and offline-capable after initial data download.

**Owner:** Cameron Zucker (cameronzucker@gmail.com)
**Repo:** /home/administrator/Code/geographica (branch: dev)
**Design doc:** ~/.gstack/projects/geographica/administrator-dev-design-20260407-021424.md

## Critical context — read before making any changes

1. **Read MEMORY.md** at `~/.claude/projects/-home-administrator-Code-geographica/memory/MEMORY.md` — it indexes all session handoffs, user preferences, and project decisions. Read the handoff at `handoff_20260408.md` for the most recent session context.

2. **Read CLAUDE.md** in the repo root — it has the project structure, commands, hardware specs, and skill routing rules.

3. **Read TODOS.md** in the repo root — it has the deferred feature backlog with full context on each item.

4. **Data lives OUTSIDE the repo** at `/srv/geographica/data/` (symlinked from `data/`). Never create large files inside the git repo tree. See `feedback_data_outside_repo.md` in memory.

5. **Git push doesn't work from terminal** — user syncs via VS Code UI. See `feedback_git_push.md` in memory. Git config: name "Cameron Zucker", email cameronzucker@gmail.com.

## Current system state

### Running services (Docker Compose on port 8093)
- **TileServer GL** (:8090) — vector basemap + elevation + aerial imagery tiles
- **Valhalla** (:8094) — routing engine, 11 Western US states
- **Nominatim** (:8092) — geocoding, 11 Western US states imported
- **GPS** (:8095) — FastAPI WebSocket, reads Pi's GPS hat via gpsd
- **Search** (:8096) — unified search (Nominatim + 304K GNIS POI features)
- **NGINX/Frontend** (:8093) — main app + config panel on localhost:8097

### Background downloads (may still be running or completed)
- **Elevation z13-14**: was at 880K/1.47M tiles, restarted at session end
- **Imagery z0-15**: was at ~1.5M/5.9M tiles in pipeline container

Check status: `curl -s http://localhost:8096/admin/status | python3 -m json.tool`

### Key files
- `docker-compose.yml` — 7 services (6 + pipeline with profiles)
- `nginx/nginx.conf` — main app + config panel server blocks
- `nginx/entrypoint.sh` — TLS mode selection (HTTP or HTTPS)
- `services/search/main.py` — unified search + admin API + pipeline orchestration
- `services/gps/main.py` — GPS WebSocket with accuracy
- `frontend/app.js` — main frontend (~2600 lines)
- `frontend/navigation.js` — turn-by-turn engine (~790 lines)
- `frontend/nav-ui.js` — navigation UI bridge (~860 lines)
- `frontend/config/index.html` — standalone config panel
- `scripts/acquire_imagery.py` — imagery download (3 modes: direct/tnmaccess/m2m)
- `scripts/download_elevation.py` — elevation tile download
- `scripts/build_poi_index.py` — GNIS POI indexer
- `scripts/generate_tls.sh` — TLS cert generation

## What to work on next

### High priority
1. **Cloudflare Tunnel setup** — register geographica.mohaverad.io, configure cloudflared, test HTTPS end-to-end. The TLS infrastructure is built but untested with real deployment.
2. **M2M API download access** — ERS approval was submitted. Once approved, test the `--mode m2m` pipeline end-to-end. Credentials are stored at `/srv/geographica/data/.credentials.json`.
3. **Verify downloads completed** — check if elevation z13-14 and imagery z0-15 finished. If so, restart TileServer to pick up new tiles.

### Medium priority
4. **Phase 2: Voice AI** — Whisper on Hailo 10H NPU for spatial queries. Design doc has the full spec. The turn-by-turn navigation engine already supports voice via Web Speech API; Phase 2 adds Hailo-based offline STT.
5. **TODOS backlog** — see TODOS.md for deferred items with full context.

### Known issues to be aware of
- TileServer config uses `/srv/data/` paths for imagery/elevation (writable mount for WAL compatibility)
- sub_filter in NGINX MUST use `$scheme://$http_host` — relative URLs break MapLibre
- Config panel is localhost-only (127.0.0.1:8097) — access via SSH tunnel or Pi's local browser
- The `depends_on: condition: service_healthy` on the search service blocks startup if Nominatim healthcheck hasn't passed — use `docker start geographica-search` to force start

## Cameron's preferences (from memory)
- Prioritizes correctness and completeness over speed
- Asks "what would 10/10 look like" before accepting shortcuts
- Values regulatory compliance details (Part 97, TLS cipher suites)
- Data must stay outside the git repo at /srv/geographica/data/
- Git push via VS Code UI only (terminal push fails)
- No unnecessary migration of existing deployments — they're reference only
- Prefers robust adversarial review (multiple rounds, cross-model) before implementing major features
