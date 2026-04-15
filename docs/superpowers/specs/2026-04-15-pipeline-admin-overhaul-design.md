# Pipeline Admin Page Overhaul Design

**Date:** 2026-04-15
**Scope:** Replace the Pipelines tab dropdown+cards layout with a card-per-source grid, inline expand config panels, and catalog-driven data.

## Problem

The Pipelines tab at localhost:8097 has 4 imagery sources crammed into one dropdown (USGS Direct, USGS M2M, National Map, NOAA), plus Sentinel-2 and NAIP as separate collapsible cards below, plus a BYO import section. Users can't:
- See all sources at a glance
- Compare resolution, auth requirements, or disk usage across sources
- Understand which source to use for their needs
- See what they've already downloaded per-source

## Design Decisions

- **Card grid layout** (2-column) showing all 7 sources simultaneously
- **Inline expand** when configuring a source: selected card pops out full-width, others dim
- **Catalog-driven data**: static registry (name, description, auth, resolution) merged with live data from `GET /admin/imagery/catalog` (disk size, zoom levels, tile count, registered status)
- **Shared bbox/minimap** at the top, used by all sources

## Source Registry

7 source cards in a 2-column grid:

| Card | ID | Auth | Resolution | Zoom | Status |
|------|----|------|-----------|------|--------|
| USGS Basemap | `imagery` | Free | 0.5m | z0-14 | Working |
| NOAA NAIP | `imagery_noaa` | Free | 0.6m | z15-18 | Working |
| USGS M2M | `imagery_m2m` | API Key | 1m | z15-19 | Working |
| Sentinel-2 | `imagery_sentinel` | API Key | 10m | z10-14 | Untested |
| National Map | `imagery_naip` | Free | 0.6m | z15-18 | Throttled |
| NAIP County | `imagery_naip_county` | Free | 0.6-1m | varies | Gateway dead |
| Custom Import | `imagery_custom` | N/A | varies | varies | Working |

Each card shows:
- **Static:** Source name, auth badge (Free/API Key), resolution, one-line description
- **From catalog:** File size on disk, zoom levels present, tile count, TileServer registration status
- **Computed:** "Not downloaded" when catalog has no entry for this source

## Card Layout

### Collapsed State (grid)

```
┌─────────────────────┐ ┌─────────────────────┐
│ USGS Basemap  [Free]│ │ NOAA NAIP     [Free]│
│ z0-14 · 0.5m        │ │ z15-18 · 0.6m       │
│ 25 GB on disk        │ │ 1.7 GB · 53 tiles   │
│ [Configure]          │ │ [Configure]          │
└─────────────────────┘ └─────────────────────┘
┌─────────────────────┐ ┌─────────────────────┐
│ USGS M2M  [API Key] │ │ Sentinel-2  [API Key]│
│ z15-19 · 1m          │ │ z10-14 · 10m         │
│ 304 MB · partial     │ │ Not downloaded       │
│ [Configure]          │ │ [Configure]          │
└─────────────────────┘ └─────────────────────┘
┌─────────────────────┐ ┌─────────────────────┐
│ National Map  [Free]│ │ NAIP County   [Free]│
│ z15-18 · throttled   │ │ ⚠ Gateway unavail.  │
│ Not downloaded       │ │ Since April 2026     │
│ [Configure]          │ │ [Configure]          │
└─────────────────────┘ └─────────────────────┘
┌─────────────────────┐
│ Import Custom  ┄┄┄┄ │  (dashed border)
│ Your GeoTIFFs        │
│ [Import]             │
└─────────────────────┘
```

### Expanded State (inline)

When "Configure" is clicked:
1. Selected card expands to full width, positioned in the flow where it was
2. Other cards dim (opacity 0.5) but remain visible
3. Expanded card shows source-specific controls (see below)
4. Blue border indicates active/expanded state
5. "✕ Close" button in top-right collapses back to grid

Only one source can be expanded at a time. Clicking "Configure" on another card closes the current one.

## Source-Specific Config Panels

### USGS Basemap (direct tile scraper)
- Zoom range dropdown (0-8 through 0-14)
- Resume checkbox
- Estimate display (tiles, GB, time)
- Start Download button

### NOAA NAIP
- State/Year dropdown (from NOAA_NAIP_CATALOG)
- Estimate button → shows: remaining tiles, raw download GB, final GB, time, disk space
- On Disk display from catalog
- Start Download button

### USGS M2M
- Credential warning with link to Settings tab (if not configured)
- Zoom range dropdown (z15-z19)
- Concurrency selector (3-5)
- Resume checkbox
- Start Download button (disabled if no credentials)

### Sentinel-2
- Credential warning with link to Settings tab (if not configured)
- Date range inputs (start/end, default last 6 months)
- Cloud cover slider (0-100%, default 20%)
- Estimate button → shows scene count and GB
- Start Download button (disabled if no credentials)

### National Map
- Zoom range dropdown
- Note about throttling: "Rate-limited to ~1 tile/sec. Best for small areas (<1000 tiles)."
- Estimate display
- Start Download button

### NAIP County
- Gateway unavailable warning (orange, dated)
- County lookup button
- County list with removable items (grouped by state)
- Summary: count, GB estimate
- Start Download button (disabled while gateway is down)

### Custom Import
- Dashed border to distinguish from download sources
- Scan result: file count, total MB, unsupported files warning
- Layer name input (optional, monospace)
- Delete-after checkbox
- Import button + Refresh Scan button

## Shared Components

### Coverage Area (top of Pipelines tab)
- Minimap with bbox drawing (existing `#minimap` canvas)
- Bbox text input (monospace, read-only from map draw)
- Shared by all sources — when a source expands, the bbox applies to it

### Progress Display
- When a pipeline is running, the active source card shows:
  - Progress bar with percentage
  - Phase text (downloading, processing, overviews, etc.)
  - Cancel button (replaces Start)
  - Tiles completed / total
- Other cards remain interactive (can configure but not start a second pipeline)
- Only one pipeline can run at a time (existing constraint)

### Pipeline Status Banner
- Dashboard tab already has a pipeline progress banner
- The Pipelines tab shows progress inline within the active card

## Source ID Mapping

The backend uses three different ID schemes. The frontend must map between them:

| Card ID (registry) | pipeline/start type | pipeline/start mode | pipeline/status type | Status mode field |
|---------------------|--------------------|--------------------|---------------------|-------------------|
| `imagery` | `imagery` | `direct` | `imagery` | `direct` |
| `imagery_noaa` | `imagery` | `noaa` | `imagery` | `noaa` |
| `imagery_m2m` | `imagery` | `m2m` | `imagery` | `m2m` |
| `imagery_naip` | `imagery` | `nationalmap` | `imagery` | `nationalmap` |
| `imagery_naip_county` | `naip` | — | `naip` | — |
| `imagery_sentinel` | `sentinel` | (from controls) | `sentinel` | — |
| `imagery_custom` | (uses `/admin/pipeline/import`) | — | `import` | — |

**Shared status channel:** USGS Direct, NOAA, M2M, and National Map all poll `type=imagery`. The status response includes a `mode` field that distinguishes which is running. The frontend must inspect `status.mode` to route progress to the correct card.

## Pipeline Start Parameters

Each source sends different parameters to `POST /admin/pipeline/start` (or `/admin/pipeline/import` for custom):

| Source | Parameters |
|--------|-----------|
| USGS Direct | `{type:"imagery", mode:"direct", bbox, zoom, concurrency, update}` |
| NOAA | `{type:"imagery", mode:"noaa", bbox, state:"AZ", year:2021}` |
| USGS M2M | `{type:"imagery", mode:"m2m", bbox, concurrency, update}` |
| National Map | `{type:"imagery", mode:"nationalmap", bbox, zoom, concurrency}` |
| Sentinel-2 | `{type:"sentinel", bbox, date_start, date_end, cloud_cover_max, mode}` |
| NAIP County | `{type:"naip", bbox, counties:"FIPS1,FIPS2,..."}` |
| Custom Import | `GET /admin/pipeline/import?delete_after=bool&layer_name=str` |

## Estimate Mechanisms

Each source has a different estimate approach:

| Source | Mechanism |
|--------|-----------|
| USGS Direct, National Map | Inline JS `estimateTiles()` — tile count from zoom/bbox math, no network call |
| NOAA | `GET /admin/pipeline/noaa/estimate?bbox=...&state=...` — server-side tile index query |
| Sentinel-2 | `GET /admin/pipeline/sentinel/estimate?bbox=...&cloud_cover_max=...&date_start=...&date_end=...` |
| M2M | No estimate endpoint — show tile count from zoom/bbox math |
| NAIP County | County lookup: `GET /admin/pipeline/naip/counties?bbox=...` → area-based GB estimate |
| Custom Import | `GET /admin/pipeline/import/scan` → file count and MB from scan |

## DOM ID Generation

The current code uses hardcoded element IDs (`cfg-start`, `cfg-cancel`, `cfg-progress`, etc.). The new card grid generates IDs from the source registry ID:

```
card-{source_id}-start    → e.g., card-imagery_noaa-start
card-{source_id}-cancel   → e.g., card-imagery_noaa-cancel
card-{source_id}-progress → e.g., card-imagery_noaa-progress
card-{source_id}-detail   → e.g., card-imagery_noaa-detail
card-{source_id}-estimate → e.g., card-imagery_noaa-estimate
```

`renderGenericProgress()` is refactored to accept a source ID prefix instead of individual element IDs.

## NAIP County: Disabled State

The USDA Gateway has been unavailable since April 3, 2026 with no ETA. The NAIP County card shows:
- Orange unavailability notice in collapsed state
- "Configure" button is replaced with a disabled state explanation
- No expanded panel — clicking the card shows a brief "USDA Gateway unavailable since April 2026" message
- No county lookup, no county list reimplemented
- Card is present so users know the source exists and can use it when the gateway returns

## Responsive Layout

- **>800px:** 2-column card grid (default)
- **480-800px:** 2-column grid, cards narrower but functional
- **<480px:** 1-column card stack, minimap hidden (existing behavior)

## Data Flow

1. On page load, fetch `GET /admin/imagery/catalog` once
2. Merge catalog response with static source registry (registry has all 7 sources; catalog adds live data for downloaded ones)
3. Render card grid with merged data
4. Poll `GET /admin/pipeline/status?type=imagery` + `type=sentinel` + `type=naip` + `type=import` every 10 seconds
5. For `type=imagery` status, inspect `mode` field to route progress to the correct card (direct/noaa/m2m/nationalmap)
6. When a pipeline completes, re-fetch catalog to update disk/zoom data

## Files Modified

| File | Changes |
|------|---------|
| `frontend/config/index.html` | Replace Pipelines tab HTML + JavaScript (~400 lines of HTML, ~600 lines of JS) |

## What This Does NOT Change

- Backend API endpoints (all existing endpoints stay the same)
- Settings tab (credentials, TLS, STT)
- Dashboard tab
- Elevation and OSM POI pipeline sections (stay as-is, below the imagery grid)
- The catalog endpoint (built in subsystem 1)

## Adversarial Review Findings (5 rounds: Opus, Opus, Sonnet, Sonnet, Haiku)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| F1 | Triple ID scheme (catalog/start/status) with no mapping | High | Added explicit mapping table |
| F2 | Shared status channel — 4 sources share `type=imagery` | High | Inspect `mode` field from status response |
| F3 | Sentinel cloud_cover/date_range may not be wired in backend | Medium | Keep UI controls; verify during implementation |
| F4 | NAIP County: full reimplementation for dead service | Medium | Show disabled card with unavailability notice only |
| F5 | No mobile responsive breakpoint defined | Medium | Added 1-column <480px rule |
| F6 | renderGenericProgress uses hardcoded DOM IDs | High | Added ID generation scheme from source_id |
| F7 | National Map has no estimate endpoint | Medium | Uses inline estimateTiles() JS, noted in estimate table |
| F8 | Import uses different API path | Low | Already in spec's parameter table |
| F9 | CSS `label { display: block }` fights inline layouts | Low | Note for implementation |

## Elevation and OSM POI

These are not imagery sources — they stay as their own sections below the imagery card grid, with their existing simple Start/Cancel/Progress UI. No changes to their layout.
