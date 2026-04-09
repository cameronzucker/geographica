# Admin Panel Redesign — Design Spec

**Date:** 2026-04-09
**Status:** Reviewed (5-round adversarial review applied)
**Scope:** Redesign `frontend/config/index.html` and extend `services/search/main.py` admin endpoints to reflect the full feature set of the deployed Geographica stack.

---

## Problem

The admin config panel was built early in development and covers only imagery download controls and M2M credentials. The system now has 7+ services, voice search (STT), OSM POI extraction, GPS hardware, TLS/Tailscale, and batched M2M downloads — none of which are visible or controllable from the admin panel.

## Design Decisions

- **Three-tab layout**: Dashboard, Pipelines, Settings — matching the existing sidebar tab UX in the main app
- **600px max-width centered container**: Preserved from the current panel. Renders naturally on desktop and mobile.
- **Service health with one-line context**: Each service shows a color-coded status dot plus a short context line (e.g., "cpu, base.en" for STT, "3D fix, ±Xm" for GPS)
- **Embedded minimap for bbox selection**: MapLibre map (~200px tall) with custom click-drag rectangle drawing (~150 lines), two-way sync with the text field. MapLibre JS/CSS loaded from the same vendor path as the main frontend, served via the config panel's NGINX proxy.
- **Backend aggregation for status**: The search service's `/admin/status` endpoint aggregates data from all services with per-service 2-second timeouts via `asyncio.gather`. Dead services return `"unreachable"` without blocking the response. GPS coordinates are NOT included in the status response (security: this endpoint is publicly accessible on the mesh).
- **Vanilla JS, no build step**: Consistent with all other frontend code. Expected total: ~600 lines JS + ~250 lines HTML/CSS, split across a main HTML file and optional JS module files.

---

## Tab 1: Dashboard

At-a-glance system health. Auto-refreshes every 10 seconds via existing polling.

### Service Health List

Single-column list of all Docker services. Each row:
- Left: colored status dot (green=healthy, yellow=starting/importing, red=unhealthy/exited/unreachable) + service name
- Right: one-line context string + uptime

Color mapping:
- **Green**: container healthy
- **Yellow**: container running but health is "starting" OR service-specific degraded state (e.g., nominatim importing, GPS no fix)
- **Red**: container unhealthy, exited, or service unreachable

Context strings per service:
| Service | Healthy context | Degraded context |
|---------|----------------|------------------|
| tileserver | "N sources, z0-M" | "unhealthy" / "exited" |
| valhalla | "graph ready, X GB" | "building graph" |
| nominatim | "ready" | "importing — rank N/30" or "importing — loading PBF" |
| search | "Nk GNIS + Mk OSM POIs" | "waiting for nominatim" |
| stt | "cpu, base.en" | "unreachable" |
| gps | "3D fix, ±Xm" or "no fix" | "no gpsd" / "unreachable" |
| frontend | "nginx" | "unhealthy" |

The search service context requires two SQL COUNT queries: one on `poi_features` and one on `osm_pois` (if loaded).

The nominatim context needs log parsing patterns for both the PBF import phase (look for "Importing data" or COPY progress) and the indexing phase (rank N/30). During PBF loading, show "importing — loading PBF".

### First-Run State

When `/admin/status` returns an empty service list (no containers exist), the Dashboard shows a centered message: "No services detected. Run `docker compose up -d` to start the stack." This is the only content visible — no service grid, no system cards.

### System Summary

Two info cards below the service list:
- **Disk**: free space in GB with percentage. Formula: `disk_used_pct = 100 - (free / total * 100)`, rounded to integer.
- **TLS**: current mode (HTTP / HTTPS / Tailscale) + cert expiry date if applicable

### Active Pipeline Banner

When any pipeline job is running (imagery, elevation, or OSM POI), a compact progress banner appears at the bottom of the Dashboard tab. The banner is a child element of the Dashboard tab container. Clicking it calls `switchTab('pipelines')`.

- Job name + mode (e.g., "Imagery — Maricopa M2M")
- Thin progress bar
- "batch N/M • X/Y files • ~Zh remaining"

---

## Tab 2: Pipelines

Controls and status for all data pipeline operations. Only one pipeline can run at a time (shared `geographica-pipeline` container). When any pipeline is running, all other Start buttons are disabled with a note: "Another pipeline is running."

### Imagery Acquisition

Form controls (existing, refined):
- **Source**: select — "USGS Direct (no auth)" / "USGS M2M API (requires credentials)"
- **Coverage area**: MapLibre minimap (200px tall) with custom click-drag rectangle drawing + synced bbox text field below the map. The minimap is desktop-optimized; on mobile (viewport < 480px), the minimap is hidden and only the text field is shown. The map loads the Positron vector basemap from the tileserver via the config panel's NGINX tile proxy.
- **Zoom range**: select — options 0-8 through 0-16 for direct, 0-17 through 0-19 for M2M. When M2M zoom is selected with direct source, show a warning note. Backend `_parse_zoom()` must be updated to allow zoom_max up to 19.
- **Concurrency**: select — "3 (M2M safe, default)" / "5 (M2M max)" when M2M is selected; "10 / 20 (default) / 50 / 80" when direct is selected. Options swap when source changes.
- **Resume checkbox**: "Resume/extend existing data"
- **Estimate line**: "~N files • est. ~X GB" (for M2M this estimates based on scene count, not tile count)
- **Start/Cancel buttons**

When M2M source is selected and credentials are not configured, show an inline warning: "M2M requires credentials — configure in Settings tab" with a button that calls `switchTab('settings')`.

#### Active Download Progress

When a pipeline is running, show below the form:
- Job description + cancel button
- Progress bar
- Single detail line: "Batch N/M • X/Y files • ~X MB/s • ~Nh remaining"
- For direct mode: "X/Y tiles • Z tiles/sec • ~Nh remaining"

When a pipeline recently completed, show: "✓ Completed Xh ago (N files, Y GB)" using `completed_at` from the state file.

#### Minimap Implementation Details

MapLibre GL JS and CSS are already vendored at `frontend/vendor/maplibre-gl.js` and `frontend/vendor/maplibre-gl.css`. The config panel NGINX block needs to serve these files and proxy tile requests.

Rectangle draw is custom (no mapbox-gl-draw dependency). Implementation:
- `mousedown` on map starts draw, captures start latlng
- `mousemove` updates a GeoJSON rectangle source/layer
- `mouseup` finalizes, updates the bbox text field
- Existing rectangle can be removed by clicking outside it
- Two-way sync: editing the text field repositions the rectangle and re-centers the map
- No corner resize handles (YAGNI — draw a new rectangle to change)

### Elevation Tiles

Compact read-only section:
- If complete: "✓ Complete — N tiles (z0-M) • X GB"
- If not present: "Not downloaded" with a Start button (same pipeline orchestrator, `type=elevation`)
- If running: progress bar + detail line

### OSM POI Extraction

- If extracted: "✓ N amenities + M public land boundaries"
- If not extracted: "⚠ Not extracted" + "Extract POIs" button + description ("Extracts amenities + public land from OSM PBF. ~10 min.")
- If running: progress spinner + elapsed time
- If PBF file not found: "⚠ No OSM PBF file found. Download OSM data first." (button disabled)

The "Extract POIs" button triggers the pipeline orchestrator with `type=osm_poi`.

---

## Tab 3: Settings

Configuration and read-only system information.

### M2M API Credentials

- If configured: show "✓ Configured" status text. "Update" and "Delete" buttons. No username or token displayed (even masked — avoids information leakage per security review).
- If not configured: show username and token input fields + "Save" button.
- The "Update" button reveals the input fields (both blank) for re-entry.

### TLS Configuration

Read-only key-value rows:
- **Mode**: HTTP / HTTPS (self-signed) / Tailscale (Let's Encrypt)
- **Hostname**: the Tailscale hostname (if applicable)
- **Certificate**: validity status + expiry date
- **Renewal**: systemd timer status

### Voice Search (STT)

Read-only key-value rows:
- **Backend**: CPU (faster-whisper) / NPU (HailoRT)
- **Model**: base.en (INT8)
- **NPU**: availability status
- **Status**: healthy / unreachable

---

## Backend Changes

### Enriched `/admin/status` Response

The existing endpoint is extended to aggregate data from all services. Sub-queries run concurrently via `asyncio.gather` with per-service 2-second timeouts. The total endpoint response time is bounded at ~8 seconds worst case (Docker list in thread pool + concurrent HTTP calls).

All top-level keys are always present. Sub-object keys are always present with `null` for missing/unavailable data.

#### Happy path response:

```json
{
  "services": [...],
  "data_tasks": [...],
  "stt": {
    "status": "ok",
    "backend": "cpu",
    "model": "base.en",
    "npu_available": false
  },
  "gps": {
    "status": "ok",
    "fix": "3d",
    "accuracy_m": 2.1
  },
  "tls": {
    "mode": "tailscale",
    "hostname": "pandora.twin-bramble.ts.net",
    "cert_expires": "2026-07-07",
    "cert_valid": true
  },
  "search_stats": {
    "gnis_count": 304094,
    "osm_pois_count": 12340,
    "osm_pois_loaded": true
  },
  "disk_free_gb": 587.2,
  "disk_total_gb": 896.0,
  "disk_used_pct": 34
}
```

#### Degraded response (STT down, GPS unreachable, HTTP mode):

```json
{
  "services": [...],
  "data_tasks": [...],
  "stt": {
    "status": "unreachable",
    "backend": null,
    "model": null,
    "npu_available": null
  },
  "gps": {
    "status": "unreachable",
    "fix": null,
    "accuracy_m": null
  },
  "tls": {
    "mode": "http",
    "hostname": null,
    "cert_expires": null,
    "cert_valid": null
  },
  "search_stats": {
    "gnis_count": 304094,
    "osm_pois_count": 0,
    "osm_pois_loaded": false
  },
  "disk_free_gb": 587.2,
  "disk_total_gb": 896.0,
  "disk_used_pct": 34
}
```

**Security: GPS coordinates (`lat`, `lon`) are NOT included in the status response.** The `/admin/status` endpoint is publicly accessible via the main NGINX server block (lines 102-106). Including GPS coordinates would expose the device's real-time location to anyone on the AREDN mesh network. The GPS context string on the Dashboard uses only fix type + accuracy — no position data needed.

**STT data**: HTTP GET to `http://stt:8000/health` with 2s timeout.

**GPS data**: HTTP GET to `http://gps:8000/status` (new endpoint, see below) with 2s timeout.

**TLS data**: Detect mode by checking the mounted TLS cert directory (`/tls/server.crt`). If cert file exists, determine if it's a Tailscale cert by checking the issuer (contains "Let's Encrypt") or SAN (contains `.ts.net`). Parse cert expiry using `subprocess.run(["openssl", "x509", "-enddate", "-noout", "-in", "/tls/server.crt"])` — avoids adding a Python dependency. If no cert file: `{"mode": "http"}`. This is more reliable than inspecting the frontend container's env vars (which don't reflect runtime TLS_MODE overrides in entrypoint.sh).

**Search stats**: Two SQL COUNT queries: `SELECT COUNT(*) FROM poi_features` and `SELECT COUNT(*) FROM osm_pois` (if table exists).

### New GPS REST Endpoint

Add `GET /status` to `services/gps/main.py` that returns the latest GPS fix as JSON. This reads from the existing `_position` dict — no new gpsd connections needed.

Three states:
1. **GPS working**: `{"status": "ok", "fix": "3d"/"2d", "accuracy_m": 2.1, "speed_mps": 0.0}`
2. **GPS connected, no fix**: `{"status": "ok", "fix": "none", "accuracy_m": null}` (indoors or no hardware)
3. **gpsd unreachable**: `{"status": "no_gpsd", "fix": null, "accuracy_m": null}`

Note: satellite count is NOT included. The GPS service currently does not parse gpsd SKY messages. Adding satellite parsing would require changes to `_blocking_read_gpsd()` which is out of scope for this redesign. The Dashboard context line uses fix type + accuracy only.

### OSM POI Pipeline Type

Add `type=osm_poi` support to the pipeline orchestrator:

1. Update `PipelineStartBody` to make `mode`, `bbox`, and `zoom` optional (they're irrelevant for OSM extraction)
2. Update the validation in `/admin/pipeline/start` to accept `"osm_poi"` as a valid type
3. Define the Docker run command: `python3 /scripts/build_osm_pois.py --pbf <pbf_path> --output /data/poi.sqlite --bbox <bbox>`
4. PBF discovery: glob `/data/valhalla/*.osm.pbf` and use the first file found. If no PBF exists, return error "No OSM PBF file found in /data/valhalla/"
5. State file: `/data/.osm-poi-state.json`
6. After completion: restart the search service to reload the POI database (`docker restart geographica-search`)

### Pipeline State Enhancements

Add `completed_at` (ISO 8601 timestamp) and `duration_seconds` (integer) to all pipeline state files when status transitions to `"completed"`. The frontend can show "Completed 2h ago" on the Pipelines tab.

Check for pipeline image existence before attempting to run: `client.images.get("geographica-pipeline")`. If missing, return HTTP 422 with `"Pipeline image not built. Run 'docker compose build pipeline' first."`

### Config Panel NGINX Proxy for Tiles and MapLibre Assets

Add to the config panel server block (port 8094) in `nginx/nginx.conf`:

1. `/tiles/styles/` location with the same `sub_filter` URL rewriting as the main server block (rewrites `http://tileserver:8080/` URLs to the config panel's tile proxy)
2. `/tiles/data/` locations for TileJSON endpoints with `sub_filter`
3. `/tiles/fonts/` catch-all for PBF glyph ranges
4. `/tiles/` catch-all for raw tile data
5. `/vendor/` location aliased to `/usr/share/nginx/html/vendor/` to serve MapLibre JS/CSS

These mirror the main server block's tile proxy pattern. The `sub_filter` rewrites use `$scheme://$http_host` to generate correct absolute URLs.

### Zoom Validation Update

Update `_parse_zoom()` in `services/search/main.py` to allow `zoom_max` up to 19 (currently rejects > 18).

---

## Files Modified

| File | Change |
|------|--------|
| `frontend/config/index.html` | Full rewrite: 3-tab layout, service health, minimap, pipeline controls (~850 lines) |
| `services/search/main.py` | Enrich `/admin/status`, add `osm_poi` pipeline type, zoom validation, search stats |
| `services/gps/main.py` | Add `GET /status` REST endpoint |
| `nginx/nginx.conf` | Add tile proxy + vendor serving to config panel server block |
| `docker-compose.yml` | Add TLS cert read-only volume mount to search service |

## Files NOT Modified

- `frontend/app.js` — main app is unchanged
- `services/stt/main.py` — STT service already has `/health`, no changes needed

---

## Testing Strategy

- **Backend `/admin/status`**: Unit tests with mocked HTTP responses for STT/GPS (healthy, unreachable, no fix). Test concurrent aggregation completes within timeout.
- **GPS `GET /status`**: Unit test with mocked `_position` dict for all 3 states (3D fix, no fix, no gpsd).
- **OSM POI pipeline**: Unit test for command building with mocked PBF discovery. Test missing PBF error.
- **Pipeline image check**: Unit test for missing image error message.
- **Zoom validation**: Unit test that zoom 19 is accepted, zoom 20 rejected.
- **Frontend**: Manual testing on desktop (via SSH tunnel) and mobile. Verify: tab switching, minimap draw interaction, form submission, progress polling, first-run empty state, degraded service display.
- **NGINX**: Verify config panel tile proxy serves style JSON with correct rewritten URLs.

---

## Out of Scope

- Service restart controls (too dangerous for a web panel)
- Log viewer (use `docker compose logs`)
- Configuration editing (`.env` changes require container restart)
- Light/dark mode toggle (panel is always dark theme)
- GPS satellite count (requires gpsd SKY message parsing — separate feature)
- Version/commit hash in status response (nice-to-have, not needed for MVP)
