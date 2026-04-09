# Adversarial Review: Admin Panel Redesign Spec

**Spec:** `docs/superpowers/specs/2026-04-09-admin-panel-redesign-design.md`
**Date:** 2026-04-09
**Reviewers:** 5 adversarial personas

---

## Round 1 -- Implementation Feasibility

**Persona:** A developer picking up this spec to implement it from scratch.

### Issues Found

**1.1 CRITICAL -- GPS service has no satellite count data**
The spec says the GPS `/status` endpoint returns `"satellites": 12`, and the Dashboard shows "3D fix, N sats". But the GPS service (`services/gps/main.py`) does **not** read satellite count from gpsd at all. The `gps3.DataStream` object would need `data_stream.satellites_used` or parsing of SKY sentences. The `_position` dict tracks lat/lon/alt/speed/heading/fix/accuracy -- no satellite field exists. The spec treats this as a simple "read from existing state" endpoint but it requires **new gpsd parsing logic**.

**Fix:** Add a section to the spec explicitly noting that `_blocking_read_gpsd()` must be modified to track satellite count from SKY messages. Specify the gps3 attribute name or the fallback strategy if SKY data is unavailable.

---

**1.2 CRITICAL -- `PipelineStartBody` rejects `type=osm_poi`**
The spec says to add `type=osm_poi` support to the pipeline orchestrator. But `PipelineStartBody` (line 73-79) validates `type: str` with the comment `"imagery" or "elevation"`, and the endpoint (`/admin/pipeline/start`, line 765) explicitly rejects anything else: `if body.type not in ("imagery", "elevation")`. The spec says "Add `type=osm_poi` support" but does not detail:
- The validation changes required
- What `mode` means for OSM POI extraction (the Pydantic model requires `mode`)
- What `bbox` and `zoom` mean for OSM extraction (they are irrelevant)
- The script path (`build_osm_pois.py` has different CLI args: `--pbf`, `--output`, `--bbox`)

**Fix:** Define the full `osm_poi` pipeline contract: new Pydantic model or make existing fields optional; specify the exact `docker run` command with PBF path, output path, and bbox arguments; specify where the PBF path comes from (hardcoded? discovered from valhalla volume?).

---

**1.3 MAJOR -- `_parse_zoom` rejects zoom 19 but spec allows it**
The spec says M2M zoom options go up to 0-19. But `_parse_zoom()` (line 117) enforces `zoom_max > 18` as invalid. The frontend already has zoom 19 options, but the backend will reject them with a 422 error.

**Fix:** Spec should note that `_parse_zoom` must be updated to allow zoom_max up to 19 (or 20 if M2M can theoretically go higher).

---

**1.4 MAJOR -- TLS cert parsing library not specified**
The spec says to use `ssl.PEM_cert_to_DER_cert` + `x509` to parse cert expiry. Python's `ssl` module can convert PEM to DER, but there is no `x509` in the stdlib. Parsing expiry requires either `cryptography` (pyOpenSSL), `openssl` subprocess call, or `ssl.get_server_certificate()` dance. The search service's `requirements.txt` would need a new dependency.

**Fix:** Specify the exact library. Recommended: shell out to `openssl x509 -enddate -noout -in /tls/server.crt` to avoid adding a dependency, or explicitly add `cryptography` to requirements.

---

**1.5 MAJOR -- Minimap tile proxy URL rewriting is underspecified**
The spec says "Add a `/tiles/` location to the config panel server block." The main server block has 5 separate `/tiles/` locations with different `sub_filter` rewriting rules for style JSON, TileJSON endpoints, and raw tile data. The minimap needs at minimum the style JSON rewritten (so MapLibre can find tile sources), plus the data and font endpoints. Simply adding one `proxy_pass` will not work because the style JSON contains hardcoded `http://tileserver:8080/` URLs.

**Fix:** Specify which `/tiles/` locations need to be duplicated (at minimum: `/tiles/styles/`, `/tiles/data/`, `/tiles/fonts/`, and catch-all `/tiles/`), or define a simpler approach (e.g., inline the style JSON in the frontend with pre-resolved URLs).

---

**1.6 MINOR -- Spec says 287-line file but actual file is 307 lines**
The spec references "a 287-line vanilla JS file." The actual `frontend/config/index.html` is 307 lines.

**Fix:** Cosmetic, no functional impact. Update the line count or remove the specific number.

---

**1.7 MINOR -- "Nk GNIS + Mk OSM POIs" context string requires new backend query**
The spec's Dashboard context for the search service shows POI counts (e.g., "142k GNIS + 38k OSM POIs"). The current `/admin/status` endpoint only returns POI count from `poi_features` table. It does not return separate GNIS vs OSM counts, and the OSM count query is not part of the current status code.

**Fix:** Spec should note that `admin_status()` needs two new SQL COUNT queries: one for `poi_features` and one for `osm_pois`.

---

**1.8 MINOR -- Concurrency options change based on source, but spec doesn't define defaults**
The spec says concurrency options change based on source selector (3/5 for M2M, 10/20/50/80 for direct). But it doesn't specify the default selected value for each set, which matters for UX consistency when switching back and forth.

**Fix:** Specify default concurrency for each source: direct defaults to 20, M2M defaults to 3.

---

## Round 2 -- API Contract Skeptic

**Persona:** A developer implementing the frontend against the `/admin/status` JSON contract.

### Issues Found

**2.1 CRITICAL -- `gps.satellites` field doesn't exist in current GPS state**
As noted in 1.1, the GPS service's shared `_position` dict has no `satellites` key. The spec's JSON shows `"satellites": 12` but this data does not flow through the system. Even if a `/status` endpoint is added, it can only return what `_position` contains.

**Fix:** Already covered in 1.1. This compounds the issue because the frontend will receive `null` or a missing key and must handle it gracefully.

---

**2.2 MAJOR -- Null vs missing field ambiguity throughout the status response**
The spec shows a single "happy path" JSON example. It does not define what happens when:
- STT is unreachable: is it `{"stt": {"status": "unreachable"}}` or `{"stt": null}` or is the `stt` key absent?
- GPS is unreachable: same ambiguity
- TLS cert doesn't exist: the spec says `{"mode": "http", "cert_expires": null}` but what about `cert_valid`? Is it `false` or absent?
- Docker socket unavailable: the current code returns `{"error": "...", "services": []}` -- do the new fields still appear?

**Fix:** Add a "degraded response" example showing every possible null/absent/unreachable state. Define a contract: all top-level keys are always present; sub-object keys are always present with null for missing data.

---

**2.3 MAJOR -- `tls.mode` detection via Docker environment inspection is fragile**
The spec says to read `TLS_MODE` from the frontend container's environment via Docker socket. But:
- `container.attrs["Config"]["Env"]` returns a list of `KEY=VALUE` strings, not a dict. The spec doesn't mention the parsing logic.
- The frontend container's `TLS_MODE` is set at startup via `entrypoint.sh` and may be overridden to `http` if certs are missing (entrypoint.sh lines 46-47). The environment variable won't reflect this runtime override.
- If the frontend container is restarting or not found, this query fails silently.

**Fix:** Instead of reading TLS_MODE from the container environment, detect TLS mode by checking: (1) if `/tls/server.crt` exists in the mounted volume, and (2) if the cert is a Tailscale cert (check issuer/SAN). This is more reliable and doesn't depend on Docker introspection.

---

**2.4 MAJOR -- Race condition: status endpoint blocks on Docker socket**
The current `admin_status()` is synchronous with respect to Docker operations. `client.containers.list(all=True)` can take 2-5 seconds on a Pi 5, especially if Docker is under load. Adding 3 more HTTP calls (STT health, GPS status) with 2-second timeouts means the worst case is ~11 seconds (Docker list + 3 serial HTTP calls + Docker env inspect). This exceeds the 10-second polling interval.

**Fix:** The spec mentions "per-service 2-second timeouts" but doesn't specify that the HTTP calls should be concurrent (asyncio.gather). Explicitly require: (1) Docker container list in a thread pool (already sync), (2) STT + GPS + TLS queries in parallel via `asyncio.gather`, (3) total endpoint timeout of 8 seconds max so it always finishes before the next poll.

---

**2.5 MAJOR -- `gps.lat` and `gps.lon` in status response expose live GPS coordinates**
The spec's JSON example includes `"lat": 33.4512, "lon": -112.074` in the `/admin/status` response. This endpoint is currently served through the public NGINX port (lines 107-111 in nginx.conf) as a read-only admin endpoint. Anyone on the network can see the device's real-time GPS location.

**Fix:** Either (1) remove lat/lon from the status response (the admin panel doesn't need them for the context string "3D fix, N sats"), or (2) restrict `/admin/status` to the config panel server block only. The current NGINX config exposes it publicly.

---

**2.6 MINOR -- No version field in status response**
The status endpoint doesn't include a Geographica version or commit hash. When debugging issues across deployments, knowing the exact version matters.

**Fix:** Add `"version": "..."` to the status response, read from a `VERSION` file or git describe.

---

**2.7 MINOR -- `disk_used_pct` is an integer but might mislead**
The spec shows `"disk_used_pct": 34` as an integer. At 896 GB total, 1% is ~9 GB, so integer precision is fine. But the field name could be confused with `disk_free_pct`. The existing code uses `_get_disk_free_gb()` which returns free space.

**Fix:** Clarify in the spec that `disk_used_pct` is `100 - (free/total * 100)`, rounded to integer.

---

## Round 3 -- Frontend Complexity Auditor

**Persona:** A frontend engineer estimating the effort for the "full rewrite."

### Issues Found

**3.1 CRITICAL -- Minimap rectangle draw requires a draw library or ~200 lines of custom code**
The spec says "MapLibre map with rectangle draw tool" but does not specify the implementation approach. Options:
- **mapbox-gl-draw** (or @mapbox/mapbox-gl-draw): adds ~150KB minified JS, and the rectangle draw mode is not built-in (requires a custom mode plugin)
- **Custom canvas overlay**: requires mousedown/mousemove/mouseup handlers, coordinate projection, rectangle rendering via GeoJSON source + layer, two-way sync with text field, and touch support. This is easily 150-200 lines alone.
- **terradraw**: lighter library but another dependency

The spec says "vanilla JS, no build step" which means any library must be loaded via CDN `<script>` tag. mapbox-gl-draw's rectangle mode requires both the library and a plugin, loaded in order.

**Fix:** Specify the exact approach: either (a) mapbox-gl-draw loaded from CDN with the rectangle mode plugin, listing the exact CDN URLs, or (b) custom implementation with a rough line count estimate and interaction spec (click-and-drag to create, drag corners to resize, click outside to deselect).

---

**3.2 MAJOR -- Estimated JS line count is far beyond the current 195 lines**
The current `index.html` has ~195 lines of JS (lines 111-304). The new spec adds:
- Tab switching logic: ~30 lines
- MapLibre init + style load: ~20 lines
- Rectangle draw interaction (custom): ~150-200 lines
- Bbox <-> rectangle two-way sync: ~30 lines
- Service health list rendering: ~60 lines (7 services x context string logic)
- TLS section rendering: ~20 lines
- STT section rendering: ~15 lines
- Pipeline progress (imagery + elevation + OSM): ~80 lines
- 3 polling endpoints (status, pipeline/status for imagery, pipeline/status for elevation): ~40 lines
- OSM POI extraction trigger + progress: ~25 lines
- Credential masking display logic: ~20 lines
- Source-dependent concurrency dropdown swap: ~15 lines
- Tab-switch links (banner click, credential warning): ~10 lines
- Estimate calculation (existing, refined): ~30 lines

Conservative total: **550-650 lines of JS** plus ~200 lines of HTML/CSS structure, for a total file of **800-1000 lines**. This is a 3x expansion, not a simple "rewrite."

**Fix:** Acknowledge the scope. Consider splitting into separate JS files (e.g., `config-dashboard.js`, `config-pipelines.js`, `config-settings.js`) loaded by the HTML, or accept the single-file approach but set realistic time estimates.

---

**3.3 MAJOR -- MapLibre GL JS library loading adds significant page weight**
MapLibre GL JS is ~250KB gzipped. The current config panel loads zero external JS libraries. Adding MapLibre plus potentially a draw library means:
- CDN is not available (offline-first platform)
- The library must be served locally from the tileserver or bundled with the frontend
- The NGINX config panel block needs to serve the MapLibre JS/CSS files

The spec does not address how MapLibre JS is loaded in the config panel context.

**Fix:** Specify that MapLibre JS/CSS is already available on the same host (the main frontend uses it). Define the exact `<script>` and `<link>` tags pointing to the correct path, e.g., `/config/maplibre-gl.js` or proxied through the config panel's NGINX block. Note: the main frontend likely loads it from a CDN-like path or bundled file -- verify this and mirror the approach.

---

**3.4 MINOR -- Touch support for minimap unaddressed**
The spec mentions the panel "renders naturally on desktop and mobile." But rectangle draw on a 200px-tall map on mobile is extremely fiddly. Touch events (touchstart/touchmove/touchend) behave differently than mouse events. Pinch-to-zoom on the minimap will conflict with rectangle drawing.

**Fix:** Either (a) disable map zoom/pan on the minimap and make it purely a draw surface, or (b) add a "draw mode" toggle button, or (c) state that the minimap is desktop-only and mobile falls back to text-only bbox input.

---

**3.5 MINOR -- Active Pipeline Banner click-to-switch-tab interaction**
The spec says "Clicking the banner switches to the Pipelines tab." This requires the banner to be aware of the tab system and potentially share state. In vanilla JS this is straightforward but the spec should specify if the banner is rendered inside the Dashboard tab DOM or as a floating overlay.

**Fix:** Clarify that the banner is a child element of the Dashboard tab container, and clicking it calls the same `switchTab('pipelines')` function used by the tab buttons.

---

## Round 4 -- Security and Access Control

**Persona:** A security reviewer focused on attack surface and data exposure.

### Issues Found

**4.1 CRITICAL -- `/admin/status` is publicly accessible and will expose GPS coordinates**
As noted in 2.5, the current NGINX config (lines 107-111) proxies `/admin/status` through the public server block (port 80/443). The spec adds GPS lat/lon to this response. Any device on the AREDN mesh network can query `http://<host>:8093/admin/status` and get the real-time GPS position.

This is a real security concern for an amateur radio operator's field equipment -- it reveals their physical location to anyone on the mesh.

**Fix:** Either:
(a) Remove lat/lon from `/admin/status` entirely (the Dashboard context string only needs fix type + satellite count + accuracy)
(b) Move `/admin/status` out of the public NGINX block and only serve it through the config panel block (localhost-only)
(c) Add a separate `/admin/status/public` with redacted fields and keep the full version localhost-only

Recommendation: option (a) is simplest and best. The GPS WebSocket is also public but that's intentional for the map -- the admin status is not.

---

**4.2 MAJOR -- Credential masking pattern reveals username structure**
The spec says: "masked username (first char + asterisks + domain)." For a USGS ERS username like "czucker@usgs.gov", the masked display would be "c*****@usgs.gov". This reveals:
- The email domain (confirms it's a government account)
- The first character
- The username length (from asterisk count)

Combined, this significantly narrows the search space.

**Fix:** Mask more aggressively: "c***@***.gov" or simply "c*****" (truncate domain entirely). Or just show "Configured" with no username hint at all -- the Settings tab is already localhost-only so there's no strong UX reason to show a partial username.

---

**4.3 MAJOR -- Tile proxy in config panel could be used for SSRF**
Adding `/tiles/` proxy to the config panel server block means the config panel can make requests to `http://tileserver:8080/`. While the config panel is localhost-only, if an attacker gains access to localhost (e.g., through a browser-based attack on the admin), they could potentially craft requests through the tile proxy to scan the internal Docker network. The `proxy_pass http://tileserver:8080/` directive with a trailing `/` allows path traversal within the tileserver's URL space.

**Fix:** This is low risk given localhost-only binding, but add the same `allow/deny` directives to the tile proxy location block, and ensure the proxy_pass does not allow escaping to other hosts. Consider restricting to specific paths (`/tiles/styles/positron/` only, since that's all the minimap needs).

---

**4.4 MINOR -- No CSRF protection on the new OSM POI pipeline trigger**
The existing pipeline endpoints require `X-Geographica` and `X-Config-Source` headers via the `require_config_source` dependency. The spec says the OSM POI extraction button triggers `/admin/pipeline/start` with `type=osm_poi`, which will go through the same auth check. This is fine.

**Fix:** No action needed -- just confirming the existing auth pattern covers the new pipeline type.

---

**4.5 MINOR -- Docker socket access from search container is broad**
The search service already has Docker socket access (for container listing and pipeline management). The spec extends this to inspect the frontend container's environment (for TLS_MODE). This doesn't expand the attack surface since the socket access is already present, but it's worth noting that any RCE in the search service gives full Docker control.

**Fix:** No spec change needed, but note this in operational documentation. The Docker socket is mounted read-only, which limits write operations but `docker.sock:ro` does NOT actually restrict Docker API calls (you can still start/stop containers).

---

## Round 5 -- Operational Edge Cases

**Persona:** An operator deploying this on fresh hardware or dealing with partial failures.

### Issues Found

**5.1 CRITICAL -- First-run state: nothing is healthy, Docker socket might not have containers**
On first run, before `docker compose up`, there are no containers. The `/admin/status` endpoint calls `client.containers.list(all=True, filters={"name": "geographica-"})` which returns an empty list. The Dashboard will show zero services. The spec doesn't address this state.

But worse: during first run, the search service itself might not be running (it's one of the Docker services). The admin panel's NGINX block proxies to `http://search:8000` -- if search isn't up, the entire panel returns 502.

**Fix:** Add a "first-run" or "bootstrap" state to the spec. When `/admin/status` returns an empty service list, the Dashboard should show a message like "No services detected. Run `docker compose up -d` to start the stack." Also consider: the NGINX config panel block could serve a static fallback page when the search backend is unavailable.

---

**5.2 CRITICAL -- Nominatim importing state (6-12 hours) is not clearly handled**
During Nominatim's initial import, the container is "running" but the healthcheck fails (it returns unhealthy until import completes). The spec's Dashboard table shows `"importing -- rank N/30"` but:
- The rank parsing logic (`_parse_progress_from_logs`) only works for the indexing phase. The initial PBF import (which is the longest phase) has different log formats.
- During the first ~4 hours (PBF loading), the logs show SQL COPY progress, not rank information. The Dashboard would show "nominatim: unhealthy" with no context string.
- The `start_period: 300s` healthcheck means Docker reports "starting" for 5 minutes, then "unhealthy" for the remaining 6+ hours.

**Fix:** Add log parsing patterns for the PBF import phase (look for "Importing data" or COPY progress). Also, add a `"starting"` context for when the container is running but health status is `"starting"`. The spec's color coding should include: yellow for `"starting"`, red for `"unhealthy"` that is NOT nominatim during import.

---

**5.3 MAJOR -- No GPS hardware: spec says "no hardware" but detection mechanism is undefined**
The spec shows `"no hardware"` as a GPS degraded context. The GPS service currently retries gpsd connection every 5 seconds and sets `_gps_connected = False` on failure. But there's no distinction between "gpsd is running but no GPS receiver" vs "gpsd is not running" vs "GPS hat is not connected."

The proposed `/status` endpoint spec says `"status": "no_gpsd"` for gpsd unreachable, but doesn't cover "gpsd is running, no device attached" (fix mode 0 indefinitely).

**Fix:** Define three states: (1) `"status": "ok", "fix": "3d"/"2d"` -- working, (2) `"status": "ok", "fix": "none"` -- gpsd connected but no fix (could be indoors or no hardware), (3) `"status": "no_gpsd"` -- can't reach gpsd. The Dashboard should map state 2 to "no fix" (yellow) and state 3 to "no hardware" (red). The current spec conflates cases 2 and 3.

---

**5.4 MAJOR -- OSM PBF file path is unknown to the pipeline orchestrator**
The spec says "Extract POIs" runs `build_osm_pois.py` via the pipeline container. But the script requires `--pbf <path>`. The PBF file lives at `/srv/geographica/data/valhalla/western-us.osm.pbf` on the host, which is mounted as `/custom_files/western-us.osm.pbf` inside the Valhalla container but is accessible as `/data/valhalla/western-us.osm.pbf` from the search/pipeline containers (since `./data:/data` is mounted).

The spec doesn't specify:
- How the pipeline knows the PBF filename (it's not always `western-us.osm.pbf`)
- What if multiple PBF files exist in the directory
- What the `--pbf` argument value should be in the Docker run command

**Fix:** Either (a) hardcode the PBF path as `/data/valhalla/*.osm.pbf` and glob for it, or (b) add a PBF discovery step that lists `/data/valhalla/*.pbf` and uses the first/largest one, or (c) add a PBF path field to the OSM POI extraction UI.

---

**5.5 MAJOR -- Pipeline container image might not be built**
The pipeline service uses `profiles: ["pipeline"]` so it's not started by default with `docker compose up`. But the image must exist for `client.containers.run("geographica-pipeline", ...)` to work. If the user hasn't run `docker compose build pipeline`, the pipeline start will fail with a confusing Docker image-not-found error.

**Fix:** The spec should document that the implementation must check for the pipeline image before attempting to run it, and return a clear error like "Pipeline image not built. Run `docker compose build pipeline` first." The current code may already handle this via the generic exception catch, but the error message would be opaque.

---

**5.6 MAJOR -- TLS cert directory not mounted in search service**
The spec says to add `${TLS_CERT_DIR:-./tls}:/tls:ro` to the search service in `docker-compose.yml`. If `TLS_CERT_DIR` is not set and the `./tls` directory doesn't exist on the host, Docker will create it as an empty directory owned by root. This won't break anything, but:
- The TLS status will always show `"mode": "http"` because no cert exists at `/tls/server.crt`
- If TLS is configured later, the search container must be restarted to pick up the new volume content (Docker bind mounts are live, but the cert reading logic runs on each status request so this is actually fine)

**Fix:** Minor -- just note in the spec that the `/tls` mount is expected to be empty when TLS is not configured, and the status endpoint handles this gracefully.

---

**5.7 MINOR -- Elevation section "Start" button shares pipeline orchestrator but doesn't check for running imagery job**
The spec says elevation uses the "same pipeline orchestrator." The current code has `_pipeline_lock` and checks `_is_pipeline_container_running()`. Since both imagery and elevation use the same `geographica-pipeline` container name, only one can run at a time. But the Elevation UI section has its own Start button -- if an imagery download is running, clicking "Start" for elevation should show a clear "Another pipeline is already running" message, not a generic error.

**Fix:** The Pipeline tab should check pipeline status before enabling any Start button. If any pipeline is running, disable all other Start buttons and show which pipeline is active.

---

**5.8 MINOR -- No "last completed" timestamp for pipelines**
The spec shows pipeline state but not when it last completed. After a 12-hour imagery download finishes, the Dashboard banner disappears. There's no way to see when the download finished or how long it took without checking logs.

**Fix:** Add `"completed_at"` and `"duration_seconds"` to the pipeline state file. Show "Completed 2h ago" in the Pipelines tab.

---

## Consolidated Issue List

### Critical (must fix before implementation)

| # | Issue | Round | Fix |
|---|-------|-------|-----|
| C1 | GPS service has no satellite count data; spec assumes it exists | 1.1, 2.1 | Modify `_blocking_read_gpsd()` to parse SKY messages for satellite count |
| C2 | `PipelineStartBody` and validation reject `type=osm_poi`; spec doesn't define the contract | 1.2 | Define OSM POI pipeline Pydantic model, validation, and Docker command |
| C3 | `/admin/status` is publicly accessible and will expose GPS lat/lon to the mesh network | 4.1, 2.5 | Remove lat/lon from status response OR restrict endpoint to localhost |
| C4 | First-run with no containers yields empty/broken Dashboard with no guidance | 5.1 | Add first-run detection and helpful messaging |

### Major (will cause bugs or confusion if not addressed)

| # | Issue | Round | Fix |
|---|-------|-------|-----|
| M1 | `_parse_zoom` rejects zoom 19; spec allows it | 1.3 | Update validation to allow zoom_max 19 |
| M2 | TLS cert parsing library unspecified; stdlib can't do it | 1.4 | Use `openssl` subprocess or add `cryptography` dep |
| M3 | Tile proxy for minimap needs full sub_filter rewriting, not just one location block | 1.5 | Duplicate all 4+ tile proxy locations or specify a simpler approach |
| M4 | Null vs missing field ambiguity in status response | 2.2 | Add degraded-state JSON example to spec |
| M5 | TLS_MODE detection via Docker env inspection is fragile (runtime override not reflected) | 2.3 | Detect TLS mode from cert file existence instead |
| M6 | Status endpoint could exceed 10s poll interval under load | 2.4 | Require concurrent HTTP calls via asyncio.gather |
| M7 | Minimap rectangle draw needs a library or ~200 lines of custom code; unspecified | 3.1 | Specify exact approach and library/CDN source |
| M8 | Realistic JS estimate is 550-650 lines (3x current), not acknowledged | 3.2 | Split into multiple files or adjust timeline |
| M9 | MapLibre GL JS loading strategy for offline config panel not specified | 3.3 | Define script/link tags and local file serving |
| M10 | Credential masking reveals email domain and username length | 4.2 | Mask more aggressively or just show "Configured" |
| M11 | Nominatim import progress during PBF loading phase not parseable | 5.2 | Add log patterns for import phase |
| M12 | GPS "no hardware" vs "no fix" distinction undefined | 5.3 | Define three GPS states with clear mapping |
| M13 | OSM PBF file path unknown to pipeline orchestrator | 5.4 | Define PBF discovery mechanism |
| M14 | Pipeline container image might not be built; error is opaque | 5.5 | Check for image existence and return clear error |

### Minor (polish, could ship without)

| # | Issue | Round | Fix |
|---|-------|-------|-----|
| m1 | Line count cited as 287 but actual is 307 | 1.6 | Update spec |
| m2 | Search context string needs separate GNIS + OSM count queries | 1.7 | Add COUNT queries to admin_status |
| m3 | Default concurrency per source not specified | 1.8 | Specify defaults |
| m4 | No version field in status response | 2.6 | Add version/commit hash |
| m5 | `disk_used_pct` calculation not specified | 2.7 | Add formula |
| m6 | Touch support for minimap draw unaddressed | 3.4 | Define mobile fallback |
| m7 | Pipeline banner click-to-switch-tab DOM placement unspecified | 3.5 | Clarify DOM structure |
| m8 | Docker socket :ro doesn't restrict API calls | 4.5 | Document in ops notes |
| m9 | TLS cert mount may create empty directory | 5.6 | Note expected behavior |
| m10 | No concurrent pipeline prevention in UI | 5.7 | Disable buttons when pipeline running |
| m11 | No "last completed" timestamp for finished pipelines | 5.8 | Add completed_at to state file |

---

**Total: 4 critical, 14 major, 11 minor (29 unique issues)**

The spec is well-structured and covers the happy path thoroughly. The primary gaps are: (1) backend data that doesn't exist yet being assumed to exist (GPS satellites, OSM POI pipeline contract), (2) security exposure of GPS coordinates through the public status endpoint, and (3) frontend complexity underestimation for the minimap draw interaction and overall JS scope.
