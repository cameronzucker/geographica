# Sidebar mobile reset — Holistic hunter report

**Agent:** manzanita
**Date:** 2026-04-25
**Scope:** `frontend/app.js` (sidebar wiring, `initSidebarTabs`, `restoreLastSidebarTab`, new
`pageshow`/`visibilitychange` listeners), `frontend/index.html` (tab button DOM +
default-active class), `frontend/style.css` (`.tab-btn.active`, `#sidebar.open`, media
queries), `docs/superpowers/specs/2026-04-24-sidebar-tab-restore-design.md`, commits
`9647efc` / `0257bca` / `46bd08c`.

---

## State model

**What state is owned by sidebar:**

| State | Owner | Location |
|---|---|---|
| Active tab identity | DOM | `.tab-btn.active` on one of 5 buttons |
| Active panel identity | DOM | `.panel.active` on one of 5 panels |
| Persisted tab identity | localStorage | key `sidebar-last-tab` |
| Sidebar open/closed | DOM | `#sidebar.classList` `.open` present/absent |

**Default state (from HTML, before any JS):** Layers tab button (`index.html:46`) has
`class="tab-btn active"`; `#layers-panel` has `class="panel active"` (`index.html:54`).
Route tab button has no `.active` class by default.

**Mutations:**

1. **User click on a tab button** → `initSidebarTabs()` click handler (wired in
   `DOMContentLoaded`) removes `.active` from all tabs/panels, adds to clicked tab and
   its panel, writes localStorage.

2. **`restoreLastSidebarTab()`** → reads localStorage, validates whitelist, idempotent
   check, calls `targetTab.click()` which fires mutation #1.

3. **`setSidebarOpen(open)`** → adds/removes `.open` on `#sidebar` and overlay. Does
   NOT touch `.active` on tabs or panels.

4. **`DOMContentLoaded`** → calls `initSidebarTabs()` + `restoreLastSidebarTab()` in
   sequence. Sets Route tab to `.active` if `route-panel` is in localStorage.

5. **`pageshow` listener** (new, `app.js:4294`) → calls `restoreLastSidebarTab()` when
   `readyState !== 'loading'`.

6. **`visibilitychange` listener** (new, `app.js:4301`) → calls
   `restoreLastSidebarTab()` when page becomes visible and `readyState !== 'loading'`.

**Events that do NOT mutate tab state:**
- `geographica:sidebar` custom event (only received by `voice-picker.js:449`, which only
  cancels speech previews)
- `nav-active` body class add/remove (nav-ui.js, no sidebar tab interaction)
- `orientationchange` / `resize` (no handlers in app.js)
- `ruler.js` `visibilitychange` (only aborts active drag)

---

## Reasoning trace

### Scenario A — In-page pane toggle (hamburger / overlay tap / swipe)

1. User is on Route tab. Route tab has `.active`; `localStorage['sidebar-last-tab'] = 'route-panel'`.
2. User taps overlay → `setSidebarOpen(false)` → `#sidebar.classList.remove('open')`. Tab `.active` classes **untouched**.
3. User taps hamburger → `setSidebarOpen(true)` → `#sidebar.classList.add('open')`. Tab `.active` classes **untouched**.
4. Sidebar slides in. Route tab is visually active. **No tab reset occurs.**

**Conclusion for Scenario A:** The code does not reset the tab on close/reopen. If Cameron sees a reset in a pure Scenario A flow (no backgrounding), it is not explained by anything in the JS or CSS. The new fix has no effect on this path (neither helps nor hurts).

### Scenario B — App lifecycle (background, lock, return)

#### B1 — BFCache restore (iOS Safari, short background, persisted=true)

1. Page frozen: Route tab has `.active`, sidebar closed.
2. iOS thaws page. JS heap fully preserved — all event listeners survive, `VALID_SIDEBAR_PANELS` and `restoreLastSidebarTab` are in closure scope.
3. `pageshow` fires with `persisted=true`. `readyState === 'complete'` → guard passes.
4. `restoreLastSidebarTab()`: reads localStorage → `'route-panel'`. Finds Route tab. Checks `.active` → **true** (BFCache preserved it). **Early-returns (idempotent).**
5. User opens sidebar → Route tab shown. ✓

**For this sub-path, the fix works correctly. The fix is also unnecessary (BFCache already preserved the tab state), but harmless.**

#### B2 — Tab-discard full reload (iOS under memory pressure, persisted=false)

1. iOS killed the renderer. Page fully reloads from network/cache.
2. HTML parsed → DOM starts with Layers `.active` (index.html defaults).
3. `DOMContentLoaded` fires:
   - `initSidebarTabs()` wires all click handlers. ←− handlers now live
   - `restoreLastSidebarTab()` reads localStorage → `'route-panel'` → clicks Route tab → Route tab becomes `.active`.
4. `pageshow` fires (after DOMContentLoaded). `readyState === 'complete'` → guard passes.
5. `restoreLastSidebarTab()` called again. Route tab already `.active` → **idempotent early-return**.
6. User opens sidebar → Route tab shown. ✓

**For this sub-path, both DOMContentLoaded and pageshow paths work. The fix is correct.**

#### B3 — App-switch return (no reload, no pageshow, DOM preserved)

1. User backgrounds the app (app-switch). Page stays alive but hidden.
2. Route tab has `.active`, sidebar closed.
3. `visibilitychange` fires with `document.hidden = true` → both `voice-picker.js:452-454` and `ruler.js:150-154` handle this correctly (neither touches tab state). `app.js:4301` handler: `if (document.hidden) return` → exits.
4. User returns to app. `visibilitychange` fires with `document.hidden = false`.
5. `app.js:4301` handler: `hidden` is false, `readyState === 'complete'` → calls `restoreLastSidebarTab()`.
6. Route tab already `.active` (DOM preserved) → **idempotent early-return**.
7. User opens sidebar → Route tab shown. ✓

**For this sub-path, the fix works correctly.**

---

## Findings

### F1 — `readyState === 'loading'` guard is based on a false premise (incorrect comment, not a functional bug)

**Location:** `frontend/app.js:4295-4297` (pageshow listener) and `app.js:4302-4303` (visibilitychange listener)

**Scenario:** Both

**What's wrong:** The comment at line 4295 reads:

```
// Skip if DOM not yet ready (first-load fires pageshow BEFORE
// DOMContentLoaded; the DOMContentLoaded path will handle it).
```

This is factually incorrect. On a normal first-load, the browser page lifecycle order is:

```
parse HTML → DOMContentLoaded → load → pageshow
```

`pageshow` fires AFTER `DOMContentLoaded` on first load, not before. By the time `pageshow` fires on a first load, `readyState` is already `'complete'` and `DOMContentLoaded` has already run. The guard `if (document.readyState === 'loading') return` therefore **never triggers on first-load `pageshow`**.

The guard IS legitimately useful for a different scenario: if the user opens Geographica as a background tab in iOS Safari, `visibilitychange` could fire while the page is still parsing (user switches to the tab mid-parse). In that case, `readyState === 'loading'` → correct to skip; `DOMContentLoaded` will handle it later. The guard is correct code for this one real case, but the comment identifies the wrong reason.

**Why this matches Cameron's signature:** It doesn't directly cause the tab-reset bug. However, the false comment misrepresents the lifecycle order in a way that could lead a future maintainer to misunderstand which paths are covered. If someone reads "pageshow fires BEFORE DOMContentLoaded" and decides to move the DOMContentLoaded path, they could break the first-load restore.

**Confidence:** High (the lifecycle order is well-specified; pageshow fires after DOMContentLoaded on first load per WHATWG HTML Living Standard §8.7.1).

**Severity:** Low — incorrect comment, guard itself is harmless, real behavior is correct.

---

### F2 — Scenario A (in-page close/reopen) is not covered by the fix and does not independently cause a reset — but represents an unverified field assumption

**Location:** `frontend/app.js:1179-1196` (`setSidebarOpen`), `app.js:1198-1209` (hamburger + overlay handlers)

**Scenario:** A

**What's wrong:** Cameron's field test description — "sidebar resets to Layers tab when he closes/reopens the left-hand pane" — is ambiguous about whether locking the phone was part of the sequence or just a close/reopen in-app. The code path for in-page toggle (`setSidebarOpen`) does not touch `.active` classes on tabs or panels. A pure in-page close/reopen cannot cause a tab reset based on the current code.

However, the spec's acceptance test (§6.1) explicitly includes "lock phone for ≥ 2 minutes" as part of the sequence. This indicates the intent is Scenario B. The field test symptom (sidebar shows Layers on reopen) aligns with an app-lifecycle restore where the in-memory `.active` state was lost (tab-discard rebuild defaulting to Layers from HTML).

**Why this matches Cameron's signature:** If Cameron's route to reproduction is: switch to Route tab → close sidebar → lock phone → return → reopen sidebar → see Layers, then the failure is Scenario B (app-lifecycle), which the new fix addresses. The new fix does NOT help if the reproduction is pure Scenario A (no lock), but that scenario shouldn't cause the tab reset either.

**Repro needed:** Cameron should verify whether the reset occurs (a) without locking the phone (pure Scenario A) or (b) only after locking/backgrounding (Scenario B). If (a), there is an undiscovered bug not visible in the JS/CSS code — possibly an iOS Safari DOM quirk with translateX-hidden elements.

**Confidence:** Medium — the distinction between A and B is critical to whether the new fix resolves Cameron's issue, but the code itself is correct for Scenario B.

---

### F3 — BFCache restore path is effectively a no-op: the fix does nothing for the most common iOS return path

**Location:** `frontend/app.js:4294-4299`

**Scenario:** B (BFCache specifically)

**What's wrong:** On a true BFCache restore (`pageshow` with `persisted=true`), iOS Safari preserves the entire JS heap AND the entire DOM, including all `.active` classes. The Route tab's `.active` class is therefore preserved when the page is thawed. When `restoreLastSidebarTab()` runs (triggered by the new pageshow listener), it checks `targetTab.classList.contains('active')` at line 4129 — **returns true** → early-returns without doing anything.

The fix does not fail for BFCache — but it also does not DO anything for BFCache. The Route tab was already active; no code was needed to restore it. This means that if Cameron's symptom was occurring specifically via BFCache restores, the bug he observed with `f1687df` was NOT caused by the missing pageshow listener. Something else would have had to reset `.active` AFTER the BFCache thaw but BEFORE the pageshow listener fired.

There is no code in the codebase that resets `.active` on tabs after a BFCache thaw. The only mutation that removes `.active` from Route tab would be another tab-button click or `initSidebarTabs()` re-running (which doesn't happen on BFCache).

**Implication:** Cameron's original bug (with `f1687df`) is most likely explained by **tab-discard restores** (not BFCache), where iOS killed the renderer and DOMContentLoaded fired but `restoreLastSidebarTab()` from `f1687df` should have worked — OR by an unusual iOS behavior that bypasses DOMContentLoaded even on full reloads. The new fix adds `pageshow` as an additional trigger, which would catch any case where DOMContentLoaded fires but doesn't reach `restoreLastSidebarTab()` (theoretically impossible given the sequential call order in the callback), OR where DOMContentLoaded doesn't fire at all on some iOS restore paths.

**Repro:** Not directly reproducible in a browser dev environment; requires iOS Safari field test with lock/background/return.

**Confidence:** High (reasoning from BFCache spec behavior), but consequence depends on which iOS restore path Cameron actually hits.

---

### F4 — No bug: `initSidebarTabs()` click handlers are always wired before `restoreLastSidebarTab()` fires from any event listener

**Note:** This was hypothesis H1 in the hunt brief. Confirmed ruled out.

`initSidebarTabs()` is called at line 4157, which is position 2 in the DOMContentLoaded callback. `restoreLastSidebarTab()` is called at position 10 (line 4167). They are sequential in the same synchronous callback — no race is possible.

For the `pageshow` and `visibilitychange` listeners: on BFCache restores, the original DOMContentLoaded closure (with wired handlers) is preserved. On full reloads, DOMContentLoaded fires before pageshow, so handlers are wired before pageshow fires. On app-switch `visibilitychange`, the page was already fully initialized — handlers have been wired since the original load.

---

## Hypotheses ruled out

**H1 — Synthetic click before handlers wired:** Ruled out. `initSidebarTabs()` runs at position 2 in DOMContentLoaded, `restoreLastSidebarTab()` at position 10. Listeners from `pageshow`/`visibilitychange` fire only after DOMContentLoaded has already run (on fresh loads) or JS heap is preserved (BFCache/app-switch). No window where click fires without handlers.

**H2 — localStorage silently swallows writes (iOS private mode):** Not Cameron's scenario. He is testing on his own device in normal mode. Even if relevant, it would be a pre-existing issue with the `f1687df` architecture, not a bug introduced by the new fix.

**H3 — Code path resets to Layers on certain events:** Exhaustively checked. `setSidebarOpen` does not touch `.active`. `nav-ui.js` does not manipulate sidebar tabs. `voice-picker.js:449` listener only cancels speech previews. `ruler.js` visibilitychange only aborts active drags. No `geographica:sidebar` consumer resets tab state. No `resize`/`orientationchange` handler exists. **Ruled out.**

**H4 — CSS specificity battle between two `.active` classes:** The HTML default is `class="tab-btn active"` on Layers. The click handler removes `.active` from all tabs before adding it to the target. The CSS rule `.tab-btn.active` is a single class selector — no specificity issue. CSS never "picks" between two `.active` classes; the JS ensures only one tab has `.active` at a time. **Ruled out.**

**H5 — `geographica:sidebar` custom event resets active tab:** Only `voice-picker.js:449` listens for this event. Its handler (`onSidebarClose`) only sets `previewArmed = false`, clears `idleResetTimer`, and cancels speech synthesis. No tab class manipulation. **Ruled out.**

**H6 — Sidebar `.open` class removal triggers tab reset:** CSS transition (`transform 0.3s ease`) does not affect JS state. No MutationObserver or transitionend handler resets tabs. **Ruled out.**

**H7 — `window.location.reload()` triggered by sidebar close:** No reload call anywhere near sidebar close handlers. `setSidebarOpen` is 15 lines; no reload. **Ruled out.**

**H8 — `pageshow` fires before `VALID_SIDEBAR_PANELS` is defined:** `VALID_SIDEBAR_PANELS` is declared at line 4118, a synchronous `var` statement inside the IIFE. By the time any `pageshow` event fires (which is a runtime event, always after script parse), the IIFE has fully executed and `VALID_SIDEBAR_PANELS` is assigned. Even on BFCache restores, the JS heap with the assigned value is preserved. **Ruled out.**

**H9 — `pageshow` listener fires before `initSidebarTabs()` in mobile Safari with partial parse:** The `readyState === 'loading'` guard in both the pageshow and visibilitychange listeners prevents `restoreLastSidebarTab()` from running until the DOM is ready. The only way `restoreLastSidebarTab()` fires without `initSidebarTabs()` having run would be if `readyState` transitions out of `'loading'` before DOMContentLoaded runs — which is impossible by spec (readyState becomes 'interactive' at the same moment DOMContentLoaded fires). **Ruled out.**

**H10 — New listeners wired INSIDE DOMContentLoaded callback:** Both new listeners are at lines 4294-4305, inside the IIFE but OUTSIDE the `document.addEventListener('DOMContentLoaded', ...)` block (which closes at line 4285). They are at 2-space IIFE indentation, not 4-space DOMContentLoaded body indentation. They register at IIFE execution time (script parse), not at DOMContentLoaded time. **Ruled out.**

---

## Summary for Cameron

The new fix (`0257bca`) is logically sound for Scenario B (app-lifecycle returns). All three code paths — BFCache, tab-discard full reload, and app-switch — are handled without races or gaps:

- **BFCache:** fix fires but is idempotent (DOM preserved by iOS, Route tab already `.active`).
- **Tab-discard reload:** DOMContentLoaded fires first (wires handlers + restores tab), then pageshow fires idempotently.
- **App-switch:** visibilitychange fires, idempotent if DOM preserved.

The one actionable finding is **F1** (the comment at line 4295 incorrectly states `pageshow` fires before `DOMContentLoaded` on first load — it fires after). This is a documentation bug in the code, not a functional bug, but worth fixing to prevent future maintainer confusion.

The open risk is **F2**: if Cameron's actual reproduction path is a pure in-page close/reopen **without** any backgrounding/locking, the new fix doesn't help and wouldn't — but that path also shouldn't cause a tab reset per code analysis. Cameron should confirm during field test whether the reset occurs without locking the phone. If it does, there is an undiscovered iOS Safari-specific behavior (possibly around CSS transform visibility + class state) that isn't captured in the current codebase.

**Recommended fix for F1** (comment-only change in `app.js`):

```js
window.addEventListener('pageshow', function (e) {
  // Guard against the edge case where the user switches to a background tab
  // mid-parse (visibilitychange fires, then pageshow fires, both while
  // readyState is still 'loading'). DOMContentLoaded will handle it.
  // Note: on normal first-loads, pageshow fires AFTER DOMContentLoaded
  // (readyState is already 'complete' by then), so this guard is a no-op
  // for that path.
  if (document.readyState === 'loading') return;
  restoreLastSidebarTab();
});
```
