# NOAA catalog refresh — async dispatch + progress UX

**Status:** v1 (pre-adversarial-review)
**Author:** Agent `cairn`, 2026-04-20
**Supersedes:** N/A (builds on shipped Tasks 22, 31 of the NOAA CONUS expansion)

## Problem

Three concrete failures surfaced on the first real user attempt to refresh the NOAA catalog via the admin UI:

1. **`POST /admin/pipeline/noaa/refresh` is synchronous and long-running.** `refresh_catalog()` walks Azure's blob container and downloads ~100–200 tile-index zips sequentially, taking 10–30 minutes on a Pi on a fresh machine. nginx's default `proxy_read_timeout` is 60s, so the browser receives a **504 Gateway Time-out HTML page** long before the refresh finishes. The frontend's `JSON.parse(response)` throws `SyntaxError: unexpected character at line 1 column 1 of the JSON data`. The refresh actually keeps running server-side but the user has no way to know.

2. **No progress reporting.** Even if the HTTP round-trip succeeded, the UI shows only "Refreshing…" for 10–30 minutes. Users with no mental model of Azure listing + per-state shapefile parsing have no idea whether the app is working or hung.

3. **Discoverability is backwards.** The "Refresh catalog now" button lives inside a collapsible panel labeled *Catalog refresh history*. On first load the state dropdown shows only "Arizona" (the CI baseline). A user looking for "how do I add more states?" will not open the history panel — history ≠ a tool for populating data. The primary affordance for expanding the catalog is buried one interaction deep under a non-matching label.

These are all consequences of a single design gap: **the refresh operation was modeled as a single HTTP request rather than as a long-running job with a polling contract.** Every UX problem follows from that.

## Goals

- Users discover the path to populate the state dropdown on first load without guessing.
- Users understand up front that a refresh is a multi-minute operation and consent to it.
- Users see continuous, specific progress during the refresh (current state, elapsed, ETA).
- Users can cancel cleanly mid-refresh and see the system return to a known-good state.
- The refresh itself never leaves the server in a state where the UI says one thing and reality is another.
- No change to the actual refresh algorithm — the work `refresh_catalog()` does is correct as of commit `4ffd658` + `1910e15`; only the dispatch, progress reporting, and UI shell change.

## Non-goals

- Stranded-pipeline-state class-of-bug fix (separate spec; applies to all pipelines, not just refresh). This spec WILL produce a `progress.json` file that's itself a candidate for the same class of bug; the file-lock invariants are documented here but the general fix is separately tracked.
- Parallelizing the Azure fetches. Sequential is fine; 10–30 min with good progress is acceptable UX.
- Caching to make subsequent refreshes faster (already partially covered by `fetch_tile_count`'s SHA-keyed cache).
- Multi-user safety. Single-admin assumption holds — the lockfile already enforces one-at-a-time refresh.

## Architecture

### Current (synchronous)

```
Browser ─POST /refresh──▶ Search service ─refresh_catalog()──▶ Azure listing ──▶ ~100 HEAD+GET+ogr2ogr
                             │                                                      │
                             │                                                      ▼
                             │                                              (10–30 min of work)
                             │                                                      │
                             ◀──────────────── response JSON ────────────────────┘
   [nginx closes at 60s]
   [browser sees 504 HTML]
```

### Target (async-dispatched + polled)

```
Browser ─POST /refresh──▶ Search service ─acquire lock, init progress.json, asyncio.create_task()
                             │
                             ◀── 202 Accepted + {progress_url, estimated_minutes}
                                 (returns in <1s)

Background task ──┬── refresh_catalog(progress_cb=update_progress)
                  │       │
                  │       ├── each state processed → write to progress.json
                  │       ├── between states: check cancel_requested flag
                  │       └── on exit (success/error/cancelled):
                  │           write terminal progress.json, release lock
                  │
Browser ── GET /refresh/progress (every 2s) ──▶ reads progress.json
                  │
Browser ── POST /refresh/cancel ──▶ sets cancel_requested=true in progress.json
```

### Lifecycle

```
lockfile absent     ──POST /refresh──▶  lockfile created, progress.json created
lockfile present    ──POST /refresh──▶  409 locked (existing behavior)
pipeline running    ──POST /refresh──▶  409 blocked_by_pipeline (existing behavior)

progress.json running  ──bg task completes──▶  progress.json status=done + terminal result
progress.json running  ──POST /cancel──▶  progress.json cancel_requested=true
progress.json running  ──bg task reads cancel_requested next iteration──▶  status=done, result.status=cancelled

Container restart during refresh:
  lockfile persists (PID of dead uvicorn), progress.json persists with status=running
  → out-of-scope for this spec (stranded-state class-of-bug); for now, document the manual recovery:
     rm /data/noaa_catalog_refresh.lock /data/noaa_catalog_refresh.progress.json
  → Phase 3 Task 6 adds a detection heuristic (progress.last_updated > 10 min stale ⇒ offer cleanup).
```

## API contract

### `POST /admin/pipeline/noaa/refresh`

**Request:** no body.

**Response (202 Accepted, refresh started):**
```json
{
  "status": "started",
  "progress_url": "/admin/pipeline/noaa/refresh/progress",
  "started_at": "2026-04-20T21:30:00Z",
  "estimated_minutes": [10, 30]
}
```

**Response (409 Conflict, already running):**
```json
{
  "detail": {
    "status": "locked",
    "lock_holder_pid": 1,
    "progress_url": "/admin/pipeline/noaa/refresh/progress"
  }
}
```

**Response (409 Conflict, pipeline running):**
```json
{
  "detail": {
    "status": "blocked_by_pipeline",
    "blocked_by_pipeline": "/data/<state-file>.pipeline-state.json"
  }
}
```

**Response (503 Service Unavailable, deps missing):** unchanged.

### `GET /admin/pipeline/noaa/refresh/progress`

**Response (200, idle):**
```json
{ "status": "idle" }
```

**Response (200, running):**
```json
{
  "status": "running",
  "phase": "fetching_tile_indexes",
  "states_processed": 79,
  "states_total": 147,
  "percent": 53.7,
  "current_slug": "georgia-us",
  "started_at": "2026-04-20T21:30:00Z",
  "last_updated": "2026-04-20T21:41:23Z",
  "rate_per_sec": 0.12,
  "eta_seconds": 567,
  "cancel_requested": false,
  "validation_issue_count": 3
}
```

Phases: `listing` (Azure container enumeration) → `fetching_tile_indexes` (HEAD + download + ogr2ogr per candidate) → `writing_snapshot` (atomic write + symlink swap).

**Response (200, done):**
```json
{
  "status": "done",
  "started_at": "2026-04-20T21:30:00Z",
  "ended_at": "2026-04-20T21:54:12Z",
  "result": {
    "status": "ok",
    "snapshot_path": "/data/noaa_catalog_snapshots/20260420T215412Z.json",
    "log_entry": { "ts": "...", "state_count": 49, "added": [...], "removed": [...], "validation_issues": [...] }
  }
}
```

Terminal result statuses: `ok`, `truncated`, `invalid_parse`, `cancelled`, `error`. The `result` object mirrors what `refresh_catalog()` returns today (backward-compatible for the refresh-log panel).

### `POST /admin/pipeline/noaa/refresh/cancel`

**Response (200, cancellation requested):**
```json
{
  "status": "cancellation_requested",
  "message": "The refresh will stop at the next state boundary (within ~10s)."
}
```

**Response (404, no running refresh):**
```json
{ "detail": "No refresh in progress" }
```

## Progress-state persistence

File: `/data/noaa_catalog_refresh.progress.json`

**Invariants:**
- Atomic write (`write to tempfile + os.rename`) so readers never see a partial file.
- Created when `POST /refresh` acquires the lock; deleted OR transitioned to `status: done` when the task finishes.
- `cancel_requested: true` can be set by the cancel endpoint; the background task polls it between states and at the start of each Azure HTTP request.
- Terminal states MUST include `ended_at`.
- `last_updated` is refreshed on every write so staleness-detection heuristics work.

## Frontend UX

### Current card body flow

```
NOAA NAIP aerial imagery
├── Whole state (active)
│   ├── State: [Arizona ▾]   ← only 1 option on first load
│   ├── [Estimate]  [Download]
├── Custom area
└── ▸ Catalog refresh history   ← ONLY path to refresh, named wrong
    ├── [Refresh catalog now]   ← hidden primary CTA
    └── (empty log entries)
```

### Target card body flow

```
NOAA NAIP aerial imagery
│
├── ⚠ Only 1 of ~49 states cataloged.  [Refresh catalog]   ← NEW empty-state banner
│      Scans NOAA's Azure blob listing (~10–30 min). Runs in background.
│
├── Whole state (active)
│   ├── State: [Arizona ▾]
│   ├── [Estimate]  [Download]
├── Custom area
└── ▸ Catalog refresh history          ← still available for audit trail only
    └── (log entries)
```

The empty-state banner ONLY renders when `catalog.entries` returned from `GET /admin/pipeline/noaa/catalog` has ≤1 entry. Once the catalog is populated, the banner collapses to a small `[Refresh]` button next to the dropdown as a secondary action (still primary-placement, just de-emphasized).

### Confirm-duration dialog

Triggered by clicking the Refresh button:

> **Refresh NOAA catalog?**
>
> This scans NOAA's Azure blob storage for every NAIP state-year directory, downloading each tile index to count its features. First-time runs take 10–30 minutes depending on your connection. Subsequent refreshes are faster (only changed states pay the download cost).
>
> You can cancel mid-way. The refresh runs in the background — you don't have to keep this tab open, but the progress bar will only update while it's visible.
>
> [Cancel]  [Start refresh]

### In-progress UI

Replaces the button once refresh is dispatched:

```
┌ Refreshing NOAA catalog ──────────────────────────┐
│                                                   │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░  54% (79 of 147)      │
│                                                   │
│  Current: georgia-us                              │
│  Elapsed: 11 min 23 s · ETA: ~11 min              │
│  Phase: fetching tile indexes                     │
│                                                   │
│                                    [Cancel]       │
└───────────────────────────────────────────────────┘
```

Polls `GET /refresh/progress` every 2 s while `status === "running"`. On each poll, updates the progress bar, counter, current_slug, elapsed, and ETA. Stops polling when `status === "done"`.

### Completion UI

On `status: done`, the in-progress card transitions to a summary banner:

- `result.status === "ok"`: green banner "Catalog refreshed — 49 states now available. [Reload dropdown]" (reload triggers the catalog fetch that populates the dropdown).
- `result.status === "truncated"`: yellow "Azure listing was truncated; refresh kept 23 states from before. [Retry refresh] [View log]".
- `result.status === "cancelled"`: neutral "Refresh cancelled at state 42 of 147. Previous catalog kept. [Refresh again]".
- `result.status === "error"`: red with error text + "[Retry] [View log]".

All refresh-log entries get populated regardless of outcome (existing `append_refresh_log` behavior).

### Cancel behavior

`Cancel` button → `POST /refresh/cancel` → UI shows "Cancelling (finishing current state)…" overlay on the progress bar → on next poll, `progress.status === "done"` with `result.status === "cancelled"` → transition to the cancelled-summary banner above.

### Empty-state persistence

The empty-state banner stays visible until `catalog.entries` exceeds 1. It doesn't auto-dismiss on refresh-started; it transitions into the in-progress UI. On refresh completion, it checks the new entry count and either disappears (success) or re-renders (e.g., cancelled or truncated with count still ≤1).

## Failure modes

1. **Refresh background task crashes with an uncaught exception.**
   - The task wrapper catches all exceptions, writes `progress.json` with `status: done`, `result: {status: "error", error: "<message>", traceback: "<short trace>"}`, releases the lock.
   - The UI sees the terminal error on the next poll and renders the red banner.

2. **Search container restarts mid-refresh.**
   - Lockfile + progress.json both persist on disk.
   - On next `POST /refresh`: lockfile present → 409 locked; the 409 payload includes the `progress_url` so the UI can poll and see the stale running state.
   - On next `GET /refresh/progress`: returns `status: running`, `last_updated` far in the past.
   - The UI detects `last_updated > 10 min old` and renders "Refresh appears stuck. [Force clear]" → calls `POST /admin/pipeline/noaa/force-unlock` + manual cleanup of progress.json.
   - Deferred to the stranded-state class-of-bug spec for a proper automatic fix.

3. **Cancel during a multi-MB Azure download.**
   - `refresh_catalog()`'s `fetch_tile_count()` uses `aiohttp` session with no explicit cancellation hook today.
   - Wrap each `await session.get(...)` in `asyncio.wait_for(..., timeout=30)` and check `cancel_requested` between every state. Worst-case cancel latency = one more state's download-and-parse, typically ≤15s.
   - For truly unresponsive downloads (hung socket), the 30s timeout terminates the request and lets the cancel flag fire.

4. **Two browser tabs poll concurrently.**
   - `GET /refresh/progress` is read-only. No race.
   - If both hit `POST /cancel`, the second is a no-op (cancel_requested already true).

5. **Progress.json write races refresh task reading.**
   - Atomic writes via temp + rename. Readers either see the pre-update or the post-update snapshot — never a partial file.

6. **Frontend polls forever on a crashed browser (progress.json never updates).**
   - Server-side has no awareness of browser state. Progress.json stops updating when the bg task finishes. UI poll transitions to `status: done` once the task writes the terminal state.
   - If the task died without writing terminal state (see mode 2), the staleness heuristic kicks in.

7. **Refresh completes successfully but the lockfile fails to release (rare: disk full, permission change).**
   - `refresh_catalog()` already uses `fcntl.flock` (atomic, OS-released on process exit) + the lockfile is removed in a `finally` block. The bg task wrapper's `finally` removes progress.json OR transitions it to terminal, and removes the lockfile.
   - Double-finally: the task wrapper has its own `try/except/finally` that logs and swallows any secondary error, so the primary result still reaches progress.json.

## Testing invariants

1. **POST /refresh returns 202 within 500ms** (doesn't wait for the bg task).
2. **Progress.json `last_updated` advances within 30s** of a running refresh — guards against silent stalls.
3. **Cancel request reaches the bg task within 30s** — guards against missed flag checks.
4. **Terminal progress.json is written exactly once per refresh** — no duplicate appends, no skipped writes on exception paths.
5. **Refresh-log (JSONL) gains exactly one entry per refresh** — no duplicates on cancel, no skipped entries on error.
6. **UI-side polling stops within 2s of `status: done`** — no runaway polling after completion.
7. **Frontend correctly renders a running refresh that started in a previous browser session** (reload the page mid-refresh → progress UI re-hydrates from the current `/progress` state).
8. **Frontend correctly renders a completed refresh that started in a previous session** (reload after completion → shows the summary banner instead of the dispatch button).

## Security

- `POST /refresh`, `GET /progress`, `POST /cancel` all require `Depends(require_config_source)` — same as existing NOAA admin endpoints.
- Progress.json path is fixed, not user-supplied. No path traversal surface.
- No user input flows into the bg task's argument list (same `refresh_catalog(data_dir=DATA_DIR)` call shape as today).

## Alternatives considered

**A) Extend nginx's `proxy_read_timeout` to 1800s (30 min) and keep the sync endpoint.**
Rejected: UI still shows nothing for 30 min. Browser keeping a single HTTP connection open for 30 min is also network-fragile.

**B) Server-Sent Events (SSE) or WebSocket-streamed progress.**
Rejected: more complex, introduces a long-lived connection per client, requires nginx buffering config changes, and the 2-second poll cadence is fine for a 10–30 min operation. Polling degrades gracefully across tab-switches and reconnects.

**C) Shell out to a subprocess that writes progress to stdout, parse server-side.**
Rejected: adds process-lifecycle complexity. `refresh_catalog()` is already async Python; an asyncio task is the natural fit.

**D) Hide the refresh button entirely; refresh on a cron.**
Rejected: the pre-merge real-Azure GitHub Action in Task 36 already handles the scheduled-refresh case for CI. The admin UI exists for users who want to refresh on demand.

## Rollback

If the async refresh misbehaves in production, revert commits in reverse order:
1. Revert frontend changes (last commits; user-visible impact).
2. Revert the async-dispatch endpoint change; re-deploy with the sync endpoint.
3. Delete `/data/noaa_catalog_refresh.progress.json` on affected machines.

Lockfile + refresh-log entries are unchanged from current behavior; no data-schema rollback is needed.

## Open questions

1. **Should the in-progress UI survive page navigation?** If the user clicks away from the NOAA card, the polling stops. Should a small inline indicator persist at the top of the admin panel? (Recommend: **no** for v1 — scope creep. Add in a follow-up if users report confusion.)
2. **Should we expose the cancel endpoint in the CLI too?** `python scripts/refresh_noaa_catalog.py --cancel` would be useful for ops. (Recommend: **yes, small addition in Phase 1** — one more CLI flag that writes `cancel_requested: true` to progress.json.)
3. **Rate-limit the poll endpoint?** (Recommend: **no** for v1. The admin panel is localhost-only per `feedback_prod_stack.md`; no adversarial load expected.)
