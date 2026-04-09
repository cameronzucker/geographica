# Hybrid Imagery + Roads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add a hybrid map mode where aerial imagery serves as the base layer with roads, labels, and boundaries rendered on top — activated by the existing imagery toggle.

**Architecture:** Pre-authored MapLibre style JSON (`hybrid/style.local.json`) derived from darkmatter, with imagery raster base + ~34 curated vector layers. Frontend imagery toggle triggers `map.setStyle()` swap. All overlays survive via existing `addPlaceholderSources()` pattern.

**Tech Stack:** MapLibre GL JS, TileServer GL, vanilla JS (ES5, var/function only)

**Spec:** docs/superpowers/specs/2026-04-09-hybrid-imagery-roads-design.md (5-round adversarial-reviewed)

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| tileserver/styles/hybrid/style.local.json | Hybrid MapLibre style | Create (~500 lines) |
| tileserver/styles/hybrid/sprite.json | Road shield sprites | Copy from darkmatter |
| tileserver/styles/hybrid/sprite.png | Road shield sprites | Copy from darkmatter |
| tileserver/styles/hybrid/sprite@2x.json | HiDPI sprites | Copy from darkmatter |
| tileserver/styles/hybrid/sprite@2x.png | HiDPI sprites | Copy from darkmatter |
| tileserver/config.json | Add hybrid style entry | Modify |
| frontend/app.js | STYLES, toggle, guards, z-order | Modify |

---

## Task Dependencies

```
Task 1 (Hybrid style directory + sprites)
  -> Task 2 (Author hybrid style JSON)
       -> Task 3 (TileServer config)
            -> Task 4 (Frontend: persistent style.load + STYLES)
                 -> Task 5 (Frontend: smart imagery toggle)
                      -> Task 6 (Frontend: hybrid guards + z-order)
                           -> Task 7 (Visual verification)
                                -> Task 8 (Review loop)
```

All sequential — each depends on the previous.

---

## Preamble (Every Task)

```
BEFORE starting work:
1. Read docs/pitfalls/implementation-pitfalls.md (especially #11: dragRotate)
2. Read the spec: docs/superpowers/specs/2026-04-09-hybrid-imagery-roads-design.md
3. Use var/function exclusively (NO let, const, arrow functions)
```

## Completion Check (Every Task)

```
BEFORE marking complete:
1. Verify git diff --stat shows only expected files
2. Commit with descriptive message
```

---

### Task 1: Hybrid Style Directory + Sprites

**Files:** Create tileserver/styles/hybrid/ directory, copy sprites from darkmatter

- [ ] Create directory and copy sprite files:

```bash
mkdir -p tileserver/styles/hybrid
cp tileserver/styles/darkmatter/sprite.json tileserver/styles/hybrid/
cp tileserver/styles/darkmatter/sprite.png tileserver/styles/hybrid/
cp tileserver/styles/darkmatter/sprite@2x.json tileserver/styles/hybrid/
cp tileserver/styles/darkmatter/sprite@2x.png tileserver/styles/hybrid/
```

- [ ] Commit:

```bash
git add tileserver/styles/hybrid/
git commit -m "feat(hybrid): create hybrid style directory with sprite files"
```

---

### Task 2: Author Hybrid Style JSON

**Files:** Create tileserver/styles/hybrid/style.local.json
**Spec ref:** Sections 1 and 4

This is the core task. Derive from darkmatter/style.local.json:

- [ ] **Step 1: Generate the hybrid style programmatically**

Write a Python script that reads darkmatter, filters layers, adds imagery source, restyles for satellite readability:

```bash
python3 -c "
import json

with open('tileserver/styles/darkmatter/style.local.json') as f:
    style = json.load(f)

# Keep layers where source-layer is in our whitelist
keep_source_layers = {'transportation', 'transportation_name', 'place', 'boundary', 'water_name'}
kept_layers = [l for l in style['layers'] if l.get('source-layer') in keep_source_layers]

# Add imagery raster as first layer
imagery_layer = {
    'id': 'imagery-base',
    'type': 'raster',
    'source': 'imagery',
    'paint': {'raster-opacity': 1.0}
}

# Build new layer list
new_layers = [imagery_layer] + kept_layers

# Add imagery to sources
style['sources']['imagery'] = {
    'type': 'raster',
    'url': 'mbtiles://{imagery}'
}

# Restyle all text layers for satellite readability (white text, dark halo)
for layer in new_layers:
    if layer.get('type') == 'symbol':
        paint = layer.setdefault('paint', {})
        layout = layer.setdefault('layout', {})
        paint['text-color'] = '#ffffff'
        paint['text-halo-color'] = 'rgba(0,0,0,0.7)'
        paint['text-halo-width'] = 1.5
        # Water labels get italic
        if layer.get('source-layer') == 'water_name':
            paint['text-color'] = 'rgba(255,255,255,0.8)'
            paint['text-halo-color'] = 'rgba(0,0,0,0.5)'

    # Restyle road lines for satellite readability
    if layer.get('type') == 'line' and layer.get('source-layer') == 'transportation':
        paint = layer.setdefault('paint', {})
        lid = layer['id']
        # Casings: dark semi-transparent
        if 'casing' in lid:
            paint['line-color'] = 'rgba(0,0,0,0.3)'
        # Motorway fills: warm yellow-orange
        elif 'motorway' in lid and 'casing' not in lid:
            paint['line-color'] = 'rgba(232,166,62,0.8)'
        # Major roads: semi-transparent white
        elif 'major' in lid and 'casing' not in lid:
            paint['line-color'] = 'rgba(255,255,255,0.6)'
        # Minor/path: subtle white
        elif 'minor' in lid or 'path' in lid:
            paint['line-color'] = 'rgba(255,255,255,0.3)'
        # Railway: dashed white
        elif 'rail' in lid:
            paint['line-color'] = 'rgba(255,255,255,0.4)'
        # Everything else
        else:
            paint['line-color'] = 'rgba(255,255,255,0.5)'

    # Restyle boundary lines
    if layer.get('type') == 'line' and layer.get('source-layer') == 'boundary':
        paint = layer.setdefault('paint', {})
        paint['line-color'] = 'rgba(255,255,255,0.3)'
        paint['line-dasharray'] = [3, 2]

    # Remove fill layers within transportation (pier areas)
    # Keep them but make transparent — piers visible in imagery
    if layer.get('type') == 'fill' and layer.get('source-layer') == 'transportation':
        paint = layer.setdefault('paint', {})
        paint['fill-opacity'] = 0

style['layers'] = new_layers

with open('tileserver/styles/hybrid/style.local.json', 'w') as f:
    json.dump(style, f, indent=2)

print(f'Wrote hybrid style: {len(new_layers)} layers')
"
```

- [ ] **Step 2: Verify the style JSON is valid**

```bash
python3 -c "
import json
with open('tileserver/styles/hybrid/style.local.json') as f:
    d = json.load(f)
print('Layers:', len(d['layers']))
print('Sources:', list(d['sources'].keys()))
print('First layer:', d['layers'][0]['id'])
for l in d['layers']:
    print(f'  {l[\"id\"]:45s} type={l[\"type\"]:8s} source-layer={l.get(\"source-layer\", \"-\")}')
"
```

Expected: ~35 layers, first layer is `imagery-base`, sources include both `openmaptiles` and `imagery`.

- [ ] **Step 3: Commit**

```bash
git add tileserver/styles/hybrid/style.local.json
git commit -m "feat(hybrid): author hybrid style JSON — imagery base + roads/labels/boundaries"
```

---

### Task 3: TileServer Config

**Files:** Modify tileserver/config.json

- [ ] Add hybrid style entry:

In `tileserver/config.json`, add `hybrid` to the `styles` section after darkmatter:

```json
"hybrid": {
  "style": "hybrid/style.local.json",
  "tilejson": {
    "bounds": [-124.8, 31.3, -102.0, 49.0]
  }
}
```

- [ ] Restart tileserver and verify:

```bash
docker compose up -d --force-recreate tileserver
sleep 5
curl -s http://localhost:8090/styles/hybrid/style.json | python3 -c "import json,sys; d=json.load(sys.stdin); print('OK:', len(d['layers']), 'layers')"
```

- [ ] Commit:

```bash
git add tileserver/config.json
git commit -m "feat(hybrid): add hybrid style to TileServer config"
```

---

### Task 4: Frontend — Persistent style.load + STYLES Object

**Files:** Modify frontend/app.js
**Spec ref:** Section 2 (persistent handler, STYLES object)

- [ ] **Step 1: Add `hybrid` to STYLES and `previousStyle` state variable**

At line 15-18, change STYLES:
```js
var STYLES = {
  positron:   '/tiles/styles/positron/style.json',
  darkmatter: '/tiles/styles/darkmatter/style.json',
  hybrid:     '/tiles/styles/hybrid/style.json'
};
```

In the STATE section (~line 34), add:
```js
var previousStyle = 'positron';
```

- [ ] **Step 2: Replace scattered map.once('style.load') with persistent handler**

In `initMap()`, after `map = new maplibregl.Map(...)`, add a persistent style.load handler:
```js
map.on('style.load', function () {
  addPlaceholderSources();
  syncLayerVisibility();
});
```

Remove the `map.once('style.load', ...)` calls from:
- The basemap radio handler (~line 716)
- Any other location that uses `map.once('style.load')`

The `map.on('load', ...)` handler in initMap (which calls initFreeLookCamera etc.) stays — that's the initial load, not style swaps.

- [ ] **Step 3: Commit**

```bash
git add frontend/app.js
git commit -m "feat(hybrid): add STYLES.hybrid, previousStyle, persistent style.load handler"
```

---

### Task 5: Frontend — Smart Imagery Toggle

**Files:** Modify frontend/app.js
**Spec ref:** Section 2 (imagery checkbox, basemap radio, opacity slider)

- [ ] **Step 1: Replace imagery checkbox handler**

Replace the imagery checkbox handler (~line 726-729) with the hybrid-aware version:

```js
imageryCheckbox.addEventListener('change', function () {
  if (this.checked) {
    previousStyle = currentStyle;
    currentStyle = 'hybrid';
    map.setStyle(STYLES.hybrid);
  } else {
    if (previousStyle === 'hybrid') previousStyle = 'positron';
    currentStyle = previousStyle;
    map.setStyle(STYLES[currentStyle]);
  }
  opacityRow.classList.toggle('visible', this.checked);
  var imageryToggles = document.getElementById('imagery-toggles');
  if (imageryToggles) imageryToggles.style.display = this.checked ? 'none' : '';
});
```

- [ ] **Step 2: Replace basemap radio handler**

Replace the basemap radio handler (~line 711-721):

```js
radios.forEach(function (radio) {
  radio.addEventListener('change', function () {
    var imageryCheckbox = document.getElementById('toggle-imagery');
    if (imageryCheckbox && imageryCheckbox.checked) {
      imageryCheckbox.checked = false;
      opacityRow.classList.remove('visible');
      var imageryToggles = document.getElementById('imagery-toggles');
      if (imageryToggles) imageryToggles.style.display = '';
    }
    previousStyle = this.value;
    currentStyle = this.value;
    map.setStyle(STYLES[currentStyle]);
  });
});
```

Note: no `map.once('style.load')` needed — the persistent handler from Task 4 fires automatically.

- [ ] **Step 3: Update opacity slider for hybrid mode**

Replace the opacity slider handler (~line 734-740):

```js
opacitySlider.addEventListener('input', function () {
  var val = parseInt(this.value, 10);
  opacityLabel.textContent = val + '%';
  if (currentStyle === 'hybrid' && map.getLayer('imagery-base')) {
    map.setPaintProperty('imagery-base', 'raster-opacity', val / 100);
  } else if (map.getLayer('imagery-layer')) {
    map.setPaintProperty('imagery-layer', 'raster-opacity', val / 100);
  }
});
```

- [ ] **Step 4: Commit**

```bash
git add frontend/app.js
git commit -m "feat(hybrid): smart imagery toggle — setStyle swap to/from hybrid"
```

---

### Task 6: Frontend — Hybrid Guards + Z-Order

**Files:** Modify frontend/app.js
**Spec ref:** Section 2 (addPlaceholderSources guard, syncLayerVisibility, public lands z-order)

- [ ] **Step 1: Guard imagery-layer creation in addPlaceholderSources**

Find where `imagery-layer` is created in `addPlaceholderSources()`. Add a hybrid guard:

Change:
```js
if (!map.getLayer('imagery-layer')) {
```
To:
```js
if (currentStyle !== 'hybrid' && !map.getLayer('imagery-layer')) {
```

This prevents creating a duplicate raster layer when the hybrid style already has `imagery-base`.

- [ ] **Step 2: Update syncLayerVisibility for hybrid mode**

In `syncLayerVisibility()` (~line 850-878), replace:
```js
setLayerVisibility('imagery-layer', imagery);
```
With:
```js
if (currentStyle !== 'hybrid') {
  setLayerVisibility('imagery-layer', imagery);
}
```

- [ ] **Step 3: Update public lands z-order anchor for hybrid mode**

In `addPlaceholderSources()`, where public-lands-fill is added with `before: 'route-line'`, add hybrid-aware anchor logic:

```js
var publicLandsAnchor = 'route-line';
if (currentStyle === 'hybrid') {
  var hybridLayers = map.getStyle().layers;
  for (var i = 0; i < hybridLayers.length; i++) {
    if (hybridLayers[i]['source-layer'] === 'transportation') {
      publicLandsAnchor = hybridLayers[i].id;
      break;
    }
  }
}
```

Then use `publicLandsAnchor` instead of the hardcoded `'route-line'` in all three public lands addLayer calls.

- [ ] **Step 4: Commit**

```bash
git add frontend/app.js
git commit -m "feat(hybrid): hybrid guards — imagery-layer skip, syncLayerVisibility, z-order anchor"
```

---

### Task 7: Visual Verification

**Prerequisites:** Tasks 1-6 complete, services restarted

- [ ] **Step 1: Restart frontend**

```bash
docker compose up -d --force-recreate frontend
```

- [ ] **Step 2: Verify hybrid toggle works**

Open browser at http://localhost:8093. Check the "Aerial Imagery" box. The map should:
- Switch to hybrid style (imagery base + roads)
- Show semi-transparent road lines over satellite imagery
- Show white labels with dark halos
- Hide NAIP/Sentinel toggles

Uncheck imagery. Map should restore to previous basemap (positron/darkmatter).

- [ ] **Step 3: Take Playwright screenshots** (use the same pattern as public lands verification)

Navigate to Hoover Dam area, z9 and z12. Screenshot with hybrid active + terrain + public lands.

- [ ] **Step 4: Commit**

```bash
git commit --allow-empty -m "feat(hybrid): visual verification complete — roads over imagery working"
```

---

### Task 8: Review Loop

```
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Minimum 3 rounds.
```

**Checklist:**
- All var/function (no let/const/arrow)
- STYLES.hybrid URL correct (/tiles/styles/hybrid/style.json)
- imagery-base layer in style JSON, not imagery-layer
- mbtiles://{imagery} source URL (not local://)
- Persistent map.on('style.load') — no remaining map.once calls for style swap
- imagery-layer guard: currentStyle !== 'hybrid'
- syncLayerVisibility: hybrid branch skips imagery-layer
- Public lands anchor: uses hybrid road layer in hybrid mode
- Basemap radio: unchecks imagery, hides opacity row, restores NAIP/Sentinel toggles
- previousStyle defensive guard against 'hybrid'
- Opacity slider targets imagery-base in hybrid, imagery-layer otherwise

---

## Execution Recommendation

**Execute in this session (inline).** Reasoning:
- Tasks are purely sequential (no parallelism benefit)
- Style JSON authoring is mechanical (Python script derives from darkmatter)
- Frontend changes are well-specified with exact code from the adversarial-reviewed spec
- This session has full context — no fresh-session advantage
- Total implementation: ~30 minutes of focused work
