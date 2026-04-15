# Pipeline Admin Page Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Pipelines tab dropdown+cards layout with a card-per-source grid featuring inline expand, catalog-driven data, and per-source progress routing.

**Architecture:** Single-file rewrite of the Pipelines tab in `frontend/config/index.html`. The HTML section (lines 155-380) is replaced with a card grid. The JS section is refactored to use a source registry, dynamic DOM IDs, and mode-based progress routing. Existing elevation/OSM sections and all backend endpoints are unchanged.

**Tech Stack:** Vanilla JS, HTML, CSS (inline in the style block), MapLibre GL JS (minimap)

**Spec:** `docs/superpowers/specs/2026-04-15-pipeline-admin-overhaul-design.md`

**XSS note:** This file uses innerHTML in several places for rendering card content. All content is derived from static registry data and server API responses — never from user text input. The existing codebase uses this same pattern throughout (e.g., renderGenericProgress, renderDashboard). No user-supplied strings are interpolated into HTML without encoding. This is consistent with the existing code style and acceptable for an admin panel served on localhost.

---

## File Map

| File | Role | Tasks |
|------|------|-------|
| `frontend/config/index.html` | Admin panel — HTML, CSS, and JS | All tasks (1-4, sequential) |

**Cross-task dependencies:** All tasks modify the same file. They MUST run sequentially, not in parallel.

---

## Task 1: Source Registry + Card Grid HTML + CSS

**Files:**
- Modify: `frontend/config/index.html` (CSS block lines ~8-115, Pipelines tab HTML lines ~155-380)

BEFORE starting work:
1. Read the full spec at `docs/superpowers/specs/2026-04-15-pipeline-admin-overhaul-design.md`
2. Read the current `frontend/config/index.html` fully — understand the HTML structure, CSS, and JS
3. Read `dev/testing-pitfalls.md`

**Context:** The admin panel is a single HTML file with inline style and script sections. The Pipelines tab currently has a dropdown for 4 imagery sources (lines 162-167), shared controls (bbox, zoom, buttons — lines 185-228), then 3 collapsible cards (Sentinel lines 260-309, NAIP lines 311-349, Import lines 351-379). Elevation (lines 231-244) and OSM POI (lines 246-258) are separate sections that stay unchanged.

**What to do:** Replace the imagery dropdown + collapsible cards with a card grid. Keep elevation and OSM POI sections exactly as-is.

- [ ] **Step 1: Add CSS for card grid layout**

Add CSS rules to the style block for the new card grid. Include: `.card-grid` (2-column grid with 1-column at 480px), `.source-card` (card styling with hover, dimmed, expanded, disabled, and custom states), `.auth-badge` (free/apikey), `.card-body` (hidden by default, shown when expanded), `.config-row`, `.estimate-box`, `.btn-row`, `.cred-warning`, `.gateway-warning`.

Reference the spec for the Catppuccin color palette: `#181825` (card bg), `#313244` (input bg), `#45475a` (borders), `#89b4fa` (primary blue), `#a6e3a1` (green/free), `#f9e2af` (yellow/apikey/warning), `#f38ba8` (red/error).

Key CSS behaviors:
- `.source-card.expanded` gets `grid-column: 1 / -1` to span full width
- `.source-card.dimmed` gets `opacity: 0.4; pointer-events: none`
- `.source-card .card-body` is `display: none` by default, `display: block` when `.expanded`
- `.source-card .card-close` is `display: none` by default, shown when `.expanded`

- [ ] **Step 2: Add source registry in JS**

Add a `SOURCE_REGISTRY` array near the top of the script block. Each entry is an object with: `id`, `name`, `auth` ('free'|'apikey'|null), `resolution`, `zoom`, `description`, `pipelineType`, `pipelineMode`, `statusType`, `controls`, and optional `disabled`/`disabledReason`/`isCustom` flags.

The 7 sources and their pipeline mappings (from spec):
- imagery → type:imagery, mode:direct, status:imagery
- imagery_noaa → type:imagery, mode:noaa, status:imagery
- imagery_m2m → type:imagery, mode:m2m, status:imagery
- imagery_sentinel → type:sentinel, mode:null, status:sentinel
- imagery_naip → type:imagery, mode:nationalmap, status:imagery
- imagery_naip_county → type:naip, mode:null, status:naip (disabled:true)
- imagery_custom → type:null, mode:null, status:import (isCustom:true)

- [ ] **Step 3: Replace Pipelines tab HTML**

Replace the content between `<div id="tab-pipelines">` and the closing tag before `<!-- SETTINGS TAB -->` with:
1. Pipeline hint banner (keep existing text)
2. Shared Coverage Area section: minimap container + bbox input (keep existing minimap element ID)
3. `<div id="source-card-grid" class="card-grid"></div>` — rendered by JS
4. Elevation Tiles section — copy existing HTML exactly (lines 231-244)
5. OSM POI Extraction section — copy existing HTML exactly (lines 246-258)

**IMPORTANT:** The old imagery dropdown, Sentinel collapsible card, NAIP collapsible card, and Import section are ALL removed.

- [ ] **Step 4: Add renderSourceCards() and toggleCardExpand() functions**

`renderSourceCards()` iterates SOURCE_REGISTRY, creates card DOM elements for each source, merges with `_catalogData` (empty object initially), and appends to the grid. Each card shows: name, auth badge, zoom/resolution meta line, disk info from catalog (or "Not downloaded"), a Configure/Import button, a hidden close button, hidden progress elements, and a hidden card-body div.

DOM IDs follow the pattern: `card-{source_id}-{suffix}` where suffix is one of: configure, close, body, start, cancel, progress, progress-fill, progress-detail, completed, estimate.

`toggleCardExpand(sourceId)` handles expand/collapse: removes expanded class from current card, clears its body, if sourceId is different then adds expanded class, dims other cards, and calls `renderCardBody(src)`.

Use DOM methods (createElement, textContent, appendChild) for user-visible text. The card structure HTML can use the existing codebase's pattern of building HTML strings from registry data (all values are from the static registry, not user input).

- [ ] **Step 5: Verify the page loads without errors**

Open `http://localhost:8097/#pipelines`. Verify 7 cards render, expand/collapse works (body will be empty), elevation and OSM sections are unchanged.

- [ ] **Step 6: Commit**

```bash
git add frontend/config/index.html
git commit -m "feat: pipeline admin card grid layout with source registry"
```

---

## Task 2: Source-Specific Config Panel Bodies

**Files:**
- Modify: `frontend/config/index.html` (JS — add renderCardBody dispatcher and per-source panel renderers)

BEFORE starting work:
1. Read the spec sections: "Source-Specific Config Panels", "Pipeline Start Parameters", "Estimate Mechanisms"
2. Read the current state of `frontend/config/index.html` after Task 1
3. Read `dev/testing-pitfalls.md`

**Context:** Task 1 created the card grid and `toggleCardExpand()` which calls `renderCardBody(src)`. This task implements the per-source panel content. Each panel has different controls and sends different parameters to the backend.

**WARNING:** All event listeners must be attached AFTER the panel HTML is inserted into the DOM. The panel is rendered dynamically when the card expands.

**WARNING:** Import uses `POST /admin/pipeline/import?params` (query params), NOT `POST /admin/pipeline/start` (JSON body). See the spec's parameter table.

- [ ] **Step 1: Add renderCardBody dispatcher**

A switch on `src.controls` that dispatches to per-source render functions: direct, noaa, m2m, sentinel, nationalmap, naip_county (no-op, disabled), import.

- [ ] **Step 2: Implement renderDirectBody (USGS Basemap)**

Panel contents: zoom range dropdown (0-8 through 0-14, default 0-14), resume checkbox, estimate display (updated on zoom change using existing `estimateTiles()` function), Start Download button.

Start handler calls `startPipeline(src, { zoom, update })`.

- [ ] **Step 3: Implement renderNoaaBody**

Panel contents: description text, state/year dropdown (Arizona 2021), on-disk info from catalog, estimate box with Estimate button that calls `GET /admin/pipeline/noaa/estimate`, Start Download button.

Estimate response fields: `tile_count`, `raw_gb`, `final_gb`, `eta_seconds`, `disk_free_gb`. Display all with disk space warning if `disk_free_gb < final_gb * 1.2`.

Start handler calls `startPipeline(src, { state, year })`.

- [ ] **Step 4: Implement renderM2mBody**

Panel contents: credential warning (if `!_m2mConfigured`) with link to Settings tab, zoom range dropdown (0-16/0-17/0-19), concurrency selector (3/4/5), resume checkbox, Start button (disabled if no credentials).

Start handler calls `startPipeline(src, { zoom, concurrency, update })`.

- [ ] **Step 5: Implement renderSentinelBody**

Panel contents: credential warning (if `!_copernicusConfigured`), date range inputs (default last 6 months), cloud cover range slider with live label, estimate box with Estimate button that calls `GET /admin/pipeline/sentinel/estimate`, Start button (disabled if no credentials).

Start handler calls `startPipeline(src, { date_start, date_end, cloud_cover_max, mode: 'composite' })`.

- [ ] **Step 6: Implement renderNationalmapBody and renderImportBody**

National Map: throttling warning, zoom dropdown (z15-z18), inline estimate via `estimateTiles()`, Start button. Start calls `startPipeline(src, { zoom, concurrency: 20 })`.

Import: instructions, scan result from `GET /admin/pipeline/import/scan` (auto-runs on expand), layer name input, delete-after checkbox, Import button (disabled until files found), Refresh Scan button. Import calls `POST /admin/pipeline/import?delete_after=bool&layer_name=str` (NOT `/admin/pipeline/start`).

- [ ] **Step 7: Add startPipeline helper**

Takes `(src, params)`, builds POST body `{ type: src.pipelineType, mode: src.pipelineMode, bbox, ...params }`, calls `POST /admin/pipeline/start`, collapses card on success, shows alert on error.

- [ ] **Step 8: Verify all panels render and function**

Test each card's Configure panel in the browser. Verify controls render, estimate buttons work (for sources with estimate endpoints), and Start buttons send correct parameters (check Network tab in DevTools).

- [ ] **Step 9: Commit**

```bash
git add frontend/config/index.html
git commit -m "feat: source-specific config panels for all 7 imagery sources"
```

---

## Task 3: Progress Routing + Catalog Fetch

**Files:**
- Modify: `frontend/config/index.html` (JS — refactor polling + add catalog fetch)

BEFORE starting work:
1. Read the spec sections: "Source ID Mapping", "Data Flow", "Shared status channel"
2. Read the current polling code (search for `fetchAll`) in `frontend/config/index.html`
3. Read `dev/testing-pitfalls.md`

**Context:** The existing code polls `GET /admin/pipeline/status?type=imagery` every 10 seconds and renders progress into hardcoded DOM IDs. Four sources share `type=imagery`. The status response includes a `mode` field. This task rewires polling to route progress to the correct card, and fetches the catalog on page load.

**WARNING:** The existing `renderImageryProgress`, `renderSentinel`, `renderNaip` functions target old DOM IDs. They must be replaced, not called.

- [ ] **Step 1: Add fetchCatalog function**

Fetches `GET /admin/imagery/catalog`, populates `_catalogData` object (keyed by source ID), then calls `renderSourceCards()` to refresh card display with disk data. Called on page load and after pipeline completion.

- [ ] **Step 2: Add renderSourceProgress function**

Takes `(sourceId, statusData)`. Builds the ID map `{ startBtn, cancelBtn, progressDiv, progressFill, progressDetail, completedEl }` using the `card-{sourceId}-{suffix}` pattern. Dynamically creates a cancel button if it doesn't exist (attaches click handler for `POST /admin/pipeline/cancel`). Calls the existing `renderGenericProgress(d, ids)`.

On pipeline completion (`d.status === 'completed'`), calls `fetchCatalog()` to refresh disk data.

- [ ] **Step 3: Refactor fetchAll polling**

Replace the imagery/sentinel/naip/import status handlers in `fetchAll()`:
- `type=imagery` response: inspect `d.mode || d.source || 'direct'` to map to card ID via `{ direct: 'imagery', noaa: 'imagery_noaa', m2m: 'imagery_m2m', nationalmap: 'imagery_naip' }`. Call `renderSourceProgress(cardId, d)`.
- `type=sentinel`: call `renderSourceProgress('imagery_sentinel', d)`
- `type=naip`: call `renderSourceProgress('imagery_naip_county', d)`
- `type=import`: call `renderSourceProgress('imagery_custom', d)`

Keep elevation and OSM handlers unchanged (they still use `renderElevation` and `renderOsmPoi`).

- [ ] **Step 4: Update updatePipelineButtons**

Replace hardcoded `ALL_START_BTNS` array with a CSS class selector: `document.querySelectorAll('.pipeline-start-btn').forEach(...)`. Disable all start buttons when `_anyPipelineRunning` is true.

- [ ] **Step 5: Remove old render functions**

Delete: `renderImageryProgress`, `renderSentinel`, `renderNaipCountyList`, `renderNaip`, and old import rendering code. Keep: `renderGenericProgress`, `renderElevation`, `renderOsmPoi`, `renderDashboard`, `renderPipelineBanner`.

- [ ] **Step 6: Remove old event handler registrations**

Delete registrations for old element IDs: `cfg-source` change, `cfg-start` click, `cfg-cancel` click, `sentinel-start/cancel/estimate-btn`, `naip-start/lookup-btn`, `import-start/refresh`, collapsible card toggles.

- [ ] **Step 7: Wire initialization**

Call `fetchCatalog()` during initialization (before or alongside the first `fetchAll()` call). Ensure `renderSourceCards()` is called after catalog data is available.

- [ ] **Step 8: Verify progress routing**

Check that pipeline status renders in the correct source card. Start the elevation pipeline as a smoke test (safe, fast). Verify elevation progress still works in its unchanged section.

- [ ] **Step 9: Commit**

```bash
git add frontend/config/index.html
git commit -m "feat: catalog-driven cards with mode-based progress routing"
```

---

## Task 4: Cleanup + Polish

**Files:**
- Modify: `frontend/config/index.html` (CSS cleanup, dead code removal, verification)

BEFORE starting work:
1. Read through the full file after Tasks 1-3
2. Read `dev/testing-pitfalls.md`

- [ ] **Step 1: Remove dead CSS**

Remove rules for elements that no longer exist: `.collapsible-card`, `.collapsible-header`, `.collapsible-body`, `.collapsible-arrow`, `.county-list`, `.county-item`, `.county-group`, and any rules targeting removed element IDs.

- [ ] **Step 2: Remove dead JS variables and code**

Remove: `_naipSelectedCounties`, `_naipRemovedCounties`, old `SOURCE_LABELS` entries superseded by registry, references to old element IDs, old NOAA estimate handler, old Sentinel advanced toggle, old collapsible toggle handlers.

- [ ] **Step 3: Verify no console errors**

Open all three tabs in the browser, check DevTools console for errors. Fix any missing element references or undefined variables.

- [ ] **Step 4: Test all tabs end-to-end**

Dashboard: services, disk info, pipeline banner. Pipelines: card grid, all 7 cards, expand/collapse, elevation, OSM. Settings: credentials, TLS, STT.

- [ ] **Step 5: Commit**

```bash
git add frontend/config/index.html
git commit -m "refactor: cleanup dead CSS/JS from pipeline admin overhaul"
```

---

## Review Checkpoint

After all 4 tasks, review from multiple perspectives (minimum 3 rounds):

1. **Spec compliance:** Does every source have the correct controls? Does the ID mapping match the spec table?
2. **Progress routing:** Does `mode` field correctly route imagery status to the right card?
3. **Catalog integration:** Do cards update after pipeline completion?
4. **No regressions:** Elevation, OSM, Dashboard, Settings all still work?
5. **DOM ID consistency:** Are all IDs using `card-{source_id}-{suffix}` pattern?
6. **No dead code:** No references to removed elements?
