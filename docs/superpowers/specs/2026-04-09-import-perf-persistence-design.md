# Import Performance + Session Persistence — Design Spec

**Date:** 2026-04-09
**Status:** Approved
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
- Outer loop: iterate `<Folder>` elements (typically dozens, not thousands — no chunking needed)
- Inner loop: iterate child `<Placemark>` nodes. If the cumulative placemark count exceeds 1,000 since the last yield, call `await yieldToMain()` and reset the counter.

This ensures the browser stays responsive even during the DOM walk phase.

### Expected Impact

The O(N^2) → O(N) fix alone should reduce Stage 4 time by 10-100x for large files. The yields provide insurance against future regressions and maintain browser responsiveness for very large datasets.

### Files Modified

- `frontend/app.js`: `processKMLDoc` Stage 4 rewrite (lines ~2264-2300)

## Section 2: Link Navigation Protection

### Problem

`DOMPurify.sanitize()` preserves `<a href>` tags in KML descriptions by default. The existing popup code (app.js ~line 460) renders sanitized HTML into a `<div>`, but does not modify link behavior. Clicking a link navigates the same tab.

### Fix

After the existing image validation loop in the popup description code, add a link rewriting loop:

```js
var links = desc.querySelectorAll('a[href]');
for (var li = 0; li < links.length; li++) {
  links[li].setAttribute('target', '_blank');
  links[li].setAttribute('rel', 'noopener noreferrer');
}
```

- `target="_blank"` — opens the link in a new tab
- `rel="noopener noreferrer"` — prevents the new tab from accessing `window.opener` (security best practice, prevents reverse tabnapping)

This runs at the same location as the existing `<img>` URL validation walk, keeping all post-sanitization DOM mutations together.

**No `beforeunload` handler.** The session persistence layer (Section 3) is the real safety net for accidental navigation. `beforeunload` is hostile UX.

### Files Modified

- `frontend/app.js`: popup description rendering code (after the `imgs` loop, ~line 473)

## Section 3: Session Persistence via IndexedDB

### Architecture

A new `frontend/import-store.js` IIFE module (~150-200 lines) wrapping IndexedDB, exposing `window._importStore`. Follows the established module pattern of `kmz-import.js`, `stt.js`, `navigation.js`.

### Session Lifecycle

**1. Page load — session initialization:**
- Check `sessionStorage` for an existing session ID key (`geographica-session-id`)
- If present: this is a same-tab navigation or refresh — reuse the ID
- If absent: fresh tab — generate a new ID via `crypto.getRandomValues()` (16 bytes, hex-encoded), store in `sessionStorage`

**2. Purge stale sessions:**
- On load, before restore, open IndexedDB and delete all entries whose `sessionId` does not match the current one
- This is the session-scoping mechanism — `sessionStorage` dies on browser close, so the next browser launch generates a new session ID, and all old entries are purged

**3. Restore current session:**
- Read all IndexedDB entries matching the current session ID
- For each entry:
  - Re-populate `importedFiles[fileId]` with the stored GeoJSON, folder visibility, feature visibility
  - Replay icon images: for each stored `iconEntry`, call `map.addImage()` if not already registered, re-populate `window._kmzImport.getIconCache()` and increment ref counts
  - After all entries restored: call `updateImportedMapData()` + `buildImportLayerUI()` once
- After restoring all entries, update `importCounter` to `max(restored fileId index numbers) + 1` to prevent ID collisions with new imports
- Show brief status: "Restored N file(s) from this session"

**4. Save after import:**
- Called at the end of `processKMLDoc` Stage 6, after finalization
- Before writing, sanitize: iterate all features, run `DOMPurify.sanitize()` on any `description` property that contains HTML. This is defense-in-depth — stored data is pre-sanitized.
- Collect `iconEntries` for this file: iterate the file's features, collect unique `_iconUrl` values, look up each in `_kmzImport.getIconCache()`, serialize the `{url, iconId, imageData}` tuples
- Write to IndexedDB: `{sessionId, fileId, filename, geojson, iconEntries, folders, features, visible, savedAt}`
- If 5 files already stored, reject with status: "Import session full (5 files). Remove a file to import more."

**5. Remove:**
- When the user clicks Remove in the import layer UI, call `_importStore.remove(fileId)` after `delete importedFiles[fileId]`

**6. Cleanup on page discard:**
- Register a `pagehide` event listener
- When `event.persisted === false` (page is being destroyed, not bfcached), purge all IndexedDB entries for the current session
- This minimizes data-at-rest exposure in the browser's profile directory
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
    - `iconEntries` (array) — `[{url, iconId, imageData: {width, height, data}}]` from icon cache for this file's icons
    - `folders` (object) — `{folderName: boolean}` visibility map
    - `features` (object) — `{featureId: boolean}` visibility map
    - `visible` (boolean) — file-level visibility toggle state
    - `savedAt` (number) — `Date.now()` timestamp

### Storage Limits

- **Max files:** 5
- **Max total size:** ~100MB (enforced by file count, not byte measurement — 5 large USMIN files are ~60MB total, well within budget)
- **No LRU eviction.** The user must explicitly Remove a file to make room. This is simpler and more predictable than automatic eviction.

### Security Mitigations

1. **Sanitize before storage.** All `description` fields are run through `DOMPurify.sanitize()` before writing to IndexedDB. Even if a future code path reads from IndexedDB and renders without sanitizing, the stored data is already clean.

2. **Crypto session ID.** `crypto.getRandomValues()` instead of `Date.now() + Math.random()`. Eliminates session ID prediction concerns.

3. **Aggressive cleanup.** Stale sessions purged on load. Current session purged on page discard (`pagehide` with `persisted === false`). Minimizes data-at-rest in the browser's LevelDB profile.

4. **No raw file storage.** Only processed GeoJSON (coordinates + sanitized properties) is persisted. The original KMZ/KML file bytes are never written to IndexedDB.

### Error Handling

- **IndexedDB unavailable** (private browsing in some browsers, or disabled): imports work normally with no persistence. Log `console.warn('IndexedDB unavailable — import persistence disabled')`. All `_importStore` methods become no-ops.
- **Corrupted entry** (can't parse, missing fields): skip it, delete it from IndexedDB, log a warning. Don't block other restores.
- **Storage quota exceeded:** show a warning status message, import still works in memory (just not persisted).
- **Icon replay failure** (image data corrupted): skip the icon, use `kmz-icon-default` fallback. Log warning.

### API

```
window._importStore = {
  init: function(mapRef, callback) { ... }
    // Open DB, purge stale, restore current session
    // callback(restoredCount) called when done

  save: function(fileId, importEntry, iconEntries) { ... }
    // Write one import to IndexedDB (sanitizes descriptions)
    // Returns Promise<void>
    // Rejects if 5 files already stored

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

`frontend/import-store.js` (~150-200 lines) — IIFE module, loaded before `app.js`

### Script Load Order (index.html)

```html
<script src="vendor/dompurify.min.js"></script>
<script src="kmz-import.js"></script>
<script src="import-store.js"></script>  <!-- NEW -->
<script src="app.js"></script>
<script src="navigation.js"></script>
<script src="nav-ui.js"></script>
<script src="stt.js"></script>
```

### app.js Integration

| Location | Change |
|----------|--------|
| `processKMLDoc` Stage 4 | Replace O(N^2) counter with integer, split into 4a/4b substages with yields, chunk folder walk |
| `processKMLDoc` Stage 6 | After finalization, call `_importStore.save(fileId, importedFiles[fileId], iconEntries)` |
| Remove button handler in `buildImportLayerUI` | After `delete importedFiles[fileId]`, call `_importStore.remove(fileId)` |
| `map.on('load')` in bootstrap | After `addPlaceholderSources()`, call `_importStore.init(map, callback)` where callback populates `importedFiles`, calls `updateImportedMapData()` + `buildImportLayerUI()` |
| Popup description code | After img validation loop, add link `target="_blank"` + `rel="noopener noreferrer"` rewriting |

### What Does NOT Change

- `kmz-import.js` — icon cache and ref counting unchanged; store serializes/deserializes cache entries
- Import UI (drop zone, file input) — unchanged
- Layer tree UI — restored imports appear identical to fresh imports
- `frontend/style.css` — no new styles needed

## Testing Strategy

- **Performance:** Import USMIN Nevada KMZ, verify no browser "page unresponsive" dialog, measure Stage 4 time before/after O(N^2) fix
- **Link behavior:** Click a USGS link in an imported feature popup, verify it opens in a new tab
- **Persistence — navigation:** Import a file, click a link or manually navigate away, press back — verify import is restored
- **Persistence — refresh:** Import a file, press F5 — verify import is restored with icons and layer tree
- **Persistence — browser close:** Import a file, close browser, reopen — verify import is NOT restored (session-scoped)
- **Persistence — limit:** Import 5 files, try a 6th — verify rejection message
- **Persistence — remove:** Import a file, click Remove, refresh — verify it's gone
- **Persistence — corrupted data:** Manually corrupt an IndexedDB entry, reload — verify graceful skip
- **Security:** Import a KMZ with malicious description HTML, check IndexedDB contents — verify descriptions are sanitized
- **Fallback:** Disable IndexedDB (private browsing), verify imports work normally without persistence
