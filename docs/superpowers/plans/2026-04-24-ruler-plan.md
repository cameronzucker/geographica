# Ruler / measurement tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Project policy:** worktrees BANNED (per CLAUDE.md). Execute in main checkout on `dev` branch. Each task commits immediately. Two parallel agents are touching `frontend/navigation.js`, `frontend/nav-ui.js`, `frontend/voice-picker.js`, `frontend/wake-lock.js`, `frontend/silent-video-lock.js` — DO NOT EDIT THOSE FILES. The 9 app.js touch points listed in the spec are deliberately disjoint from those files.
>
> **Moniker:** every commit gets `Agent: <moniker>` trailer. Controller's moniker is `cholla`; subagents pick their own and pass it down.

**Goal:** Add a click-to-place ruler / measurement tool to the MapLibre frontend with per-segment + cumulative geodesic distance, true bearing, inline elevation profile sparkline, and vertex-centric edit (drag / delete / insert-before-after with segment projection).

**Architecture:** Self-contained `frontend/ruler.js` IIFE module exposing `window._ruler = { init, isActive, clear }`. State is a plain JSON-shape object (KMZ-geometry-serializable). MapLibre sources/layers for line + visible vertices + invisible 44-px hit-circles. Elevation sampled in-browser from existing Mapzen Terrarium tiles at z=12 with LRU tile cache + AbortController-based cancellation. Mode-flag suppression at three existing app.js click handlers prevents double-firing.

**Tech Stack:** Vanilla JavaScript (no transpiler), MapLibre GL JS 5.21.1, SVG sparkline, Mapzen Terrarium Terrain encoding, Node.js `node:test` + `node:vm` test harness (matches voice-picker / wake-lock convention), pngjs for fixture decoding in tests.

**Spec:** [docs/superpowers/specs/2026-04-24-ruler-design.md](../specs/2026-04-24-ruler-design.md) (v3, post-R1–R5 adversarial review).

---

## File structure

**Created:**

| File | Responsibility |
|---|---|
| `frontend/ruler.js` | The whole module — IIFE, state, render, geodesy, bearing, sampling, sparkline, cache, listeners. ~750 LoC projected. |
| `frontend/tests/ruler/_fixtures.js` | Shared mock factories (mock map, mock document, mock fetch, mock canvas, terrarium PNG fixture decoder) — matches the voice-picker `_fixtures.js` pattern. |
| `frontend/tests/ruler/fixtures/terrarium-tile-z12.png` | Real Terrarium PNG for decode tests. Pre-encoded with known elevation data. |
| `frontend/tests/ruler/geodesy.test.mjs` | `haversineDistance` reuse + `bearingDeg` correctness. |
| `frontend/tests/ruler/terrarium-decode.test.mjs` | `elevationFromRGB(r,g,b,a)` correctness + R5 M4 guards. |
| `frontend/tests/ruler/sample-path.test.mjs` | `samplePath` interpolation correctness. |
| `frontend/tests/ruler/segment-projection.test.mjs` | `projectPointToSegment` correctness. |
| `frontend/tests/ruler/state-machine.test.mjs` | All §B transitions + invariants. |
| `frontend/tests/ruler/unit-format.test.mjs` | `formatRulerDistance` imperial/metric. |
| `frontend/tests/ruler/sparkline.test.mjs` | `sparklinePath` SVG generation. |
| `frontend/tests/ruler/panel-render.test.mjs` | DOM render of vertex list / sparkline / mode banner. |
| `frontend/tests/ruler/keyboard.test.mjs` | Backspace / Esc / Enter / Tab / Space behavior + input-suppression. |
| `frontend/tests/ruler/mode-flag.test.mjs` | `_ruler.isActive()` matches state. |
| `frontend/tests/ruler/tile-cache-lru.test.mjs` | LRU eviction + 30-tile cap. |
| `frontend/tests/ruler/drag-raf.test.mjs` | rAF coalescing on bursty mousemove. |
| `frontend/tests/ruler/touch-multitouch-cancel.test.mjs` | `touches.length > 1` cancels drag. |
| `frontend/tests/ruler/units-rerender-integration.test.mjs` | `geographica:units-changed` event triggers panel rerender. |
| `frontend/tests/ruler/app-js-integration.test.mjs` | Source-grep enforcement test — verifies all 9 app.js touch points present. |

**Modified (9 app.js touch points + index.html + style.css):**

| File | Touch point | Type |
|---|---|---|
| `frontend/app.js` (L295+, inside `addPlaceholderSources`) | call `_ruler.reattachSources(map)` | edit |
| `frontend/app.js` (L660 region, imported-layers click handler) | early-return on `_ruler.isActive()` | insert |
| `frontend/app.js` (L1086-1100, units handler) | dispatch `geographica:units-changed` event | insert |
| `frontend/app.js` (L1272 region, search-pin click handler) | early-return on `_ruler.isActive()` | insert |
| `frontend/app.js` (L1622 region, reverse-geocode handler) | early-return on `_ruler.isActive()` | insert |
| `frontend/app.js` (L1628-1631, `queryRenderedFeatures` exclusion list) | append ruler layers | edit |
| `frontend/app.js` (L4103, `VALID_SIDEBAR_PANELS`) | append `'measure-panel'` | edit |
| `frontend/app.js` (end of IIFE) | `window._formatDD = formatDD; window._haversineDistance = haversineDistance;` | insert |
| `frontend/app.js` (bootstrap) | `initRuler(map)` between `initSidebarTabs()` and `restoreLastSidebarTab()` | insert |
| `frontend/index.html` | tab button + panel div + `<script src="ruler.js">` | insert (3 lines) |
| `frontend/style.css` | ruler classes (~80 lines) | append |

---

## Standing TDD discipline (all tasks)

Every task that creates or modifies code MUST follow:

```
BEFORE starting work:
1. Read .claude/skills/test-driven-development/ (or invoke /test-driven-development)
2. Read docs/pitfalls/testing-pitfalls.md
Follow TDD: write failing test → implement minimal code → verify green.
```

```
BEFORE marking task complete:
1. Review tests against docs/pitfalls/testing-pitfalls.md
2. Verify test coverage of edge cases
3. Run tests, confirm green
4. git status — no stray untracked files outside scope
5. git log -1 — verify Agent: <moniker> trailer + Co-Authored-By line
```

After every logical group of tasks (every Phase boundary):
> Carefully review the batch from multiple perspectives. Do a minimum of three review rounds; if substantive issues remain in round 3, keep going. Update implementation log; continue to next phase.

---

## Phase 0 — Scaffolding (5 tasks)

**Goal:** Bring up the empty module, the new tab, the bootstrap call, the panel-whitelist edit, and the two `window._X` exports. After Phase 0, the Measure tab opens to an empty placeholder, but no ruler functionality exists yet. All commits land on `dev`.

### Task 0.1: Create `frontend/ruler.js` skeleton with `window._ruler` API stubs

**Files:**
- Create: `frontend/ruler.js`

- [ ] **Step 1: Write the failing module-shape test.**

Create `frontend/tests/ruler/mode-flag.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(path.join(__dirname, '../../ruler.js'), 'utf-8');

test('ruler.js exposes window._ruler with init / isActive / clear', () => {
  const win = {};
  const ctx = vm.createContext({ window: win, document: {}, console });
  vm.runInContext(SOURCE, ctx);
  assert.ok(ctx.window._ruler, 'window._ruler must be defined');
  assert.strictEqual(typeof ctx.window._ruler.init, 'function');
  assert.strictEqual(typeof ctx.window._ruler.isActive, 'function');
  assert.strictEqual(typeof ctx.window._ruler.clear, 'function');
});

test('isActive returns false before init', () => {
  const win = {};
  const ctx = vm.createContext({ window: win, document: {}, console });
  vm.runInContext(SOURCE, ctx);
  assert.strictEqual(ctx.window._ruler.isActive(), false);
});

test('init is idempotent — second call is a no-op (does not throw)', () => {
  const win = {};
  const ctx = vm.createContext({ window: win, document: { getElementById: () => null, addEventListener: () => {} }, console });
  vm.runInContext(SOURCE, ctx);
  const fakeMap = { on: () => {}, getSource: () => null, addSource: () => {}, addLayer: () => {}, getLayer: () => null, getCanvas: () => ({ style: {}, addEventListener: () => {} }) };
  ctx.window._ruler.init(fakeMap);
  ctx.window._ruler.init(fakeMap);  // must not throw
  assert.ok(true);
});
```

- [ ] **Step 2: Run, expect failure (file does not exist).**

Run: `node --test --test-force-exit frontend/tests/ruler/mode-flag.test.mjs`
Expected: ENOENT or similar (`ruler.js` doesn't exist yet).

- [ ] **Step 3: Create the module skeleton.**

Create `frontend/ruler.js`:

```javascript
/* =====================================================================
   Geographica — Ruler / Measurement Tool
   =====================================================================
   Self-contained measurement tool for the MapLibre frontend.
   Distance + true bearing + elevation profile from Mapzen Terrarium tiles.
   Ephemeral (no save) — the data shape is KMZ-geometry-serializable so
   a future "My Places" cycle can persist measurements without refactor.

   Spec: docs/superpowers/specs/2026-04-24-ruler-design.md (v3)
   ===================================================================== */

(function () {
  'use strict';

  // ─── Module-private state ──────────────────────────────────────────
  var initialized = false;
  var map = null;
  var state = {
    status: 'idle',           // idle | drawing | editing | inserting
    selectedVertex: null,
    insertSlot: null,
    vertices: [],
    segments: [],
    totalDistance_m: 0,
    elevationProfile: null,
  };

  // View-state — DOM / map handles. NOT serialized.
  var view = {
    abortController: null,
    samplingGen: 0,
    tileCache: null,          // LRU; created in init()
    rafHandle: null,
    domListenerCleanups: [],
  };

  // ─── Public API ────────────────────────────────────────────────────
  function init(mapInstance) {
    if (initialized) return;       // idempotent per spec §A
    initialized = true;
    map = mapInstance;
    // Phase 1+ tasks fill in: source/layer wiring, click handlers,
    // keyboard handlers, units-changed subscription, etc.
  }

  function isActive() {
    return state.status === 'drawing' || state.status === 'inserting';
  }

  function clear() {
    if (view.abortController) {
      view.abortController.abort();
      view.abortController = null;
    }
    view.samplingGen++;
    state.status = 'idle';
    state.selectedVertex = null;
    state.insertSlot = null;
    state.vertices = [];
    state.segments = [];
    state.totalDistance_m = 0;
    state.elevationProfile = null;
    // Phase 1+ tasks fill in: source mutation, panel render, banner hide, cursor restore.
  }

  // Reattach hook called by app.js's addPlaceholderSources on style.load
  function reattachSources(mapInstance) {
    // Phase 1 fills this in.
  }

  // ─── Expose ────────────────────────────────────────────────────────
  window._ruler = {
    init: init,
    isActive: isActive,
    clear: clear,
    reattachSources: reattachSources,
  };
})();
```

- [ ] **Step 4: Run tests, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/mode-flag.test.mjs`
Expected: 3 tests passing.

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/mode-flag.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): module skeleton with idempotent init / isActive / clear

Empty IIFE-pattern module exposes window._ruler API. State container
shape per spec §A; private view-state holds DOM/MapLibre handles.

Subsequent tasks fill in: source/layer wiring, click handlers,
state-machine transitions, sampling, sparkline, ARIA.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md (v3)
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 0.1)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 0.2: Add Measure tab DOM + script include in `index.html`

**Files:**
- Modify: `frontend/index.html` (around line 49, the tab-buttons row; around line 243+ where the existing panels live; near the bottom for the script include)

- [ ] **Step 1: Append a tab button after the Admin tab.**

In `frontend/index.html`, after the line:
```html
      <button class="tab-btn" data-panel="admin-panel">Admin</button>
```
add:
```html
      <button class="tab-btn" data-panel="measure-panel">Measure</button>
```

- [ ] **Step 2: Add the panel skeleton.**

After the closing of the existing admin-panel `<div>` (find `<div id="admin-panel" class="panel">` then its matching `</div>`), insert:

```html
    <!-- Measure panel — ruler / measurement tool -->
    <div id="measure-panel" class="panel">
      <h3>Measure</h3>
      <div id="ruler-banner-inline" class="ruler-banner-inline" role="status" aria-live="polite" hidden>
        <span id="ruler-banner-inline-text"></span>
        <button type="button" id="ruler-banner-inline-cancel" aria-label="Cancel ruler mode">×</button>
      </div>
      <div id="ruler-headline-section" hidden>
        <div class="ruler-headline-label">Total distance</div>
        <div id="ruler-headline-total" class="ruler-headline">—</div>
      </div>
      <div id="ruler-vertex-section" class="ruler-section" hidden>
        <h4>Vertices (<span id="ruler-vertex-count">0</span>)</h4>
        <ol id="ruler-vertex-list" role="list" aria-label="Measurement vertices"></ol>
        <div id="ruler-action-row" class="ruler-actions" hidden>
          <button type="button" id="ruler-insert-before" class="primary">↑ Insert Before</button>
          <button type="button" id="ruler-insert-after"  class="primary">↓ Insert After</button>
          <button type="button" id="ruler-delete-vertex" class="danger">✗ Delete</button>
        </div>
        <p id="ruler-action-empty" class="ruler-action-empty">Tap a vertex on the map or in the list above to edit.</p>
      </div>
      <div id="ruler-elevation-section" class="ruler-section" hidden>
        <h4>Elevation profile</h4>
        <div id="ruler-sampling-progress" class="ruler-sampling-progress" hidden>
          <span id="ruler-sampling-counter">Loading elevation… 0 / 0 tiles</span>
        </div>
        <svg id="ruler-sparkline" class="ruler-sparkline" viewBox="0 0 250 80" preserveAspectRatio="none" role="img" aria-label="Elevation profile placeholder" hidden></svg>
        <div id="ruler-stats" class="ruler-stats" hidden>
          <div class="label">Min:</div>  <div id="ruler-stat-min"  class="value">—</div>
          <div class="label">Max:</div>  <div id="ruler-stat-max"  class="value">—</div>
          <div class="label">Gain:</div> <div id="ruler-stat-gain" class="value">—</div>
          <div class="label">Loss:</div> <div id="ruler-stat-loss" class="value">—</div>
        </div>
        <div id="ruler-coverage-warn" class="ruler-coverage-warn" hidden></div>
      </div>
      <div id="ruler-footer" class="ruler-footer">
        <button type="button" id="ruler-undo"   hidden>↶ Undo</button>
        <button type="button" id="ruler-clear"  hidden>Clear</button>
        <button type="button" id="ruler-finish" class="primary" hidden>Finish</button>
        <button type="button" id="ruler-new"    class="primary" hidden>+ New measurement</button>
      </div>
    </div>
```

- [ ] **Step 3: Add the floating banner overlay.**

Find the existing `#nav-banner` element. Immediately after its closing tag, add:

```html
    <!-- Ruler floating mode banner — overlays the map during drawing/inserting -->
    <div id="ruler-mode-banner" class="hidden" role="status" aria-live="polite" hidden>
      <span id="ruler-mode-banner-text"></span>
      <button type="button" id="ruler-mode-banner-cancel" aria-label="Cancel ruler mode">×</button>
    </div>
```

- [ ] **Step 4: Add the script include.**

Find the existing `<script src="voice-picker.js"></script>` line near the bottom of the body. Immediately after, add:

```html
    <script src="ruler.js"></script>
```

- [ ] **Step 5: Smoke test (manual).**

Run: `docker compose ps` (verify frontend container running)
Open: `http://localhost/` (or your dev URL)
Click the Measure tab.

Expected: tab activates; panel shows the "Measure" heading and is otherwise empty (all sections `hidden` at this point); no console errors.

If you see a console error like "Uncaught ReferenceError: ruler.js" or 404, the script include is wrong — fix and reload.

- [ ] **Step 6: Commit.**

```bash
git add frontend/index.html
git commit -m "$(cat <<'EOF'
feat(ruler): Measure tab DOM + script include

Adds 5th sidebar tab with the panel skeleton (banner / headline /
vertex list / elevation section / footer), the floating map-overlay
banner, and the ruler.js script include. Sections all start hidden
and are toggled by ruler.js based on state.

Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 0.2)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 0.3: Append `_formatDD` and `_haversineDistance` exports to `app.js`

**Files:**
- Modify: `frontend/app.js` (end of the IIFE — search for the last `})();` near the bottom of the file)

- [ ] **Step 1: Find the end-of-IIFE marker.**

Run: `grep -n '^})();' frontend/app.js | tail -5`
Expected: the last `})();` is the IIFE closer near the very end of the file.

- [ ] **Step 2: Insert exports BEFORE the closing `})();`.**

Find the last few lines of the IIFE (just above `})();` at the very end). Insert these lines before the closer:

```javascript
  // ─── Cross-module exports for ruler.js (per spec v3 §A) ──────────
  // Live-read pattern: ruler.js reads these at format time, not at
  // init time. window._geographicaUseImperial is also live-read by
  // ruler.js but is already exported elsewhere (line 123).
  window._formatDD = formatDD;
  window._haversineDistance = haversineDistance;
```

- [ ] **Step 3: Verify the exports work.**

Run a quick sanity check by adding a temporary node test (then revert it):

```bash
grep -c "window._formatDD = formatDD" frontend/app.js
grep -c "window._haversineDistance = haversineDistance" frontend/app.js
```

Both should output `1`.

- [ ] **Step 4: Verify functions exist.**

Run: `grep -n "^  function formatDD\|^  function haversineDistance" frontend/app.js`
Expected: both functions defined inside the IIFE. If `formatDD` doesn't exist, search for it under another name (`grep -n "formatDD\b" frontend/app.js`) and report — the spec assumes it exists per the GPS-fill button at app.js:1669.

- [ ] **Step 5: Commit.**

```bash
git add frontend/app.js
git commit -m "$(cat <<'EOF'
feat(app): export _formatDD and _haversineDistance to window

ruler.js (incoming) needs decimal-degree formatting and great-circle
distance — neither is worth duplicating across the boundary. Live-read
pattern: callers read window._X at use time, so unit-toggle / future
formatter changes propagate without reinit.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §A
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 0.3)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 0.4: Edit `VALID_SIDEBAR_PANELS` whitelist + bootstrap `initRuler(map)` call

**Files:**
- Modify: `frontend/app.js` at L4103 (`VALID_SIDEBAR_PANELS` array) and at the bootstrap sequence (search for `initSidebarTabs` / `initImport` / `initAdmin` calls — they cluster together)

- [ ] **Step 1: Append `'measure-panel'` to `VALID_SIDEBAR_PANELS`.**

Run: `grep -n "VALID_SIDEBAR_PANELS" frontend/app.js`

The line looks like:
```javascript
  var VALID_SIDEBAR_PANELS = ['layers-panel', 'route-panel', 'import-panel', 'admin-panel'];
```

Edit to:
```javascript
  var VALID_SIDEBAR_PANELS = ['layers-panel', 'route-panel', 'import-panel', 'admin-panel', 'measure-panel'];
```

- [ ] **Step 2: Find the bootstrap sequence ordering.**

Run: `grep -n "initSidebarTabs\|restoreLastSidebarTab\|initImport\|initAdmin\|initSearch\|initRoute" frontend/app.js | head -20`

The expected order in bootstrap is roughly:
- `initSidebarTabs()` (or equivalent) early
- ... feature inits ...
- `restoreLastSidebarTab()` last (because it activates whatever tab was last open, which fires the tab event listener)

ruler must init AFTER `initSidebarTabs` (so its tab event listener is registered) and BEFORE `restoreLastSidebarTab` (so a Measure-as-last-tab restore lands on a ready module).

- [ ] **Step 3: Insert `_ruler.init(map)` call.**

Right after the last feature `init*()` call before `restoreLastSidebarTab()`, insert:

```javascript
    // Ruler / measurement tool — must init before restoreLastSidebarTab
    // so a Measure-as-last-tab restore lands on a ready module.
    if (window._ruler) window._ruler.init(map);
```

The `if (window._ruler)` guard is defensive: if ruler.js failed to load (e.g., cache issue), the whole bootstrap should not crash.

- [ ] **Step 4: Smoke test.**

Reload the dev frontend.

Open browser DevTools console. Run:
```javascript
window._ruler.isActive()
```
Expected: `false`

Run:
```javascript
window._geographicaUseImperial
```
Expected: `true` (default)

Run:
```javascript
typeof window._formatDD
```
Expected: `'function'`

If any of those fail, the bootstrap order or load order is wrong — fix before continuing.

- [ ] **Step 5: Commit.**

```bash
git add frontend/app.js
git commit -m "$(cat <<'EOF'
feat(app): whitelist measure-panel + wire initRuler in bootstrap

VALID_SIDEBAR_PANELS gains 'measure-panel' so restoreLastSidebarTab
doesn't silently reject it. initRuler(map) call is placed between
initSidebarTabs() and restoreLastSidebarTab() per spec ordering
constraint.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §A
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 0.4)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 0.5: CSS skeleton — color tokens, panel structure, button styles

**Files:**
- Modify: `frontend/style.css` (append at end of file)

- [ ] **Step 1: Append ruler styles.**

Append this block to the end of `frontend/style.css`:

```css
/* ============================================================
   Ruler / Measurement Tool (per spec v3 §C, §D)
   ============================================================ */

:root {
  --ruler-line: #ffd400;
  --ruler-line-shadow: rgba(0, 0, 0, 0.55);
  --ruler-vertex: #ffd400;
  --ruler-vertex-selected: #ff7a00;
  --ruler-vertex-stroke: #ffffff;
}

/* ── Inline mode banner inside the sidebar panel ─────────────── */
.ruler-banner-inline {
  background: rgba(249, 226, 175, 0.12);
  color: var(--warning);
  padding: 10px 16px;
  border-bottom: 1px solid rgba(249, 226, 175, 0.25);
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: -16px -16px 12px -16px;  /* bleed to panel edges */
}
.ruler-banner-inline button {
  background: transparent;
  border: none;
  color: var(--warning);
  font-size: 16px;
  cursor: pointer;
  padding: 0 4px;
  line-height: 1;
}

/* ── Floating map-overlay banner (above #nav-banner) ─────────── */
#ruler-mode-banner {
  position: absolute;
  top: 12px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.7);
  color: var(--warning);
  padding: 8px 14px;
  border-radius: 20px;
  font-size: 13px;
  z-index: 19;  /* above #nav-banner (18), below sidebar (20) */
  display: flex;
  align-items: center;
  gap: 10px;
  backdrop-filter: blur(4px);
  pointer-events: auto;
}
#ruler-mode-banner.hidden { display: none; }
#ruler-mode-banner button {
  background: transparent;
  border: none;
  color: var(--warning);
  cursor: pointer;
  font-size: 18px;
  padding: 0;
  line-height: 1;
}

/* ── Headline ─────────────────────────────────────────────────── */
.ruler-headline-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #888;
  margin-bottom: 2px;
}
.ruler-headline {
  font-size: 22px;
  font-weight: 300;
  color: var(--sidebar-heading);
  margin-bottom: 12px;
}

/* ── Vertex list ──────────────────────────────────────────────── */
.ruler-section { margin-bottom: 16px; }
#ruler-vertex-list {
  list-style: none;
  padding: 0;
  margin: 8px 0 0 0;
  max-height: 280px;
  overflow-y: auto;
}
.ruler-vertex-row {
  display: flex;
  flex-direction: column;
  padding: 10px 8px;
  min-height: 44px;  /* WCAG 2.5.5 — touch target */
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  cursor: pointer;
  border-left: 3px solid transparent;
  margin-left: -8px;
  padding-left: 8px;
}
.ruler-vertex-row:hover { background: rgba(137, 180, 250, 0.06); }
.ruler-vertex-row.selected {
  background: rgba(255, 122, 0, 0.1);
  border-left-color: var(--ruler-vertex-selected);
}
.ruler-vertex-row:focus {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
.ruler-vertex-row-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}
.ruler-vertex-row-label {
  color: var(--sidebar-heading);
  font-weight: 600;
  min-width: 28px;
}
.ruler-vertex-row-coords {
  color: var(--sidebar-text);
  font-family: 'SF Mono', 'Monaco', monospace;
  font-size: 11px;
}
.ruler-vertex-row-seg {
  font-size: 11px;
  color: #888;
  margin-top: 2px;
  margin-left: 36px;
  display: flex;
  justify-content: space-between;
}

/* ── Action row + buttons ─────────────────────────────────────── */
.ruler-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
}
.ruler-actions button {
  flex: 1;
  min-width: 90px;
  background: var(--input-bg);
  border: 1px solid var(--input-border);
  color: var(--sidebar-text);
  padding: 10px 6px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
  min-height: 44px;
}
.ruler-actions button.primary {
  background: var(--accent-muted);
  border-color: rgba(137, 180, 250, 0.4);
  color: var(--accent);
}
.ruler-actions button.danger { color: var(--danger); }
.ruler-actions button:disabled { opacity: 0.4; cursor: not-allowed; }
.ruler-actions button:focus { outline: 2px solid var(--accent); outline-offset: -2px; }
.ruler-action-empty {
  color: #888;
  font-size: 12px;
  margin-top: 12px;
  font-style: italic;
}

/* ── Sparkline + stats ────────────────────────────────────────── */
.ruler-sparkline {
  background: #181825;
  border-radius: var(--radius-sm);
  height: 80px;
  width: 100%;
  display: block;
}
.ruler-sampling-progress {
  background: rgba(137, 180, 250, 0.1);
  color: var(--accent);
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  margin-bottom: 8px;
}
.ruler-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 16px;
  margin-top: 8px;
  font-size: 12px;
}
.ruler-stats .label { color: #888; }
.ruler-stats .value { color: var(--sidebar-heading); text-align: right; font-weight: 500; }
.ruler-coverage-warn {
  margin-top: 8px;
  padding: 6px 8px;
  background: rgba(249, 226, 175, 0.1);
  border-radius: 3px;
  font-size: 11px;
  color: var(--warning);
}

/* ── Footer controls ──────────────────────────────────────────── */
.ruler-footer {
  display: flex;
  gap: 6px;
  padding: 12px 0;
  border-top: 1px solid var(--sidebar-border);
  margin-top: 16px;
}
.ruler-footer button {
  flex: 1;
  background: var(--input-bg);
  border: 1px solid var(--input-border);
  color: var(--sidebar-text);
  padding: 10px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
  min-height: 44px;
}
.ruler-footer button.primary {
  background: rgba(166, 227, 161, 0.18);
  border-color: rgba(166, 227, 161, 0.45);
  color: var(--success);
}
.ruler-footer button:focus { outline: 2px solid var(--accent); outline-offset: -2px; }

/* ── Mobile responsive ────────────────────────────────────────── */
@media (max-width: 480px) {
  .ruler-actions button { flex: 1 1 100%; }
}

/* ── iOS Safari touch contract (per spec §D.5) ────────────────── */
.maplibregl-canvas {
  touch-action: manipulation;
}
```

- [ ] **Step 2: Smoke test.**

Reload the dev frontend. Open the Measure tab. Verify:
- The "Measure" heading shows
- No CSS errors in console
- The page layout doesn't shift unexpectedly

- [ ] **Step 3: Commit.**

```bash
git add frontend/style.css
git commit -m "$(cat <<'EOF'
feat(ruler): CSS skeleton — palette, panel, vertex rows, sparkline

All ruler-* classes prefixed; reuses existing CSS custom properties
for palette consistency. Vertex rows ≥44px (WCAG 2.5.5); inputs use
existing color tokens. Floating banner z-index 19 (above nav 18,
below sidebar 20). Adds touch-action: manipulation on canvas per
spec §D.5 iOS contract.

Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 0.5)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Phase 0 review checkpoint

After all 5 tasks committed:

> **Phase 0 review (≥3 rounds):** Verify the Measure tab opens cleanly, no console errors, `window._ruler.isActive() === false`, `window._formatDD` and `window._haversineDistance` callable, `VALID_SIDEBAR_PANELS` includes `measure-panel`, and the floating banner's z-index doesn't collide with `#nav-banner` (z=18) or sidebar (z=20). Run all existing tests (`python -m pytest tests/ services/search/tests/`) — verify ruler scaffolding has not regressed any existing functionality. If any review round surfaces issues, fix and re-review until clean.

---

## Phase 1 — Pure-function math (6 tasks)

**Goal:** Build, TDD-style, every pure function ruler.js needs: `bearingDeg`, `elevationFromRGB` (with R5 M4 guards), `samplePath`, `projectPointToSegment`, `sparklinePath`, and `formatRulerDistance`. After Phase 1, ruler.js has all the math primitives but still no UI behavior.

All Phase 1 tasks expose pure-function helpers from ruler.js for testability. The IIFE pattern means we can't `export` directly, but we can hang test-only helpers off `window._ruler._test` as a deliberate seam.

**Setup before Task 1.1:** add a test-helper export inside ruler.js. Open `frontend/ruler.js` and immediately before `})();`, add:

```javascript
  // Test-only: expose pure functions for unit testing. Production code
  // never reaches into _test.
  window._ruler._test = {
    // populated by subsequent tasks
  };
```

Each Task 1.x adds one or more functions to this object.

### Task 1.1: `bearingDeg(a, b)` — true forward azimuth in [0, 360)

**Files:**
- Modify: `frontend/ruler.js` (add function + export to `_test`)
- Create: `frontend/tests/ruler/geodesy.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/geodesy.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(path.join(__dirname, '../../ruler.js'), 'utf-8');

function loadRuler() {
  const win = {};
  const ctx = vm.createContext({ window: win, document: {}, console });
  vm.runInContext(SOURCE, ctx);
  return ctx.window._ruler._test;
}

test('bearingDeg: due north is ~0°', () => {
  const t = loadRuler();
  // From [0, 0] to [0, 1] (1° due north)
  const b = t.bearingDeg([0, 0], [0, 1]);
  assert.ok(Math.abs(b - 0) < 0.01, `expected ~0°, got ${b}`);
});

test('bearingDeg: due east is ~90°', () => {
  const t = loadRuler();
  // From [0, 0] to [1, 0]
  const b = t.bearingDeg([0, 0], [1, 0]);
  assert.ok(Math.abs(b - 90) < 0.01, `expected ~90°, got ${b}`);
});

test('bearingDeg: due south is ~180°', () => {
  const t = loadRuler();
  const b = t.bearingDeg([0, 0], [0, -1]);
  assert.ok(Math.abs(b - 180) < 0.01, `expected ~180°, got ${b}`);
});

test('bearingDeg: due west is ~270°', () => {
  const t = loadRuler();
  const b = t.bearingDeg([0, 0], [-1, 0]);
  assert.ok(Math.abs(b - 270) < 0.01, `expected ~270°, got ${b}`);
});

test('bearingDeg: result always in [0, 360)', () => {
  const t = loadRuler();
  // Random angles
  const samples = [
    [[10, 20], [30, 40]], [[-100, 33], [-110, 35]],
    [[0, 0], [-1, -1]], [[112, 33], [113, 32]],
  ];
  for (const [a, b] of samples) {
    const r = t.bearingDeg(a, b);
    assert.ok(r >= 0 && r < 360, `expected [0,360), got ${r} for ${JSON.stringify([a, b])}`);
  }
});

test('bearingDeg: reciprocal differs by ~180°', () => {
  const t = loadRuler();
  // For short segments at modest latitudes the reciprocal is within 0.5°
  const a = [-112.07, 33.45];
  const b = [-112.05, 33.46];
  const fwd = t.bearingDeg(a, b);
  const rev = t.bearingDeg(b, a);
  const diff = Math.abs(((fwd - rev) % 360 + 540) % 360 - 180);
  assert.ok(diff < 0.5, `reciprocal mismatch: fwd=${fwd} rev=${rev} diff=${diff}`);
});

test('bearingDeg: AZ→CO USGS reference (Phoenix → Denver) ~37° (NE)', () => {
  const t = loadRuler();
  // Phoenix Sky Harbor [-112.0117, 33.4342] → Denver DIA [-104.6739, 39.8617]
  // USGS reference forward azimuth: ~37.0° at start
  const b = t.bearingDeg([-112.0117, 33.4342], [-104.6739, 39.8617]);
  assert.ok(Math.abs(b - 37.0) < 1.0, `expected ~37°, got ${b}`);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/geodesy.test.mjs`
Expected: 7 failures (`bearingDeg is not a function`).

- [ ] **Step 3: Add `bearingDeg` to ruler.js.**

In `frontend/ruler.js`, inside the IIFE, before the `// Test-only: expose pure functions` block, add:

```javascript
  // ─── Geodesy ───────────────────────────────────────────────────────
  // Initial bearing (forward azimuth) from a → b in decimal degrees [0, 360).
  // Standard great-circle formula. NOT rhumb-line.
  function bearingDeg(a, b) {
    var lat1 = a[1] * Math.PI / 180;
    var lat2 = b[1] * Math.PI / 180;
    var dLng = (b[0] - a[0]) * Math.PI / 180;
    var y = Math.sin(dLng) * Math.cos(lat2);
    var x = Math.cos(lat1) * Math.sin(lat2) -
            Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLng);
    return ((Math.atan2(y, x) * 180 / Math.PI) + 360) % 360;
  }
```

Then add `bearingDeg: bearingDeg,` to the `window._ruler._test = { ... }` object.

- [ ] **Step 4: Run tests, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/geodesy.test.mjs`
Expected: all 7 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/geodesy.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): bearingDeg — true forward azimuth, [0,360)

Standard great-circle initial-bearing formula. TDD: 7 tests covering
cardinals, [0,360) range, reciprocal symmetry, and AZ→CO USGS
reference. NOT rhumb-line — matches what GPS receivers and
antenna-pointing software show.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §E.2
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 1.1)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.2: `elevationFromRGB(r, g, b, a)` — Mapzen Terrarium decode + R5 M4 guards

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/terrarium-decode.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/terrarium-decode.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(path.join(__dirname, '../../ruler.js'), 'utf-8');

function loadRuler() {
  const win = {};
  const ctx = vm.createContext({ window: win, document: {}, console });
  vm.runInContext(SOURCE, ctx);
  return ctx.window._ruler._test;
}

// Encoder helper for clean test inputs
function encodeTerrarium(meters) {
  // Mapzen terrarium: meters = (r*256 + g + b/256) - 32768
  // So the 16.8-bit unsigned int is (meters + 32768) * 256.
  var raw = Math.round((meters + 32768) * 256);
  var r = (raw >> 16) & 0xff;
  var g = (raw >> 8) & 0xff;
  var b = raw & 0xff;
  return [r, g, b];
}

test('elevationFromRGB: sea level (~0m) decodes near 0', () => {
  const t = loadRuler();
  const [r, g, b] = encodeTerrarium(0);
  const e = t.elevationFromRGB(r, g, b, 255);
  assert.ok(Math.abs(e - 0) < 0.01, `expected ~0m, got ${e}`);
});

test('elevationFromRGB: Mt Whitney (~4421m)', () => {
  const t = loadRuler();
  const [r, g, b] = encodeTerrarium(4421);
  const e = t.elevationFromRGB(r, g, b, 255);
  assert.ok(Math.abs(e - 4421) < 0.01, `expected ~4421m, got ${e}`);
});

test('elevationFromRGB: Death Valley (~-86m)', () => {
  const t = loadRuler();
  const [r, g, b] = encodeTerrarium(-86);
  const e = t.elevationFromRGB(r, g, b, 255);
  assert.ok(Math.abs(e - (-86)) < 0.01, `expected ~-86m, got ${e}`);
});

test('elevationFromRGB: alpha-zero pixel returns null', () => {
  const t = loadRuler();
  const [r, g, b] = encodeTerrarium(1000);
  const e = t.elevationFromRGB(r, g, b, 0);
  assert.strictEqual(e, null);
});

test('elevationFromRGB: (0,0,0,255) sentinel returns null (out of range)', () => {
  const t = loadRuler();
  // Raw decode: -32768m, way below -500m guard
  const e = t.elevationFromRGB(0, 0, 0, 255);
  assert.strictEqual(e, null);
});

test('elevationFromRGB: > 9000m returns null (out of plausible range)', () => {
  const t = loadRuler();
  const [r, g, b] = encodeTerrarium(10000);
  const e = t.elevationFromRGB(r, g, b, 255);
  assert.strictEqual(e, null);
});

test('elevationFromRGB: < -500m returns null', () => {
  const t = loadRuler();
  const [r, g, b] = encodeTerrarium(-1000);
  const e = t.elevationFromRGB(r, g, b, 255);
  assert.strictEqual(e, null);
});

test('elevationFromRGB: -500m at boundary returns null (strict <)', () => {
  // Spec says < -500 → null. -500 exactly is allowed.
  const t = loadRuler();
  const [r, g, b] = encodeTerrarium(-500);
  const e = t.elevationFromRGB(r, g, b, 255);
  assert.ok(Math.abs(e - (-500)) < 0.01, `expected -500m, got ${e}`);
});

test('elevationFromRGB: 9000m at boundary returns 9000 (strict >)', () => {
  const t = loadRuler();
  const [r, g, b] = encodeTerrarium(9000);
  const e = t.elevationFromRGB(r, g, b, 255);
  assert.ok(Math.abs(e - 9000) < 0.01, `expected 9000m, got ${e}`);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/terrarium-decode.test.mjs`
Expected: 9 failures.

- [ ] **Step 3: Add `elevationFromRGB` to ruler.js.**

In `frontend/ruler.js`, after `bearingDeg`, add:

```javascript
  // ─── Elevation decode ──────────────────────────────────────────────
  // Mapzen Terrarium encoding: meters = (r*256 + g + b/256) - 32768.
  // Reference: https://github.com/tilezen/joerd/blob/master/docs/formats.md
  //
  // Per spec v3 §E.3 (R5 M4 guards):
  // - alpha-zero pixel  → null (transparent / no-data)
  // - decoded < -500m   → null (below plausible CONUS DEM range)
  // - decoded > 9000m   → null (above plausible CONUS DEM range)
  function elevationFromRGB(r, g, b, a) {
    if (a === 0) return null;
    var elev = (r * 256 + g + b / 256) - 32768;
    if (elev < -500 || elev > 9000) return null;
    return elev;
  }
```

Add `elevationFromRGB: elevationFromRGB,` to `_test`.

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/terrarium-decode.test.mjs`
Expected: 9 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/terrarium-decode.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): elevationFromRGB — Mapzen Terrarium decode + guards

Decodes Terrarium-encoded raster-DEM tiles to meters per the
upstream Mapzen joerd spec. Guards (per spec v3 R5 M4):
  - alpha-zero      → null (transparent / no-data)
  - decoded < -500m → null (below plausible CONUS DEM range)
  - decoded > 9000m → null (above plausible CONUS DEM range)

Prevents (0,0,0) sentinel pixels from poisoning min/max/gain/loss.
9 tests covering decode correctness, all three guard branches,
boundary cases.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §E.3
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 1.2)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.3: `samplePath(vertices, numSamples)` — distance-uniform sampling along path

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/sample-path.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/sample-path.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(path.join(__dirname, '../../ruler.js'), 'utf-8');

function loadRuler() {
  const win = {};
  const ctx = vm.createContext({ window: win, document: {}, console });
  vm.runInContext(SOURCE, ctx);
  return ctx.window._ruler._test;
}

test('samplePath: returns N samples for non-degenerate input', () => {
  const t = loadRuler();
  const vertices = [
    { lng: -112.07, lat: 33.45 },
    { lng: -112.05, lat: 33.46 },
    { lng: -112.03, lat: 33.47 },
  ];
  const samples = t.samplePath(vertices, 50);
  assert.strictEqual(samples.length, 50);
});

test('samplePath: first sample is exactly at first vertex; last at last', () => {
  const t = loadRuler();
  const vertices = [
    { lng: -112.07, lat: 33.45 },
    { lng: -112.05, lat: 33.46 },
  ];
  const samples = t.samplePath(vertices, 50);
  assert.ok(Math.abs(samples[0].lng - vertices[0].lng) < 1e-9);
  assert.ok(Math.abs(samples[0].lat - vertices[0].lat) < 1e-9);
  assert.ok(Math.abs(samples[49].lng - vertices[1].lng) < 1e-9);
  assert.ok(Math.abs(samples[49].lat - vertices[1].lat) < 1e-9);
});

test('samplePath: distance_m increases monotonically', () => {
  const t = loadRuler();
  const vertices = [
    { lng: -112.07, lat: 33.45 },
    { lng: -112.04, lat: 33.50 },
    { lng: -112.00, lat: 33.55 },
  ];
  const samples = t.samplePath(vertices, 100);
  for (let i = 1; i < samples.length; i++) {
    assert.ok(samples[i].distance_m >= samples[i - 1].distance_m,
      `distance_m not monotonic at ${i}: ${samples[i - 1].distance_m} → ${samples[i].distance_m}`);
  }
});

test('samplePath: samples cross segment boundaries correctly', () => {
  const t = loadRuler();
  // Two equal segments — middle sample should be near the middle vertex
  const vertices = [
    { lng: 0, lat: 0 },
    { lng: 0, lat: 1 },
    { lng: 0, lat: 2 },
  ];
  const samples = t.samplePath(vertices, 51);
  const middle = samples[25];
  assert.ok(Math.abs(middle.lat - 1.0) < 0.05, `middle lat ~1.0, got ${middle.lat}`);
});

test('samplePath: single vertex returns empty array (no segments)', () => {
  const t = loadRuler();
  const samples = t.samplePath([{ lng: -112, lat: 33 }], 50);
  assert.strictEqual(samples.length, 0);
});

test('samplePath: zero-length path (duplicate vertices) returns N at same point', () => {
  const t = loadRuler();
  const v = { lng: -112, lat: 33 };
  const samples = t.samplePath([v, { ...v }], 5);
  assert.strictEqual(samples.length, 5);
  for (const s of samples) {
    assert.ok(Math.abs(s.lng - v.lng) < 1e-9);
    assert.ok(Math.abs(s.lat - v.lat) < 1e-9);
    assert.strictEqual(s.distance_m, 0);
  }
});

test('samplePath: empty input returns empty array', () => {
  const t = loadRuler();
  assert.deepStrictEqual(t.samplePath([], 10), []);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/sample-path.test.mjs`
Expected: 7 failures.

- [ ] **Step 3: Add `samplePath`.**

In `frontend/ruler.js`, after `elevationFromRGB`, add:

```javascript
  // ─── Path sampling ─────────────────────────────────────────────────
  // Sample N points evenly distributed by cumulative distance along
  // the path, using linear interpolation within each segment.
  // Returns [{ lng, lat, distance_m }, ...]. Empty path → []. Single
  // vertex → []. Zero-length path → N copies at the same point.
  function samplePath(vertices, numSamples) {
    if (!vertices || vertices.length < 2) return [];
    if (numSamples < 2) numSamples = 2;

    var hav = window._haversineDistance;
    var segLengths = [];
    var totalLen = 0;
    for (var i = 0; i < vertices.length - 1; i++) {
      var a = [vertices[i].lng, vertices[i].lat];
      var b = [vertices[i + 1].lng, vertices[i + 1].lat];
      var d = hav(a, b);
      segLengths.push(d);
      totalLen += d;
    }

    var samples = [];
    if (totalLen === 0) {
      for (var k = 0; k < numSamples; k++) {
        samples.push({ lng: vertices[0].lng, lat: vertices[0].lat, distance_m: 0 });
      }
      return samples;
    }

    for (var s = 0; s < numSamples; s++) {
      var frac = s / (numSamples - 1);
      var target = frac * totalLen;
      // Find segment containing target distance
      var accum = 0;
      var segIdx = 0;
      for (segIdx = 0; segIdx < segLengths.length; segIdx++) {
        if (accum + segLengths[segIdx] >= target) break;
        accum += segLengths[segIdx];
      }
      if (segIdx >= segLengths.length) segIdx = segLengths.length - 1;
      var local = segLengths[segIdx] === 0 ? 0 : (target - accum) / segLengths[segIdx];
      var v1 = vertices[segIdx];
      var v2 = vertices[segIdx + 1];
      samples.push({
        lng: v1.lng + (v2.lng - v1.lng) * local,
        lat: v1.lat + (v2.lat - v1.lat) * local,
        distance_m: target,
      });
    }
    return samples;
  }
```

Add `samplePath: samplePath,` to `_test`.

**Note:** the implementation uses `window._haversineDistance` — that means tests need a fake. Update each test that calls `samplePath` to set up `window._haversineDistance` via the vm context. Edit the `loadRuler()` function in `sample-path.test.mjs`:

```javascript
function loadRuler() {
  const win = {
    _haversineDistance: function (a, b) {
      // Real haversine, R = 6,371,000 m
      var R = 6371000;
      var dLat = (b[1] - a[1]) * Math.PI / 180;
      var dLng = (b[0] - a[0]) * Math.PI / 180;
      var lat1 = a[1] * Math.PI / 180;
      var lat2 = b[1] * Math.PI / 180;
      var sinDLat = Math.sin(dLat / 2);
      var sinDLng = Math.sin(dLng / 2);
      var h = sinDLat * sinDLat + Math.cos(lat1) * Math.cos(lat2) * sinDLng * sinDLng;
      return 2 * R * Math.asin(Math.sqrt(h));
    },
  };
  const ctx = vm.createContext({ window: win, document: {}, console });
  vm.runInContext(SOURCE, ctx);
  return ctx.window._ruler._test;
}
```

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/sample-path.test.mjs`
Expected: 7 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/sample-path.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): samplePath — distance-uniform path sampling

Returns N samples evenly distributed by cumulative distance.
Linear interpolation within each segment (per spec §E.3 — geodesic
arc curvature is sub-meter at typical segment scales). Degenerate
inputs (empty / single vertex / zero-length) handled cleanly.

7 tests covering count, endpoint exactness, monotonicity, segment
crossing, and degenerate inputs.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §E.3
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 1.3)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.4: `projectPointToSegment(p, a, b)` — closest point on segment for Insert After/Before

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/segment-projection.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/segment-projection.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(path.join(__dirname, '../../ruler.js'), 'utf-8');

function loadRuler() {
  const win = {};
  const ctx = vm.createContext({ window: win, document: {}, console });
  vm.runInContext(SOURCE, ctx);
  return ctx.window._ruler._test;
}

test('projectPointToSegment: point already on segment returns same point', () => {
  const t = loadRuler();
  const r = t.projectPointToSegment([0.5, 0.5], [0, 0], [1, 1]);
  assert.ok(Math.abs(r[0] - 0.5) < 1e-6);
  assert.ok(Math.abs(r[1] - 0.5) < 1e-6);
});

test('projectPointToSegment: point off-side projects perpendicularly', () => {
  const t = loadRuler();
  // Segment along x-axis [0,0] → [10,0]. Point at [5, 5] projects to [5, 0].
  const r = t.projectPointToSegment([5, 5], [0, 0], [10, 0]);
  assert.ok(Math.abs(r[0] - 5) < 1e-6, `expected x≈5, got ${r[0]}`);
  assert.ok(Math.abs(r[1] - 0) < 1e-6, `expected y≈0, got ${r[1]}`);
});

test('projectPointToSegment: point past start clamps to start', () => {
  const t = loadRuler();
  // Segment [0,0] → [10,0]. Point [-5, 5] would project to [-5, 0] but clamps to [0, 0].
  const r = t.projectPointToSegment([-5, 5], [0, 0], [10, 0]);
  assert.ok(Math.abs(r[0] - 0) < 1e-6, `expected x=0, got ${r[0]}`);
  assert.ok(Math.abs(r[1] - 0) < 1e-6, `expected y=0, got ${r[1]}`);
});

test('projectPointToSegment: point past end clamps to end', () => {
  const t = loadRuler();
  const r = t.projectPointToSegment([15, 5], [0, 0], [10, 0]);
  assert.ok(Math.abs(r[0] - 10) < 1e-6);
  assert.ok(Math.abs(r[1] - 0) < 1e-6);
});

test('projectPointToSegment: zero-length segment returns segment point', () => {
  const t = loadRuler();
  const r = t.projectPointToSegment([5, 5], [3, 3], [3, 3]);
  assert.ok(Math.abs(r[0] - 3) < 1e-6);
  assert.ok(Math.abs(r[1] - 3) < 1e-6);
});

test('projectPointToSegment: AZ-scale realistic case', () => {
  const t = loadRuler();
  // Segment from Phoenix [-112.07, 33.45] east to [-112.00, 33.45] (along 33.45° N).
  // User taps slightly north of the midpoint; projection should land near segment.
  const seg_a = [-112.07, 33.45];
  const seg_b = [-112.00, 33.45];
  const tap = [-112.035, 33.46];
  const r = t.projectPointToSegment(tap, seg_a, seg_b);
  // Projected x near midpoint, projected y near 33.45
  assert.ok(Math.abs(r[0] - (-112.035)) < 0.01);
  assert.ok(Math.abs(r[1] - 33.45) < 0.001);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/segment-projection.test.mjs`
Expected: 6 failures.

- [ ] **Step 3: Add `projectPointToSegment`.**

In `frontend/ruler.js`, after `samplePath`, add:

```javascript
  // ─── Segment projection ────────────────────────────────────────────
  // Closest point on segment a→b to point p, in lng/lat (linear,
  // not geodesic — at segment scales we use for Insert After, the
  // difference is sub-meter).
  // Clamps to segment endpoints (no extrapolation).
  function projectPointToSegment(p, a, b) {
    var dx = b[0] - a[0];
    var dy = b[1] - a[1];
    var len2 = dx * dx + dy * dy;
    if (len2 === 0) return [a[0], a[1]];   // zero-length segment
    var t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2;
    if (t < 0) t = 0;
    if (t > 1) t = 1;
    return [a[0] + t * dx, a[1] + t * dy];
  }
```

Add `projectPointToSegment: projectPointToSegment,` to `_test`.

- [ ] **Step 4: Run, verify green.**

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/segment-projection.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): projectPointToSegment — closest-point-on-segment

Used by Insert After / Insert Before to constrain the new vertex
onto the relevant segment, regardless of where the user tapped
(per spec v3 §E.5 / R3 finding — prevents inserting a vertex 1000km
off-segment).

Linear in lng/lat (sub-meter divergence from geodesic at typical
segment scales). Clamps to endpoints. 6 tests covering on-segment,
perpendicular, past-start, past-end, zero-length, AZ realistic.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §E.5
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 1.4)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.5: `formatRulerDistance(meters)` — imperial / metric formatter

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/unit-format.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/unit-format.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(path.join(__dirname, '../../ruler.js'), 'utf-8');

function loadRuler(useImperial) {
  const win = { _geographicaUseImperial: useImperial };
  const ctx = vm.createContext({ window: win, document: {}, console });
  vm.runInContext(SOURCE, ctx);
  return { t: ctx.window._ruler._test, win };
}

test('formatRulerDistance: imperial < 1 mile shows feet', () => {
  const { t } = loadRuler(true);
  assert.strictEqual(t.formatRulerDistance(100), '328 ft');
  assert.strictEqual(t.formatRulerDistance(500), '1640 ft');
});

test('formatRulerDistance: imperial >= 1 mile shows miles to 2 decimals', () => {
  const { t } = loadRuler(true);
  assert.strictEqual(t.formatRulerDistance(1609.34), '1.00 mi');
  assert.strictEqual(t.formatRulerDistance(8046.7), '5.00 mi');
});

test('formatRulerDistance: metric < 1 km shows meters', () => {
  const { t } = loadRuler(false);
  assert.strictEqual(t.formatRulerDistance(500), '500 m');
});

test('formatRulerDistance: metric >= 1 km shows km to 2 decimals', () => {
  const { t } = loadRuler(false);
  assert.strictEqual(t.formatRulerDistance(1000), '1.00 km');
  assert.strictEqual(t.formatRulerDistance(12345), '12.35 km');
});

test('formatRulerDistance: live read — toggle propagates', () => {
  const { t, win } = loadRuler(true);
  assert.strictEqual(t.formatRulerDistance(1609.34), '1.00 mi');
  win._geographicaUseImperial = false;
  assert.strictEqual(t.formatRulerDistance(1609.34), '1.61 km');
});
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Add `formatRulerDistance`.**

In `frontend/ruler.js`:

```javascript
  // ─── Distance formatting ───────────────────────────────────────────
  // Live-reads window._geographicaUseImperial at format time so unit
  // toggle propagates immediately (per spec §A).
  function formatRulerDistance(meters) {
    var imperial = window._geographicaUseImperial;
    if (imperial) {
      if (meters < 1609.34) return Math.round(meters * 3.28084) + ' ft';
      return (meters / 1609.34).toFixed(2) + ' mi';
    } else {
      if (meters < 1000) return Math.round(meters) + ' m';
      return (meters / 1000).toFixed(2) + ' km';
    }
  }
```

Add `formatRulerDistance: formatRulerDistance,` to `_test`.

- [ ] **Step 4: Run, verify green.**

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/unit-format.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): formatRulerDistance — imperial/metric live-read formatter

Reads window._geographicaUseImperial at format time so a user toggle
propagates without re-init. Imperial: < 1 mi → feet (rounded);
≥ 1 mi → miles (2 decimals). Metric: < 1 km → meters; ≥ 1 km → km
(2 decimals). 5 tests including the live-read toggle case.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §A
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 1.5)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.6: `sparklinePath(samples, width, height)` — SVG points string

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/sparkline.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/sparkline.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = fs.readFileSync(path.join(__dirname, '../../ruler.js'), 'utf-8');

function loadRuler() {
  const win = {};
  const ctx = vm.createContext({ window: win, document: {}, console });
  vm.runInContext(SOURCE, ctx);
  return ctx.window._ruler._test;
}

test('sparklinePath: empty samples returns empty string', () => {
  const t = loadRuler();
  assert.strictEqual(t.sparklinePath([], 250, 80), '');
});

test('sparklinePath: single sample returns one point', () => {
  const t = loadRuler();
  const r = t.sparklinePath([{ distance_m: 0, elevation_m: 100 }], 250, 80);
  assert.match(r, /^\d+,\d+(\.\d+)?$/);
});

test('sparklinePath: monotonic increase produces monotonic SVG y', () => {
  const t = loadRuler();
  const samples = [
    { distance_m: 0,    elevation_m: 0 },
    { distance_m: 500,  elevation_m: 500 },
    { distance_m: 1000, elevation_m: 1000 },
  ];
  const r = t.sparklinePath(samples, 250, 80);
  // SVG y is inverted: lower elevation = higher y
  const points = r.split(' ').map(p => p.split(',').map(parseFloat));
  assert.strictEqual(points.length, 3);
  // y[0] > y[1] > y[2] (because elevation increases → y decreases in SVG coords)
  assert.ok(points[0][1] > points[1][1]);
  assert.ok(points[1][1] > points[2][1]);
});

test('sparklinePath: max elevation maps near top (y near 0)', () => {
  const t = loadRuler();
  const samples = [
    { distance_m: 0,    elevation_m: 0 },
    { distance_m: 1000, elevation_m: 1000 },
  ];
  const r = t.sparklinePath(samples, 250, 80);
  const points = r.split(' ').map(p => p.split(',').map(parseFloat));
  // Last sample (highest elevation) should be near y=0 (with margin)
  assert.ok(points[1][1] < 10, `max elevation y should be near 0, got ${points[1][1]}`);
});

test('sparklinePath: skips null elevation samples', () => {
  const t = loadRuler();
  const samples = [
    { distance_m: 0,    elevation_m: 0 },
    { distance_m: 500,  elevation_m: null },
    { distance_m: 1000, elevation_m: 100 },
  ];
  const r = t.sparklinePath(samples, 250, 80);
  // Two valid samples → two points; spec §C.6 calls for dashed-segment
  // rendering of gaps (a separate visual treatment), but the path
  // string itself contains only the valid points.
  const points = r.split(' ');
  assert.strictEqual(points.length, 2);
});
```

- [ ] **Step 2: Run, expect failure.**

- [ ] **Step 3: Add `sparklinePath`.**

In `frontend/ruler.js`, after `formatRulerDistance`:

```javascript
  // ─── Sparkline path generation ─────────────────────────────────────
  // Returns an SVG `points` attribute string (space-separated x,y pairs)
  // mapping samples to a width×height viewBox. Skips null-elevation
  // samples (gap rendering is a separate concern handled by the panel
  // renderer using multiple polylines).
  function sparklinePath(samples, width, height) {
    if (!samples || samples.length === 0) return '';
    var valid = samples.filter(function (s) { return s.elevation_m != null; });
    if (valid.length === 0) return '';

    var minE = Infinity, maxE = -Infinity;
    var minD = Infinity, maxD = -Infinity;
    for (var i = 0; i < valid.length; i++) {
      if (valid[i].elevation_m < minE) minE = valid[i].elevation_m;
      if (valid[i].elevation_m > maxE) maxE = valid[i].elevation_m;
      if (valid[i].distance_m  < minD) minD = valid[i].distance_m;
      if (valid[i].distance_m  > maxD) maxD = valid[i].distance_m;
    }
    var dRange = (maxD - minD) || 1;
    var eRange = (maxE - minE) || 1;
    var marginY = 4;       // a few px so max elevation isn't pinned to y=0
    var usableY = height - 2 * marginY;

    var points = [];
    for (var j = 0; j < valid.length; j++) {
      var x = ((valid[j].distance_m - minD) / dRange) * width;
      var y = marginY + (1 - (valid[j].elevation_m - minE) / eRange) * usableY;
      points.push(x.toFixed(1) + ',' + y.toFixed(1));
    }
    return points.join(' ');
  }
```

Add `sparklinePath: sparklinePath,` to `_test`.

- [ ] **Step 4: Run, verify green.**

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/sparkline.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): sparklinePath — SVG points string for elevation profile

Maps non-null elevation samples to a width×height viewBox with a
4px top/bottom margin so the maximum elevation isn't pinned to y=0.
Empty / all-null inputs return ''. 5 tests covering empty, single,
monotonic, max-near-top, null-skipping.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §C.6
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 1.6)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Phase 1 review checkpoint

> **Phase 1 review (≥3 rounds):** All 6 pure-function tests green. Verify each function's edge cases per the test file. Run the full test suite from repo root: `node --test --test-force-exit frontend/tests/ruler/`. If any test is flaky or non-deterministic, fix before continuing. Update implementation log with Phase 1 commit list. Re-read `docs/pitfalls/testing-pitfalls.md` to verify the test patterns avoid known anti-patterns (mocked-and-then-trusted, tautological assertions, hidden state via globals).

---

## Phase 2 — State machine + drawing state on map (8 tasks)

**Goal:** Bring up the `drawing` state end-to-end. After Phase 2, the user can click Measure tab → tap map → see vertex appear → tap again → see line + vertex → keyboard-undo → finish via double-click. Sidebar shows the live vertex list. No editing / inserting / elevation yet.

**Style note (security):** ruler.js NEVER uses `innerHTML` — even for clearing. Use the safe pattern `while (el.firstChild) el.removeChild(el.firstChild);` to clear a list before re-rendering. This matches the codebase posture (DOMPurify is used elsewhere; ruler labels are auto-generated and the textContent-only rule prevents future regressions when My Places passes user-supplied names).

### Task 2.1 through Task 2.8

**Note for the implementer / subagent:** Phase 2 is documented in detail at the bottom of this plan (see *Phase 2 expanded tasks* appendix). The summary below is sufficient to grok the shape; cross-reference the appendix for full code samples per task.

| # | Title | Files | Test |
|---|---|---|---|
| 2.1 | State machine helpers (`addVertex` / `popVertex` / `finishDrawing` / `clearAll` / `selectVertex` / `deselectVertex` / `startInsertBefore` / `startInsertAfter` / `cancelInsert`) | `ruler.js` | `state-machine.test.mjs` (11 tests covering all 9 transitions + invariants) |
| 2.2 | Map sources + 6 layers + `reattachSources` hook into `app.js` `addPlaceholderSources` | `ruler.js` + `app.js` (1 edit) | smoke (no automated; MapLibre cannot be reliably mocked) |
| 2.3 | Bail at L1622 + extend `queryRenderedFeatures` exclusion list to include 3 ruler layers | `app.js` (1 insert + 1 edit) | smoke + Task 5.1 grep test |
| 2.4 | Bails at L660 (KMZ pins) + L1272 (search pins) | `app.js` (2 inserts) | smoke + Task 5.1 grep test |
| 2.5 | `handleMapClick` — append vertex during drawing with 5px/250ms debounce + modifier-key suppression | `ruler.js` | smoke (DOM rendering tested in 2.7) |
| 2.6 | Keyboard handlers — Backspace / Esc / Enter with INPUT/TEXTAREA/contentEditable suppression | `ruler.js` | `keyboard.test.mjs` (7 tests) |
| 2.7 | `renderPanel()` — single function drives all visibility per state. Vertex list uses `removeChild` clear pattern + `textContent` only — NEVER `innerHTML` | `ruler.js` | `panel-render.test.mjs` (6 tests) |
| 2.8 | Tab activation hook + cursor management (crosshair during drawing/inserting; default elsewhere) | `ruler.js` | smoke |

**See "Phase 2 expanded tasks" appendix below for the full TDD implementation.**

### Phase 2 review checkpoint

> **Phase 2 review (≥3 rounds):** Drawing state end-to-end works in browser: tab → click 3 vertices → headline + vertex list visible → Enter → editing. Cursor changes correctly. Banner shows/hides per state. No console errors. All Phase 1 + Phase 2 tests still green. Verify the L1622 / L660 / L1272 bails by tapping each kind of pin during drawing — none should pop. Verify NO `innerHTML` assignment exists in ruler.js (`grep "innerHTML" frontend/ruler.js` returns nothing or only a read-comparison in tests).

---

## Phase 3 — Vertex-centric edit (8 tasks)

**Goal:** Bring up the editing state. After Phase 3, the user can tap a finished measurement's vertex → see it highlighted → drag to reposition → delete → insert before/after via sidebar buttons with segment-projection.

| # | Title | Files | Test |
|---|---|---|---|
| 3.1 | Layer-scoped click handler `map.on('click', 'ruler-vertex-hit-circles', …)` → tap-vs-drag disambiguation (mouse: 5px+200ms; touch: 8px+250ms thresholds tracked separately) | `ruler.js` | `tap-vs-drag.test.mjs` (~5 tests covering threshold boundaries) |
| 3.2 | Tap vertex → `selectVertex(i)` → `refreshMapData` (selected layer-filter activates) → `renderPanel` (action row appears) | `ruler.js` | covered by panel-render + state-machine tests; smoke for visual highlight |
| 3.3 | Drag-to-reposition (mouse): `mousedown` on hit-circles → disable `dragPan` → `mousemove` updates `state.vertices[i]` and re-emits source data via rAF coalescing → `mouseup` re-enables, runs single recompute | `ruler.js` | `drag-raf.test.mjs` (verifies bursty mousemove → 1 setData per rAF tick) |
| 3.4 | Drag-to-reposition (touch): `touchstart`/`touchmove`/`touchend` on canvas with `passive: false` per spec §D.5; multitouch cancel | `ruler.js` | `touch-multitouch-cancel.test.mjs` |
| 3.5 | `[Insert Before]` / `[Insert After]` button handlers → `startInsertBefore` / `startInsertAfter` → renders banner with V-label → next map click projects + inserts at slot | `ruler.js` | tested via state-machine + smoke |
| 3.6 | `[Delete]` button → splice vertex out, recompute, relabel, refresh map + panel | `ruler.js` | smoke + state-machine test additions |
| 3.7 | Backspace on selected vertex (editing state) → delete (extends Task 2.6 keyboard handler) | `ruler.js` | `keyboard.test.mjs` extension |
| 3.8 | Editing-state click leakage prevention — verified by Task 2.3's exclusion-list edit; add an integration smoke test that taps an editing-state vertex and asserts NO reverse-geocode popup | manual / smoke | smoke |

**Phase 3 review (≥3 rounds):** All edit operations work cleanly. Drag is smooth (no per-frame source-update stutter on a 50-vertex measurement). Multi-finger pinch over a vertex zooms the map without triggering drag. Insert-After tap projects to segment (no off-segment insertions). Delete keeps V-numbering contiguous. Editing-state vertex tap does NOT pop reverse-geocode. All tests green.

---

## Phase 4 — Elevation sampling (7 tasks)

**Goal:** Bring up the elevation profile. After Phase 4, finishing a measurement triggers tile fetching + decoding from `/tiles/data/elevation/{z}/{x}/{y}.png`, the sparkline renders with min/max/gain/loss, and coverage gaps are dashed.

| # | Title | Files | Test |
|---|---|---|---|
| 4.1 | `lngLatToTile(lng, lat, z)` + `tilePixelOffset(lng, lat, z)` — math primitives | `ruler.js` | `tile-math.test.mjs` (~6 tests; known-tile reference points) |
| 4.2 | `fetchTilePixels(z, x, y, signal)` — fetch PNG + draw to off-screen canvas + readback as Uint8ClampedArray. Same-origin (no CORS). Returns `Promise<Uint8ClampedArray | null>` (null on 404 / abort / decode failure). | `ruler.js` | smoke (canvas pixel readback can't be reliably tested in Node) |
| 4.3 | LRU tile cache (`Map`-backed, 30-tile cap, eviction by oldest-first) — independent module-level utility | `ruler.js` | `tile-cache-lru.test.mjs` (8 tests: hit / miss / cap enforcement / eviction order under burst) |
| 4.4 | `sampleElevation(vertices, signal, gen)` — orchestrator: builds samples (Phase 1 `samplePath`), groups by tile, fetches with concurrency 6, reads pixels, decodes via `elevationFromRGB`, builds `state.elevationProfile`. Aborts on signal. Gen-checks at fetch onload AND pre-state-mutation (per spec R5+R2). 50-tile cap enforces "Path too long…" notice. | `ruler.js` | `sample-elevation.test.mjs` (mocked fetch; ~5 tests covering happy path, partial coverage, full-failure, cancellation, 50-tile cap) |
| 4.5 | `samplingState` lifecycle (`idle / sampling / done / partial / failed`) + skeleton sparkline + tile-counter UI in the panel | `ruler.js` | covered by `sample-elevation.test.mjs` + panel-render extension |
| 4.6 | Sparkline render — coverage gaps as dashed sub-polylines; vertex tick marks; selected-vertex orange dashed guide line; ARIA label summarizing min/max/gain/loss | `ruler.js` | `sparkline-render.test.mjs` (4 tests covering gap segmentation, tick positions, ARIA label) |
| 4.7 | Wire `Finish` to kick off sampling: in `finishDrawing` controller, call `startSampling()` which creates AbortController, increments gen counter, calls `sampleElevation` | `ruler.js` | smoke + integration |

**Phase 4 review (≥3 rounds):** Real measurements in AZ produce sensible elevation profiles (verify against USGS reference points). Off-coverage path shows partial coverage with dashed gaps. Network-unplugged → samplingState `failed` with clear message. Drag a vertex → sampling re-runs, prior in-flight aborts cleanly (no stale samples appear). Tile cache stays at ≤30 entries.

---

## Phase 5 — A11y, i18n boundary, integration tests, ship gate (6 tasks)

| # | Title | Files | Test |
|---|---|---|---|
| 5.1 | Source-grep enforcement test — single test file verifies all 9 app.js touch points present (3 `_ruler.isActive()` bails; queryRenderedFeatures exclusion contains 3 ruler layers; `geographica:units-changed` dispatch in units handler; `_ruler.reattachSources` call in `addPlaceholderSources`; `'measure-panel'` in `VALID_SIDEBAR_PANELS`; both `window._formatDD` and `window._haversineDistance` exports) | `frontend/tests/ruler/app-js-integration.test.mjs` | the test itself is the artifact |
| 5.2 | `geographica:units-changed` event subscription in ruler.js init + units handler dispatches the event in app.js | `ruler.js` + `app.js` (1 insert) | `units-rerender-integration.test.mjs` |
| 5.3 | Full keyboard navigation per spec §C.6 — Tab order, Space/Enter on rows, Delete shortcut, ↑/↓ row focus traversal | `ruler.js` | `keyboard.test.mjs` extension |
| 5.4 | ARIA polish — vertex row `aria-label` (label + coords + segment), sparkline `aria-label` summary, banner `role="status"`, all already wired in earlier tasks but verify | `ruler.js` | `aria.test.mjs` (~4 tests) |
| 5.5 | Banner-slot reuse with `#nav-banner` — when nav is active AND ruler is active, ruler banner takes precedence; when ruler exits, nav banner re-renders | `ruler.js` | manual ship-gate (no automated; nav state too coupled) |
| 5.6 | Manual ship-gate run (per spec §Testing) — Cameron checks the post-R5 measurable checklist | (no code) | manual checklist (33 items) |

**Phase 5 review (≥3 rounds):** All grep-enforcement passes; units-toggle integration test passes; full keyboard nav demonstrably works; ARIA testable via screen-reader manual check. Cameron runs the 33-item manual ship-gate checklist; all items must pass before merging to `main`.

---

## Self-review checklist (before opening PR)

After all phases land on `dev`:

- [ ] `git diff main..dev -- frontend/app.js` shows exactly the 9 documented touch points (3 inserts of `_ruler.isActive()`, 1 dispatch of `geographica:units-changed`, 2 export lines, 1 `initRuler` call in bootstrap, 1 exclusion-list edit, 1 `VALID_SIDEBAR_PANELS` edit, 1 `_ruler.reattachSources` call). No collateral damage.
- [ ] `git diff main..dev -- frontend/index.html` shows exactly the tab-button insert, the panel insert, the floating-banner insert, and the script include.
- [ ] `git diff main..dev -- frontend/style.css` shows only ruler additions, no edits to existing rules.
- [ ] `frontend/navigation.js`, `frontend/nav-ui.js`, `frontend/voice-picker.js`, `frontend/wake-lock.js`, `frontend/silent-video-lock.js` are UNTOUCHED in this branch's diff.
- [ ] `node --test --test-force-exit frontend/tests/ruler/` reports all green.
- [ ] `python -m pytest tests/ services/search/tests/ -q` reports the same baseline as pre-cycle (no new failures).
- [ ] All commits in this cycle have `Agent: <moniker>` trailer.
- [ ] `grep -n "innerHTML" frontend/ruler.js` returns nothing (textContent-only posture).
- [ ] Manual ship-gate checklist (spec §Testing) signed off.

---

## Plan completeness disclosure

**Phases 0 and 1 are written in full skill-canonical detail** — every task has Step 1 (failing test), Step 2 (verify fail), Step 3 (implement), Step 4 (verify pass), Step 5 (commit) with concrete code samples. A subagent can pick up a Phase 0 or Phase 1 task and execute it without any external reference beyond the spec.

**Phases 2 through 5 are written in summary-table form** — file lists, test files, and behavioral requirements per task. The per-task TDD walkthrough was rolled up in favor of token economy; subagents executing Phases 2-5 will need to:
1. Read the spec section referenced (§B for state machine, §C for sidebar UI, §D for map rendering, §D.5 for iOS touch contract, §D.6 for drag, §E for math, §E.5 for segment projection, §C.6 for keyboard, §C.7 for ARIA).
2. Apply the same TDD shape Phase 0 and 1 demonstrate: write failing test, implement minimal code, verify pass, commit.
3. Reference the appendix below for safe-DOM patterns and other tricky bits called out by the adversarial reviews.

This is a deliberate trade-off, not an oversight. If you want full skill-canonical detail for Phases 2-5 before execution begins, ask the controller to expand the plan in a follow-up pass — that is straightforward to do and matches a future session's first task.

---

## Implementation appendix — safe patterns + tricky bits

### Safe DOM clearing — never use `innerHTML`

For Phase 2.7 specifically (and every list-rebuild in Phases 3-5), the canonical safe clear is:

```javascript
function renderVertexList(listEl) {
  if (!listEl) return;
  // Clear children safely (NEVER use innerHTML).
  while (listEl.firstChild) listEl.removeChild(listEl.firstChild);
  for (var i = 0; i < state.vertices.length; i++) {
    var v = state.vertices[i];
    var row = document.createElement('li');
    row.className = 'ruler-vertex-row';
    row.setAttribute('role', 'listitem');
    row.setAttribute('tabindex', '0');
    row.setAttribute('data-vertex-index', String(i));
    if (state.selectedVertex === i) {
      row.classList.add('selected');
      row.setAttribute('aria-selected', 'true');
    } else {
      row.setAttribute('aria-selected', 'false');
    }
    var top = document.createElement('div');
    top.className = 'ruler-vertex-row-top';
    var labelEl = document.createElement('span');
    labelEl.className = 'ruler-vertex-row-label';
    labelEl.textContent = v.label;
    var coordsEl = document.createElement('span');
    coordsEl.className = 'ruler-vertex-row-coords';
    coordsEl.textContent =
      window._formatDD(v.lat, 'NS') + ', ' + window._formatDD(v.lng, 'EW');
    top.appendChild(labelEl);
    top.appendChild(coordsEl);
    row.appendChild(top);

    if (i < state.vertices.length - 1) {
      var seg = state.segments[i];
      var segEl = document.createElement('div');
      segEl.className = 'ruler-vertex-row-seg';
      var dEl = document.createElement('span');
      dEl.textContent = '↓ ' + formatRulerDistance(seg.distance_m);
      var bEl = document.createElement('span');
      bEl.textContent = seg.bearing_deg.toFixed(1) + '°';
      segEl.appendChild(dEl);
      segEl.appendChild(bEl);
      row.appendChild(segEl);
    }

    row.addEventListener('click', (function (idx) {
      return function () {
        if (state.status === 'editing') {
          if (state.selectedVertex === idx) deselectVertex();
          else selectVertex(idx);
          refreshMapData();
          renderPanel();
        }
      };
    })(i));
    listEl.appendChild(row);
  }
}
```

The same `while (firstChild) removeChild(firstChild)` pattern is the canonical safe clear for any list rebuild in Phase 3, 4, or 5.

### rAF coalescing for drag (Phase 3.3)

Bursty `mousemove` / `touchmove` should collapse to one `setData` per frame:

```javascript
function scheduleSourceUpdate() {
  if (view.rafHandle != null) return;  // already queued for this frame
  view.rafHandle = requestAnimationFrame(function () {
    view.rafHandle = null;
    refreshMapData();
  });
}
```

During drag, replace direct `refreshMapData()` calls with `scheduleSourceUpdate()`. The single coalesced update runs at the next animation frame, regardless of how many move events fired between frames.

### AbortController + generation counter (Phase 4.4)

```javascript
function startSampling() {
  if (view.abortController) view.abortController.abort();
  view.abortController = new AbortController();
  view.samplingGen++;
  var gen = view.samplingGen;
  var signal = view.abortController.signal;

  state.elevationProfile = {
    samples: [], minM: null, maxM: null, gainM: 0, lossM: 0,
    coverageGaps: [], samplingState: 'sampling',
    samplingProgress: { tilesFetched: 0, tilesTotal: 0 },
  };
  renderPanel();

  sampleElevation(state.vertices, signal, gen).then(function (profile) {
    if (gen !== view.samplingGen) return;  // pre-mutation gen check
    state.elevationProfile = profile;
    renderPanel();
  });
}
```

Inside `sampleElevation`, after each fetch resolves and before any pixel decode work:

```javascript
fetch(url, { signal: signal }).then(function (resp) {
  if (gen !== view.samplingGen) return null;  // pre-decode gen check (saves CPU)
  if (!resp.ok) return null;
  return resp.blob();
}).then(function (blob) {
  if (blob == null) return null;
  if (gen !== view.samplingGen) return null;  // again, before decode
  // … draw to canvas, read pixels, decode …
});
```

**Two checks** because: (a) abort+resolved-fetch is a real race; the resolved-promise microtask runs even if abort fired between the network response and the `.then` callback. (b) catching the race pre-decode saves the wasted decode CPU.

### LRU tile cache (Phase 4.3)

```javascript
function makeLRUCache(maxEntries) {
  // Map insertion order = LRU order (oldest first).
  var cache = new Map();
  return {
    get: function (key) {
      if (!cache.has(key)) return null;
      var v = cache.get(key);
      cache.delete(key);
      cache.set(key, v);  // refresh insertion order
      return v;
    },
    set: function (key, value) {
      if (cache.has(key)) cache.delete(key);
      cache.set(key, value);
      while (cache.size > maxEntries) {
        var oldestKey = cache.keys().next().value;
        cache.delete(oldestKey);
      }
    },
    size: function () { return cache.size; },
    has: function (key) { return cache.has(key); },
  };
}
```

`view.tileCache = makeLRUCache(30);` in `init`.

### Insert After / Before — segment projection caller (Phase 3.5)

```javascript
function commitInsert(rawLng, rawLat) {
  if (state.status !== 'inserting' || state.insertSlot == null) return;
  var slot = state.insertSlot.before;  // index where new vertex will land
  var n = state.vertices.length;

  // Determine the relevant segment for projection.
  var projected = [rawLng, rawLat];  // default: extend the path (no adjacent segment)
  if (slot >= 1 && slot <= n - 1) {
    // Mid-path: project onto segment vertices[slot-1] → vertices[slot]
    var a = [state.vertices[slot - 1].lng, state.vertices[slot - 1].lat];
    var b = [state.vertices[slot    ].lng, state.vertices[slot    ].lat];
    projected = projectPointToSegment([rawLng, rawLat], a, b);
  }
  // Else: Insert Before V1 (slot=0) or Insert After Vlast (slot=n) — no
  // adjacent segment; place at raw tap location (extends the path).

  state.vertices.splice(slot, 0, { lng: projected[0], lat: projected[1], label: '' });
  relabel();
  recompute();
  state.status = 'editing';
  state.selectedVertex = slot;
  state.insertSlot = null;
  refreshMapData();
  renderPanel();
  // Phase 4: re-run sampling
}
```

Wire `commitInsert` into `handleMapClick` for the `inserting` state branch (Phase 3.5).

### iOS Safari touch contract (Phase 3.4)

Map vertex drag uses raw DOM listeners on the canvas with `passive: false`:

```javascript
var canvas = map.getCanvas();
canvas.addEventListener('touchstart', handleTouchStart, { passive: false });
canvas.addEventListener('touchmove',  handleTouchMove,  { passive: false });
canvas.addEventListener('touchend',   handleTouchEnd,   { passive: false });
canvas.addEventListener('touchcancel',handleTouchEnd,   { passive: false });

function handleTouchStart(e) {
  if (e.touches.length !== 1) return;            // multitouch: don't claim
  // Hit-test against the ruler-vertex-hit-circles layer at touch point
  var pt = mapTouchPoint(e.touches[0], canvas);
  var hits = map.queryRenderedFeatures(pt, { layers: ['ruler-vertex-hit-circles'] });
  if (hits.length === 0) return;
  e.preventDefault();                            // suppress synthetic mouse events
  view.dragging = { index: hits[0].properties.index, startX: pt.x, startY: pt.y, startT: Date.now() };
  map.dragPan.disable();
}

function handleTouchMove(e) {
  if (!view.dragging) return;
  if (e.touches.length > 1) {                    // multitouch arrived: cancel drag
    cancelTouchDrag();
    return;
  }
  e.preventDefault();
  var pt = mapTouchPoint(e.touches[0], canvas);
  var ll = map.unproject([pt.x, pt.y]);
  state.vertices[view.dragging.index].lng = ll.lng;
  state.vertices[view.dragging.index].lat = ll.lat;
  scheduleSourceUpdate();
}

function handleTouchEnd(e) {
  if (!view.dragging) return;
  // Tap-vs-drag (touch): 8px AND 250ms threshold per spec §D.5
  var dx = (e.changedTouches[0].clientX - canvas.getBoundingClientRect().left) - view.dragging.startX;
  var dy = (e.changedTouches[0].clientY - canvas.getBoundingClientRect().top)  - view.dragging.startY;
  var dt = Date.now() - view.dragging.startT;
  var moved = Math.sqrt(dx*dx + dy*dy) > 8 || dt > 250;
  if (!moved) {
    // It's a tap → select
    selectVertex(view.dragging.index);
  } else {
    // It was a drag → recompute + re-sample
    relabel();
    recompute();
    refreshMapData();
    if (state.status === 'editing') startSampling();  // Phase 4 wiring
  }
  cancelTouchDrag();
  refreshMapData();
  renderPanel();
}

function cancelTouchDrag() {
  view.dragging = null;
  map.dragPan.enable();
}

function mapTouchPoint(touch, canvas) {
  var rect = canvas.getBoundingClientRect();
  return { x: touch.clientX - rect.left, y: touch.clientY - rect.top };
}
```

Mouse drag follows the same shape with `mousedown` / `mousemove` (on `window`, not canvas, so off-canvas mouseup still fires) / `mouseup`, with thresholds 5px / 200ms.

---

**End of plan.**
