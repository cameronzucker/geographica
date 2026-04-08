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

### Phase 2b: Whisper STT on Hailo 10H NPU
- **What:** Offline speech-to-text using Whisper on the Hailo 10H NPU. User presses a mic button, audio is captured via Web Audio API, sent to a local Whisper endpoint, transcribed text is fed into `POST /search/spatial`.
- **Why:** The design doc's "what excites the builder most" feature. The spatial search pipeline (Phase 2a) is built and ready to receive transcribed text.
- **Pros:** Hands-free spatial queries while driving/navigating. Full offline capability.
- **Cons:** Hailo SDK integration complexity. Whisper model selection (tiny vs base vs small) affects accuracy vs latency tradeoff. Audio capture on mobile browsers requires HTTPS (already solved).
- **Context:** Design doc Phase 2 section. Hailo 10H NPU is physically installed on the Pi but not yet used. Phase 2a's `POST /search/spatial` is the backend interface — Phase 2b only adds audio→text.
- **Depends on:** Phase 2a (done), Hailo SDK setup.

### Expanded POI data sources
- **What:** Supplement Nominatim + GNIS with additional open POI datasets. Current spatial search returns sparse results for commercial categories (gas, food, hotels) in rural areas because Nominatim only has what's in OSM, and GNIS only has geographic features.
- **Why:** "gas stations along my route" between Phoenix and LA has a 240-mile gap (mile 22 to mile 264) with no results. There are gas stations there — they're just not in our search index.
- **Candidates:** (1) Extract named POIs from our existing OSM PBF using `osmium tags-filter` for `amenity=fuel`, `amenity=restaurant`, etc. (2) Overture Maps Places dataset (Meta/Microsoft, open, strong business coverage). (3) Who's On First gazetteer.
- **Pros:** Dramatically improves spatial search quality, especially for corridor queries.
- **Cons:** More data = larger POI database, longer indexing. Deduplication against Nominatim.
- **Context:** Identified during spatial search testing. The unified search service already handles Nominatim + POI merge with haversine dedup.
- **Depends on:** Nothing — can be implemented immediately. Most impactful improvement for spatial search quality.

### M2M API end-to-end test
- **What:** Test the `--mode m2m` imagery pipeline once ERS download access approval comes through. Credentials stored at `/srv/geographica/data/.credentials.json`.
- **Why:** M2M API provides access to higher-resolution NAIP imagery than the direct tile scraping mode.
- **Status:** ERS approval submitted, pending.
- **Depends on:** USGS ERS approval.

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
