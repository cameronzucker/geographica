# NOAA refresh async + progress — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement. TDD per task; no worktrees (banned, see CLAUDE.md §Git workflow); every commit trailer includes `Agent: <moniker>`.

**Spec:** [docs/superpowers/specs/2026-04-20-noaa-refresh-async-progress-design.md](../specs/2026-04-20-noaa-refresh-async-progress-design.md)

**Scope:** 11 tasks across 3 phases. Estimated execution time: 2–3 hours of focused work.

**Repo state at plan creation:** `dev` at `1910e15`. The NOAA CONUS expansion (Phases 0-6) shipped in the preceding session. `refresh_catalog()` + 5 admin endpoints + frontend refresh-log panel exist and are live on the stack. This plan sits ON TOP of that work.

---

## Required preambles (every task)

**Before starting:**
1. Read CLAUDE.md §"Agent identity" (pick a lowercase moniker) + §"Git workflow — worktrees are BANNED" + §"Git workflow — destructive commands are BANNED".
2. Read the spec at [docs/superpowers/specs/2026-04-20-noaa-refresh-async-progress-design.md](../specs/2026-04-20-noaa-refresh-async-progress-design.md) for the task at hand.
3. Skim [docs/pitfalls/testing-pitfalls.md](../../pitfalls/testing-pitfalls.md) items #1 (mock boundary), #5 (async isolation), #12 (orphaned processes from real-endpoint tests).
4. Skim [docs/pitfalls/implementation-pitfalls.md](../../pitfalls/implementation-pitfalls.md) §14 (worktree ban).

**TDD discipline:**
- Failing test first; if it passes before implementation, the test is wrong.
- Commit per task. Include `Agent: <moniker>` trailer.
- Confirm pre-flight: `pwd` → `/home/administrator/Code/geographica`; `git branch --show-current` → `dev`; `git status` clean (ignore untracked `.png`/adversarial docs).

**Environment at resume:**
- Dev stack is live (`docker compose ps`). Search container has `gdal-bin` + `aiohttp` from commit `1910e15`.
- `/data/companion-bench/.pipeline-state.json` is currently `status: cancelled` from an earlier triage. Not related to this work.
- A refresh may be in-flight when you resume. Check `curl -X POST /admin/pipeline/noaa/refresh`; if 409 with `lock_holder_pid: 1`, the prior session's bg task may still be running. Check `docker compose logs search --tail=20`. If truly hung, `sudo rm /srv/geographica/data/noaa_catalog_refresh.lock` + restart the search container.

---

## Phase 1 — Backend async-dispatch + progress persistence (6 tasks)

### Task 1: Progress-state helpers in `refresh_noaa_catalog.py`

**Files:** `scripts/refresh_noaa_catalog.py`, `tests/test_refresh_noaa_catalog.py`.

**Step 1 — failing tests**

```python
# tests/test_refresh_noaa_catalog.py (append)
def test_write_progress_atomic(tmp_path):
    from scripts.refresh_noaa_catalog import write_progress_state
    path = tmp_path / "progress.json"
    write_progress_state(path, {"status": "running", "phase": "listing"})
    assert path.exists()
    import json
    data = json.loads(path.read_text())
    assert data["status"] == "running"
    assert "last_updated" in data


def test_read_progress_state_missing_returns_idle(tmp_path):
    from scripts.refresh_noaa_catalog import read_progress_state
    assert read_progress_state(tmp_path / "nonexistent.json") == {"status": "idle"}


def test_is_cancel_requested(tmp_path):
    from scripts.refresh_noaa_catalog import write_progress_state, is_cancel_requested
    path = tmp_path / "progress.json"
    write_progress_state(path, {"status": "running"})
    assert is_cancel_requested(path) is False
    write_progress_state(path, {"status": "running", "cancel_requested": True})
    assert is_cancel_requested(path) is True


def test_request_cancel_sets_flag(tmp_path):
    from scripts.refresh_noaa_catalog import write_progress_state, request_cancel, read_progress_state
    path = tmp_path / "progress.json"
    write_progress_state(path, {"status": "running"})
    request_cancel(path)
    assert read_progress_state(path)["cancel_requested"] is True
```

**Step 2 — implement**

Add to `scripts/refresh_noaa_catalog.py`:

```python
PROGRESS_FILENAME = "noaa_catalog_refresh.progress.json"

def write_progress_state(path: Path, state: dict) -> None:
    """Atomic write — temp file + rename — so readers never see partial JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {**state, "last_updated": datetime.now(timezone.utc).isoformat()}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True))
    os.replace(tmp, path)


def read_progress_state(path: Path) -> dict:
    """Return progress JSON, or {'status': 'idle'} if the file is absent/unreadable."""
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {"status": "idle"}


def is_cancel_requested(path: Path) -> bool:
    return bool(read_progress_state(path).get("cancel_requested"))


def request_cancel(path: Path) -> None:
    state = read_progress_state(path)
    if state.get("status") != "running":
        return
    state["cancel_requested"] = True
    write_progress_state(path, state)
```

**Step 3 — commit**

```
feat(noaa): progress-state helpers for async catalog refresh

Atomic write/read + cancel-flag setter/getter for the new
noaa_catalog_refresh.progress.json file. Supports the upcoming
async-dispatched refresh endpoint and polling contract per
docs/superpowers/specs/2026-04-20-noaa-refresh-async-progress-design.md.

Agent: <moniker>
```

---

### Task 2: `refresh_catalog` progress callback

**Files:** `scripts/refresh_noaa_catalog.py`, `tests/test_refresh_noaa_catalog.py`.

**Step 1 — failing test**

```python
@pytest.mark.asyncio
async def test_refresh_catalog_calls_progress_callback(tmp_path, monkeypatch):
    """refresh_catalog emits per-state progress events via a callback."""
    from scripts.refresh_noaa_catalog import refresh_catalog
    events = []
    async def fake_azure(**kwargs):
        return ["AZ_NAIP_2021_9596/", "UT_NAIP_2021_9601/"]
    monkeypatch.setattr("scripts.refresh_noaa_catalog.azure_list_blob_prefixes", fake_azure)
    # … patch validate_tile_index + fetch_tile_count as in existing tests …
    result = await refresh_catalog(
        data_dir=tmp_path,
        progress_cb=lambda event: events.append(event),
    )
    phases = [e["phase"] for e in events]
    assert "listing" in phases
    assert "fetching_tile_indexes" in phases
    assert any(e.get("current_slug") == "arizona" for e in events)
    assert any(e.get("states_processed") == 2 for e in events)
```

**Step 2 — implement**

Extend `refresh_catalog(...)` signature: `progress_cb: Callable[[dict], None] | None = None`. At each phase boundary + each state processed, call `progress_cb({...})` with the current `phase`, `states_processed`, `states_total`, `current_slug`, `validation_issue_count`. Between states, ALSO check `is_cancel_requested(progress_path)` if a `progress_path` kwarg is provided — returning a `{"status": "cancelled", "log_entry": {...}}` dict.

**Step 3 — commit**

```
feat(noaa): progress callback + cancellation polling in refresh_catalog

refresh_catalog now accepts progress_cb to emit per-state events and
polls cancel_requested between state boundaries. Backward-compatible:
both parameters are optional. Prepares for async-dispatched HTTP
wrapper in Task 3.

Agent: <moniker>
```

---

### Task 3: Async-dispatch the `POST /refresh` endpoint

**Files:** `services/search/main.py`, `services/search/tests/test_noaa_admin_endpoints.py`.

**Step 1 — failing tests**

- `POST /admin/pipeline/noaa/refresh` returns 202 within 500ms (mock the bg task).
- Response body includes `status`, `progress_url`, `estimated_minutes`.
- The bg task is scheduled (assert `asyncio.all_tasks()` grew by 1).
- 409 when lockfile already exists (existing behavior).
- 409 when pipeline running (existing behavior).

**Step 2 — implement**

Rewrite `noaa_refresh()` endpoint:
1. Acquire lock via `RefreshLock` (as today).
2. Initialize progress.json with `status: "running", started_at, phase: "starting"`.
3. `asyncio.create_task(_refresh_bg_task(DATA_DIR))` where `_refresh_bg_task` wraps `refresh_catalog` with full try/except/finally (catches all exceptions, writes terminal progress, releases lock).
4. Return 202 immediately with `progress_url`.

**Step 3 — commit**

```
feat(noaa): async-dispatch POST /admin/pipeline/noaa/refresh

Endpoint now returns 202 within milliseconds instead of holding the
connection open for 10-30 min. refresh_catalog runs as an asyncio
background task; progress is persisted to progress.json and polled
via the new /refresh/progress endpoint (Task 4). Fixes the 504
Gateway Timeout + SyntaxError chain the frontend hit on first
real refresh.

Agent: <moniker>
```

---

### Task 4: `GET /refresh/progress` endpoint

**Files:** `services/search/main.py`, `services/search/tests/test_noaa_admin_endpoints.py`.

**Step 1 — failing tests**

- Idle: 200 + `{"status": "idle"}`.
- Running: 200 + the full progress shape from spec §API.
- Done: 200 + `{"status": "done", "result": {...}}`.
- Schema compatibility: all statuses have `status` at top level.

**Step 2 — implement**

```python
@app.get("/admin/pipeline/noaa/refresh/progress", dependencies=[Depends(require_config_source)])
async def noaa_refresh_progress():
    try:
        from refresh_noaa_catalog import read_progress_state, PROGRESS_FILENAME
    except ImportError:
        raise HTTPException(503, "refresh_noaa_catalog module unavailable")
    return read_progress_state(DATA_DIR / PROGRESS_FILENAME)
```

**Step 3 — commit**

```
feat(noaa): GET /admin/pipeline/noaa/refresh/progress endpoint

Returns the current refresh state (idle/running/done) by reading
noaa_catalog_refresh.progress.json. Frontend polls this every 2s
while a refresh is in flight (Task 9). Read-only; no side effects.

Agent: <moniker>
```

---

### Task 5: `POST /refresh/cancel` endpoint

**Files:** `services/search/main.py`, `services/search/tests/test_noaa_admin_endpoints.py`.

**Step 1 — failing tests**

- Running: 200 + confirmation message; progress.json's `cancel_requested` is now `True`.
- Idle: 404.
- Done: 404.

**Step 2 — implement**

```python
@app.post("/admin/pipeline/noaa/refresh/cancel", dependencies=[Depends(require_config_source)])
async def noaa_refresh_cancel():
    try:
        from refresh_noaa_catalog import read_progress_state, request_cancel, PROGRESS_FILENAME
    except ImportError:
        raise HTTPException(503, "refresh_noaa_catalog module unavailable")
    progress_path = DATA_DIR / PROGRESS_FILENAME
    if read_progress_state(progress_path).get("status") != "running":
        raise HTTPException(404, "No refresh in progress")
    request_cancel(progress_path)
    return {"status": "cancellation_requested",
            "message": "The refresh will stop at the next state boundary (within ~10s)."}
```

**Step 3 — commit**

```
feat(noaa): POST /admin/pipeline/noaa/refresh/cancel endpoint

Sets cancel_requested=true in progress.json. The background task
polls the flag between state boundaries and inside each Azure fetch
(via asyncio.wait_for's timeout loop) and terminates gracefully —
logging a log_entry with status=cancelled before releasing the
lockfile.

Agent: <moniker>
```

---

### Task 6: Stale-refresh detection heuristic

**Files:** `services/search/main.py`, `services/search/tests/test_noaa_admin_endpoints.py`.

**Step 1 — failing test**

- Progress.json shows `status: running` but `last_updated` is 15 min old → `GET /progress` returns the state with an additional `stale: true` flag.

**Step 2 — implement**

In the `noaa_refresh_progress` endpoint, after reading the state:

```python
state = read_progress_state(progress_path)
if state.get("status") == "running":
    last = state.get("last_updated")
    if last and _is_stale(last, threshold_sec=600):
        state["stale"] = True
        state["stale_reason"] = f"No progress update in {...}s; refresh task may have crashed."
return state
```

Defer the actual cleanup affordance to the frontend (Task 11b will add a "Force clear" button that calls `POST /force-unlock` + manually cleans progress.json — same remediation as today's stranded-state recovery).

**Step 3 — commit**

```
feat(noaa): flag stale refresh in /progress response

When a refresh's progress.last_updated is more than 10 minutes old
while status is still running, the endpoint stamps stale=true. The
frontend surfaces this as a recoverable error state with a "Force
clear" action. Guards against the class of bug where the bg task
crashes without writing terminal state.

Agent: <moniker>
```

---

## Phase 2 — Frontend UX (5 tasks)

### Task 7: Move Refresh button out of the history collapsible

**Files:** `frontend/config/index.html`.

**Step 1 — implement**

Restructure `renderNoaaBody` so the Refresh button is rendered:

1. In an empty-state banner above the tab strip when `catalog.entries` has ≤1 entry (amber, prominent, with copy from spec §Frontend UX).
2. As a small `[Refresh]` button in the tab strip (top-right of the card) when catalog is populated.

Move the `[Refresh catalog now]` out of the history collapsible. The history panel stays for audit-trail display only.

**Step 2 — commit**

```
feat(frontend): promote NOAA Refresh to primary CTA

Discoverability fix: the "Refresh catalog now" button was buried
inside the "Catalog refresh history" collapsible — users looking
for "how do I add more states" had no reason to open history. Now
it renders as an amber empty-state banner when catalog.entries ≤ 1
("Only N of ~49 states cataloged") and a small secondary button
next to the card header once the catalog is populated. History
panel stays in place for audit trail.

Agent: <moniker>
```

---

### Task 8: Confirm-duration dialog

**Files:** `frontend/config/index.html`.

**Step 1 — implement**

Replace the current `confirm(...)` in the Refresh click handler with a longer-form native `confirm()` dialog carrying the copy from spec §Confirm-duration dialog. (Native `confirm` is ugly but zero dependencies; a nicer modal is a follow-up.)

**Step 2 — commit**

```
feat(frontend): cite 10-30 min duration in NOAA refresh confirm dialog

Makes expected duration + background-dispatch + cancel affordance
visible to the user BEFORE they trigger the refresh. Sets the
mental model that this is a long-running job, not a round-trip.

Agent: <moniker>
```

---

### Task 9: Progress bar polling UI

**Files:** `frontend/config/index.html`.

**Step 1 — implement**

On Refresh confirmation:
- `POST /refresh`; on 202, start polling.
- Replace the Refresh button/banner with the progress-card markup from spec §In-progress UI.
- `setInterval(() => fetch('/progress').then(render), 2000)`.
- Render: `<progress value="..." max="..."></progress>`, current_slug, elapsed (computed client-side from `started_at`), ETA (use `eta_seconds` from response; format as `~N min` or `N min K s`).
- On `status === "done"`, clearInterval, render the completion summary banner per spec.
- On `stale: true`, render the recoverable-error banner with a "Force clear" button.
- Cancel button in the card → `POST /refresh/cancel` → UI overlay "Cancelling…".

**Step 2 — commit**

```
feat(frontend): live progress bar + ETA for NOAA catalog refresh

Polls /admin/pipeline/noaa/refresh/progress every 2 s while status
is running. Renders a progress bar, current state slug, elapsed,
and server-computed ETA. Stops polling on terminal status. Handles
the stale-progress case (10+ min no update) with an actionable
Force Clear affordance.

Agent: <moniker>
```

---

### Task 10: Completion summary + reload dropdown

**Files:** `frontend/config/index.html`.

**Step 1 — implement**

On `status === "done"`:

- `result.status === "ok"`: green banner "Catalog refreshed — N states available." + auto-trigger the catalog fetch that populates the state dropdown (the existing Task 28 fetch in renderNoaaBody).
- `result.status === "cancelled"`: neutral banner "Refresh cancelled." + offer "[Refresh again]".
- `result.status === "truncated"` or `"invalid_parse"`: yellow banner with error text + "[Retry]".
- `result.status === "error"`: red banner with error + "[Retry]" + "[View log]".

Appending a new entry to the history panel is a free side-effect of the existing `loadRefreshLog()` function — call it from the summary-render path.

**Step 2 — commit**

```
feat(frontend): NOAA refresh completion summary + dropdown reload

On terminal progress, the in-progress card becomes a summary banner
matched to result.status (ok/cancelled/truncated/invalid_parse/error).
On ok, auto-reloads the catalog dropdown so the newly-refreshed
states appear without the user needing to collapse + expand the
card. On error-class outcomes, surfaces actionable retry copy.

Agent: <moniker>
```

---

### Task 11: Cancel + Force Clear wiring

**Files:** `frontend/config/index.html`.

**Step 1 — implement**

- Cancel button on the progress card → `POST /refresh/cancel` → apply a "Cancelling…" overlay to the progress card (opacity dim + text).
- Force Clear button (only when `progress.stale === true`) → `POST /admin/pipeline/noaa/force-unlock` + on success, manually cleanup `/progress` via a new `DELETE /admin/pipeline/noaa/refresh/progress` endpoint OR by POSTing the cancel flag and accepting the stale-state transition.
- Recommended: add a small `POST /admin/pipeline/noaa/refresh/reset` endpoint that force-unlocks AND removes the progress.json — used only via the Force Clear affordance. Single atomic operation avoids a split-brain state where unlock succeeds but progress.json lingers.

**Step 2 — commit**

```
feat(noaa): cancel + force-clear wiring for stuck refreshes

Cancel button POSTs /refresh/cancel; progress card shows a
"Cancelling..." overlay until the bg task notices the flag and
transitions to status=done. Force Clear (visible only when
progress.stale=true) calls the new /refresh/reset endpoint which
atomically force-unlocks the lockfile AND removes progress.json,
returning the refresh subsystem to idle so the user can retry.

Agent: <moniker>
```

---

## Phase 3 — Review + log

### Task 12: Phase review (3 rounds)

Dispatch in parallel:
1. Sonnet architectural review — check async-dispatch correctness, task cancellation semantics, state-file race conditions.
2. Haiku test coverage review — identify missing failure-mode tests across tasks 1-11.
3. Codex adversarial — `npx --yes @openai/codex review --base <pre-Phase-1 SHA>`.

Address any Critical/Important findings in a closeout commit.

### Task 13: Implementation log + push

Update [dev/implementation-log.md](../../../dev/implementation-log.md) with a new 2026-04-?? entry. Push dev to origin.

---

## Execution options

1. **Subagent-Driven (recommended)** — dispatch fresh subagents per task with TDD preamble.
2. **Inline execution** — the scope (11 tasks, mostly small) fits one focused session if context budget allows.

Either works. Current context is running out; the NEXT session's agent should pick up from a clean slate with this plan + the spec + the handoff memory.

## Estimated duration

- Phase 1 (6 tasks, backend): ~1 hour
- Phase 2 (5 tasks, frontend): ~1 hour
- Phase 3 (review + log): ~30 min

Total: ~2.5 hours focused work, not counting review-finding fixes.
