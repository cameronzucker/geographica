# TODOS

## Deferred from Phase 1

### NGINX selective compression optimization
- **What:** Apply `sub_filter` URL rewriting only to style JSON/TileJSON endpoints, let tile data pass through with gzip compression intact.
- **Why:** On bandwidth-constrained AREDN mesh, PBF vector tiles compress ~60-70%. Currently all TileServer GL responses are uncompressed due to blanket `Accept-Encoding ""` header required by sub_filter.
- **Pros:** Significant bandwidth reduction for vector tile serving over mesh.
- **Cons:** More complex NGINX config with multiple location blocks for the same upstream. URL rewriting across multiple location blocks is fragile and hard to debug.
- **Context:** Decision made during eng review to defer. Core platform stability takes priority over bandwidth optimization. Revisit after Phase 1 is stable and field-tested.
- **Depends on:** Phase 1 complete, NGINX config stable.

### Search debounce/abort pattern
- **What:** Add 300ms client-side debounce and AbortController to cancel in-flight search requests on new keystrokes.
- **Why:** Rapid typing could queue up Nominatim PostgreSQL queries on the Pi. Reference stack showed instant results with single user, but untested under load.
- **Pros:** Prevents query pile-up if multiple users or rapid interaction.
- **Cons:** Minimal code (~10 lines), but adds complexity to search flow.
- **Context:** Deferred because real-world testing on Pi 5 showed instant Nominatim responses. Add a diagnostic: if p95 search latency exceeds 500ms under rapid sequential queries, implement debounce.
- **Depends on:** Frontend search implementation complete.

### Data freshness / update workflow
- **What:** Define a workflow for updating stale map data (OSM extracts, imagery, Nominatim, Valhalla routing graph).
- **Why:** Offline maps decay. OSM data changes, roads get built, imagery gets updated. Without an update path, operators will stop trusting the data.
- **Pros:** Keeps the platform trustworthy over time.
- **Cons:** Re-running the full data pipeline is time-consuming (days for imagery, hours for Nominatim import).
- **Context:** Codex outside voice raised this (point #27). For v1, "re-run the pipeline" is acceptable. A future version could support incremental OSM updates via Osmium and differential Nominatim updates.
- **Depends on:** Phase 0 data pipeline proven.

### Admin task monitor in UI
- **What:** A panel in the frontend (or a dedicated /admin page) that shows the status of long-running backend tasks: Nominatim import progress, Valhalla graph build, tile downloads, POI indexing. Display progress percentage, ETA, and current phase where available.
- **Why:** First-run setup involves multiple multi-hour imports running simultaneously. Right now the only way to check progress is SSH + `docker logs`. An operator deploying Geographica on a mesh should be able to check import status from any browser on the network without terminal access.
- **Pros:** Dramatically improves the first-run experience. Also useful for data refresh workflows (re-importing after an OSM update). Could surface service health at a glance — which containers are up, which are still initializing.
- **Cons:** Requires a lightweight status API that polls container logs or healthcheck endpoints. Nominatim and Valhalla don't expose structured progress — would need log parsing or periodic healthcheck probing.
- **Context:** Identified during Phase 0 deployment while waiting ~8 hours for Nominatim to import 11 Western US states. The operator experience of "is it done yet?" with no visibility is poor.
- **Depends on:** Phase 1 frontend complete. Could be a simple addition to the search/POI FastAPI service (add a /admin/status endpoint that checks healthchecks and parses recent Docker logs via the Docker socket).

### Offline KML icon set for common Google Earth markers
- **What:** Bundle the standard Google Earth/Maps icon set (pushpins, shapes, paddles) locally so KML IconStyle references to `maps.google.com/mapfiles/kml/` URLs render correctly when offline.
- **Why:** Most KML/KMZ files reference Google-hosted icons via URLs like `http://maps.google.com/mapfiles/kml/pushpin/ylw-pushpin.png`. On an offline AREDN deployment these URLs are unreachable, so marker icons fail to load. Currently, broken icon URLs are hidden gracefully (onerror handler), but the intended visual distinction between marker types is lost.
- **Pros:** KML imports look correct without internet access. The Google Earth icon set is small (~200 icons, ~2 MB total) and freely redistributable.
- **Cons:** Requires downloading and bundling the icon set, plus URL rewriting logic in the import pipeline to map `maps.google.com/mapfiles/kml/...` paths to local equivalents.
- **Context:** Identified when importing Ham Radio Deployment Sites.kmz which uses pushpin, caution, and triangle icons. Could also render icons as SVG symbols on the MapLibre canvas for better scaling.
- **Depends on:** KML import feature complete (done).
