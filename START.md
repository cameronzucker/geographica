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

## What to work on next — PRIORITY TASK LIST

Use the `build-robust-features` skill (at `.claude/skills/build-robust-features/`) for each subsystem below. Each is an independent feature that gets its own brainstorm → adversarial → plan → execution cycle.

### 1. Unified Imagery Layer + z15-z17 Gap Fix (HIGH PRIORITY)

**Problem:** Users see a jarring gap between z14 (USGS basemap tiles) and z18 (NOAA NAIP aerial). Zooming from z14 drops to positron vector basemap at z15-z17, then jumps to aerial at z18.

**Proven solution:** Add `gdaladdo -r average <temp.mbtiles> 2 4 8` to the per-tile conversion step in the NOAA pipeline. This generates z15-z17 overview tiles from each z18 tile for +34 seconds/tile and +0 MB extra memory (peak is already 633 MB from gdalwarp). Benchmarked — see below.

**Benchmark data (from this session):**

| Metric | Value |
|--------|-------|
| Per-tile gdaladdo time | 34 seconds |
| Per-tile gdaladdo memory | 0 MB additional (633 MB peak set by gdalwarp) |
| Output zoom levels | z15, z16, z17, z18 (from single NAIP quad) |
| Tile counts per quad | z15: 56, z16: 224, z17: 837, z18: 3,172 |
| Size overhead | +16 MB per quad (43 MB → 59 MB) |
| Full job overhead | +3 hours for 322 tiles |

**Implementation:** In `scripts/acquire_imagery.py`, `_process_tile()` function, add `gdaladdo -r average` on the temp MBTiles BEFORE merging into the main output. The temp file is small (~43 MB) so gdaladdo is fast. After gdaladdo, the temp file has z15-z18 and gets merged into the main output preserving all zoom levels.

**Also needed:** When overlay imagery is toggled on, restyle basemap vector layers to match the hybrid style (white semi-transparent roads, white-on-dark-halo labels, no building/landuse fills). The hybrid style at `tileserver/styles/hybrid/style.local.json` has 35 layers with these paint properties already defined — they need to be applied dynamically via `map.setPaintProperty()` when any overlay imagery is visible.

### 2. Pipeline Admin Page Overhaul (HIGH PRIORITY)

**Problem:** The Pipelines tab at localhost:8097 has 4 imagery sources in one dropdown (USGS Direct, USGS M2M, National Map NAIP, NOAA NAIP), plus Sentinel-2 and NAIP county-lookup cards below, plus a BYO import card. It's confusing — users don't know which source to pick or what each produces.

**What users need to understand at a glance:**
- What imagery do I already have? (covered in subsystem 3 below)
- What resolution/coverage does each source provide?
- Which ones need credentials vs. are free?
- How long will each take?

**Current state:** Source dropdown with 4 options + contextual help text per selection. NOAA has an "Estimate Download" button showing tile count, download size, final size, and ETA. Other sources have basic tile count estimates.

**Design direction:** Replace the single dropdown with a card-per-source layout. Each card shows: source name, resolution, auth requirements, coverage area, estimated time, and a "Start" button. Cards should be collapsible like the existing Sentinel/NAIP cards.

### 3. Imagery Inventory Manager (HIGH PRIORITY)

**Problem:** Users have no way to see what imagery they've downloaded, at what zoom levels, covering what areas. With 4+ sources producing separate MBTiles files, they need a visual inventory.

**Cameron's vision:** A map showing partially transparent labeled overlays for each imagery source. Users can select an overlay to see its details (zoom range, tile count, file size, download date) and manage it (delete, re-download, extend coverage).

**Data available:** Each MBTiles file has metadata (bounds, minzoom, maxzoom) and tile data that can be queried for actual coverage. TileServer config.json lists all registered data sources.

**Implementation approach:** Add a new tab or section in the admin panel that:
1. Reads all `imagery_*.mbtiles` files from the data directory
2. For each, queries SQLite for zoom levels, tile counts, bounds
3. Renders a MapLibre map with semi-transparent colored rectangles showing each source's coverage
4. Clicking a source shows details + management options (delete file, restart pipeline for this area)

### 4. Mobile Navigation UX Fixes (MEDIUM)

Three specific bugs:

**a) Search bar takes too much space in navigation mode:**
When navigation is active, the search bar should collapse to just search + voice icons positioned to the right, out of the way of the turn-by-turn instructions.

**b) Scale bar position:**
Currently sits on top of the zoom +/- controls. Should be at the bottom of the page, to the LEFT of the zoom controls.

**c) Navigation pane z-order:**
The left-hand control pane (sidebar) layers UNDER the turn-by-turn navigation top pane. It should be ON TOP so users can manipulate controls while navigating. The nav pane should go behind the sidebar when the sidebar is open.

Files: `frontend/app.js`, `frontend/nav-ui.js`, `frontend/index.html` (CSS)

### 5. Frontend/Backend UI Overhaul (MEDIUM)

Use the `frontend-design` skill for a visual refresh of both:
- **Frontend (map app):** sidebar design, control layout, imagery toggles, dark mode polish
- **Backend (admin panel):** pipeline cards, settings, credential management, import card

Cameron's preferences: dark mode, ~800px max-width for UI elements, Catppuccin-esque color palette (already in use: `#89b4fa` blue, `#f9e2af` amber, `#a6e3a1` green, `#f38ba8` red, `#313244` dark bg).

### 6. Documentation Update (DO LAST)

After all features are implemented:
- Review README.md against all changes
- Update CLAUDE.md with new files, commands, architectural details
- Update START.md for the next agent session
- Check for stale content from parallel agent sessions

## Current system state

### Running services (Docker Compose)
- **TileServer GL** (:8090) — vector basemap + elevation + aerial imagery + public lands + NOAA NAIP
- **Valhalla** (:8094) — routing engine, 11 Western US states
- **Nominatim** (:8092) — geocoding, 11 Western US states imported
- **GPS** (:8095) — FastAPI WebSocket, reads Pi's GPS hat via gpsd
- **Search** (:8096) — spatial search + admin API + pipeline orchestration + NOAA/import endpoints
- **STT** (:8098) — Whisper base.en (CPU + NPU backends), push-to-hold mic button
- **NGINX/Frontend** (:8093 HTTP, :443 HTTPS) — main app + config panel on localhost:8097

### Imagery sources (current state)

| Source | Mode | File | Status | Zoom | Coverage |
|--------|------|------|--------|------|----------|
| USGS Direct (tile scraper) | `direct` | `imagery.mbtiles` (25 GB) | COMPLETE | z0-z14 | Western US |
| USGS M2M | `m2m` | `imagery_az.mbtiles` (304 MB) | Partial (50 tiles) | z19 | SE Arizona |
| National Map ImageServer | `nationalmap` | `imagery_naip.mbtiles` (150 MB) | TESTED | z15 | Small test areas |
| NOAA Digital Coast | `noaa` | `imagery_noaa.mbtiles` (1.7 GB) | 53/322 tiles | z18 | Phoenix metro (partial) |
| BYO Import | `import_imagery.py` | `imagery_custom.mbtiles` | NOT TESTED | varies | user-provided |

**Critical gap:** z15-z17 has no imagery. The NOAA pipeline produces z18 only. The gdaladdo fix (subsystem 1 above) fills this gap.

**National Map throttling:** The ImageServer throttles sustained bulk downloads to ~1 tile/sec after a few minutes. Useful for small areas only (~1000 tiles). IP-based rate limit persists for 3+ hours.

**NOAA unthrottled:** Azure Blob Storage, no auth, ~2.7 MB/s per connection. 3 concurrent downloads. Pipeline has producer-consumer pattern with asyncio. ~6 min/tile effective rate. Per-tile checkpoint resume works.

**USDA Gateway:** Officially unavailable since April 3, 2026. The `acquire_naip.py` script targets this source but it's dead.

### NOAA Pipeline Technical Details

The NOAA pipeline (`run_noaa()` in `scripts/acquire_imagery.py`) was extensively debugged in this session. Key details for the next agent:

- **Tile index:** NOAA distributes as a ZIP archive (`tileindex_*.zip`) containing .shp/.shx/.dbf/.prj. The code downloads the ZIP, extracts, caches in `/data/noaa_cache/{STATE}_{YEAR}/`.
- **Spatial filtering:** `ogr2ogr -f CSV /dev/stdout <shp> -spat w s e n -select filename` returns intersecting tile filenames.
- **Download:** `fetch_to_file()` with `sock_read=120s` timeout (detects stalled connections in 2 min instead of 30 min), 5 retries with 30s/60s/120s/240s/480s backoff.
- **Processing per tile:** download (~150s) → `gdalwarp -t_srs EPSG:3857` (~85s) → `gdal_translate -of MBTiles` (~100s) → merge into main output → delete staging files.
- **Concurrency:** 3 concurrent downloads via `asyncio.Semaphore`, sequential GDAL processing via `asyncio.Queue` + `run_in_executor`.
- **Cancel:** SIGTERM handler kills child GDAL process group via `os.killpg(os.getpgid(_child_pid), signal.SIGTERM)`.
- **Catalog:** Static dict `NOAA_NAIP_CATALOG` — currently only Arizona 2021 (`AZ_NAIP_2021_9596`). Needs other Western US states populated.
- **Estimate endpoint:** `GET /admin/pipeline/noaa/estimate?bbox=...&state=AZ` uses pure-Python DBF reader (no GDAL in search container) with area-ratio approximation.
- **TileServer integration:** Pipeline updates `tileserver/config.json` via `TILESERVER_CONFIG` env var. The catch-all `/tiles/` NGINX location has `sub_filter` rewriting for `$http_host` patterns.

### Navigation system (2026-04-14 overhaul — 14 bugs fixed + compass button)
- Event-driven GPS feed from WebSocket callback (NOT polling)
- Off-route detection: 3-of-5 rolling window with hysteresis (50m enter, 35m exit)
- Reroute recovery: 10s engine timeout + 3 retries with exponential backoff
- Voice: 5s cooldown, 2 m/s speed gate, 50m near-maneuver exemption
- Bug hunt reports: `dev/bug-hunts/2026-04-14-navigation-*.md`

### Setup wizard
- `bootstrap.sh` + `setup.sh` → browser wizard on localhost:8099
- Custom storage path, pre-flight checks, auto-fix buttons, dark mode
- See `docs/superpowers/specs/2026-04-10-setup-wizard-design.md`

### LXD validation harness
- Automated README testing in isolated Debian 13 LXC containers
- Generalized skill at `.claude/skills/lxd-validation/`
- Reports: `docs/validation/`

### TLS
- **Tailscale HTTPS active**: `https://pandora.twin-bramble.ts.net` (Let's Encrypt)
- Dual-mode: HTTP on :8093 (LAN/AREDN) + HTTPS on :443 (Tailscale)

### Tests
475+ tests across project. Run: `python -m pytest tests/ -v`
(9 pre-existing asyncio event loop errors in test_osm_poi_search and test_spatial_osm — test isolation issue, not a bug)

### Data
- **Elevation z0-14**: ~120 GB
- **Imagery z0-14**: 25 GB (just restored)
- **Imagery NOAA z18**: 1.7 GB (53/322 Phoenix tiles)
- **Public lands**: 412 MB
- **POI index**: GNIS + OSM amenities
- **Vector basemap**: 2.4 GB (southwest5.mbtiles)
- **Disk free**: ~576 GB

### Key files
- `docker-compose.yml` — 7 persistent services + pipeline
- `services/search/main.py` — Search API, admin API, pipeline orchestration, NOAA/import endpoints
- `frontend/app.js` — Main frontend (~4000 lines), imagery toggles, overlay state management
- `frontend/config/index.html` — Admin panel (~1800 lines), pipeline UI, NOAA estimate, BYO import
- `frontend/navigation.js` — Navigation engine
- `frontend/nav-ui.js` — Navigation UI
- `scripts/acquire_imagery.py` — All imagery modes (direct, m2m, nationalmap, noaa), concurrent pipeline
- `scripts/import_imagery.py` — BYO GeoTIFF import
- `scripts/tileserver_config.py` — TileServer config.json updater
- `scripts/pipeline_security.py` — Path traversal guards, layer name sanitization
- `tileserver/config.json` — TileServer data source registry
- `tileserver/styles/hybrid/style.local.json` — 35-layer hybrid imagery+roads style
- `nginx/nginx.conf` — Reverse proxy with sub_filter URL rewriting

### Custom skills
- `.claude/skills/build-robust-features/` — Brainstorm → adversarial → subagent-proof plan
- `.claude/skills/bug-hunt-cycle/` — 3-hunter parallel dispatch + consolidation
- `.claude/skills/code-bug-hunter-*/` — Exploratory, holistic, multipass analysis
- `.claude/skills/lxd-validation/` — LXD container doc testing

## Key architectural details

1. **NGINX sub_filter for TileServer URLs:** The catch-all `/tiles/` location rewrites both `http://tileserver:8080/` and `http://$http_host/` patterns to `$scheme://$http_host/tiles/`. This is critical — without it, TileJSON responses contain internal URLs that fail on HTTPS. Per-source location blocks exist for the original 6 data sources; new sources use the catch-all.

2. **TileServer does NOT auto-discover MBTiles.** New data sources must be added to `tileserver/config.json` and TileServer restarted. The `tileserver_config.py` helper does this atomically.

3. **Pipeline container runs as root.** Files it creates need `chmod a+rw` for TileServer (runs as uid 999 `node`). The `/srv/geographica/data/` directory itself must be world-writable for SQLite journal creation.

4. **`log` is NOT defined in `services/search/main.py`.** All `log.error()` calls in exception handlers are dead code. Use `print()` for diagnostics. (Should be fixed properly with `logging.getLogger(__name__)`.)

5. **Overlay imagery toggle state management:** `_updateOverlayImageryState()` in `app.js` hides conflicting basemap layers (buildings, landuse, parks) when any overlay imagery is visible. The opacity slider works for both hybrid and overlay imagery. But the basemap road/label styling is still positron (dark on white) — needs to switch to hybrid styling (white on dark) for proper imagery overlay.

6. **The hybrid style is a complete 35-layer MapLibre style** with imagery as the base. It has NO building fills, NO landuse fills. Roads use semi-transparent white (`rgba(255,255,255,0.35)`), labels use white text with dark halos. This is what the overlay imagery needs to replicate via dynamic `setPaintProperty()` calls.

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
