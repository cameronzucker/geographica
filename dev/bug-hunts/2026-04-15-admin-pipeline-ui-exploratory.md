# Bug Hunt: Admin Pipeline UI Card Grid Event Handling

**Date:** 2026-04-15
**Scope:** `frontend/config/index.html` -- card grid event handling, polling interference, expand/collapse logic
**Method:** Depth-first exploratory code review

---

## Bug 1: Polling destroys expanded card state (CRITICAL)

**Location:** Lines 2248-2250 (init), lines 568-581 (fetchCatalog), lines 1843-1897 (fetchAll), lines 617-621 (renderSourceProgress)

**The problem:** `fetchCatalog()` calls `renderSourceCards()` which does `grid.textContent = ''` (line 847), destroying ALL card DOM elements and rebuilding them from scratch. The expanded card, its body content, all user-entered form values, and all event listeners inside the card body are obliterated.

`fetchCatalog()` is called from two places:
1. **On page load** (line 2248) -- harmless, no card is expanded yet
2. **From `renderSourceProgress()`** (lines 619-621) -- every time a pipeline status comes back as `completed`, `error`, or `cancelled`, it calls `fetchCatalog()`, which rebuilds the grid

But the **real killer** is the indirect path: `fetchAll()` runs every 10 seconds (line 2250). Each `fetchAll()` call fetches pipeline status for imagery, sentinel, naip, import, etc. Each of those responses calls `renderSourceProgress()`. If the pipeline status is `completed`/`error`/`cancelled` (which is the steady-state for most sources), `renderSourceProgress()` calls `fetchCatalog()`, which calls `renderSourceCards()`, which **nukes the entire grid**.

This means: every 10 seconds, if ANY pipeline has a terminal status, the expanded card collapses. The user sees the card body flash open then disappear. Since most pipelines are in a terminal state most of the time, this fires on essentially every poll cycle.

**`_expandedCard` state is stale after rebuild:** After `renderSourceCards()` rebuilds all cards, `_expandedCard` still holds the old source ID, but the new card elements don't have the `expanded` class. The next click on the same card hits the `sourceId === _expandedCard` check in `toggleCardExpand()` (line 991) and treats it as a toggle-off, setting `_expandedCard = null` without ever expanding. So the user must click **twice** to re-expand: once to clear the stale `_expandedCard`, once to actually expand.

**Severity:** Critical. This is the primary cause of "cards collapse without user input" and "require multiple clicks to open."

**Fix:** Either (a) don't call `fetchCatalog()` from `renderSourceProgress()` on every terminal status -- only on *transition* to terminal, or (b) make `renderSourceCards()` preserve expanded state by re-expanding the card after rebuilding, or (c) don't rebuild the entire grid -- update disk info in-place.

---

## Bug 2: Multiple fetchCatalog() calls per poll cycle (HIGH)

**Location:** Lines 1852-1892 (fetchAll pipeline status handlers), lines 617-621 (renderSourceProgress)

**The problem:** `fetchAll()` fetches status for 5 different pipeline types (imagery, sentinel, naip, import, and elevation/osm which use separate renderers). Each imagery/sentinel/naip/import status response calls `renderSourceProgress()`. If 3 of those have terminal status (`completed`/`error`/`cancelled`), `fetchCatalog()` is called 3 times in rapid succession. Each call triggers `renderSourceCards()` which rebuilds the grid 3 times.

These are async fetch calls that resolve at slightly different times, so the grid is being destroyed and rebuilt multiple times within a few hundred milliseconds, causing visible flicker and compounding Bug 1.

**Fix:** Debounce `fetchCatalog()` or track which sources have already triggered it for the current status value.

---

## Bug 3: No click handler on .source-card itself, but CSS implies clickability (MODERATE)

**Location:** Lines 91 (CSS `cursor: pointer`), lines 844-973 (renderSourceCards)

**The problem:** The `.source-card` CSS sets `cursor: pointer` (line 91), signaling to users that the entire card is clickable. But there is NO click handler on the card element itself -- only on the Configure button (line 962) and Close button (line 969). Users clicking the card header, meta text, or disk info get no response, contradicting the cursor affordance.

This isn't a propagation bug per se -- clicking the card body area does nothing because no handler is attached to the card div. But combined with the `cursor: pointer` styling, users naturally click the card and think it's broken when nothing happens.

**The `.expanded` state sets `cursor: default`** (line 105), which is correct for the expanded state, but the non-expanded state misleads users.

**Fix:** Either add a click handler on the card div that calls `toggleCardExpand(src.id)`, or change `cursor: pointer` to `cursor: default` on `.source-card`.

---

## Bug 4: Card-level click handler would conflict with child buttons (LATENT)

**Location:** Lines 960-973 (event handlers)

**The problem:** If Bug 3 is fixed by adding a click handler on the card div, clicks on the Configure button, Close button, and all body elements (inputs, selects, checkboxes, sliders, estimate buttons, start buttons) would bubble up to the card handler and trigger expand/collapse.

Currently, Configure and Close buttons call `e.stopPropagation()` (lines 963, 970), which is correct. But none of the card body content (rendered by `renderDirectBody`, `renderNoaaBody`, etc.) calls `stopPropagation()` on its elements.

If a card-level click handler is added without also adding `stopPropagation()` to the card body container, every click on a form element inside an expanded card would collapse it.

**Fix:** When adding a card-level click handler, also add `e.stopPropagation()` on the `.card-body` element, or check `e.target` to avoid collapsing when clicking inside the body.

---

## Bug 5: Cancel button created outside card body, missing stopPropagation (MODERATE)

**Location:** Lines 597-613 (renderSourceProgress cancel button creation)

**The problem:** When `renderSourceProgress()` dynamically creates a cancel button (lines 600-608), it attaches a click handler that calls `fetch('/admin/pipeline/cancel', { method: 'POST' })` but does NOT call `e.stopPropagation()`. If the card has any parent click handler (or if Bug 3 is fixed), clicking Cancel would also trigger the card toggle.

Additionally, this cancel button is inserted directly into the card element (line 612), NOT into the card body. This means it appears outside the `.card-body` div and is always visible regardless of expand/collapse state -- the CSS rule `.source-card .card-body { display: none }` doesn't hide it.

**Fix:** Add `e.stopPropagation()` to the cancel button handler. Consider inserting it into the card body instead.

---

## Bug 6: renderSourceProgress guard clause too lenient (LOW)

**Location:** Lines 1459-1460 (renderGenericProgress)

**The problem:** `renderGenericProgress()` returns early if progress DOM elements don't exist (line 1460), but it doesn't guard against `startBtn` being null. When a card is collapsed, its body is empty (`prevBody.textContent = ''` at line 985), so the start button created by `renderCardBody()` no longer exists. But progress elements (lines 928-949) are created by `renderSourceCards()` and exist outside the body.

This means `renderGenericProgress()` will execute and try to set `startBtn.style.display` on a null reference when the card is collapsed AND has a running pipeline, causing a silent error (since `startBtn` is guarded with `if (startBtn)` checks at lines 1474, 1504, 1511).

Actually, on closer inspection, the guards are present (`if (startBtn)` at lines 1474, 1504, 1511). This is handled correctly. **Not a bug, but fragile.**

---

## Bug 7: Inventory source selection uses wrong property name (MODERATE)

**Location:** Lines 2199-2209 (selectInventorySource)

**The problem:** At line 2202, the code compares `_inventorySources[i].source_id` but the catalog data uses `.id` (as seen in line 573: `_catalogData[s.id] = s`). The sidebar click handler at line 2089 sets `div.dataset.sourceId = src.id` and the selection toggle at line 2187 uses `sourceId` parameter correctly, but the map zoom logic at line 2202 looks for `.source_id` instead of `.id`.

This means clicking a source in the sidebar toggles its selected visual state correctly, but the map never zooms to the selected source because the property lookup always fails (`src` is always null).

**Fix:** Change `_inventorySources[i].source_id` to `_inventorySources[i].id` on line 2202.

---

## Bug 8: startPipeline collapses card before confirming success (LOW)

**Location:** Lines 1026-1040 (startPipeline)

**The problem:** `startPipeline()` calls `toggleCardExpand(null)` (line 1037) and `fetchAll()` (line 1038) inside the `.then()` handler regardless of whether the start actually succeeded. The success path runs `toggleCardExpand(null)` which collapses the card -- fine. But it does this before checking the response. Looking more carefully: line 1036 checks `!resp.ok` and returns early with an alert, so the success path at line 1037 only runs on actual success. This is correct.

However, on the error path (line 1036), it calls `alert()` and returns, but `fetchAll()` is NOT called, so the UI state doesn't update after a failed start attempt. **Minor issue.**

---

## Summary: Root Cause Chain

The primary user-reported symptoms trace to a single root cause:

1. **10-second polling** (`setInterval(fetchAll, 10000)`) fires
2. `fetchAll()` fetches status for all pipeline types
3. Any pipeline in terminal state (`completed`/`error`/`cancelled`) triggers `renderSourceProgress()` -> `fetchCatalog()`
4. `fetchCatalog()` calls `renderSourceCards()` which does `grid.textContent = ''`
5. All cards are destroyed and rebuilt without the `expanded` class
6. `_expandedCard` still holds the old ID (stale state)
7. User's expanded card visually collapses -- "cards collapse without user input"
8. Next click on the same card hits `sourceId === _expandedCard` and toggles off instead of expanding -- "require multiple clicks to open"
9. Multiple pipeline types in terminal state cause multiple `fetchCatalog()` calls per cycle -- visible flicker

**Priority fixes:**
1. **Bug 1+2:** Stop `renderSourceProgress()` from calling `fetchCatalog()` on every poll for terminal states. Only call on status *transitions*. Or: make `renderSourceCards()` preserve and restore `_expandedCard`.
2. **Bug 7:** Fix `.source_id` -> `.id` in inventory source selection.
3. **Bug 3:** Either add card click handler with proper propagation guards, or remove `cursor: pointer` from `.source-card`.
