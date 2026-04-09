# Import Performance + Session Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix ingest performance bottleneck (O(N^2) → O(N)), force KML links to open in new tabs, and persist imported KMZ/KML files in IndexedDB for session-scoped restoration.

**Architecture:** Three independent fixes: (1) surgical O(N^2) elimination + yield splitting in processKMLDoc Stage 4, (2) link target rewriting after DOMPurify sanitization, (3) new `import-store.js` IIFE module wrapping IndexedDB with TTL-based session scoping. The store returns raw data to app.js via callback — app.js writes its own closure state (Option B from spec).

**Tech Stack:** Vanilla JS (ES5, var/function only), IndexedDB, DOMPurify (vendored), MapLibre GL JS

**Spec:** `docs/superpowers/specs/2026-04-09-import-perf-persistence-design.md` (5-round adversarial reviewed)

**Pitfalls:** Read `docs/pitfalls/implementation-pitfalls.md` and `docs/pitfalls/testing-pitfalls.md` before starting.

**IMPORTANT:** Use `var`/`function` exclusively. No `let`, `const`, or arrow functions anywhere in frontend code.

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `frontend/import-store.js` | IndexedDB session persistence wrapper | Create (~200 lines) |
| `frontend/app.js` | Perf fix, link rewriting, store integration | Modify |
| `frontend/style.css` | `.import-ui-restoring` class | Modify (1 line) |
| `frontend/index.html` | Add import-store.js script tag | Modify |

---

## Task Dependencies

```
Task 1 (Perf: O(N^2) fix + yields) — independent
Task 2 (Link target="_blank") — independent
Task 3 (import-store.js: IndexedDB + session + purge)
  → Task 4 (import-store.js: save with sanitization)
      → Task 5 (import-store.js: remove + pagehide cleanup)
          → Task 6 (app.js: integrate store — save, remove, restore)
              → Task 7 (review loop)
```

Tasks 1 and 2 are independent of each other and of Tasks 3-6. They can run in parallel.

---

## Preamble (Apply to Every Task)

```
BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
3. Read the spec section referenced in each task
4. Use var/function exclusively (NO let, const, or arrow functions)
```

---

## Tasks

### Task 1: Performance Fix — O(N^2) Elimination + Stage 4 Yields

**Spec ref:** Section 1 (Ingest Performance Fix)
**Files:** Modify `frontend/app.js:2273-2301`

- [ ] Replace O(N^2) counter at line 2295. Change:
```js
folderMap['pm_' + Object.keys(folderMap).length] = { folder: folderName, name: pmName };
```
To use an integer counter declared before the outer folder loop:
```js
var folderMapCount = 0;
```
And inside the inner loop:
```js
folderMap['pm_' + (folderMapCount++)] = { folder: folderName, name: pmName };
```

- [ ] Split Stage 4 into substages. After `toGeoJSON.kml(kmlDoc)` at line 2266, add a yield:
```js
          // ── Stage 4a: GeoJSON Conversion ──
          showImportProgress('Converting to GeoJSON...');
          var geojson = toGeoJSON.kml(kmlDoc);
          if (!geojson.features || geojson.features.length === 0) {
            showImportStatus('No features found in ' + filename, 'warning');
            importInProgress = false;
            return;
          }

          return yieldToMain().then(function () {

          // ── Stage 4b: Folder Map Construction ──
          showImportProgress('Building folder map...');
```
Close the new `.then()` wrapper at the end of the folder map block, before Stage 5 setup.

- [ ] Add chunked yielding to the folder map inner loop. Declare `var yieldCount = 0;` before the outer folder loop (at the same scope as `folderMapCount`). Inside the Placemark inner loop, after each placemark is processed:
```js
yieldCount++;
if (yieldCount >= 1000) {
  yieldCount = 0;
  return yieldToMain().then(buildFolderMapContinuation);
}
```
Note: Since this is inside a synchronous for-loop and we need to yield, the folder map construction must be refactored into a recursive-promise pattern (similar to `processBatch` in Stage 5). Convert the nested for-loops into a flattened iterator:
```js
          // ── Stage 4b: Folder Map Construction (chunked) ──
          showImportProgress('Building folder map...');
          var folderMap = {};
          var folderMapCount = 0;
          var folders = kmlDoc.getElementsByTagName('Folder');
          var folderIdx = 0;
          var pmIdx = 0;
          var yieldCount = 0;

          function buildFolderMapChunk() {
            while (folderIdx < folders.length) {
              var folderNameEl = folders[folderIdx].childNodes;
              var folderName = 'Ungrouped';
              for (var j = 0; j < folderNameEl.length; j++) {
                if (folderNameEl[j].nodeName === 'name' && folderNameEl[j].textContent) {
                  folderName = folderNameEl[j].textContent;
                  break;
                }
              }
              var pms = folders[folderIdx].childNodes;
              while (pmIdx < pms.length) {
                if (pms[pmIdx].nodeName === 'Placemark') {
                  var pmName = '';
                  for (var m = 0; m < pms[pmIdx].childNodes.length; m++) {
                    if (pms[pmIdx].childNodes[m].nodeName === 'name') {
                      pmName = pms[pmIdx].childNodes[m].textContent || '';
                      break;
                    }
                  }
                  folderMap['pm_' + (folderMapCount++)] = { folder: folderName, name: pmName };
                  yieldCount++;
                }
                pmIdx++;
                if (yieldCount >= 1000) {
                  yieldCount = 0;
                  return yieldToMain().then(buildFolderMapChunk);
                }
              }
              folderIdx++;
              pmIdx = 0;
            }
            return Promise.resolve();
          }

          return buildFolderMapChunk().then(function () {
            return yieldToMain();
          }).then(function () {
            // Stage 5 setup continues here...
            var totalFeatures = geojson.features.length;
            var folderEntries = Object.values(folderMap);
            // ... rest of existing Stage 5+ code
```

- [ ] Verify the pipeline still works: the Stage 4a → 4b → 5 → 6 promise chain must remain intact. Check that `geojson`, `folderMap`, `folderEntries` variables are accessible in the correct scope.

- [ ] Commit:
```
feat: fix O(N^2) folder map + add Stage 4 substage yields (perf)
```

### Task 2: Link Navigation Protection — target="_blank"

**Spec ref:** Section 2 (Link Navigation Protection)
**Files:** Modify `frontend/app.js:473` (inside the HTML description branch)

- [ ] After the image validation loop (line 473) and before `content.appendChild(desc)` (line 477), inside the HTML branch, add:
```js
            // Force KML description links to open in new tabs
            var links = desc.querySelectorAll('a[href]');
            for (var li = 0; li < links.length; li++) {
              links[li].setAttribute('target', '_blank');
              links[li].setAttribute('rel', 'noopener noreferrer');
            }
```

- [ ] Verify placement: this code must be INSIDE the `if (/<[a-z][\s\S]*>/i.test(props.description))` block, after the `imgs` loop, before `content.appendChild(desc)`.

- [ ] Commit:
```
fix: force KML description links to open in new tabs
```

### Task 3: import-store.js — IndexedDB + Session ID + TTL Purge

**Spec ref:** Section 3 (Session Persistence), Session Lifecycle steps 1-2, IndexedDB Schema, API
**Files:** Create `frontend/import-store.js`, Modify `frontend/index.html`, Modify `frontend/style.css`

- [ ] Create `frontend/import-store.js` with the IIFE skeleton, session ID generation, DB open, and TTL-based purge. Full content:

```js
/* =====================================================================
   Geographica — Import Session Persistence
   =====================================================================
   Wraps IndexedDB for session-scoped persistence of KMZ/KML imports.
   Exposes API via window._importStore for app.js to call.
   ===================================================================== */

(function () {
  'use strict';

  var DB_NAME = 'geographica-imports';
  var DB_VERSION = 1;
  var STORE_NAME = 'imports';
  var SESSION_KEY = 'geographica-session-id';
  var MAX_FILES = 5;
  var STALE_TTL_MS = 60 * 60 * 1000;       // 1 hour — grace window for multi-tab
  var HARD_TTL_MS = 24 * 60 * 60 * 1000;   // 24 hours — guaranteed upper bound

  var db = null;       // IDBDatabase instance (null if unavailable)
  var sessionId = '';  // current session ID

  // ── Session ID ──────────────────────────────────────────────────────

  function getOrCreateSessionId() {
    var existing = sessionStorage.getItem(SESSION_KEY);
    if (existing) return existing;
    var bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    var hex = '';
    for (var i = 0; i < bytes.length; i++) {
      hex += ('0' + bytes[i].toString(16)).slice(-2);
    }
    sessionStorage.setItem(SESSION_KEY, hex);
    return hex;
  }

  // ── Database ────────────────────────────────────────────────────────

  function openDB() {
    return new Promise(function (resolve, reject) {
      if (typeof indexedDB === 'undefined') {
        reject(new Error('IndexedDB not available'));
        return;
      }
      var req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function (e) {
        var database = e.target.result;
        if (!database.objectStoreNames.contains(STORE_NAME)) {
          database.createObjectStore(STORE_NAME, { keyPath: 'fileId' });
        }
      };
      req.onsuccess = function (e) { resolve(e.target.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  // ── TTL Purge ───────────────────────────────────────────────────────

  function purgeStale(database, currentSessionId) {
    return new Promise(function (resolve) {
      var tx = database.transaction(STORE_NAME, 'readwrite');
      var store = tx.objectStore(STORE_NAME);
      var req = store.getAll();
      req.onsuccess = function () {
        var entries = req.result || [];
        var now = Date.now();
        var toDelete = [];
        entries.forEach(function (entry) {
          var age = now - (entry.savedAt || 0);
          // Hard TTL: anything older than 24h
          if (age > HARD_TTL_MS) {
            toDelete.push(entry.fileId);
            return;
          }
          // Stale session: different session ID AND older than 1h
          if (entry.sessionId !== currentSessionId && age > STALE_TTL_MS) {
            toDelete.push(entry.fileId);
          }
        });
        toDelete.forEach(function (fileId) {
          store.delete(fileId);
        });
        tx.oncomplete = function () { resolve(toDelete.length); };
        tx.onerror = function () { resolve(0); };
      };
      req.onerror = function () { resolve(0); };
    });
  }

  // ── Read session entries ────────────────────────────────────────────

  function readSessionEntries(database, currentSessionId) {
    return new Promise(function (resolve) {
      var tx = database.transaction(STORE_NAME, 'readonly');
      var store = tx.objectStore(STORE_NAME);
      var req = store.getAll();
      req.onsuccess = function () {
        var entries = (req.result || []).filter(function (e) {
          return e.sessionId === currentSessionId;
        });
        // Sort by savedAt descending, cap at MAX_FILES
        entries.sort(function (a, b) { return (b.savedAt || 0) - (a.savedAt || 0); });
        if (entries.length > MAX_FILES) {
          var excess = entries.splice(MAX_FILES);
          // Delete excess (fire-and-forget)
          try {
            var dtx = database.transaction(STORE_NAME, 'readwrite');
            var dstore = dtx.objectStore(STORE_NAME);
            excess.forEach(function (e) { dstore.delete(e.fileId); });
          } catch (_) { /* best effort */ }
        }
        resolve(entries);
      };
      req.onerror = function () { resolve([]); };
    });
  }

  // ── Count session entries ───────────────────────────────────────────

  function countSessionEntries(database, currentSessionId) {
    return new Promise(function (resolve) {
      var tx = database.transaction(STORE_NAME, 'readonly');
      var store = tx.objectStore(STORE_NAME);
      var req = store.getAll();
      req.onsuccess = function () {
        var count = (req.result || []).filter(function (e) {
          return e.sessionId === currentSessionId;
        }).length;
        resolve(count);
      };
      req.onerror = function () { resolve(0); };
    });
  }

  // ── Public API ──────────────────────────────────────────────────────

  function init(callback) {
    sessionId = getOrCreateSessionId();
    openDB().then(function (database) {
      db = database;
      return purgeStale(db, sessionId).then(function () {
        return readSessionEntries(db, sessionId);
      });
    }).then(function (entries) {
      callback(entries);
    }).catch(function (err) {
      console.warn('IndexedDB unavailable — import persistence disabled:', err.message);
      db = null;
      callback([]);
    });

    // Best-effort cleanup on page discard
    window.addEventListener('pagehide', function (e) {
      if (e.persisted === false && db) {
        try {
          var tx = db.transaction(STORE_NAME, 'readwrite');
          var store = tx.objectStore(STORE_NAME);
          var req = store.getAll();
          req.onsuccess = function () {
            (req.result || []).forEach(function (entry) {
              if (entry.sessionId === sessionId) {
                store.delete(entry.fileId);
              }
            });
          };
        } catch (_) { /* best effort — page is being destroyed */ }
      }
    });
  }

  function save(fileId, importEntry, iconEntries) {
    if (!db) return Promise.resolve();
    return countSessionEntries(db, sessionId).then(function (count) {
      if (count >= MAX_FILES) {
        return Promise.reject(new Error('Import session full (' + MAX_FILES + ' files). Remove a file to import more.'));
      }

      // Sanitize descriptions before storage (defense in depth)
      var geojsonCopy = importEntry.geojson;
      if (typeof DOMPurify !== 'undefined') {
        geojsonCopy.features.forEach(function (f) {
          if (f.properties && f.properties.description &&
              /<[a-z][\s\S]*>/i.test(f.properties.description)) {
            f.properties.description = DOMPurify.sanitize(f.properties.description);
          }
        });
      } else {
        console.warn('DOMPurify unavailable at save time — skipping pre-storage sanitization');
      }

      var record = {
        sessionId: sessionId,
        fileId: fileId,
        filename: importEntry.name,
        geojson: geojsonCopy,
        iconEntries: iconEntries || [],
        folders: importEntry.folders,
        features: importEntry.features,
        visible: importEntry.visible,
        savedAt: Date.now()
      };

      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE_NAME, 'readwrite');
        var store = tx.objectStore(STORE_NAME);
        store.put(record);
        tx.oncomplete = function () { resolve(); };
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }

  function remove(fileId) {
    if (!db) return Promise.resolve();
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(STORE_NAME, 'readwrite');
      var store = tx.objectStore(STORE_NAME);
      store.delete(fileId);
      tx.oncomplete = function () { resolve(); };
      tx.onerror = function () { reject(tx.error); };
    });
  }

  function clear() {
    if (!db) return Promise.resolve();
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(STORE_NAME, 'readwrite');
      var store = tx.objectStore(STORE_NAME);
      var req = store.getAll();
      req.onsuccess = function () {
        (req.result || []).forEach(function (entry) {
          if (entry.sessionId === sessionId) {
            store.delete(entry.fileId);
          }
        });
        tx.oncomplete = function () { resolve(); };
        tx.onerror = function () { reject(tx.error); };
      };
      req.onerror = function () { reject(req.error); };
    });
  }

  window._importStore = {
    init: init,
    save: save,
    remove: remove,
    clear: clear
  };

})();
```

- [ ] Add script tag to `frontend/index.html`. Between `kmz-import.js` and `app.js`:
```html
  <script src="import-store.js"></script>
```

- [ ] Add CSS class to `frontend/style.css` (after the `.import-ui-restoring` section or near the import styles):
```css
.import-ui-restoring {
  pointer-events: none;
  opacity: 0.5;
}
```

- [ ] Commit:
```
feat: create import-store.js — IndexedDB session persistence module
```

### Task 4: Integrate Store — Save After Import

**Spec ref:** Section 3, step 4 (Save after import); Section 4, Integration table
**Files:** Modify `frontend/app.js:2430-2437` (processKMLDoc Stage 6, after status message)

- [ ] After the status message and before the GC release at line 2433, add the icon entry collection and fire-and-forget save:
```js
            // Persist to IndexedDB (fire-and-forget — save failure does not affect import)
            if (window._importStore && window._importStore.save) {
              var iconEntriesToSave = [];
              var savedIconUrls = {};
              if (window._kmzImport && window._kmzImport.getIconCache) {
                processedFeatures.forEach(function (f) {
                  var url = f.properties._iconUrl;
                  if (url && !savedIconUrls[url] && f.properties._iconId !== 'kmz-icon-default') {
                    var cacheEntry = window._kmzImport.getIconCache().get(url);
                    if (cacheEntry && cacheEntry.imageData) {
                      iconEntriesToSave.push({
                        url: url,
                        iconId: cacheEntry.iconId,
                        imageData: {
                          width: cacheEntry.imageData.width,
                          height: cacheEntry.imageData.height,
                          data: cacheEntry.imageData.data
                        }
                      });
                    }
                    savedIconUrls[url] = true;
                  }
                });
              }
              window._importStore.save(fileId, importedFiles[fileId], iconEntriesToSave)
                .catch(function (err) {
                  console.warn('Import persistence failed:', err);
                  showImportStatus('Imported but not persisted: ' + err.message, 'warning');
                });
            }
```

Note: This must go BEFORE `processedFeatures = null` (line 2436) since we iterate processedFeatures to collect icon URLs.

- [ ] Commit:
```
feat: persist imports to IndexedDB after processing (save integration)
```

### Task 5: Integrate Store — Remove + Cleanup

**Spec ref:** Section 3, steps 5-6; Section 4, Integration table (Remove button)
**Files:** Modify `frontend/app.js:2538-2542` (Remove button handler in buildImportLayerUI)

- [ ] After `delete importedFiles[fileId]` (line 2539), add:
```js
        // Remove from IndexedDB persistence (fire-and-forget)
        if (window._importStore && window._importStore.remove) {
          window._importStore.remove(fileId).catch(function (err) {
            console.warn('Failed to remove persisted import:', err);
          });
        }
```

- [ ] Commit:
```
feat: remove persisted imports on file removal
```

### Task 6: Integrate Store — Restore on Page Load

**Spec ref:** Section 3, step 3 (Restore); Section 4, Integration table (map.on('load'))
**Files:** Modify `frontend/app.js:3334-3346` (bootstrap map.on('load') block)

- [ ] In the existing `map.on('load')` block at line 3334, after `initPositionDetail()` and before the STT init, add the restore call:
```js
      // Restore persisted imports from IndexedDB
      if (window._importStore && window._importStore.init) {
        var dropZone = document.getElementById('drop-zone');
        var fileInput = document.getElementById('file-input');
        // Disable import UI during restore
        if (dropZone) dropZone.classList.add('import-ui-restoring');
        if (fileInput) fileInput.disabled = true;

        window._importStore.init(function (restoredEntries) {
          var restoredCount = 0;
          var failedIds = [];
          var maxIdx = 0;

          for (var ri = 0; ri < restoredEntries.length; ri++) {
            var entry = restoredEntries[ri];
            try {
              // Populate importedFiles
              importedFiles[entry.fileId] = {
                name: entry.filename,
                geojson: entry.geojson,
                visible: entry.visible !== false,
                folders: entry.folders || {},
                features: entry.features || {}
              };

              // Replay icons into cache + map
              if (entry.iconEntries && window._kmzImport) {
                for (var ii = 0; ii < entry.iconEntries.length; ii++) {
                  var iconEntry = entry.iconEntries[ii];
                  try {
                    var imgData = {
                      width: iconEntry.imageData.width,
                      height: iconEntry.imageData.height,
                      data: new Uint8Array(iconEntry.imageData.data)
                    };
                    window._kmzImport.getIconCache().set(iconEntry.url, {
                      iconId: iconEntry.iconId,
                      imageData: imgData
                    });
                    if (!map.hasImage(iconEntry.iconId)) {
                      map.addImage(iconEntry.iconId, imgData);
                    }
                  } catch (iconErr) {
                    console.warn('Failed to restore icon ' + iconEntry.iconId + ':', iconErr);
                  }
                }
              }

              // Increment ref counts per-feature (matches original import behavior)
              if (entry.geojson && entry.geojson.features && window._kmzImport) {
                entry.geojson.features.forEach(function (f) {
                  var iconId = f.properties && f.properties._iconId;
                  if (iconId && iconId !== 'kmz-icon-default') {
                    window._kmzImport.incrementIconRef(iconId);
                  }
                });
              }

              // Track max fileId index
              var parts = entry.fileId.split('_');
              var idx = parseInt(parts[1], 10);
              if (!isNaN(idx) && idx > maxIdx) maxIdx = idx;

              restoredCount++;
            } catch (restoreErr) {
              console.warn('Failed to restore import ' + entry.fileId + ':', restoreErr);
              failedIds.push(entry.fileId);
              delete importedFiles[entry.fileId];
            }
          }

          // Batch-delete failed entries
          if (failedIds.length > 0 && window._importStore && window._importStore.remove) {
            failedIds.forEach(function (fid) {
              window._importStore.remove(fid).catch(function () {});
            });
          }

          // Update importCounter to avoid ID collisions
          importCounter = Math.max(importCounter, maxIdx);

          // Finalize — try/finally ensures UI is always re-enabled
          try {
            if (restoredCount > 0) {
              updateImportedMapData();
              buildImportLayerUI();
              showImportStatus('Restored ' + restoredCount + ' file(s) from this session', 'success');
            }
          } finally {
            // Always re-enable import UI
            if (dropZone) dropZone.classList.remove('import-ui-restoring');
            if (fileInput) fileInput.disabled = false;
          }
        });
      }
```

- [ ] Commit:
```
feat: restore persisted imports on page load (IndexedDB session restore)
```

### Task 7: Review Loop

After all tasks are implemented:

```
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues.
```

**Review checklist:**
- All `var` (no `let`/`const`/arrow functions)
- All IndexedDB operations wrapped in Promises with error handling
- `save()` is fire-and-forget with `.catch()` — never propagates to import pipeline
- `remove()` is fire-and-forget with `.catch()`
- Import UI disabled during restore, re-enabled in `finally` block
- `importCounter` updated to `max(restored indices)` (not `+ 1`)
- Icon ref counts incremented per-feature during restore
- `map.addImage()` uses `new Uint8Array(data)` not `.buffer`
- `yieldCount` in folder walk is cumulative across folders
- Link rewriting is inside HTML branch only
- `pagehide` only fires cleanup when `event.persisted === false`
- Script load order: `kmz-import.js` → `import-store.js` → `app.js`

**Final test suite:**
```bash
python3 -m pytest tests/ services/stt/tests/ -v
cd services/gps && python -m pytest tests/ -v
```

---

## Execution Recommendation

Tasks 1 and 2 are independent and can run in parallel with Tasks 3-6.

Recommended order:
1. Task 1 (perf fix) — highest user impact, tests immediately with real KMZ files
2. Task 2 (link protection) — 5-line change, instant value
3. Tasks 3-6 (persistence) — sequential dependency chain
4. Task 7 (review loop)
