# Holistic bug hunt — pipeline sticky error state
**Date:** 2026-04-24
**Agent:** manzanita

## Summary of reasoning

The pipeline's multi-state guard is implemented ONLY in the pipeline container
(`scripts/acquire_imagery.py:2229-2244`), not at the `/admin/pipeline/start`
endpoint. The HTTP endpoint already has the information needed to detect the
multi-state case (`_noaa_peak_and_snapshot` at `services/search/main.py:1242`
calls `states_intersecting` and computes `states_list`) but throws that count
away. So every multi-state Start spawns a container that writes
`status=error` and `sys.exit(1)`s a few seconds later, producing the sticky
state file the user is staring at.

From there the "stickiness" reported by the user comes from a cluster of
frontend / UX bugs that **compound** the backend's failure to reject
multi-state bboxes cleanly:

1. The error label (`card-imagery_noaa-completed`) and the state-file error
   field are never cleared by a frontend "try again" action — they only
   disappear after a successful Start writes a new `.pipeline-state.json`
   with `status=running` and no `error` key. So the conspicuous red "NOAA
   NAIP failed — bbox intersects 3 states…" label stays on screen even
   when the user has drawn a new bbox and is in the process of retrying.
2. The NOAA card opens on the **Whole state** tab by default each time,
   even when the user's prior flow was **Custom area**. A user who just
   failed a Custom-area Start and re-expands the card will see the
   Whole-state start button, which will send `state=arizona` (the
   fallback when no catalog is loaded) + the current bbox. Whether that
   "works" or errors is state-dependent but it's not what the user asked
   for.
3. Per-element DOM state on `estBoxCustom` (`_diskBlocked`, the
   `ack-missing` checkbox) is set by `_renderEstimate` and persists
   verbatim until the next Estimate click. Re-drawing a bbox does **not**
   re-run Estimate. So `_diskBlocked=true` or an unchecked ack checkbox
   from a prior estimate can silently block a retry click even though the
   underlying failure (multi-state dispatch) has nothing to do with disk
   or ack. This matches the exact surface the user describes: clicking
   Start "does nothing" (an `alert()` fires, but the error label is still
   on screen — hard to realize the alert is distinct).
4. The `_is_pipeline_container_running` check at `services/search/main.py:1175`
   silently swallows Docker errors and returns `False` on any exception.
   If the Docker socket ever has a transient hiccup the endpoint will
   proceed to `containers.run()` and any name-conflict with a leftover
   `geographica-pipeline` container surfaces as a 500 at L1621 —
   indistinguishable from a backend crash.

These four compound. The user's mental model is "I redrew the bbox, so the
old error is gone," but none of the on-screen error artifacts go away
until the next successful Start, and several latent DOM gates can silently
block the click that would clear them.

## Confirmed bugs

### B1: Multi-state NOAA bbox isn't rejected at `/admin/pipeline/start` — failure happens inside the container instead
- **Location:** `services/search/main.py:1341-1385` (NOAA pre-flight guards in `pipeline_start`) and `scripts/acquire_imagery.py:2229-2244` (downstream guard).
- **What the code does:** `pipeline_start` already calls
  `_noaa_peak_and_snapshot(body)` which internally does
  `states_list = [s for s in intersecting if s in entries]` and throws the
  count away. The endpoint rejects "no catalog" (B1 reviewer fix at L1348)
  and "missing-state without ack" (L1361), but **not** "multi cataloged
  states." It dispatches the container, which immediately calls
  `update_progress(..., status='error', phase='error', error=msg)` and
  `sys.exit(1)`.
- **What it should do:** Detect `len(states_list) > 1` in
  `pipeline_start` before taking the `_pipeline_lock` and return a 409
  with a structured detail (status:`multi_state_unsupported`, the list of
  USPS codes, a message that matches the pipeline's current error text).
  Mirror the shape of the existing `missing_unacknowledged` 409.
- **Impact:** Every multi-state Start poisons `.pipeline-state.json`,
  leaves an exited container around for the next Start to force-remove,
  and gives the user a red "NOAA NAIP failed" card until the next
  successful Start completes. The endpoint has the information to prevent
  all of that with a clean 409.
- **Related bugs:** Directly causes B2 (because the UI treats a
  server-side error as a sticky card label) and compounds with B3/B4
  (which block the retry click that would overwrite the error).

### B2: Pipeline error state is never cleared until the NEXT successful Start — no "dismiss error" affordance
- **Location:** `services/search/main.py:1269-1628` (`pipeline_start`
  write path) and `frontend/config/index.html:2739-2743`
  (`renderGenericProgress` error branch).
- **What the code does:** The state file is only overwritten by (a) a new
  `pipeline_start` call that reaches L1617 `state_file.write_text(...)`,
  or (b) a subsequent `update_progress(...)` from a live pipeline
  container. There is no endpoint that says "clear the error, I
  acknowledge it." Correspondingly, the frontend has no button to
  dismiss the error. The red status label at
  `card-imagery_noaa-completed` (L2742) persists through card
  collapse/expand, page navigation, and browser reload, because the
  JSON file on disk still says `status=error`. It's wiped only when a
  new Start succeeds far enough for `container.run()` + `write_text` to
  land.
- **What it should do:** Either (a) add a `DELETE /admin/pipeline/status?type=imagery`
  or similar "dismiss error" endpoint that the frontend wires to a
  small "Dismiss" button on the error label, or (b) automatically treat
  the error as dismissed on the next card-expand that successfully
  renders fresh state. Users expect a stale error to evaporate on
  acknowledgement. Today it only evaporates on another successful run —
  and B3/B4 below can prevent that run.
- **Impact:** The user stares at a red failure banner that they cannot
  clear via any user-visible action, amplifying the "sticky" perception.

### B3: Stale `estBoxCustom._diskBlocked` silently blocks retry after bbox redraw
- **Location:** `frontend/config/index.html:1700-1710` (flag is set inside
  `_renderEstimate`), `:1820-1826` (Start-custom click handler reads the
  flag).
- **What the code does:** `_renderEstimate` writes
  `estBox._diskBlocked = true` when
  `peak_required_gb > disk_free_gb`. That property lives on the DOM node
  and is only rewritten on the next Estimate click. The Start-custom
  click handler (`:1823`) short-circuits with `alert(...)` if the flag
  is true. There is no listener on `#cfg-bbox` that clears the flag when
  the bbox changes, and no watcher that re-estimates. So a user who
  estimated a huge bbox (peak > free), saw the red "peak working set
  exceeds free disk" message, then shrunk the bbox and clicked Start
  — gets the alert and believes the UI is broken.
- **What it should do:** Either clear `_diskBlocked` on every `#cfg-bbox`
  input event (forcing re-estimate), or replace the DOM-property gate
  with a re-estimate-on-Start guard that computes peak fresh from the
  server. Don't let a ghost of a previous estimate block a current
  click.
- **Impact:** Legitimate retries with smaller bboxes appear broken. The
  user's reported symptom ("clicked Start, nothing happens") matches an
  `alert()` that many users dismiss on reflex without reading —
  especially when a large red error label is already on the card.

### B4: Stale `ack-missing` checkbox persists across bbox changes
- **Location:** `frontend/config/index.html:1666-1676` (checkbox created
  inside `_renderEstimate`), `:1828-1833` (read by Start handler).
- **What the code does:** The ack checkbox is built inside `estBoxCustom`
  the first time Estimate returns with `d.missing.length > 0`. On
  subsequent Estimate calls (same card expansion), `estBox.textContent =
  ''` at L1645 wipes the estimate text but `_renderEstimate` re-inserts
  a fresh checkbox only if `d.missing` is still non-empty. If the new
  estimate has no missing states, no new checkbox is rendered — but the
  OLD checkbox DOM was cleared by the `textContent = ''`, so the
  `querySelector('#card-...-ack-missing')` returns null and the gate
  is permissive. That's fine.
- **The trouble is:** If the user redraws a bbox and clicks Start
  WITHOUT re-Estimating, the Start handler queries `estBoxCustom` for
  the ack checkbox from the PRIOR estimate (which was built for the
  PRIOR bbox's missing list). If that prior estimate showed missing
  states and the user hadn't yet ticked the box, the Start gate fires
  `alert("This bbox intersects non-cataloged state(s)...")` even though
  the CURRENT bbox may have no missing states at all. If the prior
  estimate had NO missing states (common case — all cataloged), no
  checkbox exists, the gate is permissive, and the bbox is sent without
  `acknowledge_missing=true`. Either outcome is incorrect: the gate is
  attached to whatever the previous Estimate showed, not to the bbox
  about to be submitted.
- **What it should do:** Re-Estimate before Start, or require the user
  to re-Estimate whenever `#cfg-bbox` changes (by clearing stale
  Estimate output + disabling Start until a fresh Estimate is on
  screen). Simpler alternative: compute the missing-state check
  server-side on every Start (already done — see L1361) and trust that
  as the source of truth. The frontend ack gate is defense-in-depth but
  it's referencing the wrong bbox.
- **Impact:** Users can be blocked from Start with a misleading alert
  ("non-cataloged state(s)") when their CURRENT bbox has no such issue,
  OR can have a stale `acknowledge_missing=false` sent when it should
  have been true (the server-side gate catches that — a 409 — so no
  data corruption, but the UX is confusing).

### B5: `_is_pipeline_container_running` swallows all Docker exceptions silently
- **Location:** `services/search/main.py:1175-1187`.
- **What the code does:**
  ```python
  try:
      containers = client.containers.list(
          all=False, filters={"name": "geographica-pipeline"}
      )
      return any(c.status == "running" for c in containers)
  except Exception:
      return False
  ```
  ANY Docker API failure (socket hiccup, permission error, daemon
  restart, timeout) is treated as "no pipeline running". The
  `/admin/pipeline/start` L1396 gate uses this as the "is anything
  already running?" check — a False-on-error answer LIES about
  reality, letting a new Start proceed even when a container might
  already be running. If the prior container is still there, the
  subsequent `client.containers.run(name="geographica-pipeline", ...)`
  at L1590 raises a name-conflict error, which surfaces as a 500
  "Failed to start pipeline" at L1621 — indistinguishable from any
  other backend crash.
- **What it should do:** Log the exception (at minimum) and surface
  ambiguity to the caller. A safer default would be to `raise` on
  unexpected exceptions (let the 500 in `pipeline_start` expose the
  underlying Docker error) rather than lie about the state.
- **Impact:** On a transient Docker issue the sticky-error state
  becomes even stickier — the Start 500s, the error label persists,
  and the user has no diagnostic (no mention of the Docker failure).

### B6: Whole-state tab is always active by default; Custom-area users lose their tab context on retry
- **Location:** `frontend/config/index.html:1416-1420` (initial tab
  markup: `class="noaa-tab active" data-tab="whole"`), and the
  tab-switching listener (`:1464-1474`) — no persistence.
- **What the code does:** Every card-expand rebuilds the tab strip with
  "Whole state" marked `active`. If the user fails a Custom-area
  Start, re-expands the card, they see the Whole-state tab first.
  Clicking the Start button there sends `{ state: stateSel.value,
  acknowledge_missing: ... }` — which is a DIFFERENT request shape,
  potentially against a catalog dropdown that hadn't finished loading
  (fallback: `arizona`). The user has to realize they need to click
  "Custom area" tab again.
- **What it should do:** Persist the last-used tab in `sessionStorage`
  and restore on re-expand. Low-risk: the tabs are sibling sections in
  the same card.
- **Impact:** Adds one click per retry cycle, and — more concerning —
  a user who doesn't notice the tab switch could dispatch a
  whole-state Arizona download instead of a custom-bbox retry.

### B7: Non-atomic `state_file.write_text` in `/admin/pipeline/start` races with pipeline `update_progress` writes
- **Location:** `services/search/main.py:1617`.
- **What the code does:** The endpoint writes the initial `status:
  running` via `state_file.write_text(json.dumps(state_data, indent=2))`
  AFTER `client.containers.run(...)` has launched the container at
  L1590. The container runs `run_noaa` which almost-immediately calls
  `update_progress(...)` — a file read-modify-write via tmp + rename
  (`_atomic_write_json` at `scripts/acquire_imagery.py:451`). The two
  writes are ordered but `write_text` truncates and writes in-place;
  it is not atomic vs the concurrent atomic rename.
- **What it should do:** Use the same tmp-plus-rename pattern the
  pipeline uses (there is a `.json.tmp` convention already — see L1802
  in `/cancel`). Order the writes correctly: write the running-state
  file BEFORE calling `container.run()` so the pipeline cannot observe
  a file with stale error keys from a previous run.
- **Impact:** In the failure path described by the runtime evidence,
  the pipeline's merge-read of the state file could observe a partial
  JSON (JSONDecodeError → `existing = {}`), losing all the /start-written
  fields (`container_id`, `started_at`, `type`, `mode`). More relevantly
  for the sticky-error story: if a previous run's `error` key persists
  because `/start`'s write clears it but the pipeline's read races and
  gets an incomplete doc, the next `update_progress` call writes a
  document with no prior context — subsequent `/status` reconciliation
  can then misclassify the run. This is a latent concurrency bug, not
  guaranteed to manifest, but it's a real primary-reason to be careful
  about state-file ownership across two processes.

### B8: `/admin/pipeline/status` reconciliation can't detect the multi-state error case — it treats a clean `status=error` from the script as terminal and does NO cleanup
- **Location:** `services/search/main.py:1669-1714`.
- **What the code does:** Reconciliation only fires when the state says
  `running`/`cancelling` AND the container is dead. A script that
  exits with `status=error` written BEFORE exit is NOT a "crash path"
  — `is_crash_path = status in ("running","cancelling") and not
  container_running` is False. So no last-logs capture, no
  `completed_at` stamp, no duration calculation, no TileServer
  handoff-gate update. The error state is preserved verbatim.
- **What it should do:** Extend the terminal-detection to include
  `status=error` once: stamp `completed_at`, capture last N lines of
  container logs (useful for the user's "why did it fail?" question)
  and idempotently force-remove the exited container so the next Start
  doesn't have to rely on `remove(force=True)` in its happy path.
- **Impact:** Minor on its own, but the missing `completed_at` means
  the frontend's `timeAgo(d.completed_at)` at L2721 returns empty
  string for this error case, so the user sees "NOAA NAIP failed" with
  no time context. Small but compounds the "this error is mysteriously
  permanent" feel.

## Design smells (not bugs, but fragile)

- **State-file invariants are implicit and split between two processes.**
  The search service owns the initial write at `pipeline_start`; the
  pipeline container owns progress updates; the search service owns
  reconciliation (status reads). But there's no documented contract for
  which keys can appear when. E.g., `phase=None` vs `phase="error"` vs
  missing `phase` key; `catalog_snapshot` persistence across runs; `error`
  key clearing semantics. A schema/TypedDict + tests at the schema level
  would catch B7/B8-class issues.

- **`_pipeline_lock` (asyncio.Lock) protects only in-process Python
  coroutines.** It does not protect against (a) CLI-started pipeline
  containers (`geographica-pipeline-run-*`), (b) multiple uvicorn workers
  in the search service, or (c) the pipeline container writing to
  `.pipeline-state.json` concurrently with `/cancel`'s "change running
  to cancelling" write. Today the search service is single-worker so
  (b) is moot, but nothing enforces that. If it ever changes (e.g., in
  development a `--workers 2` flag slips in) the lock silently becomes
  useless.

- **The Start click handler has five nested per-element DOM gates**
  (`_diskBlocked`, `ack-missing`, presence of Estimate, map bbox draw,
  `_anyPipelineRunning` global). Each is defensible in isolation, but
  the aggregate is a combinatorial maze. A cleaner architecture would
  compute a single `canStart` derived state from a central store on
  every bbox/Estimate change, and render the Start button's
  enabled/disabled state + tooltip from that. Today the button is
  always enabled during non-running state and the gates are hidden
  side-effects that fire `alert()` after the click — which is hostile
  UX.

- **The pipeline container is a terminal-run, not a supervised
  subprocess.** The search service starts it and then hopes for the
  best. There is no "container exited within 5 seconds = preflight
  failure, surface via health endpoint" detector. The polling frontend
  is the only thing that eventually notices. A short-lived watcher
  task in the search service that inspects the container's exit code
  within, say, 10 seconds of `containers.run()` and captures its
  `error` for immediate display to the original Start response's UI
  would collapse the B1/B2 feedback loop from "error visible on next
  poll" to "error in the same click".

- **No automatic cleanup of exited pipeline containers.** Today the
  next `/start` call force-removes a leftover `geographica-pipeline`
  container at L1583-1587. That works for "exactly one exited
  container, named `geographica-pipeline`." A name prefix (CLI-started
  `geographica-pipeline-run-*`) is never pruned by any endpoint. Over
  time these accumulate and occupy disk. Not directly related to the
  reported bug but hygienic.

- **The 403 `require_config_source` dependency gates `/start` and
  `/cancel` but NOT `/status`** (L1631 has no dependency). Intentional
  — `/status` needs to be reachable for the public dashboard. But the
  asymmetry means a crafted request to `/status` can bypass the CSRF
  token and scrape pipeline state, which on a public-facing deployment
  is a minor information disclosure (bbox coordinates, error messages
  that may include filesystem paths). Not the reported bug, but worth
  flagging.

## Ruled out

- **`_is_pipeline_container_running` falsely reporting True on an
  exited container.** Docker's `containers.list(all=False, ...)`
  returns only running containers; exited containers are excluded. No
  false-positive on the 409 path at L1396.
- **`state_file.write_text` failing to overwrite the `error` key on
  retry.** `write_text` truncates and rewrites the entire file; the
  new `state_data` dict at L1604-1616 has no `error` key, so the
  resulting JSON has no `error` key. Not a sticky-error source — but
  see B7 for the atomicity concern.
- **`_resolve_or_pin_snapshot` preserving the previous run's snapshot
  pointer across a retry.** The `/start` endpoint's L1617
  `write_text` overwrites the entire state file, so `catalog_snapshot`
  from a prior run is gone before the retry's pipeline reads it. The
  retry pipeline then pins a fresh snapshot. Verified via code trace.
- **The NOAA progress-polling interval leaking across card
  collapse/expand (`_noaaProgressPollId` at L1282-1284).** This was
  "Fix 1" in a prior cycle and is correctly cleared. Not related to
  the sticky error.
- **The ack checkbox on the Whole-state tab leaking into
  Custom-area Start state.** Separate DOM nodes
  (`#card-imagery_noaa-ack-missing` is inside `estBoxWhole` vs
  `estBoxCustom`), queried via `estBox.querySelector`, so no
  cross-contamination. The Custom-tab variant has its own issue (B4).
- **The polling interleaving (older response after newer).** Each
  `fetchAll()` fires seven parallel fetches, each resolves
  independently. In principle an older poll's response could arrive
  after a newer one's. But each status response has a self-describing
  `status` field; an older `status=error` arriving after a newer
  `status=running` would set `_imageryRunning=false` and call
  `renderSourceProgress` to render the error label. The next poll
  corrects it. This would cause a brief flicker at worst, not the
  sustained stickiness reported.
- **`renderGenericProgress` disabling the Start button permanently
  on error.** The NOAA card has no `card-imagery_noaa-start` element
  (only `-start-whole` and `-start-custom`); `document.getElementById`
  returns null; the `if (startBtn)` guards in `renderGenericProgress`
  short-circuit. So the renderer never disables the real buttons.
  This is intentional (the two real buttons are disabled by
  `updatePipelineButtons` based on the `_anyPipelineRunning` flag
  alone). Not a source of stickiness.
