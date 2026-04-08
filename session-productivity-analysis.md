# Geographica Marathon Session — Productivity Analysis

**Session window:** April 7, 2026 01:37 AM — April 8, 2026 00:21 AM (~23 hours wall clock)
**Active development time:** ~18 hours (excluding OOM downtime ~01:00–14:00)
**Output:** 49 files, 17,107 lines of code, 76 commits
**Result:** A fully functional offline GIS platform running 7 Docker services on a Raspberry Pi 5

---

## Timeline

### Phase 1: Design + Scaffolding (01:37 – 03:42) — ~2 hours

| What | Commits | Lines |
|------|---------|-------|
| Brainstorming session via /office-hours skill — problem statement, architecture review, storage budgets, cross-model adversarial critique, approach selection | 0 (design doc) | ~500 (design doc) |
| Project baseline — CLAUDE.md, .gitignore, skill routing | 3 | ~1,350 |
| Docker Compose (6 services), NGINX reverse proxy, TileServer GL config | 1 | ~280 |
| GPS FastAPI service — gpsd WebSocket, stale detection | 1 | ~215 |
| Unified search service — Nominatim + SQLite FTS5 merge, haversine dedup | 1 | ~270 |
| Data pipeline scripts — imagery acquisition (3 modes), POI indexer, elevation downloader | 1 | ~970 |
| MapLibre GL frontend — layers, search, routing, GPS, KML import | 1 | ~1,740 |
| Data safety — move large files outside repo, .gitignore hardening | 1 | ~50 |

**Unassisted human estimate: 2–3 weeks (80–120 hours)**

This phase involved designing a multi-service architecture from scratch, writing a Docker Compose stack with health checks and inter-service dependencies, building two Python microservices with WebSocket support, creating three data pipeline scripts that interface with USGS APIs, and a ~1,700-line MapLibre frontend with search, routing, layers, and KML import. A skilled developer familiar with all these technologies would spend significant time on: Docker networking and volume mounts (~1 day), NGINX reverse proxy with sub_filter rewriting (~0.5 days), gpsd integration and WebSocket protocol (~1 day), Nominatim API integration + FTS5 search merge (~1.5 days), USGS TNMAccess/M2M API integration with GDAL (~2–3 days), MapLibre GL JS frontend from scratch (~5–7 days), and initial testing/debugging cycles (~2–3 days).

---

### Phase 2: 3D Terrain + Map Polish (04:34 – 05:25) — ~1 hour

| What | Commits | Lines |
|------|---------|-------|
| NGINX sub_filter fix for TileServer proxying | 1 | ~10 |
| Elevation MBTiles in TileServer config | 1 | ~115 |
| 3D terrain rendering with Terrarium RGB encoding | 1 | ~280 |
| Terrain exaggeration slider + free-look camera (Ctrl+drag) | 1 | ~150 |
| Basemap readability improvements, house numbers at z17+ | 1 | ~100 |
| Coverage expansion to 11 Western US states | 1 | ~5 |

**Unassisted human estimate: 2–3 days (16–24 hours)**

3D terrain in MapLibre GL JS requires understanding Terrarium vs Mapbox RGB encoding, configuring the raster-dem source, wiring addTerrain/addSky, and getting the hillshade layer right. The exaggeration slider with real-time terrain updates and free-look camera require non-obvious MapLibre API knowledge. Style customization (label contrast, house number zoom thresholds) involves iterating on dozens of style-spec properties.

---

### Phase 3: OOM Recovery + Documentation (14:27 – 14:29) — ~30 minutes

| What | Commits | Lines |
|------|---------|-------|
| Docker memory limits (all 6 services, 13.5 GB ceiling) | 1 | ~500 |
| Complete README setup guide (12-step walkthrough for beta testers) | 1 | — |

**Unassisted human estimate: 3–4 hours**

The OOM debugging required examining Docker stats, understanding the Pi's 16 GB memory budget, and sizing each service appropriately. The README required distilling the entire data pipeline into reproducible steps for a new operator.

---

### Phase 4: GPS + UI + Coordinates (16:51 – 17:43) — ~1 hour

| What | Commits | Lines |
|------|---------|-------|
| GPS center button, accuracy circle (geographic layer, not screen overlay) | 3 | ~375 |
| Status bar — GPS position + camera eye altitude | 1 | ~50 |
| Imperial/metric unit toggle (global, all displays) | 1 | ~35 |
| Maidenhead grid + MGRS coordinate display | 1 | ~240 |
| Position detail overlay — tap-to-copy all coordinate formats | 1 | ~200 |
| Mobile responsive sidebar (slide-out overlay) | 1 | ~40 |
| KML folder-aware layer management with per-feature controls | 1 | ~240 |
| KML color/line-width/opacity preservation | 1 | ~100 |
| KML popup sanitization (hide broken images, internal properties) | 1 | ~60 |

**Unassisted human estimate: 1–1.5 weeks (40–60 hours)**

The GPS accuracy circle alone is surprisingly complex — it must be a geographic GeoJSON circle (not a screen-space ring) that scales with map zoom, requiring haversine math to generate a 64-point polygon. Maidenhead grid locators and MGRS coordinates require implementing the encoding algorithms. The KML layer management system with folder hierarchy, per-feature toggles, and color preservation from KML's unusual color format (aaBBGGRR) is a substantial feature. Mobile responsive layout with a slide-out sidebar that interacts correctly with the map required careful z-index and touch event management.

---

### Phase 5: Search + Pipeline Fixes + Admin Monitor (18:06 – 18:55) — ~1 hour

| What | Commits | Lines |
|------|---------|-------|
| Search UX fix (Enter-only, remove dimming overlay) | 1 | ~25 |
| GNIS data source fix (swap to S3 when primary 503'd) | 1 | ~45 |
| Admin task monitor — service health + data pipeline status API | 1 | ~430 |
| SQLite WAL mode for concurrent read/write | 2 | ~65 |

**Unassisted human estimate: 2–3 days (16–24 hours)**

The admin monitor required adding a `/admin/status` endpoint that queries Docker container health via the Docker socket, parses MBTiles tile counts from SQLite, and reports pipeline progress. The SQLite WAL mode fix required understanding why concurrent reader/writer access was failing — the pipeline writes tiles while TileServer reads them — and switching from journal to WAL mode across all MBTiles databases.

---

### Phase 6: Turn-by-Turn Navigation (19:00 – 20:30) — ~1.5 hours

| What | Commits | Lines |
|------|---------|-------|
| Multi-stop waypoints, GPS fill, reverse geocode on map click | 1 | ~425 |
| Technical proposal document (reviewed) | 1 | ~500 |
| Navigation engine (navigation.js — 790 lines) | 1 | ~1,000 |
| Nav UI bridge (nav-ui.js — 860 lines) | 1 | ~1,100 |
| Map centering with sidebar offset compensation | 1 | ~100 |
| Mute button event propagation fix | 1 | ~5 |
| Hamburger/nav overlay z-index fixes | 1 | ~20 |
| GPS source toggle with secure context check | 2 | ~75 |

**Unassisted human estimate: 2–3 weeks (80–120 hours)**

Turn-by-turn navigation is a major feature. The engine (790 lines) implements: route geometry snapping, step advancement with distance thresholds, off-route detection with automatic rerouting, dead reckoning when GPS is lost, bearing-based instruction generation, and Web Speech API voice guidance. The UI bridge (860 lines) connects the engine to MapLibre with: animated route line, camera tracking with bearing rotation, instruction cards with distance countdown, maneuver icons, and arrival detection. The multi-stop waypoint system with drag-to-reorder, GPS autofill, and map-click reverse geocoding adds another layer. A skilled frontend developer would spend days just on the route snapping and step advancement algorithms.

---

### Phase 7: Imagery Pipeline + Management UI (20:55 – 23:14) — ~2.5 hours

| What | Commits | Lines |
|------|---------|-------|
| 17x faster imagery download (remove rate limit, 80 concurrent connections) | 1 | ~45 |
| M2M API mode for NAIP imagery | 1 | ~270 |
| SIGTERM handling + JSON progress for pipeline scripts | 1 | ~130 |
| NGINX admin read/write route separation | 1 | ~20 |
| Pipeline Docker container (profiles, GDAL, volume mounts) | 1 | ~100 |
| Pipeline orchestration API (credentials, start, status, cancel) | 1 | ~400 |
| Imagery management UI (config panel) | 1 | ~130 |
| 7 bugs + 2 design decisions from 3-hunter bug hunt | 1 | ~625 |
| 5 UI bugs in pipeline management | 1 | ~45 |
| Various pipeline fixes (staging dir, restore layers, zoom options, O(1) checkpoint, naming races, argparse, display) | 10 | ~350 |
| Draw-on-map bounding box selection with polished UX | 4 | ~200 |
| Progress bars and rates in data pipeline monitor | 2 | ~65 |

**Unassisted human estimate: 2–3 weeks (80–120 hours)**

This phase built a complete pipeline management system: a Docker container with GDAL for imagery processing, an orchestration API that starts/stops/monitors pipeline jobs via the Docker socket, a management UI with source selection and progress monitoring, secure M2M API credential storage, and a draw-on-map bounding box tool. The 3-hunter bug hunt (dispatching 3 parallel AI agents to independently find bugs, then cross-validating) found 7 real bugs and 2 design decisions — the kind of review that would typically happen over days of QA testing.

---

### Phase 8: TLS + Admin Separation + Hardening (23:49 – 00:21) — ~30 minutes

| What | Commits | Lines |
|------|---------|-------|
| Admin panel separation to localhost-only port + TLS support (5 adversarial review rounds) | 1 | ~515 |
| TileServer writable data mount fix | 1 | ~15 |
| Healthcheck + sub_filter absolute URL fixes | 1 | ~15 |
| Comprehensive README update | 1 | ~80 |
| START.md session bootstrap prompt | 1 | ~80 |

**Unassisted human estimate: 1–1.5 weeks (40–60 hours)**

The TLS/admin architecture went through 5 rounds of adversarial review (Claude + Codex cross-model critique). This included: NGINX dual-port config (public 8093 + localhost-only 8097), X-Config-Source + X-Geographica header validation, TLS 1.3 mode with auto-generated self-signed certs, entrypoint.sh for mode selection, and generate_tls.sh for manual cert management. The review process alone — designing, critiquing, revising, re-critiquing across 5 rounds — would consume days of a security engineer's time.

---

## Summary

| Phase | Wall clock | Human estimate |
|-------|-----------|---------------|
| Design + Scaffolding | ~2 hr | 2–3 weeks |
| 3D Terrain + Polish | ~1 hr | 2–3 days |
| OOM Recovery + Docs | ~30 min | 3–4 hours |
| GPS + UI + Coordinates | ~1 hr | 1–1.5 weeks |
| Search + Admin Monitor | ~1 hr | 2–3 days |
| Turn-by-Turn Navigation | ~1.5 hr | 2–3 weeks |
| Pipeline Management | ~2.5 hr | 2–3 weeks |
| TLS + Hardening | ~30 min | 1–1.5 weeks |
| **Total** | **~10 hr active** | **~10–14 weeks** |

### The multiplier

**~10 hours of human-AI collaboration produced ~10–14 weeks of solo developer output.**

That's roughly a **10–14x throughput multiplier** on this particular session. Some caveats:

- **The human estimates assume a single skilled developer** who knows Docker, Python, JavaScript, MapLibre, NGINX, and GIS pipelines. A specialist team would be faster, but would introduce coordination overhead.
- **The estimates include the debugging/polish cycles** that actually happened — the 24 bug fix commits, the 5 rounds of security review, the 3-hunter bug hunt. These aren't overhead; they're the work.
- **The human brought irreplaceable domain expertise.** Cameron's knowledge of USGS APIs, Part 97 regulations, AREDN mesh constraints, and GDAL pipelines guided architectural decisions that the AI couldn't have made alone. The AI moved fast because the human knew exactly where to go.
- **Not all hours are equal.** The 2.5 hours on pipeline management produced ~2,400 lines across Docker, Python, JavaScript, and NGINX — spanning four different technology domains simultaneously. A solo developer would context-switch between these, losing flow each time.

### What the AI was especially good at

1. **Cross-domain fluency** — writing Docker Compose, Python FastAPI, vanilla JavaScript, NGINX config, and shell scripts in the same session without context-switching costs
2. **Boilerplate velocity** — the initial 5,000+ lines of scaffolding in Phase 1 would be the most tedious part for a human; the AI produced it in minutes
3. **Bug hunting** — dispatching 3 parallel agents to independently audit the codebase found 7 real bugs in one pass
4. **Adversarial review** — 5 rounds of cross-model security review on TLS/admin architecture, catching issues that would normally surface weeks later in production

### What the human was essential for

1. **Architectural direction** — choosing USGS M2M over tile scraping, TLS 1.2 published-key for Part 97, the entire offline-first philosophy
2. **Domain knowledge** — knowing that GNIS has an S3 mirror when the primary API 503'd, understanding AREDN bandwidth constraints, knowing which USGS datasets exist
3. **Quality gatekeeping** — asking "what would 10/10 look like" pushed the implementation past good-enough to genuinely complete
4. **Real-world testing** — running the stack on actual hardware, hitting the OOM, discovering the GPS secure context issue, testing KML imports with real ham radio data files
