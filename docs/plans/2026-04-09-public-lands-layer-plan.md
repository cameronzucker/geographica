# Public Lands Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a togglable vector tile overlay showing color-coded public land boundaries (BLM, USFS, NPS, State Trust, Tribal, Wilderness, etc.) from the authoritative PAD-US dataset.

**Architecture:** Python pipeline downloads PAD-US GeoPackage, classifies and clips via ogr2ogr SQL, generates vector tiles with Tippecanoe, served by TileServer GL. Frontend adds fill+outline layers with toggle, opacity slider, click popup, legend, and style swap survival.

**Tech Stack:** Python 3, GDAL/ogr2ogr, Tippecanoe (built from source on ARM64), TileServer GL, MapLibre GL JS, NGINX, Playwright (visual verification)

**Spec:** docs/superpowers/specs/2026-04-09-public-lands-layer-design.md (adversarial-reviewed, CSO-reviewed)

**Pitfalls:** Read docs/pitfalls/testing-pitfalls.md and docs/pitfalls/implementation-pitfalls.md before starting.

**IMPORTANT:** This plan was validated by 5 adversarial review rounds and CSO security review. Key corrections:
- fill-sort-key is a LAYOUT property, not paint
- sort_key MUST be emitted by ogr2ogr SQL (not just category)
- Use --coalesce-smallest-as-needed NOT --drop-densest-as-needed (drops whole polygons)
- Single ogr2ogr call (FROM {layer} references GeoPackage, not GeoJSON)
- Use subprocess.run(shell=False) for all external commands (CSO: shell injection risk)
- Validate detected layer name against ^[A-Za-z0-9_]+$ regex
- Add public-lands layers AFTER imported-points in addPlaceholderSources
- Add public-lands-fill to generic click handler exclusion list

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| scripts/build_public_lands.py | PAD-US download, classify, tile generation | Create |
| tileserver/config.json | Add publiclands data source | Modify |
| nginx/nginx.conf | Add publiclands.json TileJSON sub_filter | Modify |
| frontend/app.js | Layers, toggle, click popup, syncLayerVisibility | Modify |
| frontend/index.html | Checkbox, slider, legend HTML | Modify |
| frontend/style.css | Legend grid, slider row, toggle interaction | Modify |
| tests/test_public_lands_pipeline.py | Pipeline unit tests | Create |

---

## Task Dependencies

```
Task 1 (Host deps: GDAL + Tippecanoe)
  -> Task 2 (Pipeline script)
       -> Task 3 (Sample tiles + Playwright verification)
            -> Task 4 (TileServer + NGINX config)
                 -> Task 5 (Frontend layers + toggle + opacity)
                      -> Task 6 (Click popup + handler exclusion)
                           -> Task 7 (Legend UI)
                                -> Task 8 (Full Western US build + verification)
                                     -> Task 9 (Review loop)
```

All tasks are sequential. No parallelization — each depends on the previous.

---

## Preamble (Apply to Every Task)

```
BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
3. Read the spec: docs/superpowers/specs/2026-04-09-public-lands-layer-design.md
4. Use var/function exclusively in frontend code (NO let, const, or arrow functions)
5. Use subprocess.run(shell=False) for ALL external commands in Python
Follow TDD: write failing test -> implement fix -> verify green.
```

## Completion Check (Apply to Every Task)

```
BEFORE marking this task complete:
1. Review your code against docs/pitfalls/implementation-pitfalls.md
2. Verify all tests pass
3. Run: git diff --stat to confirm only expected files changed
4. Commit with descriptive message
```

---

### Task 1: Install Host Dependencies

**Spec ref:** Spec Dependencies section

This task runs on the Pi 5 host, NOT in Docker. These are build-time dependencies for the pipeline script.

- [ ] **Step 1: Install GDAL**

```bash
sudo apt update && sudo apt install -y gdal-bin libgdal-dev python3-gdal
ogr2ogr --version
# Expected: GDAL X.Y.Z
ogrinfo --version
# Expected: GDAL X.Y.Z
```

- [ ] **Step 2: Build Tippecanoe from source**

```bash
sudo apt install -y build-essential libsqlite3-dev zlib1g-dev
git clone https://github.com/felt/tippecanoe.git /tmp/tippecanoe
cd /tmp/tippecanoe && make -j4 && sudo make install
tippecanoe --version
# Expected: tippecanoe vX.Y.Z
```

This takes 10-20 minutes on Pi 5's Cortex-A76.

- [ ] **Step 3: Verify both tools work**

```bash
echo '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[-114.5,36.0]},"properties":{"name":"test"}}]}' > /tmp/test.geojson
tippecanoe -o /tmp/test.mbtiles -Z0 -z4 -l test /tmp/test.geojson
# Expected: creates /tmp/test.mbtiles
ls -lh /tmp/test.mbtiles
rm /tmp/test.geojson /tmp/test.mbtiles
```

- [ ] **Step 4: Commit (no code changes — document in CLAUDE.md if desired)**

This task has no code to commit. Proceed to Task 2.

---

### Task 2: Pipeline Script

**Spec ref:** Spec Section 1 (Data Pipeline)
**Files:** Create scripts/build_public_lands.py, Create tests/test_public_lands_pipeline.py

- [ ] **Step 1: Write pipeline unit tests**

Create `tests/test_public_lands_pipeline.py`:

```python
"""Tests for build_public_lands.py pipeline functions."""
import os
import re
import subprocess
import pytest

# Import will fail until script exists — that's the TDD point
from scripts.build_public_lands import (
    detect_layer_name,
    validate_layer_name,
    build_ogr2ogr_command,
    build_tippecanoe_command,
    validate_url_scheme,
)


class TestLayerNameValidation:
    def test_valid_alphanumeric_underscore(self):
        assert validate_layer_name("PADUS4_0Combined_Fee") is True

    def test_rejects_shell_metacharacters(self):
        assert validate_layer_name("layer; rm -rf /") is False

    def test_rejects_quotes(self):
        assert validate_layer_name("layer'DROP") is False

    def test_rejects_empty(self):
        assert validate_layer_name("") is False

    def test_rejects_spaces(self):
        assert validate_layer_name("layer name") is False


class TestUrlValidation:
    def test_accepts_https(self):
        assert validate_url_scheme("https://example.com/file.gpkg") is True

    def test_rejects_http(self):
        assert validate_url_scheme("http://example.com/file.gpkg") is False

    def test_rejects_ftp(self):
        assert validate_url_scheme("ftp://example.com/file.gpkg") is False


class TestOgr2ogrCommand:
    def test_returns_list_not_string(self):
        cmd = build_ogr2ogr_command(
            gpkg_path="/tmp/padus.gpkg",
            layer_name="PADUS4_0Combined_Fee",
            bbox="-115.5,35.5,-113.5,36.5",
            output_path="/tmp/out.geojson",
        )
        assert isinstance(cmd, list), "Must be a list for shell=False"
        assert cmd[0] == "ogr2ogr"

    def test_contains_clipsrc(self):
        cmd = build_ogr2ogr_command(
            gpkg_path="/tmp/padus.gpkg",
            layer_name="TestLayer",
            bbox="-115.5,35.5,-113.5,36.5",
            output_path="/tmp/out.geojson",
        )
        assert "-clipsrc" in cmd

    def test_contains_srs_transform(self):
        cmd = build_ogr2ogr_command(
            gpkg_path="/tmp/padus.gpkg",
            layer_name="TestLayer",
            bbox="-115.5,35.5,-113.5,36.5",
            output_path="/tmp/out.geojson",
        )
        assert "-t_srs" in cmd
        idx = cmd.index("-t_srs")
        assert cmd[idx + 1] == "EPSG:4326"

    def test_sql_contains_category_and_sort_key(self):
        cmd = build_ogr2ogr_command(
            gpkg_path="/tmp/padus.gpkg",
            layer_name="TestLayer",
            bbox="-115.5,35.5,-113.5,36.5",
            output_path="/tmp/out.geojson",
        )
        sql_idx = cmd.index("-sql")
        sql = cmd[sql_idx + 1]
        assert "AS category" in sql
        assert "AS sort_key" in sql
        assert "FROM TestLayer" in sql


class TestTippecanoeCommand:
    def test_returns_list(self):
        cmd = build_tippecanoe_command("/tmp/out.mbtiles", "/tmp/in.geojson")
        assert isinstance(cmd, list)

    def test_no_drop_densest(self):
        cmd = build_tippecanoe_command("/tmp/out.mbtiles", "/tmp/in.geojson")
        cmd_str = " ".join(cmd)
        assert "--drop-densest-as-needed" not in cmd_str

    def test_uses_coalesce_smallest(self):
        cmd = build_tippecanoe_command("/tmp/out.mbtiles", "/tmp/in.geojson")
        assert "--coalesce-smallest-as-needed" in cmd

    def test_max_tile_bytes(self):
        cmd = build_tippecanoe_command("/tmp/out.mbtiles", "/tmp/in.geojson")
        assert "--maximum-tile-bytes=500000" in cmd

    def test_layer_name_is_public_lands(self):
        cmd = build_tippecanoe_command("/tmp/out.mbtiles", "/tmp/in.geojson")
        assert "-l" in cmd
        idx = cmd.index("-l")
        assert cmd[idx + 1] == "public_lands"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/administrator/Code/geographica
python3 -m pytest tests/test_public_lands_pipeline.py -v
# Expected: ImportError — scripts.build_public_lands does not exist
```

- [ ] **Step 3: Write the pipeline script**

Create `scripts/build_public_lands.py` (~250 lines). The full implementation must include:

1. `validate_layer_name(name)` — regex check `^[A-Za-z0-9_]+$` (CSO requirement)
2. `validate_url_scheme(url)` — enforce HTTPS
3. `detect_layer_name(gpkg_path)` — run `ogrinfo` via subprocess.run(shell=False), pattern match `PADUS.*Combined|PADUS.*Fee`
4. `build_ogr2ogr_command(gpkg_path, layer_name, bbox, output_path)` — returns list (NOT string). SQL includes both `category` and `sort_key` CASE expressions per spec.
5. `build_tippecanoe_command(output_path, input_path)` — returns list with correct flags
6. `download_padus(url, cache_dir)` — download with retry, HTTPS validation
7. `main()` with argparse: --bbox, --output, --padus-url, --cache-dir, --sample

**Critical implementation details (from spec + adversarial review):**
- ALL subprocess calls use `subprocess.run([...], shell=False, check=True)`
- Layer name validated with regex before interpolation into SQL
- Single ogr2ogr call: clip + reproject + classify from GeoPackage (NOT two steps)
- ogr2ogr SQL FROM clause uses `{detected_layer}` (GeoPackage layer name)
- Tippecanoe flags: `--coalesce-smallest-as-needed --simplification=10 --no-simplification-of-shared-nodes --maximum-tile-bytes=500000`
- Do NOT use `--drop-densest-as-needed` or `--extend-zooms-if-still-dropping`
- Verify non-empty output after ogr2ogr (fail fast if layer name was wrong)
- Sample bbox: `[-115.5, 35.5, -113.5, 36.5]` when --sample flag is set
- Default bbox: `[-124.8, 31.3, -102.0, 49.0]`

Read the full spec Section 1 for the complete ogr2ogr SQL with classification and sort_key.

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_public_lands_pipeline.py -v
# Expected: all pass
```

- [ ] **Step 5: Commit**

```bash
git add scripts/build_public_lands.py tests/test_public_lands_pipeline.py
git commit -m "feat(pipeline): build_public_lands.py — PAD-US download, classify, tile generation

Downloads PAD-US GeoPackage, auto-detects layer name, clips/classifies
via single ogr2ogr SQL call (category + sort_key), generates vector
tiles with Tippecanoe. CSO-hardened: shell=False, layer name regex
validation, HTTPS enforcement."
```

---

### Task 3: Sample Tile Generation + Visual Verification

**Spec ref:** Spec Section 1 (Sample Pipeline), Section 4 (Visual Verification)
**Prerequisites:** Task 1 (GDAL + Tippecanoe installed), Task 2 (script exists)

- [ ] **Step 1: Run the sample pipeline**

```bash
cd /home/administrator/Code/geographica
python3 scripts/build_public_lands.py \
  --sample \
  --output /srv/geographica/data/public-lands.mbtiles \
  --cache-dir /srv/geographica/data/padus_cache/
```

This downloads ~2GB PAD-US GeoPackage (first run only), then clips to NW Arizona bbox and generates tiles. Expected time: 2-5 minutes after download completes.

- [ ] **Step 2: Verify MBTiles output**

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('/srv/geographica/data/public-lands.mbtiles')
cur = conn.cursor()
# Check metadata
for row in cur.execute('SELECT name, value FROM metadata'):
    print(f'{row[0]}: {row[1]}')
# Count tiles
count = cur.execute('SELECT COUNT(*) FROM tiles').fetchone()[0]
print(f'Total tiles: {count}')
conn.close()
"
# Expected: non-zero tile count, format=pbf, name=public_lands
```

- [ ] **Step 3: Complete Tasks 4-7 (TileServer + Frontend) before visual verification**

The visual verification requires the frontend to be configured. Skip to Tasks 4-7, then return here for Step 4.

- [ ] **Step 4: Visual verification via Playwright**

After Tasks 4-7 are complete and `docker compose up -d --force-recreate frontend` has been run:

Use Playwright to navigate to the running instance, enable the public lands toggle, and take screenshots of the NW Arizona test region:

```
1. Navigate to http://localhost:8093
2. Wait for map to load
3. Click #toggle-public-lands checkbox
4. Execute JS: map.flyTo({center: [-114.5, 36.0], zoom: 9})
5. Wait 3 seconds for tiles to load
6. Take screenshot: public-lands-z9-positron.png
7. Execute JS: map.setZoom(12)
8. Wait 2 seconds
9. Take screenshot: public-lands-z12-detail.png
10. Click #toggle-terrain checkbox
11. Wait 2 seconds
12. Take screenshot: public-lands-z12-terrain.png
13. Click darkmatter basemap radio button
14. Wait for style swap
15. Take screenshot: public-lands-z12-darkmatter.png
```

Verify in screenshots:
- BLM areas (wheat/tan) visible west of Kingman
- Lake Mead NRA (dark green NPS) clearly shaded
- Wilderness areas (purple) distinct from surrounding forest/BLM
- State Trust (chocolate) visible in checkerboard pattern south of I-40
- Boundaries align with roads/terrain features at z12
- Terrain exaggeration doesn't clip/fight with fills
- Dark basemap: fills visible and legible

- [ ] **Step 5: Commit verification screenshots**

```bash
# Save screenshots to dev/ for reference (do NOT commit large PNGs to repo)
# Just note the verification result in the commit message
git add -A && git commit -m "feat(pipeline): sample tile generation verified via Playwright

NW Arizona sample tiles generated and visually verified:
BLM, NPS, Wilderness, State Trust all rendering correctly."
```

---

### Task 4: TileServer + NGINX Configuration

**Spec ref:** Spec Section 2 (TileServer GL Integration)
**Files:** Modify tileserver/config.json, Modify nginx/nginx.conf

- [ ] **Step 1: Add publiclands data source to TileServer config**

In `tileserver/config.json`, add `publiclands` to the `data` object:

```json
"publiclands": {
  "mbtiles": "/srv/data/public-lands.mbtiles"
}
```

- [ ] **Step 2: Add NGINX TileJSON sub_filter block**

In `nginx/nginx.conf`, in the main server block, after the `elevation.json` location block (after line 61), add:

```nginx
    location /tiles/data/publiclands.json {
        proxy_pass http://tileserver:8080/data/publiclands.json;
        proxy_http_version 1.1;

        proxy_set_header Accept-Encoding "";
        sub_filter_once off;
        sub_filter_types application/json text/plain;
        sub_filter 'http://tileserver:8080/data/' '$scheme://$http_host/tiles/data/';
    }
```

- [ ] **Step 3: Restart services**

```bash
docker compose up -d --force-recreate tileserver frontend
# Wait for tileserver to start
sleep 5
# Verify the new data source is served
curl -s http://localhost:8090/data/publiclands.json | head -c 200
# Expected: JSON with "tiles" array (or 404 if MBTiles not yet generated — that's OK)
```

- [ ] **Step 4: Commit**

```bash
git add tileserver/config.json nginx/nginx.conf
git commit -m "feat(tileserver): add publiclands data source + NGINX TileJSON block

TileServer serves public-lands.mbtiles as vector tiles at
/tiles/data/publiclands/{z}/{x}/{y}.pbf. NGINX sub_filter rewrites
internal URLs for external access."
```

---

### Task 5: Frontend Layers + Toggle + Opacity + Style Swap

**Spec ref:** Spec Section 3 (Frontend Layer Integration)
**Files:** Modify frontend/app.js, Modify frontend/index.html

- [ ] **Step 1: Add source and layers in addPlaceholderSources()**

In `frontend/app.js`, inside `addPlaceholderSources()`, **AFTER the search-result layers** (after all imported-* and search-result-* layers are created), add:

```js
    // --- Public lands vector tile overlay ---
    if (!map.getSource('public-lands')) {
      map.addSource('public-lands', {
        type: 'vector',
        tiles: [window.location.origin + '/tiles/data/publiclands/{z}/{x}/{y}.pbf'],
        maxzoom: 14
      });
    }
    // Fill layer (add FIRST — outline goes on top)
    if (!map.getLayer('public-lands-fill')) {
      map.addLayer({
        id: 'public-lands-fill',
        type: 'fill',
        source: 'public-lands',
        'source-layer': 'public_lands',
        layout: {
          visibility: 'none',
          'fill-sort-key': ['get', 'sort_key']
        },
        paint: {
          'fill-color': ['match', ['get', 'category'],
            'BLM', '#f5deb3', 'USFS', '#228b22', 'NPS', '#006400',
            'FWS', '#008080', 'DOD', '#8b4545', 'USBR', '#4682b4',
            'Tribal', '#cd853f', 'State', '#d2691e', 'Wilderness', '#800080',
            '#a9a9a9'],
          'fill-opacity': 0.3
        }
      }, 'imported-points');
    }
    // Outline layer (add SECOND — renders on top of fill)
    if (!map.getLayer('public-lands-outline')) {
      map.addLayer({
        id: 'public-lands-outline',
        type: 'line',
        source: 'public-lands',
        'source-layer': 'public_lands',
        layout: { visibility: 'none' },
        paint: {
          'line-color': ['match', ['get', 'category'],
            'BLM', '#c8a870', 'USFS', '#1a6b1a', 'NPS', '#004d00',
            'FWS', '#006666', 'DOD', '#6b3535', 'USBR', '#366fa0',
            'Tribal', '#a0682f', 'State', '#a34f1a', 'Wilderness', '#660066',
            '#808080'],
          'line-width': 1,
          'line-opacity': 0.6
        }
      }, 'imported-points');
    }
```

**CRITICAL:** fill-sort-key is a LAYOUT property. fill layer added BEFORE outline (same before anchor). Both default to visibility: 'none' (user opts in via checkbox).

- [ ] **Step 2: Add toggle HTML**

In `frontend/index.html`, after the terrain exaggeration slider row (after line 76), add:

```html
      <label class="checkbox-label">
        <input type="checkbox" id="toggle-public-lands"> Public Lands
      </label>
      <div class="slider-row" id="public-lands-opacity-row">
        <label for="public-lands-opacity">Opacity</label>
        <input type="range" id="public-lands-opacity" min="0" max="100" value="50">
        <span id="public-lands-opacity-value">50%</span>
      </div>
```

- [ ] **Step 3: Add toggle logic in initLayerControls()**

In `frontend/app.js`, inside `initLayerControls()`, after the terrain slider logic (after line 595), add:

```js
    // Public lands toggle
    var publicLandsCheckbox = document.getElementById('toggle-public-lands');
    var publicLandsOpacityRow = document.getElementById('public-lands-opacity-row');
    if (publicLandsCheckbox) {
      publicLandsCheckbox.addEventListener('change', function () {
        setLayerVisibility('public-lands-fill', this.checked);
        setLayerVisibility('public-lands-outline', this.checked);
        if (publicLandsOpacityRow) {
          publicLandsOpacityRow.classList.toggle('visible', this.checked);
        }
      });
    }

    // Public lands opacity slider
    var publicLandsOpacity = document.getElementById('public-lands-opacity');
    var publicLandsOpacityLabel = document.getElementById('public-lands-opacity-value');
    if (publicLandsOpacity) {
      publicLandsOpacity.addEventListener('input', function () {
        var val = parseInt(this.value, 10);
        if (publicLandsOpacityLabel) publicLandsOpacityLabel.textContent = val + '%';
        if (map.getLayer('public-lands-fill')) {
          map.setPaintProperty('public-lands-fill', 'fill-opacity', val / 100 * 0.6);
        }
        if (map.getLayer('public-lands-outline')) {
          map.setPaintProperty('public-lands-outline', 'line-opacity', val / 100 * 0.8);
        }
      });
    }
```

- [ ] **Step 4: Add style swap restoration in syncLayerVisibility()**

In `syncLayerVisibility()` (app.js line 635-646), after the terrain restore logic, add:

```js
    // Restore public lands toggle state
    var plCheckbox = document.getElementById('toggle-public-lands');
    if (plCheckbox) {
      setLayerVisibility('public-lands-fill', plCheckbox.checked);
      setLayerVisibility('public-lands-outline', plCheckbox.checked);
      if (plCheckbox.checked) {
        var plSlider = document.getElementById('public-lands-opacity');
        if (plSlider && map.getLayer('public-lands-fill')) {
          var plVal = parseInt(plSlider.value, 10);
          map.setPaintProperty('public-lands-fill', 'fill-opacity', plVal / 100 * 0.6);
          map.setPaintProperty('public-lands-outline', 'line-opacity', plVal / 100 * 0.8);
        }
      }
    }
```

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js frontend/index.html
git commit -m "feat(frontend): public lands overlay — source, layers, toggle, opacity, style swap

Vector tile source from TileServer, fill+outline layers with category
color matching, fill-sort-key in layout for overlap ordering, toggle
checkbox with opacity slider, syncLayerVisibility for style swap."
```

---

### Task 6: Click Popup + Generic Handler Exclusion

**Spec ref:** Spec Section 3 (Click Interaction)
**Files:** Modify frontend/app.js

- [ ] **Step 1: Add public-lands-fill to generic click handler exclusion**

In `frontend/app.js`, find the `queryRenderedFeatures` call at line ~1102-1105. Add `'public-lands-fill'` to the layers array:

```js
      var features = map.queryRenderedFeatures(e.point, {
        layers: ['imported-points', 'imported-lines', 'imported-polygons',
                 'imported-polygon-outlines', 'search-result-circles', 'public-lands-fill']
      });
```

- [ ] **Step 2: Add dedicated public lands click handler**

In `frontend/app.js`, in `addPlaceholderSources()` after the public lands layers are added, register the click handler:

```js
    // Public lands click popup
    map.on('click', 'public-lands-fill', function (e) {
      if (!e.features || !e.features.length) return;
      var props = e.features[0].properties || {};
      var coords = e.lngLat;

      var content = document.createElement('div');

      // Category badge (colored dot)
      var categoryColors = {
        BLM: '#f5deb3', USFS: '#228b22', NPS: '#006400', FWS: '#008080',
        DOD: '#8b4545', USBR: '#4682b4', Tribal: '#cd853f', State: '#d2691e',
        Wilderness: '#800080', Other: '#a9a9a9'
      };
      var badge = document.createElement('span');
      badge.style.cssText = 'display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle;background:' + (categoryColors[props.category] || '#a9a9a9');
      content.appendChild(badge);

      // Title (unit name)
      var title = document.createElement('strong');
      title.textContent = props.name || props.category || 'Public Land';
      content.appendChild(title);

      // Subtitle (agency + designation)
      if (props.agency || props.designation) {
        var sub = document.createElement('p');
        sub.style.cssText = 'font-size:12px;color:#a6adc8;margin:4px 0 0;';
        var parts = [];
        if (props.agency) parts.push(props.agency);
        if (props.designation) parts.push(props.designation);
        sub.textContent = parts.join(' — ');
        content.appendChild(sub);
      }

      new maplibregl.Popup({ maxWidth: '280px' })
        .setLngLat(coords)
        .setDOMContent(content)
        .addTo(map);
    });

    // Pointer cursor on hover
    map.on('mouseenter', 'public-lands-fill', function () {
      map.getCanvas().style.cursor = 'pointer';
    });
    map.on('mouseleave', 'public-lands-fill', function () {
      map.getCanvas().style.cursor = '';
    });
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app.js
git commit -m "feat(frontend): public lands click popup with category badge

Dedicated click handler shows unit name, agency, designation with
colored category badge. Added to generic handler exclusion list to
prevent double-firing with reverse geocode."
```

---

### Task 7: Legend UI

**Spec ref:** Spec Section 5 (Legend UI)
**Files:** Modify frontend/index.html, Modify frontend/style.css

- [ ] **Step 1: Add legend HTML**

In `frontend/index.html`, after the public lands opacity slider row (added in Task 5), add:

```html
      <div id="public-lands-legend" class="public-lands-legend">
        <div class="legend-item"><span class="legend-swatch" style="background:#f5deb3"></span>BLM</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#228b22"></span>Nat'l Forest</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#006400"></span>Nat'l Park</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#008080"></span>Fish &amp; Wildlife</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#8b4545"></span>Military*</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#4682b4"></span>Bur. of Reclamation</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#cd853f"></span>Tribal&dagger;</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#d2691e"></span>State Trust</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#800080"></span>Wilderness</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#a9a9a9"></span>Other Federal</div>
        <div class="legend-footnotes">
          <small>* Restricted access</small><br>
          <small>&dagger; Boundaries may be incomplete</small>
        </div>
      </div>
```

- [ ] **Step 2: Add legend CSS**

In `frontend/style.css`, add:

```css
.public-lands-legend {
  display: none;
  grid-template-columns: 1fr 1fr;
  gap: 4px 12px;
  padding: 8px 0 4px;
  font-size: 12px;
}
.public-lands-legend.visible {
  display: grid;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text, #cdd6f4);
}
.legend-swatch {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 2px;
  flex-shrink: 0;
}
.legend-footnotes {
  grid-column: 1 / -1;
  color: var(--subtext0, #a6adc8);
  padding-top: 4px;
}
```

- [ ] **Step 3: Wire legend visibility to toggle**

In `frontend/app.js`, in the public lands checkbox change handler (added in Task 5), add legend toggle:

```js
      var legend = document.getElementById('public-lands-legend');
      if (legend) legend.classList.toggle('visible', this.checked);
```

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html frontend/style.css frontend/app.js
git commit -m "feat(frontend): public lands legend with category swatches and footnotes

Two-column grid legend with 10 categories, colored swatches, Military*
and Tribal footnotes. Visibility tied to toggle checkbox."
```

---

### Task 8: Full Western US Build + Verification

**Spec ref:** Spec Section 1 (Memory guidance), Section 4 (Visual Verification)
**Prerequisites:** Tasks 1-7 complete, sample verified

- [ ] **Step 1: Stop Docker services to free memory**

```bash
docker compose stop
free -h
# Verify at least 6GB free RAM
```

- [ ] **Step 2: Run full Western US pipeline**

```bash
python3 scripts/build_public_lands.py \
  --output /srv/geographica/data/public-lands.mbtiles \
  --cache-dir /srv/geographica/data/padus_cache/
```

Expected time: 30-90 minutes. Monitor with `top` or `htop`.

- [ ] **Step 3: Verify output**

```bash
ls -lh /srv/geographica/data/public-lands.mbtiles
# Expected: 50-200 MB
python3 -c "
import sqlite3
conn = sqlite3.connect('/srv/geographica/data/public-lands.mbtiles')
count = conn.execute('SELECT COUNT(*) FROM tiles').fetchone()[0]
print(f'Total tiles: {count}')
conn.close()
"
```

- [ ] **Step 4: Restart services and verify**

```bash
docker compose up -d
# Wait for all services healthy
docker compose ps
```

- [ ] **Step 5: Visual verification at multiple zoom levels**

Use Playwright to verify at Western US scale (z4-z5) and detail (z12-z14):

```
1. Navigate to http://localhost:8093
2. Enable public lands toggle
3. Zoom to z5 covering full Western US
4. Screenshot: verify large BLM/USFS areas visible, not dropped
5. Zoom to z12 over NW Arizona (Hoover Dam area)
6. Screenshot: verify boundary precision
7. Click a wilderness area inside a national forest
8. Verify: wilderness popup appears (not forest) — confirms fill-sort-key working
```

- [ ] **Step 6: Commit**

```bash
git commit --allow-empty -m "feat(pipeline): full Western US public lands tiles generated and verified

public-lands.mbtiles generated from PAD-US 4.0, all categories rendering
correctly at z0-z14. fill-sort-key confirmed working (wilderness on top)."
```

---

### Task 9: Review Loop

```
After completing all tasks:
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues. Then
update your private journal and continue onto the next tasks.
```

**Review checklist:**
- All subprocess.run calls use shell=False (CSO requirement)
- Layer name validated with regex ^[A-Za-z0-9_]+$
- fill-sort-key in layout block (NOT paint)
- sort_key emitted by ogr2ogr SQL
- addLayer for fill BEFORE outline (same before anchor)
- public-lands-fill in generic click handler exclusion list at line ~1103
- syncLayerVisibility restores public lands toggle + opacity
- Opacity formula: val / 100 * 0.6 for fill, val / 100 * 0.8 for outline
- Slider default 50 produces fill-opacity 0.3 (matches layer definition)
- All var/function (no let/const/arrow)
- Legend uses textContent (never raw HTML from tile properties)
- No hardcoded URLs — uses window.location.origin for tile source
- Tippecanoe uses --coalesce-smallest-as-needed (NOT --drop-densest)
- Tippecanoe uses --no-simplification-of-shared-nodes (NOT deprecated --detect-shared-borders)

---

## Execution Recommendation

**Option 2: Parallel session with /executing-plans in a worktree** is recommended because:

1. **Context consumption:** This session has used substantial context for brainstorming, 5 adversarial rounds, and CSO review. A fresh session has maximum capacity for code generation.
2. **Self-contained plan:** The spec contains every detail needed — SQL expressions, Tippecanoe flags, MapLibre layer definitions, exact line numbers. No implicit conversation context required.
3. **Sequential tasks:** All 9 tasks are sequential (no parallelization possible). Subagent-driven would add overhead without parallelism benefit.
4. **Risk concentration:** Tasks 1-3 (host dependencies, pipeline, sample generation) are the riskiest (ARM64 compilation, 2GB download, external tool integration) and benefit from focused attention in a dedicated session.
5. **Playwright verification:** The visual verification steps require interactive browser access, which works best in a single focused session that can iterate on color adjustments.
