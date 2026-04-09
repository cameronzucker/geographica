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

### Regenerate vector basemap with lower minzoom for minor roads
- **What:** Rebuild `southwest5.mbtiles` using Planetiler with a custom profile that lowers minzoom for minor/service/track roads from z14 to z11-12. BLM/Forest Service roads are invisible in hybrid mode until very close zoom because Planetiler drops them from low-zoom tiles.
- **Why:** Off-road navigation is a core use case. BLM and USFS roads to places like White Pocket, AZ are the only routes and need to be visible from ~3.9 miles eye altitude (z13). Currently they don't appear until z14-15 due to Planetiler's default feature dropping.
- **Prerequisites:** Install `openjdk-21-jre-headless`, download Planetiler JAR, stop Docker services for memory
- **Source data:** `/srv/geographica/data/valhalla/western-us.osm.pbf` (3.1GB, already on disk)
- **Current output:** `tileserver/southwest5.mbtiles` (2.4GB)
- **Approach:** Custom Planetiler YAML profile overriding transportation layer minzoom, or `--transportation-name-min-zoom` CLI flag. Key: lower minzoom for `highway=unclassified/track/service/path` from z14 to z11-12. Must not increase tile sizes so much that rendering becomes slow.
- **Risk:** Larger tiles at z11-13 could worsen the Firefox performance issue. Need to balance road visibility vs tile size.
- **Estimated time:** 1-2 hours (install + build + verify)

### Spatial search in large cities — FIXED
- **Was:** "gas stations in Long Beach, CA" returned 0 results.
- **Root cause:** Geocode timeout was 1.0s but Nominatim takes 1.3s+ for cold queries. The geocode silently failed, returning `geocode_failed` instead of a bbox. The bbox logic was already correct (uses Nominatim's boundingbox).
- **Fix:** Raised geocode timeout to 5.0s in `services/search/geocode.py:69`. Now returns 10 results in 0.47s.

### Imagery coverage visualization
- **What:** A way to see what imagery is currently downloaded, at what zoom levels, and for what geographic areas. Either as an admin panel feature or a map toggle overlay.
- **Why:** With multiple imagery sources (NAIP, Sentinel-2, direct scraper) at different zoom levels for different regions, it's hard to know what you have without querying MBTiles directly. Users need to see gaps, plan downloads, and verify coverage.
- **Options:** (a) Admin panel coverage map — query MBTiles metadata/tile counts by zoom and render a coverage heatmap on the minimap, (b) Map toggle overlay — a "Coverage" checkbox that shows colored bounding boxes or tile grid shading indicating which areas have imagery at what resolution, (c) Admin panel table — zoom level × region matrix showing tile counts and estimated coverage percentage.

### Sentinel-2 imagery pipeline not working
- **What:** `scripts/acquire_sentinel.py` was created by a parallel agent but has not been tested end-to-end. The Copernicus STAC endpoint and auth flow need validation against the live API. The admin panel has a Sentinel-2 pipeline card but it returns 422.
- **Status:** Code exists but untested. The two working imagery modes are M2M (NAIP GeoTIFFs) and the direct tile scraper (TNMAccess).
- **To validate:** Need Copernicus credentials, test STAC search, test download, test GDAL conversion, verify MBTiles output.

### Monitor: search request latency with multiple tile sources active
- **What:** With hybrid imagery + public lands + terrain all active, the browser queues the spatial search fetch behind dozens of concurrent tile requests. This caused 7.6s round-trip times despite the server responding in <200ms.
- **Current fix:** `priority: 'high'` on the search fetch request. This works but is a band-aid — the root cause is browser connection pool contention.
- **Better fixes to investigate:** (a) Enable HTTP/2 on NGINX (`listen 443 ssl http2`) to multiplex all requests over one connection instead of the HTTP/1.1 6-connection limit, (b) Use a separate subdomain or port for API calls vs tile serving so they don't share connection pools, (c) Investigate whether MapLibre can be configured to use lower fetch priority for tile requests.
- **How to reproduce:** Open hybrid mode + public lands + terrain, pan the map, then immediately search "gas stations in bisbee, az". Check HAR trace for the /search/spatial request timing.
- **Evidence:** curl from the same machine shows 197ms. Browser shows 7.6s. The delay is entirely browser connection scheduling.

### Public lands tile build on Pi 5 8GB
- **What:** The public lands tile pipeline (`scripts/build_public_lands.py`) requires stopping Docker services and needs ~6-9GB free RAM for ogr2ogr + Tippecanoe. On the 16GB Pi 5 this works (stop services, build, restart). On an 8GB Pi 5 (which the README lists as compatible), it would OOM even with services stopped.
- **Why:** README claims Pi 5 8GB compatibility. The pipeline needs to work there too.
- **Options to investigate:** (a) Process in geographic chunks (tile by state, then tile-join), (b) Use ogr2ogr `-limit` batching with append mode, (c) Reduce Tippecanoe memory via `-z12` instead of `-z14`, (d) Build on x86 and copy MBTiles to Pi, (e) Streaming GeoJSON processing to avoid loading entire 674MB file into memory.
