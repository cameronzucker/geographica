# Sidebar mobile reset — Exploratory hunter report

**Date:** 2026-04-25
**Hunter:** manzanita (exploratory)

---

## Threads followed

### Thread 1: What does "closing the sidebar pane on mobile" actually do?

Examined `initSidebarTabs()` (`app.js:1155-1220`) and `setSidebarOpen()` (`app.js:1179-1196`).

**Only two UI controls can close the sidebar:**
- Hamburger button (`#sidebar-toggle`) → `setSidebarOpen(!sidebar.classList.contains('open'))` — toggle
- Overlay backdrop (`#sidebar-overlay`) click → `setSidebarOpen(false)` — close

`setSidebarOpen` body:
- Adds/removes `.open` on `#sidebar` and `#sidebar-overlay`
- Adds/removes `.sidebar-open` on `#search-container`
- Adds/removes `.hidden` on `#sidebar-toggle`
- Calls `map.setPadding(...)` to adjust MapLibre viewport padding
- Dispatches `geographica:sidebar` custom event

**None of these actions touch `.active` on `.tab-btn` or `.panel` elements.** The sidebar open/close cycle is purely a CSS visibility mechanism (`transform: translateX(-100%)` / `translateX(0)`). DOM tab state is fully preserved across the toggle.

No swipe-to-close gesture handler exists. The overlay is the only "tap outside" dismiss path.

---

### Thread 2: Does anything listen to `geographica:sidebar` event?

Grep confirmed only ONE listener outside of the dispatch site:

```
frontend/voice-picker.js:449:  document.addEventListener('geographica:sidebar', function (e) {
```

`voice-picker.js:449-451` calls `onSidebarClose()` when `e.detail.open === false`. `onSidebarClose()` (`voice-picker.js:286-293`) only resets `previewArmed`, clears `idleResetTimer`, and cancels speech synthesis. **Zero interaction with sidebar tab state.**

The `geographica:sidebar` event path is ruled out as a tab-reset vector.

---

### Thread 3: Does `targetTab.click()` actually transfer the active class?

Traced the click handler wired in `initSidebarTabs()`:

```js
tab.addEventListener('click', function () {
  var target = this.dataset.panel;
  var panelEl = document.getElementById(target);
  if (!panelEl) return;
  tabs.forEach(function (t) { t.classList.remove('active'); });   // line 1164
  panels.forEach(function (p) { p.classList.remove('active'); }); // line 1165
  this.classList.add('active');   // line 1166 — 'this' = clicked button
  panelEl.classList.add('active'); // line 1167
  try { localStorage.setItem('sidebar-last-tab', target); } catch (e) {}
});
```

When `restoreLastSidebarTab()` calls `targetTab.click()`, `this` inside the handler is `targetTab` (the Route button). The handler:
1. Removes `.active` from all 5 tab buttons and 5 panels (confirmed: `tabs`/`panels` are static NodeLists from `querySelectorAll`, correct count)
2. Adds `.active` to Route button
3. Adds `.active` to route-panel
4. Writes `'route-panel'` to localStorage

The synthetic click path is mechanically correct.

---

### Thread 4: Race — is `initSidebarTabs()` wired before `restoreLastSidebarTab()` fires?

`DOMContentLoaded` callback in app.js (lines 4155-4285) calls in strict sequence:
1. `initMap()` (line 4156)
2. `initSidebarTabs()` (line 4157) ← wires click handlers
3. `initLayerControls()`, `initSearch()`, `initRouting()`, `initImport()`, `initGPS()`
4. `initAdmin()` (line 4163) ← must precede restore per test assertion
5. `window._ruler.init()` if available
6. `restoreLastSidebarTab()` (line 4167) ← synthetic click fires AFTER handlers wired

No race is possible on the DOMContentLoaded path.

For `pageshow`/`visibilitychange` paths:
- **BFCache restore:** entire JS heap is preserved — handlers wired since original DCL are still live
- **Tab-discard full reload:** DCL fires first (handlers wired), then pageshow fires
- **App-switch visibilitychange:** page fully initialized, handlers live since original DCL

No path exists where `restoreLastSidebarTab()` fires before `initSidebarTabs()` has wired the click handlers.

---

### Thread 5: localStorage write reliability

`localStorage.setItem` at `app.js:1168` is inside `try/catch`. On iOS Private Browsing (zero-quota localStorage), the write throws and is silently swallowed. The `localStorage.getItem` at `app.js:4122` is also in a `try/catch` — if it throws, the function returns early and Layers (HTML default) is preserved.

In standard non-private mode: write succeeds, `'route-panel'` is stored. No silent failure path relevant to Cameron's normal-mode navigation session.

The `VALID_SIDEBAR_PANELS` whitelist at `app.js:4118` correctly includes `'route-panel'` at index 1. The `indexOf` check succeeds.

---

### Thread 6: Is there a "reset to Layers" path anywhere?

Exhaustive grep for anything that:
- Calls `.click()` on the Layers tab button
- Adds `.active` to Layers button or `#layers-panel`
- Removes `.active` from the Route button without adding it to something else

**Results:** The ONLY code that mutates `.tab-btn.active` or `.panel.active` is the click handler inside `initSidebarTabs()` (lines 1164-1167). This handler only fires from explicit user clicks or the synthetic click in `restoreLastSidebarTab()`. Neither `nav-ui.js`, `navigation.js`, `ruler.js`, `voice-picker.js`, nor `import-store.js` manipulate tab/panel active state. No programmatic Layers-tab activation exists anywhere.

**Conclusion: The tab reset Cameron observes CANNOT happen through Scenario A (pure in-page toggle) in the current code.** The DOM `.active` classes are preserved when the sidebar is hidden.

---

### Thread 7: Is the sidebar `.open` class removed unexpectedly?

`setSidebarOpen(false)` is called only from:
- Overlay click handler (`app.js:1207`)
- Hamburger toggle click handler (`app.js:1200`) when sidebar is open

No other code removes `.open` from `#sidebar`. No timer, no nav event, no orientation event, no map event triggers a sidebar close. Nav-active mode only repositions the hamburger button via CSS, does not close the sidebar.

---

### Thread 8: Mobile-specific code paths

CSS media queries at `@media (max-width: 768px)` and `@media (max-width: 480px)` only affect `--sidebar-width`, nav-instruction font sizes, and search container layout. No media-query-triggered JS event handlers. No `matchMedia` listeners in `app.js`. No `window.innerWidth` branches affecting sidebar tab state.

`nav-active` body class is set/cleared by `nav-ui.js:164` and `nav-ui.js:206`. The `voice-picker.js` MutationObserver (`voice-picker.js:457-459`) watches body class changes and calls `renderDropdown()` — which only touches `#pref-voice-select`. No sidebar tab effect.

---

## Findings

### F1 — Admin polling permanently dead after BFCache return on Admin tab

**Location:** `frontend/app.js:4129` (idempotent guard) + `app.js:3740-3744` (admin polling start)
**Scenario:** B (BFCache return specifically)
**What's wrong:**

The idempotent guard:
```js
if (targetTab.classList.contains('active')) return;  // idempotent
```

On a BFCache restore, iOS Safari freezes AND thaws the entire JS heap + DOM. The Admin tab button retains its `.active` class exactly as the user left it. When `pageshow` fires and `restoreLastSidebarTab()` runs, the Admin tab already has `.active` → **the guard triggers early-return before `targetTab.click()` fires**.

`initAdmin()`'s click listener at `app.js:3740-3744` (which calls `fetchAdminStatus()` + `setInterval(fetchAdminStatus, ADMIN_REFRESH_MS)`) **never fires**. iOS kills timer-based callbacks during background. So `adminTimer` is dead and never restarted. The Admin panel shows permanently stale service/data-task status until the user manually taps another tab and taps Admin again.

The spec §4.3 states: "Admin polling restart is implicit — the synthetic click naturally re-invokes initAdmin's listener." This is only true on tab-discard/full-reload paths (where the HTML default Layers is active and the synthetic click is needed). On BFCache paths (where Admin is already `.active`), the claim is false. The idempotent guard silently breaks the spec's polling-restart guarantee.

**Why this matches Cameron's signature:** This is NOT the "reverts to Layers" symptom, but it IS a regression introduced by the idempotent guard change in `0257bca`. If Cameron opens Admin, backgrounds the app, returns via BFCache, and observes stale service status, this is the cause. He may interpret it as an admin endpoint bug.

**How to reproduce in test:**
1. Open Admin tab. Observe 30s polling refresh.
2. Background iOS Safari (app switch) for ≥ 30s.
3. Return to Safari (BFCache restore — page doesn't reload, URL bar reappears instantly).
4. Admin tab is visually active (BFCache preserved it).
5. Wait 60s. Observe that Admin panel data does NOT refresh automatically.
6. Tap Layers tab → tap Admin tab → polling resumes.

**Confidence:** High — provable from code path without device testing. The idempotent guard prevents the click; the admin listener requires the click; BFCache preserves the active state. All three facts are deterministic.

---

### F2 — `setSidebarOpen(true)` is an unguarded fourth "sidebar-becomes-visible" path

**Location:** `frontend/app.js:1179-1196` (`setSidebarOpen` body)
**Scenario:** A (in-page toggle, but only manifests under a specific iOS DOM-reset condition)
**What's wrong:**

Three paths call `restoreLastSidebarTab()` when sidebar content becomes visible to the user:
- `DOMContentLoaded` (first load)
- `pageshow` listener (BFCache + tab-discard returns)
- `visibilitychange` listener (app-switch returns)

The **fourth path — `setSidebarOpen(true)` (user taps hamburger)** — does NOT call `restoreLastSidebarTab()`.

For pure Scenario A (no backgrounding, no page lifecycle event), this gap is harmless: `setSidebarOpen` doesn't touch `.active` classes, so the DOM tab state is correct before and after the hamburger tap. Route stays active.

However, if iOS Safari resets DOM class attributes (stripping dynamically-added `.active`) after a BFCache thaw but before `pageshow` fires — a non-standard but plausibly observed behavior on some iOS/iPadOS builds — the following scenario produces the "reverts to Layers" symptom even with the new fix in place:

1. BFCache thaw occurs. iOS strips dynamically-added `.active` from Route button (resets to HTML default: Layers active).
2. `pageshow` fires. `restoreLastSidebarTab()` runs. Finds Route does NOT have `.active` → clicks Route → Route becomes active. ← **This should fix it.**
3. Sidebar is still closed. User taps hamburger.
4. `setSidebarOpen(true)` runs. Does NOT call `restoreLastSidebarTab()`.
5. **If the `.active` state was somehow again reset between step 2 and step 3**, user sees Layers.

The scenario requires two DOM resets in sequence, which is theoretically unlikely. However, if iOS resets the DOM at hamburger-tap time (e.g., the CSS transition triggers a relayout that reverts JS-set attributes in some buggy OS build), the `setSidebarOpen` gap would be exploitable. This is unconfirmed from code analysis alone.

**The conservative fix** is to add `restoreLastSidebarTab()` at the start of the `if (open)` branch in `setSidebarOpen`:

```js
function setSidebarOpen(open) {
  if (open) {
    restoreLastSidebarTab();  // ← add this line
    sidebar.classList.add('open');
    // ...
  }
```

This is cheap (idempotent — one localStorage read + NodeList walk), covers the gap, and is correct to call unconditionally since `restoreLastSidebarTab` is idempotent by design.

**Why this matches Cameron's signature:** If Cameron's repro is Scenario A (closes sidebar, reopens it in the same session without backgrounding) and sees Layers, this gap — activated by iOS DOM-reset behavior — is the only code-level explanation. The symptom would be perfectly consistent: every hamburger-open shows Layers because no restoration is attempted at open time.

**How to reproduce in test (platform hypothesis):**
1. On iOS Safari, load Geographica fresh.
2. Tap Route tab. Observe Route panel visible.
3. Tap overlay to close sidebar.
4. Tap hamburger to reopen sidebar.
5. If sidebar shows Layers, Scenario A is real and `setSidebarOpen` needs the `restoreLastSidebarTab()` call.

(If step 5 shows Route, the pure Scenario A path works correctly on this device and the F2 gap is harmless.)

**Confidence:** Medium — the code gap is real and provably absent from the current fix. Whether the iOS platform triggers it depends on undocumented OS behavior. Cameron's field test of step 3-5 above (no phone locking, pure same-session toggle) is the critical diagnostic.

---

### F3 — Dead guard + incorrect comment on `pageshow` listener

**Location:** `frontend/app.js:4295-4297`
**Scenario:** Neither — documentation error only, no user-facing impact
**What's wrong:**

The comment at `app.js:4295` reads:
```
// Skip if DOM not yet ready (first-load fires pageshow BEFORE
// DOMContentLoaded; the DOMContentLoaded path will handle it).
```

This is factually incorrect. Per the HTML Living Standard §8.7.1, the page lifecycle order on a first load is:

```
parse HTML → DOMContentLoaded → load → pageshow
```

`pageshow` fires AFTER both `DOMContentLoaded` and `load`. By the time `pageshow` fires on a first load, `document.readyState` is always `'complete'`. The guard `if (document.readyState === 'loading') return` is therefore **dead code** for the `pageshow` path — it never triggers.

The guard does protect one real (narrower) case: a user opening a background iOS Safari tab mid-parse and triggering `visibilitychange` while `readyState === 'loading'`. But the comment describes the wrong event and the wrong scenario.

The behavior is correct despite the wrong guard: the idempotent early-return at `app.js:4129` catches the double-call on first load. But a future developer reading this comment might incorrectly model the lifecycle and introduce a dependency on the false ordering assumption.

**Confidence:** High (incorrect per spec, dead code) — but no user-facing impact.

---

## Dead ends

### `geographica:sidebar` listener resets tabs
Ruled out. `voice-picker.js:449` is the only listener. Its `onSidebarClose()` handler only cancels speech previews. No tab class manipulation.

### `nav-ui.js` or `navigation.js` auto-switch tabs on nav start/stop
Ruled out. Neither file has any reference to `tab-btn`, `data-panel`, `route-panel`, `layers-panel`, or `setSidebarOpen`. `startNavigation()` and `stopNavigation()` only manipulate `body.nav-active`, nav overlay visibility, wake lock, and GPS feed.

### Double-wired click handlers cause state corruption
Ruled out. `initSidebarTabs()` is called exactly once (inside the single `DOMContentLoaded` callback at `app.js:4157`). On BFCache restores, `DOMContentLoaded` does not re-fire, so no duplicate handler registration.

### `VALID_SIDEBAR_PANELS` undefined at pageshow/visibilitychange fire time
Ruled out. It's a `var` declaration at `app.js:4118` inside the IIFE. All callers are async event handlers that fire after the IIFE has fully executed. `var` hoisting only poses a risk for synchronous reads during IIFE evaluation, not for async callbacks.

### CSS media queries reset active tab state
Ruled out. No media query or `matchMedia` listener in app.js, nav-ui.js, or ruler.js touches `.tab-btn.active` or `.panel.active`.

### `ruler.js` `visibilitychange` resets sidebar
Ruled out. `ruler.js:150-154` only calls `cancelActiveDrag()` when `document.hidden && view.dragging`. No tab state manipulation.

### `map.setPadding()` triggers a repaint event that resets classes
Ruled out. MapLibre `setPadding` only modifies the internal viewport padding for tile rendering. It dispatches MapLibre events (`move`, `moveend`) but no DOM class changes. No `app.js` listener on `map.on('move')` touches sidebar tab state.

### localStorage missing write causes first-session restore failure
Ruled out for Cameron's scenario. He's testing in normal (non-private) Safari mode with localStorage available. Even if this were true, it would be a pre-existing limitation of the `f1687df` architecture, not a regression from `0257bca`.
