# Sidebar tab restore — implementation plan

**Date:** 2026-04-24
**Spec:** [docs/superpowers/specs/2026-04-24-sidebar-tab-restore-design.md](../specs/2026-04-24-sidebar-tab-restore-design.md)
**Plan author:** manzanita
**Execution protocol:** `superpowers:subagent-driven-development` with two-stage review per task (spec compliance + code quality).
**Branch:** dev (no worktrees per CLAUDE.md ban).
**Field-test gate:** Cameron's iOS Safari acceptance per spec §6 — independent of nav-voice ship gate.

## Scope

Three small code changes + two structural tests, all in two files:

- `frontend/app.js` — add `pageshow` + `visibilitychange` listeners outside the DOMContentLoaded block; rewrite `restoreLastSidebarTab()` to capture and restore form focus + selection across the synthetic click.
- `tests/test_frontend_voice_picker.py` — add `test_sidebar_tab_restore_covers_pageshow_and_visibilitychange` and `test_sidebar_tab_restore_preserves_form_focus`.

The spec is highly prescriptive (provides exact JS code). The implementer's job is mechanical: paste the spec's code at the specified locations, write the structural tests, verify everything passes.

## Existing state

- Commit `f1687df` shipped the localStorage-based persistence + DOMContentLoaded restore.
- `restoreLastSidebarTab()` lives at [frontend/app.js:4105-4118](../../frontend/app.js#L4105-L4118).
- `VALID_SIDEBAR_PANELS` constant exists somewhere in `app.js` (search).
- Existing test `test_sidebar_tab_persistence_wired` lives in [tests/test_frontend_voice_picker.py](../../tests/test_frontend_voice_picker.py) — mirror its structure for the new tests.

## Task 1: TDD red — add the two new structural tests

**Files:** `tests/test_frontend_voice_picker.py`

Add the two tests verbatim from spec §4.4 (lines 172-222 of the spec document). Both are regex-grep structural tests.

**Verification step:**
```bash
python -m pytest tests/test_frontend_voice_picker.py -v 2>&1 | tail -15
```

Expected: the two new tests **fail** (the listeners don't exist yet, the focus-capture pattern doesn't exist yet). The existing tests in the file (especially `test_sidebar_tab_persistence_wired`) should still pass.

**Commit message:**

```
test(frontend): sidebar tab restore — pageshow + visibilitychange + form focus

Two structural tests verifying spec v1 §4.4 invariants:
- pageshow listener calling restoreLastSidebarTab (BFCache + tab-discard
  return paths on iOS Safari)
- visibilitychange listener (app-switch returns without pageshow)
- restoreLastSidebarTab captures document.activeElement BEFORE synthetic
  click (form focus preservation across tab restore)

Tests fail at this commit; implementation lands in next commit.

Agent: manzanita
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

## Task 2: Implementation

**Files:** `frontend/app.js`

Two changes:

### 2a. Add the two listeners outside DOMContentLoaded

Per spec §4.1 (lines 90-111). Add to `frontend/app.js` outside the existing `DOMContentLoaded` block — at script-parse time, so listeners wire up immediately. Best location: near the bottom of the file, immediately above or below the existing `DOMContentLoaded` callback registration, so both lifecycle hooks are visually grouped.

The listeners must:
- Both call `restoreLastSidebarTab()` unconditionally (no `e.persisted` filter).
- Both early-return when `document.readyState === 'loading'` to avoid running before initial wiring is complete.
- The `visibilitychange` listener must early-return when `document.hidden` is true.

```js
window.addEventListener('pageshow', function (e) {
  if (document.readyState === 'loading') return;
  restoreLastSidebarTab();
});

document.addEventListener('visibilitychange', function () {
  if (document.hidden) return;
  if (document.readyState === 'loading') return;
  restoreLastSidebarTab();
});
```

### 2b. Rewrite `restoreLastSidebarTab()` with focus capture + restore

Per spec §4.2 (lines 119-155). Replace the existing function body at `app.js:4105-4118` with the focus-preserving variant. The function must:
- Read localStorage saved tab + validate against whitelist (existing behavior).
- Find the target tab DOM node (existing behavior).
- Early-return if target tab already has `.active` class (existing behavior — idempotent).
- **NEW:** Capture `document.activeElement` if it's an INPUT or TEXTAREA. Save `selectionStart`, `selectionEnd`, `selectionDirection`.
- Call `targetTab.click()` (existing behavior).
- **NEW:** After the click, if focus was editable AND the previous element is still in the DOM, restore focus + selection range. Wrap selection-restore in `try/catch` (some input types don't support selection APIs).

**Verification step:**
```bash
python -m pytest tests/test_frontend_voice_picker.py -v 2>&1 | tail -15
node --test --test-force-exit frontend/tests/engine/ 2>&1 | tail -5
```

Expected: both new tests now pass. Existing `test_sidebar_tab_persistence_wired` still passes. Engine tests still 80/80 (no engine changes; should not regress).

**Commit message:**

```
feat(sidebar): restore tab on pageshow/visibilitychange + preserve form focus

Per spec v1 §4. iOS Safari does not fire DOMContentLoaded on most return
paths (BFCache, tab-discard, app-switch). This wires pageshow +
visibilitychange listeners that call the existing restoreLastSidebarTab
helper unconditionally — function is idempotent (early-returns when target
tab already active), so unconditional invocation is safe.

Also rewrites restoreLastSidebarTab to capture document.activeElement
BEFORE the synthetic targetTab.click() and restore focus + selection
afterward. Without this, switching tabs during active form editing
(e.g., typing in #route-start) clobbers input focus and selection.

Admin-polling restart on the saved-tab=Admin path is handled implicitly:
the synthetic click triggers initAdmin's click listener which calls
fetchAdminStatus + setInterval (per spec §4.3 — no extra code needed).

Closes Issue 3 of the 2026-04-24 nav-voice TTM follow-up cycle (split
into a separate spec per Codex F5.1 + R4 F4.13 — orthogonal risk surface
to Issues 1+2).

Agent: manzanita
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

## Task 3: Verify + ship gate

No code changes. Verify the full state:

1. `python -m pytest tests/test_frontend_voice_picker.py -v 2>&1 | tail -20` — all sidebar tests pass.
2. `python -m pytest tests/ services/search/tests/ --tb=no -q 2>&1 | tail -10` — no new regressions beyond known pre-existing failures (test_pipeline_status_m2m ×2, test_wake_lock_static, test_bootstrap_messaging, test_setup_main test-isolation false-failures).
3. `node --test --test-force-exit frontend/tests/engine/ 2>&1 | tail -5` — 80/80 still pass.
4. Read spec §6 ship-gate criteria. Confirm each is testable on Cameron's iOS device:
   - Route-tab restore after long background (target use case).
   - Form-focus preservation when editing #route-start before background.
   - Admin polling restart after BFCache restore on Admin tab.
   - Hard-refresh path still works (DOMContentLoaded preserved).
5. Update [dev/implementation-log.md](../../dev/implementation-log.md) with a 2026-04-24 entry for this work (separate from the nav-voice entry already there — different feature, different ship gate).

**Commit message** (impl log only):

```
docs(sidebar): impl log entry — sidebar tab restore for iOS BFCache

Companion to feat(sidebar) commit. Captures spec rationale, the four
adversarial findings the spec absorbed (R1 F1.7 admin polling dead,
Codex F5.2 BFCache is one path of many, Codex F5.7 form focus clobber,
plus Codex F5.1 + R4 F4.13 driving the issue split from nav-voice).

Agent: manzanita
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

## Final review

After Task 3, dispatch one code-reviewer (Sonnet — small surface area) for the full sidebar diff. Check:
- The listeners are wired outside DOMContentLoaded so they survive script-parse-time race.
- `restoreLastSidebarTab` is fully idempotent — focus-capture happens BEFORE the early-return-if-active check would matter? Actually the early-return happens BEFORE focus capture in the spec code; verify the implementer matched that ordering (otherwise focus state is captured then discarded, wasting a tick of work). Spec §4.2 line 127 places the early-return BEFORE the focus capture — implementer must match.
- The selection-restore is wrapped in try/catch (some input types throw on `setSelectionRange`).
- The two listener guard conditions (`document.readyState === 'loading'` and `document.hidden`) are in the right places.
- ES5 syntax preserved (no arrow fn / template literal in the new app.js code).
- No `// NEW:` annotations.

If clean, halt the cycle. Cameron field-tests via spec §6.

## What NOT to do

- Do NOT change the localStorage key (`sidebar-last-tab`) — preserves user state across the upgrade.
- Do NOT add a `if (e.persisted)` filter on the pageshow listener — both BFCache and tab-discard paths matter.
- Do NOT remove the existing DOMContentLoaded restoration path — first-loads need it.
- Do NOT add `navigator.userAgent` Safari sniffing (NG5).
- Do NOT touch `frontend/navigation.js` — out of scope, separate ship gate.
