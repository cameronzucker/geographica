# Import Performance + Session Persistence — Design Spec

**Date:** 2026-04-09
**Status:** Approved (adversarial-reviewed rounds 1-3, fixes applied)
**Scope:** frontend/app.js ingest performance fix, link navigation protection, IndexedDB session persistence for KMZ/KML imports

## Problem Statement

Two issues discovered during testing with USGS USMIN Nevada KMZ (~25K features, ~15MB KML):

1. **Ingest performance.** The import pipeline hangs at ~step 13/15 long enough for the browser to threaten tab termination. Post-import rendering performance is acceptable. The bottleneck is in Stage 4 of `processKMLDoc` — specifically an O(N^2) folder map construction and the synchronous toGeoJSON conversion with insufficient yields.

2. **Link navigation destroys state.** KML descriptions from USMIN datasets contain `<a href>` links to external USGS database pages. DOMPurify preserves these links. Clicking one navigates the current tab away from Geographica, destroying all in-memory import state. The user must re-import from scratch.

## Section 1: Ingest Performance Fix

### Root Cause

In `processKMLDoc` Stage 4 (app.js), the folder map construction loop uses:
```js
folderMap['pm_' + Object.keys(folderMap).length] = { folder: folderName, name: pmName };
```
`Object.keys(folderMap).length` is called once per Placemark. For N placemarks, this scans all keys N times — O(N^2). At 25K placemarks, that's ~625M key scans. This is the primary bottleneck.

Secondary: the entire Stage 4 block (toGeoJSON conversion + folder map walk) runs synchronously with only one yield before it, giving the browser no opportunity to paint or process input during the heaviest computation phase.

### Fix

**1. Eliminate O(N^2) counter.**

Replace:
```js
folderMap['pm_' + Object.keys(folderMap).length] = { ... };
```
With:
```js
var folderMapCount = 0;
// ... inside loop:
folderMap['pm_' + (folderMapCount++)] = { ... };
```
This single change reduces the folder map construction from O(N^2) to O(N).

**2. Split Stage 4 into substages with yields.**

Current Stage 4 does three things synchronously:
- `toGeoJSON.kml(kmlDoc)` — DOM walk, feature conversion
- Folder map DOM construction — walking `<Folder>` → `<Placemark>` hierarchy
- Setup for Stage 5

Split into:
- **Stage 4a:** `toGeoJSON.kml(kmlDoc)` + `await yieldToMain()`
- **Stage 4b:** Folder map construction + `await yieldToMain()`
- Then proceed to Stage 5

**3. Chunk folder map walk for large files.**

If the KML contains many folders with many placemarks, the DOM walk itself can be slow. Process folder children in batches:
- Declare `var yieldCount = 0` **before** the outer folder loop (not inside it)
- Outer loop: iterate `<Folder>` elements (typically dozens, not thousands — no chunking needed)
- Inner loop: iterate child `<Placemark>` nodes. Increment `yieldCount` for each placemark. If `yieldCount >= 1000`, call `await yieldToMain()` and reset `yieldCount = 0`. The counter is truly cumulative across all folders — do NOT reset it when entering a new folder. This ensures yields fire even when placemarks are spread across many small folders (e.g., USMIN Nevada: ~100 folders × ~250 placemarks each).

This ensures the browser stays responsive even during the DOM walk phase.

### Known Limitation: Folder Index Alignment

The folder map is correlated with toGeoJSON features by positional index — `folderEntries[idx]` maps to `geojson.features[idx]`. This assumes toGeoJSON emits features in the same DOM order as the folder walk. This is an existing assumption in the codebase (not introduced by this spec). Root-level Placemarks (outside any `<Folder>`) are assigned to "Ungrouped" by the existing fallback, which is acceptable.

### Expected Impact

The O(N^2) → O(N) fix alone should reduce Stage 4 time by 10-100x for large files. The yields provide insurance against future regressions and maintain browser responsiveness for very large datasets.

### Files Modified

- `frontend/app.js`: `processKMLDoc` Stage 4 rewrite (lines ~2264-2300)

## Section 2: Link Navigation Protection

### Problem

`DOMPurify.sanitize()` preserves `<a href>` tags in KML descriptions by default. The existing popup code (app.js ~line 460) renders sanitized HTML into a `<div>`, but does not modify link behavior. Clicking a link navigates the same tab.

### Fix

After the existing image validation loop in the popup description code — **inside the HTML branch** (the `if (/<[a-z][\s\S]*>/i.test(props.description))` block, after the `imgs` loop but before `content.appendChild(desc)`) — add a link rewriting loop:

```js
var links = desc.querySelectorAll('a[href]');
for (var li = 0; li < links.length; li++) {
  links[li].setAttribute('target', '_blank');
  links[li].setAttribute('rel', 'noopener noreferrer');
}
```

- `target="_blank"` — opens the link in a new tab
- `rel="noopener noreferrer"` — prevents the new tab from accessing `window.opener` (security best practice, prevents reverse tabnapping)

This must be inside the HTML branch — the `else` branch uses `textContent` which produces no `<a>` elements.

**No `beforeunload` handler.** The session persistence layer (Section 3) is the real safety net for accidental navigation. `beforeunload` is hostile UX.

### Files Modified

- `frontend/app.js`: popup description rendering code (inside the HTML branch, after the `imgs` loop, ~line 473)

## Section 3: Session Persistence via IndexedDB

### Architecture

A new `frontend/import-store.js` IIFE module (~200-250 lines) wrapping IndexedDB, exposing `window._importStore`. Follows the established module pattern of `kmz-import.js`, `stt.js`, `navigation.js`.

### IIFE Boundary Contract

`importedFiles`, `importCounter`, and `importInProgress` are `var` declarations inside app.js's IIFE closure — they are not accessible from `import-store.js`. The design uses **Option B: import-store.js returns raw data, app.js writes its own state.**

- `_importStore.init()` reads IndexedDB and returns restored entries to a callback. The callback runs **inside app.js** (where `importedFiles` and `importCounter` are in scope) and does all state writes.
- `_importStore.save()` receives the data to store as parameters from app.js — it never reads `importedFiles` directly.
- No mutable app.js internals are exported to `window`.

### Session Lifecycle

**1. Page load — session initialization:**
- Check `sessionStorage` for an existing session ID key (`geographica-session-id`)
- If present: this is a same-tab navigation or refresh — reuse the ID
- If absent: fresh tab — generate a new ID via `crypto.getRandomValues()` (16 bytes, hex-encoded), store in `sessionStorage`

**2. Purge stale sessions (TTL-based):**
- On load, before restore, open IndexedDB and delete all entries where **either:**
  - `sessionId` does not match the current one **AND** `savedAt` is older than 1 hour, **OR**
  - `savedAt` is older than 24 hours (regardless of session ID)
- The 1-hour grace window prevents multi-tab data loss: if Tab B opens 30 minutes after Tab A imported data, Tab A's entries survive because they're within the 1-hour window. After 1 hour of no refresh/re-save, they're considered stale.
- The 24-hour hard TTL is the guaranteed upper bound on data-at-rest lifetime. This handles the Chromium "Continue where you left off" edge case where `sessionStorage` survives browser close — even if the session ID persists, entries older than 24h are always purged.
- **Known limitation: only one active tab is fully supported.** If two tabs are open simultaneously, they have independent session IDs and independent IndexedDB entries. Tab B's purge does NOT delete Tab A's recent entries (within 1-hour window), but entries older than 1 hour from other sessions will be cleaned up. This is acceptable for the single-Pi deployment model.

**3. Restore current session:**
- Read all IndexedDB entries matching the current session ID
- Disable the import UI during restore to prevent race conditions with new imports:
  - Set `pointer-events: none` and `opacity: 0.5` on `#drop-zone` and `#file-input`
  - Show "Restoring session..." in `#import-status`
  - CSS class: add `.import-ui-restoring` to the drop zone element
- Return the restored entries to the callback. The callback (running inside app.js IIFE) does:
  - For each entry (wrapped in individual try/catch — a failed entry does not block others):
    - Populate `importedFiles[entry.fileId]` with `{name: entry.filename, geojson: entry.geojson, visible: entry.visible, folders: entry.folders, features: entry.features}`
    - Replay icons — for each item in `entry.iconEntries`, explicitly register with both the cache and the map:
      ```
      var imgData = {
        width: iconEntry.imageData.width,
        height: iconEntry.imageData.height,
        data: new Uint8Array(iconEntry.imageData.data)  // defensive re-wrap
      };
      _kmzImport.getIconCache().set(iconEntry.url, {
        iconId: iconEntry.iconId,
        imageData: imgData
      });
      if (!map.hasImage(iconEntry.iconId)) {
        map.addImage(iconEntry.iconId, imgData);  // explicit — getIconCache().set() does NOT call addImage
      }
      ```
    - Increment ref counts **per feature** (not per unique icon) to match original import behavior: iterate `entry.geojson.features`, call `_kmzImport.incrementIconRef(f.properties._iconId)` for each feature with a non-default icon
    - On try/catch failure: log warning, mark entry for deletion from IndexedDB, continue to next entry
  - After all entries processed: batch-delete any marked-for-deletion entries in a single IndexedDB transaction, then check count
  - Update `importCounter`: parse each restored fileId safely (`var idx = parseInt(fileId.split('_')[1], 10); if (isNaN(idx)) skip`), set `importCounter = Math.max(importCounter, maxIdx)`. The pre-increment in the original code (`++importCounter`) provides the +1.
  - If restored count > 5, keep only the 5 most recent (by `savedAt`), delete the rest
  - Call `updateImportedMapData()` + `buildImportLayerUI()` once
  - Re-enable the import UI (remove `.import-ui-restoring`, reset opacity/pointer-events). **This must happen in a finally-equivalent block** — if `updateImportedMapData()` or `buildImportLayerUI()` throws, the UI must still be re-enabled. Wrap the post-loop finalization in try/finally.
- Show brief status: "Restored N file(s) from this session"

**4. Save after import:**
- Called at the end of `processKMLDoc` Stage 6, after finalization
- **Fire-and-forget with its own .catch()** — save failure must NOT propagate to the import pipeline's error handler. The import succeeded; only persistence failed.

```js
_importStore.save(fileId, importedFiles[fileId], iconEntries)
  .catch(function(err) {
    console.warn('Import persistence failed:', err);
    showImportStatus('Imported but not persisted: ' + err.message, 'warning');
  });
```

- Before writing, sanitize descriptions: iterate all features, if `description` contains HTML, replace it with `DOMPurify.sanitize(description)`. Since JS strings are immutable, this creates a new string reference — the in-memory feature's description is now sanitized too, which is intentional (defense in depth, and the popup already sanitizes at render time). If DOMPurify is unavailable, skip sanitization and log a warning (low risk — data is from the current session).
- **Collect `iconEntries`:** iterate the file's features, collect unique `_iconUrl` values (skip empty and `kmz-icon-default`), look up each in `_kmzImport.getIconCache()`, build array of `{url, iconId, imageData: {width, height, data}}`. The `data` field is a `Uint8Array` — IndexedDB structured clone supports this natively.
- **Single transaction:** Each `save()` writes one IndexedDB record in one `readwrite` transaction. IndexedDB transactions are atomic — a quota failure rolls back cleanly with no partial state.
- Write to IndexedDB: `{sessionId, fileId, filename, geojson, iconEntries, folders, features, visible, savedAt}`
- If 5 files already stored for this session, reject with status message. The `.catch()` at the call site handles this gracefully.

**5. Remove:**
- When the user clicks Remove in the import layer UI, call `_importStore.remove(fileId)` after `delete importedFiles[fileId]`
- Fire-and-forget with `.catch()` logging: `_importStore.remove(fileId).catch(function(err) { console.warn('Failed to remove persisted import:', err); });`
- If remove fails, the entry reappears on next refresh — acceptable minor UX glitch.

**6. Cleanup on page discard (best-effort):**
- Register a `pagehide` event listener
- When `event.persisted === false` (page is being destroyed, not bfcached), purge all IndexedDB entries for the current session
- This is **best-effort, not guaranteed.** Browser crashes, OOM kills, and power loss will not fire this event. The async IndexedDB delete may not complete before the page is destroyed. The TTL-based purge on next load (step 2) is the reliable cleanup mechanism.
- **Important:** `visibilitychange` → `hidden` must NOT trigger cleanup (mobile browsers fire this when switching tabs). Only `pagehide` with `persisted === false` qualifies.

### IndexedDB Schema

- **Database name:** `geographica-imports`
- **Version:** 1
- **Object store:** `imports`
  - **keyPath:** `fileId`
  - **Fields:**
    - `sessionId` (string) — crypto-random hex, matches `sessionStorage` key
    - `fileId` (string) — e.g., `import_3`
    - `filename` (string) — original filename for display
    - `geojson` (object) — FeatureCollection with pre-sanitized descriptions
    - `iconEntries` (array) — `[{url, iconId, imageData: {width, height, data: Uint8Array}}]` — Uint8Array is preserved by IndexedDB structured clone
    - `folders` (object) — `{folderName: boolean}` visibility map
    - `features` (object) — `{featureId: boolean}` visibility map
    - `visible` (boolean) — file-level visibility toggle state
    - `savedAt` (number) — `Date.now()` timestamp

### Storage Limits

- **Max files:** 5 per session
- **Max total size:** ~100MB (enforced by file count, not byte measurement — 5 large USMIN files are ~60MB total, well within budget)
- **No LRU eviction.** The user must explicitly Remove a file to make room. This is simpler and more predictable than automatic eviction.
- **Restore cap:** If >5 entries are found during restore (manual IndexedDB manipulation), keep only the 5 most recent by `savedAt`, delete the rest.

### Security Mitigations

1. **Sanitize before storage.** All `description` fields are run through `DOMPurify.sanitize()` before writing to IndexedDB. Even if a future code path reads from IndexedDB and renders without sanitizing, the stored data is already clean. If DOMPurify is unavailable at save time, skip sanitization and log a warning.

2. **Crypto session ID.** `crypto.getRandomValues()` instead of `Date.now() + Math.random()`. Eliminates session ID prediction concerns.

3. **TTL-based cleanup.** 1-hour stale purge for other sessions, 24-hour hard TTL for all entries. Best-effort `pagehide` cleanup. Minimizes data-at-rest in the browser's LevelDB profile.

4. **No raw file storage.** Only processed GeoJSON (coordinates + sanitized properties) is persisted. The original KMZ/KML file bytes are never written to IndexedDB.

### Error Handling

- **IndexedDB unavailable** (private browsing in some browsers, or disabled): imports work normally with no persistence. Log `console.warn('IndexedDB unavailable — import persistence disabled')`. All `_importStore` methods become no-ops (save/remove/clear return resolved Promises, init calls callback with 0).
- **Corrupted entry** (can't parse, missing fields, icon addImage throws): skip it, delete it from IndexedDB (fire-and-forget), log a warning. Continue restoring other entries. Restore iterates entries in a for-loop with individual try/catch around each entry's full restoration (state + icons + ref counts).
- **Storage quota exceeded:** save()'s `.catch()` at the call site shows a warning. Import still works in memory.
- **Icon replay failure** (imageData corrupted, `map.addImage()` throws): catch the error, set affected features' `_iconId` to `'kmz-icon-default'`. Log warning. Do not abort restore.
- **Clock skew:** If the system clock moves backward (e.g., Pi RTC battery dies), TTL comparisons may produce nonsensical results. This is out of scope — rely on OS/Pi network time sync. The 24-hour hard TTL is a conservative backstop.

### API

```
window._importStore = {
  init: function(callback) { ... }
    // Open DB, purge stale (TTL-based), read current session entries
    // No mapRef parameter — under Option B, import-store.js never touches the map.
    // callback(restoredEntries) where each entry has this shape:
    //   {
    //     fileId: string,          // e.g., 'import_3'
    //     filename: string,        // original filename for display
    //     geojson: Object,         // FeatureCollection with pre-sanitized descriptions
    //     iconEntries: Array,      // [{url, iconId, imageData: {width, height, data: Uint8Array}}]
    //     folders: Object,         // {folderName: boolean} visibility map
    //     features: Object,        // {featureId: boolean} visibility map
    //     visible: boolean         // file-level visibility toggle state
    //   }
    // The callback is defined INSIDE app.js's IIFE, so it closes over
    // importedFiles, importCounter, map, etc. import-store.js never sees
    // those variables — it only invokes the callback with data.
    // If IndexedDB unavailable, calls callback([]) immediately

  save: function(fileId, importEntry, iconEntries) { ... }
    // importEntry is importedFiles[fileId]: {name, geojson, visible, folders, features}
    // iconEntries is [{url, iconId, imageData: {width, height, data: Uint8Array}}]
    // Sanitizes descriptions, writes single IndexedDB transaction
    // Returns Promise<void>
    // Rejects if 5 files already stored for this session

  remove: function(fileId) { ... }
    // Delete one entry from IndexedDB
    // Returns Promise<void>

  clear: function() { ... }
    // Purge all entries for current session
    // Returns Promise<void>
}
```

All methods are safe to call even if IndexedDB is unavailable (no-ops).

## Section 4: Integration Points

### New File

`frontend/import-store.js` (~200-250 lines) — IIFE module, loaded before `app.js`

### Script Load Order (index.html)

DOMPurify stays in `<head>` where it currently is. The new script is added to the `<body>` script block.

**CRITICAL load order:** `kmz-import.js` MUST load before `import-store.js`. The restore callback uses `_kmzImport.getIconCache()` and `_kmzImport.incrementIconRef()`. If load order is reversed, icon restore fails silently.

```html
<!-- In <head> (already exists): -->
<script src="vendor/dompurify.min.js"></script>

<!-- In <body>, before app.js: -->
<script src="kmz-import.js"></script>
<script src="import-store.js"></script>  <!-- NEW — MUST be after kmz-import.js -->
<script src="app.js"></script>
<script src="navigation.js"></script>
<script src="nav-ui.js"></script>
<script src="stt.js"></script>
```

### app.js Integration

| Location | Change |
|----------|--------|
| `processKMLDoc` Stage 4 | Replace O(N^2) counter with integer, split into 4a/4b substages with yields, chunk folder walk |
| `processKMLDoc` Stage 6 | After finalization, fire-and-forget `_importStore.save(fileId, importedFiles[fileId], iconEntries).catch(...)` |
| Remove button handler in `buildImportLayerUI` | After `delete importedFiles[fileId]`, fire-and-forget `_importStore.remove(fileId).catch(...)` |
| `map.on('load')` in bootstrap (the existing block at ~line 3334, NOT a new registration) | After `addPlaceholderSources()` has run (it runs in the first `map.on('load')` from `initMap`), call `_importStore.init(callback)`. Callback: disable import UI, iterate restored entries in try/catch per-entry, populate importedFiles, replay icons (cache + map.addImage), increment ref counts per-feature, update importCounter, call `updateImportedMapData()` + `buildImportLayerUI()`. **Always re-enable import UI** — use try/finally or equivalent pattern so the UI is re-enabled even if updateImportedMapData/buildImportLayerUI throws. |
| Popup description code | Inside the HTML branch, after img validation loop, add link `target="_blank"` + `rel="noopener noreferrer"` rewriting |

### What Does NOT Change

- `kmz-import.js` — icon cache and ref counting unchanged; the restore code uses the existing `getIconCache().set()` (live Map reference) and `incrementIconRef()` methods
- Import UI (drop zone, file input) — unchanged (temporarily disabled during restore)
- Layer tree UI — restored imports appear identical to fresh imports
- `frontend/style.css` — one new class: `.import-ui-restoring { pointer-events: none; opacity: 0.5; }`

## Testing Strategy

- **Performance:** Import USMIN Nevada KMZ, verify no browser "page unresponsive" dialog, measure Stage 4 time before/after O(N^2) fix
- **Link behavior:** Click a USGS link in an imported feature popup, verify it opens in a new tab
- **Persistence — navigation:** Import a file, click a link or manually navigate away, press back — verify import is restored
- **Persistence — refresh:** Import a file, press F5 — verify import is restored with icons and layer tree
- **Persistence — browser close:** Import a file, close browser (without "Continue where you left off"), reopen — verify import is NOT restored
- **Persistence — TTL:** Import a file, wait >24h (or manually set savedAt to old timestamp), reload — verify entry is purged
- **Persistence — multi-tab:** Open Tab A, import file. Open Tab B within 1 hour — verify Tab A's data survives Tab B's purge
- **Persistence — limit:** Import 5 files, try a 6th — verify rejection message
- **Persistence — remove:** Import a file, click Remove, refresh — verify it's gone
- **Persistence — corrupted data:** Manually corrupt an IndexedDB entry, reload — verify graceful skip, other entries still restore
- **Persistence — race condition:** Verify import UI is disabled during restore, re-enabled after
- **Security:** Import a KMZ with malicious description HTML, check IndexedDB contents — verify descriptions are sanitized
- **Fallback:** Disable IndexedDB (private browsing), verify imports work normally without persistence
- **Save failure:** Fill IndexedDB to quota, import a file — verify import succeeds with "not persisted" warning
