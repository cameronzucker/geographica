# Frontend UX Fixes — Design Spec

**Date:** 2026-04-08
**Status:** Approved
**Scope:** 7 bugs/regressions in frontend/app.js — camera controls, click handling, search UX, routing UX

## Issue 1: CTRL/SHIFT Camera Rotation Regression

### Current Behavior
`initFreeLookCamera()` at app.js:2674-2742 implements:
- CTRL+left drag → free-look mode (bearing/pitch from fixed sky point)
- SHIFT+left drag → ground-orbit (MapLibre default dragRotate)
- Right-click drag → ground-orbit

**Bug:** `map.dragRotate.enable()` is called on SHIFT mousedown (line 2739) and right-click mousedown (line 2689) but never re-disabled after the gesture completes. Once the user SHIFT-drags or right-click-drags once, `dragRotate` stays enabled permanently, making all subsequent regular left-click drags also orbit instead of pan.

### Fix

Add mouseup handlers that re-disable `dragRotate` after orbit gestures complete:

**In the right-click handler (near line 2687-2692):**
Add a `mouseup` listener that calls `map.dragRotate.disable()` when the right mouse button is released. Use a flag (`orbitActive`) to track whether an orbit gesture is in progress and only disable on the corresponding mouseup.

**In the SHIFT handler (near line 2737-2741):**
Same pattern — track that SHIFT-orbit started, disable dragRotate on mouseup.

**State machine:**
```
Default state: dragRotate disabled, dragPan enabled
CTRL+mousedown → free-look: dragPan disabled, cursor crosshair, manual bearing/pitch
SHIFT+mousedown → orbit: dragRotate enabled
Right-click mousedown → orbit: dragRotate enabled
Any mouseup → restore default: dragRotate disabled, dragPan enabled, cursor default
```

**Edge case:** If user holds CTRL, starts free-look, then releases CTRL before mouseup — the mouseup handler in the existing code (line 2729-2734) already handles this correctly by checking `freeLookActive`. No change needed there.

### Files Modified
- `frontend/app.js`: `initFreeLookCamera()` function (lines 2674-2742)

### Testing
- CTRL+left drag → bearing/pitch change, camera stays at fixed point → release → map pannable
- SHIFT+left drag → ground orbit → release → map pannable (not orbiting)
- Right-click drag → ground orbit → release → map pannable
- Sequence: SHIFT-drag, release, regular left-drag → must pan, NOT orbit
- Sequence: CTRL-drag for free-look, release → no point info popup

---

## Issue 2: CTRL/SHIFT Click Suppresses Point Info Lookup

### Current Behavior
The generic map click handler at app.js:866-875 calls `reverseGeocodeAndShowPopup()` on every click that doesn't hit an imported feature. It does NOT check for modifier keys. When the user releases a CTRL+drag (free-look) or SHIFT+drag (orbit), the click event fires and triggers an unwanted reverse geocode popup.

### Fix

Two guards in the generic map click handler:

**Guard 1 — Modifier key check:**
```js
if (e.originalEvent.ctrlKey || e.originalEvent.shiftKey) return;
```
Added at the top of the `map.on('click')` handler, before the `queryRenderedFeatures` call.

**Guard 2 — Drag suppression flag:**
Add a module-level `var wasDragging = false;` variable.
- In `initFreeLookCamera()`: set `wasDragging = true` when free-look activates (CTRL+mousedown) or orbit activates (SHIFT/right-click mousedown)
- In the generic click handler: check `if (wasDragging) { wasDragging = false; return; }`
- In mouseup handlers: set `wasDragging = true` (the click fires after mouseup, so the flag persists through to the click handler, then gets cleared)

**Why both guards:** Guard 1 catches the case where user clicks (not drags) with CTRL/SHIFT held. Guard 2 catches the case where user CTRL-drags and releases — the click event fires without modifier keys still down if the user releases CTRL before the mouse button.

### Files Modified
- `frontend/app.js`: generic `map.on('click')` handler (line 866), `initFreeLookCamera()` (lines 2674-2742)

### Testing
- CTRL+left drag → release → no point info popup
- SHIFT+left drag → release → no point info popup
- Regular click on empty map → point info popup (unchanged behavior)
- Click on imported feature → feature popup, no reverse geocode (unchanged)

---

## Issue 3: Mobile Search Results — Zoom to Cover Results

### Current Behavior
`renderSearchResults()` at app.js:700-768 renders the full results list and pins but does NOT zoom the map to fit all result locations. On mobile, the results list can be very long relative to screen real estate.

### Fix

**A) Zoom-to-fit after search:**

After `updateSearchPins(results)` (line 766), compute bounding box from all result coordinates and call `map.fitBounds()`:

```js
if (results.length > 1) {
  var bounds = new maplibregl.LngLatBounds();
  results.forEach(function(item) {
    var lng = parseFloat(item.lon || item.lng || item.longitude);
    var lat = parseFloat(item.lat || item.latitude);
    if (!isNaN(lng) && !isNaN(lat)) bounds.extend([lng, lat]);
  });
  if (!bounds.isEmpty()) {
    var isMobile = window.innerWidth < 768;
    map.fitBounds(bounds, {
      padding: isMobile
        ? { top: 60, bottom: 120, left: 20, right: 20 }
        : { top: 60, bottom: 60, left: 320, right: 60 },
      maxZoom: 14
    });
  }
}
```

Desktop padding includes 320px left to account for sidebar width. Mobile padding includes more bottom for the collapsed result list. `maxZoom: 14` prevents over-zooming when results are clustered.

**B) Collapsed results list on mobile:**

On mobile (`window.innerWidth < 768`), after rendering the full list, hide all `<li>` elements beyond the first 3. Append a "Show N more results" button that removes the limit when tapped. This keeps the map visible while still providing access to all results.

```js
if (window.innerWidth < 768 && items.length > 3) {
  items.forEach(function(li, i) { if (i >= 3) li.classList.add('mobile-hidden'); });
  // Append "Show N more" expander
  var expander = document.createElement('li');
  expander.className = 'search-results-expander';
  expander.textContent = 'Show ' + (items.length - 3) + ' more results';
  expander.addEventListener('click', function() {
    items.forEach(function(li) { li.classList.remove('mobile-hidden'); });
    expander.remove();
  });
  list.appendChild(expander);
}
```

### Files Modified
- `frontend/app.js`: `renderSearchResults()` function (lines 700-768)
- `frontend/style.css`: `.mobile-hidden { display: none; }` and `.search-results-expander` styles

### Testing
- Desktop: search results zoom map to show all pins with sidebar clearance
- Mobile: search results zoom map, list collapsed to 3 items with expander
- Single result: no fitBounds (current flyTo behavior in selectSearchResult preserved)
- No results: no fitBounds attempted

---

## Issue 4: Search Result Pin Click-Through / Routing Accuracy

### Current Behavior
Clicking a search result pin on the map (app.js:629-638) only highlights the corresponding list item with a 2-second CSS animation. It does NOT:
- Open a popup with result details
- Show distance from GPS
- Offer routing to the result
- Prevent the generic click handler from firing underneath

The generic click handler (line 866) then fires a reverse geocode at the click point, which at low zoom levels can be far from the actual result coordinates, leading to routing inaccuracy.

### Fix

**A) Block generic click handler for search result clicks:**

Add `'search-result-circles'` to the layer exclusion check in the generic click handler:

```js
var features = map.queryRenderedFeatures(e.point, {
  layers: ['imported-points', 'imported-lines', 'imported-polygons',
           'imported-polygon-outlines', 'search-result-circles']
});
if (features.length > 0) return;
```

**B) Enhanced search result pin click handler:**

Replace the current highlight-only behavior with a full popup:

```js
map.on('click', 'search-result-circles', function (e) {
  if (!e.features || !e.features.length) return;
  var feat = e.features[0];
  var idx = parseInt(feat.properties.index, 10) - 1;
  var resultCoords = feat.geometry.coordinates;

  // Still highlight list item
  var items = document.querySelectorAll('#search-results li:not(.search-intent-subtitle)');
  if (items[idx]) {
    items[idx].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    items[idx].classList.add('search-result-active');
    setTimeout(function() { items[idx].classList.remove('search-result-active'); }, 2000);
  }

  // Build popup with name, distance, route button
  var popupDiv = document.createElement('div');
  // ... name from properties or lastSearchResults[idx]
  // ... distance from GPS using haversine
  // ... "Route to here" button that sets routeEndCoords
  
  new maplibregl.Popup({ offset: 25, closeOnClick: true })
    .setLngLat(resultCoords)   // Use result coords, NOT click point
    .setDOMContent(popupDiv)
    .addTo(map);
});
```

**C) Distance display in popup:**

Add a new `haversineDistance(coordA, coordB)` helper function (returns distance in meters between two `[lng, lat]` arrays). This does not currently exist in app.js — it must be added. Standard haversine formula, ~10 lines.

Calculate distance from current GPS position (if available) or route start point (if set):

```js
var distanceFrom = null;
var distanceLabel = '';
if (routeStartCoords) {
  distanceFrom = routeStartCoords;
  distanceLabel = 'from start';
} else if (gpsLastPos && !gpsStale) {
  distanceFrom = gpsLastPos;
  distanceLabel = 'from GPS';
}
if (distanceFrom) {
  var d = haversineDistance(distanceFrom, resultCoords);
  // Format with formatRouteDistance() (already exists in app.js)
}
```

**D) "Route to here" button:**

```js
var routeBtn = document.createElement('button');
routeBtn.textContent = 'Route to here';
routeBtn.addEventListener('click', function() {
  setRouteEnd(resultCoords, resultName);
  popup.remove();
});
```

Where `setRouteEnd()` populates the route end input field and coordinates, then auto-generates route if start is already set.

**E) Store search results for reference:**

Add a module-level `var lastSearchResults = [];` that's populated in `renderSearchResults()`. The pin click handler uses `lastSearchResults[idx]` to access the full result object (name, display_name, etc.) since MapLibre feature properties only contain `index` and `name`.

### Files Modified
- `frontend/app.js`: `search-result-circles` click handler (lines 629-638), generic click handler (line 866-875), new `lastSearchResults` state variable, new `setRouteEnd()` helper

### Testing
- Click search pin → popup with name, distance, route button (NOT reverse geocode)
- Click "Route to here" → route endpoint set, route generated if start exists
- Distance shows "from GPS" by default, "from start" if route start is set
- Click empty map → reverse geocode (unchanged)
- Click imported feature → feature popup (unchanged)

---

## Issue 5: Mobile Route Zoom-to-Fit

### Current Behavior
`renderRoute()` at app.js:1218 calls `map.fitBounds(bounds, { padding: 60 })` with static 60px padding on all sides. This reportedly doesn't zoom correctly on mobile — likely because the sidebar overlay covers a large portion of the viewport and 60px padding is insufficient.

### Fix

Make fitBounds padding responsive to viewport size:

```js
var isMobile = window.innerWidth < 768;
var padding = isMobile
  ? { top: 40, bottom: 100, left: 20, right: 20 }
  : { top: 60, bottom: 60, left: 340, right: 60 };
map.fitBounds(bounds, { padding: padding });
```

Desktop left padding accounts for the ~320px sidebar (var `--sidebar-width`). Mobile bottom padding accounts for the bottom control bar.

Additionally, on mobile, close/collapse the sidebar after route generation so the full map viewport is available for the route display. The user can reopen it to see directions.

### Files Modified
- `frontend/app.js`: `renderRoute()` function (line 1218)

### Testing
- Desktop: route fits with sidebar clearance on left
- Mobile: route fits within visible viewport, sidebar collapses
- Short route (same city): doesn't over-zoom
- Long route (cross-state): all legs visible

---

## Issue 6: Auto-Regenerate Route on Stop Addition

### Current Behavior
`addWaypointRow()` at app.js:880-929 creates a waypoint UI row and marker but does NOT trigger route recalculation. User must manually click "Get Route" again.

### Fix

**Trigger auto-regeneration when a waypoint's coordinates are set AND a route already exists:**

1. After waypoint geocode completion: in `geocodeForRoute()` (app.js:1048-1086), after the `which === 'waypoint'` branch sets coords at line 1074-1076, call `scheduleRouteRegen()`
2. After GPS button click: in the `gpsBtn` handler inside `addWaypointRow()` (app.js:905-911), after `placeWaypointMarker(idx)`, call `scheduleRouteRegen()`
3. After waypoint removal: in `removeWaypoint()` (app.js:931-937), after `rebuildWaypointUI()`, call `scheduleRouteRegen()`

**Debounce:** Wrap auto-regeneration in a 300ms debounce to prevent rapid re-routing when multiple waypoints are edited quickly:

```js
var routeRegenTimer = null;
function scheduleRouteRegen() {
  if (!lastRouteTrip) return;  // No existing route to update
  if (!routeStartCoords || !routeEndCoords) return;  // Missing endpoints
  clearTimeout(routeRegenTimer);
  routeRegenTimer = setTimeout(requestRoute, 300);
}
```

Call `scheduleRouteRegen()` in each of the three trigger points above.

**UX feedback:** While route is recalculating, show a brief "Updating route..." indicator in the route summary area (reuse the existing "Calculating..." button state).

### Files Modified
- `frontend/app.js`: new `scheduleRouteRegen()` function, modifications to `geocodeForRoute` callback, GPS button handler, `removeWaypoint()`

### Testing
- Add waypoint to existing route → route regenerates within 300ms
- Remove waypoint from existing route → route regenerates
- Use GPS button for waypoint → route regenerates
- Add waypoint with no existing route → no regeneration
- Rapid add/remove → only one route request (debounced)

---

## Issue 7: Reorderable Stops with Auto-Regeneration

### Current Behavior
`rebuildWaypointUI()` at app.js:939-947 clears and re-adds all waypoint rows sequentially. There is no drag-to-reorder capability.

### Fix

**Implement drag-to-reorder using native HTML5 Drag and Drop API (no library):**

Each waypoint row in `addWaypointRow()` gets:
```js
row.draggable = true;
row.addEventListener('dragstart', function(e) {
  e.dataTransfer.setData('text/plain', String(idx));
  e.dataTransfer.effectAllowed = 'move';
  row.classList.add('dragging');
});
row.addEventListener('dragend', function() {
  row.classList.remove('dragging');
});
```

The waypoint container gets:
```js
container.addEventListener('dragover', function(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  // Show drop indicator based on mouse Y position relative to rows
  var afterElement = getDragAfterElement(container, e.clientY);
  var dragging = container.querySelector('.dragging');
  if (afterElement) {
    container.insertBefore(dragging, afterElement);
  } else {
    container.appendChild(dragging);
  }
});

container.addEventListener('drop', function(e) {
  e.preventDefault();
  var fromIdx = parseInt(e.dataTransfer.getData('text/plain'), 10);
  // Determine new index from DOM order
  var rows = container.querySelectorAll('.waypoint-row');
  var newOrder = [];
  rows.forEach(function(r) { newOrder.push(parseInt(r.dataset.wpIndex, 10)); });
  // Reorder routeWaypoints array to match new DOM order
  var reordered = newOrder.map(function(i) { return routeWaypoints[i]; });
  routeWaypoints = reordered;
  rebuildWaypointUI();
  scheduleRouteRegen();  // Auto-regenerate from Issue 6
});
```

**`getDragAfterElement()` helper:** Standard pattern — iterate sibling rows, find the one whose vertical midpoint is just below the cursor Y position.

**Touch support:** HTML5 drag-and-drop has poor mobile support. For mobile, add up/down arrow buttons (small ▲/▼ icons) next to each waypoint that swap with the adjacent row. These are always visible on mobile (`window.innerWidth < 768`) and hidden on desktop where drag works.

**CSS:**
```css
.waypoint-row.dragging { opacity: 0.4; }
.waypoint-row.drag-over { border-top: 2px solid var(--accent); }
```

### Files Modified
- `frontend/app.js`: `addWaypointRow()` gains drag attributes, new container event listeners, new `getDragAfterElement()` helper, mobile up/down buttons
- `frontend/style.css`: drag state styles, mobile reorder button styles

### Testing
- Desktop: drag waypoint row to new position → route regenerates
- Mobile: tap up/down arrows → waypoint moves, route regenerates
- Drag with no existing route → reorder works, no route request
- Single waypoint → up/down arrows hidden (nothing to reorder)
- Three waypoints: drag first to last → order reversed in array, route uses new order

---

## Cross-Issue Dependencies

| Issue | Depends On | Reason |
|-------|-----------|--------|
| Issue 2 (click suppression) | Issue 1 (camera fix) | Both touch `initFreeLookCamera()` and the `wasDragging` flag |
| Issue 7 (reorderable stops) | Issue 6 (auto-regen) | Reorder triggers `scheduleRouteRegen()` from Issue 6 |
| Issue 4 (result pin click) | Issue 3 (zoom-to-fit) | Both modify search result rendering/interaction flow |

**Implementation order:**
1. Issues 1 + 2 together (camera + click suppression — same function)
2. Issues 3 + 4 together (search result display + interaction)
3. Issue 5 alone (route zoom — small, independent)
4. Issues 6 + 7 together (auto-regen + reorderable stops)
