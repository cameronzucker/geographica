# Bug Hunt Report

## Scope

Files analyzed:
- `services/search/main.py` — `_build_imagery_catalog`, `imagery_catalog`, `delete_imagery_source`
- `scripts/tileserver_config.py` — `remove_mbtiles_from_config`
- `frontend/config/index.html` — `fetchCatalog`, `loadInventoryData`, `renderInventoryMap`, `renderInventorySidebar`, `initInventoryMap`, `selectInventorySource`
- `tests/test_imagery_catalog.py` — test suite for catalog endpoint
- `docker-compose.yml` — search service env, volume mounts
- `nginx/nginx.conf` — proxy routing for `/admin/` paths on both server blocks

Focus: full data flow from disk files → catalog endpoint → NGINX → frontend → MapLibre render.

---

## Bugs

### Bug 1 — Frontend uses `src.source_id` but API returns `src.id` (primary "no inventory" cause)

**Location:** `frontend/config/index.html:2008-2009, 2029, 2060, 2066, 2070, 2085, 2118, 2121-2124, 2136, 2160`
**Severity:** Critical
**Evidence:**
The API (`_build_imagery_catalog`, line 773) builds each source dict with key `"id"`:
```python
results.append({
    "id": source_id,          # <-- key is "id"
    "file": mbt_path.name,
    "size_bytes": stat_info.st_size,
    ...
})
```
The tests confirm this (e.g., `test_imagery_catalog.py:39` asserts `src["id"] == "imagery_noaa"`).

But every access in the inventory tab reads `src.source_id` (which is `undefined`):
- Line 2008: `invSourceColor(src.source_id)` → always gets default color; also `undefined` is passed to color lookup
- Line 2009: `var srcId = 'inv-' + src.source_id;` → MapLibre source/layer ID becomes `"inv-undefined"`
- Line 2029: `selectInventorySource(src.source_id)` → selection key is always `"undefined"`
- Line 2060: `invSourceColor(src.source_id)` — same in `renderInventorySidebar`
- Line 2066: `div.dataset.sourceId = src.source_id;` → all sidebar items get `data-source-id="undefined"`
- Line 2070: `invHumanName(src.source_id)` → name always falls through to default
- Line 2121: `var fileName = src.source_id + '.mbtiles';` → delete confirms "undefined.mbtiles"
- Line 2124: `cfgFetch('/admin/imagery/' + src.source_id, ...)` → sends DELETE to `/admin/imagery/undefined`, which 404s

**Impact:** The inventory sidebar renders every source as if it had `source_id = undefined`. `invComputeUnionBounds` still works because it reads `src.zoom_levels` (correct key), so bounds data flows. MapLibre `addSource('inv-undefined', ...)` is called multiple times — the second source with the same `source_id=undefined` will throw a runtime error ("A source with this ID already exists"), aborting the entire `renderInventoryMap` loop after the first source. Result: at most one map polygon appears, and it is anonymous. The sidebar shows entries with blank names, "undefined" in size strings (`invFormatSize(undefined)` returns `"0 B"`), and clicking "Delete" silently fails with 404. Selection is entirely broken since all elements share `data-source-id="undefined"`.

---

### Bug 2 — Frontend uses `src.file_size_bytes` but API returns `src.size_bytes`

**Location:** `frontend/config/index.html:2085, 2122`
**Severity:** Significant
**Evidence:**
API returns key `"size_bytes"` (main.py line 775). The sidebar renders:
```js
sizeEl.textContent = invFormatSize(src.file_size_bytes) + ' · ' + totalTiles.toLocaleString() + ' tiles';
```
And the delete confirmation:
```js
var sizeStr = invFormatSize(src.file_size_bytes);
```
`src.file_size_bytes` is always `undefined`. `invFormatSize(undefined)` evaluates `undefined >= 1024*1024*1024` which is `false`, walks down the chain, and returns `"0 B"` for every source regardless of actual file size.

**Impact:** Every source shows "0 B" in the size column. The delete confirmation dialog reads "Delete imagery_noaa.mbtiles (0 B)?" — misleading but not blocking. The underlying data is intact; this is a display-only corruption.

---

### Bug 3 — `renderInventoryMap` crashes on second source due to duplicate MapLibre source ID

**Location:** `frontend/config/index.html:2009-2014`
**Severity:** Critical (amplifies Bug 1)
**Evidence:**
Bug 1 causes every source's MapLibre source ID to be `'inv-undefined'`. The first `_inventoryMap.addSource('inv-undefined', ...)` succeeds. The second call with the same ID throws a MapLibre error: "There is already a source with ID 'inv-undefined'". This error is not caught. `sources.forEach` propagates the exception, halting the entire render loop.

**Impact:** With two or more imagery files on disk, only the first one (alphabetically, since `_build_imagery_catalog` sorts the glob results) appears on the map. The remainder are silently dropped. The sidebar still renders all sources (it has a separate loop that doesn't use MapLibre), but the map shows only one polygon.

---

### Bug 4 — `fetchCatalog` (pipelines tab) uses bare `fetch` without `X-Geographica` header, but the catalog endpoint has no auth guard

**Location:** `frontend/config/index.html:568-581`
**Severity:** Minor (not a correctness bug today, but fragile)
**Evidence:**
`fetchCatalog` at line 569 calls `fetch('/admin/imagery/catalog')` directly, without using `cfgFetch`. `cfgFetch` adds `X-Geographica: 1`, which is the CSRF-protection header checked by `require_config_source`. However, `imagery_catalog` (main.py line 784) does NOT have a `dependencies=[Depends(require_config_source)]`, so the missing header doesn't cause a 403 today.

But the inconsistency is structurally fragile: if a future developer adds `require_config_source` to `imagery_catalog` for consistency with other admin endpoints, `fetchCatalog` will silently start getting 403s with no indication of why. Additionally, `fetchCatalog` is served through the `/search/` proxy on the public NGINX server block (line 129: `/search/` → `http://search:8000/`), while the config panel's `/admin/` block is only on port 8094. The catalog fetch at line 569 goes to `/admin/imagery/catalog` on port 8094 (the config panel), which correctly routes through the full admin block (nginx.conf line 207). So routing is correct; the issue is only the missing header in `fetchCatalog` vs all other fetch calls.

**Impact:** None today. The endpoint works. But `fetchCatalog` is the odd one out among all config-panel fetches — every other call uses `cfgFetch`.

---

### Bug 5 — `delete_imagery_source` and `imagery_catalog` both use `DATA_DIR` env var differently from the module-level `DATA_DIR` constant

**Location:** `services/search/main.py:787, 807`
**Severity:** Minor
**Evidence:**
The module defines `DATA_DIR = Path("/data")` at line 32 (hardcoded). But both `imagery_catalog` (line 787) and `delete_imagery_source` (line 807) re-read `DATA_DIR` from env at request time:
```python
data_dir = Path(os.environ.get("DATA_DIR", "/data"))
```
Every other function in main.py uses the module-level `DATA_DIR` constant directly (lines 863, 887, 903, 931, 982, 1024, 1095-1104, 1110-1115, 1146, 1259, 1584, 1635, 1721). The test (`test_imagery_catalog.py:97`) patches `os.environ["DATA_DIR"]` to use `tmp_path`, which only works because these two functions re-read from env — if they used the module constant instead, the test's patch wouldn't take effect.

This is a split-personality data directory: the same process may use `/data` for all pipeline operations but a different directory for catalog reads if `DATA_DIR` env is set. In practice `DATA_DIR` defaults to `/data` in both paths, so they agree in production. But if someone sets `DATA_DIR=/srv/geographica/data` in the container environment, the catalog and delete endpoints would scan a different directory than the pipeline functions write to, producing an empty catalog despite files existing.

**Impact:** With the current docker-compose.yml, `DATA_DIR` is not set in the search service env — so both paths resolve to `/data`. No bug in the deployed configuration, but the inconsistency is a trap.

---

### Bug 6 — `_build_imagery_catalog` is not guarded by `require_config_source` but `delete_imagery_source` is also not guarded

**Location:** `services/search/main.py:784, 801`
**Severity:** Significant (security concern)
**Evidence:**
Neither `imagery_catalog` nor `delete_imagery_source` have `dependencies=[Depends(require_config_source)]`. The DELETE endpoint at `/admin/imagery/{source_id}` can be called by anyone who can reach the search service on port 8096, or through the public NGINX server block's `/search/` prefix (though the path would need to be `/search/admin/imagery/...` to match, which NGINX does proxy to `http://search:8000/admin/imagery/...`).

Checking NGINX: the public server block (port 80/443) has specific allowlist entries for `/admin/status`, `/admin/pipeline/status`, and `/admin/credentials/status` (lines 151-167) — but does NOT have a wildcard `/admin/` block. The `/search/` proxy (line 129) forwards everything under `/search/` to `http://search:8000/`, so a request to `/search/admin/imagery/imagery_noaa` (DELETE) would be forwarded as `/admin/imagery/imagery_noaa` to the search service, which would delete the file with no auth check.

**Impact:** Any user who can reach the public-facing port (port 80/443) and knows the URL structure can delete imagery MBTiles files by issuing a DELETE to `/search/admin/imagery/imagery_noaa`. No credentials required.

---

## Design Concerns

### API field naming contract is not enforced between backend and frontend

The API returns `id` and `size_bytes` but the inventory tab reads `source_id` and `file_size_bytes`. There is no shared schema, TypeScript types, or even a comment linking the two. The tests in `test_imagery_catalog.py` verify backend field names (`src["id"]`, `src["size_bytes"]`) but don't test what the frontend reads. A single test that fetches the catalog and asserts the presence of every field the frontend accesses would have caught Bugs 1 and 2 immediately.

### MapLibre `addSource`/`addLayer` called without existence checks

`renderInventoryMap` removes existing `inv-*` sources by scanning `style.sources` before re-adding. But if any source ID is non-unique (as happens when Bug 1 produces all IDs as `"inv-undefined"`), the removal loop removes only the first one with that ID. Wrapping each `addSource` in a `try/catch` or checking `_inventoryMap.getSource(srcId)` before adding would prevent the crash-on-second-source behavior that amplifies Bug 1.
