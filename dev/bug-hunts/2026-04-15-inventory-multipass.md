# Bug Hunt Report: Imagery Catalog + Inventory Tab + Delete

## Scope

Analyzed files:
- `services/search/main.py` — catalog (`/admin/imagery/catalog`) and delete (`/admin/imagery/{source_id}`) endpoints
- `scripts/tileserver_config.py` — `remove_mbtiles_from_config()` function
- `frontend/config/index.html` — inventory tab JS (initInventoryMap, loadInventoryData, renderInventoryMap, renderInventorySidebar, delete handler)
- `tests/test_imagery_catalog.py` — test suite
- `docker-compose.yml` — search service config

All five passes completed: contract violations, cross-component patterns, failure modes, concurrency, error propagation.

---

## Bugs

### Bug 1: Field Name Mismatch in Catalog Response — `file_size_bytes` vs `size_bytes`

**Location:** services/search/main.py:772-779 (catalog builder) and frontend/config/index.html:2085 (sidebar renderer)

**Severity:** Critical

**Evidence:**
- Catalog builder returns: `"size_bytes": stat_info.st_size` (line 775)
- Sidebar renderer expects: `src.file_size_bytes` (line 2085, invFormatSize call) and `src.file_size_bytes` (line 2122, delete button)
- Also appears at frontend line 2060 via invSourceColor expecting `src.source_id` but catalog returns `src.id`

**Impact:** The frontend sidebar displays `--` (null) for file sizes because the field names don't match. When user deletes, size display is wrong in confirmation dialog.

**Found in:** Pass 1 — Contract Violations

---

### Bug 2: Field Name Mismatch in Catalog Response — `id` vs `source_id`

**Location:** services/search/main.py:773 (returns `id`) and frontend/config/index.html:2008, 2060, 2066, 2070, 2121 (expects `source_id`)

**Severity:** Critical

**Evidence:**
- Catalog builder returns: `"id": source_id` (line 773)
- Map rendering uses: `src.source_id` (line 2008)
- Sidebar rendering uses: `src.source_id` (line 2060, 2066, 2070, 2121)
- Tests verify: `src["id"]` (test_imagery_catalog.py:40)

**Impact:** Frontend code reads `src.source_id` which is undefined. All color lookups, human names, and delete calls fail silently. The inventory map and sidebar show no sources or broken state.

**Found in:** Pass 1 — Contract Violations

---


### Bug 3: Unsafe Path Handling in Delete Endpoint — Data Dir Symlink Not Validated

**Location:** services/search/main.py:807-813

**Severity:** Significant

**Evidence:**
```python
data_dir = Path(os.environ.get("DATA_DIR", "/data"))
mbt_path = data_dir / f"{source_id}.mbtiles"
if not mbt_path.exists():
    return JSONResponse(status_code=404, ...)
mbt_path.unlink()  # Dangerous: mbt_path could be symlink traversal
```

The regex at line 804 validates `source_id` format (`imagery[a-z0-9_]*`) but does NOT validate that the resolved path stays within `data_dir`. If `DATA_DIR` environment variable is a symlink (common in Docker), and it points outside the intended directory, deletion could affect unintended paths.

**Impact:** If `DATA_DIR=/data` is a symlink to `/srv/geographica/data/../../../` or similar, deleting via frontend could delete unintended files.

**Found in:** Pass 3 — Failure Mode Reasoning

---

### Bug 4: Silent Failure in TileServer Config Removal

**Location:** services/search/main.py:815-821

**Severity:** Significant

**Evidence:**
```python
ts_config_path = os.environ.get("TILESERVER_CONFIG")
if ts_config_path:
    try:
        from tileserver_config import remove_mbtiles_from_config
        remove_mbtiles_from_config(Path(ts_config_path), source_id)
    except Exception:
        pass  # <-- SILENT FAILURE
```

The delete endpoint removes the file AND attempts to unregister it from TileServer config. If the import fails (module not found, file not writable, JSON corruption), the error is silently swallowed. The file is already deleted, but TileServer still thinks it's registered.

**Impact:** User deletes imagery source. File is gone. But TileServer config still references it. Next time TileServer starts or config is reloaded, it fails with "file not found" errors. User sees broken TileServer, but the delete endpoint reported success (200 OK).

**Found in:** Pass 5 — Error Propagation

---

### Bug 5: Race Condition: Catalog Read During Concurrent Delete + Pipeline

**Location:** services/search/main.py:738 (scan), main.py:813 (unlink), frontend index.html:2124 (delete fetch)

**Severity:** Significant

**Evidence:**
- `_build_imagery_catalog()` scans directory via `glob("imagery*.mbtiles")` without locking (line 738)
- `delete_imagery_source()` calls `unlink()` without coordination (line 813)
- Frontend calls delete, then immediately calls `loadInventoryData()` which calls `_build_imagery_catalog()` (line 2126)
- No coordinating lock between these operations

**Impact:** If a pipeline is downloading `imagery_noaa.mbtiles` while user deletes it, or if the pipeline finishes while delete is in progress, race conditions can occur:
  1. Pipeline writes tile, catalog sees file with partial data
  2. Delete removes file, catalog process crashes trying to read it
  3. Frontend shows stale data from catalog cached during the brief window before unlink completed

**Found in:** Pass 4 — Concurrency Reasoning

---

### Bug 6: Delete Endpoint Missing Service-Layer Authorization

**Location:** services/search/main.py:801-802

**Severity:** Minor

**Evidence:**
```python
@app.delete("/admin/imagery/{source_id}")
async def delete_imagery_source(source_id: str):
    # No dependencies=[Depends(require_config_source)]
```

Compare to credential endpoints (lines 995, 1058, 1069, 1079) which all have `dependencies=[Depends(require_config_source)]`.

The delete endpoint is missing the same authorization decorator that other destructive endpoints use.

**Impact:** The endpoint currently relies on NGINX binding (port 8094 only accessible to 127.0.0.1 and Docker gateway) for authorization. However, the service layer doesn't defend itself. If NGINX config changes or if someone calls the search service directly via Docker Compose networking, authorization is bypassed. The catalog endpoint (`/admin/imagery/catalog`) also lacks authorization and is read-only, so this is asymmetric defense.

**Found in:** Pass 5 — Error Propagation

---

### Bug 7: Frontend Delete Button References Wrong Field — `source_id` Instead of `id`

**Location:** frontend/config/index.html:2121

**Severity:** Critical

**Evidence:**
```javascript
var fileName = src.source_id + '.mbtiles';  // src.source_id is undefined
```

The catalog returns `"id"` (line 773 in main.py), not `"source_id"`. So `src.source_id` is always undefined.

**Impact:** Delete button builds filename as `undefined.mbtiles` and sends DELETE request to `/admin/imagery/undefined`. The server rejects it with 404 or 422. User gets "Delete failed: File not found" even though the file exists.

**Found in:** Pass 1 — Contract Violations

---

## Design Concerns

1. **Field Naming Inconsistency:** The catalog builder uses `"id"` but the entire frontend is written expecting `"source_id"`. This isn't a hidden contract — it's exposed in every sidebar click. This should have been caught in integration testing.

2. **Missing Size Field:** Tests verify `size_bytes` exists and is non-zero, but the frontend reads `file_size_bytes`. The test suite is insufficient — it doesn't verify what the frontend actually expects.

3. **Silent Failure Pattern:** The TileServer config removal failure is silently swallowed (line 820). The file is deleted successfully, but the cleanup step fails without the user knowing. This leaves TileServer in an inconsistent state.

4. **No Locking on Destructive Operations:** The delete operation modifies the filesystem without any coordination with concurrent reads (catalog scans) or concurrent pipeline writes. A simple lock (similar to `_pipeline_lock` at line 42) would prevent race conditions.

5. **NGINX-Layer Auth Bypassed:** The delete endpoint relies on NGINX routing to prevent unauthorized access, but the service layer doesn't check the required header. If NGINX config changes or if someone calls the search service directly (via Docker Compose networking), authorization is bypassed.

6. **Broken Inventory Tab on Production:** Due to field mismatches (#1, #2, #7), the inventory tab shows no imagery sources and the delete button is non-functional. The inventory feature was added with the frontend expecting `source_id` and `file_size_bytes`, but the catalog endpoint returns `id` and `size_bytes`. This should have been caught by integration tests or smoke testing of the new inventory tab.

