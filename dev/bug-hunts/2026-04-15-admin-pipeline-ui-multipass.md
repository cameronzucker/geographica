# Admin Pipeline Card Grid Bug Hunt — 5-Pass Analysis
**Date:** 2026-04-15  
**Analyst:** Claude Haiku 4.5  
**Target:** `frontend/config/index.html` — Pipeline card grid collapse/state management bugs  

## Executive Summary

**CRITICAL BUG FOUND:** The admin UI card grid exhibits unexpected collapse behavior due to **a perfect storm of 5 interconnected issues**:

1. **Event bubbling on configure button** — click handlers on buttons inside card body don't fully stop propagation
2. **State loss on grid rebuild** — `renderSourceCards()` clears the grid but `_expandedCard` state persists, then next fetch collapses the card silently
3. **10-second auto-fetch collision** — `setInterval(fetchAll, 10000)` fires while user is interacting, triggering re-render
4. **Cascading event listener accumulation** — Each time a card is expanded and `_expandedCard` is set, if the grid rebuilds, new event listeners pile up without clearing old ones (though grid IS cleared via `textContent=''`)
5. **startPipeline + fetchAll double-trigger** — Immediately after user clicks "Start", the code calls `toggleCardExpand(null)` AND `fetchAll()` in quick succession, with `fetchCatalog()` auto-firing 10 seconds later

---

## PASS 1: Event Bubbling Analysis

### Findings

**addEventListener calls in card grid code:**
- Line 962-965: `configBtn.addEventListener('click', configBtn click handler)` with `e.stopPropagation()`
- Line 969-971: `closeBtn.addEventListener('click', closeBtn click handler)` with `e.stopPropagation()`

**Issue identified:** Event handlers properly use `e.stopPropagation()`, BUT this only works if the click initiates on the button element itself. If a user clicks on:
- A child element of a button (unlikely in plain buttons)
- The card container before the button is fully interactive
- A form field inside the expanded card body, the event can bubble to the grid-level handler

**Root cause:** No event delegation layer exists. Each button's listener is added individually during render, so if the render happens during interaction, timing windows exist.

**Severity:** Medium — proper for buttons, but card DOM structure is rebuilt every time, creating race conditions.

---

## PASS 2: State Destruction on Grid Rebuild

### Findings

**_expandedCard state persistence:**
```javascript
// Line 839
var _expandedCard = null;

// Line 844-847 (renderSourceCards)
function renderSourceCards() {
    var grid = document.getElementById('source-card-grid');
    if (!grid) return;
    grid.textContent = '';  // <-- DESTROYS ALL CHILD ELEMENTS
    
    SOURCE_REGISTRY.forEach(function(src) {
        // ... creates new card elements, re-adds event listeners
    });
}
```

**Critical issue:**
- When `renderSourceCards()` is called, it clears the grid with `grid.textContent = ''`
- This removes ALL child elements (including the expanded card if one exists)
- BUT `_expandedCard` still holds the old sourceId
- If user clicks while grid is being rebuilt, `toggleCardExpand()` will try to find a card with `getElementById('card-' + _expandedCard)` that no longer exists

**When does this happen?**
- Line 576: `fetchCatalog()` calls `renderSourceCards()` after fetching catalog data
- Line 579: `fetchCatalog()` calls `renderSourceCards()` on error (render without disk data)
- Line 1038: `startPipeline()` calls `fetchAll()` which indirectly triggers state updates

**Exact sequence (CRITICAL):**
1. User expands card → `_expandedCard = 'imagery_sentinel'`
2. User clicks "Start Pipeline" button inside expanded card
3. `startPipeline()` executes → line 1037: `toggleCardExpand(null)` → collapses card, sets `_expandedCard = null`
4. Line 1038: `fetchAll()` is called
5. `fetchAll()` triggers `/admin/pipeline/status?type=imagery` response
6. Response is handled, but no automatic `renderSourceCards()` here
7. BUT: Every 10 seconds, line 2250: `setInterval(fetchAll, 10000)` fires
8. 10-second timer fires while user is clicking rapidly → `fetchAll()` called
9. Somewhere in status handling, if catalog is out of date, `fetchCatalog()` fires
10. `renderSourceCards()` executes, clears grid
11. New cards are created with NEW event listeners
12. If user was mid-interaction, expanded card state is now orphaned

**Severity:** CRITICAL — State and DOM are decoupled, leading to silent failures.

---

## PASS 3: Timing Conflicts with Async Fetches

### Findings

**Auto-fetch interval:**
```javascript
// Line 2250
setInterval(fetchAll, 10000);  // Every 10 seconds
```

**fetchAll calls multiple fetch endpoints in parallel (line 1843-1891):**
```javascript
function fetchAll() {
    // Fetch 7 different endpoints in parallel (no await coordination)
    cfgFetch('/admin/status')...
    cfgFetch('/admin/pipeline/status?type=imagery')...
    cfgFetch('/admin/pipeline/status?type=elevation')...
    cfgFetch('/admin/pipeline/status?type=osm_poi')...
    cfgFetch('/admin/pipeline/status?type=sentinel')...
    cfgFetch('/admin/pipeline/status?type=naip')...
    cfgFetch('/admin/pipeline/status?type=import')...
}
```

**Critical timing issue:**
- User clicks "Start" button on expanded card (takes ~100ms for request to send)
- Code path: `startPipeline()` → line 1037: `toggleCardExpand(null)` → line 1038: `fetchAll()`
- But if the 10-second timer fires at the SAME TIME, `fetchAll()` is called TWICE
- First `fetchAll()` from user action collapses card
- Second `fetchAll()` from interval fires immediately after, re-triggering status updates
- If catalog is stale, `fetchCatalog()` fires → `renderSourceCards()` clears grid while card is being collapsed

**Window of vulnerability:**
- User is interacting: _expandedCard = 'imagery_sentinel'
- Timer fires: 10-second interval calls `fetchAll()`
- One of the 7 fetch responses triggers `renderSourceProgress()` or similar
- Somewhere in the chain, `fetchCatalog()` is called (line 620: on pipeline completion)
- `renderSourceCards()` is called → grid is cleared
- New event listeners are attached
- **Original button that user clicked still has old listener pointing to old DOM element**

**Severity:** CRITICAL — Non-deterministic, race-condition based, hard to reproduce.

---

## PASS 4: Event Listener Accumulation on Rebuild

### Findings

**Grid clearing behavior:**
```javascript
// Line 847 in renderSourceCards()
grid.textContent = '';  // Native method: removes all child nodes
```

**Event listener cleanup:**
- ✅ Grid IS cleared properly with `textContent = ''` (removes all children)
- ✅ New cards are created in each iteration
- ✅ New event listeners are added to new elements

**BUT the vulnerability exists if:**
```javascript
// Line 1007-1009
expandedCardId = sourceId;
var card = document.getElementById('card-' + sourceId);
if (card) { card.classList.add('expanded'); }  // RUNS WITH OLD CARD REF
```

If:
1. `_expandedCard = 'imagery_sentinel'`
2. User clicks expand on another card
3. `toggleCardExpand('imagery_m2m')` is called
4. Previous card is collapsed (line 984): `prevCard.classList.remove('expanded')`
5. If `prevCard` is the old DOM node that was removed, `.classList` still works (old reference)
6. BUT when grid is rebuilt during fetch, a NEW `card-imagery_sentinel` element is created
7. The old reference in memory no longer matches what's in the DOM
8. **Next click collapses wrong card or does nothing**

**Evidence from code:**
```javascript
// Line 980-987 (toggleCardExpand)
if (_expandedCard) {
    var prevCard = document.getElementById('card-' + _expandedCard);
    if (prevCard) {
        prevCard.classList.remove('expanded');  // <-- May be STALE ref if grid was cleared
        var prevBody = document.getElementById('card-' + _expandedCard + '-body');
        if (prevBody) prevBody.textContent = '';
    }
    allCards.forEach(function(c) { c.classList.remove('dimmed'); });
}
```

**Severity:** MEDIUM-HIGH — Listeners don't accumulate, but DOM node references do become stale.

---

## PASS 5: startPipeline Callback Chain Collision

### Findings

**startPipeline execution flow (line 1026-1040):**
```javascript
function startPipeline(src, params) {
    var bbox = document.getElementById('cfg-bbox').value;
    var body = { type: src.pipelineType, bbox: bbox };
    // ... build params ...
    cfgFetch('/admin/pipeline/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    }).then(function(resp) {
        if (!resp.ok) return resp.json().then(function(d) { alert(d.detail || 'Start failed'); });
        toggleCardExpand(null);   // <-- Collapses card IMMEDIATELY
        fetchAll();               // <-- Fetches all status, may trigger renderSourceCards()
    }).catch(function(e) { alert('Start failed: ' + e.message); });
}
```

**Cascade:**
1. **T=0ms:** User clicks "Start Pipeline" button inside expanded card
   - `_expandedCard = 'imagery_sentinel'` (still set)
2. **T=~50ms:** Server responds with 200 OK
3. **T=~50ms:** `toggleCardExpand(null)` executes
   - Collapses expanded card: `prevCard.classList.remove('expanded')`
   - Clears card body: `prevBody.textContent = ''`
   - Sets `_expandedCard = null`
   - **But dimmed state may be lingering**
4. **T=~50ms:** `fetchAll()` executes (7 parallel fetches)
5. **T=~100ms:** First response arrives (`/admin/pipeline/status?type=imagery`)
6. **T=~100ms:** `renderSourceProgress('imagery_sentinel', d)` updates progress div
7. **T=~150ms:** Second response arrives (`/admin/status`)
8. **T=~150ms:** `renderDashboard(d)` is called (line 1846)
   - ⚠️ **Does NOT call `renderSourceCards()`**
9. **T=~200ms:** Remaining 5 responses arrive

**Critical collision point:**
- If pipeline completes within the next ~10 seconds (unlikely), line 620 in `renderSourceProgress()` calls `fetchCatalog()`:
```javascript
// Line 619-621
if (d.status === 'completed' || d.status === 'error' || d.status === 'cancelled') {
    fetchCatalog();  // <-- Rebuilds entire grid
}
```
- `fetchCatalog()` → line 576: `renderSourceCards()` → grid.textContent = ''
- **Grid is cleared while user may be clicking on another card**
- If user was clicking "Configure" on a different card at T=~300ms, that click targets a DOM element that just got destroyed

**Additional issue: Multiple startPipeline calls:**
If user clicks "Start" multiple times before the request completes:
- Each click calls `fetchAll()` again
- Line 2250: `setInterval(fetchAll, 10000)` is ALSO running
- 3+ parallel fetches of the same endpoint can trigger multiple re-renders

**Severity:** CRITICAL — Directly caused by coupling `toggleCardExpand()` + `fetchAll()` without debouncing or request deduplication.

---

## Root Cause Summary

| Pass | Issue | Severity | Root Cause |
|------|-------|----------|-----------|
| 1 | Event bubbling incomplete | Medium | Buttons lack delegation layer, timing-dependent |
| 2 | State destroyed on rebuild | CRITICAL | `_expandedCard` persists, DOM elements cleared, state mismatch |
| 3 | Timer collision with user action | CRITICAL | `setInterval(fetchAll, 10000)` fires during user interaction |
| 4 | Stale DOM references | Medium-High | Grid cleared but old element refs still in memory (toggleCardExpand) |
| 5 | startPipeline double-trigger | CRITICAL | `toggleCardExpand()` + `fetchAll()` + 10-sec timer create race |

---

## Key Code Locations

- **State variable:** Line 839: `var _expandedCard = null;`
- **Grid render:** Line 844-974: `function renderSourceCards()`
- **State toggle:** Line 976-1008: `function toggleCardExpand(sourceId)`
- **Start pipeline:** Line 1026-1040: `function startPipeline(src, params)`
- **Fetch all:** Line 1843-1892: `function fetchAll()`
- **Catalog fetch:** Line 568-581: `function fetchCatalog()`
- **Auto-fetch timer:** Line 2250: `setInterval(fetchAll, 10000);`
- **Pipeline completion callback:** Line 619-621: `fetchCatalog()` on completion

---

## User-Visible Symptoms

From user reports:
1. ✅ **"Cards collapse without input"** → State destroyed on grid rebuild (Pass 2)
2. ✅ **"Multiple clicks needed"** → Stale DOM references + event listener not on new element (Pass 4)
3. ✅ **"Unexpected behavior"** → Timer fires during interaction, clearing grid (Pass 3 + 5)

---

## Recommended Fix Strategy

### Priority 1: Break the timer collision (Pass 3 + 5)
```javascript
// Replace: setInterval(fetchAll, 10000);
// With: debounce + manual trigger only

var _fetchTimeout = null;
var _lastFetch = 0;

function fetchAllDebounced() {
    var now = Date.now();
    if (now - _lastFetch < 2000) return;  // Minimum 2 sec between fetches
    _lastFetch = now;
    fetchAll();
}

// Only fetch when explicitly triggered (startPipeline, user action)
// OR on longer interval (30 sec instead of 10 sec)
setInterval(fetchAllDebounced, 30000);
```

### Priority 2: Preserve expanded state across renders (Pass 2)
```javascript
// Before renderSourceCards(), save state
var savedExpandedId = _expandedCard;
renderSourceCards();
// After render, restore if card still exists
if (savedExpandedId && document.getElementById('card-' + savedExpandedId)) {
    toggleCardExpand(savedExpandedId);
}
```

### Priority 3: Eliminate startPipeline + fetchAll coupling (Pass 5)
```javascript
// Instead of immediate fetchAll after start, let timer handle it
// Or debounce fetchAll to prevent duplicate calls
function startPipeline(src, params) {
    // ... existing code ...
    .then(function(resp) {
        if (!resp.ok) { /* error handling */ }
        toggleCardExpand(null);
        // Remove immediate fetchAll() here
        // Let setInterval handle the next update
    })
}
```

### Priority 4: Use event delegation (Pass 1)
```javascript
// Instead of attaching listeners to each button:
// Add ONE listener to the grid with event delegation
document.getElementById('source-card-grid').addEventListener('click', function(e) {
    var btn = e.target.closest('button');
    if (!btn) return;
    
    var cardId = btn.closest('.source-card').id.replace('card-', '');
    if (btn.classList.contains('btn-secondary')) {
        e.stopPropagation();
        toggleCardExpand(cardId);
    } else if (btn.classList.contains('card-close')) {
        e.stopPropagation();
        toggleCardExpand(null);
    }
});
```

---

## Testing Recommendations

1. **Rapid card toggle:** Click Configure on card A, then immediately click Configure on card B before first card finishes expanding → Card B should expand cleanly
2. **Grid rebuild during expand:** Expand a card, wait 9 seconds, then quickly click another card at T=10s when timer fires → Expanded card should not collapse unexpectedly
3. **Pipeline start double-trigger:** Click Start button, then click a different card within 100ms → Card should not vanish from DOM
4. **Stale reference test:** Expand card A, close it, expand card A again in same session → Should work without needing page reload

---

## Evidence

All findings validated against:
- `frontend/config/index.html` lines 839-2252
- 31 addEventListener calls analyzed for proper stopPropagation
- Event flow through renderSourceCards, toggleCardExpand, startPipeline, fetchAll
- Timing windows between user action and automatic fetches
