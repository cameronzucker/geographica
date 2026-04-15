# Imagery Inventory Manager Design

**Date:** 2026-04-15
**Scope:** New Inventory tab in admin panel showing a map of imagery coverage per source, with per-source delete capability.

## Problem

Users have no way to see what imagery they've downloaded, at what zoom levels, covering what areas. With 4+ sources producing separate MBTiles files, they need a visual inventory. There's also no GUI mechanism to delete an imagery source to free disk space.

## Design Decisions

- **New Inventory tab** in admin panel (localhost:8097), alongside Dashboard, Pipelines, Settings
- **Map + sidebar layout** with wider container (~1000px max-width, vs 600px for other tabs)
- **Catalog-driven** — uses `GET /admin/imagery/catalog` (built in subsystem 1)
- **View + delete** — coverage rectangles on map, source details in sidebar, per-source delete with confirmation
- **Responsive** — sidebar collapses below map at narrow widths

## Tab Layout

### Container Width

The Inventory tab uses `max-width: 1000px` instead of the global `max-width: 600px`. This is achieved by adding a CSS rule scoped to the inventory tab content that overrides the container width. Other tabs are unaffected.

### Structure

```
┌──────────────────────────────────────────────────┐
│ Dashboard │ Pipelines │ Inventory │ Settings     │
├──────────────────────────────────────────────────┤
│                                                  │
│  ┌─────────────────────────┐ ┌────────────────┐  │
│  │                         │ │ Sources        │  │
│  │      MapLibre Map       │ │                │  │
│  │   (coverage rectangles) │ │ ▌USGS Basemap  │  │
│  │                         │ │  z0-14 · 25 GB │  │
│  │  ┌───────────────────┐  │ │                │  │
│  │  │ USGS z0-14        │  │ │ ▌NOAA NAIP    │  │
│  │  │  ┌──────┐         │  │ │  z18 · 1.7 GB │  │
│  │  │  │NOAA  │         │  │ │                │  │
│  │  │  │z18   │         │  │ │ ▌M2M           │  │
│  │  │  └──────┘         │  │ │  z19 · 304 MB │  │
│  │  └───────────────────┘  │ │                │  │
│  │                         │ │ ────────────── │  │
│  └─────────────────────────┘ │ Total: 27 GB   │  │
│                               │ Free: 576 GB   │  │
│                               └────────────────┘  │
└──────────────────────────────────────────────────┘
```

At `<640px`: sidebar stacks below the map, full width.

### Map

- MapLibre GL JS map instance (separate from the minimap in Pipelines tab)
- Dark basemap style (darkmatter or positron)
- Centered on the Western US bbox (`-124.8,31.3,-102.0,49.0`) with auto-fit to coverage
- Each source's coverage rendered as a semi-transparent colored rectangle (GeoJSON polygon layer)
- Colors assigned per source from a fixed palette:
  - imagery (USGS): `#89b4fa` (blue)
  - imagery_noaa: `#a6e3a1` (green)
  - imagery_m2m: `#f9e2af` (amber)
  - imagery_sentinel: `#cba6f7` (purple)
  - imagery_naip: `#fab387` (peach)
  - imagery_custom: `#f38ba8` (red)
- **One rectangle per source** using the union (outer envelope) of all zoom-level bounds. Per-zoom detail is shown in the sidebar only, not on the map. This avoids 15+ overlapping same-color rectangles for sources like USGS basemap (z0-z14).
- Rectangle opacity: fill 0.1, stroke 0.6, stroke-width 2
- Label on each rectangle: source name + zoom range
- Clicking a rectangle on the map highlights the corresponding sidebar entry

### Sidebar

- Scrollable list of sources from catalog data
- Each entry shows:
  - Colored left border (matches map rectangle color)
  - Source name
  - Zoom levels present (e.g., "z0, z1, ..., z14" or "z18")
  - File size (human-readable: MB or GB)
  - Tile count
  - Last modified date
  - TileServer registration status (Registered checkmark or "Not registered" warning)
- Clicking a sidebar entry:
  - Highlights the entry (selected state)
  - Zooms/pans map to that source's bounds
  - Shows the delete button for that source
- **Selected state** shows an expanded detail panel:
  - Per-zoom breakdown (zoom level: tile count)
  - Delete button with source name

### Disk Summary

Below the source list:
- Total imagery on disk (sum of all source sizes)
- Disk free (fetched from existing `GET /admin/status` endpoint which already returns `disk_free_gb`)
- Simple bar showing used/free ratio

## Delete Flow

### Frontend

1. User clicks source in sidebar → expanded detail shows "Delete [source name]" button (red)
2. Click Delete → confirmation dialog: "Delete imagery_noaa.mbtiles (1.7 GB)? This removes the file and unregisters it from TileServer. This cannot be undone."
3. Confirm → `DELETE /admin/imagery/{source_id}` request
4. On success: re-fetch catalog, re-render map + sidebar
5. On error: show error message in sidebar

### Backend

New endpoint: `DELETE /admin/imagery/{source_id}`

1. Validate `source_id` matches regex `^imagery[a-z0-9_]*$` (security: prevent path traversal, no hyphens/slashes)
2. Resolve file path: `data_dir / f"{source_id}.mbtiles"`
3. Verify file exists (404 if not)
4. Delete the MBTiles file FIRST (if this fails, config is unchanged — safe)
5. Remove from TileServer config.json (using `tileserver_config.py` helper)
6. Return `{"deleted": source_id, "file": filename}`

Order matters: delete file first, then update config. If file deletion fails (permissions, locked), the config is untouched and the error is clean. If config update fails after file deletion, the config has an orphaned entry pointing to a missing file — harmless, and the catalog won't show it since the file is gone.

The TileServer config update uses the existing `scripts/tileserver_config.py` module. A new `remove_mbtiles_from_config()` function mirrors the existing `add_mbtiles_to_config()`. It returns `True` if the source was removed, `False` if it wasn't in the config (idempotent, no error).

TileServer restart is NOT triggered by the delete endpoint. The user can restart manually or wait for the next pipeline run to restart it. The file being gone means TileServer will serve 404s for that source's tiles — acceptable since the user just chose to delete it.

### Security

- `source_id` is validated against the regex `^imagery[a-z0-9_]*$` (alphanumeric + underscore, must start with "imagery")
- No path separators allowed (prevents `../../etc/passwd`)
- Only files in the data directory are deletable
- The base `imagery.mbtiles` (USGS basemap) could be deletable — this is intentional (user may want to free 25 GB)

## Data Flow

1. On tab activation, fetch `GET /admin/imagery/catalog`
2. Render map with GeoJSON rectangles from `bounds_lonlat` per source per zoom level
3. Populate sidebar from catalog data
4. On delete: `DELETE /admin/imagery/{source_id}` → re-fetch catalog → re-render

## Files Modified

| File | Changes |
|------|---------|
| `frontend/config/index.html` | Add Inventory tab HTML + CSS + JS (map, sidebar, delete UI) |
| `services/search/main.py` | Add `DELETE /admin/imagery/{source_id}` endpoint |
| `scripts/tileserver_config.py` | Add `remove_mbtiles_from_config()` function |
| `tests/test_imagery_catalog.py` | Add tests for delete endpoint |
| `tests/test_tileserver_config.py` | Add tests for remove function |

## Container Width Override

The Inventory tab needs a wider container than the default 600px. This is achieved by toggling a CSS class on the `.container` element in the tab switch handler:

```javascript
// In switchTab():
document.querySelector('.container').classList.toggle('wide', tabId === 'tab-inventory');
```

```css
.container.wide { max-width: 1000px; }
```

This ensures only the Inventory tab gets the wider layout. Other tabs are unaffected.

## MapLibre Instance Management

The Pipelines tab already has a minimap MapLibre instance. The Inventory tab adds a second one. To avoid GPU memory pressure on the Pi 5:

- **Lazy init:** The inventory map is created on first tab activation, not page load
- **No teardown needed:** MapLibre instances are lightweight when not rendering (no animation loop when hidden). The minimap is similarly always-alive.

## Adversarial Review Findings (5 rounds: Opus, Opus, Opus, Sonnet, Sonnet)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| F1 | CSS container width override unscoped | High | JS class toggle on .container in tab switch |
| F2 | Dual MapLibre GPU pressure | Medium | Lazy init on first tab activation |
| F3 | Frontend retries deleted sources every 30s | Low | Acceptable — 404 responses tiny, no data impact |
| F4 | remove_mbtiles_from_config needs idempotency | Medium | Returns false if not found, no error |
| F5 | Regex allows imagery, rejects hyphens | Low | Matches all current source IDs (underscore format) |
| F6 | Multiple rectangles per source at different zooms | High | One rectangle per source using union of all zoom bounds |
| F7 | Disk free not in catalog response | Medium | Fetch from existing /admin/status endpoint |
| F8 | Delete atomicity — file then config order | Medium | Delete file first, then config update |

## What This Does NOT Change

- The catalog endpoint (already built)
- Pipeline start/cancel/status endpoints
- Frontend map app (app.js)
- TileServer configuration format
- Other admin panel tabs (Dashboard, Pipelines, Settings)
