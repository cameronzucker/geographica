# Frontend Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Overhaul the KMZ/KML import pipeline (icon display, chunked processing, security) and fix 7 frontend UX issues (camera, search, routing).

**Architecture:** Two independent spec streams that share frontend/app.js. KMZ overhaul replaces the circle-based import layer with an icon-capable symbol layer, adds async chunked processing, and hardens the pipeline against malicious input. UX fixes address camera rotation regression, click suppression, mobile search/route behavior, auto-route-regeneration, and reorderable stops.

**Tech Stack:** Vanilla JS (ES5, var/function only), MapLibre GL JS (vendored v5.21.1), JSZip, toGeoJSON, DOMPurify (new vendor)

**Specs:**
- docs/superpowers/specs/2026-04-08-kmz-import-overhaul-design.md
- docs/superpowers/specs/2026-04-08-frontend-ux-fixes-design.md

**Pitfalls:** Read docs/pitfalls/testing-pitfalls.md and docs/pitfalls/implementation-pitfalls.md before starting any task. Key: Pitfall #6 (offline-first), Pitfall #9 (app.js ~2800 lines — extract new modules).

**IMPORTANT:** This plan was validated by 5 rounds of adversarial review (Opus, Sonnet, Haiku models) and a CSO security review. All critical findings have been incorporated into the specs and this plan. Read the specs before implementing — they contain adversarial-review-validated API corrections (e.g., MapLibre addImage requires {width, height, data} not canvas, icon-size/icon-image are layout not paint properties).

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| frontend/vendor/dompurify.min.js | HTML sanitization library | Create (vendor from CDN) |
| frontend/index.html | Script load order | Modify: add DOMPurify + kmz-import.js script tags |
| frontend/kmz-import.js | KMZ/KML import pipeline (extracted from app.js) | Create (~400 lines) |
| frontend/app.js | Main app — remove old import code, add UX fixes | Modify |
| frontend/style.css | Progress bar, mobile-hidden, drag states, reorder buttons | Modify |

**Extraction rationale:** app.js is ~2800 lines (Implementation Pitfall #9). The KMZ import overhaul adds ~400 lines of new code. Rather than growing app.js to 3200+, extract the import pipeline into frontend/kmz-import.js as a new module, following the pattern of stt.js, navigation.js, and nav-ui.js.

---

## Task Dependencies

```
Task 1 (Security: DOMPurify + URL validation)
  -> Task 2 (KMZ: Symbol layer + default icon)
       -> Task 3 (KMZ: Style resolution tables)
            -> Task 4 (KMZ: Icon pipeline)
                 -> Task 5 (KMZ: Async pipeline + chunked processing)
                      -> Task 6 (KMZ: Caller updates + file limits)
                           -> Task 7 (KMZ: Style swap survival + cleanup)

Task 8 (UX: Camera rotation fix) -- independent of KMZ tasks
  -> Task 9 (UX: Click suppression)

Task 10 (UX: Search zoom-to-fit + mobile collapse) -- independent
  -> Task 11 (UX: Search pin interaction + haversine + setRouteEnd)

Task 12 (UX: Mobile route zoom-to-fit) -- independent

Task 13 (UX: Auto-regenerate route + geocode guard) -- independent
  -> Task 14 (UX: Reorderable stops)

Task 15: Review loop -- after all tasks
```

**Parallelizable:** Tasks 8-9 can run parallel with Tasks 1-7. Tasks 10-11 can run parallel with 12-14.

---

## Preamble (Apply to Every Task)

```
BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
3. Read the relevant spec section (referenced in each task)
4. Use var/function exclusively (NO let, const, or arrow functions)
5. Follow TDD: write failing test -> implement fix -> verify green
```

## Completion Check (Apply to Every Task)

```
BEFORE marking this task complete:
1. Review your code against docs/pitfalls/implementation-pitfalls.md
2. Verify all tests pass
3. Run: git diff --stat to confirm only expected files changed
4. Commit with descriptive message
```

---

## Tasks

Full task details are in the companion specs. Each task below references the exact spec section and code locations. The specs contain complete pseudocode, API signatures, and adversarial-review-validated corrections.

### Task 1: Security Foundation -- DOMPurify + URL Validation

**Spec ref:** KMZ spec Section 5 (Security Considerations -- MANDATORY)
**Files:** Create frontend/vendor/dompurify.min.js, Modify frontend/index.html:14, Modify frontend/app.js:339-360

- [ ] Vendor DOMPurify: curl from jsdelivr CDN, save to frontend/vendor/dompurify.min.js
- [ ] Add script tag in index.html after jszip.min.js and before app.js
- [ ] Add isUrlSafe(url) function in app.js after CONSTANTS section -- blocks private IPs (IPv4+IPv6), dangerous schemes, .local domains, octal/hex IPs. See spec Section 5 URL Validation for complete blocklist.
- [ ] Sanitize KML HTML descriptions: replace the raw HTML rendering at app.js:354 with DOMPurify.sanitize() call. Keep textContent path for non-HTML. Fallback to textContent if DOMPurify not loaded.
- [ ] Gate popup icon img.src on isUrlSafe(): change app.js:339 condition to include isUrlSafe(props.icon)
- [ ] Commit

### Task 2: Symbol Layer + Default Icon Registration

**Spec ref:** KMZ spec Section 1 (Layer Changes)
**Files:** Modify frontend/app.js:204-227 (addPlaceholderSources)

- [ ] Register kmz-icon-default image in addPlaceholderSources (32x32 pink circle via canvas getImageData -> {width, height, data: Uint8Array})
- [ ] Replace imported-points circle layer with symbol layer. CRITICAL: icon-image and icon-size are LAYOUT properties, not paint. Use coalesce expressions per spec.
- [ ] Verify: import a simple KML with no icons -> features render as pink circles via fallback
- [ ] Commit

### Task 3: Style Resolution Tables (kmz-import.js)

**Spec ref:** KMZ spec Section 3 (Style Resolution)
**Files:** Create frontend/kmz-import.js, Modify frontend/index.html

- [ ] Create frontend/kmz-import.js IIFE module with buildStyleTables(kmlDoc) and resolveFeatureIcon(props, tables)
- [ ] buildStyleTables walks KML DOM for Style/StyleMap elements, returns {styleTable, styleMapTable, urlToScale}
- [ ] resolveFeatureIcon checks properties.icon first (toGeoJSON resolved it), then styleUrl fallback, then defaults
- [ ] Export via window._kmzImport object
- [ ] Add script tag in index.html before app.js
- [ ] Commit

### Task 4: Icon Pipeline -- Fetch, Fallback, Cache

**Spec ref:** KMZ spec Section 1 (Icon Pipeline, Fallback, Icon ID Derivation)
**Files:** Modify frontend/kmz-import.js

- [ ] Add deriveIconId(url) -- extract filename, strip extension, prefix kmz-icon-, handle collisions
- [ ] Add deriveAbbreviation(styleName) -- split on _/-, first letters, truncate to 2, pad single chars
- [ ] Add generateFallbackIcon(styleName) -- canvas 32x32, hashed color circle, white text, getImageData
- [ ] Add isArchivePathSafe(path) -- reject .., /, backslash, URL-encoded traversal
- [ ] Add loadSingleIcon(url, styleName, zipArchive, mapRef) -- archive path -> blob URL -> Image, or fetch with redirect:'error' -> blob URL -> Image, or fallback
- [ ] Add loadAllIcons(tables, zipArchive, mapRef, onProgress) -- parallel with Promise.all, cap at 50, phase timeout 30s, navigator.onLine short-circuit
- [ ] Update window._kmzImport exports
- [ ] Commit

### Task 5: Async Pipeline + Chunked Processing

**Spec ref:** KMZ spec Section 2 (Async Processing Pipeline, Stages 1-6)
**Files:** Modify frontend/app.js:1809-1901 (processKMLDoc rewrite)

- [ ] Add yieldToMain() helper (function expression, NOT arrow)
- [ ] Add showImportProgress(text, current, total) helper + CSS
- [ ] Rewrite processKMLDoc as async: signature (kmlDoc, filename, zipArchive)
- [ ] Stage 1: validate DOM
- [ ] Stage 2: buildStyleTables via window._kmzImport
- [ ] Stage 3: loadAllIcons with progress callback
- [ ] Stage 4: toGeoJSON.kml(kmlDoc) + yield
- [ ] Stage 5: batch 500 features with yield -- resolve icons, assign _iconId/_iconScale/_folder, abort check per batch. Do NOT call setData during batching (O(n^2)).
- [ ] Stage 6: single setData, fitBounds, buildImportLayerUI, null references for GC
- [ ] Wrap in try/finally: importInProgress flag, partial recovery on error
- [ ] Commit

### Task 6: Caller Updates + File Size Limits

**Spec ref:** KMZ spec Section 2 (File Size Limits), caller updates
**Files:** Modify frontend/app.js:26-27, 1763-1776, 1778-1803

- [ ] Update MAX_FILE_SIZE_WARN to 25MB, MAX_FILE_SIZE_REJECT to 100MB
- [ ] Update importKML: pass null as zipArchive, chain .catch()
- [ ] Update importKMZ: pass zip object, add decompression bomb check (kmlFile._data.uncompressedSize > MAX_KML_SIZE), chain .catch()
- [ ] Commit

### Task 7: Style Swap Survival + Icon Cleanup

**Spec ref:** KMZ spec Section 1 (Style Swap Survival), Section 4 (Cleanup, Swatch Update)
**Files:** Modify frontend/app.js (addPlaceholderSources, buildImportLayerUI)

- [ ] In addPlaceholderSources: replay icon cache after registering kmz-icon-default
- [ ] In buildImportLayerUI Remove handler: decrement iconRefCounts, removeImage when 0 (guarded with hasImage)
- [ ] Update popup: skip icon img for features where _iconId !== 'kmz-icon-default'
- [ ] Update buildImportLayerUI swatch: gray #999 for icon features, retain color for non-icon
- [ ] Commit

### Task 8: Camera Rotation Fix (UX Issue 1)

**Spec ref:** UX Fixes spec, Issue 1
**Files:** Modify frontend/app.js:2674-2742

- [ ] Rewrite initFreeLookCamera: add orbitActive flag, single mouseup handler that disables dragRotate when orbit ends
- [ ] Add wasDragging state variable (set in mousemove only, not mousedown)
- [ ] MouseUp auto-clears wasDragging via setTimeout(fn, 0) safety net
- [ ] Commit

### Task 9: Click Suppression (UX Issue 2)

**Spec ref:** UX Fixes spec, Issue 2
**Files:** Modify frontend/app.js:866-875

- [ ] Add modifier key guard: if (e.originalEvent.ctrlKey || e.originalEvent.shiftKey) return
- [ ] Add wasDragging guard: if (wasDragging) { wasDragging = false; return; }
- [ ] Add 'search-result-circles' to queryRenderedFeatures layer exclusion list
- [ ] Commit

### Task 10: Search Zoom-to-Fit + Mobile Collapse (UX Issue 3)

**Spec ref:** UX Fixes spec, Issue 3
**Files:** Modify frontend/app.js:700-768, Modify frontend/style.css

- [ ] After updateSearchPins: compute LngLatBounds from results, fitBounds with responsive padding (read --sidebar-width CSS var)
- [ ] Mobile collapse: querySelectorAll li after render, hide beyond 3rd, append "Show N more" expander
- [ ] Add CSS: .mobile-hidden, .search-results-expander
- [ ] Commit

### Task 11: Search Pin Interaction (UX Issue 4)

**Spec ref:** UX Fixes spec, Issue 4
**Files:** Modify frontend/app.js (search pin handler, new helpers)

- [ ] Add haversineDistance(a, b) -- [lng, lat] pairs, returns meters
- [ ] Add lastSearchResults state var, populate in renderSearchResults
- [ ] Add setRouteEnd(coords, name) -- sets routeEndCoords, updates input, places marker, auto-routes if start exists
- [ ] Replace search-result-circles click handler: popup with name, distance from GPS/start, "Route to here" button
- [ ] Commit

### Task 12: Mobile Route Zoom-to-Fit (UX Issue 5)

**Spec ref:** UX Fixes spec, Issue 5
**Files:** Modify frontend/app.js:1218

- [ ] Replace static padding: 60 with responsive padding using --sidebar-width CSS var
- [ ] Commit

### Task 13: Auto-Regenerate Route (UX Issue 6)

**Spec ref:** UX Fixes spec, Issue 6
**Files:** Modify frontend/app.js (multiple locations)

- [ ] Add routeRegenTimer and geocodeSeq state vars
- [ ] Add scheduleRouteRegen() -- guards on lastRouteTrip + endpoints, 300ms debounce
- [ ] Add geocode sequence counter to geocodeForRoute -- discard stale responses
- [ ] Call scheduleRouteRegen after waypoint geocode, GPS button, removeWaypoint
- [ ] clearRoute must clearTimeout(routeRegenTimer)
- [ ] Commit

### Task 14: Reorderable Stops (UX Issue 7)

**Spec ref:** UX Fixes spec, Issue 7
**Files:** Modify frontend/app.js, Modify frontend/style.css

- [ ] Add draggable + dragstart/dragend to waypoint rows in addWaypointRow
- [ ] Add up/down arrow buttons for touch devices
- [ ] Add container dragover/drop listeners ONCE in initRouting (NOT per-row)
- [ ] Add getDragAfterElement helper
- [ ] Drop handler: read DOM order -> reorder routeWaypoints -> rebuildWaypointUI -> scheduleRouteRegen
- [ ] Add CSS: .dragging opacity, .waypoint-reorder-btn, @media (pointer: coarse)
- [ ] Commit

### Task 15: Review Loop

After every logical group of tasks (Tasks 1-7, Tasks 8-9, Tasks 10-11, Tasks 12-14):

```
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues. Then
update your private journal and continue onto the next tasks.
```

**Final review checklist:**
- All var (no let/const/arrow functions)
- All new functions accessible from correct scope (IIFE boundaries)
- No hardcoded pixel values where CSS vars should be used
- Popup DOM uses createElement/textContent (never raw string HTML without DOMPurify)
- Every map.removeImage guarded with map.hasImage
- importInProgress always cleared in finally
- wasDragging auto-clears via setTimeout
- routeRegenTimer cancelled in clearRoute
- geocodeSeq prevents stale responses
- icon-image and icon-size in layout (not paint)
- kmz-icon-default registered before any features added

---

## Execution Recommendation

**Option 2: Parallel session with /executing-plans in a worktree** is recommended because:
- This session consumed substantial context with brainstorming + 5 adversarial rounds + CSO review
- The plan is self-contained with explicit file:line references, complete pseudocode, and adversarial-review-validated API corrections
- Tasks are mostly sequential (security -> KMZ -> UX) with parallelizable sub-groups
- A fresh session would have maximum context for code generation
- The KMZ overhaul (Tasks 1-7) is highest-risk and benefits from focused attention
