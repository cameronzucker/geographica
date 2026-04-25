# Sidebar tab persistence — restore across all iOS Safari return paths

**Date:** 2026-04-24
**Agent:** pinyon
**Scope:** Cameron's field test on the live dev stack reported that the sidebar tab resets to "Layers" after reopening following active navigation, even with the `f1687df` fix in place. The fix only hooks `DOMContentLoaded`, which iOS Safari does not fire on BFCache restores or several other return paths. This spec widens the restore mechanism to cover all common page-lifecycle return paths and addresses two collateral concerns: the synthetic `.click()` clobbering form focus during active editing, and admin-polling staying dead after a restore that lands the user on the Admin tab.
**Files:** [frontend/app.js](../../../frontend/app.js) (sidebar tab restore wiring), [tests/test_frontend_voice_picker.py](../../../tests/test_frontend_voice_picker.py) (structural test extension).
**Prior art:**
- Commit `f1687df` (the partial fix this spec completes) — DOMContentLoaded-only restore via localStorage.
- Adversarial findings R1 F1.7 (admin-polling dead after BFCache), Codex F5.2 (BFCache is one path among many), Codex F5.7 (synthetic click clobbers form focus). All from the [combined 2026-04-24 adversarial review](../../../dev/adversarial/) run on the v1 nav-voice-followup spec that originally bundled this issue.

## Revision history

- **v1 (2026-04-24)** — Split out from [2026-04-24-nav-voice-followup-design.md](2026-04-24-nav-voice-followup-design.md) v1 per Codex F5.1 + R4 F4.13 (orthogonal risk surface, different file, different test harness, separate ship gate). Standalone spec from this point. Incorporates the adversarial findings before any code is written.

## 1. Summary

`f1687df` shipped a sidebar tab persistence mechanism: click handlers `setItem('sidebar-last-tab', target)` to localStorage; `DOMContentLoaded` calls `restoreLastSidebarTab()` which reads localStorage and synthetically `.click()`s the saved tab. Cameron field-tested this and the bug (sidebar reverts to Layers on reopen during active navigation) **persists** on his iOS device.

Root cause: **iOS Safari restores backgrounded pages via mechanisms that do NOT fire `DOMContentLoaded`**:

1. **BFCache restore** — `pageshow` with `event.persisted === true`. Most common case for short-backgrounded tabs.
2. **Tab-discard restore** — `pageshow` with `event.persisted === false` after a renderer recreation. iOS aggressively discards backgrounded tabs under memory pressure; on return, the page reloads but lifecycle fires differ from a true first-load.
3. **PWA standalone-mode process recreation** — when the app is launched from a home-screen icon, iOS may treat returns differently than browser tabs.
4. **Visibilitychange + partial rehydration** — `document.hidden` flips to false on app-switch return; for some return paths this is the only signal that fires.
5. **Audio session interruption** — speech synthesis pauses for an incoming phone call, then resumes; the visible state may have been re-rendered by the system without firing standard load events.

The `f1687df` fix only hooks `DOMContentLoaded`, which fires only on path 0 (true first-load parse from network). Paths 1-5 leave `restoreLastSidebarTab` un-invoked, and the hardcoded `class="tab-btn active"` on the Layers button at [index.html:46](../../../frontend/index.html#L46) wins by default.

Two collateral problems surface in adversarial review of the originally-proposed `pageshow + e.persisted` fix:

- **C1 — admin-polling dead after BFCache** (R1 F1.7). `initAdmin` wires the admin tab's click handler at DOMContentLoaded. On a BFCache restore, that wiring survives in memory (BFCache preserves the JS state), but if the saved tab is Admin and the click handler's `setInterval(fetchAdminStatus, ...)` was killed by iOS's timer-eviction-during-background, the polling never restarts. User sees the Admin tab restored visually but data is stale.
- **C2 — synthetic `.click()` clobbers form focus** (Codex F5.7). If the user was editing `#route-start` or `#route-end` when backgrounded and the saved tab is Route, the synthetic click fires while the input has focus → blur fires → any blur-driven validation / auto-regen runs → input value or selection might be discarded.

## 2. Goals & non-goals

### Goals

- **G1.** Sidebar tab restoration fires on **all** iOS Safari return paths that lose the in-memory `.active` class state, not just `DOMContentLoaded`.
- **G2.** Mechanism: `pageshow` listener (covers paths 1+2 — BFCache and tab-discard, both fire pageshow regardless of `persisted` value), supplemented by `visibilitychange` listener triggered when the page becomes visible (covers path 4). DOMContentLoaded path preserved for true first-loads.
- **G3.** Restoration is idempotent. Calling `restoreLastSidebarTab()` when the saved tab already has `.active` is a no-op (existing early-return). All event handlers can fire freely without side effects.
- **G4.** When `restoreLastSidebarTab()` triggers a synthetic `.click()`, **form focus is preserved**. If `document.activeElement` is an editable control inside any panel, the restoration captures focus + selection state, fires the click, and restores focus + selection.
- **G5.** When the saved tab is Admin and the restoration happens via a non-DOMContentLoaded path, admin polling restarts. Either by re-using the existing click-handler-based polling restart (which calls `setInterval(fetchAdminStatus, ...)`) or by an explicit polling-restart call inside the restore path.
- **G6.** Restoration logic does not synthetically click on the same tab repeatedly. The early-return "if already active" guard prevents loops.
- **G7.** Field-test acceptance: open Geographica during active navigation, switch to Route tab, close sidebar, lock phone for ≥ 2 minutes, return, reopen sidebar → Route tab is active (with the Stop Navigation button visible). Hard-reload the page → Route tab is still restored. Both paths work.

### Non-goals

- **NG1.** No change to the localStorage key (`sidebar-last-tab`) or value format.
- **NG2.** No change to the `VALID_SIDEBAR_PANELS` whitelist or click semantics for explicit user clicks.
- **NG3.** No restoration on user-deliberate navigation (e.g., user clicks Layers during nav-active state, then closes sidebar — reopen restores Layers, not Route, because the user's most recent click is what's persisted).
- **NG4.** No coverage of audio-session-interruption-only restorations (path 5). Theoretical concern; not field-observed. If/when reported, add a `mediasession` event hook.
- **NG5.** No platform-specific code paths (no `navigator.userAgent` Safari sniffing). The mechanism (`pageshow` + `visibilitychange`) is standard across all browsers; behavior on non-iOS is identical (idempotent restoration on every visibility/page-show event).
- **NG6.** No new persistent storage. Continue to use the same localStorage key.

## 3. Architecture

```
                                                                  
   First load (parse from network):                               
     DOMContentLoaded ──▶ initSidebarTabs() ──▶ wires click       
                          initAdmin() ──▶ wires admin polling     
                          ...                                      
                          restoreLastSidebarTab() ──▶ click saved 
                                                                  
   BFCache restore (background → return, short):                  
     pageshow(persisted=true) ──▶ restoreLastSidebarTab() ──▶ ...
                                                                  
   Tab-discard restore (background → return after eviction):      
     pageshow(persisted=false) ──▶ restoreLastSidebarTab() ──▶ ...
                                                                  
   App-switch return (no full reload, no pageshow):               
     visibilitychange(visible) ──▶ restoreLastSidebarTab() ──▶ ...
                                                                  
   Inside restoreLastSidebarTab():                                
     1. Read localStorage saved tab                               
     2. Validate against whitelist                                
     3. If saved tab already active → early return (idempotent)   
     4. Capture document.activeElement + selection (if editable)  
     5. targetTab.click()  // fires existing initSidebarTabs +    
                            // initAdmin handlers — admin polling 
                            // restarts via the same click path   
     6. Restore focus + selection if was editable                 
                                                                  
```

## 4. Implementation

### 4.1 Listener wiring

Add to [frontend/app.js](../../../frontend/app.js) **outside** the `DOMContentLoaded` block (so listeners wire up immediately at script-parse time, surviving any early-load race):

```js
// BFCache (persisted=true) and tab-discard (persisted=false) both fire pageshow
// on iOS Safari return paths. DOMContentLoaded does NOT fire for these. The
// listener calls restoreLastSidebarTab() unconditionally because the function
// is idempotent (early-returns when target tab already active).
window.addEventListener('pageshow', function (e) {
  // Skip if DOM not yet ready (true first-load fires pageshow BEFORE
  // DOMContentLoaded; the DOMContentLoaded path will handle it).
  if (document.readyState === 'loading') return;
  restoreLastSidebarTab();
});

// visibilitychange covers app-switch returns where iOS doesn't fire pageshow
// (e.g., return from a long-backgrounded session, partial rehydration paths).
document.addEventListener('visibilitychange', function () {
  if (document.hidden) return;
  if (document.readyState === 'loading') return;
  restoreLastSidebarTab();
});
```

The DOMContentLoaded-block call to `restoreLastSidebarTab()` (existing in `f1687df`) is preserved — true first-loads continue to work via that path.

### 4.2 `restoreLastSidebarTab()` — focus-preserving variant

Rewrite [app.js:4105-4118](../../../frontend/app.js#L4105-L4118) to capture and restore focus around the synthetic click:

```js
function restoreLastSidebarTab() {
  var saved;
  try { saved = localStorage.getItem('sidebar-last-tab'); } catch (e) { return; }
  if (!saved || VALID_SIDEBAR_PANELS.indexOf(saved) === -1) return;
  var targetTab = Array.from(document.querySelectorAll('.tab-btn'))
    .find(function (t) { return t.dataset.panel === saved; });
  if (!targetTab) return;
  if (targetTab.classList.contains('active')) return;  // idempotent

  // NEW: preserve form focus + selection across the synthetic click.
  var prevFocus = document.activeElement;
  var prevSelectionStart = null, prevSelectionEnd = null;
  var prevSelectionDirection = null;
  var hadEditableFocus = false;
  if (prevFocus && (prevFocus.tagName === 'INPUT' || prevFocus.tagName === 'TEXTAREA')) {
    try {
      hadEditableFocus = true;
      prevSelectionStart = prevFocus.selectionStart;
      prevSelectionEnd = prevFocus.selectionEnd;
      prevSelectionDirection = prevFocus.selectionDirection;
    } catch (e) { /* selection unavailable for some input types — noop */ }
  }

  targetTab.click();

  // Restore focus + selection if it was editable.
  if (hadEditableFocus && prevFocus && document.body.contains(prevFocus)) {
    try {
      prevFocus.focus();
      if (prevSelectionStart !== null && prevSelectionEnd !== null) {
        prevFocus.setSelectionRange(prevSelectionStart, prevSelectionEnd, prevSelectionDirection || 'none');
      }
    } catch (e) { /* defensive — focus/selection restore failed, accept degradation */ }
  }
}
```

Why `.click()` not direct class manipulation: the existing `initSidebarTabs` click handler is the source of truth for tab+panel `.active` toggles AND the localStorage write AND admin-polling start (via `initAdmin`'s click listener). Bypassing the click would split that authority and require keeping multiple paths in sync. The synthetic click is a stable contract.

### 4.3 Admin-polling restart on BFCache restore (G5)

The synthetic `.click()` already triggers `initAdmin`'s click listener at [app.js:3725-3729](../../../frontend/app.js#L3725-L3729), which calls `fetchAdminStatus()` + `setInterval(fetchAdminStatus, ADMIN_REFRESH_MS)`. So the restoration path naturally restarts polling — no extra code needed.

But there's a latent state bug: on a BFCache restore, the previous `adminTimer` `setInterval` ID may still be set in JS state (BFCache preserves JS state) AND the timer itself may have been killed by iOS. In that case, `clearInterval(adminTimer)` at [app.js:3727](../../../frontend/app.js#L3727) is a no-op (the ID is stale), and a new timer is set. Net: polling restarts correctly; the only minor cost is a stale ID is overwritten. **No additional code needed.**

For the case where the saved tab is NOT Admin (most common), no polling concern arises.

### 4.4 Tests (structural)

Extend [tests/test_frontend_voice_picker.py](../../../tests/test_frontend_voice_picker.py) with:

```python
def test_sidebar_tab_restore_covers_pageshow_and_visibilitychange():
    """f1687df closed the DOMContentLoaded path. This test ensures the
    restoration also fires on iOS Safari BFCache restores (pageshow regardless
    of e.persisted) AND on app-switch return paths that fire visibilitychange
    without pageshow.
    """
    src = (REPO_ROOT / "frontend/app.js").read_text()
    # Original DOMContentLoaded restoration path must still exist
    assert "DOMContentLoaded" in src
    assert "restoreLastSidebarTab()" in src
    # NEW: pageshow listener (covers BFCache + tab-discard restores)
    pageshow_match = re.search(
        r"addEventListener\s*\(\s*['\"]pageshow['\"]\s*,\s*function\s*\([^)]*\)\s*\{[^}]{0,400}restoreLastSidebarTab\s*\(",
        src,
    )
    assert pageshow_match is not None, (
        "Missing pageshow listener calling restoreLastSidebarTab. iOS Safari "
        "BFCache restores fire pageshow but NOT DOMContentLoaded; without this "
        "listener, sidebar reverts to default Layers tab on every BFCache restore."
    )
    # NEW: visibilitychange listener (covers app-switch returns without pageshow)
    visibility_match = re.search(
        r"addEventListener\s*\(\s*['\"]visibilitychange['\"]\s*,\s*function\s*\(\)\s*\{[^}]{0,400}restoreLastSidebarTab\s*\(",
        src,
    )
    assert visibility_match is not None, (
        "Missing visibilitychange listener calling restoreLastSidebarTab. Some "
        "iOS app-switch returns fire visibilitychange without pageshow; without "
        "this listener, those return paths leave the sidebar on default Layers."
    )

def test_sidebar_tab_restore_preserves_form_focus():
    """When the user was editing #route-start (or any input) at backgrounding
    time and the saved tab is Route, the synthetic .click() inside
    restoreLastSidebarTab must NOT clobber input focus or selection.
    """
    src = (REPO_ROOT / "frontend/app.js").read_text()
    # restoreLastSidebarTab must capture activeElement before click
    capture_match = re.search(
        r"function\s+restoreLastSidebarTab\s*\(\s*\)\s*\{[\s\S]{0,1000}?"
        r"document\.activeElement[\s\S]{0,500}?"
        r"\.click\s*\(\s*\)",
        src,
    )
    assert capture_match is not None, (
        "restoreLastSidebarTab must capture document.activeElement BEFORE "
        "calling targetTab.click(), then restore focus + selection after. "
        "Without this, switching tabs during active form editing clobbers "
        "the user's input focus."
    )
```

No unit-test pathway available — JSDOM doesn't simulate BFCache or iOS lifecycle quirks. The structural-grep test is the project's established rigor for this class of invariant (cf. existing `test_sidebar_tab_persistence_wired`).

## 5. Invariants

- **S1**: `restoreLastSidebarTab()` is idempotent — calling it when the target tab already has `.active` is a no-op. Safe to call from any number of event listeners without side effects.
- **S2**: All restore-triggering listeners fire `restoreLastSidebarTab()` unconditionally (no `if (e.persisted)` filter on pageshow). The function's internal early-return handles the no-op case correctly.
- **S3**: When the active focused element at restore time is an `<input>` or `<textarea>`, focus and selection are captured before the synthetic click and restored after.
- **S4**: When the saved tab is Admin, the synthetic click triggers `initAdmin`'s click handler which restarts the `setInterval(fetchAdminStatus, ...)` polling. No additional code path required.
- **S5**: On true first-loads (parse from network), `DOMContentLoaded` continues to fire and the existing path runs. The `pageshow` listener also fires on first-load but the `document.readyState === 'loading'` guard prevents a duplicate run before `DOMContentLoaded` completes.

## 6. Ship gate

Cameron's manual acceptance:

1. **Real-world regression test**: load Geographica on iOS Safari, switch to Route tab, initiate navigation, lock phone for ≥ 2 minutes, return → reopen sidebar → Route tab active with Stop Navigation button visible.
2. **Form-focus preservation**: load Geographica, click Route tab, click into `#route-start` field, type "Vil" (don't submit), background for 30 s, return → input still has focus, selection at end of "Vil", input value preserved.
3. **Admin polling**: switch to Admin tab, observe service status table populates, background for 30 s, return → Admin tab active and table data refreshes within `ADMIN_REFRESH_MS` (no manual reload needed).
4. **Hard-refresh path**: cmd-R / pull-to-refresh from the Route tab → on reload, Route tab is restored (DOMContentLoaded path still works).

Tests on `dev`:

- `python -m pytest tests/test_frontend_voice_picker.py` — both new structural tests pass plus the existing `test_sidebar_tab_persistence_wired`.

## 7. Rollback

Revert the 3-line listener block + the `restoreLastSidebarTab` rewrite. Behavior reverts to `f1687df` state (DOMContentLoaded-only restoration). The localStorage key is unchanged so user-saved tab choices survive the revert.

## 8. Open questions

- **Path 5 (audio-session interruption)**: not covered by `pageshow` or `visibilitychange`. If field-tested as a problem, add `navigator.mediaSession` event listeners. Currently flagged NG4.
- **Race window between `pageshow` and `DOMContentLoaded` on first load**: `document.readyState === 'loading'` guard handles this. Verify by adding a console.log to both paths during dev testing if any doubt.
- **Rapid-fire pageshow/visibilitychange events** (e.g., user toggles app-switcher repeatedly): each call is idempotent, so no functional issue. Performance: each call reads localStorage + walks the .tab-btn NodeList. Negligible cost.
