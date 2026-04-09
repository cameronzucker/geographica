# Admin Panel Redesign — Design Spec

**Date:** 2026-04-09
**Status:** Draft
**Scope:** Redesign `frontend/config/index.html` and extend `services/search/main.py` admin endpoints to reflect the full feature set of the deployed Geographica stack.

---

## Problem

The admin config panel was built early in development and covers only imagery download controls and M2M credentials. The system now has 7+ services, voice search (STT), OSM POI extraction, GPS hardware, TLS/Tailscale, and batched M2M downloads — none of which are visible or controllable from the admin panel.

## Design Decisions

- **Three-tab layout**: Dashboard, Pipelines, Settings — matching the existing sidebar tab UX in the main app
- **600px max-width centered container**: Preserved from the current panel. Renders naturally on desktop and mobile.
- **Service health with one-line context**: Each service shows a color-coded status dot plus a short context line (e.g., "cpu, base.en" for STT, "3D fix, 12 sats" for GPS)
- **Embedded minimap for bbox selection**: MapLibre map (~200px tall) with click-drag rectangle drawing, two-way sync with the text field. Replaces the bare text input.
- **Backend aggregation for status**: The search service's `/admin/status` endpoint aggregates data from all services (Docker socket, STT health, GPS status, TLS info) with per-service 2-second timeouts. Dead services return `"unreachable"` without blocking the response.
- **Vanilla JS, no build step**: Consistent with all other frontend code.

---

## Tab 1: Dashboard

At-a-glance system health. Auto-refreshes every 10 seconds via existing polling.

### Service Health List

Single-column list of all Docker services. Each row:
- Left: colored status dot (green=healthy, yellow=starting/importing, red=unhealthy/exited) + service name
- Right: one-line context string + uptime

Context strings per service:
| Service | Healthy context | Degraded context |
|---------|----------------|------------------|
| tileserver | "N sources, z0-M" | "unhealthy" / "exited" |
| valhalla | "graph ready, X GB" | "building graph — N%" |
| nominatim | "ready" | "importing — rank N/30" |
| search | "Nk GNIS + Mk OSM POIs" | "waiting for nominatim" |
| stt | "cpu, base.en" | "unreachable" |
| gps | "3D fix, N sats, ±Xm" | "no fix" / "no hardware" / "unreachable" |
| frontend | "nginx" | "unhealthy" |

The context data comes from the enriched `/admin/status` response (see Backend section).

### System Summary

Two info cards below the service list:
- **Disk**: free space in GB with percentage (from `shutil.disk_usage`)
- **TLS**: current mode (HTTP / HTTPS / Tailscale) + cert expiry date if applicable

### Active Pipeline Banner

When a pipeline job is running (imagery or elevation), a compact progress banner appears at the bottom of the Dashboard tab:
- Job name + mode (e.g., "Imagery — Maricopa M2M")
- Thin progress bar
- "batch N/M • X/Y files • ~Zh remaining"

This is a summary view only — the full controls are on the Pipelines tab. Clicking the banner switches to the Pipelines tab.

---

## Tab 2: Pipelines

Controls and status for all data pipeline operations.

### Imagery Acquisition

Form controls (existing, refined):
- **Source**: select — "USGS Direct (no auth)" / "USGS M2M API (requires credentials)"
- **Coverage area**: MapLibre minimap (200px tall) with rectangle draw tool + synced bbox text field below the map. The map loads the Positron vector basemap from the tileserver via the config panel's NGINX proxy.
- **Zoom range**: select — options 0-8 through 0-16 for direct, 0-17 through 0-19 for M2M. When M2M zoom is selected with direct source, show a warning note.
- **Concurrency**: select — "3 (M2M safe)" / "5 (M2M max)" when M2M is selected; "10 / 20 / 50 / 80" when direct is selected. The options change based on the source selector.
- **Resume checkbox**: "Resume/extend existing data"
- **Estimate line**: "~N files • est. ~X GB" (for M2M this estimates based on scene count, not tile count)
- **Start/Cancel buttons**

When M2M source is selected and credentials are not configured, show an inline warning: "M2M requires credentials — configure in Settings tab" with a link/button that switches to the Settings tab.

#### Active Download Progress

When a pipeline is running, show below the form:
- Job description + cancel button
- Progress bar
- Single detail line: "Batch N/M • X/Y files • ~X MB/s • ~Nh remaining"
- For direct mode: "X/Y tiles • Z tiles/sec • ~Nh remaining"

### Elevation Tiles

Compact read-only section:
- If complete: "✓ Complete — N tiles (z0-M) • X GB"
- If not present: "Not downloaded" with a Start button (same pipeline orchestrator, `type=elevation`)
- If running: progress bar + detail line

### OSM POI Extraction

- If extracted: "✓ N amenities + M public land boundaries"
- If not extracted: "⚠ Not extracted" + "Extract POIs" button + description ("Extracts amenities + public land from OSM PBF. ~10 min.")
- If running: progress spinner + elapsed time

The "Extract POIs" button triggers the pipeline orchestrator with a new `type=osm_poi` pipeline type.

---

## Tab 3: Settings

Configuration and read-only system information.

### M2M API Credentials

- If configured: show masked username (first char + asterisks + domain) and masked token (bullets + length). "Update" and "Delete" buttons.
- If not configured: show username and token input fields + "Save" button.
- The "Update" button reveals the input fields pre-filled (token blank for security) for editing.

### TLS Configuration

Read-only key-value rows:
- **Mode**: HTTP / HTTPS (self-signed) / Tailscale (Let's Encrypt)
- **Hostname**: the Tailscale hostname (if applicable)
- **Certificate**: validity status + expiry date
- **Renewal**: systemd timer status

This data comes from the enriched `/admin/status` endpoint.

### Voice Search (STT)

Read-only key-value rows:
- **Backend**: CPU (faster-whisper) / NPU (HailoRT)
- **Model**: base.en (INT8)
- **NPU**: availability status
- **Status**: healthy / unreachable

This data comes from the STT service's `/health` endpoint, aggregated via `/admin/status`.

---

## Backend Changes

### Enriched `/admin/status` Response

The existing endpoint at `services/search/main.py` line 539 is extended to aggregate data from other services. Each sub-query has a 2-second timeout and returns `"unreachable"` on failure, so the overall response always completes quickly.

New fields added to the response:

```json
{
  "services": [...],  // existing — Docker container list with health
  "data_tasks": [...],  // existing — MBTiles file stats
  "stt": {
    "status": "ok",
    "backend": "cpu",
    "model": "base.en",
    "npu_available": false
  },
  "gps": {
    "status": "ok",
    "fix": "3d",
    "satellites": 12,
    "accuracy_m": 2.1,
    "lat": 33.4512,
    "lon": -112.074
  },
  "tls": {
    "mode": "tailscale",
    "hostname": "pandora.twin-bramble.ts.net",
    "cert_expires": "2026-07-07",
    "cert_valid": true
  },
  "disk_free_gb": 587.2,
  "disk_total_gb": 896.0,
  "disk_used_pct": 34
}
```

**STT data**: HTTP GET to `http://stt:8000/health` with 2s timeout. On failure: `{"status": "unreachable"}`.

**GPS data**: HTTP GET to `http://gps:8000/status` — this is a **new endpoint** to add to the GPS service. The GPS service currently only has a WebSocket endpoint. Adding `GET /status` that returns the latest fix data as JSON is simpler than connecting a WebSocket from the search service. On failure: `{"status": "unreachable"}`.

**TLS data**: Two-step approach. (1) Inspect the `geographica-frontend` container's environment via Docker socket to read `TLS_MODE`. (2) Read the certificate expiry from the mounted TLS directory — the search service container needs a read-only volume mount to the TLS cert directory (add `${TLS_CERT_DIR:-./tls}:/tls:ro` to the search service in `docker-compose.yml`). Use Python's `ssl.PEM_cert_to_DER_cert` + `x509` to parse the cert expiry date. If the cert file doesn't exist (HTTP mode), return `{"mode": "http", "cert_expires": null}`.

### New GPS REST Endpoint

Add `GET /status` to `services/gps/main.py` that returns the latest GPS fix as JSON:

```json
{
  "status": "ok",
  "fix": "3d",
  "satellites": 12,
  "accuracy_m": 2.1,
  "lat": 33.4512,
  "lon": -112.074,
  "speed_mps": 0.0,
  "timestamp": "2026-04-09T02:30:00Z"
}
```

When no fix is available: `{"status": "ok", "fix": "none", "satellites": 0}`.
When gpsd is unreachable: `{"status": "no_gpsd"}`.

This endpoint reads from the same state that the WebSocket broadcasts — no new gpsd connections needed.

### OSM POI Pipeline Type

Add `type=osm_poi` support to the pipeline orchestrator (`/admin/pipeline/start`). This runs `build_osm_pois.py` in the pipeline container, similar to how imagery and elevation pipelines are launched. The state file is `/data/.osm-poi-state.json`.

### Config Panel NGINX Proxy for Tiles

Add a `/tiles/` location to the config panel server block in `nginx/nginx.conf` (the port 8094 block) so the minimap can load vector tiles from the tileserver. This mirrors the main server block's `/tiles/` proxy.

---

## Files Modified

| File | Change |
|------|--------|
| `frontend/config/index.html` | Full rewrite: 3-tab layout, service health, minimap, pipeline controls |
| `services/search/main.py` | Enrich `/admin/status` with STT/GPS/TLS aggregation, add `osm_poi` pipeline type |
| `services/gps/main.py` | Add `GET /status` REST endpoint |
| `nginx/nginx.conf` | Add `/tiles/` proxy to config panel server block |
| `docker-compose.yml` | Add TLS cert read-only volume mount to search service |

## Files NOT Modified

- `frontend/app.js` — main app is unchanged
- `services/stt/main.py` — STT service already has `/health`, no changes needed

---

## Testing Strategy

- **Backend**: Unit tests for the enriched `/admin/status` response with mocked service calls (STT unreachable, GPS no fix, etc.)
- **GPS endpoint**: Unit test for `GET /status` with mocked gpsd data
- **Frontend**: Manual testing on desktop (via SSH tunnel) and mobile (direct localhost). Verify tab switching, minimap draw interaction, form submission, progress polling.
- **Integration**: Verify the config panel NGINX proxy serves tiles correctly for the minimap.

---

## Out of Scope

- Service restart controls (too dangerous for a web panel)
- Log viewer (use `docker compose logs`)
- Configuration editing (`.env` changes require container restart)
- Light/dark mode toggle (panel is always dark theme)
