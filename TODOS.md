# TODOS

## Completed

### TLS implementation for device GPS
- **Completed 2026-04-08** via Tailscale TLS integration. `TLS_MODE=tailscale` with Let's Encrypt certs. Device GPS works over HTTPS. See `docs/superpowers/specs/2026-04-08-tailscale-tls-design.md`.

### Natural language spatial search (Phase 2a)
- **Completed 2026-04-08.** Intent parser, corridor search, numbered map pins, distance badges. See `docs/superpowers/specs/2026-04-08-natural-language-spatial-search-design.md`.

### Elevation tile download
- **Completed 2026-04-08.** 1,474,959 tiles z0-z14, covering 11 Western US states.

---

## High Priority

### Phase 2b: Whisper STT — CPU backend
- **Completed and deployed 2026-04-08.** CPU backend (faster-whisper base.en INT8). STT Docker service, push-to-hold mic button, AudioWorklet capture, NGINX proxy with resilient resolver pattern (frontend stays up if STT is down). See `docs/superpowers/specs/2026-04-08-whisper-stt-design.md`.

### Expanded POI data sources
- **Completed 2026-04-08.** OSM amenity + public land extraction from existing PBF. Separate `osm_pois` table with brand-only POI support, BLM/USFS/NPS search, compound index for corridor queries. See `docs/superpowers/specs/2026-04-08-expanded-poi-sources-design.md`.
- **Deploy:** `python3 scripts/build_osm_pois.py --pbf /srv/geographica/data/valhalla/western-us.osm.pbf --output /srv/geographica/data/poi.sqlite --bbox "-124.8,31.3,-102.0,49.0" && docker compose restart search`

### M2M API end-to-end test
- **Validated 2026-04-08.** Full pipeline tested against live USGS M2M API with Tucson bbox. 8 scenes found, 4 GeoTIFFs downloaded (1.07 GB), 52,760 tiles at z15-z19 (3 zoom levels beyond direct mode). Three code fixes: product name filter update (USGS renamed products), field mapping fix (`id` not `productId`), removed invalid `downloadApplication` parameter. See `dev/m2m-test-results.md`.

### Whisper NPU backend — revisit at hailo-10-all 5.3.0
- **What:** Swap Whisper STT from CPU (faster-whisper) to NPU (HailoRT) for faster inference on the Hailo 10H.
- **Why:** NPU should be significantly faster than CPU for Whisper inference. CPU backend works but takes ~3s per utterance.
- **Status:** Investigated 2026-04-08. Whisper-Base.hef (131MB, compiled for 5.3.0) loads on 5.1.1 firmware (metadata readable) but `VDevice.configure()` fails with `HAILO_NOT_IMPLEMENTED`. The 5.3.0 model uses operations unavailable in 5.1.1 runtime. See `dev/npu-investigation-results.md`.
- **Action:** When `hailo-10-all` reaches 5.3.0 for Pi 5, re-run `configure()` test. The `npu.py` skeleton and architecture docs are ready. Single-pass decoder design (64 tokens, vocab split across 4 outputs) is documented.
- **Depends on:** Hailo Pi 5 package update to 5.3.0+.

---

## Medium Priority

### NGINX selective compression optimization
- **What:** Apply `sub_filter` URL rewriting only to style JSON/TileJSON endpoints, let tile data pass through with gzip compression intact.
- **Why:** On bandwidth-constrained AREDN mesh, PBF vector tiles compress ~60-70%. Currently all TileServer GL responses are uncompressed due to blanket `Accept-Encoding ""` header required by sub_filter.
- **Pros:** Significant bandwidth reduction for vector tile serving over mesh.
- **Cons:** More complex NGINX config with multiple location blocks.
- **Depends on:** NGINX config stable (it is now).

### Setup CLI tool
- **What:** A `geographica-setup` command that detects the network environment, generates TLS certs if needed, writes `.env`, and restarts the frontend container.
- **Why:** Current setup requires editing .env, running provision scripts, and restarting containers separately.
- **Depends on:** TLS implementation (done).

### GPS track recording
- **What:** Record GPS tracks and export as GPX/KML. Design doc specifies this as a Phase 1 feature.
- **Why:** Users on field deployments need track logs for after-action reports.
- **Depends on:** GPS service (done), frontend (done).

### Valhalla costing toggles
- **What:** Expose avoid highways/tolls/ferries toggles in the routing panel UI.
- **Why:** The routing code already supports these options (app.js:993-1005) but the UI has the checkboxes — need to verify they're wired up and working.
- **Depends on:** Nothing.

### Light/dark mode toggle
- **What:** Runtime toggle between Positron (light) and Dark Matter (dark) basemap styles.
- **Why:** Both styles exist in TileServer but there's no UI toggle. Design doc specifies this.
- **Depends on:** Nothing.

---

### Public land use map layer
- **What:** Add public land boundaries (BLM, USFS, NPS, state lands) to the vector basemap or as a toggleable overlay layer. Show checkerboard ownership patterns that are invisible on the ground.
- **Why:** Public/private land boundaries in the Western US are often unmarked. Knowing whether you're on BLM, National Forest, or private land is critical for field operations, recreation, and regulatory compliance.
- **Depends on:** Expanded POI sources (provides the `boundary=protected_area` data with operator/agency attribution).

---

## Low Priority / Deferred

### Search debounce/abort pattern
- **What:** 300ms debounce + AbortController for search input.
- **Why:** Rapid typing could queue queries. Deferred because Pi 5 Nominatim is fast.
- **Depends on:** Frontend search (done).

### Data freshness / update workflow
- **What:** Workflow for updating stale map data.
- **Why:** Offline maps decay. For v1, "re-run the pipeline" is acceptable.

### Admin task monitor enhancements
- **What:** Surface Nominatim/Valhalla import progress in the UI.
- **Why:** Improves first-run experience. `/admin/status` exists but could show more.

### Offline KML icon set
- **What:** Bundle ~200 Google Earth icons (~2 MB) for offline KML rendering.
- **Why:** KML imports with Google-hosted icons fail offline.
- **Depends on:** KML import (done).

### KML popup rendering improvements
- **What:** Handle edge cases with HTML/CDATA descriptions from various authoring tools.
- **Depends on:** KML import (done).

### AREDN TLS 1.2 published-key mode
- **What:** TLS 1.2 with non-PFS ciphers and published private key for Part 97 compliance.
- **Status:** Deferred — regulatory landscape is ambiguous. HTTP works fine for AREDN.
