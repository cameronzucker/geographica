# Sidebar mobile reset — Multipass hunter report

**Agent:** manzanita
**Date:** 2026-04-25
**Scope:** `frontend/app.js` sidebar wiring (initSidebarTabs ~1155, setSidebarOpen ~1179,
restoreLastSidebarTab ~4120, VALID_SIDEBAR_PANELS ~4118, pageshow/visibilitychange ~4294),
`frontend/index.html` tab DOM (~46), `frontend/style.css` sidebar/tab rules, commits
`9647efc` / `0257bca` / `46bd08c`, spec `docs/superpowers/specs/2026-04-24-sidebar-tab-restore-design.md`.

---

## Pass 1: Contract violations

### `initSidebarTabs()` — click handler promise

The click handler (lines 1159-1170) promises: tab click → remove `.active` from all
tabs/panels → add `.active` to clicked tab + its panel → write `localStorage`.  All four
steps execute unconditionally (the null-guard `if (!panelEl) return` on line 1163 fires
before any mutation). Contract is kept.

### `setSidebarOpen(open)` — promise

Promises: toggle `.open` on sidebar/overlay, adjust map padding, dispatch
`geographica:sidebar` custom event. Implementation at lines 1179-1196 keeps all four
promises. The function makes **no promise about tab state** and correctly does not touch
`.tab-btn.active` or `.panel.active`. Contract is kept.

### `restoreLastSidebarTab()` — promise

Promises: if a saved panel ID exists in localStorage AND is in `VALID_SIDEBAR_PANELS`,
synthetic `.click()` the matching `.tab-btn` to activate it.

**Contract violation (F1):** The function has an idempotent guard at line 4129:
```
if (targetTab.classList.contains('active')) return;
```
This guard is correct for the "already on the right tab" case. However, the **Admin
polling restart sub-contract** is silently broken. When Admin is the saved tab and the
page returns from BFCache (DOM fully preserved, Admin tab still `.active`), the idempotent
guard fires an early return **before** `targetTab.click()` is ever called. The Admin
polling `setInterval` — which iOS kills during background — is never restarted. The
spec §4.3 and the implementation-log both claim "Admin polling restart is implicit, no
extra code — the synthetic click path naturally re-invokes it." That claim is only true
when the tab is **not** already `.active` on restore. On BFCache returns (the most common
path), the tab IS already `.active`, so the click never fires, and the admin timer is
permanently dead until the user manually taps another tab then taps Admin again.

### `pageshow`/`visibilitychange` listeners — promise

Both promise to call `restoreLastSidebarTab()` after DOM is ready. The
`document.readyState === 'loading'` guard is present on both. Both promises are structurally
kept. However, see Pass 3 for a dead-guard observation.

---

## Pass 2: Cross-sibling deviations

### Sibling pattern: "when the page returns to a visible, ready state, restore the correct tab"

Three paths trigger this restoration:
1. `DOMContentLoaded` at line 4155 → calls `restoreLastSidebarTab()` (line 4167)
2. `pageshow` at line 4294 → calls `restoreLastSidebarTab()` (line 4298)
3. `visibilitychange` at line 4301 → calls `restoreLastSidebarTab()` (line 4304)

**Deviation (F2):** A fourth path exists — the user tapping the hamburger button to reopen
the sidebar after any return (Scenario A). `setSidebarOpen(true)` at line 1179 does **not**
call `restoreLastSidebarTab()`. For **pure Scenario A** (no page-lifecycle event, no DOM
reset), this is not a functional gap: `setSidebarOpen` only manipulates the `.open` CSS
class and does not touch `.active` on tabs, so the DOM tab state is already correct when
the sidebar slides in. However, for the **hybrid scenario** (BFCache return where iOS
Safari resets DOM class attributes before firing `pageshow`, a non-standard but observed
behavior on some iOS/iPadOS builds), the restoration via `pageshow` would activate the
correct tab in the closed sidebar, but if the user had backgrounded with the sidebar
**open** and returns to find it still open (BFCache preserved `.open` class), the
`pageshow` restoration correctly handles it. The gap is real but only bites if iOS resets
DOM class attributes without triggering a standard lifecycle event — unconfirmed from code
analysis alone.

**Cross-check:** `pageshow` and `visibilitychange` both call `restoreLastSidebarTab()` when
the page becomes visible. `setSidebarOpen(true)` does not. If the fix is intended to cover
"any time the user can see the sidebar content," the hamburger-open path is the one
unguarded sibling.

---

## Pass 3: Failure modes

### Dead guard: `readyState === 'loading'` on `pageshow` listener

**Location:** `frontend/app.js:4297` and `4303`

The comment at line 4295 says: "Skip if DOM not yet ready (first-load fires pageshow
BEFORE DOMContentLoaded; the DOMContentLoaded path will handle it)." This comment is
**factually incorrect** per the HTML spec: `pageshow` fires on `window` *after* the
`load` event, which is after `DOMContentLoaded`. By the time `pageshow` fires on a normal
first load, `document.readyState` is always `'complete'` — never `'loading'` or even
`'interactive'`. The guard `if (document.readyState === 'loading') return` is therefore
**dead code** for the `pageshow` listener. It will never trigger. The guard is also dead
for the `visibilitychange` listener (line 4303): `visibilitychange` fires while the page
is fully loaded and rendered.

Consequence: on first load, `pageshow` fires at `readyState='complete'`, the guard passes
(does not return), and `restoreLastSidebarTab()` runs a second time. The idempotent guard
at line 4129 catches this (the tab just activated by `DOMContentLoaded` already has
`.active`) and returns early. No double-click fires. **The behavior is correct despite the
wrong guard logic**, because the idempotent guard does the actual protection. The dead
`readyState` guard is a correctness non-issue but creates misleading documentation about
when `pageshow` fires.

### localStorage unavailability (iOS private browsing)

The `try/catch` at line 4122 handles `localStorage.getItem` throwing. If localStorage is
unavailable, `return` is called. The tab stays on the HTML default (Layers). This is
correct graceful degradation — Cameron is unlikely in private mode during navigation.

### `targetTab` not found in DOM

Line 4128: `if (!targetTab) return`. This guards correctly against a saved value that has
no matching button (e.g., `measure-panel` was added after the user's last localStorage
write before the VALID_SIDEBAR_PANELS whitelist was updated). No bug.

### `selectionStart`/`selectionEnd` throwing for non-text inputs

The `try/catch` at lines 4135-4140 handles this. If `selectionStart` throws (e.g.,
`input[type=number]`), `hadFocus` is `true` but `prevStart` remains `null`. After the
click, focus is restored (line 4147) but `setSelectionRange` is skipped (line 4148 guard:
`prevStart !== null`). Graceful degradation. No bug.

---

## Pass 4: Concurrency / state machine / ordering

### VALID_SIDEBAR_PANELS hoisting — false positive from task brief

`VALID_SIDEBAR_PANELS` is declared `var` at line 4118, inside the IIFE. `var` declarations
are hoisted to the top of the IIFE with value `undefined`. **However**, all callers of
`restoreLastSidebarTab()` are async event handlers (`DOMContentLoaded`, `pageshow`,
`visibilitychange`) registered AFTER the IIFE has fully executed. By the time any handler
fires, line 4118 has already assigned the array. The hoisting concern is a **false
positive** — `var` hoisting is only a risk for synchronous early reads during script
evaluation, not for async callbacks. `VALID_SIDEBAR_PANELS` always has its array value
when `restoreLastSidebarTab()` runs.

### Idempotent guard interaction with Admin polling state machine (F1 confirmed)

The state machine for Admin polling has three states: RUNNING (setInterval active),
DEAD (interval killed by iOS background), NEVER_STARTED (cold load, Admin not opened).

On BFCache return with Admin as the saved-and-active tab:
- iOS kills timer-based callbacks during background → adminTimer interval is DEAD
- BFCache preserves DOM: Admin tab has `.active`, `adminTimer` variable may still hold
  the old interval ID (now defunct) or was cleared if iOS zeroed it
- `pageshow` fires → `restoreLastSidebarTab` → Admin btn has `.active` → **idempotent
  early return** → no `targetTab.click()` → `initAdmin`'s click listener never fires →
  `setInterval(fetchAdminStatus, ADMIN_REFRESH_MS)` never called → Admin polling stays DEAD

The Admin panel silently shows stale data from before the user backgrounded the app. The
user would need to manually tap another tab and then tap Admin again to restart polling.
This contradicts spec §4.3's guarantee.

**Fix direction:** Before the idempotent early return, check if the restored tab is the
Admin panel and separately restart the polling interval. Or: remove the idempotent guard
for BFCache returns (conditional on `e.persisted`) and always fire the synthetic click on
BFCache paths, accepting that the visual tab flicker (deactivate+reactivate) is
imperceptible.

### DOMContentLoaded + pageshow double-call on first load

`DOMContentLoaded` calls `restoreLastSidebarTab()` (line 4167). `pageshow` then fires
(readyState `'complete'`) and calls it again (line 4298). The second call hits the
idempotent guard and returns. No double-click, no state corruption. Safe.

### Click handler snapshot vs. live NodeList

`tabs` and `panels` at lines 1156-1157 are `querySelectorAll` results — **static
NodeLists** (snapshot at `DOMContentLoaded` time). No new `.tab-btn` or `.panel` elements
are added dynamically, so the snapshot remains complete. No concurrency issue.

---

## Pass 5: Error propagation

### Exceptions inside `restoreLastSidebarTab`

The function has no outer `try/catch`. If `targetTab.click()` throws (possible if an
event listener wired in `initAdmin` or `initSidebarTabs` throws), the exception propagates
up to the `pageshow`/`visibilitychange` event listener, which also has no `try/catch`.
The exception would surface in the browser console as an unhandled event-listener error.
In practice, the click handlers are simple (classList + localStorage + setInterval) and
unlikely to throw. But if `initAdmin`'s `clearInterval(adminTimer)` or `setInterval`
throws (shouldn't), the `.active` class would be set correctly (line 1166 fires before any
admin polling code in the handler), so the tab visual state would be correct even if the
error propagates. No silent data loss. Acceptable risk.

### `prevFocus.focus()` throwing after synthetic click

Line 4147: `prevFocus.focus()` inside a `try/catch`. Any exception during focus restoration
is silently swallowed (`/* defensive — accept degradation */`). The comment documents this
choice. The synthetic click at line 4142 has already completed and the tab is visually
activated. Focus degradation does not affect the tab restoration. No state corruption.

### `geographica:sidebar` custom event dispatch

`setSidebarOpen` dispatches `geographica:sidebar` at line 1193. Only `voice-picker.js:449`
listens. Its handler calls `onSidebarClose()` when `e.detail.open === false`. No throw
path observed. No propagation concern.

---

## Consolidated findings

### F1 — Admin polling permanently dead after BFCache return on Admin tab

**Pass:** Pass 1 (contract violation) + Pass 4 (state machine ordering)
**Location:** `frontend/app.js:4129` (idempotent guard) + `frontend/app.js:3740-3744` (admin polling start)
**Scenario:** B (app background/foreground via BFCache)
**What's wrong:** When the Admin tab is saved in localStorage AND is currently `.active`
in the DOM (which is true on any BFCache return, since BFCache preserves DOM), the
idempotent guard at line 4129 fires an early return before `targetTab.click()` is ever
reached. The `initAdmin` click handler (which calls `clearInterval` + `setInterval` to
restart the polling loop) never fires. iOS kills timer callbacks during background, so the
admin timer is dead. The Admin panel displays permanently stale service/data-task status
until the user manually taps away and taps Admin again.

The spec §4.3 explicitly claims: "Admin polling restart on the Admin tab BFCache path is
handled implicitly: the synthetic click fires initAdmin's click listener which restarts
setInterval." This claim is only true when the target tab does NOT already have `.active`
— i.e., on tab-discard/full-reload paths where the HTML default (Layers `.active`) differs
from the saved Admin tab. On BFCache paths (where DOM is preserved and Admin stays
`.active`), the implicit restart never happens.

**Why this matches Cameron's signature:** Cameron accesses Admin during setup and
troubleshooting sessions. If he backgrounds the app while on Admin, returns via BFCache,
and then checks Admin again, he sees stale service status. He may interpret this as an
admin endpoint bug rather than a tab-restore bug. Not the "reverts to Layers" symptom but
a real regression introduced by the idempotent guard.

**Repro:**
1. Open Admin tab in Geographica
2. Observe polling data refreshing every 30s
3. Background iOS Safari (switch to another app) for ≥ 30s
4. Return to Safari (BFCache restore — no full reload)
5. Admin tab still visually shown (correct)
6. Wait 60s — observe Admin panel data does NOT refresh
7. Tap Layers tab, then tap Admin tab → polling resumes

**Confidence:** High — provable from code path without device testing.

---

### F2 — setSidebarOpen(true) never calls restoreLastSidebarTab — Scenario A gap

**Pass:** Pass 2 (cross-sibling deviation)
**Location:** `frontend/app.js:1179-1196` (setSidebarOpen body)
**Scenario:** A (in-page sidebar toggle, no lifecycle event)
**What's wrong:** `pageshow`, `visibilitychange`, and `DOMContentLoaded` all call
`restoreLastSidebarTab()` when the page (re)gains visibility. The hamburger-open path
(`setSidebarOpen(true)`) does not. For **pure Scenario A** (no page lifecycle, DOM fully
preserved), this is not a functional gap: `setSidebarOpen` does not touch `.active` on
tabs/panels, so the DOM tab state is correct before and after the open. The sidebar opens
showing whatever tab was last active. No revert occurs.

The gap becomes real only under a platform-specific hypothesis: if iOS Safari resets DOM
class attributes (stripping dynamically-added `.active`) between the last page-active
period and the user tapping the hamburger, without firing any `pageshow` or
`visibilitychange` event. This is not a documented iOS behavior and has not been
independently confirmed. If it does occur, opening the sidebar via hamburger would show
the HTML default (Layers) even though `pageshow` had already fired and `restoreLastSidebarTab`
had run moments earlier (with idempotent early return, since the DOM incorrectly showed the
saved tab's button as `.active` before the reset).

**Why this matches Cameron's signature:** If the bug is Scenario A, the symptom is
exactly "I close the sidebar, reopen it, and it shows Layers." But based on code analysis,
pure Scenario A cannot cause a DOM class reset through any path in the app's own code.
This finding is flagged as medium-confidence because iOS Safari DOM behavior under
backgrounding is not fully observable from source analysis alone.

**Repro (if platform hypothesis is confirmed):**
1. On iOS Safari, open Geographica fresh
2. Tap Route tab
3. Tap hamburger to close sidebar
4. Tap hamburger to reopen sidebar
5. If sidebar shows Layers instead of Route, Scenario A is real; setSidebarOpen
   needs to call restoreLastSidebarTab()

**Confidence:** Medium — the code-level gap is real; whether the platform surfaces it
is unconfirmed without device testing.

---

### F3 — Dead readyState guard + incorrect comment on pageshow listener

**Pass:** Pass 3 (failure modes)
**Location:** `frontend/app.js:4295-4297` (pageshow listener comment + guard)
**Scenario:** Neither A nor B — this is a documentation/dead-code issue, not a user-facing bug
**What's wrong:** The comment at line 4295 states "first-load fires pageshow BEFORE
DOMContentLoaded." This is incorrect. Per the HTML spec, `pageshow` fires *after* the
`load` event, which fires after `DOMContentLoaded`. On a first load, by the time `pageshow`
fires, `document.readyState` is always `'complete'`. The guard `if (document.readyState ===
'loading') return` will therefore never trigger on the `pageshow` path. The guard is dead
code. The behavior is correct anyway (the idempotent guard at line 4129 prevents the
double-click), but a future developer reading the comment might add logic that depends on
the (false) assumption that `pageshow` fires before `DOMContentLoaded`.

**Why this matches Cameron's signature:** Not directly — this is a documentation error,
not the "reverts to Layers" symptom. It does not block Cameron's field test. Flagged
because incorrect comments about event ordering can lead to future bugs.

**Repro:** Not applicable (dead code, no user-facing impact).

**Confidence:** High (incorrect per HTML spec, dead code path) — but not a correctness bug.

---

## Summary verdict on the shipped fix

The new fix (commit `0257bca`) **correctly solves the "reverts to Layers" bug for all
known iOS Safari return paths** (BFCache, tab-discard, app-switch via visibilitychange).
The implementation is structurally sound:

- `pageshow` + `visibilitychange` cover the paths that `DOMContentLoaded` misses.
- The idempotent guard prevents double-clicks and infinite loops.
- The `var VALID_SIDEBAR_PANELS` hoisting concern (raised in the task brief as a potential
  `TypeError`) is a **false positive** — by the time any event callback fires, the IIFE
  has fully executed and `VALID_SIDEBAR_PANELS` holds its array value. The concern only
  applies to synchronous calls during IIFE execution, which never occur for this function.
- The concern about `pageshow` firing at `readyState='interactive'` (also from the task
  brief) is **also a false positive** — `pageshow` fires after `load`, always at
  `readyState='complete'`.

**The one confirmed bug (F1)** is Admin polling dead on BFCache return — a side-effect of
the idempotent guard that the spec failed to account for. **F2** is a plausible gap for
Scenario A but requires device testing to confirm whether iOS Safari actually exhibits the
DOM-reset behavior that would trigger it. **F3** is a documentation error only.

Cameron's field test should proceed. If the "reverts to Layers" bug persists after
testing, the likeliest residual cause is **F2** (some platform-specific DOM class reset
that the idempotent guard mishandles), and the fix would be to add a
`restoreLastSidebarTab()` call inside `setSidebarOpen(open)` at the start of the `if (open)`
branch.
