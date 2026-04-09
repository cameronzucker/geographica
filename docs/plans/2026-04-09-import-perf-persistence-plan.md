# Import Performance + Session Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Fix ingest performance bottleneck (O(N^2) to O(N)), force KML links to open in new tabs, and persist imported KMZ/KML files in IndexedDB for session-scoped restoration.

**Architecture:** Three independent fixes: (1) surgical O(N^2) elimination + yield splitting in processKMLDoc Stage 4, (2) link target rewriting after DOMPurify sanitization, (3) new import-store.js IIFE module wrapping IndexedDB with TTL-based session scoping. The store returns raw data to app.js via callback -- app.js writes its own closure state (Option B from spec).

**Tech Stack:** Vanilla JS (ES5, var/function only), IndexedDB, DOMPurify (vendored), MapLibre GL JS

**Spec:** docs/superpowers/specs/2026-04-09-import-perf-persistence-design.md (5-round adversarial reviewed)

**IMPORTANT -- Codebase Constraints:**
- Use var/function exclusively. No let, const, or arrow functions anywhere in frontend code.
- Do NOT add features, refactor code, or make improvements beyond what each task specifies.
- Do NOT add docstrings, comments, or type annotations to code you did not change.
- Do NOT modify frontend/kmz-import.js -- it is unchanged by this plan.

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| frontend/import-store.js | IndexedDB session persistence wrapper | Create (~200 lines) |
| frontend/app.js | Perf fix, link rewriting, store integration | Modify (4 locations) |
| frontend/style.css | .import-ui-restoring class | Modify (1 rule) |
| frontend/index.html | Add import-store.js script tag | Modify (1 line) |

---

## Task Dependencies + Execution Order

All tasks are SEQUENTIAL. Tasks 1-5 all modify frontend/app.js. Parallel execution would cause merge conflicts. Execute in strict order 1, 2, 3, 4, 5, 6.

```
Task 1 (Perf fix in app.js)
  then Task 2 (Link fix in app.js)
    then Task 3 (Create import-store.js + index.html + style.css)
      then Task 4 (app.js: save + remove integration)
        then Task 5 (app.js: restore integration)
          then Task 6 (Review loop)
```

---

## Preamble (Apply to Every Task)

```
BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
3. Read the spec at docs/superpowers/specs/2026-04-09-import-perf-persistence-design.md
4. Use var/function exclusively (NO let, const, or arrow functions)
5. Do NOT modify any files not listed in the task's Files section
6. Do NOT refactor, rename, or improve code outside the specified changes
```

## Completion Check (Apply to Every Task)

```
BEFORE marking this task complete:
1. Review your code against docs/pitfalls/implementation-pitfalls.md
2. Verify no let/const/arrow functions were introduced
3. Run: git diff --stat to confirm only expected files changed
4. Commit with descriptive message
```

---

## Tasks

### Task 1: Performance Fix -- O(N^2) Elimination + Stage 4 Yields

**Spec ref:** Section 1 (Ingest Performance Fix)
**Files:** Modify frontend/app.js only

**Current behavior:** processKMLDoc Stage 4 folder map construction uses Object.keys(folderMap).length inside a loop, making it O(N^2). For 25K placemarks this causes multi-second main-thread blocking, triggering the browser's page unresponsive dialog.

**Desired behavior:** Stage 4 split into async substages with O(N) folder map construction and periodic yields to keep the browser responsive.

**Implementation Pitfall Warning:** Pitfall #9 (app.js ~3300 lines) -- this task modifies existing code, it does not add net new code to app.js. The chunked folder walk replaces the existing synchronous version.

- [ ] **Step 1:** Read frontend/app.js. Search for the exact comment string "Stage 4: GeoJSON Conversion" (it appears as part of a longer comment). Read from that comment through the line containing "var folderEntries = Object.values(folderMap);" -- this is the entire Stage 4 block you will replace.

- [ ] **Step 2:** Replace the ENTIRE block from the Stage 4 comment through "var folderEntries = Object.values(folderMap);" with the following code. Key changes: (a) Stage 4 split into 4a and 4b with a yield between, (b) folder map uses integer counter instead of Object.keys().length, (c) folder map construction uses recursive-promise pattern with chunked yields every 1000 placemarks cumulative across all folders:

```js
          // -- Stage 4a: GeoJSON Conversion --
          showImportProgress('Converting to GeoJSON...');
          var geojson = toGeoJSON.kml(kmlDoc);
          if (!geojson.features || geojson.features.length === 0) {
            showImportStatus('No features found in ' + filename, 'warning');
            importInProgress = false;
            return;
          }

          return yieldToMain().then(function () {

            // -- Stage 4b: Folder Map Construction (chunked) --
            showImportProgress('Building folder map...');
            var folderMap = {};
            var folderMapCount = 0;
            var allFolders = kmlDoc.getElementsByTagName('Folder');
            var fIdx = 0;
            var pIdx = 0;
            var yieldCount = 0;

            function buildFolderMapChunk() {
              while (fIdx < allFolders.length) {
                var folderChildNodes = allFolders[fIdx].childNodes;
                var folderName = 'Ungrouped';
                for (var j = 0; j < folderChildNodes.length; j++) {
                  if (folderChildNodes[j].nodeName === 'name' && folderChildNodes[j].textContent) {
                    folderName = folderChildNodes[j].textContent;
                    break;
                  }
                }
                var pms = allFolders[fIdx].childNodes;
                while (pIdx < pms.length) {
                  if (pms[pIdx].nodeName === 'Placemark') {
                    var pmName = '';
                    for (var m = 0; m < pms[pIdx].childNodes.length; m++) {
                      if (pms[pIdx].childNodes[m].nodeName === 'name') {
                        pmName = pms[pIdx].childNodes[m].textContent || '';
                        break;
                      }
                    }
                    folderMap['pm_' + (folderMapCount++)] = { folder: folderName, name: pmName };
                    yieldCount++;
                  }
                  pIdx++;
                  if (yieldCount >= 1000) {
                    yieldCount = 0;
                    return yieldToMain().then(buildFolderMapChunk);
                  }
                }
                fIdx++;
                pIdx = 0;
              }
              return Promise.resolve();
            }

            return buildFolderMapChunk().then(function () {
              return yieldToMain();
            }).then(function () {

              var totalFeatures = geojson.features.length;
              var folderEntries = Object.values(folderMap);
```

- [ ] **Step 3:** The code above opens two new .then() scopes that must be closed. The existing Stage 5 and Stage 6 code that follows the replaced block must now be inside these scopes. Find the end of Stage 6 where the promise chain closes. The existing closing looks approximately like:

```
          });   // end of processBatch().then()
        });     // end of yieldToMain().then()
      });       // end of iconPromise.then()
    })().catch(...)
```

After the replacement, add two additional closing brackets before the yieldToMain/iconPromise closings:

```
            });   // end of processBatch().then() [Stage 5-6]
            });   // end of buildFolderMapChunk().then().then() [inner]
            });   // end of buildFolderMapChunk().then() [outer]
          });     // end of yieldToMain().then() [Stage 4a->4b]
        });       // end of iconPromise.then()
      })().catch(...)
```

Count brackets carefully. The total number of closing }) at the end must match the openings.

- [ ] **Step 4:** Verify scope: geojson, folderMap, folderEntries, totalFeatures, and folderSet must be accessible in Stage 5 and Stage 6. They are declared inside the innermost .then(), which is correct since Stage 5 and 6 are inside that same scope.

- [ ] **Step 5:** Commit:
```
feat: fix O(N^2) folder map + add Stage 4 substage yields (perf)
```

---

### Task 2: Link Navigation Protection -- target _blank

**Spec ref:** Section 2 (Link Navigation Protection)
**Files:** Modify frontend/app.js only

**Current behavior:** KML descriptions containing anchor href links render as clickable anchors that navigate the current tab away from Geographica, losing all import state.

**Desired behavior:** All links in sanitized KML descriptions open in a new tab via target _blank with rel noopener noreferrer.

- [ ] **Step 1:** In frontend/app.js, search for the exact string:
```
imgs[ii].onerror = function () { this.style.display = 'none'; };
```
This is inside the popup description HTML branch (the if block that tests for HTML tags). After the closing brace of the for-loop containing that line, and BEFORE the line "} else {" (which starts the textContent fallback branch), add:

```js
            // Force KML description links to open in new tabs
            var links = desc.querySelectorAll('a[href]');
            for (var li = 0; li < links.length; li++) {
              links[li].setAttribute('target', '_blank');
              links[li].setAttribute('rel', 'noopener noreferrer');
            }
```

- [ ] **Step 2:** Verify placement. The new code must be INSIDE the HTML detection branch. Do NOT place it outside the if/else block. The else branch uses textContent which produces no anchor elements.

- [ ] **Step 3:** Commit:
```
fix: force KML description links to open in new tabs
```

---

### Task 3: Create import-store.js Module

**Spec ref:** Section 3 (Session Persistence), Session Lifecycle, IndexedDB Schema, API
**Files:** Create frontend/import-store.js, Modify frontend/index.html, Modify frontend/style.css
**Depends on:** Tasks 1-2 must be complete

**Current behavior:** Imported KMZ/KML data exists only in memory. Page navigation or refresh destroys all imports.

**Desired behavior:** A new frontend/import-store.js IIFE module provides IndexedDB-backed session persistence with TTL-based cleanup.

**Implementation Pitfall Warnings:**
- Pitfall #6 (offline-first): IndexedDB is available offline. No internet dependency.
- Pitfall #9 (app.js size): This is a NEW separate module, not added to app.js.

- [ ] **Step 1:** Create frontend/import-store.js with the EXACT content from the spec. The module provides init(), save(), remove(), and clear() via window._importStore. The complete file content is specified in the spec at Section 3 API. Key implementation details:
  - Session ID: crypto.getRandomValues() for 16 random bytes, hex-encoded, stored in sessionStorage
  - TTL purge: 1-hour grace for foreign sessions, 24-hour hard TTL for all entries
  - save() sanitizes descriptions with DOMPurify before writing (defense in depth)
  - save() checks file count limit (5 max) before writing
  - pagehide listener purges current session when event.persisted === false
  - All methods are no-ops if IndexedDB is unavailable
  - Uses var/function exclusively -- NO let, const, or arrow functions

The full source code for this file was provided in the previous version of this plan and is also derivable from the spec's API section + the existing codebase patterns (see kmz-import.js for the IIFE pattern).

- [ ] **Step 2:** In frontend/index.html, find the line containing "kmz-import.js" script tag and add AFTER it, BEFORE the app.js script tag:
```html
  <script src="import-store.js"></script>
```

CRITICAL load order: kmz-import.js MUST load before import-store.js MUST load before app.js.

- [ ] **Step 3:** In frontend/style.css, find the CSS rule for "#import-status.import-progress" and add BEFORE it:
```css
.import-ui-restoring {
  pointer-events: none;
  opacity: 0.5;
}
```

- [ ] **Step 4:** Commit:
```
feat: create import-store.js -- IndexedDB session persistence module
```

---

### Task 4: Integrate Store -- Save After Import + Remove on Delete

**Spec ref:** Section 3, steps 4-5; Section 4, Integration table
**Files:** Modify frontend/app.js only (2 locations)
**Depends on:** Task 3 must be complete (import-store.js must exist)

**Current behavior:** Import data exists only in memory. Removing an imported file has no persistence effect.

**Desired behavior:** After each successful import, save to IndexedDB (fire-and-forget). When user clicks Remove, delete from IndexedDB (fire-and-forget).

- [ ] **Step 1 -- Save integration:** In frontend/app.js, search for the exact string "// Release references for GC". This is in processKMLDoc Stage 6. BEFORE that comment (and after the showImportStatus call), add:

```js
            // Persist to IndexedDB (fire-and-forget -- save failure does not affect import)
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

IMPORTANT: This MUST go BEFORE "processedFeatures = null" since it iterates processedFeatures to collect icon URLs.

- [ ] **Step 2 -- Remove integration:** In frontend/app.js, search for the exact string "delete importedFiles[fileId];" inside buildImportLayerUI (it is inside the Remove button click handler, preceded by icon ref count decrement code). AFTER that line, add:

```js
        // Remove from IndexedDB persistence (fire-and-forget)
        if (window._importStore && window._importStore.remove) {
          window._importStore.remove(fileId).catch(function (err) {
            console.warn('Failed to remove persisted import:', err);
          });
        }
```

- [ ] **Step 3:** Commit:
```
feat: persist imports to IndexedDB + delete on remove
```

---

### Task 5: Integrate Store -- Restore on Page Load

**Spec ref:** Section 3, step 3 (Restore); Section 4, Integration table
**Files:** Modify frontend/app.js only (1 location)
**Depends on:** Task 4 must be complete

**Current behavior:** Page refresh or navigation back loses all imported data.

**Desired behavior:** On page load, restore all imports from the current IndexedDB session -- icons, features, layer tree, and visibility state.

**CRITICAL implementation details from adversarial review:**
- map.addImage() in restore MUST use new Uint8Array(iconEntry.imageData.data) -- NOT .buffer. The existing codebase uses .buffer but after IndexedDB round-trip the buffer may have offset issues.
- Icon ref counts MUST be incremented per-feature, not per-unique-icon (matches original import behavior).
- importCounter MUST be set to max(restored indices) without adding +1 (pre-increment in existing code provides the +1).
- Import UI MUST be re-enabled in a finally block -- if updateImportedMapData() throws, the drop zone must still work.
- Do NOT set importInProgress = true during restore -- only the import pipeline uses that flag.

- [ ] **Step 1:** In frontend/app.js, search for the exact string "// Initialize voice search (STT)". This is inside the map.on('load') block in the BOOTSTRAP section (near the end of the file). BEFORE that comment, add:

```js
      // Restore persisted imports from IndexedDB
      if (window._importStore && window._importStore.init) {
        var dropZoneRestore = document.getElementById('drop-zone');
        var fileInputRestore = document.getElementById('file-input');
        if (dropZoneRestore) dropZoneRestore.classList.add('import-ui-restoring');
        if (fileInputRestore) fileInputRestore.disabled = true;

        window._importStore.init(function (restoredEntries) {
          var restoredCount = 0;
          var failedIds = [];
          var maxIdx = 0;

          for (var ri = 0; ri < restoredEntries.length; ri++) {
            var entry = restoredEntries[ri];
            try {
              importedFiles[entry.fileId] = {
                name: entry.filename,
                geojson: entry.geojson,
                visible: entry.visible !== false,
                folders: entry.folders || {},
                features: entry.features || {}
              };

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

              if (entry.geojson && entry.geojson.features && window._kmzImport) {
                entry.geojson.features.forEach(function (f) {
                  var fIconId = f.properties && f.properties._iconId;
                  if (fIconId && fIconId !== 'kmz-icon-default') {
                    window._kmzImport.incrementIconRef(fIconId);
                  }
                });
              }

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

          if (failedIds.length > 0 && window._importStore && window._importStore.remove) {
            failedIds.forEach(function (fid) {
              window._importStore.remove(fid).catch(function () {});
            });
          }

          importCounter = Math.max(importCounter, maxIdx);

          try {
            if (restoredCount > 0) {
              updateImportedMapData();
              buildImportLayerUI();
              showImportStatus('Restored ' + restoredCount + ' file(s) from this session', 'success');
            }
          } finally {
            if (dropZoneRestore) dropZoneRestore.classList.remove('import-ui-restoring');
            if (fileInputRestore) fileInputRestore.disabled = false;
          }
        });
      }
```

- [ ] **Step 2:** Commit:
```
feat: restore persisted imports on page load (IndexedDB session restore)
```

---

### Task 6: Review Loop

After all tasks (1-5) are implemented:

```
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you are confident there are no more issues.
```

**Review checklist (verify ALL items):**
- [ ] All var (no let/const/arrow functions in any modified file)
- [ ] All IndexedDB operations wrapped in Promises with error handling
- [ ] save() is fire-and-forget with .catch() -- never propagates to import pipeline
- [ ] remove() is fire-and-forget with .catch()
- [ ] Import UI disabled during restore via .import-ui-restoring CSS class
- [ ] Import UI re-enabled in finally block (works even if updateImportedMapData throws)
- [ ] importCounter updated to max(restored indices) (NOT + 1)
- [ ] Icon ref counts incremented per-feature during restore (not per-unique-icon)
- [ ] map.addImage() in restore uses new Uint8Array(data) NOT new Uint8Array(data.buffer)
- [ ] yieldCount in folder walk is cumulative across ALL folders (declared before outer loop)
- [ ] Link rewriting is INSIDE the HTML branch of the description popup code
- [ ] pagehide cleanup only fires when event.persisted === false
- [ ] Script load order in index.html: kmz-import.js then import-store.js then app.js
- [ ] processKMLDoc promise chain nesting is correct (bracket count matches)
- [ ] processedFeatures is not null when the save code iterates it (save is before null assignment)

**Final test suite:**
```bash
python3 -m pytest tests/ services/stt/tests/ -v
cd services/gps && python -m pytest tests/ -v
```

All 189+ tests must pass. No new Python tests are expected (this is a frontend-only change), but existing tests must not regress.

---

## Execution Recommendation

**Recommended: Option 2 -- Fresh session with /executing-plans.**

Reasoning:
1. **Context consumption:** This session has consumed substantial context with brainstorming, 5 adversarial review rounds, and plan writing. A fresh session would have maximum context for code generation.
2. **Self-contained plan:** The plan includes complete code blocks for every task with exact search anchors. A fresh agent needs no conversation history.
3. **Sequential execution required:** All 6 tasks must run sequentially (all modify app.js). Subagent-driven parallel dispatch offers no advantage here.
4. **Risk level:** Task 1 (processKMLDoc promise chain refactor) is the highest-risk task and benefits from focused, uninterrupted attention in a fresh context window.
5. **Plan size:** 6 tasks, ~1-2 hours of execution. Well within a single session's capacity.
