# Admin Pipeline Card Grid UI — Holistic Bug Hunt
**Date:** 2026-04-15
**File:** `frontend/config/index.html`
**Symptom:** Cards collapse without user input, require multiple clicks to open, behave unexpectedly.

---

## Executive Summary

There are **four distinct bugs** causing the reported behavior. The most severe is a structural flaw: `fetchCatalog()` is called on pipeline completion and unconditionally calls `renderSourceCards()`, which **destroys the entire DOM** of the card grid — including any expanded card — every time a pipeline finishes. The polling loop (`fetchAll()` every 10 seconds) compounds this by calling `renderSourceProgress()` which calls `fetchCatalog()` again on terminal states. A secondary issue is that clicking any part of a collapsed card triggers a double-expand because the card itself has no click handler — the user must target the Configure button specifically, but mis-clicks on the card surface do nothing, making it feel like "multiple clicks to open". A third bug: `startPipeline()` always calls `toggleCardExpand(null)` which collapses the card before the pipeline has even confirmed it started. A fourth bug: `_expandedCard` is never reset when `renderSourceCards()` demolishes the DOM, so after the DOM is rebuilt `_expandedCard` holds a stale ID and `toggleCardExpand()` gets confused about toggle state.

---

## Bug 1 (Critical): `renderSourceCards()` Destroys DOM — Including Expanded Card — Every Time a Pipeline Finishes

### Where
- `renderSourceCards()` line 844: `grid.textContent = ''` — unconditional full teardown.
- `renderSourceProgress()` lines 619–621: calls `fetchCatalog()` on `completed`, `error`, or `cancelled`.
- `fetchCatalog()` lines 576–577: its `.then()` always calls `renderSourceCards()`.

### The call chain
```
fetchAll() [every 10s]
  -> /admin/pipeline/status?type=imagery  (or sentinel, naip, import)
  -> renderSourceProgress(cardId, d)
     -> if d.status === 'completed'|'error'|'cancelled':
        -> fetchCatalog()
           -> renderSourceCards()   <-- NUKES THE ENTIRE CARD GRID
```

### Impact
Every time a pipeline transitions to a terminal state (`completed`, `error`, `cancelled`), the full card grid is rebuilt from scratch. Any card that was expanded is destroyed. The expanded state variable `_expandedCard` still holds the old card ID, but the new DOM has no `.expanded` class on anything, so the UI is in an inconsistent state: `_expandedCard !== null` but no card appears expanded.

The next time the user clicks "Configure", `toggleCardExpand()` sees `_expandedCard` is already set to the same `src.id`, treats it as a "collapse same card" action (line 991: `if (sourceId === _expandedCard || sourceId === null)`), and collapses immediately — without ever expanding. The user must click **twice**: once to clear the stale `_expandedCard`, and once to actually expand.

### Even without a pipeline finishing, `fetchCatalog()` is called at page load
Line 2248: `fetchCatalog()` is called once at startup, then again whenever any pipeline finishes. The startup call is fine. But repeated calls on completion mean this can fire multiple times per session while the user is actively interacting with the UI.

---

## Bug 2 (High): `startPipeline()` Always Collapses the Card — Even Before Confirming Success

### Where
`startPipeline()` line 1037: `toggleCardExpand(null)` is called unconditionally in the `.then()` success path.

### The problem
When the user clicks "Start Download" inside an expanded card, the card collapses immediately. If the server returns an error, the user sees an `alert()` but their card is already collapsed and they have to re-open it, re-configure, and try again. Collapsing before confirming success also means the progress elements inside the card body are destroyed just as the pipeline is starting, so `renderSourceProgress()` can't update them (the DOM IDs don't exist yet — the card is collapsed).

### Note: Progress still works
`renderSourceProgress()` updates elements **outside** the card body (the `card-{id}-progress`, `card-{id}-progress-fill`, `card-{id}-progress-detail`, `card-{id}-completed` elements are appended directly to the card, not to `.card-body`). So progress bars survive collapse. But the configured body (zoom selects, checkboxes) is destroyed. If the user wants to cancel a running pipeline, they must re-expand the card to see the Cancel button — but Cancel is dynamically appended in `renderSourceProgress()` only when the card exists in the DOM. This part actually works because Cancel is added to the card root, not the body.

---

## Bug 3 (High): Stale `_expandedCard` After `renderSourceCards()` Rebuilds DOM

### Where
`_expandedCard` (line 839) is a module-level variable. `renderSourceCards()` (line 844) sets `grid.textContent = ''` which destroys all card DOM nodes, but **never resets `_expandedCard`**.

### What happens
1. User expands card "imagery_noaa" → `_expandedCard = 'imagery_noaa'`
2. Pipeline finishes → `fetchCatalog()` → `renderSourceCards()` → DOM rebuilt, no card has `.expanded`
3. `_expandedCard` is still `'imagery_noaa'`
4. User clicks "Configure" on imagery_noaa card again
5. `toggleCardExpand('imagery_noaa')` is called
6. Line 991: `sourceId === _expandedCard` → `true` → function returns early, treating this as a "collapse" (toggle off)
7. Card never expands — the user sees nothing happen
8. User clicks again → `_expandedCard` is now `null` → card finally expands

This explains the "requires multiple clicks to open" symptom precisely.

**Fix:** `renderSourceCards()` must reset `_expandedCard = null` at the top.

---

## Bug 4 (Medium): Card Header Click Does Nothing — Only Configure Button Works

### Where
`renderSourceCards()` lines 960–972: only `configBtn` and `closeBtn` have click listeners. The card `div` itself has no click handler.

### The problem
CSS sets `cursor: pointer` on `.source-card` (line 90), implying the entire card is clickable. But clicking the card name, meta line, disk info, or any blank area does nothing. Only the small "Configure" button in the bottom-left triggers expansion.

The user expects to click anywhere on the card to open it (standard card UI pattern). Instead, they must find the exact "Configure" button. Combined with Bug 3 (stale state), this creates the "multiple clicks" perception: the first click lands on the card body (no-op), the second lands on the Configure button (but `_expandedCard` is stale so it collapses), the third click finally expands.

**Fix:** Add a click handler to the card itself:
```js
card.addEventListener('click', function(e) {
    if (!src.disabled) toggleCardExpand(src.id);
});
```
Then ensure the Configure button stops propagation (it already does with `e.stopPropagation()` on line 963) so both work.

---

## Bug 5 (Low): `renderSourceProgress()` Creates a Cancel Button Each Poll Cycle — Potentially Multiple

### Where
`renderSourceProgress()` lines 597–613: creates a Cancel button if `document.getElementById(ids.cancelBtn)` doesn't exist.

### The issue
The guard check is `!document.getElementById(ids.cancelBtn)`. This is correct for the first call. But `renderSourceCards()` nukes the DOM and rebuilds all cards — so the newly-built card has no Cancel button. On the next `fetchAll()` poll, `renderSourceProgress()` creates a new one and appends it. This is fine functionally but means Cancel is only present after the first poll tick following DOM rebuild, creating a ~0–10 second window where Cancel appears to be absent after a rebuild.

---

## Bug 6 (Low): `selectInventorySource()` Uses `source_id` Field That Doesn't Exist

### Where
`selectInventorySource()` lines 2200–2208:
```js
if (_inventorySources[i].source_id === _inventorySelectedSource) { ... }
```

But `loadInventoryData()` stores `data.sources` directly, and `renderInventorySidebar()` iterates over `src.id` (not `src.source_id`). The field is `id`, not `source_id`. So the "zoom to selected source on map" feature is silently broken — `src` is always `null`, bounds are never computed, and the map never zooms.

---

## Root Cause Summary

| Bug | Severity | Symptom |
|-----|----------|---------|
| `renderSourceCards()` called by `fetchCatalog()` on pipeline completion; destroys DOM | Critical | Card collapses without user input |
| `_expandedCard` not reset when DOM is rebuilt | High | Requires multiple clicks to re-open |
| `startPipeline()` collapses card unconditionally before confirming success | High | Card collapses on start click |
| Card body not clickable, only Configure button | Medium | Difficult to open cards, mis-clicks |
| Cancel button absent for ~1 poll cycle after DOM rebuild | Low | Cancel button flash |
| `source_id` vs `id` field mismatch in inventory zoom | Low | Inventory map zoom broken |

---

## Fix Plan

### Fix 1 (Critical): Don't call `renderSourceCards()` from `fetchCatalog()` during a running session

Change `fetchCatalog()` to only update `_catalogData` and then call a **non-destructive** `updateCardDiskInfo()` function that updates disk text in-place:

```js
function fetchCatalog() {
    fetch('/admin/imagery/catalog')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            _catalogData = {};
            (data.sources || []).forEach(function(s) { _catalogData[s.id] = s; });
            updateCardDiskInfo();  // non-destructive update
        })
        .catch(function() {});
}

function updateCardDiskInfo() {
    SOURCE_REGISTRY.forEach(function(src) {
        var diskDiv = document.querySelector('#card-' + src.id + ' .card-disk');
        if (!diskDiv) return;
        if (src.disabled) return;
        if (_catalogData[src.id]) {
            var catEntry = _catalogData[src.id];
            diskDiv.className = 'card-disk';
            var bytes = catEntry.size_bytes || 0;
            var diskText = bytes > 1e9 ? (bytes / 1e9).toFixed(1) + ' GB' : (bytes / 1e6).toFixed(0) + ' MB';
            var totalTiles = (catEntry.zoom_levels || []).reduce(function(s, z) { return s + (z.tile_count || 0); }, 0);
            if (totalTiles) diskText += ' · ' + totalTiles.toLocaleString() + ' tiles';
            diskDiv.textContent = diskText;
        }
    });
}
```

`renderSourceCards()` is called once at startup. After that, only `updateCardDiskInfo()` refreshes disk data.

### Fix 2 (Critical): Reset `_expandedCard` in `renderSourceCards()`

```js
function renderSourceCards() {
    _expandedCard = null;  // add this line
    var grid = document.getElementById('source-card-grid');
    if (!grid) return;
    grid.textContent = '';
    // ...rest unchanged
}
```

### Fix 3 (High): Make `startPipeline()` collapse only on error-free success

```js
cfgFetch('/admin/pipeline/start', { ... }).then(function(resp) {
    if (!resp.ok) return resp.json().then(function(d) { alert(d.detail || 'Start failed'); });
    // Only collapse if start succeeded:
    toggleCardExpand(null);
    fetchAll();
}).catch(function(e) { alert('Start failed: ' + e.message); });
```
This is already the structure — the collapse is in the right place. But consider keeping the card open and showing a "running" state within it instead of collapsing, so the user can see progress inline.

### Fix 4 (Medium): Make entire card clickable

```js
if (!src.disabled) {
    card.addEventListener('click', function() {
        toggleCardExpand(src.id);
    });
    configBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        toggleCardExpand(src.id);
    });
}
```

### Fix 5 (Low): Fix `selectInventorySource()` field name

```js
if (_inventorySources[i].id === _inventorySelectedSource) { ... }
// was: _inventorySources[i].source_id
```
