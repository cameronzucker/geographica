# Imagery Inventory Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Inventory tab to the admin panel showing a MapLibre map with per-source coverage rectangles, a sidebar with source details, and per-source delete capability.

**Architecture:** Three components: (1) backend delete endpoint + tileserver config removal helper, (2) frontend Inventory tab with map + sidebar, (3) tests. Backend tasks are independent and can run in parallel. Frontend depends on the backend endpoints.

**Tech Stack:** Python (FastAPI, SQLite), Vanilla JS, MapLibre GL JS, CSS

**Spec:** `docs/superpowers/specs/2026-04-15-imagery-inventory-manager-design.md`

---

## File Map

| File | Role | Tasks |
|------|------|-------|
| `scripts/tileserver_config.py` | Add `remove_mbtiles_from_config()` | 1 |
| `tests/test_tileserver_config.py` | Tests for remove function | 1 |
| `services/search/main.py` | Add `DELETE /admin/imagery/{source_id}` endpoint | 2 |
| `tests/test_imagery_catalog.py` | Tests for delete endpoint | 2 |
| `frontend/config/index.html` | Inventory tab HTML + CSS + JS | 3 |

**Cross-task dependencies:** Tasks 1 and 2 can run in parallel (different files). Task 3 depends on Tasks 1+2 (uses the delete endpoint).

---

## Task 1: tileserver_config.py — Remove Function

**Files:**
- Modify: `scripts/tileserver_config.py` (add `remove_mbtiles_from_config`)
- Modify: `tests/test_tileserver_config.py` (add tests)

BEFORE starting work:
1. Read `scripts/tileserver_config.py` — understand the existing `add_mbtiles_to_config` function
2. Read `tests/test_tileserver_config.py` — understand existing test patterns
3. Read `dev/testing-pitfalls.md`
Follow TDD: write failing test -> implement fix -> verify green.

**Context:** `tileserver_config.py` has one function: `add_mbtiles_to_config(config_path, name, mbtiles_path)` which adds a data source entry to TileServer's config.json using atomic file writes (tmp + fsync + os.replace). We need the inverse: `remove_mbtiles_from_config(config_path, name)`.

- [ ] **Step 1: Write tests for remove function**

Add to `tests/test_tileserver_config.py`:

```python
class TestRemoveMbtilesFromConfig:
    def test_removes_existing_source(self, tmp_path):
        from tileserver_config import add_mbtiles_to_config, remove_mbtiles_from_config
        config = tmp_path / "config.json"
        config.write_text('{"data": {"imagery_noaa": {"mbtiles": "/srv/data/imagery_noaa.mbtiles"}}}')
        result = remove_mbtiles_from_config(config, "imagery_noaa")
        assert result is True
        import json
        data = json.loads(config.read_text())
        assert "imagery_noaa" not in data["data"]

    def test_returns_false_if_not_present(self, tmp_path):
        from tileserver_config import remove_mbtiles_from_config
        config = tmp_path / "config.json"
        config.write_text('{"data": {"imagery": {"mbtiles": "imagery.mbtiles"}}}')
        result = remove_mbtiles_from_config(config, "imagery_noaa")
        assert result is False

    def test_preserves_other_sources(self, tmp_path):
        from tileserver_config import remove_mbtiles_from_config
        config = tmp_path / "config.json"
        config.write_text('{"data": {"imagery": {"mbtiles": "a.mbtiles"}, "imagery_noaa": {"mbtiles": "b.mbtiles"}}, "styles": {}}')
        remove_mbtiles_from_config(config, "imagery_noaa")
        import json
        data = json.loads(config.read_text())
        assert "imagery" in data["data"]
        assert "styles" in data

    def test_handles_empty_data_section(self, tmp_path):
        from tileserver_config import remove_mbtiles_from_config
        config = tmp_path / "config.json"
        config.write_text('{"data": {}}')
        result = remove_mbtiles_from_config(config, "imagery_noaa")
        assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_tileserver_config.py::TestRemoveMbtilesFromConfig -v`
Expected: ImportError — `remove_mbtiles_from_config` doesn't exist yet.

- [ ] **Step 3: Implement remove_mbtiles_from_config**

Add to `scripts/tileserver_config.py` after the existing `add_mbtiles_to_config` function:

```python
def remove_mbtiles_from_config(config_path: Path, name: str) -> bool:
    """Remove an MBTiles entry from TileServer config.json.

    Args:
        config_path: Path to tileserver/config.json
        name: Data source name to remove (e.g., "imagery_noaa")

    Returns:
        True if entry was removed, False if it wasn't present (idempotent).
    """
    config = json.loads(config_path.read_text())

    if name not in config.get("data", {}):
        return False

    del config["data"][name]

    tmp_path = config_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp_path), str(config_path))

    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tileserver_config.py -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/tileserver_config.py tests/test_tileserver_config.py
git commit -m "feat: add remove_mbtiles_from_config to tileserver config helper"
```

BEFORE marking this task complete:
1. Review tests against `docs/pitfalls/testing-pitfalls.md`
2. Verify idempotency is tested (remove something not present)
3. Run tests and confirm green

---

## Task 2: Delete Imagery Endpoint

**Files:**
- Modify: `services/search/main.py` (add DELETE endpoint)
- Modify: `tests/test_imagery_catalog.py` (add delete tests)

BEFORE starting work:
1. Read `services/search/main.py` — find the existing `_build_imagery_catalog` and `imagery_catalog` functions, understand the admin endpoint patterns
2. Read `scripts/tileserver_config.py` — understand both add and remove functions
3. Read `tests/test_imagery_catalog.py` — understand existing test patterns and the `_create_test_mbtiles` helper
4. Read `dev/testing-pitfalls.md`
Follow TDD: write failing test -> implement fix -> verify green.

**Context:** The admin panel needs to delete imagery MBTiles files. The endpoint validates the source_id (security), deletes the file, then removes it from TileServer config. Order matters: delete file first so if it fails, config is unchanged.

**WARNING:** `source_id` must be validated against `^imagery[a-z0-9_]*$` to prevent path traversal. Do NOT allow hyphens, slashes, dots, or any path separator characters.

**WARNING:** `log` is NOT defined in `services/search/main.py`. Use `print()` for diagnostics.

- [ ] **Step 1: Write tests for delete endpoint**

Add to `tests/test_imagery_catalog.py`:

```python
import re

class TestDeleteImageryEndpoint:
    def test_delete_existing_source(self, tmp_path):
        """DELETE /admin/imagery/{id} removes file and returns success."""
        _create_test_mbtiles(tmp_path / "imagery_noaa.mbtiles", [(18, 1, 1)])
        assert (tmp_path / "imagery_noaa.mbtiles").exists()

        with patch.dict("os.environ", {"DATA_DIR": str(tmp_path)}):
            from main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            resp = client.delete("/admin/imagery/imagery_noaa")

        assert resp.status_code == 200
        assert resp.json()["deleted"] == "imagery_noaa"
        assert not (tmp_path / "imagery_noaa.mbtiles").exists()

    def test_delete_nonexistent_returns_404(self, tmp_path):
        with patch.dict("os.environ", {"DATA_DIR": str(tmp_path)}):
            from main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            resp = client.delete("/admin/imagery/imagery_noaa")
        assert resp.status_code == 404

    def test_delete_rejects_path_traversal(self, tmp_path):
        with patch.dict("os.environ", {"DATA_DIR": str(tmp_path)}):
            from main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            resp = client.delete("/admin/imagery/../../etc/passwd")
        assert resp.status_code == 422

    def test_delete_rejects_non_imagery_id(self, tmp_path):
        with patch.dict("os.environ", {"DATA_DIR": str(tmp_path)}):
            from main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            resp = client.delete("/admin/imagery/elevation")
        assert resp.status_code == 422

    def test_delete_accepts_base_imagery(self, tmp_path):
        """The base 'imagery' source (no suffix) should be deletable."""
        _create_test_mbtiles(tmp_path / "imagery.mbtiles", [(14, 1, 1)])
        with patch.dict("os.environ", {"DATA_DIR": str(tmp_path)}):
            from main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            resp = client.delete("/admin/imagery/imagery")
        assert resp.status_code == 200
        assert not (tmp_path / "imagery.mbtiles").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_imagery_catalog.py::TestDeleteImageryEndpoint -v`
Expected: 405 Method Not Allowed or 404 — endpoint doesn't exist yet.

- [ ] **Step 3: Implement the delete endpoint**

Add to `services/search/main.py` after the `imagery_catalog` endpoint:

```python
import re as _re

@app.delete("/admin/imagery/{source_id}")
async def delete_imagery_source(source_id: str):
    """Delete an imagery MBTiles file and unregister from TileServer."""
    # Security: validate source_id format
    if not _re.match(r'^imagery[a-z0-9_]*$', source_id):
        raise HTTPException(status_code=422, detail=f"Invalid source ID: {source_id}")

    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    mbtiles_path = data_dir / f"{source_id}.mbtiles"

    if not mbtiles_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {source_id}.mbtiles")

    # Delete file first — if this fails, config is unchanged
    try:
        mbtiles_path.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {exc}")

    # Remove from TileServer config (best-effort)
    ts_config_path = os.environ.get("TILESERVER_CONFIG")
    if ts_config_path:
        try:
            from tileserver_config import remove_mbtiles_from_config
            remove_mbtiles_from_config(Path(ts_config_path), source_id)
        except Exception:
            pass  # Config update is best-effort

    return {"deleted": source_id, "file": f"{source_id}.mbtiles"}
```

**Note:** `re` may already be imported. Check — if so, use it directly instead of `import re as _re`. `HTTPException`, `Path`, `os` are already imported.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_imagery_catalog.py -v`
Expected: All tests pass.

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: 487+ tests pass, 9 pre-existing errors.

- [ ] **Step 6: Commit**

```bash
git add services/search/main.py tests/test_imagery_catalog.py
git commit -m "feat: add DELETE /admin/imagery/{source_id} endpoint"
```

BEFORE marking this task complete:
1. Review tests against `docs/pitfalls/testing-pitfalls.md`
2. Verify path traversal is tested
3. Verify non-imagery ID is rejected
4. Run tests and confirm green

---

## Task 3: Inventory Tab Frontend

**Files:**
- Modify: `frontend/config/index.html` (add Inventory tab HTML + CSS + JS)

BEFORE starting work:
1. Read the full spec at `docs/superpowers/specs/2026-04-15-imagery-inventory-manager-design.md`
2. Read the current `frontend/config/index.html` — understand the tab system, CSS, and how the Pipelines tab card grid was built
3. Read `dev/testing-pitfalls.md`

**Context:** The admin panel has 3 tabs (Dashboard, Pipelines, Settings). We're adding a 4th: Inventory. The tab system uses hash-based navigation (`#dashboard`, `#pipelines`, `#settings`). Tab switching is handled by JS in the `switchTab()` function (or equivalent click handlers on `.tab-btn` elements).

The Inventory tab has:
- A MapLibre map (2/3 width) showing colored coverage rectangles per source
- A sidebar (1/3 width) listing sources with details
- The container is wider (1000px) than other tabs (600px)
- Data comes from `GET /admin/imagery/catalog` (already built) and `GET /admin/status` (for disk free)
- Delete uses `DELETE /admin/imagery/{source_id}` (Task 2)
- Map is lazy-initialized on first tab activation

**Source colors (fixed palette):**
- imagery (USGS): #89b4fa
- imagery_noaa: #a6e3a1
- imagery_m2m: #f9e2af
- imagery_sentinel: #cba6f7
- imagery_naip: #fab387
- imagery_custom: #f38ba8

**WARNING:** Do NOT modify the Dashboard, Pipelines, or Settings tabs. Only add new content.

- [ ] **Step 1: Add CSS for Inventory tab**

Add to the style block:

```css
/* === INVENTORY TAB === */
.container.wide { max-width: 1000px; }
.inventory-layout { display: flex; gap: 12px; min-height: 400px; }
.inventory-map { flex: 2; background: #0d1117; border-radius: 8px; overflow: hidden; position: relative; }
.inventory-sidebar { flex: 1; min-width: 200px; display: flex; flex-direction: column; gap: 8px; }
@media (max-width: 640px) {
  .inventory-layout { flex-direction: column; }
  .inventory-map { min-height: 250px; }
}
.inv-source { padding: 8px; background: #181825; border-radius: 6px; cursor: pointer; transition: background 0.15s; }
.inv-source:hover { background: #313244; }
.inv-source.selected { background: #313244; }
.inv-source .inv-name { font-size: 12px; font-weight: 600; }
.inv-source .inv-meta { font-size: 10px; color: #7a8299; margin-top: 2px; }
.inv-source .inv-size { font-size: 11px; margin-top: 2px; }
.inv-source .inv-detail { display: none; margin-top: 6px; padding-top: 6px; border-top: 1px solid #45475a; font-size: 11px; }
.inv-source.selected .inv-detail { display: block; }
.inv-disk-summary { padding: 8px; background: #181825; border-radius: 6px; margin-top: auto; }
.inv-disk-bar { height: 6px; background: #313244; border-radius: 3px; margin-top: 6px; overflow: hidden; }
.inv-disk-bar-fill { height: 100%; background: #89b4fa; border-radius: 3px; }
```

- [ ] **Step 2: Add Inventory tab button and content div**

Add a new tab button in the `.tab-bar`:
```html
<button class="tab-btn" data-tab="tab-inventory">Inventory</button>
```

Add the tab content div (before or after the Settings tab div):
```html
<div id="tab-inventory" class="tab-content">
    <div class="inventory-layout">
        <div class="inventory-map" id="inventory-map"></div>
        <div class="inventory-sidebar" id="inventory-sidebar">
            <div style="font-size:13px;font-weight:600;margin-bottom:4px;">Imagery Sources</div>
            <div id="inventory-source-list"></div>
            <div class="inv-disk-summary" id="inventory-disk-summary"></div>
        </div>
    </div>
</div>
```

- [ ] **Step 3: Update tab switching for wide container**

Find the tab switching code (click handlers on `.tab-btn`). Add the wide container toggle:

```javascript
// When switching tabs, toggle wide class for inventory
var container = document.querySelector('.container');
container.classList.toggle('wide', targetTabId === 'tab-inventory');
```

Also add `#inventory` to the hash-based navigation mapping.

- [ ] **Step 4: Add inventory map + sidebar rendering JS**

Add the following JavaScript:

```javascript
var _inventoryMap = null;
var _inventorySelectedSource = null;

var INV_COLORS = {
  imagery: '#89b4fa',
  imagery_noaa: '#a6e3a1',
  imagery_m2m: '#f9e2af',
  imagery_sentinel: '#cba6f7',
  imagery_naip: '#fab387',
  imagery_custom: '#f38ba8'
};

function initInventoryMap() {
  if (_inventoryMap) return;
  _inventoryMap = new maplibregl.Map({
    container: 'inventory-map',
    style: '/tiles/styles/darkmatter/style.json',
    center: [-113.4, 40.15],
    zoom: 4,
    attributionControl: false
  });
  _inventoryMap.on('load', function() {
    loadInventoryData();
  });
}

function loadInventoryData() {
  fetch('/admin/imagery/catalog')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      renderInventoryMap(data.sources || []);
      renderInventorySidebar(data.sources || []);
    })
    .catch(function() {
      var list = document.getElementById('inventory-source-list');
      if (list) list.textContent = 'Failed to load catalog';
    });

  // Disk info from /admin/status
  fetch('/admin/status')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      renderDiskSummary(data);
    })
    .catch(function() {});
}

function renderInventoryMap(sources) {
  if (!_inventoryMap) return;

  // Remove existing source layers
  sources.forEach(function(src) {
    var layerId = 'inv-' + src.id;
    if (_inventoryMap.getLayer(layerId)) _inventoryMap.removeLayer(layerId);
    if (_inventoryMap.getLayer(layerId + '-label')) _inventoryMap.removeLayer(layerId + '-label');
    if (_inventoryMap.getSource(layerId)) _inventoryMap.removeSource(layerId);
  });

  var bounds = new maplibregl.LngLatBounds();
  var hasBounds = false;

  sources.forEach(function(src) {
    // Compute union bounds across all zoom levels
    var minLon = 180, minLat = 90, maxLon = -180, maxLat = -90;
    src.zoom_levels.forEach(function(z) {
      var b = z.bounds_lonlat;
      if (b[0] < minLon) minLon = b[0];
      if (b[1] < minLat) minLat = b[1];
      if (b[2] > maxLon) maxLon = b[2];
      if (b[3] > maxLat) maxLat = b[3];
    });

    if (minLon >= maxLon || minLat >= maxLat) return;

    var color = INV_COLORS[src.id] || '#cdd6f4';
    var layerId = 'inv-' + src.id;
    var zooms = src.zoom_levels.map(function(z) { return 'z' + z.zoom; }).join(',');

    _inventoryMap.addSource(layerId, {
      type: 'geojson',
      data: {
        type: 'Feature',
        properties: { name: src.id, label: src.id.replace('imagery_', '').replace('imagery', 'USGS') + ' ' + zooms },
        geometry: {
          type: 'Polygon',
          coordinates: [[[minLon,minLat],[maxLon,minLat],[maxLon,maxLat],[minLon,maxLat],[minLon,minLat]]]
        }
      }
    });

    _inventoryMap.addLayer({
      id: layerId,
      type: 'fill',
      source: layerId,
      paint: { 'fill-color': color, 'fill-opacity': 0.1 }
    });

    _inventoryMap.addLayer({
      id: layerId + '-outline',
      type: 'line',
      source: layerId,
      paint: { 'line-color': color, 'line-opacity': 0.6, 'line-width': 2 }
    });

    bounds.extend([minLon, minLat]);
    bounds.extend([maxLon, maxLat]);
    hasBounds = true;

    // Click handler
    _inventoryMap.on('click', layerId, function() {
      selectInventorySource(src.id);
    });
  });

  if (hasBounds) {
    _inventoryMap.fitBounds(bounds, { padding: 30 });
  }
}

function renderInventorySidebar(sources) {
  var list = document.getElementById('inventory-source-list');
  if (!list) return;
  while (list.firstChild) list.removeChild(list.firstChild);

  sources.forEach(function(src) {
    var color = INV_COLORS[src.id] || '#cdd6f4';
    var sizeBytes = src.size_bytes;
    var sizeStr = sizeBytes > 1e9 ? (sizeBytes / 1e9).toFixed(1) + ' GB' : (sizeBytes / 1e6).toFixed(0) + ' MB';
    var totalTiles = src.zoom_levels.reduce(function(s, z) { return s + z.tile_count; }, 0);
    var zooms = src.zoom_levels.map(function(z) { return 'z' + z.zoom; }).join(', ');

    var div = document.createElement('div');
    div.className = 'inv-source';
    div.id = 'inv-sidebar-' + src.id;
    div.style.borderLeft = '3px solid ' + color;

    var nameEl = document.createElement('div');
    nameEl.className = 'inv-name';
    nameEl.textContent = src.id.replace('imagery_', '').replace('imagery', 'USGS Basemap');
    div.appendChild(nameEl);

    var metaEl = document.createElement('div');
    metaEl.className = 'inv-meta';
    metaEl.textContent = zooms;
    div.appendChild(metaEl);

    var sizeEl = document.createElement('div');
    sizeEl.className = 'inv-size';
    sizeEl.style.color = color;
    sizeEl.textContent = sizeStr + ' \u00b7 ' + totalTiles.toLocaleString() + ' tiles';
    div.appendChild(sizeEl);

    // Detail panel (shown when selected)
    var detail = document.createElement('div');
    detail.className = 'inv-detail';

    // Per-zoom breakdown
    src.zoom_levels.forEach(function(z) {
      var row = document.createElement('div');
      row.textContent = 'z' + z.zoom + ': ' + z.tile_count.toLocaleString() + ' tiles';
      detail.appendChild(row);
    });

    // Registration status
    var regEl = document.createElement('div');
    regEl.style.marginTop = '4px';
    regEl.style.color = src.registered ? '#a6e3a1' : '#f9e2af';
    regEl.textContent = src.registered ? 'Registered \u2713' : 'Not registered';
    detail.appendChild(regEl);

    // Delete button
    var delBtn = document.createElement('button');
    delBtn.className = 'btn-danger';
    delBtn.style.cssText = 'margin-top:8px;width:100%;font-size:11px;padding:6px;';
    delBtn.textContent = 'Delete ' + src.file;
    delBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      if (!confirm('Delete ' + src.file + ' (' + sizeStr + ')? This removes the file and unregisters it from TileServer. This cannot be undone.')) return;
      fetch('/admin/imagery/' + src.id, { method: 'DELETE' })
        .then(function(r) {
          if (!r.ok) return r.json().then(function(d) { alert(d.detail || 'Delete failed'); });
          loadInventoryData(); // refresh
        })
        .catch(function(err) { alert('Delete failed: ' + err.message); });
    });
    detail.appendChild(delBtn);

    div.appendChild(detail);

    div.addEventListener('click', function() {
      selectInventorySource(src.id);
    });

    list.appendChild(div);
  });
}

function selectInventorySource(sourceId) {
  // Toggle selection
  if (_inventorySelectedSource === sourceId) {
    _inventorySelectedSource = null;
  } else {
    _inventorySelectedSource = sourceId;
  }

  // Update sidebar selection state
  document.querySelectorAll('.inv-source').forEach(function(el) {
    el.classList.toggle('selected', el.id === 'inv-sidebar-' + _inventorySelectedSource);
  });

  // Zoom map to selected source bounds
  if (_inventorySelectedSource && _inventoryMap) {
    var src = _inventoryMap.getSource('inv-' + _inventorySelectedSource);
    if (src) {
      var data = src._data || src.serialize().data;
      if (data && data.geometry) {
        var coords = data.geometry.coordinates[0];
        var b = new maplibregl.LngLatBounds(coords[0], coords[2]);
        _inventoryMap.fitBounds(b, { padding: 40, duration: 500 });
      }
    }
  }
}

function renderDiskSummary(statusData) {
  var el = document.getElementById('inventory-disk-summary');
  if (!el) return;
  var freeGb = statusData.disk_free_gb || 0;
  var totalGb = statusData.disk_total_gb || 1;
  var usedPct = statusData.disk_used_pct || 0;

  el.textContent = '';
  var label = document.createElement('div');
  label.style.cssText = 'font-size:10px;color:#7a8299;';
  label.textContent = 'Disk: ' + freeGb.toFixed(0) + ' GB free of ' + totalGb.toFixed(0) + ' GB';
  el.appendChild(label);

  var bar = document.createElement('div');
  bar.className = 'inv-disk-bar';
  var fill = document.createElement('div');
  fill.className = 'inv-disk-bar-fill';
  fill.style.width = usedPct + '%';
  if (usedPct > 90) fill.style.background = '#f38ba8';
  else if (usedPct > 75) fill.style.background = '#f9e2af';
  bar.appendChild(fill);
  el.appendChild(bar);
}
```

- [ ] **Step 5: Wire tab activation to lazy-init the map**

In the tab switching handler, when the Inventory tab becomes active:

```javascript
if (targetTabId === 'tab-inventory') {
  // Lazy-init map on first show
  setTimeout(function() { initInventoryMap(); }, 100);
}
```

The `setTimeout` ensures the tab content div is visible before MapLibre tries to measure the container size. Without it, the map may render at 0x0 pixels.

- [ ] **Step 6: Verify in browser**

Open http://localhost:8097/#inventory:
1. Map should render with darkmatter basemap
2. Coverage rectangles for each source on disk (requires Docker rebuild for catalog endpoint)
3. Sidebar shows source list with colored borders
4. Clicking a source highlights it, shows detail panel with per-zoom breakdown + delete button
5. Delete shows confirmation dialog, removes file on confirm, refreshes display
6. Disk summary bar at bottom of sidebar
7. Other tabs (Dashboard, Pipelines, Settings) are unaffected

- [ ] **Step 7: Commit**

```bash
git add frontend/config/index.html
git commit -m "feat: add Inventory tab with coverage map, sidebar, and delete"
```

BEFORE marking this task complete:
1. Verify the container width toggles correctly (wide for Inventory, normal for other tabs)
2. Verify the map lazy-inits only on first Inventory tab activation
3. Verify delete confirmation dialog shows source name and size
4. Verify no console errors on any tab

---

## Review Checkpoint

After all 3 tasks:
Carefully review the batch of work from multiple perspectives. Do a minimum
of three review rounds. Specifically verify:

1. **Task 1:** Does `remove_mbtiles_from_config` use atomic writes? Is it idempotent?
2. **Task 2:** Does the delete endpoint validate source_id? Is the order correct (file first, then config)?
3. **Task 3:** Does the map use union bounds (one rectangle per source)? Does the container width toggle work?
4. **Cross-task:** Does the delete button in the frontend call the correct endpoint? Does it re-fetch the catalog after deletion?
5. **No regressions:** All other tabs functional, 487+ tests pass.
