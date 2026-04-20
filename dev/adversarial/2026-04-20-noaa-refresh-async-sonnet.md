# Adversarial review — NOAA refresh async + progress spec/plan

**Reviewer:** Sonnet, read-only independent pass
**Date:** 2026-04-20
**Spec:** [docs/superpowers/specs/2026-04-20-noaa-refresh-async-progress-design.md](../docs/superpowers/specs/2026-04-20-noaa-refresh-async-progress-design.md)
**Plan:** [docs/superpowers/plans/2026-04-20-noaa-refresh-async-progress.md](../docs/superpowers/plans/2026-04-20-noaa-refresh-async-progress.md)

## Summary — not ready to execute as written

Three issues must land as spec/plan v2 before implementation begins.

## Critical

**A1 / E2 — `asyncio.create_task()` reference must be retained.** Plan Task 3 calls `asyncio.create_task(...)` and drops the reference. CPython docs explicitly warn that Tasks held only in the event loop's weak set can be garbage-collected before they finish — no exception, no terminal progress.json, just a vanished refresh. Fix: Task 3 must store the returned Task in a module-level `_active_refresh_task: asyncio.Task | None = None` and clear it in the task's `finally`. Alternative: switch to FastAPI `BackgroundTasks` (but the module-level var is needed anyway for Force Clear to call `task.cancel()`, so keep `create_task`).

**A3 / C1 — event loop blocks during `ogr2ogr` and unbounded downloads.** `fetch_tile_count` runs `subprocess.run(["ogr2ogr", ...], timeout=60)` which is a SYNC call — it blocks the entire asyncio event loop for up to 60 seconds. During that time, `GET /progress` polls from the browser queue up and the UI appears frozen. Separately, the aiohttp GET for the tile-index zip download has no `ClientTimeout`, so a slow Azure connection can stall indefinitely. Fix: plan needs explicit steps to (a) wrap `subprocess.run` in `asyncio.get_event_loop().run_in_executor(None, ...)` AND (b) pass `ClientTimeout(total=300)` to the download session.

## Important

**A2 / B1 — file-based cancel flag races with bg task progress writes.** `request_cancel` reads progress.json, mutates, writes back. Bg task's next `write_progress_state` can clobber the flag. Even when the flag survives, the cancel check happens only at state boundaries. Fix: use a module-level `asyncio.Event` for cross-coroutine signaling; the progress.json's `cancel_requested` becomes a read-only status field for the UI, written by the bg task after it observes the event.

**C2 — Force Clear + immediate new refresh can spawn a ghost task.** `/refresh/reset` deletes the lockfile + progress.json, but the old bg task (still in `fetch_tile_count`) doesn't know. User clicks Refresh, new bg task starts, old bg task's next `progress_cb` call corrupts the new progress.json. Fix: `/refresh/reset` must call `_active_refresh_task.cancel()` before clearing files; wait for cancellation to take effect.

**D3 / invariant-#7 inconsistency — rehydration on page navigation is untasked.** Spec testing invariant #7 requires "frontend correctly renders a running refresh that started in a previous browser session," but no task implements re-hydration on `renderNoaaBody`. Either add a Task 9a to detect `status: running` on card expand and restore the in-progress UI, or move invariant #7 to a follow-up.

**E1 — `progress_cb` contract under-specified.** Task 2 says "call `progress_cb({...})`" but doesn't define: sync vs async, can it raise (and does that abort the refresh?), the exact key set. Define: sync callable, takes dict, return ignored, must not raise. Document in the Task 2 step-2 text.

**F1 — no end-to-end integration test for async dispatch.** Task 3's unit test checks `asyncio.all_tasks()` grew by 1, but that's a mock-world assertion. Need a test that starts a real async refresh against a mock Azure server, polls /progress through phase transitions, and verifies terminal state + refresh-log entry. Required for invariants #1, #3, #4.

**F2 — no test for the ghost-task / new-refresh collision.** Required now that C2 is identified. Test: force-clear during running bg task, start new refresh, verify old progress writes don't corrupt new task's progress.json.

## Minor / Open questions

- **B2:** Stale threshold 10 min hardcoded. On slow mesh backhauls a single state's zip download can legitimately take that long. Consider making configurable via env var.
- **C3:** No low-disk guard. `OSError: No space left` gets caught per-state as `tile_count_failed`; refresh appears to succeed with 0 states. Low-pri but ugly.
- **D1:** Task 8 uses native `window.confirm()`. Ugly + Chrome "This page says:" prefix undermines copy. HTML `<dialog>` is a zero-dep upgrade.
- **D2:** Empty-state banner "Only 1 of ~49 states cataloged" assumes the CI stub looks like a sparse real catalog. Consider distinguishing `stub` vs `sparse_real` in catalog metadata.
- **E3:** `/refresh/reset` is in the plan (Task 11) but not in the spec's API contract section. Scope drift — add it to the spec.
- **E4:** Task 12 review-closeout commit format not specified. Match the NOAA CONUS expansion's pattern: write review output to `dev/adversarial/<date>-noaa-refresh-async-<model>.md`, closeout commit `fix(noaa): async-refresh review closeout — N findings addressed`.
- **F3:** Add a test that `GET /progress` is non-blocking during a mock long-running `fetch_tile_count`. Catches the run_in_executor fix regression.
- **G1:** Rollback script should specify both files: `rm -f /srv/geographica/data/noaa_catalog_refresh.{lock,progress.json}`.

## Overall assessment

**Not ready to execute as written.** Critical A1/E2 and A3/C1 must be fixed in spec v2 + plan v2. Important A2/B1, C2, D3, E1, F1, F2 should be addressed in the same pass. Minor items are safe to defer to implementation-time discretion.

Once the must-fixes land, the spec is well-structured, the task breakdown is reasonable, and the architecture (dispatch + poll) is correct. The plan's overall 2-3h estimate is realistic IF the above are resolved first.
