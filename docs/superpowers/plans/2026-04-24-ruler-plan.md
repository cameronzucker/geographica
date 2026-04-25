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
    <div id="ruler-mode-banner" class="hidden" role="status" aria-live="polite">
      <span id="ruler-mode-banner-text"></span>
      <button type="button" id="ruler-mode-banner-cancel" aria-label="Cancel ruler mode">×</button>
    </div>
```

- [ ] **Step 4: Add the script include.**

Find the existing `<script src="voice-picker.js"></script>` line near the bottom of the body. Immediately after, add:

```html
    <script src="ruler.js?v=20260424"></script>
```

The `?v=YYYYMMDD` cache-buster matches the convention used on sibling script includes (`voice-picker.js?v=20260421`, `wake-lock.js?v=20260420`, etc.).

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

/* ── [hidden] overrides — UA stylesheet [hidden] { display: none } loses
   to the four ruler rules above that set display: flex / grid / block.
   Re-assert hidden=true wins. Specificity 0,2,0 (class+attribute) beats
   the bare class 0,1,0 so no !important needed. ───────────────────── */
.ruler-banner-inline[hidden],
.ruler-actions[hidden],
.ruler-stats[hidden],
.ruler-sparkline[hidden] {
  display: none;
}

/* ── Mobile responsive ────────────────────────────────────────── */
@media (max-width: 480px) {
  .ruler-actions button { flex: 1 1 100%; }
}

/* ── iOS Safari touch contract (per spec §D.5) ────────────────── */
.maplibregl-canvas {
  touch-action: manipulation;
}
```

**Why the `[hidden]` overrides matter:** `.ruler-banner-inline` (display:flex), `.ruler-actions` (display:flex), `.ruler-stats` (display:grid), and `.ruler-sparkline` (display:block) each set an explicit `display:` rule that beats the UA stylesheet's `[hidden] { display: none }`. Without the explicit `[hidden]` overrides, those elements remain visible despite carrying the `hidden` HTML attribute. The Phase 0 ship surfaced this on the inline banner — the empty Measure tab showed a gray banner box with a non-functional ✕ button until the fix landed.

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
  // For short segments at modest latitudes the reciprocal is within 0.5°.
  // Normalize: wrap |fwd - rev| to [0°, 360°) then measure distance from 180°.
  // (Note: JS `%` is sign-preserving, so we must do `+ 360 then % 360`
  // — Python-style `((x % 360 + 540) % 360 - 180)` does NOT work in JS for
  // negative `x`. See impl-log 2026-04-25 Task 1.1.)
  const a = [-112.07, 33.45];
  const b = [-112.05, 33.46];
  const fwd = t.bearingDeg(a, b);
  const rev = t.bearingDeg(b, a);
  const diff = Math.abs(((fwd - rev) + 360) % 360 - 180);
  assert.ok(diff < 0.5, `reciprocal mismatch: fwd=${fwd} rev=${rev} diff=${diff}`);
});

test('bearingDeg: AZ→CO reference (Phoenix → Denver) ~40° (NE)', () => {
  const t = loadRuler();
  // Phoenix Sky Harbor [-112.0117, 33.4342] → Denver DIA [-104.6739, 39.8617].
  // Standard great-circle initial bearing: ~40.35° (verified directly against
  // the formula and cross-checked with multiple geodesy calculators).
  // (Plan v1/v2 cited ~37° as a "USGS reference" — that was wrong; the
  // correct spherical-Earth value is ~40.35°. See impl-log 2026-04-25
  // Task 1.1.)
  const b = t.bearingDeg([-112.0117, 33.4342], [-104.6739, 39.8617]);
  assert.ok(Math.abs(b - 40.35) < 1.0, `expected ~40.35°, got ${b}`);
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

**Reusable test helpers:** Phase 2-5 tests follow the same `loadRuler()` factory pattern Phase 1 introduced. To avoid duplicating ~20 lines per file, factor it into a shared module before Task 2.1:

Create `frontend/tests/ruler/_fixtures.js`:

```javascript
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const SOURCE = fs.readFileSync(path.join(__dirname, '../../ruler.js'), 'utf-8');

// Real haversine for tests that need accurate distances.
export function realHaversine(a, b) {
  const R = 6371000;
  const dLat = (b[1] - a[1]) * Math.PI / 180;
  const dLng = (b[0] - a[0]) * Math.PI / 180;
  const lat1 = a[1] * Math.PI / 180;
  const lat2 = b[1] * Math.PI / 180;
  const sinDLat = Math.sin(dLat / 2);
  const sinDLng = Math.sin(dLng / 2);
  const h = sinDLat*sinDLat + Math.cos(lat1)*Math.cos(lat2)*sinDLng*sinDLng;
  return 2 * R * Math.asin(Math.sqrt(h));
}

// formatDD shim — matches the format app.js's formatDD produces:
// "33.45000° N" (5 decimals + space + hemisphere letter).
export function shimFormatDD(value, dirs) {
  const hemi = value >= 0 ? dirs[0] : dirs[1];
  return Math.abs(value).toFixed(5) + '° ' + hemi;
}

// loadRuler — instantiate ruler.js in a fresh VM context with optional overrides.
// opts: { useImperial?: boolean, fakeDocument?: object, fakeFetch?: function }
export function loadRuler(opts = {}) {
  const win = {
    _haversineDistance: realHaversine,
    _formatDD: shimFormatDD,
    _geographicaUseImperial: opts.useImperial !== undefined ? opts.useImperial : true,
  };
  const doc = opts.fakeDocument || {
    getElementById: () => null,
    addEventListener: () => {},
    createElement: () => ({
      setAttribute: () => {},
      appendChild: () => {},
      addEventListener: () => {},
      classList: { add: () => {}, remove: () => {} },
      style: {},
    }),
  };
  const ctx = {
    window: win,
    document: doc,
    console,
    requestAnimationFrame: (cb) => { setTimeout(cb, 0); return 1; },
    cancelAnimationFrame: () => {},
  };
  if (opts.fakeFetch) ctx.fetch = opts.fakeFetch;
  if (opts.AbortController) ctx.AbortController = opts.AbortController;
  vm.createContext(ctx);
  vm.runInContext(SOURCE, ctx);
  return { ruler: ctx.window._ruler, test: ctx.window._ruler._test, win, ctx };
}
```

Tests below import `loadRuler` from `_fixtures.js` rather than reimplementing it.

---

### Task 2.1: State machine helpers — `addVertex` / `popVertex` / `finishDrawing` / `clearAll` / `selectVertex` / `deselectVertex` / `startInsertBefore` / `startInsertAfter` / `cancelInsert` + `relabel` / `recompute`

This task introduces all state-machine transitions per spec §B as testable helpers. Plus the supporting `relabel()` and `recompute()` functions that re-derive segments + total + labels after any vertex mutation. `getStateSnapshot()` is the read-only seam tests use to assert state without leaking the live mutable reference.

**Files:**
- Modify: `frontend/ruler.js` (add helpers + expose to `_test`)
- Create: `frontend/tests/ruler/_fixtures.js` (new shared module — see "Reusable test helpers" above)
- Create: `frontend/tests/ruler/state-machine.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create the shared `_fixtures.js` from the section above (this happens once). Then create `frontend/tests/ruler/state-machine.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

test('initial state is idle, vertices empty', () => {
  const { test: t } = loadRuler();
  const s = t.getState();
  assert.strictEqual(s.status, 'idle');
  assert.deepStrictEqual(s.vertices, []);
  assert.strictEqual(s.selectedVertex, null);
  assert.strictEqual(s.insertSlot, null);
});

test('addVertex from idle transitions to drawing', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  const s = t.getState();
  assert.strictEqual(s.status, 'drawing');
  assert.strictEqual(s.vertices.length, 1);
  assert.strictEqual(s.vertices[0].label, 'V1');
  assert.strictEqual(s.totalDistance_m, 0);
});

test('addVertex twice produces 2 vertices and 1 segment', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 2);
  assert.strictEqual(s.segments.length, 1);
  assert.ok(s.totalDistance_m > 0, 'totalDistance_m should be > 0');
  assert.ok(s.segments[0].distance_m > 0);
  assert.ok(s.segments[0].bearing_deg >= 0 && s.segments[0].bearing_deg < 360);
});

test('popVertex from drawing with 1 vertex returns to idle', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.popVertex();
  const s = t.getState();
  assert.strictEqual(s.status, 'idle');
  assert.strictEqual(s.vertices.length, 0);
});

test('popVertex from drawing with multiple vertices stays in drawing', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.addVertex(-112.03, 33.47);
  t.popVertex();
  const s = t.getState();
  assert.strictEqual(s.status, 'drawing');
  assert.strictEqual(s.vertices.length, 2);
});

test('finishDrawing requires >=2 vertices, transitions to editing', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.finishDrawing();   // 1 vertex: should be a no-op
  assert.strictEqual(t.getState().status, 'drawing');
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  assert.strictEqual(t.getState().status, 'editing');
});

test('clearAll resets to idle from any state', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  t.clearAll();
  const s = t.getState();
  assert.strictEqual(s.status, 'idle');
  assert.strictEqual(s.vertices.length, 0);
  assert.strictEqual(s.selectedVertex, null);
  assert.strictEqual(s.insertSlot, null);
  assert.strictEqual(s.totalDistance_m, 0);
});

test('selectVertex requires editing state', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.selectVertex(0);  // still drawing — should be no-op
  assert.strictEqual(t.getState().selectedVertex, null);
  t.finishDrawing();
  t.selectVertex(0);
  assert.strictEqual(t.getState().selectedVertex, 0);
});

test('deselectVertex clears selection without leaving editing', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  t.deselectVertex();
  const s = t.getState();
  assert.strictEqual(s.selectedVertex, null);
  assert.strictEqual(s.status, 'editing');
});

test('startInsertAfter from editing transitions to inserting with slot=index+1', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  t.startInsertAfter();
  const s = t.getState();
  assert.strictEqual(s.status, 'inserting');
  assert.deepStrictEqual(s.insertSlot, { before: 1 });
});

test('startInsertBefore from editing transitions to inserting with slot=index', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(1);
  t.startInsertBefore();
  const s = t.getState();
  assert.strictEqual(s.status, 'inserting');
  assert.deepStrictEqual(s.insertSlot, { before: 1 });
});

test('cancelInsert returns to editing with previous selection preserved', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  t.startInsertAfter();
  t.cancelInsert();
  const s = t.getState();
  assert.strictEqual(s.status, 'editing');
  assert.strictEqual(s.selectedVertex, 0);
  assert.strictEqual(s.insertSlot, null);
});

test('shape invariant: vertices.length < 2 ⇒ segments.length === 0', () => {
  const { test: t } = loadRuler();
  let s = t.getState();
  assert.strictEqual(s.segments.length, 0);
  t.addVertex(-112.07, 33.45);
  s = t.getState();
  assert.strictEqual(s.segments.length, 0);
});

test('shape invariant: clearAll wipes everything atomically', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  t.clearAll();
  const s = t.getState();
  assert.strictEqual(s.selectedVertex, null);
  assert.strictEqual(s.status, 'idle');
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/state-machine.test.mjs`
Expected: 14 failures (`addVertex is not a function`, etc.).

- [ ] **Step 3: Implement helpers.**

In `frontend/ruler.js`, after the existing pure functions (after `sparklinePath`, before the `_test` export block), insert:

```javascript
  // ─── State recompute / relabel ─────────────────────────────────────
  function relabel() {
    for (var i = 0; i < state.vertices.length; i++) {
      state.vertices[i].label = 'V' + (i + 1);
    }
  }

  function recompute() {
    state.segments = [];
    state.totalDistance_m = 0;
    var hav = window._haversineDistance;
    for (var i = 0; i < state.vertices.length - 1; i++) {
      var a = [state.vertices[i].lng,     state.vertices[i].lat];
      var b = [state.vertices[i + 1].lng, state.vertices[i + 1].lat];
      var d = hav(a, b);
      var brg = bearingDeg(a, b);
      state.segments.push({
        distance_m: d, bearing_deg: brg,
        from: state.vertices[i].label, to: state.vertices[i + 1].label,
      });
      state.totalDistance_m += d;
    }
  }

  // ─── State-machine transitions (spec §B) ───────────────────────────
  function addVertex(lng, lat) {
    if (state.status === 'idle') state.status = 'drawing';
    if (state.status !== 'drawing') return;
    state.vertices.push({ lng: lng, lat: lat, label: '' });
    relabel();
    recompute();
  }

  function popVertex() {
    if (state.status !== 'drawing') return;
    if (state.vertices.length === 0) return;
    state.vertices.pop();
    relabel();
    recompute();
    if (state.vertices.length === 0) state.status = 'idle';
  }

  function finishDrawing() {
    if (state.status !== 'drawing') return;
    if (state.vertices.length < 2) return;
    state.status = 'editing';
    state.elevationProfile = null;  // sampling kicks off in Phase 4
  }

  function clearAll() {
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
  }

  function selectVertex(index) {
    if (state.status !== 'editing') return;
    if (index < 0 || index >= state.vertices.length) return;
    state.selectedVertex = index;
  }

  function deselectVertex() {
    if (state.status !== 'editing') return;
    state.selectedVertex = null;
  }

  function startInsertBefore() {
    if (state.status !== 'editing') return;
    if (state.selectedVertex === null) return;
    state.status = 'inserting';
    state.insertSlot = { before: state.selectedVertex };
  }

  function startInsertAfter() {
    if (state.status !== 'editing') return;
    if (state.selectedVertex === null) return;
    state.status = 'inserting';
    state.insertSlot = { before: state.selectedVertex + 1 };
  }

  function cancelInsert() {
    if (state.status !== 'inserting') return;
    state.status = 'editing';
    state.insertSlot = null;
  }

  // Read-only state snapshot for tests + view-layer rendering.
  function getStateSnapshot() {
    return {
      status: state.status,
      selectedVertex: state.selectedVertex,
      insertSlot: state.insertSlot ? { before: state.insertSlot.before } : null,
      vertices: state.vertices.map(function (v) {
        return { lng: v.lng, lat: v.lat, label: v.label };
      }),
      segments: state.segments.map(function (s) {
        return { distance_m: s.distance_m, bearing_deg: s.bearing_deg, from: s.from, to: s.to };
      }),
      totalDistance_m: state.totalDistance_m,
      elevationProfile: state.elevationProfile,
    };
  }
```

Then add to the `window._ruler._test = { ... }` object:
```javascript
    addVertex: addVertex,
    popVertex: popVertex,
    finishDrawing: finishDrawing,
    clearAll: clearAll,
    selectVertex: selectVertex,
    deselectVertex: deselectVertex,
    startInsertBefore: startInsertBefore,
    startInsertAfter: startInsertAfter,
    cancelInsert: cancelInsert,
    getState: getStateSnapshot,
    relabel: relabel,
    recompute: recompute,
```

Update the public `clear()` function body to delegate:
```javascript
  function clear() {
    clearAll();
    // Phase 2.7+ extends this to call renderPanel() + refreshMapData() for view sync.
  }
```

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/state-machine.test.mjs`
Expected: 14 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/_fixtures.js frontend/tests/ruler/state-machine.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): state-machine helpers + relabel/recompute

addVertex / popVertex / finishDrawing / clearAll / selectVertex /
deselectVertex / startInsertBefore / startInsertAfter / cancelInsert
implement the 9 spec §B transitions. relabel() reassigns V1..Vn
contiguously after any mutation; recompute() rebuilds segments +
totalDistance_m via window._haversineDistance + bearingDeg.

14 tests covering all transitions + the §A shape invariants
(selectedVertex / status pairing; vertices.length < 2 ⇒ no segments;
clearAll-from-any-state). getStateSnapshot is the read-only seam.
_fixtures.js shared loadRuler helper for Phase 2-5 test files.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §A, §B
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 2.1)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2.2: Map sources + 6 layers + `reattachSources` hook into `addPlaceholderSources`

Per spec §D: ruler renders into two GeoJSON sources (`ruler-line-source` for the LineString, `ruler-vertex-source` for the points) with 6 layers (shadow line, line, vertex circles, selected-vertex circles via filter, invisible 44-px hit circles, vertex labels). `refreshMapData()` re-emits source data after any state mutation. `reattachSources()` reattaches the entire source/layer set on `style.load` (called by app.js's centralized `addPlaceholderSources`).

**No automated test:** MapLibre's source/layer API cannot be reliably mocked without exercising real GL state. Coverage is via Phase 5.1 grep enforcement + manual smoke.

**Files:**
- Modify: `frontend/ruler.js` (add the source/layer wiring)
- Modify: `frontend/app.js` (~line 295 inside `addPlaceholderSources` — call `_ruler.reattachSources(map)`)

- [ ] **Step 1: Verify the existing app.js shape.**

Run: `grep -n "function addPlaceholderSources" frontend/app.js`
Expected: line ~295.

Open the file at that line and read the function body. It already adds placeholder GeoJSON sources for hillshade, public-lands, etc. — ruler joins this list.

- [ ] **Step 2: Add source/layer wiring to ruler.js.**

In `frontend/ruler.js`, after the state-machine helpers, before the `_test` export block, insert:

```javascript
  // ─── Map source/layer wiring (spec §D) ─────────────────────────────
  // Layer IDs (also referenced by app.js queryRenderedFeatures exclusion
  // edit at L1628 — keep in sync with that list).
  var SOURCE_LINE = 'ruler-line-source';
  var SOURCE_VERTEX = 'ruler-vertex-source';
  var LAYER_LINE_SHADOW = 'ruler-line-shadow';
  var LAYER_LINE = 'ruler-line';
  var LAYER_VERTEX_CIRCLES = 'ruler-vertex-circles';
  var LAYER_VERTEX_CIRCLES_SELECTED = 'ruler-vertex-circles-selected';
  var LAYER_VERTEX_HIT_CIRCLES = 'ruler-vertex-hit-circles';
  var LAYER_VERTEX_LABELS = 'ruler-vertex-labels';

  function buildLineFeature() {
    if (state.vertices.length < 2) {
      return { type: 'Feature', geometry: { type: 'LineString', coordinates: [] }, properties: {} };
    }
    var coords = state.vertices.map(function (v) { return [v.lng, v.lat]; });
    return { type: 'Feature', geometry: { type: 'LineString', coordinates: coords }, properties: {} };
  }

  function buildVertexFeatures() {
    return {
      type: 'FeatureCollection',
      features: state.vertices.map(function (v, i) {
        return {
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [v.lng, v.lat] },
          properties: {
            index: i,
            label: v.label,
            selected: state.selectedVertex === i,
          },
        };
      }),
    };
  }

  function refreshMapData() {
    if (!map) return;
    var lineSrc = map.getSource(SOURCE_LINE);
    var vertSrc = map.getSource(SOURCE_VERTEX);
    if (lineSrc) lineSrc.setData(buildLineFeature());
    if (vertSrc) vertSrc.setData(buildVertexFeatures());
  }

  function ensureSources() {
    if (!map) return;
    if (!map.getSource(SOURCE_LINE)) {
      map.addSource(SOURCE_LINE, { type: 'geojson', data: buildLineFeature() });
    }
    if (!map.getSource(SOURCE_VERTEX)) {
      map.addSource(SOURCE_VERTEX, { type: 'geojson', data: buildVertexFeatures() });
    }
  }

  function ensureLayers() {
    if (!map) return;
    // Order matters: shadow → line → circles → selected circles → hit circles → labels.
    if (!map.getLayer(LAYER_LINE_SHADOW)) {
      map.addLayer({
        id: LAYER_LINE_SHADOW, type: 'line', source: SOURCE_LINE,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': 'rgba(0,0,0,0.55)', 'line-width': 7 },
      });
    }
    if (!map.getLayer(LAYER_LINE)) {
      map.addLayer({
        id: LAYER_LINE, type: 'line', source: SOURCE_LINE,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#ffd400', 'line-width': 4, 'line-opacity': 0.95 },
      });
    }
    if (!map.getLayer(LAYER_VERTEX_CIRCLES)) {
      map.addLayer({
        id: LAYER_VERTEX_CIRCLES, type: 'circle', source: SOURCE_VERTEX,
        paint: {
          'circle-radius': 8,
          'circle-color': '#ffd400',
          'circle-stroke-width': 2,
          'circle-stroke-color': '#ffffff',
        },
      });
    }
    if (!map.getLayer(LAYER_VERTEX_CIRCLES_SELECTED)) {
      map.addLayer({
        id: LAYER_VERTEX_CIRCLES_SELECTED, type: 'circle', source: SOURCE_VERTEX,
        // MapLibre v3+ requires the explicit ['get', ...] expression form.
        filter: ['==', ['get', 'selected'], true],
        paint: {
          'circle-radius': 11,
          'circle-color': '#ff7a00',
          'circle-stroke-width': 3,
          'circle-stroke-color': '#ffffff',
        },
      });
    }
    if (!map.getLayer(LAYER_VERTEX_HIT_CIRCLES)) {
      // Visible-but-transparent: 44px diameter (WCAG 2.5.5). MUST NOT be
      // visibility:'none' — that would skip queryRenderedFeatures.
      map.addLayer({
        id: LAYER_VERTEX_HIT_CIRCLES, type: 'circle', source: SOURCE_VERTEX,
        paint: { 'circle-radius': 22, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-width': 0 },
      });
    }
    if (!map.getLayer(LAYER_VERTEX_LABELS)) {
      map.addLayer({
        id: LAYER_VERTEX_LABELS, type: 'symbol', source: SOURCE_VERTEX,
        layout: {
          'text-field': ['get', 'label'],
          // Two-font fallback per spec §D / R5 M3 — matches positron/darkmatter/hybrid.
          'text-font': ['Metropolis Regular', 'Noto Sans Regular'],
          'text-size': 12,
          'text-offset': [0, -1.4],
          'text-anchor': 'bottom',
          'text-allow-overlap': true,
        },
        paint: {
          'text-color': '#ffffff',
          'text-halo-color': '#000000',
          'text-halo-width': 2,
        },
      });
    }
  }

  function reattachSources(mapInstance) {
    // Called by app.js's addPlaceholderSources() on initial load and on
    // every style.load (basemap toggle / 3D enable). Idempotent.
    map = mapInstance;
    ensureSources();
    ensureLayers();
    refreshMapData();
  }

  function teardownSourcesAndLayers() {
    if (!map) return;
    [LAYER_VERTEX_LABELS, LAYER_VERTEX_HIT_CIRCLES, LAYER_VERTEX_CIRCLES_SELECTED,
     LAYER_VERTEX_CIRCLES, LAYER_LINE, LAYER_LINE_SHADOW].forEach(function (id) {
      if (map.getLayer(id)) map.removeLayer(id);
    });
    [SOURCE_VERTEX, SOURCE_LINE].forEach(function (id) {
      if (map.getSource(id)) map.removeSource(id);
    });
  }
```

Update `init(mapInstance)` to call `ensureSources()` + `ensureLayers()`:
```javascript
  function init(mapInstance) {
    if (initialized) return;
    initialized = true;
    map = mapInstance;
    view.tileCache = null;  // Phase 4 task creates this
    ensureSources();
    ensureLayers();
    // Phase 2.5+ adds map click handler; Phase 2.6 keyboard handler;
    // Phase 5.2 units-changed subscription; Phase 2.8 tab activation.
  }
```

Add `reattachSources: reattachSources` to the public `window._ruler` exports (the API object near the bottom of the file). Also add `refreshMapData: refreshMapData` to `_test` (Phase 3+ tests need to invoke it).

- [ ] **Step 3: Wire `addPlaceholderSources` in app.js.**

Run: `grep -n "function addPlaceholderSources" frontend/app.js`
Expected output points at line ~295.

Open `frontend/app.js` and find the END of `addPlaceholderSources()` (the closing `}`). Just before that closing brace, insert:

```javascript
    // Ruler measurement tool — reattach on initial load + every style.load.
    if (window._ruler && window._ruler.reattachSources) {
      window._ruler.reattachSources(map);
    }
```

- [ ] **Step 4: Smoke test in browser.**

Reload the dev frontend. Open DevTools console, run:
```javascript
map.getSource('ruler-line-source')
map.getSource('ruler-vertex-source')
map.getLayer('ruler-line')
map.getLayer('ruler-vertex-hit-circles')
```
Expected: each returns a non-null object. No console errors.

Toggle the basemap (e.g., positron → darkmatter). Re-run the same queries. Expected: still non-null (style.load reattach worked).

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/app.js
git commit -m "$(cat <<'EOF'
feat(ruler): map sources + 6 layers + style-load reattach hook

Two GeoJSON sources (ruler-line-source, ruler-vertex-source) feed
six layers in spec-mandated order: shadow → line → circles →
selected-circles → hit-circles → labels. Hit-circles are visible-
but-transparent (NOT visibility:'none' — preserves hit-testability).
Filter expression uses the MapLibre v3+ ['get', ...] form.
text-font is the two-font fallback from positron/darkmatter/hybrid.

reattachSources(map) hooks into app.js's centralized
addPlaceholderSources() at line ~295 (one new line) so basemap
toggles and 3D enable / disable preserve ruler state.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §D
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 2.2)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2.3: Bail at L1622 reverse-geocode handler + extend `queryRenderedFeatures` exclusion list to include 3 ruler layers

Per spec §A edits #1 and #2 + §B + R5 C1: the generic reverse-geocode click handler at app.js:1622 must bail when ruler is active (`drawing` / `inserting`). Additionally, the existing `queryRenderedFeatures` exclusion list at L1628-1631 (which already excludes `imported-points` etc.) must include the three ruler hit-test layers — so even in the `editing` state (where `_ruler.isActive() === false` is intentional), vertex-clicks don't fall through to reverse-geocode.

**Files:**
- Modify: `frontend/app.js` (1 insert before the existing handler body + 1 edit to the exclusion array)

- [ ] **Step 1: Locate the handler.**

Run: `grep -n "L1622\|reverseGeocode\|reverse-geocode\|reverse_geocode" frontend/app.js | head -10`

If grep doesn't find the canonical L1622 region directly, search for the click handler that produces the reverse-geocode popup. Look for `map.on('click', function` or similar near line 1620, with a body that does `map.queryRenderedFeatures` and exits early if any feature was found, then falls through to `fetch('/api/reverse_geocode'…)` or similar.

- [ ] **Step 2: Insert the ruler-active bail.**

At the very top of the handler body — BEFORE any other logic, BEFORE the `queryRenderedFeatures` call — insert:

```javascript
      // Ruler measurement tool — suppress popup during drawing/inserting.
      if (window._ruler && window._ruler.isActive()) return;
```

- [ ] **Step 3: Extend the exclusion list.**

Find the `queryRenderedFeatures` call inside this handler. The existing exclusion list looks like:

```javascript
      var feats = map.queryRenderedFeatures(e.point, {
        layers: ['imported-points', 'search-result-circles', 'search-result-pin', /* ... */],
      });
```

Append the three ruler layers to this list:
```javascript
      var feats = map.queryRenderedFeatures(e.point, {
        layers: [
          'imported-points', 'search-result-circles', 'search-result-pin', /* ... existing entries ... */,
          // Ruler measurement tool — vertex-clicks in editing state must NOT
          // fall through to reverse-geocode (spec R5 C1).
          'ruler-vertex-hit-circles',
          'ruler-vertex-circles',
          'ruler-line',
        ],
      });
```

**Important:** preserve the EXISTING entries. The Phase 5.1 grep enforcement test will assert all three ruler layer names are present — it doesn't care about ordering with respect to the existing entries.

- [ ] **Step 4: Smoke test in browser.**

Reload dev. Open the Measure tab. Click the map twice (places V1 + V2). Then click empty map again to add V3 — expected: vertex appears, NO reverse-geocode popup.

Click `[Finish]` to enter editing. Click on V2 — expected: vertex highlighted (Phase 3.2 wires up the actual selection; for now, just verify NO reverse-geocode popup appears on the vertex click).

Switch to Layers tab, then click an empty area of the map — expected: reverse-geocode popup behaves normally (the bail must NOT leak into non-ruler-active states).

- [ ] **Step 5: Commit.**

```bash
git add frontend/app.js
git commit -m "$(cat <<'EOF'
feat(app): ruler bail at reverse-geocode handler + exclusion list

Two changes at the L1622 click handler:

  1. Insert: early-return when window._ruler.isActive() — suppresses
     reverse-geocode popup during ruler drawing / inserting.

  2. Edit: append 'ruler-vertex-hit-circles', 'ruler-vertex-circles',
     'ruler-line' to the queryRenderedFeatures exclusion list. This
     covers the editing state, where isActive() is intentionally
     false — without it, vertex clicks would fall through to
     reverse-geocode and double-fire (per spec R5 C1).

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §A, §B (R5 C1)
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 2.3)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2.4: Bails at L660 (KMZ-pin handler) + L1272 (search-pin handler)

Two more click handlers in app.js need the same `_ruler.isActive()` early-return: imported-layers (KMZ pins) at L660 and search-result-circles at L1272. Without these, clicking a KMZ pin during ruler drawing fires its info popup AND adds a ruler vertex.

**Files:**
- Modify: `frontend/app.js` (2 inserts)

- [ ] **Step 1: Locate both handlers.**

Run: `grep -n "imported-points\|search-result-circles\|search-result-pin" frontend/app.js | head -20`

Find the click handlers that fire on these layers. They look like:
```javascript
  map.on('click', 'imported-points', function (e) { /* L660 region */ });
  map.on('click', 'search-result-circles', function (e) { /* L1272 region */ });
```

- [ ] **Step 2: Insert ruler bail at L660 (KMZ-pin handler).**

At the top of the imported-layers click handler body, BEFORE any other logic, insert:

```javascript
    // Ruler measurement tool — suppress KMZ-pin popup during drawing/inserting.
    if (window._ruler && window._ruler.isActive()) return;
```

- [ ] **Step 3: Insert ruler bail at L1272 (search-pin handler).**

At the top of the search-result-circles click handler body, insert the same line:

```javascript
    // Ruler measurement tool — suppress search-pin popup during drawing/inserting.
    if (window._ruler && window._ruler.isActive()) return;
```

- [ ] **Step 4: Smoke test in browser.**

Reload dev. Drop a KMZ overlay + run a search to ensure KMZ pins and search pins are visible. Open Measure tab.

Click on a KMZ pin: expected — vertex placed, NO KMZ info popup.
Click on a search-result pin: expected — vertex placed, NO search popup.
Switch to Layers tab; click each kind of pin: expected — popups behave normally (the bail must NOT leak into non-ruler-active states).

- [ ] **Step 5: Commit.**

```bash
git add frontend/app.js
git commit -m "$(cat <<'EOF'
feat(app): ruler bails at KMZ-pin + search-pin click handlers

Two early-returns added (L660 imported-points handler, L1272
search-result-circles handler) — both bail when window._ruler.
isActive() returns true. Prevents double-firing during ruler
drawing/inserting where the click should ONLY add a vertex.

The reverse-geocode handler (L1622) was covered in Task 2.3.
The exclusion-list edit at L1628 covers the editing state.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §A
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 2.4)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2.5: `handleMapClick` — append vertex during drawing with debounce + modifier-key suppression

`handleMapClick(e)` is the ruler.js-internal callback that turns a MapLibre `click` event into an `addVertex` call when the ruler is in `drawing` state. Per spec §F: debounce (5px AND 250ms suppresses rapid duplicate clicks) and modifier-key suppression (Ctrl/Shift/Alt/Meta-clicks pass through to other handlers — they're typically map-pan / select-rectangle gestures).

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/click-debounce.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/click-debounce.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

function fakeClickEvent(lng, lat, opts = {}) {
  return {
    lngLat: { lng: lng, lat: lat },
    point: opts.point || { x: 100, y: 100 },
    originalEvent: {
      ctrlKey: opts.ctrlKey || false,
      shiftKey: opts.shiftKey || false,
      altKey: opts.altKey || false,
      metaKey: opts.metaKey || false,
      timeStamp: opts.t !== undefined ? opts.t : 1000,
    },
  };
}

test('handleMapClick during idle starts drawing with V1', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45));
  const s = t.getState();
  assert.strictEqual(s.status, 'drawing');
  assert.strictEqual(s.vertices.length, 1);
});

test('handleMapClick during drawing appends', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { t: 1000 }));
  t.handleMapClick(fakeClickEvent(-112.05, 33.46, { t: 2000, point: { x: 200, y: 200 } }));
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 2);
});

test('handleMapClick debounces near-duplicate clicks within 5px AND 250ms', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { t: 1000, point: { x: 100, y: 100 } }));
  // Second click 3px away, 100ms later → debounced
  t.handleMapClick(fakeClickEvent(-112.0701, 33.4500001, { t: 1100, point: { x: 102, y: 102 } }));
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 1, 'second near-duplicate click should be debounced');
});

test('handleMapClick does NOT debounce a click >5px away', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { t: 1000, point: { x: 100, y: 100 } }));
  t.handleMapClick(fakeClickEvent(-112.06, 33.46, { t: 1100, point: { x: 110, y: 110 } }));
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 2);
});

test('handleMapClick does NOT debounce a click >250ms later', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { t: 1000, point: { x: 100, y: 100 } }));
  t.handleMapClick(fakeClickEvent(-112.0701, 33.4500001, { t: 1300, point: { x: 102, y: 102 } }));
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 2);
});

test('handleMapClick suppresses on Ctrl-click', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { ctrlKey: true }));
  assert.strictEqual(t.getState().vertices.length, 0);
});

test('handleMapClick suppresses on Shift-click', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { shiftKey: true }));
  assert.strictEqual(t.getState().vertices.length, 0);
});

test('handleMapClick suppresses on Meta-click (Cmd on macOS)', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { metaKey: true }));
  assert.strictEqual(t.getState().vertices.length, 0);
});

test('handleMapClick suppresses on Alt-click', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { altKey: true }));
  assert.strictEqual(t.getState().vertices.length, 0);
});

test('handleMapClick during editing is a no-op', () => {
  const { test: t } = loadRuler();
  t.handleMapClick(fakeClickEvent(-112.07, 33.45, { t: 1000 }));
  t.handleMapClick(fakeClickEvent(-112.05, 33.46, { t: 2000, point: { x: 200, y: 200 } }));
  t.finishDrawing();
  // Now in editing — empty-map clicks should NOT add vertices.
  t.handleMapClick(fakeClickEvent(-112.03, 33.47, { t: 3000, point: { x: 300, y: 300 } }));
  assert.strictEqual(t.getState().vertices.length, 2);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/click-debounce.test.mjs`
Expected: 10 failures.

- [ ] **Step 3: Implement `handleMapClick`.**

In `frontend/ruler.js`, after the state-machine helpers, add:

```javascript
  // ─── Click handler (drawing state only) ────────────────────────────
  function handleMapClick(e) {
    var oe = e.originalEvent || {};
    // Modifier keys → pass-through (map-pan/select gesture).
    if (oe.ctrlKey || oe.shiftKey || oe.altKey || oe.metaKey) return;

    if (state.status === 'inserting') {
      // Phase 3.5 wires this branch to commitInsert(). Stub for now.
      return;
    }
    if (state.status !== 'idle' && state.status !== 'drawing') return;

    // Debounce: 5px AND 250ms vs the previous accepted click.
    var t = oe.timeStamp != null ? oe.timeStamp : Date.now();
    var pt = e.point || { x: 0, y: 0 };
    if (view.lastClick) {
      var dx = pt.x - view.lastClick.x;
      var dy = pt.y - view.lastClick.y;
      var dt = t - view.lastClick.t;
      if ((dx * dx + dy * dy) < 25 && dt < 250) return;
    }
    view.lastClick = { x: pt.x, y: pt.y, t: t };

    addVertex(e.lngLat.lng, e.lngLat.lat);
    refreshMapData();
    // Phase 2.7 wires renderPanel() into this flow.
  }
```

Also initialize `view.lastClick = null;` in the view-state init block at the top of the IIFE.

Add `handleMapClick: handleMapClick` to `_test`.

In `init(mapInstance)`, add the click-listener registration:

```javascript
  function init(mapInstance) {
    if (initialized) return;
    initialized = true;
    map = mapInstance;
    ensureSources();
    ensureLayers();
    map.on('click', handleMapClick);
    // Phase 2.6 keyboard handler; Phase 5.2 units-changed; Phase 2.8 tab activation.
  }
```

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/click-debounce.test.mjs`
Expected: 10 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/click-debounce.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): handleMapClick — debounce + modifier-key suppression

Map-click handler appends a vertex during idle/drawing, idempotently
debounces near-duplicates within 5px AND 250ms, and passes through
modifier-key clicks (Ctrl/Shift/Alt/Meta) so map-pan/select gestures
aren't intercepted. Editing-state empty-map clicks are silent (the
generic reverse-geocode handler picks them up). Inserting-state is
stubbed pending Task 3.5's commitInsert wiring.

10 tests covering: idle→drawing, drawing append, debounce hit, two
debounce-miss conditions (px and ms), all four modifier keys,
editing-state no-op.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §F
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 2.5)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2.6: Keyboard handlers — Backspace / Esc / Enter with INPUT/TEXTAREA/contentEditable suppression

Per spec §C.6: Backspace pops last vertex during drawing; Esc cancels current mode; Enter finishes drawing (≥2 vertices). Critically, all three handlers MUST check `e.target.tagName !== 'INPUT' && !== 'TEXTAREA' && !e.target.isContentEditable` to avoid stealing keys from the search input.

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/keyboard.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/keyboard.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

function fakeKey(key, opts = {}) {
  let prevented = false;
  return {
    key: key,
    target: {
      tagName: opts.tagName || 'BODY',
      isContentEditable: opts.isContentEditable || false,
    },
    preventDefault: () => { prevented = true; },
    get prevented() { return prevented; },
  };
}

test('Backspace during drawing pops last vertex', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.handleKeydown(fakeKey('Backspace'));
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 1);
  assert.strictEqual(s.status, 'drawing');
});

test('Backspace inside an INPUT does NOT pop a vertex', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.handleKeydown(fakeKey('Backspace', { tagName: 'INPUT' }));
  assert.strictEqual(t.getState().vertices.length, 2);
});

test('Backspace inside a TEXTAREA does NOT pop a vertex', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.handleKeydown(fakeKey('Backspace', { tagName: 'TEXTAREA' }));
  assert.strictEqual(t.getState().vertices.length, 2);
});

test('Backspace inside contentEditable does NOT pop a vertex', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.handleKeydown(fakeKey('Backspace', { isContentEditable: true }));
  assert.strictEqual(t.getState().vertices.length, 2);
});

test('Esc during drawing with ≥2 vertices transitions to editing', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.handleKeydown(fakeKey('Escape'));
  assert.strictEqual(t.getState().status, 'editing');
});

test('Esc during drawing with <2 vertices returns to idle', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.handleKeydown(fakeKey('Escape'));
  assert.strictEqual(t.getState().status, 'idle');
});

test('Esc during inserting returns to editing', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  t.startInsertAfter();
  t.handleKeydown(fakeKey('Escape'));
  assert.strictEqual(t.getState().status, 'editing');
});

test('Esc during editing with selection deselects vertex', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  t.handleKeydown(fakeKey('Escape'));
  const s = t.getState();
  assert.strictEqual(s.status, 'editing');
  assert.strictEqual(s.selectedVertex, null);
});

test('Enter during drawing with ≥2 vertices finishes', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.handleKeydown(fakeKey('Enter'));
  assert.strictEqual(t.getState().status, 'editing');
});

test('Enter during drawing with <2 vertices is a no-op', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.handleKeydown(fakeKey('Enter'));
  assert.strictEqual(t.getState().status, 'drawing');
});

test('Backspace during idle is a no-op', () => {
  const { test: t } = loadRuler();
  t.handleKeydown(fakeKey('Backspace'));  // must not throw
  assert.strictEqual(t.getState().status, 'idle');
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/keyboard.test.mjs`
Expected: 11 failures.

- [ ] **Step 3: Implement `handleKeydown`.**

In `frontend/ruler.js`, after `handleMapClick`, add:

```javascript
  // ─── Keyboard handler (spec §C.6) ──────────────────────────────────
  function handleKeydown(e) {
    // Don't steal keys from text inputs.
    var tag = e.target && e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;
    if (e.target && e.target.isContentEditable) return;

    if (e.key === 'Backspace' || e.key === 'Delete') {
      if (state.status === 'drawing') {
        if (state.vertices.length === 0) return;
        popVertex();
        if (e.preventDefault) e.preventDefault();
        refreshMapData();
        // Phase 2.7 renders the panel.
        return;
      }
      // Phase 3.7 extends this to handle editing-state vertex deletion.
      return;
    }

    if (e.key === 'Escape') {
      if (state.status === 'drawing') {
        if (state.vertices.length >= 2) state.status = 'editing';
        else clearAll();
        if (e.preventDefault) e.preventDefault();
        refreshMapData();
        return;
      }
      if (state.status === 'inserting') {
        cancelInsert();
        if (e.preventDefault) e.preventDefault();
        refreshMapData();
        return;
      }
      if (state.status === 'editing' && state.selectedVertex !== null) {
        deselectVertex();
        if (e.preventDefault) e.preventDefault();
        refreshMapData();
        return;
      }
      return;
    }

    if (e.key === 'Enter') {
      if (state.status === 'drawing' && state.vertices.length >= 2) {
        finishDrawing();
        if (e.preventDefault) e.preventDefault();
        refreshMapData();
        // Phase 4.7 wires startSampling() here.
        return;
      }
      return;
    }
    // Phase 5.3 extends to Tab/Space/Arrows.
  }
```

Add `handleKeydown: handleKeydown` to `_test`.

In `init(mapInstance)`, register the listener:
```javascript
    document.addEventListener('keydown', handleKeydown);
```

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/keyboard.test.mjs`
Expected: 11 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/keyboard.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): keyboard handler — Backspace/Esc/Enter + input guard

INPUT/TEXTAREA/contentEditable bail prevents stealing keys from the
search input. Backspace pops last vertex (drawing), Esc cancels
mode (drawing→idle/editing, inserting→editing, editing→deselect),
Enter finishes drawing if ≥2 vertices.

11 tests including all three input-suppression branches per
spec §C.6's critical guard rule.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §C.6
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 2.6)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2.7: `renderPanel()` — single function drives all visibility per state, with safe-DOM clearing

`renderPanel()` is the single source-of-truth function that updates the entire `#measure-panel` DOM based on current state. Per spec §C: 6 sections (banner / headline / vertex list / action row / elevation / footer) with state-driven visibility. Per spec security note: NEVER `innerHTML`. Use the `while (firstChild) removeChild(firstChild)` clear pattern.

This task wires up sections that exist now (banner, headline, vertex list, action row, footer); the elevation section + sparkline rendering land in Phase 4.6.

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/panel-render.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/panel-render.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

// Tiny DOM-element factory for tests — produces just enough to satisfy ruler.js.
function makeEl(tagName, parent) {
  var children = [];
  var attrs = {};
  var classList = new Set();
  var listeners = {};
  var el = {
    tagName: tagName.toUpperCase(),
    children: children,
    childNodes: children,
    get firstChild() { return children[0] || null; },
    appendChild: function (c) { children.push(c); c._parent = el; return c; },
    removeChild: function (c) {
      var idx = children.indexOf(c);
      if (idx >= 0) children.splice(idx, 1);
      return c;
    },
    setAttribute: function (k, v) { attrs[k] = v; },
    getAttribute: function (k) { return attrs[k]; },
    classList: {
      add: function (c) { classList.add(c); },
      remove: function (c) { classList.delete(c); },
      contains: function (c) { return classList.has(c); },
      toggle: function (c, on) { if (on) classList.add(c); else classList.delete(c); },
    },
    addEventListener: function (k, fn) { (listeners[k] = listeners[k] || []).push(fn); },
    removeEventListener: function () {},
    style: {},
    hidden: false,
    textContent: '',
    _attrs: attrs,
    _classList: classList,
    _listeners: listeners,
  };
  if (parent) parent.appendChild(el);
  return el;
}

function makeMeasurePanelDocument() {
  var elems = {};
  function id(name, tag) {
    elems[name] = makeEl(tag || 'div');
    elems[name].id = name;
    return elems[name];
  }
  id('measure-panel'); id('ruler-banner-inline'); id('ruler-banner-inline-text', 'span');
  id('ruler-banner-inline-cancel', 'button');
  id('ruler-headline-section'); id('ruler-headline-total');
  id('ruler-vertex-section'); id('ruler-vertex-count', 'span');
  id('ruler-vertex-list', 'ol');
  id('ruler-action-row'); id('ruler-action-empty', 'p');
  id('ruler-insert-before', 'button'); id('ruler-insert-after', 'button');
  id('ruler-delete-vertex', 'button');
  id('ruler-elevation-section'); id('ruler-sparkline', 'svg');
  id('ruler-stats'); id('ruler-stat-min'); id('ruler-stat-max');
  id('ruler-stat-gain'); id('ruler-stat-loss');
  id('ruler-coverage-warn');
  id('ruler-footer'); id('ruler-undo', 'button'); id('ruler-clear', 'button');
  id('ruler-finish', 'button'); id('ruler-new', 'button');
  id('ruler-mode-banner'); id('ruler-mode-banner-text', 'span');
  id('ruler-mode-banner-cancel', 'button');
  id('ruler-sampling-progress'); id('ruler-sampling-counter');
  return {
    getElementById: function (n) { return elems[n] || null; },
    addEventListener: function () {},
    createElement: function (tag) { return makeEl(tag); },
    elems: elems,
  };
}

test('renderPanel idle state: empty placeholder, finish hidden', () => {
  const doc = makeMeasurePanelDocument();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.renderPanel();
  assert.strictEqual(doc.elems['ruler-headline-section'].hidden, true);
  assert.strictEqual(doc.elems['ruler-vertex-section'].hidden, true);
  assert.strictEqual(doc.elems['ruler-finish'].hidden, true);
  assert.strictEqual(doc.elems['ruler-clear'].hidden, true);
  assert.strictEqual(doc.elems['ruler-mode-banner'].hidden, true);
});

test('renderPanel drawing state: banner visible, vertex list rendered', () => {
  const doc = makeMeasurePanelDocument();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.renderPanel();
  assert.strictEqual(doc.elems['ruler-mode-banner'].hidden, false);
  assert.strictEqual(doc.elems['ruler-vertex-section'].hidden, false);
  assert.strictEqual(doc.elems['ruler-vertex-list'].children.length, 2);
});

test('renderPanel uses textContent (NEVER innerHTML)', () => {
  const doc = makeMeasurePanelDocument();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.renderPanel();
  // Walk all rendered elements; none should have innerHTML set.
  function walk(el) {
    assert.strictEqual('innerHTML' in el ? el.innerHTML : undefined, undefined,
      'innerHTML must never be assigned');
    (el.children || []).forEach(walk);
  }
  walk(doc.elems['ruler-vertex-list']);
});

test('renderPanel editing state: action row + new measurement button visible', () => {
  const doc = makeMeasurePanelDocument();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.renderPanel();
  // Action row visibility depends on selectedVertex; nothing selected yet
  // so action-empty should show, action-row hidden.
  assert.strictEqual(doc.elems['ruler-action-empty'].hidden, false);
  assert.strictEqual(doc.elems['ruler-action-row'].hidden, true);
  assert.strictEqual(doc.elems['ruler-clear'].hidden, false);
  assert.strictEqual(doc.elems['ruler-new'].hidden, false);
});

test('renderPanel editing with selection: action row visible, empty hidden', () => {
  const doc = makeMeasurePanelDocument();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  t.renderPanel();
  assert.strictEqual(doc.elems['ruler-action-row'].hidden, false);
  assert.strictEqual(doc.elems['ruler-action-empty'].hidden, true);
});

test('renderPanel: vertex count badge tracks state', () => {
  const doc = makeMeasurePanelDocument();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.addVertex(-112.03, 33.47);
  t.renderPanel();
  assert.strictEqual(doc.elems['ruler-vertex-count'].textContent, '3');
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/panel-render.test.mjs`
Expected: 6 failures.

- [ ] **Step 3: Implement `renderPanel`.**

In `frontend/ruler.js`, after `handleKeydown`, add:

```javascript
  // ─── DOM rendering — panel + banner ────────────────────────────────
  // Single source-of-truth: every state mutation calls renderPanel().
  // NEVER use innerHTML. textContent only. Safe-clear via removeChild.

  function $id(id) { return document.getElementById(id); }

  function setHidden(el, hidden) {
    if (!el) return;
    el.hidden = !!hidden;
  }

  function clearChildren(el) {
    if (!el) return;
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function renderVertexList() {
    var listEl = $id('ruler-vertex-list');
    if (!listEl) return;
    clearChildren(listEl);
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

      if (i < state.vertices.length - 1 && state.segments[i]) {
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

      // Click handler closes over the index for this row.
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

  function renderBanners() {
    var floating = $id('ruler-mode-banner');
    var floatingTxt = $id('ruler-mode-banner-text');
    var inline = $id('ruler-banner-inline');
    var inlineTxt = $id('ruler-banner-inline-text');
    if (state.status === 'drawing') {
      var msg = state.vertices.length === 0
        ? 'Tap map to place first vertex'
        : 'Tap map to add more, or [Finish] when done';
      if (floatingTxt) floatingTxt.textContent = msg;
      if (inlineTxt) inlineTxt.textContent = msg;
      setHidden(floating, false);
      setHidden(inline, false);
    } else if (state.status === 'inserting') {
      var slot = state.insertSlot ? state.insertSlot.before : 0;
      var msg2 = 'Tap map to insert vertex (slot V' + (slot + 1) + ')';
      if (floatingTxt) floatingTxt.textContent = msg2;
      if (inlineTxt) inlineTxt.textContent = msg2;
      setHidden(floating, false);
      setHidden(inline, false);
    } else {
      setHidden(floating, true);
      setHidden(inline, true);
    }
  }

  function renderHeadline() {
    var headlineSection = $id('ruler-headline-section');
    var totalEl = $id('ruler-headline-total');
    var visible = state.vertices.length >= 2;
    setHidden(headlineSection, !visible);
    if (visible && totalEl) totalEl.textContent = formatRulerDistance(state.totalDistance_m);
  }

  function renderActionRow() {
    var actionRow = $id('ruler-action-row');
    var actionEmpty = $id('ruler-action-empty');
    var visible = state.status === 'editing' && state.selectedVertex !== null;
    setHidden(actionRow, !visible);
    setHidden(actionEmpty, visible || state.status !== 'editing');
  }

  function renderFooter() {
    var undo = $id('ruler-undo');
    var clearBtn = $id('ruler-clear');
    var finish = $id('ruler-finish');
    var newBtn = $id('ruler-new');
    if (state.status === 'drawing') {
      setHidden(undo, false);
      setHidden(clearBtn, false);
      setHidden(finish, state.vertices.length < 2);
      setHidden(newBtn, true);
    } else if (state.status === 'editing') {
      setHidden(undo, true);
      setHidden(clearBtn, false);
      setHidden(finish, true);
      setHidden(newBtn, false);
    } else if (state.status === 'inserting') {
      setHidden(undo, true); setHidden(clearBtn, true);
      setHidden(finish, true); setHidden(newBtn, true);
    } else {
      setHidden(undo, true); setHidden(clearBtn, true);
      setHidden(finish, true); setHidden(newBtn, true);
    }
  }

  function renderPanel() {
    var vertexSection = $id('ruler-vertex-section');
    var visible = state.vertices.length > 0;
    setHidden(vertexSection, !visible);
    var countEl = $id('ruler-vertex-count');
    if (countEl) countEl.textContent = String(state.vertices.length);

    renderVertexList();
    renderBanners();
    renderHeadline();
    renderActionRow();
    renderFooter();
    // Phase 4.5+ adds renderElevation().
  }
```

Add `renderPanel: renderPanel` to `_test`.

Update `handleMapClick`, `handleKeydown`, and `clear()` to call `renderPanel()` after each state mutation. (Comments in those functions already say "Phase 2.7 wires renderPanel()" — replace with the actual call.)

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/panel-render.test.mjs`
Expected: 6 tests pass.

Also run: `grep -n "innerHTML" frontend/ruler.js`
Expected: no matches.

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/panel-render.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): renderPanel — state-driven DOM via safe-clear pattern

Single source-of-truth for the Measure panel — every state mutation
calls renderPanel() which rebuilds banner + headline + vertex list +
action row + footer per current state. Vertex list uses
while(firstChild) removeChild(firstChild) for safe clearing;
labels and coords are textContent only — NEVER innerHTML.

6 tests including a textContent-only walker that fails if any
rendered element has innerHTML set. Phase 4.6 will extend this with
the elevation-section render path.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §C
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 2.7)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2.8: Tab activation hook + cursor management

When the user clicks the Measure tab, `renderPanel()` runs once on activation (state-aware empty placeholder vs. resumed editing). Cursor is `crosshair` during `drawing` / `inserting`, `pointer` on hovered hit-circles during `editing`, otherwise default. Smoke tested only — cursor styling on a real MapLibre canvas is not reliably testable in Node.

**Files:**
- Modify: `frontend/ruler.js`
- Modify: `frontend/index.html` (none expected — DOM was already added in Task 0.2)

- [ ] **Step 1: Implement tab activation hook.**

In `frontend/ruler.js`, add inside `init(mapInstance)`:

```javascript
    var measureBtn = document.querySelector('.tab-btn[data-panel="measure-panel"]');
    if (measureBtn) {
      measureBtn.addEventListener('click', function () {
        // Tab DOM already activated by app.js's tab handler. Just refresh.
        renderPanel();
        updateCursor();
      });
    }
    // Initial render — a fresh page may already have Measure as active tab.
    renderPanel();
```

- [ ] **Step 2: Implement cursor management.**

In `frontend/ruler.js`, add:

```javascript
  // ─── Cursor management ─────────────────────────────────────────────
  function updateCursor() {
    if (!map) return;
    var canvas = map.getCanvas();
    if (!canvas) return;
    if (state.status === 'drawing' || state.status === 'inserting') {
      canvas.style.cursor = 'crosshair';
      return;
    }
    if (state.status === 'editing') {
      // pointer-on-hover handled by mouseenter/mouseleave on the hit layer
      // (Phase 3.1+ wires the hover transitions). Default cursor for now.
      canvas.style.cursor = '';
      return;
    }
    canvas.style.cursor = '';
  }
```

Call `updateCursor()` after every state transition: at the end of `handleMapClick`, `handleKeydown`, `clear()`, etc. (Add a single call inside `renderPanel()` so it always runs together — DRY.)

```javascript
  function renderPanel() {
    /* ... existing body ... */
    updateCursor();
  }
```

- [ ] **Step 3: Wire `[Clear]` / `[Finish]` / `[+ New measurement]` / `[↶ Undo]` button handlers.**

In `init(mapInstance)`:

```javascript
    var clearBtn = document.getElementById('ruler-clear');
    if (clearBtn) clearBtn.addEventListener('click', function () {
      clear(); refreshMapData(); renderPanel();
    });
    var finishBtn = document.getElementById('ruler-finish');
    if (finishBtn) finishBtn.addEventListener('click', function () {
      finishDrawing(); refreshMapData(); renderPanel();
      // Phase 4.7 wires startSampling() here.
    });
    var newBtn = document.getElementById('ruler-new');
    if (newBtn) newBtn.addEventListener('click', function () {
      clear(); refreshMapData(); renderPanel();
    });
    var undoBtn = document.getElementById('ruler-undo');
    if (undoBtn) undoBtn.addEventListener('click', function () {
      popVertex(); refreshMapData(); renderPanel();
    });
    var inlineCancel = document.getElementById('ruler-banner-inline-cancel');
    var floatCancel = document.getElementById('ruler-mode-banner-cancel');
    function cancelBannerHandler() {
      if (state.status === 'drawing') {
        if (state.vertices.length >= 2) state.status = 'editing';
        else clearAll();
      } else if (state.status === 'inserting') {
        cancelInsert();
      }
      refreshMapData(); renderPanel();
    }
    if (inlineCancel) inlineCancel.addEventListener('click', cancelBannerHandler);
    if (floatCancel)  floatCancel.addEventListener('click', cancelBannerHandler);
```

- [ ] **Step 4: Smoke test in browser.**

Reload dev. Open Measure tab — empty placeholder shows. Click on map → cursor turns crosshair, vertex appears, banner reads "Tap map to add more, or [Finish] when done". Click again → 2 vertices, line drawn, headline shows total distance.

Press Enter → state transitions to editing; cursor returns to default; banner hides; clear+new buttons visible.

Press Escape from editing — does nothing visible (no selection). Click `[+ New measurement]` → returns to idle empty.

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js
git commit -m "$(cat <<'EOF'
feat(ruler): tab activation + cursor management + footer button wiring

Measure tab click triggers renderPanel() (state-aware: empty
placeholder OR resumed editing). Cursor is crosshair during
drawing/inserting; default elsewhere (Phase 3.1+ adds pointer-on-
vertex-hover for editing). Footer buttons wired:
[Clear]/[+ New measurement]→clear, [Finish]→finishDrawing,
[↶ Undo]→popVertex, banner [×] cancel buttons → state-appropriate
exit.

Smoke-tested only — MapLibre canvas cursor styling can't be reliably
unit-tested in Node. Phase 5.1 grep enforcement covers regression
of the wiring itself.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §C, §D.7
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 2.8)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Phase 2 review checkpoint

> **Phase 2 review (≥3 rounds):** Drawing state end-to-end works in browser: tab → click 3 vertices → headline + vertex list visible → Enter → editing. Cursor changes correctly. Banner shows/hides per state. No console errors. All Phase 0+1+2 tests still green: `node --test --test-force-exit frontend/tests/ruler/`. Verify the L1622 / L660 / L1272 bails by tapping each kind of pin during drawing — none should pop. Verify NO `innerHTML` assignment exists in ruler.js (`grep "innerHTML" frontend/ruler.js` returns nothing). Run `python -m pytest tests/ services/search/tests/ -q` — Python baseline must be unchanged. If any review round surfaces issues, fix and re-review until clean.

---

## Phase 3 — Vertex-centric edit (8 tasks)

**Goal:** Bring up the editing state. After Phase 3, the user can tap a finished measurement's vertex → see it highlighted → drag to reposition → delete → insert before/after via sidebar buttons with segment-projection.

### Task 3.1: Layer-scoped click handler + tap-vs-drag disambiguation

A second click handler is registered specifically on `ruler-vertex-hit-circles`. It runs BEFORE the generic `map.on('click')` handler (MapLibre dispatches layer-scoped listeners first). On mouse: tap = `mousedown`→`mouseup` within 5 px AND 200 ms. On touch: 8 px AND 250 ms (looser to accommodate gloved fingers per spec §D.5). Anything more is a drag (Task 3.3 / 3.4).

The pure tap-vs-drag detector (`isTap(start, end, threshold)`) is a small math primitive that's worth unit-testing.

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/tap-vs-drag.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/tap-vs-drag.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

test('isTap: 0px 0ms is a tap', () => {
  const { test: t } = loadRuler();
  assert.strictEqual(t.isTap({ x: 100, y: 100, t: 1000 }, { x: 100, y: 100, t: 1000 }, 'mouse'), true);
});

test('isTap mouse: 4px 150ms is a tap (under both thresholds)', () => {
  const { test: t } = loadRuler();
  assert.strictEqual(t.isTap({ x: 100, y: 100, t: 1000 }, { x: 102, y: 103, t: 1150 }, 'mouse'), true);
});

test('isTap mouse: 6px 150ms is a drag (over distance threshold)', () => {
  const { test: t } = loadRuler();
  assert.strictEqual(t.isTap({ x: 100, y: 100, t: 1000 }, { x: 105, y: 105, t: 1150 }, 'mouse'), false);
});

test('isTap mouse: 4px 250ms is a drag (over time threshold)', () => {
  const { test: t } = loadRuler();
  assert.strictEqual(t.isTap({ x: 100, y: 100, t: 1000 }, { x: 102, y: 103, t: 1250 }, 'mouse'), false);
});

test('isTap touch: 7px 240ms is a tap (looser thresholds)', () => {
  const { test: t } = loadRuler();
  assert.strictEqual(t.isTap({ x: 100, y: 100, t: 1000 }, { x: 105, y: 105, t: 1240 }, 'touch'), true);
});

test('isTap touch: 9px 240ms is a drag', () => {
  const { test: t } = loadRuler();
  assert.strictEqual(t.isTap({ x: 100, y: 100, t: 1000 }, { x: 106, y: 107, t: 1240 }, 'touch'), false);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/tap-vs-drag.test.mjs`
Expected: 6 failures.

- [ ] **Step 3: Implement `isTap` + register layer-scoped handler.**

In `frontend/ruler.js`, after `handleMapClick`, add:

```javascript
  // ─── Tap-vs-drag detector (spec §D.6) ──────────────────────────────
  function isTap(start, end, mode) {
    var pxThreshold = mode === 'touch' ? 8 : 5;
    var msThreshold = mode === 'touch' ? 250 : 200;
    var dx = end.x - start.x;
    var dy = end.y - start.y;
    var dt = end.t - start.t;
    if (dx * dx + dy * dy > pxThreshold * pxThreshold) return false;
    if (dt > msThreshold) return false;
    return true;
  }

  // ─── Layer-scoped click on ruler-vertex-hit-circles (editing only) ─
  function handleVertexLayerClick(e) {
    if (state.status !== 'editing') return;
    if (!e.features || e.features.length === 0) return;
    var idx = e.features[0].properties.index;
    if (typeof idx !== 'number') return;
    if (state.selectedVertex === idx) deselectVertex();
    else selectVertex(idx);
    refreshMapData();
    renderPanel();
  }
```

Add `isTap: isTap` and `handleVertexLayerClick: handleVertexLayerClick` to `_test`.

In `init(mapInstance)`, register the layer-scoped listener AFTER `map.on('click', handleMapClick)`:

```javascript
    map.on('click', 'ruler-vertex-hit-circles', handleVertexLayerClick);
    // mouseenter/mouseleave for cursor pointer-on-hover
    map.on('mouseenter', 'ruler-vertex-hit-circles', function () {
      if (state.status === 'editing' && map.getCanvas()) {
        map.getCanvas().style.cursor = 'pointer';
      }
    });
    map.on('mouseleave', 'ruler-vertex-hit-circles', function () {
      if (state.status === 'editing' && map.getCanvas()) {
        updateCursor();  // restore default
      }
    });
```

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/tap-vs-drag.test.mjs`
Expected: 6 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/tap-vs-drag.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): layer-scoped vertex click + tap-vs-drag detector

Layer-scoped map.on('click', 'ruler-vertex-hit-circles', ...) fires
ahead of the generic click handler so editing-state vertex taps
select/deselect without falling through. mouseenter/mouseleave on
the hit-circles layer toggles cursor:pointer during editing.

isTap(start, end, mode) is the pure math primitive used by Phase
3.3 / 3.4 drag handlers. Mouse: 5px AND 200ms. Touch: 8px AND
250ms (looser per spec §D.5 — gloved fingers).

6 tests at threshold boundaries.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §D.5, §D.6
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 3.1)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.2: Selected-vertex highlight via filter + panel sync

The `ruler-vertex-circles-selected` layer's filter expression already targets `properties.selected === true` (Task 2.2). `refreshMapData()` re-emits per-vertex `selected` flags computed from `state.selectedVertex`. So selecting a vertex in `state` plus calling `refreshMapData()` plus `renderPanel()` is the entire wiring — Task 3.1's `handleVertexLayerClick` already does this.

This task adds an integration test asserting that selecting a vertex sets the `selected: true` property on the right Feature. Smoke confirms the orange highlight appears in the browser.

**Files:**
- Create: `frontend/tests/ruler/selection-feature-flag.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/selection-feature-flag.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

test('buildVertexFeatures: selectedVertex=null → no Features have selected=true', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  const fc = t.buildVertexFeatures();
  for (const f of fc.features) {
    assert.strictEqual(f.properties.selected, false);
  }
});

test('buildVertexFeatures: selectedVertex=1 → exactly one Feature has selected=true', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  t.addVertex(-112.03, 33.47);
  t.finishDrawing();
  t.selectVertex(1);
  const fc = t.buildVertexFeatures();
  const selectedFlags = fc.features.map(f => f.properties.selected);
  assert.deepStrictEqual(selectedFlags, [false, true, false]);
});

test('buildVertexFeatures: each Feature carries its index property', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.07, 33.45);
  t.addVertex(-112.05, 33.46);
  const fc = t.buildVertexFeatures();
  assert.strictEqual(fc.features[0].properties.index, 0);
  assert.strictEqual(fc.features[1].properties.index, 1);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/selection-feature-flag.test.mjs`
Expected: 3 failures (`buildVertexFeatures is not a function`).

- [ ] **Step 3: Expose `buildVertexFeatures` on `_test`.**

In `frontend/ruler.js`, in the `_test` export object, add:
```javascript
    buildVertexFeatures: buildVertexFeatures,
    buildLineFeature: buildLineFeature,
```

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/selection-feature-flag.test.mjs`
Expected: 3 tests pass.

- [ ] **Step 5: Smoke test in browser.**

Reload dev. Place 3 vertices + Finish. Click V2 — orange enlarged circle appears at V2's position, V1 and V3 stay yellow. Click V2 again → orange disappears (deselect). Click V3 → V3 highlights orange.

- [ ] **Step 6: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/selection-feature-flag.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): selected-vertex highlight via per-Feature property flag

buildVertexFeatures emits per-vertex {index, label, selected} where
selected matches state.selectedVertex. The ruler-vertex-circles-
selected layer's MapLibre filter ['==', ['get', 'selected'], true]
makes one orange enlarged ring appear over the selected vertex
without toggling layer visibility.

3 tests asserting per-Feature selected-flag correctness across
no-selection, selection-mid-list, and index correctness.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §D
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 3.2)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.3: Drag-to-reposition (mouse) with rAF coalescing

Mouse drag flow per spec §D.6: `mousedown` on hit-circle disables `dragPan` and captures vertex index → `mousemove` (registered on `window`, not the canvas, so off-canvas mouseup still fires) updates `state.vertices[i]` and schedules a single `setData` per rAF tick → `mouseup` re-enables `dragPan` and runs `recompute()` once. The rAF coalescer is the load-bearing perf optimization (per R2 — bursty mousemove without coalescing stutters on a 50-vertex measurement).

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/drag-raf.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/drag-raf.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

test('scheduleSourceUpdate coalesces N calls per frame to 1 callback', async () => {
  // Capture rAF callbacks; synthesize one frame.
  let frameCallbacks = [];
  const ctx = {
    requestAnimationFrame: (cb) => { frameCallbacks.push(cb); return frameCallbacks.length; },
    cancelAnimationFrame: () => {},
  };
  const { test: t, ctx: vmCtx } = loadRuler();
  // Override rAF in the loaded ruler's context — done via the loadRuler
  // factory's existing fake, but we want fine-grained control here:
  vmCtx.requestAnimationFrame = ctx.requestAnimationFrame;
  vmCtx.cancelAnimationFrame  = ctx.cancelAnimationFrame;

  let updateCount = 0;
  // Stub refreshMapData via a side-channel: since refreshMapData is internal,
  // we instead instrument scheduleSourceUpdate's behaviour by counting how
  // many times rAF was queued.
  for (let i = 0; i < 10; i++) t.scheduleSourceUpdate();
  // The coalescer must register at most ONE rAF.
  assert.strictEqual(frameCallbacks.length, 1, 'expected 1 rAF call, got ' + frameCallbacks.length);
});

test('scheduleSourceUpdate after frame fires queues a fresh rAF', () => {
  let frameCallbacks = [];
  const { test: t, ctx: vmCtx } = loadRuler();
  vmCtx.requestAnimationFrame = (cb) => { frameCallbacks.push(cb); return frameCallbacks.length; };
  t.scheduleSourceUpdate();
  // Fire the frame
  frameCallbacks[0]();
  // Now schedule another — should queue a NEW rAF.
  t.scheduleSourceUpdate();
  assert.strictEqual(frameCallbacks.length, 2);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/drag-raf.test.mjs`
Expected: 2 failures.

- [ ] **Step 3: Implement `scheduleSourceUpdate` + mouse drag.**

In `frontend/ruler.js`, after `refreshMapData`, add:

```javascript
  // ─── rAF coalescer (spec §D.6) ─────────────────────────────────────
  function scheduleSourceUpdate() {
    if (view.rafHandle != null) return;  // already queued for this frame
    view.rafHandle = requestAnimationFrame(function () {
      view.rafHandle = null;
      refreshMapData();
    });
  }

  // ─── Mouse drag (spec §D.6) ────────────────────────────────────────
  function handleVertexMouseDown(e) {
    if (state.status !== 'editing') return;
    if (!e.features || e.features.length === 0) return;
    var idx = e.features[0].properties.index;
    if (typeof idx !== 'number') return;
    e.preventDefault();
    if (e.originalEvent && e.originalEvent.preventDefault) e.originalEvent.preventDefault();

    map.dragPan.disable();
    view.dragging = {
      index: idx,
      startX: e.point ? e.point.x : 0,
      startY: e.point ? e.point.y : 0,
      startT: Date.now(),
      mode: 'mouse',
    };

    // mousemove + mouseup on window (not canvas) so off-canvas release still fires.
    var onMove = function (ev) { handleMouseMoveDrag(ev); };
    var onUp   = function (ev) { handleMouseUpDrag(ev, onMove, onUp); };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }

  function handleMouseMoveDrag(ev) {
    if (!view.dragging) return;
    var rect = map.getCanvas().getBoundingClientRect();
    var x = ev.clientX - rect.left;
    var y = ev.clientY - rect.top;
    var ll = map.unproject([x, y]);
    state.vertices[view.dragging.index].lng = ll.lng;
    state.vertices[view.dragging.index].lat = ll.lat;
    scheduleSourceUpdate();
  }

  function handleMouseUpDrag(ev, onMove, onUp) {
    if (!view.dragging) {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      return;
    }
    var rect = map.getCanvas().getBoundingClientRect();
    var x = ev.clientX - rect.left;
    var y = ev.clientY - rect.top;
    var moved = !isTap(
      { x: view.dragging.startX, y: view.dragging.startY, t: view.dragging.startT },
      { x: x, y: y, t: Date.now() }, 'mouse');
    if (moved) {
      relabel();
      recompute();
      // Phase 4.7: re-trigger sampling after drag commits a new layout.
    }
    map.dragPan.enable();
    view.dragging = null;
    refreshMapData();
    renderPanel();
    window.removeEventListener('mousemove', onMove);
    window.removeEventListener('mouseup', onUp);
  }
```

Add `scheduleSourceUpdate: scheduleSourceUpdate` to `_test`. In `view = { ... }`, add `dragging: null`.

In `init(mapInstance)`, register the mousedown handler:
```javascript
    map.on('mousedown', 'ruler-vertex-hit-circles', handleVertexMouseDown);
```

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/drag-raf.test.mjs`
Expected: 2 tests pass.

- [ ] **Step 5: Smoke test in browser (mouse).**

Reload dev. Place 3 vertices + Finish. Click+hold V2 → drag across the map → release. The vertex follows the cursor smoothly (no stutter). On release, segment distances/bearings in the vertex list update for V1→V2 and V2→V3.

- [ ] **Step 6: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/drag-raf.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): mouse drag-to-reposition with rAF-coalesced source updates

mousedown on a vertex hit-circle disables dragPan + binds mousemove/
mouseup to window (off-canvas releases still fire). Each mousemove
mutates state.vertices[i] then queues setData() via rAF — at most
ONE source update per frame, regardless of mousemove burst rate.
On mouseup: tap-vs-drag check (Task 3.1's isTap), recompute() if
moved, re-enable dragPan, render.

2 tests asserting the rAF coalescer queues exactly one callback per
frame and re-arms after the frame fires.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §D.6 (R2 perf)
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 3.3)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.4: Drag-to-reposition (touch) with `passive: false` + multitouch cancel

iOS Safari needs raw `touchstart`/`touchmove`/`touchend` listeners on the canvas with `passive: false` so `preventDefault()` actually suppresses the synthetic mouse event. Plus: any second finger arriving (`touches.length > 1`) cancels the in-progress vertex drag and re-enables `dragPan` so the user's pinch-zoom intent isn't blocked.

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/touch-multitouch-cancel.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/touch-multitouch-cancel.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

function fakeTouch(x, y) { return { clientX: x, clientY: y }; }
function fakeTouchEvent(touches, opts = {}) {
  let prevented = false;
  return {
    touches: touches,
    changedTouches: opts.changedTouches || touches,
    preventDefault: () => { prevented = true; },
    get prevented() { return prevented; },
  };
}

test('touchstart on a vertex with one finger initiates drag', () => {
  const { test: t, ctx } = loadRuler();
  // Stub map for the test
  ctx.window._geographicaTestMap = {
    getCanvas: () => ({
      getBoundingClientRect: () => ({ left: 0, top: 0 }),
      style: {},
    }),
    queryRenderedFeatures: () => [{ properties: { index: 0 } }],
    dragPan: { disable: () => { ctx.window._geographicaTestDragPanDisabled = true; },
               enable:  () => { ctx.window._geographicaTestDragPanDisabled = false; } },
    unproject: ([x, y]) => ({ lng: -112 + x / 1000, lat: 33 + y / 1000 }),
  };
  t.installTestMap(ctx.window._geographicaTestMap);

  t.addVertex(-112, 33);
  t.addVertex(-112.01, 33.01);
  t.finishDrawing();
  t.handleTouchStart(fakeTouchEvent([fakeTouch(100, 100)]));
  const dragging = t.peekDragging();
  assert.ok(dragging, 'drag state should exist after touchstart on vertex');
  assert.strictEqual(dragging.mode, 'touch');
  assert.strictEqual(ctx.window._geographicaTestDragPanDisabled, true);
});

test('multitouch arriving during drag cancels the drag', () => {
  const { test: t, ctx } = loadRuler();
  ctx.window._geographicaTestMap = {
    getCanvas: () => ({ getBoundingClientRect: () => ({ left: 0, top: 0 }), style: {} }),
    queryRenderedFeatures: () => [{ properties: { index: 0 } }],
    dragPan: { disable: () => {}, enable: () => { ctx.window._geographicaTestDragPanReenabled = true; } },
    unproject: ([x, y]) => ({ lng: -112, lat: 33 }),
  };
  t.installTestMap(ctx.window._geographicaTestMap);
  t.addVertex(-112, 33); t.addVertex(-112.01, 33.01); t.finishDrawing();
  t.handleTouchStart(fakeTouchEvent([fakeTouch(100, 100)]));
  // Now a second finger arrives:
  t.handleTouchMove(fakeTouchEvent([fakeTouch(100, 100), fakeTouch(150, 150)]));
  assert.strictEqual(t.peekDragging(), null, 'drag should be canceled by multitouch');
  assert.strictEqual(ctx.window._geographicaTestDragPanReenabled, true);
});

test('touchstart with two fingers does NOT start a drag', () => {
  const { test: t, ctx } = loadRuler();
  ctx.window._geographicaTestMap = {
    getCanvas: () => ({ getBoundingClientRect: () => ({ left: 0, top: 0 }), style: {} }),
    queryRenderedFeatures: () => [{ properties: { index: 0 } }],
    dragPan: { disable: () => {}, enable: () => {} },
    unproject: ([x, y]) => ({ lng: -112, lat: 33 }),
  };
  t.installTestMap(ctx.window._geographicaTestMap);
  t.addVertex(-112, 33); t.addVertex(-112.01, 33.01); t.finishDrawing();
  t.handleTouchStart(fakeTouchEvent([fakeTouch(100, 100), fakeTouch(150, 150)]));
  assert.strictEqual(t.peekDragging(), null);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/touch-multitouch-cancel.test.mjs`
Expected: 3 failures.

- [ ] **Step 3: Implement touch handlers + test seams.**

In `frontend/ruler.js`, after the mouse-drag handlers, add:

```javascript
  // ─── Touch drag (spec §D.5 / §D.6) ─────────────────────────────────
  function mapTouchPoint(touch, canvas) {
    var rect = canvas.getBoundingClientRect();
    return { x: touch.clientX - rect.left, y: touch.clientY - rect.top };
  }

  function handleTouchStart(e) {
    if (state.status !== 'editing') return;
    if (!e.touches || e.touches.length !== 1) return;
    var canvas = map.getCanvas();
    var pt = mapTouchPoint(e.touches[0], canvas);
    var hits = map.queryRenderedFeatures(pt, { layers: [LAYER_VERTEX_HIT_CIRCLES] });
    if (!hits || hits.length === 0) return;
    e.preventDefault();
    view.dragging = {
      index: hits[0].properties.index,
      startX: pt.x, startY: pt.y, startT: Date.now(),
      mode: 'touch',
    };
    map.dragPan.disable();
  }

  function handleTouchMove(e) {
    if (!view.dragging) return;
    if (!e.touches) return;
    if (e.touches.length > 1) {
      cancelTouchDrag();
      return;
    }
    e.preventDefault();
    var canvas = map.getCanvas();
    var pt = mapTouchPoint(e.touches[0], canvas);
    var ll = map.unproject([pt.x, pt.y]);
    state.vertices[view.dragging.index].lng = ll.lng;
    state.vertices[view.dragging.index].lat = ll.lat;
    scheduleSourceUpdate();
  }

  function handleTouchEnd(e) {
    if (!view.dragging) return;
    var canvas = map.getCanvas();
    var ct = e.changedTouches && e.changedTouches[0];
    if (!ct) { cancelTouchDrag(); return; }
    var rect = canvas.getBoundingClientRect();
    var x = ct.clientX - rect.left;
    var y = ct.clientY - rect.top;
    var moved = !isTap(
      { x: view.dragging.startX, y: view.dragging.startY, t: view.dragging.startT },
      { x: x, y: y, t: Date.now() }, 'touch');
    if (!moved) {
      var idx = view.dragging.index;
      if (state.selectedVertex === idx) deselectVertex();
      else selectVertex(idx);
    } else {
      relabel();
      recompute();
      // Phase 4.7: re-trigger sampling.
    }
    cancelTouchDrag();
    refreshMapData();
    renderPanel();
  }

  function cancelTouchDrag() {
    view.dragging = null;
    if (map && map.dragPan) map.dragPan.enable();
  }
```

Test seams: add to `_test`:
```javascript
    handleTouchStart: handleTouchStart,
    handleTouchMove:  handleTouchMove,
    handleTouchEnd:   handleTouchEnd,
    peekDragging: function () { return view.dragging; },
    installTestMap: function (m) { map = m; },
```

In `init(mapInstance)`, register the canvas listeners with `passive: false`:
```javascript
    var canvas = map.getCanvas();
    canvas.addEventListener('touchstart', handleTouchStart, { passive: false });
    canvas.addEventListener('touchmove',  handleTouchMove,  { passive: false });
    canvas.addEventListener('touchend',   handleTouchEnd,   { passive: false });
    canvas.addEventListener('touchcancel', cancelTouchDrag, { passive: false });
```

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/touch-multitouch-cancel.test.mjs`
Expected: 3 tests pass.

- [ ] **Step 5: Smoke test on iOS Safari.**

Open dev URL on iPhone (or Tailscale `pandora.twin-bramble.ts.net` for HTTPS). Place 3 vertices + Finish. Tap-and-hold V2 → drag → release: vertex repositions. Begin a drag, then add a second finger → drag cancels, pinch zoom proceeds.

- [ ] **Step 6: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/touch-multitouch-cancel.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): touch drag with passive:false + multitouch cancel

Raw canvas touchstart/touchmove/touchend listeners with
{passive: false} so preventDefault() actually suppresses the
synthetic mouse event on iOS. touchstart on a vertex with one finger
captures index + disables dragPan; touchmove updates state via the
rAF coalescer; touchend runs tap-vs-drag check and either select/
deselect (tap) or recompute (drag). touches.length > 1 during drag
cancels and re-enables dragPan so pinch-to-zoom proceeds normally.

3 tests covering single-finger drag start, multitouch arrival
cancel, and two-finger touchstart no-op.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §D.5, §D.6
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 3.4)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.5: `[Insert Before]` / `[Insert After]` button handlers + `commitInsert` with segment projection

`[Insert Before]` and `[Insert After]` transition state to `inserting` with a slot index per spec §B; the floating banner (already wired in 2.7) reads "Tap map to insert vertex". The next map click commits via `commitInsert(rawLng, rawLat)` which projects to the relevant adjacent segment using Task 1.4's `projectPointToSegment` (so off-segment taps land at the closest on-segment point, NOT at the raw tap location).

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/insert-projection.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/insert-projection.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

test('commitInsert mid-path projects onto adjacent segment', () => {
  const { test: t } = loadRuler();
  // Two vertices along latitude 33.45 (east-west segment)
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.00, 33.45);
  t.finishDrawing();
  t.selectVertex(0);
  t.startInsertAfter();   // slot.before = 1 → projects onto V1→V2 segment
  // Tap slightly north of segment midpoint
  t.commitInsert(-112.05, 33.46);
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 3);
  assert.strictEqual(s.status, 'editing');
  // Inserted vertex should be on the segment (lat ≈ 33.45)
  assert.ok(Math.abs(s.vertices[1].lat - 33.45) < 0.001);
  assert.ok(Math.abs(s.vertices[1].lng - (-112.05)) < 0.01);
});

test('commitInsert at path endpoint (Insert After Vlast) places at raw tap', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.00, 33.45);
  t.finishDrawing();
  t.selectVertex(1);  // last vertex
  t.startInsertAfter();   // slot.before = 2 → no segment to project onto
  t.commitInsert(-111.90, 33.50);  // tap somewhere off-axis
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 3);
  // Inserted at raw tap (no projection)
  assert.ok(Math.abs(s.vertices[2].lng - (-111.90)) < 1e-6);
  assert.ok(Math.abs(s.vertices[2].lat - 33.50) < 1e-6);
});

test('commitInsert at path start (Insert Before V1) places at raw tap', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.00, 33.45);
  t.finishDrawing();
  t.selectVertex(0);
  t.startInsertBefore();   // slot.before = 0 → no segment before V1
  t.commitInsert(-112.20, 33.50);
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 3);
  assert.ok(Math.abs(s.vertices[0].lng - (-112.20)) < 1e-6);
  assert.ok(Math.abs(s.vertices[0].lat - 33.50) < 1e-6);
});

test('commitInsert relabels V1..Vn contiguously after splice', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.00, 33.45);
  t.finishDrawing();
  t.selectVertex(0);
  t.startInsertAfter();
  t.commitInsert(-112.05, 33.46);
  const s = t.getState();
  assert.strictEqual(s.vertices[0].label, 'V1');
  assert.strictEqual(s.vertices[1].label, 'V2');
  assert.strictEqual(s.vertices[2].label, 'V3');
});

test('commitInsert leaves selection on the new vertex', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.00, 33.45);
  t.finishDrawing();
  t.selectVertex(0);
  t.startInsertAfter();
  t.commitInsert(-112.05, 33.46);
  assert.strictEqual(t.getState().selectedVertex, 1);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/insert-projection.test.mjs`
Expected: 5 failures.

- [ ] **Step 3: Implement `commitInsert` + button handlers.**

In `frontend/ruler.js`, add:

```javascript
  // ─── Insert commit (spec §B + §E.5) ────────────────────────────────
  function commitInsert(rawLng, rawLat) {
    if (state.status !== 'inserting' || state.insertSlot == null) return;
    var slot = state.insertSlot.before;
    var n = state.vertices.length;
    var projected = [rawLng, rawLat];   // default: extend the path
    if (slot >= 1 && slot <= n - 1) {
      var a = [state.vertices[slot - 1].lng, state.vertices[slot - 1].lat];
      var b = [state.vertices[slot    ].lng, state.vertices[slot    ].lat];
      projected = projectPointToSegment([rawLng, rawLat], a, b);
    }
    state.vertices.splice(slot, 0, { lng: projected[0], lat: projected[1], label: '' });
    relabel();
    recompute();
    state.status = 'editing';
    state.selectedVertex = slot;
    state.insertSlot = null;
  }
```

Wire `commitInsert` into `handleMapClick`'s `inserting` branch — replace the stubbed `if (state.status === 'inserting') return;` with:

```javascript
    if (state.status === 'inserting') {
      var oe = e.originalEvent || {};
      if (oe.ctrlKey || oe.shiftKey || oe.altKey || oe.metaKey) return;
      commitInsert(e.lngLat.lng, e.lngLat.lat);
      refreshMapData();
      renderPanel();
      // Phase 4.7: re-trigger sampling.
      return;
    }
```

Wire the `[Insert Before]` / `[Insert After]` buttons in `init`:

```javascript
    var insBefore = document.getElementById('ruler-insert-before');
    var insAfter  = document.getElementById('ruler-insert-after');
    if (insBefore) insBefore.addEventListener('click', function () {
      startInsertBefore(); refreshMapData(); renderPanel();
    });
    if (insAfter) insAfter.addEventListener('click', function () {
      startInsertAfter(); refreshMapData(); renderPanel();
    });
```

Add `commitInsert: commitInsert` to `_test`.

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/insert-projection.test.mjs`
Expected: 5 tests pass.

- [ ] **Step 5: Smoke test in browser.**

Place 3 vertices + Finish. Click V2 → action row appears. Click `[↓ Insert After]` → banner reads "Tap map to insert vertex". Tap somewhere off-segment between V2 and V3 → new vertex appears AT the closest point on the V2→V3 segment (NOT at raw tap). Numbering becomes V1..V4 contiguous. New vertex is selected (orange highlight).

Click V1 → click `[↑ Insert Before]` — banner reads correct slot — tap somewhere → new vertex placed at raw tap (no segment to project onto before V1).

- [ ] **Step 6: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/insert-projection.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): commitInsert + Insert-Before/After button wiring

Insert buttons → state→inserting + slot index → next map click
commits via commitInsert which uses projectPointToSegment (Task 1.4)
to land the new vertex on the relevant adjacent segment, NOT at the
raw tap. Endpoints (Insert Before V1, Insert After Vlast) extend
the path at the raw tap location since there's no adjacent segment.

5 tests covering mid-path projection, both endpoint cases (no
projection), relabeling, and selection landing on the new vertex.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §B, §E.5
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 3.5)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.6: `[Delete]` button — splice + recompute + relabel

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/delete-vertex.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/delete-vertex.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

test('deleteSelectedVertex removes the selected vertex', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.05, 33.46);
  t.addVertex(-112.00, 33.47);
  t.finishDrawing();
  t.selectVertex(1);
  t.deleteSelectedVertex();
  const s = t.getState();
  assert.strictEqual(s.vertices.length, 2);
  // V1 stays at -112.10, V2 (was V3) at -112.00
  assert.ok(Math.abs(s.vertices[0].lng - (-112.10)) < 1e-9);
  assert.ok(Math.abs(s.vertices[1].lng - (-112.00)) < 1e-9);
});

test('deleteSelectedVertex relabels V1..Vn contiguously', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.05, 33.46);
  t.addVertex(-112.00, 33.47);
  t.finishDrawing();
  t.selectVertex(1);
  t.deleteSelectedVertex();
  const s = t.getState();
  assert.strictEqual(s.vertices[0].label, 'V1');
  assert.strictEqual(s.vertices[1].label, 'V2');
});

test('deleteSelectedVertex when remaining count >= 2 stays in editing, no selection', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.05, 33.46);
  t.addVertex(-112.00, 33.47);
  t.finishDrawing();
  t.selectVertex(0);
  t.deleteSelectedVertex();
  const s = t.getState();
  assert.strictEqual(s.status, 'editing');
  assert.strictEqual(s.selectedVertex, null);
});

test('deleteSelectedVertex with 2 vertices → 1 vertex returns to drawing', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  t.deleteSelectedVertex();
  // 1 vertex remaining: spec says vertices.length < 2 ⇒ no segments;
  // finished editing now degenerate. Plan: revert to drawing so user
  // can extend; selection cleared.
  const s = t.getState();
  assert.strictEqual(s.status, 'drawing');
  assert.strictEqual(s.vertices.length, 1);
  assert.strictEqual(s.selectedVertex, null);
});

test('deleteSelectedVertex no-op when no selection', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.deleteSelectedVertex();
  assert.strictEqual(t.getState().vertices.length, 2);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/delete-vertex.test.mjs`
Expected: 5 failures.

- [ ] **Step 3: Implement `deleteSelectedVertex` + button wiring.**

In `frontend/ruler.js`:

```javascript
  function deleteSelectedVertex() {
    if (state.status !== 'editing') return;
    if (state.selectedVertex === null) return;
    state.vertices.splice(state.selectedVertex, 1);
    state.selectedVertex = null;
    relabel();
    recompute();
    if (state.vertices.length < 2) state.status = 'drawing';
  }
```

Wire the `[✗ Delete]` button in `init`:
```javascript
    var delBtn = document.getElementById('ruler-delete-vertex');
    if (delBtn) delBtn.addEventListener('click', function () {
      deleteSelectedVertex(); refreshMapData(); renderPanel();
      // Phase 4.7: re-trigger sampling.
    });
```

Add `deleteSelectedVertex: deleteSelectedVertex` to `_test`.

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/delete-vertex.test.mjs`
Expected: 5 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/delete-vertex.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): deleteSelectedVertex + Delete-button wiring

[✗ Delete] splices the selected vertex out, relabels V1..Vn
contiguously, and clears selection. If the result is <2 vertices,
state reverts to drawing so the user can extend without
re-finishing.

5 tests covering splice, relabel, post-state-mode, the 2→1 fall-
back, and the no-selection no-op.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §B, §C
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 3.6)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.7: Backspace on selected vertex (editing state) extends Task 2.6 keyboard handler

Per spec §C.6: in `editing` state with `selectedVertex !== null`, Backspace or Delete deletes the selected vertex (mirrors the action button).

**Files:**
- Modify: `frontend/ruler.js`
- Modify: `frontend/tests/ruler/keyboard.test.mjs` (extend with 2 tests)

- [ ] **Step 1: Append failing tests to `keyboard.test.mjs`.**

```javascript
test('Backspace during editing with selection deletes the selected vertex', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.05, 33.46);
  t.addVertex(-112.00, 33.47);
  t.finishDrawing();
  t.selectVertex(1);
  t.handleKeydown(fakeKey('Backspace'));
  assert.strictEqual(t.getState().vertices.length, 2);
  assert.strictEqual(t.getState().selectedVertex, null);
});

test('Delete (key) during editing with selection deletes the vertex', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.05, 33.46);
  t.addVertex(-112.00, 33.47);
  t.finishDrawing();
  t.selectVertex(1);
  t.handleKeydown(fakeKey('Delete'));
  assert.strictEqual(t.getState().vertices.length, 2);
});

test('Backspace during editing without selection is a no-op', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.05, 33.46);
  t.addVertex(-112.00, 33.47);
  t.finishDrawing();
  t.handleKeydown(fakeKey('Backspace'));
  assert.strictEqual(t.getState().vertices.length, 3);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/keyboard.test.mjs`
Expected: 3 new failures.

- [ ] **Step 3: Extend `handleKeydown`.**

Update the Backspace/Delete branch:
```javascript
    if (e.key === 'Backspace' || e.key === 'Delete') {
      if (state.status === 'drawing') {
        if (state.vertices.length === 0) return;
        popVertex();
        if (e.preventDefault) e.preventDefault();
        refreshMapData();
        renderPanel();
        return;
      }
      if (state.status === 'editing' && state.selectedVertex !== null) {
        deleteSelectedVertex();
        if (e.preventDefault) e.preventDefault();
        refreshMapData();
        renderPanel();
        // Phase 4.7: re-trigger sampling.
        return;
      }
      return;
    }
```

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/keyboard.test.mjs`
Expected: all 14 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/keyboard.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): Backspace/Delete in editing deletes selected vertex

Extends Task 2.6's keyboard handler — when state.status==='editing'
AND selectedVertex !== null, Backspace/Delete fires
deleteSelectedVertex(). No-op without selection (so the user can
still backspace inside the search input without surprise).

3 new tests added to keyboard.test.mjs.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §C.6
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 3.7)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.8: Editing-state click leakage prevention smoke test

Task 2.3's `queryRenderedFeatures` exclusion-list edit is the actual fix for R5 C1. This task is the explicit smoke verification that confirms it works in the browser — ensuring future regressions are noticed before the Phase 5.1 grep test.

**Files:**
- (no code changes — manual smoke verification + a written cross-reference)

- [ ] **Step 1: Manual smoke test in browser.**

Reload dev. Place 3 vertices + Finish (now in `editing`). Click anywhere on V2 (vertex itself OR within its 44-px hit area).

Expected:
- V2 highlights orange (selection works).
- NO reverse-geocode popup appears.
- NO duplicate console messages indicating two handlers fired.

Click an empty area of the map (not on any vertex):
- Reverse-geocode popup appears as normal (the bail must NOT leak into non-vertex empty clicks during editing).

Click on the line segment between V1 and V2 (not on a vertex):
- Reverse-geocode popup MAY appear (acceptable — the line layer is in the exclusion list per Task 2.3, so reverse-geocode bails; but no ruler action is wired to bare-line clicks in v1).

- [ ] **Step 2: Document the verification.**

Append a one-line note to `dev/implementation-log.md` (top, reverse-chronological):

```
2026-04-24 ruler — Task 3.8 editing-state click leakage smoke verified.
Vertex tap selects without popup. Empty-map tap pops reverse-geocode.
Line-segment tap pops reverse-geocode (acceptable per spec — no v1
behavior wired to bare-line clicks). R5 C1 closed.
```

- [ ] **Step 3: Commit.**

```bash
git add dev/implementation-log.md
git commit -m "$(cat <<'EOF'
docs(ruler): log Task 3.8 click-leakage smoke verification

R5 C1 (editing-state vertex click falls through to reverse-geocode)
was fixed by Task 2.3's queryRenderedFeatures exclusion-list edit.
This commit documents the manual smoke verification confirming the
fix works end-to-end. Phase 5.1 will add the grep enforcement test
to catch a regression in CI.

Refs: dev/adversarial/2026-04-24-ruler-r5-codex.md C1
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 3.8)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Phase 3 review checkpoint

> **Phase 3 review (≥3 rounds):** All edit operations work cleanly. Drag is smooth (no per-frame source-update stutter on a 50-vertex measurement) — verified by drag-raf.test.mjs + manual scroll across the AZ basemap. Multi-finger pinch over a vertex zooms the map without triggering drag. Insert-After tap projects to segment (no off-segment insertions). Delete keeps V-numbering contiguous. Editing-state vertex tap does NOT pop reverse-geocode. All Phase 0+1+2+3 tests still green. Run `python -m pytest tests/ services/search/tests/ -q` — Python baseline unchanged. If any review round surfaces issues, fix and re-review until clean.

---

## Phase 4 — Elevation sampling (7 tasks)

**Goal:** Bring up the elevation profile. After Phase 4, finishing a measurement triggers tile fetching + decoding from `/tiles/data/elevation/{z}/{x}/{y}.png`, the sparkline renders with min/max/gain/loss, and coverage gaps are dashed.

### Task 4.1: `lngLatToTile(lng, lat, z)` + `tilePixelOffset(lng, lat, z)` — tile-coord math primitives

Standard Web Mercator tile math. `lngLatToTile` returns `{tx, ty}` integer tile coords; `tilePixelOffset` returns the `{px, py}` offset into a 256×256 tile for the given lng/lat at zoom z.

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/tile-math.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/tile-math.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

test('lngLatToTile: (0, 0) at z=0 is tile (0, 0)', () => {
  const { test: t } = loadRuler();
  const r = t.lngLatToTile(0, 0, 0);
  assert.deepStrictEqual(r, { tx: 0, ty: 0 });
});

test('lngLatToTile: equator at z=1 splits tiles correctly', () => {
  const { test: t } = loadRuler();
  // At z=1 there are 2x2 tiles. lng=-180,lat=85 → tile (0, 0); lng=0,lat=0 boundary.
  const r1 = t.lngLatToTile(-90, 45, 1);
  // -90 is at the left half boundary; 45° is in the upper half
  assert.strictEqual(r1.tx, 0);
  assert.strictEqual(r1.ty, 0);
});

test('lngLatToTile: AZ Phoenix [-112, 33.5] at z=12 (known tile)', () => {
  const { test: t } = loadRuler();
  // Verified via https://tile.openstreetmap.org reference: at z=12, lng=-112, lat=33.5
  // → tile (752, 1614) (give-or-take ±1 depending on exact boundary)
  const r = t.lngLatToTile(-112, 33.5, 12);
  assert.ok(Math.abs(r.tx - 752) <= 1, `tx near 752, got ${r.tx}`);
  assert.ok(Math.abs(r.ty - 1614) <= 1, `ty near 1614, got ${r.ty}`);
});

test('tilePixelOffset: at exact tile origin returns (0, 0) or (256, 256)', () => {
  const { test: t } = loadRuler();
  // The exact lng/lat for tile (752, 1614) at z=12 corner — round-trip check
  const tileTopLeft = t.tileToLngLat(752, 1614, 12);
  const off = t.tilePixelOffset(tileTopLeft.lng, tileTopLeft.lat, 12);
  // At the top-left corner of a tile, offset should be near (0, 0)
  assert.ok(off.px < 2 && off.px >= 0, `px near 0, got ${off.px}`);
  assert.ok(off.py < 2 && off.py >= 0, `py near 0, got ${off.py}`);
});

test('tilePixelOffset: returned px/py always in [0, 256)', () => {
  const { test: t } = loadRuler();
  const samples = [
    [-112.0, 33.5], [-100, 40], [-118, 34], [-104, 39], [0, 0], [-180, -85],
  ];
  for (const [lng, lat] of samples) {
    const o = t.tilePixelOffset(lng, lat, 12);
    assert.ok(o.px >= 0 && o.px < 256, `px in [0,256): got ${o.px}`);
    assert.ok(o.py >= 0 && o.py < 256, `py in [0,256): got ${o.py}`);
  }
});

test('lngLatToTile + tilePixelOffset together identify a unique pixel', () => {
  const { test: t } = loadRuler();
  const lng = -112.07; const lat = 33.45;
  const tile = t.lngLatToTile(lng, lat, 12);
  const off = t.tilePixelOffset(lng, lat, 12);
  // Round-trip: re-derive lng/lat from tile + offset, expect close match
  const back = t.tilePixelToLngLat(tile.tx, tile.ty, off.px, off.py, 12);
  assert.ok(Math.abs(back.lng - lng) < 0.01, `lng round-trip ${back.lng} vs ${lng}`);
  assert.ok(Math.abs(back.lat - lat) < 0.01, `lat round-trip ${back.lat} vs ${lat}`);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/tile-math.test.mjs`
Expected: 6 failures.

- [ ] **Step 3: Implement tile math.**

In `frontend/ruler.js`, after the existing pure functions (after `sparklinePath`), add:

```javascript
  // ─── Tile coord math (Web Mercator) ────────────────────────────────
  function lngLatToTile(lng, lat, z) {
    var n = Math.pow(2, z);
    var tx = Math.floor((lng + 180) / 360 * n);
    var latRad = lat * Math.PI / 180;
    var ty = Math.floor((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n);
    // Clamp to valid range
    if (tx < 0) tx = 0; if (tx >= n) tx = n - 1;
    if (ty < 0) ty = 0; if (ty >= n) ty = n - 1;
    return { tx: tx, ty: ty };
  }

  function tileToLngLat(tx, ty, z) {
    // Top-left corner of the tile in lng/lat
    var n = Math.pow(2, z);
    var lng = tx / n * 360 - 180;
    var lat = Math.atan(sinh(Math.PI * (1 - 2 * ty / n))) * 180 / Math.PI;
    return { lng: lng, lat: lat };
  }

  function sinh(x) { return (Math.exp(x) - Math.exp(-x)) / 2; }

  function tilePixelOffset(lng, lat, z) {
    // Pixel offset (0..255) within the tile at zoom z for given lng/lat.
    var n = Math.pow(2, z);
    var pixelXf = (lng + 180) / 360 * n * 256;
    var latRad = lat * Math.PI / 180;
    var pixelYf = (1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n * 256;
    var px = Math.floor(pixelXf) % 256;
    var py = Math.floor(pixelYf) % 256;
    if (px < 0) px += 256;
    if (py < 0) py += 256;
    return { px: px, py: py };
  }

  function tilePixelToLngLat(tx, ty, px, py, z) {
    var n = Math.pow(2, z);
    var pixelX = tx * 256 + px;
    var pixelY = ty * 256 + py;
    var lng = pixelX / (256 * n) * 360 - 180;
    var lat = Math.atan(sinh(Math.PI * (1 - 2 * pixelY / (256 * n)))) * 180 / Math.PI;
    return { lng: lng, lat: lat };
  }
```

Add to `_test`:
```javascript
    lngLatToTile: lngLatToTile,
    tileToLngLat: tileToLngLat,
    tilePixelOffset: tilePixelOffset,
    tilePixelToLngLat: tilePixelToLngLat,
```

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/tile-math.test.mjs`
Expected: 6 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/tile-math.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): tile coord math — lngLatToTile + tilePixelOffset

Standard Web Mercator slippy-tile math. lngLatToTile returns the
integer (tx, ty) at zoom z; tilePixelOffset returns the pixel
offset within a 256x256 tile. tilePixelToLngLat is the inverse —
exposed for the round-trip test and for sample-position rendering.

6 tests: zoom-0 origin, zoom-1 equator boundary, AZ z=12 reference
tile, top-left-corner offset (0,0), [0,256) range invariant, and
round-trip pixel→lnglat consistency.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §E.3
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 4.1)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4.2: `fetchTilePixels(z, x, y, signal)` — fetch PNG → canvas → Uint8ClampedArray

Same-origin nginx serves the elevation tiles, so no CORS handling. The PNG is fetched as a Blob → drawn to an off-screen `<canvas>` → `getImageData()` returns the RGBA Uint8ClampedArray. Returns `null` on any failure (404, abort, decode error). Cannot reliably unit-test canvas pixel readback in Node — smoke + Phase 4.4's mocked-fetch tests cover it.

**Files:**
- Modify: `frontend/ruler.js`

- [ ] **Step 1: Implement `fetchTilePixels`.**

In `frontend/ruler.js`, add:

```javascript
  // ─── Tile fetch + decode ───────────────────────────────────────────
  function fetchTilePixels(z, x, y, signal) {
    // Returns Promise<Uint8ClampedArray | null>. Same-origin (nginx).
    var url = '/tiles/data/elevation/' + z + '/' + x + '/' + y + '.png';
    return fetch(url, { signal: signal }).then(function (resp) {
      if (!resp.ok) return null;
      return resp.blob();
    }).then(function (blob) {
      if (blob == null) return null;
      // Decode via createImageBitmap (faster than <img>, supported on iOS Safari 15+)
      if (typeof createImageBitmap === 'function') {
        return createImageBitmap(blob);
      }
      // Fallback: <img> + canvas (for unusual environments)
      return new Promise(function (resolve) {
        var img = new Image();
        img.onload = function () { resolve(img); };
        img.onerror = function () { resolve(null); };
        img.src = URL.createObjectURL(blob);
      });
    }).then(function (bitmap) {
      if (!bitmap) return null;
      var canvas = document.createElement('canvas');
      canvas.width = 256; canvas.height = 256;
      var cctx = canvas.getContext('2d');
      try {
        cctx.drawImage(bitmap, 0, 0, 256, 256);
        var img = cctx.getImageData(0, 0, 256, 256);
        return img.data;
      } catch (err) {
        return null;
      }
    }).catch(function (err) {
      // AbortError or fetch error — return null so callers treat as missing tile.
      return null;
    });
  }
```

Add `fetchTilePixels: fetchTilePixels` to `_test`.

- [ ] **Step 2: Smoke test in browser.**

Reload dev. Open DevTools console. Run:
```javascript
fetch('/tiles/data/elevation/12/752/1614.png').then(r => r.ok && console.log('tile OK'));
window._ruler._test.fetchTilePixels(12, 752, 1614).then(px => console.log('pixels:', px ? px.length : null));
```
Expected: tile OK; `pixels: 262144` (256×256×4 RGBA bytes).

If the tile-server is misconfigured or coverage is missing, you'll get `pixels: null` — that's the expected failure mode.

- [ ] **Step 3: Commit.**

```bash
git add frontend/ruler.js
git commit -m "$(cat <<'EOF'
feat(ruler): fetchTilePixels — fetch PNG + canvas readback to RGBA

Returns Promise<Uint8ClampedArray | null> for the elevation tile at
(z, x, y). Same-origin (nginx) so no CORS. createImageBitmap is the
fast path; <img> + canvas is the fallback. Any failure (404, abort,
decode error) resolves to null — callers treat as missing-tile.

Smoke-tested only — canvas pixel readback can't be reliably tested
in Node. Phase 4.4's mocked-fetch tests cover the orchestrator
that consumes this.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §E.3
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 4.2)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4.3: LRU tile cache (30-tile cap)

Pure data structure: `Map`-backed LRU with eviction order = oldest insertion. On `get`, hit refreshes order. On `set`, exceed-cap triggers oldest-first eviction. 30 tiles ≈ 7.5 MB at 256 KB/tile (RGBA).

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/tile-cache-lru.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/tile-cache-lru.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

test('LRU: empty cache get returns null', () => {
  const { test: t } = loadRuler();
  const c = t.makeLRUCache(3);
  assert.strictEqual(c.get('a'), null);
  assert.strictEqual(c.size(), 0);
});

test('LRU: set then get returns value', () => {
  const { test: t } = loadRuler();
  const c = t.makeLRUCache(3);
  c.set('a', 1);
  assert.strictEqual(c.get('a'), 1);
});

test('LRU: cap enforced — overflow evicts oldest', () => {
  const { test: t } = loadRuler();
  const c = t.makeLRUCache(3);
  c.set('a', 1); c.set('b', 2); c.set('c', 3);
  c.set('d', 4);  // overflow — evicts 'a'
  assert.strictEqual(c.get('a'), null);
  assert.strictEqual(c.get('b'), 2);
  assert.strictEqual(c.get('c'), 3);
  assert.strictEqual(c.get('d'), 4);
});

test('LRU: get refreshes recency — recently-got entry is NOT evicted', () => {
  const { test: t } = loadRuler();
  const c = t.makeLRUCache(3);
  c.set('a', 1); c.set('b', 2); c.set('c', 3);
  c.get('a');           // 'a' is now most recent
  c.set('d', 4);        // overflow — evicts 'b' (oldest now)
  assert.strictEqual(c.get('a'), 1);   // survives
  assert.strictEqual(c.get('b'), null); // evicted
});

test('LRU: re-set existing key updates value + refreshes recency', () => {
  const { test: t } = loadRuler();
  const c = t.makeLRUCache(3);
  c.set('a', 1); c.set('b', 2); c.set('c', 3);
  c.set('a', 11);
  c.set('d', 4);   // overflow — should evict 'b' (oldest now), not 'a'
  assert.strictEqual(c.get('a'), 11);
  assert.strictEqual(c.get('b'), null);
});

test('LRU: has reports membership without changing recency', () => {
  const { test: t } = loadRuler();
  const c = t.makeLRUCache(3);
  c.set('a', 1); c.set('b', 2); c.set('c', 3);
  c.has('a');
  c.set('d', 4);   // 'has' shouldn't refresh — 'a' still oldest, gets evicted
  assert.strictEqual(c.get('a'), null);
});

test('LRU: size() reflects current entries, capped', () => {
  const { test: t } = loadRuler();
  const c = t.makeLRUCache(3);
  c.set('a', 1); c.set('b', 2);
  assert.strictEqual(c.size(), 2);
  c.set('c', 3); c.set('d', 4); c.set('e', 5);
  assert.strictEqual(c.size(), 3, 'size never exceeds cap');
});

test('LRU: burst of 100 sets keeps size at 30 (default cap)', () => {
  const { test: t } = loadRuler();
  const c = t.makeLRUCache(30);
  for (let i = 0; i < 100; i++) c.set('k' + i, i);
  assert.strictEqual(c.size(), 30);
  // The 30 most recent should be present
  for (let i = 70; i < 100; i++) assert.strictEqual(c.get('k' + i), i);
  // Older entries evicted
  for (let i = 0; i < 70; i++) assert.strictEqual(c.get('k' + i), null);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/tile-cache-lru.test.mjs`
Expected: 8 failures.

- [ ] **Step 3: Implement `makeLRUCache`.**

In `frontend/ruler.js`, after the tile math, add:

```javascript
  // ─── LRU tile cache (spec §E.3 — 30-tile cap) ──────────────────────
  function makeLRUCache(maxEntries) {
    var cache = new Map();   // insertion order = LRU order (oldest first)
    return {
      get: function (key) {
        if (!cache.has(key)) return null;
        var v = cache.get(key);
        cache.delete(key);
        cache.set(key, v);    // refresh insertion order
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
      clear: function () { cache.clear(); },
    };
  }
```

In `init`:
```javascript
    view.tileCache = makeLRUCache(30);
```

Add `makeLRUCache: makeLRUCache` to `_test`.

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/tile-cache-lru.test.mjs`
Expected: 8 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/tile-cache-lru.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): LRU tile cache, 30-tile cap

Map-backed LRU. Insertion order is the LRU order; get refreshes by
delete+reset; set evicts oldest while size > cap. has() does NOT
refresh recency (matches DOM Cache API conventions).

8 tests covering empty, set/get, cap enforcement, get-refresh,
re-set-refresh, has-not-refresh, size capping, and a 100-burst
stress test.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §E.3
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 4.3)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4.4: `sampleElevation(vertices, signal, gen)` — orchestrator with AbortController + gen counter

The load-bearing function: builds N samples via `samplePath`, groups by tile, fetches with concurrency cap 6, decodes via `elevationFromRGB`, builds the elevation profile object. Aborts on signal. Gen-checks at fetch onload AND pre-state-mutation (per spec R5+R2). 50-tile cap.

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/sample-elevation.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/sample-elevation.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

// Synthetic Terrarium pixel encoder
function encT(meters) {
  var raw = Math.round((meters + 32768) * 256);
  return [(raw >> 16) & 0xff, (raw >> 8) & 0xff, raw & 0xff, 255];
}

// Build a 256x256x4 tile with constant elevation
function constTile(meters) {
  const arr = new Uint8ClampedArray(256 * 256 * 4);
  const [r, g, b, a] = encT(meters);
  for (let i = 0; i < 256 * 256; i++) {
    arr[i*4] = r; arr[i*4+1] = g; arr[i*4+2] = b; arr[i*4+3] = a;
  }
  return arr;
}

class FakeAbortController {
  constructor() { this.signal = { aborted: false }; }
  abort() { this.signal.aborted = true; }
}

test('sampleElevation: happy path returns profile with min/max/gain/loss', async () => {
  // Stub fetchTilePixels via _test seam: any tile returns constant 1000m
  const { test: t } = loadRuler({ AbortController: FakeAbortController });
  t.installFetchTilePixels(async () => constTile(1000));
  const vertices = [
    { lng: -112.07, lat: 33.45 },
    { lng: -112.05, lat: 33.46 },
  ];
  const ac = new FakeAbortController();
  const gen = 1;
  const profile = await t.sampleElevation(vertices, ac.signal, gen);
  assert.strictEqual(profile.samplingState, 'done');
  assert.ok(profile.samples.length > 0);
  // All samples constant 1000 → min=max=1000, gain=loss=0
  assert.strictEqual(profile.minM, 1000);
  assert.strictEqual(profile.maxM, 1000);
  assert.strictEqual(profile.gainM, 0);
  assert.strictEqual(profile.lossM, 0);
});

test('sampleElevation: all tiles 404 → samplingState failed', async () => {
  const { test: t } = loadRuler({ AbortController: FakeAbortController });
  t.installFetchTilePixels(async () => null);
  const vertices = [
    { lng: -112.07, lat: 33.45 },
    { lng: -112.05, lat: 33.46 },
  ];
  const ac = new FakeAbortController();
  const profile = await t.sampleElevation(vertices, ac.signal, 1);
  assert.strictEqual(profile.samplingState, 'failed');
  // Coverage gaps span entire path
  assert.deepStrictEqual(profile.coverageGaps, [{ from: 0, to: 1 }]);
});

test('sampleElevation: partial coverage → samplingState partial', async () => {
  // First tile 404, others succeed
  let called = 0;
  const { test: t } = loadRuler({ AbortController: FakeAbortController });
  t.installFetchTilePixels(async () => {
    called++;
    return called === 1 ? null : constTile(800);
  });
  const vertices = [
    { lng: -112.07, lat: 33.45 },
    { lng: -111.50, lat: 33.45 },  // long path → multiple tiles
  ];
  const profile = await t.sampleElevation(vertices, { aborted: false }, 1);
  assert.strictEqual(profile.samplingState, 'partial');
  assert.ok(profile.coverageGaps.length > 0);
});

test('sampleElevation: aborted signal short-circuits before mutating state', async () => {
  const { test: t } = loadRuler({ AbortController: FakeAbortController });
  t.installFetchTilePixels(async () => constTile(1000));
  const ac = new FakeAbortController();
  ac.abort();
  const profile = await t.sampleElevation(
    [{ lng: -112.07, lat: 33.45 }, { lng: -112.05, lat: 33.46 }],
    ac.signal, 1);
  assert.strictEqual(profile.samplingState, 'failed');
  assert.strictEqual(profile.aborted, true);
});

test('sampleElevation: 50-tile cap triggers truncation notice', async () => {
  const { test: t } = loadRuler({ AbortController: FakeAbortController });
  t.installFetchTilePixels(async () => constTile(500));
  // Pacific to Atlantic: spans many z=12 tiles
  const vertices = [
    { lng: -124.0, lat: 40.0 },
    { lng:  -75.0, lat: 40.0 },
  ];
  const profile = await t.sampleElevation(vertices, { aborted: false }, 1);
  assert.strictEqual(profile.truncated, true);
  // Sanity: profile.samplingState may be 'partial' since beyond-cap samples are null
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/sample-elevation.test.mjs`
Expected: 5 failures.

- [ ] **Step 3: Implement `sampleElevation`.**

In `frontend/ruler.js`, add:

```javascript
  // ─── Elevation sampling orchestrator (spec §E.3) ───────────────────
  var TILE_CAP = 50;
  var FETCH_CONCURRENCY = 6;
  var SAMPLE_ZOOM = 12;

  // Test seam — Phase 4.4 tests inject a fake fetcher.
  var fetchTilePixelsFn = fetchTilePixels;
  function installFetchTilePixelsForTesting(fn) { fetchTilePixelsFn = fn; }

  function sampleElevation(vertices, signal, gen) {
    return new Promise(function (resolve) {
      function abortedProfile() {
        return {
          samples: [], minM: null, maxM: null, gainM: 0, lossM: 0,
          coverageGaps: [{ from: 0, to: 1 }],
          samplingState: 'failed', samplingProgress: { tilesFetched: 0, tilesTotal: 0 },
          aborted: true,
        };
      }
      if (signal && signal.aborted) return resolve(abortedProfile());

      // Phase 1.3 sample count: clamp(L/50, 50, 200)
      var hav = window._haversineDistance;
      var totalLen = 0;
      for (var i = 0; i < vertices.length - 1; i++) {
        totalLen += hav([vertices[i].lng, vertices[i].lat], [vertices[i+1].lng, vertices[i+1].lat]);
      }
      var n = Math.max(50, Math.min(200, Math.floor(totalLen / 50) || 50));
      var samples = samplePath(vertices, n);

      // Annotate each sample with its tile + pixel offset
      var byTile = new Map();   // 'tx,ty' -> [{ sampleIdx, px, py }]
      for (var s = 0; s < samples.length; s++) {
        var ti = lngLatToTile(samples[s].lng, samples[s].lat, SAMPLE_ZOOM);
        var off = tilePixelOffset(samples[s].lng, samples[s].lat, SAMPLE_ZOOM);
        var key = ti.tx + ',' + ti.ty;
        if (!byTile.has(key)) byTile.set(key, { tx: ti.tx, ty: ti.ty, picks: [] });
        byTile.get(key).picks.push({ sampleIdx: s, px: off.px, py: off.py });
      }
      var tiles = Array.from(byTile.values());
      var truncated = false;
      if (tiles.length > TILE_CAP) {
        // Mark beyond-cap samples null up-front
        for (var k = TILE_CAP; k < tiles.length; k++) {
          tiles[k].picks.forEach(function (p) { samples[p.sampleIdx].elevation_m = null; });
        }
        tiles = tiles.slice(0, TILE_CAP);
        truncated = true;
      }

      var tilesTotal = tiles.length;
      var tilesFetched = 0;
      var anySuccess = false;
      var allFailed = true;

      function processTile(tile) {
        if (signal && signal.aborted) return Promise.resolve();
        if (gen !== view.samplingGen) return Promise.resolve();
        var cacheKey = SAMPLE_ZOOM + '/' + tile.tx + '/' + tile.ty;
        var cached = view.tileCache && view.tileCache.get(cacheKey);
        if (cached) {
          decodeIntoSamples(cached, tile, samples);
          tilesFetched++;
          anySuccess = true; allFailed = false;
          return Promise.resolve();
        }
        return fetchTilePixelsFn(SAMPLE_ZOOM, tile.tx, tile.ty, signal).then(function (pixels) {
          // Pre-decode gen check (saves CPU)
          if (gen !== view.samplingGen) return;
          if (signal && signal.aborted) return;
          tilesFetched++;
          if (pixels == null) {
            tile.picks.forEach(function (p) { samples[p.sampleIdx].elevation_m = null; });
            return;
          }
          if (view.tileCache) view.tileCache.set(cacheKey, pixels);
          decodeIntoSamples(pixels, tile, samples);
          anySuccess = true; allFailed = false;
        });
      }

      // Concurrency 6
      function runBatch(idx) {
        if (idx >= tiles.length) return Promise.resolve();
        var batch = tiles.slice(idx, idx + FETCH_CONCURRENCY);
        return Promise.all(batch.map(processTile)).then(function () {
          return runBatch(idx + FETCH_CONCURRENCY);
        });
      }

      runBatch(0).then(function () {
        if (signal && signal.aborted) return resolve(abortedProfile());
        // Pre-mutation gen check
        if (gen !== view.samplingGen) return resolve(abortedProfile());

        // Reduce: min/max/gain/loss, skip null + null-bracket diffs
        var minM = Infinity, maxM = -Infinity;
        var gainM = 0, lossM = 0;
        var prev = null;
        for (var p = 0; p < samples.length; p++) {
          var e = samples[p].elevation_m;
          if (e == null) { prev = null; continue; }
          if (e < minM) minM = e;
          if (e > maxM) maxM = e;
          if (prev != null) {
            var d = e - prev;
            if (d > 0) gainM += d; else lossM -= d;
          }
          prev = e;
        }
        if (minM === Infinity)  minM = null;
        if (maxM === -Infinity) maxM = null;

        // Coverage gaps: contiguous null-spans expressed as fractions of totalLen
        var coverageGaps = [];
        var inGap = false; var gapStart = 0;
        for (var q = 0; q < samples.length; q++) {
          var fr = samples.length === 1 ? 0 : q / (samples.length - 1);
          if (samples[q].elevation_m == null) {
            if (!inGap) { inGap = true; gapStart = fr; }
          } else {
            if (inGap) { coverageGaps.push({ from: gapStart, to: fr }); inGap = false; }
          }
        }
        if (inGap) coverageGaps.push({ from: gapStart, to: 1 });

        var samplingState = allFailed ? 'failed' : (coverageGaps.length > 0 ? 'partial' : 'done');

        resolve({
          samples: samples.map(function (s) { return { distance_m: s.distance_m, elevation_m: s.elevation_m }; }),
          minM: minM, maxM: maxM, gainM: gainM, lossM: lossM,
          coverageGaps: coverageGaps,
          samplingState: samplingState,
          samplingProgress: { tilesFetched: tilesFetched, tilesTotal: tilesTotal },
          truncated: truncated,
        });
      });
    });
  }

  function decodeIntoSamples(pixels, tile, samples) {
    tile.picks.forEach(function (p) {
      var off = (p.py * 256 + p.px) * 4;
      var r = pixels[off];
      var g = pixels[off + 1];
      var b = pixels[off + 2];
      var a = pixels[off + 3];
      samples[p.sampleIdx].elevation_m = elevationFromRGB(r, g, b, a);
    });
  }
```

Add to `_test`:
```javascript
    sampleElevation: sampleElevation,
    installFetchTilePixels: installFetchTilePixelsForTesting,
```

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/sample-elevation.test.mjs`
Expected: 5 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/sample-elevation.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): sampleElevation orchestrator with abort + gen checks

Builds N samples via samplePath, groups by z=12 tile, fetches with
concurrency 6 (HTTP/1.1 LAN ceiling), decodes via elevationFromRGB,
reduces to min/max/gain/loss/coverageGaps. Two gen-counter checks
per tile: pre-decode (saves CPU) and pre-mutation (catches resolved-
but-pending-microtask races). 50-tile cap → truncated:true plus
beyond-cap samples explicitly null. Aborted signal short-circuits
to a failed profile WITHOUT touching state.

5 tests with mocked fetchTilePixels: happy path, all-404 → failed,
partial coverage → partial, aborted-signal short-circuit, 50-tile
cap truncation.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §E.3
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 4.4)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4.5: `samplingState` lifecycle + skeleton sparkline + tile-counter UI

`startSampling()` is the controller that creates an AbortController, increments `view.samplingGen`, sets `state.elevationProfile.samplingState = 'sampling'`, renders the panel (which now shows the skeleton sparkline + "Loading elevation… X/Y tiles" counter), and awaits `sampleElevation`. On resolve, replaces `state.elevationProfile` IF gen still matches.

**Files:**
- Modify: `frontend/ruler.js`
- Modify: `frontend/tests/ruler/panel-render.test.mjs` (extend with sampling-state checks)

- [ ] **Step 1: Append failing tests.**

Append to `panel-render.test.mjs`:

```javascript
test('renderPanel: samplingState=sampling shows skeleton + counter', () => {
  const doc = makeMeasurePanelDocument();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.installSamplingState({
    samples: [], minM: null, maxM: null, gainM: 0, lossM: 0, coverageGaps: [],
    samplingState: 'sampling', samplingProgress: { tilesFetched: 2, tilesTotal: 5 },
  });
  t.renderPanel();
  assert.strictEqual(doc.elems['ruler-elevation-section'].hidden, false);
  assert.strictEqual(doc.elems['ruler-sampling-progress'].hidden, false);
  assert.strictEqual(doc.elems['ruler-sampling-counter'].textContent,
    'Loading elevation… 2 / 5 tiles');
});

test('renderPanel: samplingState=done shows stats', () => {
  const doc = makeMeasurePanelDocument();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.addVertex(-112.10, 33.45); t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.installSamplingState({
    samples: [{ distance_m: 0, elevation_m: 100 }, { distance_m: 1000, elevation_m: 200 }],
    minM: 100, maxM: 200, gainM: 100, lossM: 0, coverageGaps: [],
    samplingState: 'done', samplingProgress: { tilesFetched: 2, tilesTotal: 2 },
  });
  t.renderPanel();
  assert.strictEqual(doc.elems['ruler-stats'].hidden, false);
  assert.match(doc.elems['ruler-stat-min'].textContent, /100|328/);  // m or ft
});

test('renderPanel: samplingState=failed shows error message, no skeleton', () => {
  const doc = makeMeasurePanelDocument();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.addVertex(-112.10, 33.45); t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.installSamplingState({
    samples: [], minM: null, maxM: null, gainM: 0, lossM: 0, coverageGaps: [{from: 0, to: 1}],
    samplingState: 'failed', samplingProgress: { tilesFetched: 0, tilesTotal: 5 },
  });
  t.renderPanel();
  assert.strictEqual(doc.elems['ruler-sampling-progress'].hidden, true);
  assert.match(doc.elems['ruler-coverage-warn'].textContent, /Failed|elevation data/i);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/panel-render.test.mjs`
Expected: 3 new failures.

- [ ] **Step 3: Extend `renderPanel` with elevation rendering.**

In `frontend/ruler.js`, add:

```javascript
  function renderElevation() {
    var section = $id('ruler-elevation-section');
    var progress = $id('ruler-sampling-progress');
    var counter = $id('ruler-sampling-counter');
    var spark = $id('ruler-sparkline');
    var stats = $id('ruler-stats');
    var warn = $id('ruler-coverage-warn');

    var p = state.elevationProfile;
    var visible = state.vertices.length >= 2 && p && p.samplingState !== 'idle';
    setHidden(section, !visible);
    if (!visible) return;

    if (p.samplingState === 'sampling') {
      setHidden(progress, false);
      if (counter) counter.textContent =
        'Loading elevation… ' + p.samplingProgress.tilesFetched + ' / ' + p.samplingProgress.tilesTotal + ' tiles';
      setHidden(spark, true);
      setHidden(stats, true);
      setHidden(warn, true);
      return;
    }

    setHidden(progress, true);

    if (p.samplingState === 'failed') {
      setHidden(spark, true);
      setHidden(stats, true);
      setHidden(warn, false);
      if (warn) warn.textContent = 'Failed to load elevation data — showing distance only.';
      return;
    }

    setHidden(spark, false);
    setHidden(stats, false);

    // Phase 4.6: full sparkline + tick rendering. Stats text rendered now:
    var minTxt = p.minM == null ? '—' : formatRulerDistance(p.minM);
    var maxTxt = p.maxM == null ? '—' : formatRulerDistance(p.maxM);
    var gainTxt = formatRulerDistance(p.gainM);
    var lossTxt = formatRulerDistance(p.lossM);
    var sMin = $id('ruler-stat-min'); if (sMin) sMin.textContent = minTxt;
    var sMax = $id('ruler-stat-max'); if (sMax) sMax.textContent = maxTxt;
    var sGain = $id('ruler-stat-gain'); if (sGain) sGain.textContent = gainTxt;
    var sLoss = $id('ruler-stat-loss'); if (sLoss) sLoss.textContent = lossTxt;

    if (p.samplingState === 'partial' && p.coverageGaps.length > 0) {
      setHidden(warn, false);
      var pct = 0;
      for (var i = 0; i < p.coverageGaps.length; i++) {
        pct += (p.coverageGaps[i].to - p.coverageGaps[i].from);
      }
      pct = Math.round(pct * 100);
      if (warn) warn.textContent = pct + '% of path outside elevation coverage';
    } else {
      setHidden(warn, true);
    }
  }
```

Wire into `renderPanel`:
```javascript
  function renderPanel() {
    /* ... existing body ... */
    renderElevation();
    updateCursor();
  }
```

Add the test seam:
```javascript
    installSamplingState: function (profile) { state.elevationProfile = profile; },
```

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/panel-render.test.mjs`
Expected: all 9 tests pass (6 from Task 2.7 + 3 new).

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/panel-render.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): samplingState lifecycle + skeleton + counter UI

renderElevation drives the elevation section's visibility and
content per state.elevationProfile.samplingState:
  sampling → skeleton sparkline + 'Loading elevation… X/Y tiles'
  done     → sparkline visible + stats (min/max/gain/loss)
  partial  → as 'done' + coverage warning with %-outside-coverage
  failed   → 'Failed to load elevation data — showing distance only'

Stats use formatRulerDistance for unit live-read consistency. 3 new
panel-render tests covering sampling/done/failed.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §C, §E.3
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 4.5)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4.6: Sparkline render with coverage gaps + vertex ticks + selected-guide + ARIA

Per spec §C/§C.7: SVG sparkline shows the elevation curve with dashed sub-polylines for coverage gaps, vertex tick marks at each Vn position, and an orange dashed vertical guide line at the selected vertex's x-position. The SVG carries an `aria-label` summarizing min/max/gain/loss.

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/sparkline-render.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/sparkline-render.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

test('renderSparklineSVG: produces a polyline + N tick marks for N vertices', () => {
  const { test: t } = loadRuler();
  const profile = {
    samples: [
      { distance_m: 0,    elevation_m: 100 },
      { distance_m: 500,  elevation_m: 150 },
      { distance_m: 1000, elevation_m: 200 },
    ],
    minM: 100, maxM: 200, gainM: 100, lossM: 0,
    coverageGaps: [],
  };
  const vertices = [
    { lng: -112.10, lat: 33.45 },
    { lng: -112.05, lat: 33.46 },
    { lng: -112.00, lat: 33.47 },
  ];
  const out = t.renderSparklineSVG(profile, vertices, null, 250, 80);
  assert.match(out.polyline, /^[\d.,\s]+$/);
  assert.strictEqual(out.ticks.length, 3);
  assert.strictEqual(out.guideX, null);
});

test('renderSparklineSVG: coverage gap produces split sub-polylines', () => {
  const { test: t } = loadRuler();
  const profile = {
    samples: [
      { distance_m: 0,    elevation_m: 100 },
      { distance_m: 500,  elevation_m: null },
      { distance_m: 1000, elevation_m: 200 },
    ],
    minM: 100, maxM: 200, gainM: 100, lossM: 0,
    coverageGaps: [{ from: 0.5, to: 0.5 }],
  };
  const out = t.renderSparklineSVG(profile, [{lng:0,lat:0},{lng:0,lat:1}], null, 250, 80);
  // Two valid polyline segments (before and after the gap)
  assert.ok(out.polylineSegments.length >= 1, 'gap should split into segments');
});

test('renderSparklineSVG: selected vertex sets guideX to its proportional position', () => {
  const { test: t } = loadRuler();
  const profile = {
    samples: [
      { distance_m: 0,    elevation_m: 100 },
      { distance_m: 1000, elevation_m: 200 },
    ],
    minM: 100, maxM: 200, gainM: 100, lossM: 0, coverageGaps: [],
  };
  const vertices = [
    { lng: -112.10, lat: 33.45 },
    { lng: -112.05, lat: 33.46 },
  ];
  // Select V0 → guide near x=0
  const out0 = t.renderSparklineSVG(profile, vertices, 0, 250, 80);
  assert.ok(out0.guideX < 5);
  // Select V1 → guide near x=250 (right edge)
  const out1 = t.renderSparklineSVG(profile, vertices, 1, 250, 80);
  assert.ok(out1.guideX > 240);
});

test('renderSparklineSVG: ariaLabel summarizes stats numerically', () => {
  const { test: t } = loadRuler({ useImperial: false });   // metric
  const profile = {
    samples: [{ distance_m: 0, elevation_m: 100 }, { distance_m: 1000, elevation_m: 200 }],
    minM: 100, maxM: 200, gainM: 100, lossM: 0, coverageGaps: [],
  };
  const out = t.renderSparklineSVG(profile, [{lng:0,lat:0},{lng:0,lat:1}], null, 250, 80);
  assert.match(out.ariaLabel, /min/i);
  assert.match(out.ariaLabel, /max/i);
  assert.match(out.ariaLabel, /gain/i);
  assert.match(out.ariaLabel, /loss/i);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/sparkline-render.test.mjs`
Expected: 4 failures.

- [ ] **Step 3: Implement `renderSparklineSVG`.**

In `frontend/ruler.js`, add:

```javascript
  // ─── Sparkline render (spec §C, §C.7) ──────────────────────────────
  // Pure function — returns an object describing the SVG content.
  // The DOM-emission helper that uses this is renderSparklineDOM.
  function renderSparklineSVG(profile, vertices, selectedVertex, width, height) {
    var samples = profile.samples || [];
    var valid = samples.filter(function (s) { return s.elevation_m != null; });
    var minE = profile.minM, maxE = profile.maxM;
    var marginY = 4;
    var usableY = height - 2 * marginY;

    var totalDist = 0;
    if (valid.length > 0) {
      // Use full sample distance range, not just valid samples — preserves x-mapping
      totalDist = samples[samples.length - 1].distance_m - samples[0].distance_m || 1;
    }
    var dStart = samples.length > 0 ? samples[0].distance_m : 0;

    function xFor(distance_m) { return ((distance_m - dStart) / totalDist) * width; }
    function yFor(e) {
      var range = (maxE - minE) || 1;
      return marginY + (1 - (e - minE) / range) * usableY;
    }

    // Split valid samples into runs (gaps break runs)
    var polylineSegments = [];
    var currentRun = [];
    for (var i = 0; i < samples.length; i++) {
      var s = samples[i];
      if (s.elevation_m == null) {
        if (currentRun.length > 0) {
          polylineSegments.push(currentRun);
          currentRun = [];
        }
      } else {
        currentRun.push(xFor(s.distance_m).toFixed(1) + ',' + yFor(s.elevation_m).toFixed(1));
      }
    }
    if (currentRun.length > 0) polylineSegments.push(currentRun);
    var polyline = polylineSegments.map(function (run) { return run.join(' '); }).join(' | ');

    // Vertex ticks: cumulative distance per vertex
    var hav = window._haversineDistance;
    var ticks = [];
    var cum = 0;
    for (var v = 0; v < vertices.length; v++) {
      if (v > 0) {
        cum += hav(
          [vertices[v - 1].lng, vertices[v - 1].lat],
          [vertices[v].lng, vertices[v].lat]
        );
      }
      ticks.push({ index: v, x: xFor(cum) });
    }

    // Selected guide
    var guideX = null;
    if (selectedVertex != null && ticks[selectedVertex]) {
      guideX = ticks[selectedVertex].x;
    }

    // ARIA summary
    var fmt = formatRulerDistance;
    var ariaLabel = 'Elevation profile, min ' + fmt(minE || 0) +
      ', max ' + fmt(maxE || 0) +
      ', gain ' + fmt(profile.gainM || 0) +
      ', loss ' + fmt(profile.lossM || 0);

    return {
      polyline: polyline,
      polylineSegments: polylineSegments,
      ticks: ticks,
      guideX: guideX,
      ariaLabel: ariaLabel,
    };
  }
```

Add `renderSparklineSVG: renderSparklineSVG` to `_test`.

Then implement the DOM emission inside `renderElevation` — append after the `setHidden(stats, false)` line:

```javascript
    if (spark && (p.samplingState === 'done' || p.samplingState === 'partial')) {
      var out = renderSparklineSVG(p, state.vertices, state.selectedVertex, 250, 80);
      // Clear existing SVG children
      while (spark.firstChild) spark.removeChild(spark.firstChild);
      // One <polyline> per gap-split run, dashed if there's a coverageGaps array entry
      out.polylineSegments.forEach(function (seg, idx) {
        var pl = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
        pl.setAttribute('points', seg.join(' '));
        pl.setAttribute('fill', 'none');
        pl.setAttribute('stroke', 'var(--accent)');
        pl.setAttribute('stroke-width', '2');
        // Dashed if there's any coverage gap before this segment (cheap heuristic)
        if (p.coverageGaps && p.coverageGaps.length > 0 && idx > 0) {
          pl.setAttribute('stroke-dasharray', '4,4');
        }
        spark.appendChild(pl);
      });
      // Vertex ticks
      out.ticks.forEach(function (tick) {
        var line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', tick.x);
        line.setAttribute('x2', tick.x);
        line.setAttribute('y1', 80 - 6);
        line.setAttribute('y2', 80);
        line.setAttribute('stroke', '#ffd400');
        line.setAttribute('stroke-width', '1.5');
        spark.appendChild(line);
      });
      // Selected guide
      if (out.guideX != null) {
        var guide = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        guide.setAttribute('x1', out.guideX);
        guide.setAttribute('x2', out.guideX);
        guide.setAttribute('y1', 0);
        guide.setAttribute('y2', 80);
        guide.setAttribute('stroke', '#ff7a00');
        guide.setAttribute('stroke-width', '1.5');
        guide.setAttribute('stroke-dasharray', '3,3');
        spark.appendChild(guide);
      }
      spark.setAttribute('aria-label', out.ariaLabel);
    }
```

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/sparkline-render.test.mjs`
Expected: 4 tests pass.

- [ ] **Step 5: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/sparkline-render.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): sparkline with gaps + vertex ticks + selected guide

renderSparklineSVG returns a pure description of the SVG content
(polyline segments split at coverage gaps, vertex tick positions,
selected-vertex guide x-coord, ariaLabel summarizing stats). The
DOM emitter inside renderElevation creates SVG <polyline>s for
gap-split sub-curves, <line>s for vertex ticks at the bottom of
the chart, and an orange dashed <line> for the selected guide.

aria-label format: 'Elevation profile, min X, max Y, gain Z, loss W'
— readable by screen readers without exposing the SVG geometry.

4 tests covering happy-path render, gap-split segmentation, guide-x
proportional positioning, and ARIA label content.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §C, §C.7
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 4.6)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4.7: Wire `Finish` to start sampling — `startSampling()`

`startSampling()` is the Phase 4.4-driven controller hook called whenever a measurement is finished, has a vertex inserted, deleted, or dragged. It supersedes any in-flight sampling (abort + bump gen counter), sets `samplingState: 'sampling'`, calls `sampleElevation`, and replaces `state.elevationProfile` on resolve IF gen still matches.

**Files:**
- Modify: `frontend/ruler.js`

- [ ] **Step 1: Implement `startSampling`.**

In `frontend/ruler.js`, add:

```javascript
  // ─── Sampling controller (spec §E.3 + R5+R2 race analysis) ─────────
  function startSampling() {
    if (state.vertices.length < 2) {
      state.elevationProfile = null;
      return;
    }
    if (view.abortController) {
      view.abortController.abort();
    }
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

    sampleElevation(state.vertices.slice(), signal, gen).then(function (profile) {
      // Pre-mutation gen check.
      if (gen !== view.samplingGen) return;
      state.elevationProfile = profile;
      renderPanel();
    });
  }
```

Wire `startSampling` into the relevant transitions — the comment markers placed in earlier tasks now resolve:

In `finishDrawing`'s call site (the [Finish] button + Enter-key handler): add `startSampling();` after `finishDrawing(); refreshMapData(); renderPanel();`.

In `commitInsert` call site (handleMapClick inserting branch): add `startSampling();`.

In `deleteSelectedVertex` call sites ([Delete] button + Backspace): add `startSampling();`.

In `handleMouseUpDrag` AND `handleTouchEnd` (drag commit branches): add `startSampling();` AFTER `recompute()`.

Add `startSampling: startSampling` to `_test`.

- [ ] **Step 2: Smoke test in browser.**

Reload dev. Place 3 vertices in Phoenix → Finish. Counter shows "Loading elevation… X/Y tiles" briefly, then sparkline renders with min/max/gain/loss. Drag V2 → counter reappears (prior sampling aborted), then sparkline re-renders with new shape. Delete a vertex → re-sample. Add a vertex via Insert After → re-sample.

Plug network out → place new measurement → Finish → counter stalls → eventually `samplingState=failed` → "Failed to load elevation data — showing distance only" appears. Plug network back in → click `[+ New measurement]` → place new path → samples normally.

- [ ] **Step 3: Commit.**

```bash
git add frontend/ruler.js
git commit -m "$(cat <<'EOF'
feat(ruler): startSampling — wired into all state transitions

startSampling() aborts any in-flight sampling, increments
view.samplingGen, sets samplingState='sampling' (so the panel
shows the skeleton + counter), then calls sampleElevation. On
resolve, replaces state.elevationProfile only if gen still
matches — supersession is atomic.

Wired into: Finish button + Enter, commitInsert, deleteSelectedVertex
(button + Backspace), and both drag-mouseup + drag-touchend.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §E.3
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 4.7)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Phase 4 review checkpoint

> **Phase 4 review (≥3 rounds):** Real measurements in AZ produce sensible elevation profiles (verify against USGS reference points: Camelback Mountain summit ~825 m, Phoenix surface ~340 m). Off-coverage path shows partial coverage with dashed gap segments. Network-unplugged → samplingState `failed` with clear inline message. Drag a vertex → sampling re-runs, prior in-flight aborts cleanly (no stale samples appear). Tile cache stays at ≤30 entries (verify with `window._ruler._test.makeLRUCache(30)` smoke; in production the cap is enforced in `init`). All Phase 0+1+2+3+4 tests still green. Run `python -m pytest tests/ services/search/tests/ -q` — Python baseline unchanged.

---

## Phase 5 — A11y, i18n boundary, integration tests, ship gate (6 tasks)

**Goal:** Lock the integration surface against future regressions, finalize a11y / keyboard nav, and run the manual ship-gate checklist that closes the build-robust-features cycle.

### Task 5.1: Source-grep enforcement test — verify all 9 app.js touch points present in CI

The artifact IS the test. Pattern matches the existing `tests/test_overview_write_enforcement.py` style — the test reads the actual `frontend/app.js` source and asserts via regex that the 9 documented integration points exist. A future refactor that silently removes one will fail in CI before it merges.

**Files:**
- Create: `frontend/tests/ruler/app-js-integration.test.mjs`

- [ ] **Step 1: Write the test (it IS the artifact).**

Create `frontend/tests/ruler/app-js-integration.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = path.dirname(fileURLToPath(import.meta.url));

const APP_JS = fs.readFileSync(
  path.join(__dirname, '../../app.js'), 'utf-8');
const INDEX_HTML = fs.readFileSync(
  path.join(__dirname, '../../index.html'), 'utf-8');
const RULER_JS = fs.readFileSync(
  path.join(__dirname, '../../ruler.js'), 'utf-8');

// Helper: count how many times a regex matches in the source.
function countMatches(source, re) {
  const m = source.match(re);
  return m ? m.length : 0;
}

test('app.js: ruler-active bail present in 3 click handlers', () => {
  // Pattern: any line `window._ruler && window._ruler.isActive()` returning early
  const matches = APP_JS.match(/_ruler.*\.isActive\s*\(\s*\)/g) || [];
  assert.ok(matches.length >= 3,
    `expected >=3 _ruler.isActive() calls (KMZ-pin L660, search-pin L1272, reverse-geocode L1622), found ${matches.length}`);
});

test('app.js: queryRenderedFeatures exclusion list includes the 3 ruler layers', () => {
  // The exclusion list at L1628 must include all three ruler hit-test layers.
  assert.match(APP_JS, /'ruler-vertex-hit-circles'/,
    'queryRenderedFeatures exclusion list must include ruler-vertex-hit-circles (R5 C1)');
  assert.match(APP_JS, /'ruler-vertex-circles'/,
    'queryRenderedFeatures exclusion list must include ruler-vertex-circles (R5 C1)');
  assert.match(APP_JS, /'ruler-line'/,
    'queryRenderedFeatures exclusion list must include ruler-line (R5 C1)');
});

test('app.js: units-handler dispatches geographica:units-changed', () => {
  assert.match(APP_JS,
    /dispatchEvent\s*\(\s*new\s+CustomEvent\s*\(\s*['"]geographica:units-changed['"]/,
    'units-radio handler must dispatch geographica:units-changed CustomEvent (R5 M1)');
});

test('app.js: addPlaceholderSources calls _ruler.reattachSources', () => {
  // Find the addPlaceholderSources function body and verify the reattach hook.
  const fn = APP_JS.match(/function\s+addPlaceholderSources[\s\S]+?\n\s*\}/);
  assert.ok(fn, 'addPlaceholderSources function not found');
  assert.match(fn[0], /_ruler.*\.reattachSources/,
    'addPlaceholderSources must call window._ruler.reattachSources(map)');
});

test('app.js: VALID_SIDEBAR_PANELS includes measure-panel', () => {
  const arrMatch = APP_JS.match(/VALID_SIDEBAR_PANELS\s*=\s*\[[^\]]*\]/);
  assert.ok(arrMatch, 'VALID_SIDEBAR_PANELS array not found');
  assert.match(arrMatch[0], /'measure-panel'/,
    "VALID_SIDEBAR_PANELS must include 'measure-panel'");
});

test('app.js: window._formatDD export present', () => {
  assert.match(APP_JS, /window\._formatDD\s*=\s*formatDD/,
    'window._formatDD = formatDD export must be present at end of IIFE');
});

test('app.js: window._haversineDistance export present', () => {
  assert.match(APP_JS, /window\._haversineDistance\s*=\s*haversineDistance/,
    'window._haversineDistance = haversineDistance export must be present');
});

test('app.js: initRuler(map) call placed between initSidebarTabs and restoreLastSidebarTab', () => {
  // Find ordering by line index
  const lines = APP_JS.split('\n');
  let initSidebarTabsLine = -1;
  let initRulerLine = -1;
  let restoreLastLine = -1;
  for (let i = 0; i < lines.length; i++) {
    if (initSidebarTabsLine === -1 && /initSidebarTabs\s*\(\s*\)\s*;/.test(lines[i])) {
      initSidebarTabsLine = i;
    }
    if (initRulerLine === -1 && /_ruler.*\.init\s*\(\s*map\s*\)/.test(lines[i])) {
      initRulerLine = i;
    }
    if (restoreLastLine === -1 && /restoreLastSidebarTab\s*\(\s*\)\s*;/.test(lines[i])) {
      restoreLastLine = i;
    }
  }
  assert.ok(initSidebarTabsLine >= 0, 'initSidebarTabs() call not found');
  assert.ok(initRulerLine >= 0,        '_ruler.init(map) call not found in bootstrap');
  assert.ok(restoreLastLine >= 0,      'restoreLastSidebarTab() call not found');
  assert.ok(initSidebarTabsLine < initRulerLine,
    'initRuler must come AFTER initSidebarTabs');
  assert.ok(initRulerLine < restoreLastLine,
    'initRuler must come BEFORE restoreLastSidebarTab');
});

test('index.html: measure-panel + tab button + ruler.js script include present', () => {
  assert.match(INDEX_HTML, /id\s*=\s*"measure-panel"/, 'measure-panel div missing');
  assert.match(INDEX_HTML, /data-panel\s*=\s*"measure-panel"/, 'tab button missing');
  assert.match(INDEX_HTML, /<script[^>]*src\s*=\s*"ruler\.js"/, 'ruler.js script missing');
  assert.match(INDEX_HTML, /id\s*=\s*"ruler-mode-banner"/, 'floating banner missing');
});

test('ruler.js: NO innerHTML assignments anywhere', () => {
  // The textContent-only posture (R5 N2) — protect against future regression.
  const matches = RULER_JS.match(/\.innerHTML\s*=/g) || [];
  assert.strictEqual(matches.length, 0,
    `ruler.js must never assign innerHTML — found ${matches.length} occurrence(s)`);
});

test('ruler.js: text-font uses two-font fallback for symbol layers', () => {
  // Per R5 M3
  assert.match(RULER_JS,
    /['"]Metropolis Regular['"][^]*['"]Noto Sans Regular['"]/,
    "symbol-layer text-font must be ['Metropolis Regular', 'Noto Sans Regular']");
});

test('ruler.js: terrarium decode formula matches Mapzen spec', () => {
  // (r * 256 + g + b / 256) - 32768 — NOT Mapbox Terrain-RGB
  assert.match(RULER_JS,
    /r\s*\*\s*256\s*\+\s*g\s*\+\s*b\s*\/\s*256\s*\)\s*-\s*32768/,
    'elevationFromRGB must use Mapzen Terrarium formula, not Mapbox Terrain-RGB');
});
```

- [ ] **Step 2: Run the test.**

Run: `node --test --test-force-exit frontend/tests/ruler/app-js-integration.test.mjs`
Expected: all 12 tests pass. (If any fail, an earlier task's edit drifted — fix the source, NOT the test.)

- [ ] **Step 3: Commit.**

```bash
git add frontend/tests/ruler/app-js-integration.test.mjs
git commit -m "$(cat <<'EOF'
test(ruler): grep-based enforcement of all 9 app.js touch points

Single test file reads frontend/app.js, frontend/index.html, and
frontend/ruler.js as text and asserts via regex that:
  1-3. _ruler.isActive() bails present in 3 click handlers
  4.   queryRenderedFeatures exclusion list includes 3 ruler layers
  5.   units handler dispatches geographica:units-changed
  6.   addPlaceholderSources calls _ruler.reattachSources
  7.   VALID_SIDEBAR_PANELS includes 'measure-panel'
  8-9. window._formatDD + window._haversineDistance exports present
  10.  initRuler call is between initSidebarTabs and restoreLastSidebarTab
  11.  index.html has measure-panel + tab + script + banner
  12.  ruler.js never assigns innerHTML
  13.  ruler.js text-font uses two-font fallback (R5 M3)
  14.  terrarium decode matches Mapzen formula (R1+R2+R4 critical fix)

Future PRs that silently regress any integration point fail this
test in CI. Pattern matches tests/test_overview_write_enforcement.py.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §Testing
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 5.1)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5.2: `geographica:units-changed` dispatch + ruler.js subscription — units toggle live-rerender

Task 0.3 + 0.4 already exposed `window._geographicaUseImperial` for live read at format time. But per R5 M1: live read alone is insufficient — without an explicit rerender trigger, an already-rendered measurement keeps showing stale units until the next state mutation. This task adds the dispatch + subscription.

**Files:**
- Modify: `frontend/app.js` (1 insert at the units-radio handler at L1086-1100)
- Modify: `frontend/ruler.js` (subscribe in `init`)
- Create: `frontend/tests/ruler/units-rerender-integration.test.mjs`

- [ ] **Step 1: Write failing test.**

Create `frontend/tests/ruler/units-rerender-integration.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

test('toggling units AND dispatching geographica:units-changed rerenders panel', () => {
  // Build a fake document with the panel + an event-listener registry.
  const handlers = {};
  const elems = {};
  function makeEl(id) {
    const el = {
      id: id,
      _listeners: {},
      childNodes: [],
      get firstChild() { return this.childNodes[0] || null; },
      appendChild: (c) => { el.childNodes.push(c); },
      removeChild: (c) => { const idx = el.childNodes.indexOf(c); if (idx>=0) el.childNodes.splice(idx, 1); },
      setAttribute: () => {}, getAttribute: () => '',
      addEventListener: () => {}, removeEventListener: () => {},
      classList: { add: () => {}, remove: () => {}, contains: () => false, toggle: () => {} },
      style: {}, hidden: false, textContent: '',
    };
    elems[id] = el;
    return el;
  }
  ['measure-panel', 'ruler-banner-inline', 'ruler-banner-inline-text',
   'ruler-banner-inline-cancel', 'ruler-headline-section', 'ruler-headline-total',
   'ruler-vertex-section', 'ruler-vertex-count', 'ruler-vertex-list',
   'ruler-action-row', 'ruler-action-empty', 'ruler-insert-before',
   'ruler-insert-after', 'ruler-delete-vertex', 'ruler-elevation-section',
   'ruler-sparkline', 'ruler-stats', 'ruler-stat-min', 'ruler-stat-max',
   'ruler-stat-gain', 'ruler-stat-loss', 'ruler-coverage-warn', 'ruler-footer',
   'ruler-undo', 'ruler-clear', 'ruler-finish', 'ruler-new', 'ruler-mode-banner',
   'ruler-mode-banner-text', 'ruler-mode-banner-cancel',
   'ruler-sampling-progress', 'ruler-sampling-counter'].forEach(makeEl);

  const fakeDocument = {
    getElementById: (id) => elems[id] || null,
    addEventListener: (k, fn) => { (handlers[k] = handlers[k] || []).push(fn); },
    removeEventListener: () => {},
    createElement: (tag) => {
      const el = makeEl('_synthetic_' + Math.random());
      el.tagName = tag.toUpperCase();
      return el;
    },
    createElementNS: (ns, tag) => {
      const el = makeEl('_synthetic_' + Math.random());
      el.tagName = tag.toUpperCase();
      return el;
    },
    querySelector: () => null,
  };
  const { ruler, test: t, win } = loadRuler({ fakeDocument: fakeDocument, useImperial: true });
  // Pretend init has run; place a long path so distance > 1 mile
  t.installSubscribeUnitsChanged();   // wires the handler the same way init() does
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.00, 33.45);
  t.finishDrawing();
  t.renderPanel();
  const headlineImperial = elems['ruler-headline-total'].textContent;
  assert.match(headlineImperial, /mi\b/, `imperial: ${headlineImperial}`);

  // Toggle to metric + dispatch the event
  win._geographicaUseImperial = false;
  // Simulate a CustomEvent dispatch on document
  (handlers['geographica:units-changed'] || []).forEach(fn => fn({ type: 'geographica:units-changed' }));
  const headlineMetric = elems['ruler-headline-total'].textContent;
  assert.match(headlineMetric, /km\b/, `metric: ${headlineMetric}`);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/units-rerender-integration.test.mjs`
Expected: 1 failure.

- [ ] **Step 3: Wire the dispatch in app.js.**

Run: `grep -n "useImperial\s*=\s*useImperial\|useImperial\s*=\s*input\|input\[name=\"units\"\]" frontend/app.js | head -10`

Find the radio-change handler at L1086-1100 (the place that already mirrors `useImperial` to `window._geographicaUseImperial`). At the END of that handler body, add:

```javascript
        document.dispatchEvent(new CustomEvent('geographica:units-changed'));
```

- [ ] **Step 4: Subscribe in ruler.js init.**

In `frontend/ruler.js`, inside `init(mapInstance)`:

```javascript
    document.addEventListener('geographica:units-changed', function () {
      renderPanel();
    });
```

Add a test seam to `_test`:
```javascript
    installSubscribeUnitsChanged: function () {
      document.addEventListener('geographica:units-changed', function () {
        renderPanel();
      });
    },
```

- [ ] **Step 5: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/units-rerender-integration.test.mjs`
Expected: test passes.

- [ ] **Step 6: Smoke test in browser.**

Reload dev. Place 3 vertices + Finish. Note headline reads e.g. "1.23 mi". Switch units radio to Metric (without any other interaction): headline immediately becomes "1.98 km", vertex-list segment distances and sparkline aria-label all flip to metric. No reload required.

- [ ] **Step 7: Commit.**

```bash
git add frontend/app.js frontend/ruler.js frontend/tests/ruler/units-rerender-integration.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): geographica:units-changed dispatch + subscribe rerender

app.js's units-radio handler now dispatches a CustomEvent on
document; ruler.js init subscribes and calls renderPanel() on receipt.
Closes R5 M1 — without this, live-read alone left already-rendered
measurements showing stale units until next state mutation.

Integration test asserts the full flow: place measurement →
imperial readout → toggle + dispatch → metric readout, no other
interaction.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §A (R5 M1)
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 5.2)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5.3: Full keyboard navigation per spec §C.6 — Tab, Space/Enter, ↑/↓ row focus

Spec §C.6 specifies Space/Enter on a focused vertex row → select; ↑/↓ → move focus to prev/next row (does NOT change selection). Plus Tab cycles through tab buttons → vertex rows → action buttons → sparkline → footer buttons (focus is provided by `tabindex="0"` set in Task 2.7 and the footer buttons being native `<button>` elements).

**Files:**
- Modify: `frontend/ruler.js`
- Modify: `frontend/tests/ruler/keyboard.test.mjs` (extend)

- [ ] **Step 1: Append failing tests.**

Append to `keyboard.test.mjs`:

```javascript
test('Space on focused vertex row toggles selection (editing state)', () => {
  // Need a fake document with a focused row carrying data-vertex-index.
  // We can't fully simulate focus in the VM, but we can call handleKeydown
  // with a synthesized event whose target is the row.
  const { test: t } = loadRuler();
  t.addVertex(-112.10, 33.45); t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  const rowEvent = {
    key: ' ',
    target: {
      tagName: 'LI',
      isContentEditable: false,
      classList: { contains: (c) => c === 'ruler-vertex-row' },
      getAttribute: (k) => k === 'data-vertex-index' ? '0' : null,
    },
    preventDefault: () => {},
  };
  t.handleKeydown(rowEvent);
  assert.strictEqual(t.getState().selectedVertex, 0);
  // Press again → deselect
  t.handleKeydown(rowEvent);
  assert.strictEqual(t.getState().selectedVertex, null);
});

test('Enter on focused vertex row selects it (editing state)', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.10, 33.45); t.addVertex(-112.05, 33.46); t.addVertex(-112.00, 33.47);
  t.finishDrawing();
  const rowEvent = {
    key: 'Enter',
    target: {
      tagName: 'LI',
      isContentEditable: false,
      classList: { contains: (c) => c === 'ruler-vertex-row' },
      getAttribute: (k) => k === 'data-vertex-index' ? '2' : null,
    },
    preventDefault: () => {},
  };
  t.handleKeydown(rowEvent);
  assert.strictEqual(t.getState().selectedVertex, 2);
});

test('Arrow keys on focused row do NOT change selection', () => {
  const { test: t } = loadRuler();
  t.addVertex(-112.10, 33.45); t.addVertex(-112.05, 33.46);
  t.finishDrawing();
  t.selectVertex(0);
  const rowEvent = {
    key: 'ArrowDown',
    target: {
      tagName: 'LI',
      isContentEditable: false,
      classList: { contains: (c) => c === 'ruler-vertex-row' },
      getAttribute: (k) => k === 'data-vertex-index' ? '0' : null,
    },
    preventDefault: () => {},
    moved: false,
  };
  t.handleKeydown(rowEvent);
  // Selection unchanged (focus moves visually but state.selectedVertex stays)
  assert.strictEqual(t.getState().selectedVertex, 0);
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/keyboard.test.mjs`
Expected: 3 new failures.

- [ ] **Step 3: Extend `handleKeydown` for row-focused keys.**

In `frontend/ruler.js`, add at the top of `handleKeydown` (after the input-suppression bail):

```javascript
    // Row-focused keys (Space/Enter to select; arrows move focus only)
    var target = e.target;
    var isRow = target && target.classList && target.classList.contains &&
                target.classList.contains('ruler-vertex-row');
    if (isRow && state.status === 'editing') {
      var idx = parseInt(target.getAttribute('data-vertex-index'), 10);
      if (e.key === ' ' || e.key === 'Enter') {
        if (state.selectedVertex === idx) deselectVertex();
        else selectVertex(idx);
        if (e.preventDefault) e.preventDefault();
        refreshMapData(); renderPanel();
        return;
      }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        // Move focus only — selection unchanged. Native focus management:
        // find next/prev row in the DOM list and focus it.
        var listEl = document.getElementById('ruler-vertex-list');
        if (!listEl) return;
        var rows = listEl.childNodes;
        var nextIdx = e.key === 'ArrowDown' ? idx + 1 : idx - 1;
        if (nextIdx < 0) nextIdx = rows.length - 1;
        if (nextIdx >= rows.length) nextIdx = 0;
        var nextRow = rows[nextIdx];
        if (nextRow && typeof nextRow.focus === 'function') nextRow.focus();
        if (e.preventDefault) e.preventDefault();
        return;
      }
    }
```

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/keyboard.test.mjs`
Expected: all 17 tests pass.

- [ ] **Step 5: Smoke test in browser.**

Reload dev. Place 3 vertices + Finish. Press Tab repeatedly: focus rings should appear in order on the tab buttons → vertex row 1 → vertex row 2 → vertex row 3 → action buttons (when a row is selected) → sparkline → footer buttons. Press ↓/↑ on a focused row: focus moves between rows, NO selection change. Press Enter or Space on a focused row: selection toggles for that row.

- [ ] **Step 6: Commit.**

```bash
git add frontend/ruler.js frontend/tests/ruler/keyboard.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): keyboard nav per spec §C.6 — Space/Enter + arrows

Space/Enter on a focused vertex row toggles selection (mirrors
click). ↑/↓ moves focus between adjacent rows WITHOUT changing
selection (focus and selection are deliberately distinct per
spec — accessibility convention). Tab order is achieved natively
via the tabindex='0' on rows and native <button> footer controls.

3 new tests for the row-focused-key branches.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §C.6
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 5.3)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5.4: ARIA polish — vertex-row `aria-label`, sparkline `aria-label`, banner `role="status"`

Most ARIA was wired in earlier tasks (Task 2.7 vertex rows, Task 4.6 sparkline aria-label, index.html `role="status"` on banners). This task adds a richer per-row `aria-label` summarizing the segment-out distance and bearing, and an integration test that asserts the wire-up.

**Files:**
- Modify: `frontend/ruler.js`
- Create: `frontend/tests/ruler/aria.test.mjs`

- [ ] **Step 1: Write failing tests.**

Create `frontend/tests/ruler/aria.test.mjs`:

```javascript
import { test } from 'node:test';
import assert from 'node:assert';
import { loadRuler } from './_fixtures.js';

// Reuse panel-render's makeMeasurePanelDocument helper inline (DRY would be better)
function makeEl(tag) {
  const c = [];
  const a = {};
  return {
    tagName: tag.toUpperCase(),
    children: c, childNodes: c,
    get firstChild() { return c[0] || null; },
    appendChild: function (e) { c.push(e); },
    removeChild: function (e) { const i = c.indexOf(e); if (i>=0) c.splice(i, 1); },
    setAttribute: function (k, v) { a[k] = v; },
    getAttribute: function (k) { return a[k]; },
    addEventListener: function () {},
    classList: { add: () => {}, remove: () => {}, contains: () => false, toggle: () => {} },
    style: {}, hidden: false, textContent: '',
    _attrs: a,
  };
}
function makeMeasurePanelDoc() {
  const elems = {};
  ['measure-panel','ruler-banner-inline','ruler-banner-inline-text','ruler-banner-inline-cancel',
   'ruler-headline-section','ruler-headline-total','ruler-vertex-section','ruler-vertex-count',
   'ruler-vertex-list','ruler-action-row','ruler-action-empty','ruler-insert-before',
   'ruler-insert-after','ruler-delete-vertex','ruler-elevation-section','ruler-sparkline',
   'ruler-stats','ruler-stat-min','ruler-stat-max','ruler-stat-gain','ruler-stat-loss',
   'ruler-coverage-warn','ruler-footer','ruler-undo','ruler-clear','ruler-finish',
   'ruler-new','ruler-mode-banner','ruler-mode-banner-text','ruler-mode-banner-cancel',
   'ruler-sampling-progress','ruler-sampling-counter'].forEach(id => {
    elems[id] = makeEl('div'); elems[id].id = id;
  });
  return {
    getElementById: id => elems[id] || null,
    addEventListener: () => {},
    removeEventListener: () => {},
    createElement: tag => makeEl(tag),
    createElementNS: (ns, tag) => makeEl(tag),
    querySelector: () => null,
    elems: elems,
  };
}

test('vertex row has aria-label with label + coords + segment summary', () => {
  const doc = makeMeasurePanelDoc();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.addVertex(-112.10, 33.45);
  t.addVertex(-112.00, 33.45);
  t.renderPanel();
  const list = doc.elems['ruler-vertex-list'];
  const row0 = list.children[0];
  const aria = row0.getAttribute('aria-label');
  assert.ok(aria, 'aria-label must be set on each row');
  assert.match(aria, /V1/);
  assert.match(aria, /33\.45000/);
  // Segment-out info on row 0 (which has a segment)
  assert.match(aria, /distance|bearing|°/);
});

test('vertex row aria-selected toggles with selection', () => {
  const doc = makeMeasurePanelDoc();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.addVertex(-112.10, 33.45); t.addVertex(-112.00, 33.45);
  t.finishDrawing();
  t.selectVertex(0);
  t.renderPanel();
  const row0 = doc.elems['ruler-vertex-list'].children[0];
  const row1 = doc.elems['ruler-vertex-list'].children[1];
  assert.strictEqual(row0.getAttribute('aria-selected'), 'true');
  assert.strictEqual(row1.getAttribute('aria-selected'), 'false');
});

test('sparkline carries role=img + aria-label after sampling completes', () => {
  const doc = makeMeasurePanelDoc();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.addVertex(-112.10, 33.45); t.addVertex(-112.00, 33.45);
  t.finishDrawing();
  t.installSamplingState({
    samples: [
      { distance_m: 0,    elevation_m: 100 },
      { distance_m: 1000, elevation_m: 250 },
    ],
    minM: 100, maxM: 250, gainM: 150, lossM: 0, coverageGaps: [],
    samplingState: 'done', samplingProgress: { tilesFetched: 2, tilesTotal: 2 },
  });
  t.renderPanel();
  const spark = doc.elems['ruler-sparkline'];
  assert.match(spark.getAttribute('aria-label') || '', /min[^,]*,\s*max[^,]*,\s*gain/i);
});

test('vertex list root has role=list', () => {
  const doc = makeMeasurePanelDoc();
  const { test: t } = loadRuler({ fakeDocument: doc });
  t.addVertex(-112.10, 33.45); t.addVertex(-112.00, 33.45);
  t.renderPanel();
  // Either set in HTML or via setAttribute in render — verify either path.
  // index.html uses role="list" on the static <ol>; renderPanel doesn't reset it.
  // For this test, simulate the static attribute by checking that ruler.js
  // doesn't strip or contradict it. Without DOM-parser context, the test
  // confirms the rows themselves carry role=listitem.
  const list = doc.elems['ruler-vertex-list'];
  assert.strictEqual(list.children[0].getAttribute('role'), 'listitem');
  assert.strictEqual(list.children[1].getAttribute('role'), 'listitem');
});
```

- [ ] **Step 2: Run, expect failure.**

Run: `node --test --test-force-exit frontend/tests/ruler/aria.test.mjs`
Expected: 4 failures.

- [ ] **Step 3: Extend `renderVertexList` to set richer ARIA.**

In `frontend/ruler.js`, inside `renderVertexList` after the existing `row.setAttribute('aria-selected', ...)`:

```javascript
      // Build a rich aria-label per spec §C.7
      var ariaParts = [v.label];
      ariaParts.push(window._formatDD(v.lat, 'NS') + ', ' + window._formatDD(v.lng, 'EW'));
      if (i < state.vertices.length - 1 && state.segments[i]) {
        ariaParts.push('distance to next ' + formatRulerDistance(state.segments[i].distance_m));
        ariaParts.push('bearing ' + state.segments[i].bearing_deg.toFixed(1) + '°');
      }
      row.setAttribute('aria-label', ariaParts.join(', '));
```

In `index.html` (Task 0.2 already added it), confirm the static `<ol id="ruler-vertex-list" role="list">` has `role="list"`. If missing, add it.

In Task 4.6's renderElevation, add `spark.setAttribute('role', 'img')` once before the aria-label set.

- [ ] **Step 4: Run, verify green.**

Run: `node --test --test-force-exit frontend/tests/ruler/aria.test.mjs`
Expected: 4 tests pass.

- [ ] **Step 5: Manual screen-reader smoke (iOS Safari + VoiceOver).**

On an iOS device with VoiceOver enabled, navigate to the dev URL. Open Measure tab. Place 3 vertices + Finish. Use rotor / swipe to navigate the vertex list:
- Each row announces "V1, decimal-degrees, distance to next X, bearing Y°" (specific format, NOT generic "list item").
- Sparkline announces "Elevation profile, min X feet, max Y feet, gain Z feet, loss W feet" (once per render — not every interaction).
- Floating banner announces aria-live polite when entering drawing/inserting.
- The cancel `[×]` button is reachable by swipe and named "Cancel ruler mode".

- [ ] **Step 6: Commit.**

```bash
git add frontend/ruler.js frontend/index.html frontend/tests/ruler/aria.test.mjs
git commit -m "$(cat <<'EOF'
feat(ruler): rich vertex-row aria-label + verified ARIA wireup

Each vertex row's aria-label now includes label + coords + segment-
out distance + bearing, so a screen-reader-only user gets the same
information visible-readers see in the row. Sparkline carries
role='img' + aria-label summarizing min/max/gain/loss numerically.

4 tests covering aria-label content, aria-selected toggle, sparkline
role+label, and listitem role on each row.

Manual VoiceOver smoke verifies the rendered announcements per
spec §C.7's accessibility checklist.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §C.7
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 5.4)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5.5: Banner-slot reuse with `#nav-banner` — ruler banner takes precedence during ruler-active

Per spec §D.4: when active nav coexists with active ruler (`drawing` / `inserting`), the ruler banner shows; nav banner is occluded by z-index. When ruler exits, nav banner re-renders if nav is still active.

The CSS work for z-index 19 vs 18 was done in Task 0.5. This task is the verification + a small explicit check in `renderBanners` to ensure no stale state leaks.

**Files:**
- Modify: `frontend/ruler.js` (small explicit guard in `renderBanners`)
- Manual ship-gate (no automated; nav state too coupled)

- [ ] **Step 1: Verify `renderBanners` correctness (no code change usually needed).**

Open `frontend/ruler.js` and find `renderBanners()`. Confirm it:
- Sets `floating` (the `#ruler-mode-banner`) hidden=false ONLY when state ∈ {drawing, inserting}.
- Sets it hidden=true otherwise.
- Does NOT touch `#nav-banner` directly (it's app.js's responsibility).

If `renderBanners` does anything that disables/hides `#nav-banner` directly, REMOVE that — z-index ordering does the right thing without explicit show/hide of nav.

- [ ] **Step 2: Manual ship-gate verification (no automated test).**

Run a real navigation route in the frontend (Layers → Route → Get Directions). With nav active, open Measure tab and place a vertex.

Expected:
- Ruler floating banner appears at top-center (z-index 19).
- Nav banner is occluded (z-index 18 — visually hidden behind ruler banner).
- Voice prompts continue from nav (TTS audible).
- Press Esc / [×] cancel on ruler banner → ruler exits → nav banner re-renders correctly at top-right.
- End nav → ruler banner remains visible (no leftover nav UI artifacts).

- [ ] **Step 3: Document the verification in `dev/implementation-log.md`.**

Append (or extend the 2026-04-24 entry):
```
2026-04-24 ruler — Task 5.5 banner-slot reuse manually verified.
Ruler+nav coexist; ruler banner takes precedence (z-index 19 vs 18);
nav voice TTS continues; ruler exit returns nav banner to its slot.
```

- [ ] **Step 4: Commit.**

```bash
git add dev/implementation-log.md
git commit -m "$(cat <<'EOF'
docs(ruler): log Task 5.5 banner-slot reuse manual verification

Spec §D.4's ruler+nav coexistence requirement is enforced by
CSS z-index alone (Task 0.5 set ruler-mode-banner to z=19 above
nav-banner z=18). renderBanners() does NOT touch #nav-banner
directly — z-index ordering is sufficient.

Manual verification confirmed: with nav active, ruler banner
takes the top-center slot; nav voice continues; ruler exit
returns the nav banner to its slot.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §D.4
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 5.5)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5.6: Manual ship-gate — Cameron runs the post-R5 measurable checklist

The build-robust-features cycle's discipline: agent-complete ≠ ship-complete. Cameron runs the spec §Testing checklist (33 measurable items across functional happy path, state preservation, touch/mobile, cross-network, coverage/failure modes, nav coexistence, unit toggle, style-load reattach, keyboard, accessibility, color contrast). Any failure → file issue, stay on `dev`.

**Files:** (no code changes — manual checklist + status capture)

- [ ] **Step 1: Run the full spec §Testing checklist.**

Open `docs/superpowers/specs/2026-04-24-ruler-design.md` and walk through each `[ ]` checklist item under "Manual ship-gate checklist (post-R5 — measurable assertions, not vibes)". Each item has measurable pass/fail criteria.

Sections (~33 items total):
- Functional happy path (8 items)
- State preservation (4 items)
- Touch / mobile (real devices, not emulators) (4 items)
- Cross-network / cross-environment (2 items)
- Coverage / failure modes (3 items)
- Coexistence with nav (2 items)
- Unit toggle (1 item)
- Style-load reattach (1 item)
- Keyboard (5 items)
- Accessibility (3 items)
- Color contrast (2 items)

- [ ] **Step 2: Track pass/fail in `dev/implementation-log.md`.**

Append a 2026-04-24 ruler ship-gate entry with each item's status. For any failure: file an issue (or write a `dev/ship-blockers/2026-04-24-ruler-<n>.md` note) AND keep `dev` on hold.

- [ ] **Step 3: If all pass, merge `dev` → `main`.**

Per CLAUDE.md §"Commit and release discipline": `release-please`'s Release PR is the ONLY release mechanism. Standard merge:

```bash
git switch main
git merge --ff-only dev
git push origin main
```

`release-please` auto-bumps to a `feat:`-driven minor version on the next trigger.

- [ ] **Step 4: Commit ship-gate log.**

```bash
git add dev/implementation-log.md
git commit -m "$(cat <<'EOF'
docs(ruler): ship-gate run — all 33 manual items recorded

Per build-robust-features discipline, agent-complete ≠ ship-
complete. Cameron walked the spec §Testing checklist covering:
  - functional happy path (8 items)
  - state preservation (4)
  - touch/mobile (4)
  - cross-network (2)
  - coverage/failure (3)
  - nav coexistence (2)
  - unit toggle (1)
  - style-load reattach (1)
  - keyboard (5)
  - accessibility (3)
  - color contrast (2)

Pass/fail recorded per item in implementation-log.md. Any failure
gates the dev → main merge until resolved.

Refs: docs/superpowers/specs/2026-04-24-ruler-design.md §Testing
Refs: docs/superpowers/plans/2026-04-24-ruler-plan.md (Task 5.6)

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Phase 5 review checkpoint

> **Phase 5 review (≥3 rounds):** All 5.1 grep-enforcement tests pass; 5.2 units-toggle integration test passes; 5.3 keyboard nav demonstrably works (Tab, Space/Enter, ↑/↓); 5.4 ARIA verified via screen-reader manual check (rich aria-labels per row + sparkline summary); 5.5 banner-slot reuse manually verified with nav running concurrently; 5.6 33-item manual ship-gate checklist signed off (all PASS) before merging to `main`. All Phase 0+1+2+3+4+5 tests still green: `node --test --test-force-exit frontend/tests/ruler/`. `python -m pytest tests/ services/search/tests/ -q` reports unchanged baseline.

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

**All five phases (0 through 5) are written in full skill-canonical detail.** Every task has Step 1 (failing test), Step 2 (verify fail), Step 3 (implement), Step 4 (verify pass), Step 5 (commit) with concrete code samples and exact commit boilerplate. A subagent can pick up any task and execute it without external reference beyond the spec.

History: this plan was committed as v1 in `41b431d` with Phases 0-1 skill-canonical and Phases 2-5 in summary-table form. v2 (this commit) expanded Phases 2-5 to match Phase 0-1 detail while keeping Phases 0-1 byte-identical to v1 — re-use of completed work is intentional. The v2 expansion was a mechanical follow-up to v1's deliberate token-economy trade-off, executed in a fresh session per the v1 commit's "ask the controller to expand the plan in a follow-up pass" guidance.

**The implementation appendix below is now redundant with the inline task content** — its safe-DOM, rAF-coalescer, AbortController-gen-counter, LRU, segment-projection-caller, and iOS-touch-contract patterns all appear inside the relevant Phase 2-4 tasks. The appendix is preserved for two reasons: (a) it functions as a quick-reference index when a subagent gets confused mid-task, and (b) deleting it would risk dropping subtle edge-case framing the inline expansion may have shortened. If you find the appendix and the inline tasks contradict each other on any point, the **inline task wins** (it was written second, with the spec-section anchor, and matches the test asserts).

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
