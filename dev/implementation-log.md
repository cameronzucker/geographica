# Implementation Log

Narrative companion to [CHANGELOG.md](../CHANGELOG.md). Where
`CHANGELOG.md` lists *what* changed in each release, this log captures
*why* and *how* — the reasoning, tradeoffs, adversarial reviews, and
bugs caught before release.

Entries are reverse-chronological (newest first). Each significant work
item gets one entry. The format:

```markdown
## YYYY-MM-DD — <topic>

**Released as:** vX.Y.Z (or "not yet released" / "ongoing")
**Plan / spec:** docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md
                 docs/plans/YYYY-MM-DD-<topic>-plan.md
**Bug hunts:** dev/bug-hunts/YYYY-MM-DD-<topic>-*.md (if any)
**Adversarial reviews:** dev/adversarial/YYYY-MM-DD-<topic>-*.md (if any)

### Summary
One paragraph: what was built, why, and the outcome.

### Key decisions
- Decision and rationale.
- Alternative considered and why rejected.

### Notable bugs caught
- Bug → where caught → commit SHA that fixed it.

### Commits
Short list of notable commits (SHA + subject). The git log is
authoritative; list only the ones a reader would want to jump to.

### Outcome
Production results, test counts, any surprises.
```

---

## 2026-04-20 — NOAA catalog refresh async+progress (Phase 1 complete, Phase 2 pending)

**Released as:** not yet released (in-progress on `dev`)
**Plan / spec:** [docs/superpowers/specs/2026-04-20-noaa-refresh-async-progress-design.md](../docs/superpowers/specs/2026-04-20-noaa-refresh-async-progress-design.md), [docs/superpowers/plans/2026-04-20-noaa-refresh-async-progress.md](../docs/superpowers/plans/2026-04-20-noaa-refresh-async-progress.md)
**Adversarial reviews:** [dev/adversarial/2026-04-20-noaa-refresh-async-sonnet.md](adversarial/2026-04-20-noaa-refresh-async-sonnet.md) (v1→v2); Phase 1 closeout: Sonnet architectural + Sonnet adversarial + Codex (`/tmp/phase1-codex-review.log`)

### Summary
Follow-on to the 2026-04-20 NOAA NAIP CONUS expansion (39 tasks shipped). First live refresh attempt surfaced three UX failures: nginx 60s `proxy_read_timeout` returning a 504 HTML page (browser `JSON.parse` → SyntaxError), no progress reporting for the 10–30 min operation, and the Refresh button buried inside a collapsible labeled "history". Phase 1 converts the endpoint from a single synchronous HTTP call to a **dispatch + poll** pattern: `POST /refresh` returns 202 Accepted in <1s and schedules `refresh_catalog()` on `asyncio.create_task()`; a progress callback atomically writes `/data/noaa_catalog_refresh.progress.json`; `GET /refresh/progress` returns the state; `POST /refresh/cancel` sets a module-level `asyncio.Event`. Frontend wiring lands in Phase 2.

### Key decisions
- **asyncio.Event (not file flag) for cancel signalling.** Spec v2 §change #3 — eliminates the read-then-write race where the cancel endpoint's file write would clobber the bg task's progress update. The file flag stays in progress.json as UI-readable status only, written by the bg task *after* observing the Event.
- **Module-level `_active_refresh_task` reference retention.** Spec v2 §change #1 — prevents Python's GC from collecting tasks held only in the event loop's weak set; also enables future `/refresh/reset` to cancel the task cleanly.
- **run_in_executor for blocking ops.** `fetch_tile_count`'s `ogr2ogr` subprocess, the ZIP file write, and `ZipFile.extractall()` are all dispatched through the executor so the event loop stays responsive for `/progress` polling during the 10–30 min refresh.
- **RefreshCancelled exception for mid-state cancel routing.** Spec v2 §Failure mode 3 targeted ≤15s typical cancel latency — state-boundary polling alone was ~360s+ worst case inside a large tile-index download + extract. `fetch_tile_count` now checks `cancel_event` at four points and raises `RefreshCancelled`, which `refresh_catalog`'s per-state loop catches and routes to the same cancelled-log-entry path as its loop-top check.

### Notable bugs caught (by the Phase 1 closeout 3-round review)
- **Cancel latency unbounded** — `sess.get(total=300)` + `write_bytes` + `extractall` + `ogr2ogr(60s)` could stall cancel for minutes (all 3 rounds) → `fe8db7d`.
- **Duplicate refresh-log entries** — `refresh_catalog` logs on all ok/truncated/cancelled/invalid_parse paths; bg-task wrapper's generic `except Exception` was appending a second `validation_status=error` entry (Sonnet Round 2 + Codex) → `fe8db7d`.
- **_is_progress_stale `TypeError`** on tz-naive ISO timestamps — `GET /progress` 500 instead of gracefully non-stale (Sonnet Round 2 + Codex) → `fe8db7d`.
- **Test gaps** — bg-task error path round-trip, CancelledError branch, POST /cancel auth, naive-ISO stale path. All added in `fe8db7d`.

### Commits (Phase 1)
- `6fdac47` feat(noaa): progress-state helpers
- `3956dff` feat(noaa): refresh_catalog progress callback + event-loop-safe fetch_tile_count
- `015a325` feat(noaa): async-dispatch POST /refresh
- `b3b4a39` feat(noaa): GET /refresh/progress
- `5238834` feat(noaa): POST /refresh/cancel
- `dcce6c5` feat(noaa): stale-refresh heuristic
- `fe8db7d` fix(noaa): Phase 1 review closeout — 3 bugs + 4 test gaps

### Known latent issues (deferred to a separate ops-hardening spec)
- **Multi-worker double-dispatch**: module-level `_active_refresh_task` doesn't serialize across uvicorn workers. Currently single-worker, so inactive. (Codex flagged.)
- **Single-temp-file race** in `write_progress_state`: fixed `.tmp` filename is not multi-writer safe under the multi-worker scenario above. Same mitigation. (Codex flagged.)

### Outcome
Phase 1 complete: 6 Task commits + 1 closeout commit = 7 commits on `dev`. 95 passing tests (up from 90 at start of Phase 1) across `tests/test_refresh_noaa_catalog.py` (43) + `services/search/tests/test_noaa_admin_endpoints.py` (52). No regressions in the pre-existing 2 M2M failures or 18 Nominatim-env errors. Phase 2 (frontend: Tasks 7-11) is next.

---

## 2026-04-21 — Nav UX beta-bug remediation (13 bugs closed, B1 deferred)

**Released as:** not yet released (pending main merge + runtime validation)
**Plan / spec:** [docs/superpowers/plans/2026-04-21-nav-uxb-remediation.md](../docs/superpowers/plans/2026-04-21-nav-uxb-remediation.md)
**Bug hunts:** [dev/bug-hunts/2026-04-21-nav-uxb-consolidated.md](bug-hunts/2026-04-21-nav-uxb-consolidated.md)
**Adversarial reviews:** none (exploratory/holistic/multipass hunters cross-validated in parallel)

### Summary

Four beta-tester reports triggered a full bug-hunt cycle on turn-by-turn navigation. Exploratory, Holistic, and Multipass hunters conducted independent analysis and triangulated findings across [frontend/navigation.js](../frontend/navigation.js), [frontend/nav-ui.js](../frontend/nav-ui.js), and [frontend/app.js](../frontend/app.js). Cycle surfaced 14 confirmed bugs (13 closed in this cycle, 1 deferred) + 6 low-priority signals + 2 pre-existing out-of-scope issues.

**Closed bugs:**
- **B2 (highest severity):** Reroute leaves map polyline, sidebar directions, and trip globals stale. Fixed via new `setActiveRoute(trip, options)` unifier in app.js that owns engine state + map source + sidebar + globals. Reroute path now calls this before engine apply.
- **B3:** GPS marker renders at ~60% instead of 78% from viewport top. Fixed proportional padding formula `top = mapH * 0.56 + overlayH` in getNavPadding; also explicit clear-padding on nav exit (merged with B8).
- **B4:** Recenter/compass overlap on mobile; wrong stack order on desktop. CSS-only stack reorder: compass at bottom:120, recenter at bottom:170 (desktop); at mobile:100/150 resp.
- **B5:** Multi-stop reroutes drop intermediate waypoints. Fixed `buildRouteData` to extract `remainingWaypoints` from trip.locations; reroute callback filters already-passed waypoints.
- **B6:** `costing_options` (avoid_highways, etc.) dropped on reroute. Added `costingOptions` field to route payload; engine passes through to reroute callback.
- **B7:** GPS hysteresis fills in ~2.5s instead of 5s because feedGPS calls updateGPS twice per unique position. Moved `nav.updateGPS()` inside signature-change guard.
- **B8:** Padding leaks across sessions via MapLibre persistence. Merged into B3 fix; explicit `padding: {top:0, bottom:0, left:0, right:0}` in restoreMapState easeTo.
- **B9:** `applyReroute` does not reset `lastAnnouncementTime`; `announcedSet` filter is backward. Fixed: `announcedSet = {}; lastAnnouncementTime = 0;`.
- **B10:** `lastRerouteTime` not cleared when engine timeout fires (10s reroute timeout but 15s cooldown overhang). Cleared on timeout callback.
- **B11:** Valhalla 200-with-error silent no-op (banner stuck). Explicit branch on `!data.trip || data.error` routes to retry/failure path.
- **B12:** In-flight fetches + retry setTimeouts survive stopNavigation. Tracked setTimeout IDs in array; stopNavigation clears all + resets counter.
- **B13:** First maneuver of subsequent leg at `begin_shape_index=0` indexes into previous leg. Clamped to `Math.max(0, ...)`.
- **B14 (upgraded from false-positive):** UI mute state not propagated to engine on nav start. Added `nav.setMuted(muted)` call after `nav.start()`.

**Deferred:**
- **B1 (voice tiering redesign):** Current distance-threshold logic announces 3× per turn; thresholds + tier boundaries are design-dependent. Cameron's plan-review decision: no band-aid this cycle — ship nothing until the full TTM (time-to-maneuver) redesign lands with its own brainstorm + spec + adversarial review. `VOICE_THRESHOLDS` in [frontend/navigation.js:42-46](../frontend/navigation.js#L42-L46) remains unchanged at `[800, 200, 50]`. Beta testers continue to hear 3 announcements per turn until the follow-up plan ships. TTM-redesign seed topics documented in the plan's Appendix.

### Key decisions

- **B1 fully deferred, no threshold band-aid:** Cameron's explicit call ("no reason to fix now when we're going to rebuild it"). The consolidated report's D1 option (b) chosen; options (a) and (c) rejected.
- **setActiveRoute refactor for B2, not band-aid:** Cameron's explicit call ("no more bandaids approaching 2.0.0"). Introduced `setActiveRoute(trip, options)` in [frontend/app.js](../frontend/app.js) that owns the 4-way state update (engine route, `_geographicaLastTrip`, `lastRouteCoords`, map `'route'` source, sidebar `#route-directions`). Exposed as `window._geographicaSetActiveRoute` for nav-ui.js reroute consumer. The old `renderRoute` function was deleted (~80 LOC). Three commits implement this: `2c03471` (extract, behavior unchanged), `a8cd7ba` (convert initial-route site + delete renderRoute), `cb3f27b` (convert reroute site — closes B2).
- **All 13 non-B1 bugs fixed inline:** Reroute path is under heavy surgery this cycle; deferring B5, B6, B12 would require revisiting same code in a follow-up. Fixing now is cheap + reduces regression risk.

### Notable bugs caught

- B2: State split across 4 places (engine route, globals, map source, sidebar) — caught by all three hunters as "most severe reported bug."
- B3: Padding math inverted (inset vs. offset) — caught by all hunters; Multipass also found sub-bug (B8 padding leak).
- B14: Upgraded from false-positive FP6 after re-read of logic — mute state guard is UI-side only; engine's announcedSet still fires, suppressing unmute-time announcements.

### Commits

Notable commits (20+ total on this branch):
- `54af3f0` test(nav): bootstrap Node vm-based engine test harness
- `830e4c7` fix(nav): reset announcedSet and lastAnnouncementTime on applyReroute (B9)
- `2c03471` refactor(nav): extract setActiveRoute as single source of truth (B2 prep)
- `03624b5` fix(nav): preserve intermediate waypoints across reroutes (B5)
- `ce12c02` fix(nav): preserve costing_options across reroutes (B6)
- `633f176` fix(nav): engine dedups duplicate GPS positions for hysteresis (B7)
- `cf56e6a` fix(nav): proportional nav padding + clear padding on nav exit (B3, B8)
- `ddc9578` fix(nav): stack recenter button above compass, resolve mobile overlap (B4)

### Outcome

- **Tests:** 12 unit tests passing (6 engine nav + 6 nav-ui route-data builders). Engine tests include dedicated B7 dedup test + B10 timeout test. Playwright harness modes (B2 polyline update, B11 error banner, B12 fetch abort, B3/B8 padding assertions, B4 button stack at viewports) documented as pending runtime validation against live dev frontend.
- **Code coverage:** Frontend path touched: navigation.js (9 + 10 = 19 modified lines), nav-ui.js (50+ across 5 separate sites), app.js (setActiveRoute export), style.css (B4 stack reorder). Zero backend/pipeline/setup changes.
- **Surprises:** None. Hunters' consensus across three independent passes validates the scope. B1 threshold tuning deferred cleanly. B14 upgrade from FP justified on re-read.

---

## 2026-04-20 — Nav keep-awake (feature-complete, field-untested)

**Released as:** not yet released (agent-complete on dev, awaiting §6.3 manual field acceptance before merge to main)
**Plan / spec:** [docs/superpowers/specs/2026-04-20-nav-keep-awake-design.md](../docs/superpowers/specs/2026-04-20-nav-keep-awake-design.md)
                 [docs/superpowers/plans/2026-04-20-nav-keep-awake-plan.md](../docs/superpowers/plans/2026-04-20-nav-keep-awake-plan.md)
**Adversarial reviews:** [dev/adversarial/2026-04-20-nav-keep-awake-r{1..6}-*.md](adversarial/)
**Research:** [dev/research/2026-04-20-spec-b-field-mode-research.md](research/2026-04-20-spec-b-field-mode-research.md) (parallel Spec B research for future offline-HTTPS work)

### Summary

Turn-by-turn nav silently broke on mobile when the phone auto-dimmed — not because the screen going dark is itself dangerous, but because a driver glances down to investigate a silent/dark phone, and that's the actual eyes-off-road safety hazard at driving speeds. This feature holds the device screen awake for the duration of active nav using a two-layer mechanism: `navigator.wakeLock.request('screen')` on Secure Context origins, with a first-party `SilentVideoLock` helper (plays a 2×2 no-audio-track MP4) on plain HTTP. Entirely passive to the driver — no indicator, no chime, no banner; the existing nav UI IS the evidence. Voice-continuity-under-backgrounding is explicitly out of scope for a future sibling spec.

### Key decisions

- **Bespoke silent-video helper instead of NoSleep.js.** Round 1 of the adversarial review (with the Codex cross-validation round) discovered that NoSleep.js v0.12.0 internally calls `navigator.wakeLock.request('screen')` first — meaning our "fallback" was re-invoking the same failing API on any origin where the primary rejects. Replaced with a ~60-line first-party module. Removed a 5-year-unmaintained dependency as a bonus.
- **Generation-counter race safety.** Concurrency round (R2) found three distinct orphan-lock bug classes the v1 canonical code permitted under rapid Start→Stop→Start, release-during-pending-acquire, and visibility-reacquire-during-release interleavings. Fix: monotonic `acquireGeneration` counter captured per-call, compared on await resume. Task 8's race tests verify all three scenarios empirically.
- **iOS PWA standalone-mode bypass.** WebKit #254545 silently breaks `navigator.wakeLock` in iOS 16.4–18.3 Home Screen PWA. Detection via `matchMedia('(display-mode: standalone)')` forces the fallback path on affected devices. Extended to the visibility-reacquire handler after Task 10 quality review caught that the visibility handler re-called the broken primary API without the bypass.
- **Explicit "no audio track" (not muted silence) media contract.** Codex R6 F6.4 caught that muted silence collides with `speechSynthesis` media-session routing and iOS lock-screen affordances. The MP4 is generated with ffmpeg `-an` flag (no audio stream at all); a Python test verifies via `ffprobe`.
- **Tests promoted to GitHub Actions (frontend-ci.yml)** per `feedback_env_drift_favor_ci.md` — pure-logic tests on ubuntu-latest distinct from Cameron's dev Pi, separate from wizard-ci.yml's LXD integration suite.
- **Voice-continuity deferred (user decision B).** Wake-lock reduces how often the tab is backgrounded at all (driver doesn't need to unlock to check); a proper voice-continuity spec gets its own treatment later. Stale-prompt replay explicitly rejected as NG7 — worse than silence.

### Notable bugs caught by adversarial review

- **NoSleep fallback is not a fallback** (R1 F1.1) — architectural; fix = replace with bespoke helper.
- **Orphan-lock on rapid acquire/release interleavings** (R2 F2.1/2.3/2.8) — race safety; fix = generation counter.
- **Grep-based static tests mistake presence for behavior** (R3 F3.1) — test quality; fix = brace-tracked `function_body` + `strip_js_noise`.
- **Mock fidelity underspecified** (R3 F3.7) — fix = reference mock factories in `_fixtures.js`.
- **JS test dir collision with pytest** (R3 F3.11) — fix = `frontend/tests/wake-lock/` (hyphen blocks Python import).
- **Spec meta-coherence** (R6 F6.1, Codex) — the highest-leverage finding. R1's "replace NoSleep" decision wasn't propagated through acceptance criteria, tests, dependencies — spec would have asked a subagent to ship the rejected design. Fix = full v2 rewrite before plan was written.
- **Silent video must have no audio track** (R6 F6.4) — media contract; fix = ffmpeg `-an` + ffprobe verification test.
- **iOS PWA bypass incomplete in visibility handler** (Task 10 quality review) — real bug that would silently break nav after the first tab-hide/show on iOS <18.4 PWA. Fix = hoisted `isIosPwaBypass()` helper, gated both `acquire()` and the visibility handler.

### Commits

Spec + adversarial review (before implementation):
- `0cfd989` spec v1 — immediately invalidated by R1's NoSleep.js finding
- `eb8b53b` 6 adversarial review files + Spec B research
- `0ab8bf2` spec v2 — full post-adversarial rewrite (525 → 877 lines)
- `846a722` implementation plan (16 tasks across 5 phases)

Implementation (17 commits on dev):
- `22fbc2a` Task 1 silent.mp4
- `3ea2bd7` Task 2 test fixtures
- `a473597` ffmpeg recipe fix (1×1 unworkable)
- `e2dc957` Task 3 SilentVideoLock lifecycle
- `8087dbd` Task 4 SilentVideoLock contract
- `272d156` Task 5 WakeLock scaffolding
- `95b8c5a` Task 6 fallback path
- `f6742eb` Task 7 release lifecycle tests
- `96e0ed5` Task 8 race-safety tests
- `fac58fe` Task 9 visibility handler
- `d8a2200` Task 10 iOS PWA bypass
- `c2179b4` Task 10.5 iOS PWA bypass in visibility handler (Critical bug caught in review)
- `f7fb1aa` Task 11 index.html
- `17f5cff` Task 12 nav-ui.js hooks
- `fad0385` Task 13 Python static tests
- `46a5e44` Task 14 CHANGELOG + CONTRIBUTING
- `74c979c` Task 15 frontend-ci.yml

Supporting:
- `df4ac27` CLAUDE.md clarification that Codex CLI is installed but not on $PATH (unblocks future build-robust-features runs)

### Outcome

**Tests (local, pre-merge):**
- 34/34 JS unit tests via `node --test frontend/tests/wake-lock/` (11 SilentVideoLock + 23 WakeLock)
- 13/13 Python static tests via `python -m pytest tests/test_wake_lock_static.py`
- 47/47 combined, 0 failures, 0 skips

**Deferred intentionally:**
- §6.3 manual field acceptance (real phone, driving scenarios) — the agent plan formally defers this to Cameron per build-robust-features' agent-complete ≠ ship-complete principle. PR body contains the 10-item checklist.
- Test-hardening follow-ups flagged in Task 9 quality review:
  - Empirical test for `document.visibilityState !== 'visible'` guard
  - Empirical test for generation check inside visibility handler's `.then()` — the §5.11 race the original Task 9 test sketched but couldn't wire up cleanly
  - Either remove `++acquireGeneration` from `release()` or add a test that requires it (currently belt-and-suspenders)

**Review-process observations (for transferable lessons):**
- Per-task subagent-driven-development with two-stage review (spec then quality) caught 1 Critical bug (Task 10 visibility-handler iOS PWA hole) and several Important findings that would have shipped otherwise. The per-task review step earned its cost.
- Codex cross-validation round (R6) found the single most valuable meta-level finding — spec-meta coherence — that 5 Claude-family agents collectively missed because each attacked one angle. Worth making "meta-coherence after per-angle review" a routine step for future build-robust-features cycles.
- Two implementer-flagged plan bugs found during execution: (a) `loadModule` JS-destructuring semantics silently ignoring `undefined` (Task 6), (b) `strip_js_noise` helper wiping string-literal tokens (Task 13). Both caught via DONE_WITH_CONCERNS signalling rather than silent papering-over — the right posture.


---

## 2026-04-20 — NOAA NAIP CONUS expansion (in progress)

**Released as:** not yet released (work landed on `dev` via cherry-pick; `feat/noaa-conus` worktree + branch retired 2026-04-20 per the new worktree ban)
**Plan / spec:** [docs/superpowers/specs/2026-04-20-noaa-naip-conus-expansion-design.md](../docs/superpowers/specs/2026-04-20-noaa-naip-conus-expansion-design.md) (v2, committed `0341c00`)
                 [docs/superpowers/plans/2026-04-20-noaa-naip-conus-expansion.md](../docs/superpowers/plans/2026-04-20-noaa-naip-conus-expansion.md) (committed `0e0a9ae`)
**Adversarial reviews:** 5 rounds (Codex + 4 general-purpose subagents with distinct lenses: subagent-reader, implementer-skeptic, failure-mode-hunter, operator) — transcripts in session tool-results at `~/.claude/projects/.../tool-results/bsdkk6a2n.txt` + subagent returns

### Summary

Expanding NOAA NAIP imagery from Arizona-only to all 48 CONUS + DC. Adds a bbox-based custom-area mode and a snapshot-pinned versioned catalog (P7). Brainstorm originally paused 2026-04-19 at fatigue limit after 9 decisions were locked; resumed 2026-04-20 with Sections 3-6 completed and a 5-round adversarial review that surfaced 15 MUST-FIX issues before the plan phase. Plan v1 would have broken production in at least 3 ways (import from `setup/runner.py` inside a pipeline container that doesn't mount `setup/`, filter-always-runs with a 60s timeout that fails on TX/CA, checkpoint PK that would silently dedupe NAIP border quads); v2 addresses all 15. 39-task plan with phase-level review checkpoints.

### Key decisions

- **One pipeline, two CLI entry points** (`--state` slug / `--bbox`) rather than separate scripts. Code reuse of the 3-stage parallel pipeline matters more than path purity.
- **Filter short-circuits for whole-state mode** (reversal of original "always-on filter" design). `ogr2ogr -spat` has a 60s timeout that can't handle TX/CA shapefiles.
- **P7 catalog refresh** with snapshot pinning (every pipeline run pins at Start; refresh/rollback only affect future runs). Replaces an earlier threshold-based atomic-swap that was rejected as arbitrary.
- **Disk-relative big-bbox confirmation**, peak-working-set (raw + intermediate + final), not GB-magic-number.
- **Pre-merge real-Azure test as GitHub Action** (not local harness) — env drift is Geographica's dominant bug class per 2026-04-21 beta-triage marathon.
- **Checkpoint PK = `(catalog_snapshot, state_usps, tile_filename)`** — NAIP border quads are shipped in both states' directories, and old PK of `tile_filename` alone would silently dedupe.
- **Partial-coverage policy:** pre-run uncataloged states surfaced at estimate time and explicitly acknowledged; mid-run state failure produces terminal `partial_failed` status (never silent partial coverage via TileServer auto-registration).

### Notable findings from adversarial review

- **Codex C1** (code-verified): `setup/runner.py` not in pipeline container. Would have crashed on first pipeline run. → Task 1 extracts to `scripts/common/state_bboxes.py`.
- **Codex C2**: open question #5 (snapshot pinning) was not optional — without it, estimate/start/resume can use three different catalogs. → Decision #11 revised; pipeline pins at Start.
- **R3-C1** (code-verified): v1 claim that this work closed pre-existing bugs B2/B3 was factually wrong. Those bugs target NAIP/Sentinel, not NOAA. NOAA already works. Including them would regress the just-shipped TileServer handoff fix. → §"Pre-existing bugs closed" removed from v2.
- **R1-C3**: disk model used `total_size_mb > free_disk_mb`, ignoring reproject + intermediate staging. Would strand jobs at 80% progress. → Decision #12 revised to peak-working-set.

### Commits

- `8041478` — v1 spec (dev branch, then superseded)
- `0341c00` — v2 spec (post-adversarial-review; dev branch)
- `0e0a9ae` — plan (dev branch)
- `cc03d42` — Phase 0 Task 1: extract `scripts/common/state_bboxes.py` (feat/noaa-conus)
- `519790c` — Phase 0 Task 1 follow-up: stale error message fix (feat/noaa-conus)
- `85e8dac` — Phase 0 Task 2: canonicalization table + `display_name` (feat/noaa-conus)

### Outcome (in progress — updated 2026-04-20 afternoon)

**Phase 0 complete (Tasks 1-2).** 78 tests (68 setup baseline + 10 new state_bboxes_common).

**Phase 1 complete (Tasks 3-10).** Full P7 mechanics shipped to `scripts/refresh_noaa_catalog.py`: catalog structure validator, Azure blob listing with `<NextMarker>` pagination, NOAA directory parser + tile-index HEAD check, atomic snapshot writer + symlink swap, flock-based lockfile with PID-liveness force-unlock, pipeline-running detector (for refresh/rollback gating), refresh log appender + pinning-aware snapshot pruner, and the `refresh_catalog()` orchestrator + CLI. 35 tests in `tests/test_refresh_noaa_catalog.py` (9 existing + 26 net new across Tasks 3-10). Phase 0 + Phase 1 combined: 113 tests passing in worktree.

**Known follow-up (surfaced during Task 10's live-run attempt):** the tile-index URL template assembled by `refresh_catalog()` (`{AZURE_BASE}/{dir}/tileindex/tileindex_{dir}.zip`) does NOT match NOAA's actual Azure blob layout. All 103 directory prefixes parsed correctly, but every `validate_tile_index` HEAD returned 404. A stub baseline (just the AZ entry) was committed to unblock Phase 2-4; real baseline generation is deferred to Phase 5 where the CI-tier integration test + the pre-merge GitHub Action will force discovery of the correct URL pattern. Two likely fixes: (a) per-directory blob listing with `prefix=<dir>/tileindex/` to discover the actual ZIP name, or (b) URL-pattern correction once confirmed against live Azure. Logged in Task 10's commit message (`c45a0b7`).

**Phase 2 complete (Tasks 11-18).** Pipeline refactor landed: resolver (`resolve_noaa_candidates`), per-state queue build with whole-state filter short-circuit (`build_state_queue`), unified download queue of `(snapshot, usps, filename, blob_url)` tuples (`build_unified_queue`), composite-PK checkpoint migration with `NOT NULL DEFAULT ''` transitional semantics (`_init_noaa_checkpoint` / `_record_tile_complete`), Start-time snapshot pinning (`pin_catalog_snapshot` + `_resolve_or_pin_snapshot`) with `SnapshotPrunedError` resume guard, CLI `--state` slug/USPS normalization with `--year` removed (BREAKING), and `partial_failed` terminal status via `_finalize_noaa_status`. 8 commits (`4a67164` → `eb30eb3`) plus review-closeout fix commit `3cd2e58`. 

**Phase 2 review loop** (2 rounds: Sonnet architectural + Haiku test coverage; Codex adversarial blocked by v0.118.0 CLI flag conflict — deferred to full-branch pass) surfaced 1 Critical + 3 Important issues fixed in `3cd2e58`:
- `services/search/main.py` still passed `--year` + both `--state`+`--bbox` to the CLI (would have broken every admin-initiated NOAA pipeline launch).
- `_finalize_noaa_status` clobbered `status=error` with `partial_failed` on total-failure single-state runs.
- `FileNotFoundError` (missing catalog) and `SnapshotPrunedError` (pruned resume) produced raw tracebacks instead of actionable error messages.
- `tests/test_noaa_naip.py::test_argparse_accepts_noaa_mode` validated a local parser with `--year` rather than the real CLI — test defunct, deleted.

Review notes in [dev/adversarial/2026-04-20-noaa-phase2-review.md](../dev/adversarial/2026-04-20-noaa-phase2-review.md). Pre-merge hardening deferred (Round 2 edge-case tests, `_init_noaa_checkpoint` per-tile optimization) documented there.

**Incident during Phase 2:** implementer subagent for Task 13 silently escaped the worktree and committed to `dev` (on top of the parallel agent's WakeLock work). Recovered via `git revert` on dev (`bdd3157`); all subsequent implementer prompts require a pre-flight `pwd` / `git branch --show-current` / `git rev-parse HEAD` assertion, and the controller independently verifies `git branch --contains <sha>` before accepting DONE status. Saved to memory as `feedback_worktree_escape.md`.

**Test counts:** 905 passed (pre-fix-commit) → 911 passed (post-fix, +6 new admin-endpoint tests). 27 pre-existing `test_setup_main.py` / `test_bootstrap_messaging.py` failures unchanged throughout.

**Known follow-up** (same as Phase 1): tile-index URL template still assembles `{AZURE_BASE}/{dir}/tileindex/tileindex_{dir}.zip` which doesn't match NOAA's actual Azure layout. Phase 5 integration test will force discovery via live-Azure listing. Phase 2 doesn't exercise the tile-index URL path (it builds queues from synthetic inputs in unit tests); Arizona-only runs through the legacy `NOAA_NAIP_CATALOG` dict still work because that path never touches `refresh_catalog`'s URL builder.

**Phase 3 complete (Tasks 19-26).** Admin endpoints shipped to [services/search/main.py](../services/search/main.py):

- **Task 19** `GET /admin/pipeline/noaa/estimate` extended — catalog-driven via `_load_noaa_catalog`, USPS↔slug normalization, bbox-mode state resolution, new response fields (`states`, `missing`, `placename`, `catalog_snapshot`, `intermediate_gb`, `peak_required_gb`) alongside all 12 preserved legacy fields.
- **Task 20** peak-working-set disk estimate: `intermediate_gb = raw × 0.3`, `peak_required_gb = raw + intermediate + final`.
- **Task 21** `_noaa_placename` — multi-state (≥2 cataloged OR width/height > 5°) returns `"Coverage area across AZ, UT"`; single-state + small bbox uses Nominatim reverse lookup with 3s timeout.
- **Tasks 22-25** four admin endpoints (`POST /refresh`, `POST /rollback`, `POST /force-unlock`, `GET /refresh-log`) wrapping `scripts.refresh_noaa_catalog` helpers. Rollback gates on pipeline-not-running + 404 on missing snapshot + rejects path traversal. Refresh-log returns entries reverse-chronological with per-entry `rollback_available` flag.
- **Task 26** `POST /admin/pipeline/start` extended for NOAA mode — `_noaa_peak_and_snapshot` helper gates on `acknowledge_missing` (409) and rechecks disk (507) before entering `_pipeline_lock`.

Commits on dev (Phase 3 only, in order): `c74a935` (19), `5719b3b` (20), `f20d517` (20 follow-up), `3dc72e3` (21), `b1fb1cb` (22), `53055cc` (23), `52b9d96` (24), `d347701` (25), `7159080` (23 hardening — path traversal), `8adb061` (26), `649ed3d` (review closeout).

**Phase 3 review loop** (2 rounds: Sonnet architectural + Haiku test coverage) surfaced 1 Important divergence and 2 Minor issues plus 3 Critical test gaps, all closed in `649ed3d`:
- `_noaa_peak_and_snapshot` used catalog totals while `noaa_estimate` used shapefile-refined per-bbox counts → spurious 507s on sub-state bboxes with cached `.dbf`. Extracted `_count_noaa_tiles(slugs, bbox, entries, data_dir)` shared helper.
- `_noaa_peak_and_snapshot` docstring claimed the returned `snapshot_path` was an "effective pin" — caller discards it; the real pin happens container-side. Docstring rewritten to describe the actual mechanism.
- `noaa_force_unlock` 409 used a raw result dict; other 409s use structured `{status, message}`. Standardized.
- Added 3 coverage-gap tests (malformed bbox, zero-state-intersection bbox, `invalid_parse` refresh status).

**Worktree + feat/noaa-conus branch retired (2026-04-20 PM):** after two near-miss git incidents (Task 13 implementer contaminated `dev` with a misdirected commit; a later Task 26 implementer or dispatch ran `git reset --hard feat/noaa-conus` on dev, wiping six commits of nav-remediation + wake-lock work — all recovered via reflog and restored via merge commit `5545a4c`). Worktrees are now BANNED per `CLAUDE.md §Git workflow` + `docs/pitfalls/implementation-pitfalls.md §14` (landed on dev as `9daa05f`, cherry-picked to main as `7dc2e01`). Destructive git commands are also banned (`ea07e1e`), and agents now carry moniker trailers in every commit (`c28cb35`). The feat/noaa-conus branch's unique commits (`71fef86`, `772c745`) were cherry-picked to dev with Agent trailers (`7159080`, `8adb061`); the branch and worktree were removed.

**Test counts:** 911 (end of Phase 2) → 941 on `services/search/tests/test_noaa_admin_endpoints.py` alone (+30 new Phase 3 tests after the Round-2-gap additions; the other suites remained unchanged). Two pre-existing `test_pipeline_status_m2m.py` failures persist.

**Phase 4 complete (Tasks 27-32).** NOAA admin card fully refactored in [frontend/config/index.html](../frontend/config/index.html):

- **Task 27** (`23ff95b`) — `renderNoaaBody` rewritten into a two-tab structure (Whole state / Custom area) matching the validated brainstorm mockup at `.superpowers/brainstorm/869511-1776625800/content/whole-page-flow-v4.html`. Shared `_renderEstimate` helper surfaces placename callout, missing[] banner, "I understand" acknowledgment checkbox.
- **Task 28** (`b82c3d9`) — new `GET /admin/pipeline/noaa/catalog` endpoint (in `services/search/main.py`); Whole state dropdown populated from the catalog at render time; slug-based option values (matches `_normalize_state_arg`).
- **Task 29** (`a37f4a9`) — Custom area tab shows a live indicator of the `#cfg-bbox` value (green monospace when valid, yellow prompt when empty). Scope trim documented in the entry: the mockup's full shared-Coverage-Area redesign was deferred; the existing bbox input stays in place.
- **Task 30** (`7a98433`) — peak-working-set disk gate (>85% yellow, >100% red+Start-blocked via `estBox._diskBlocked`); `acknowledge_missing` wired through `startPipeline` into the POST body; Custom-area Estimate validates bbox client-side before firing the fetch.
- **Task 31** (`37a33ad`) — collapsible "Catalog refresh history" panel inside the NOAA card: lists entries reverse-chronological from `GET /refresh-log`, per-entry `[Rollback]` button when `rollback_available` is true, "Refresh catalog now" button that triggers `POST /refresh`.
- **Task 32** (`c979205`) — `partial_failed` status branch in `renderGenericProgress` surfaces the per-state breakdown and a "Retry failed state(s)" button that starts a fresh pipeline for the failed entries (MVP: retries first failed state; multi-state retry sequential).

**Phase 4 review loop** (1 Sonnet round on JS correctness + regression risk; no browser harness available for the UI so manual visual check deferred to Cameron). Surfaced 3 Important issues, all closed in `bf83af4`:
- `#cfg-bbox` listener accumulation across repeated card-expand cycles (dedup via stashed function reference + `removeEventListener`).
- HTML-injection surface in Task 32's retry-list `li.innerHTML` where a backend error string could render raw tags (rebuilt via `createElement` + `textContent`).
- Whole-state Estimate fell through to a 422 on empty bbox (mirrored the Custom-area tab's client-side 4-float isFinite pre-check).

**Pending: Cameron's manual visual check** of the live admin UI against the mockup. The tests green (32 passing in `services/search/tests/test_noaa_admin_endpoints.py`) don't exercise the DOM — the admin panel lacks Playwright/jsdom infra, documented as a Phase 4 follow-up.

**Phase 5 complete (Tasks 33-37).**

- **Tile-index URL pattern fix (`4ffd658`).** Task 10's template `{AZURE_BASE}/{dir}/tileindex/tileindex_{dir}.zip` never matched NOAA's real Azure layout — every HEAD returned 404. Live-listing verified the actual pattern across four independent directories (AZ/AL/AR/CA): the zip is `tileindex_{USPS}_NAIP_{year}.zip` in the directory root (no `/tileindex/` subdir, no trailing hash). Fix lands in `scripts/refresh_noaa_catalog.py`; Task 35's integration test now regression-guards it.
- **Task 33 (`5c82fda`)**: synthetic tile-index shapefiles at `tests/fixtures/noaa_tile_indexes/{arizona,utah}_test.shp` + helper. Both shapefiles include `m_border.tif` to exercise the composite-PK checkpoint case. Helper script has 4 fallbacks (osgeo → ogr2ogr-cli → pyshp → raw binary) — on this Pi the osgeo path isn't pip-installable, so the script uses the CLI path.
- **Task 34 (`d192624`)**: Azure XML fixture set extended with `empty_container.xml` + `mixed_valid_invalid.xml` alongside the three existing Task 4 fixtures.
- **Task 35 (`89e27ba`)**: `tests/integration/test_noaa_multistate.py` — 9 tests covering refresh → resolver → queue → checkpoint end-to-end against mocked Azure. Includes an explicit regression guard for the URL pattern fix.
- **Task 36 (`f9fd810`)**: `.github/workflows/noaa-real-azure.yml` — manual-dispatch only (weekly cron deliberately commented out until Cameron confirms runtime budget). Refreshes catalog against real Azure, spot-checks the resulting entries, resolves a Four Corners bbox and asserts AZ/UT/CO/NM are all accounted for. Uploads refreshed catalog.json as a 7-day artifact.
- **Task 37 (`f9fd810`)**: new "Catalog refresh (NOAA)" section in `dev/harness/exploratory_agent/bug_classes.md` with four actionable symptoms: fewer-states-than-expected, URL-pattern drift, stale symlink after rollback, dead-PID lockfile discoverability.

**Phase 5 review** (1 Haiku round on URL correctness + integration-test rigor + fixture completeness + GH Action safety + seed quality) — approved, no fixes required.

**Phase 6 complete (Tasks 38-39).**

- **Task 38 (`994363d`)**: `tests/test_noaa_semantic_equivalence.py` — three env-gated regression tests that compare a pre-refactor baseline MBTiles against a post-refactor Arizona run. Equivalence is NOT byte-for-byte; it's tile-count-by-zoom + metadata-key subset + SHA256 hash match on a 10-point probe grid at z15. Tests skip gracefully when `GEOGRAPHICA_NOAA_BASELINE_MBTILES` / `GEOGRAPHICA_NOAA_CURRENT_MBTILES` are unset. Docstring documents the manual baseline-capture workflow.
- **Task 39**: verification only — `tests/test_setup_runner.py` still passes 68 tests post-extraction of `STATE_BBOXES` to `scripts/common`. No new test required.

**All 39 tasks shipped.** Branch `dev` commits ahead of `origin/dev` at closeout: Phase-0 → Phase-6 inclusive.

**Test counts at Phase-6 closeout:** 1005 passed, 4 skipped (3 new `test_noaa_semantic_equivalence.py` + 1 pre-existing), 30 pre-existing failures unchanged (`test_setup_main.py`, `test_wake_lock_static.py`, `test_pipeline_status_m2m.py`).

**Known follow-ups (documented in plan + reviews):**
- Phase 4 manual visual verification against `.superpowers/brainstorm/869511-1776625800/content/whole-page-flow-v4.html` — the admin panel has no headless browser test infra; Cameron to validate the NOAA card's six tabs / buttons / banners interactively before merge to main.
- Task 38 baseline capture — run a pre-refactor AZ whole-state pipeline once to produce `noaa_az_baseline.mbtiles`, then run current-tip code against the same state for comparison. Both pipelines take ~20-40 min each and ~39 GB disk.
- Task 36's weekly cron schedule — still commented out; enable after one manual dispatch confirms the runtime budget.
- Pre-merge hardening items from Phase-2 Round-2 review (edge-case test coverage for snapshot non-string values, CLI whitespace, partial migration states) and Phase-4 Round-1 review — all non-blocking for merge but worth closing before the release PR.

**Integration path to `main`.** The branch is now plain `dev`; no feature branches remain. The normal release-please PR flow merges dev → main. Cameron: when ready, merge the Release PR at `origin/release-please--branches--main` to cut the next version. Given the BREAKING CHANGE footer on commit `bf27867` (`--year` removed from `acquire_imagery.py`), release-please will propose a major bump.


---

## 2026-04-19 NIGHT — Beta-tester preflight unblocker + wizard harness rebuild

**Released as:** `fix(setup): unblock beta testers stuck in preflight + bootstrap loops` (commit `5e400c5` on main). Harness rewrite lands with this commit on main.
**Plan / spec:** none — single-session debug off a beta-tester screenshot (docs/123_1 (7).jpeg).
**Bug hunts:** none — all found through the harness rewrite.
**Adversarial reviews:** none.

### Summary
Every beta tester attempting to set up Geographica since the 2026-04-19
setup-remediation landing hit a hard wizard-level block: preflight's
"Python pipeline deps" check reported `Missing: rasterio, shapely, scipy,
numpy` on every Pi, regardless of bootstrap success or reboot. The
wizard's "remedy" box told them to re-run `sudo ./bootstrap.sh` in what
was effectively an infinite loop. One beta tester looped this ~16 times
before giving up; another rebooted and still hit the same error.

Root cause (confirmed against beta tester's screenshot + end-to-end LXD
reproduction): the wizard's preflight check used in-process
`__import__('rasterio')`, which runs inside `setup/.venv` — the venv
setup.sh creates. That venv does NOT inherit the user's `~/.local/...`
where bootstrap's `pip install --user --break-system-packages` places
those packages. So the check ALWAYS reported missing on every Pi, forever.

Fix: preflight now shells out to `/usr/bin/python3 -c 'import <pkg>'` so
the check reflects the actual user environment bootstrap targeted, not
the venv. 6 regression tests in `tests/test_preflight_python_deps.py`
guard against the bug coming back.

Also shipped alongside:
- **bootstrap.sh curl/gpg prereq.** Bootstrap consumed `curl` + `gpg`
  for Docker repo setup BEFORE installing them. Fine on raspios Full
  (preinstalled) but broke on minimal Debian / raspios Lite.
- **bootstrap.sh completion-message overhaul.** Beta tester literally
  reported "exiting a screen and opening a new one counts as logging
  out, right?" — it doesn't. New message spells out 4 concrete options
  (reboot / ssh exit+reconnect / console logout / `newgrp docker`)
  and names what does NOT count. Includes a `groups` verification step.
- **setup.sh diagnostic message.** Distinguishes "Docker not installed"
  from "installed but your shell isn't in the docker group" and gives
  a specific fix for each (previously offered both as a list, asking
  the beta tester to guess).

Post-fix, the LXD harness got the rebuild it's needed since v1.0:

- **`dev/harness/drive-wizard.mjs` full rewrite.** Before: waited for
  `#step-4` selector, exited 0. Asserted nothing. After: asserts no
  error banners at any step boundary, no raw Python tracebacks in
  the DOM, preflight all dots are `.ok` (with a named exclusion for
  known-environmentally-unavoidable failures), `#btn-next` enabled
  + text appropriate, no pageerror / console.error events. RED-tested
  by injecting a bogus package into the preflight list — harness
  correctly failed with `ASSERT FAIL: 1 preflight check(s) failing`.
- **`dev/harness/wizard-ci.sh` fixes.** Four LXD-version bugs
  discovered during the rewrite: `lxc file push -r` syntax changed
  (swapped for `git ls-files | tar`); `lxc exec ... & ` never
  detaches (swapped for `systemd-run --unit=...`); setup.sh binds
  127.0.0.1 inside container, unreachable from host (added LXD proxy
  device on port 18099); cloud-init wait blocked on raspios
  (non-cloud-init images — now handles `done`/`disabled`/missing +
  installs systemd-networkd if eth0 has no IPv4).
- **`--image=ALIAS` + `--pre-state=NAME` flags** let the same harness
  run against Debian cloud, raspios, or arbitrary pre-conditioned
  environments.
- **`dev/harness/import-raspios.sh`**: one-shot importer that
  downloads latest raspios-lite-arm64, extracts the root partition,
  creates an LXD metadata tarball, imports as alias `raspios-trixie-lite`.
  Idempotent; cached.
- **`dev/harness/wizard-matrix.sh`**: iterates every `pre-states/*.sh`,
  runs a full wizard walkthrough per pre-state, fail-surfaces all
  failures in one run.
- **`.github/workflows/wizard-ci.yml` upgraded** from manual-dispatch
  only to: smoke mode on every push/PR to `main` or `dev` touching
  the setup code paths, plus manual-dispatch for `matrix`,
  `matrix-raspios`, and `full` modes.

### Notable bugs caught

- **Preflight python-deps infinite loop** (beta-blocker, 5e400c5).
- **LXD bridge down, NAT flushed by Docker** — the harness wouldn't
  run on this Pi AT ALL. Fixed with a `DOCKER-USER` ACCEPT rule +
  systemd unit for persistence (`lxd-docker-bridge.service`).
- **Old harness claimed to exercise the wizard but didn't.** Smoke
  mode exited as soon as `#step-4` rendered — never read any status.
  Every preflight regression since v1.0 would have slipped past.

### Why the 50-task setup-remediation missed the preflight bug

That plan focused on making bootstrap CORRECT; it assumed the wizard's
preflight check (set up well before the plan) was already correct.
In the beta-tester failure mode, bootstrap actually worked — the
wizard's check was broken. No number of bootstrap-focused tests would
catch it, and our LXD harness didn't assert anything beyond DOM-load.
The rewrite fixes the class — any future preflight regression will
fail CI instead of beta.

### Commits

- `5e400c5 fix(setup): unblock beta testers stuck in preflight + bootstrap loops` — setup/main.py + tests + bootstrap.sh curl prereq + completion msg + setup.sh diagnostic (on main).
- (this commit) `test(harness): real assertion-bearing wizard harness + raspios + pre-state matrix + CI gating` — harness rewrite + import-raspios.sh + wizard-matrix.sh + workflow update.

### Outcome

- **Beta testers unblocked**: 5e400c5 is on main. `git pull && sudo ./bootstrap.sh` (or just `./setup.sh` if bootstrap already succeeded) now proceeds past preflight.
- **Harness on the gate**: push to `main`/`dev` now runs the assertion-bearing smoke mode. Before: manual dispatch only + smoke-mode that passed even on the broken wizard.
- **One concrete known-limitation surfaced to a follow-up**: `--image=raspios-trixie-lite` launches the container fine and bootstrap's apt phase completes, but `systemctl start docker` inside raspios-LXD fails with "Job for docker.service canceled" after bootstrap edits `/boot/cmdline.txt` for cgroup_enable=memory. Does not affect the Debian-cloud smoke gate. Deferred for separate debug session.

---

## 2026-04-19 EVE — Trixie docker file-conflict: fix + pre-state harness

**Released as:** fix on `dev` (commit `59f00b5`); matrix landing with this commit.
**Plan / spec:** none — single-session debug + fix.
**Bug hunts:** none — the three 2026-04-18 setup hunts missed this (see "Why internal missed it" below).
**Adversarial reviews:** none.

### Summary
Every beta tester on Raspberry Pi OS Trixie with any prior Docker
attempt (`apt install docker.io`, `get.docker.com`, or `apt
full-upgrade` with docker.io on it) was hard-blocked at `./bootstrap.sh`
with a dpkg file-conflict. Debian 13 Trixie started shipping native
`docker-buildx` (0.13.1+ds1-3) and `docker-compose` (2.26.1-4) packages
that physically own the same paths as Docker's official
`docker-buildx-plugin` / `docker-compose-plugin`
(`/usr/libexec/docker/cli-plugins/docker-{buildx,compose}`); neither
side declares `Replaces`, so if either Debian package was installed,
our `apt install docker-ce ... docker-compose-plugin` aborted
mid-unpack. Observed tester looped bootstrap 16× before giving up
(docs/123_1 (6).jpeg). `apt --fix-broken install` couldn't help:
it only resolves dependency issues, not filesystem overwrites.

Fixed in `fix(setup)` 59f00b5: bootstrap now runs Docker's official
"Uninstall old versions" prerequisite step before the docker-ce
install. Idempotent (no-op on clean systems) so the internal dev
Pi and the LXD harness stay green.

Post-fix, built `dev/harness/bootstrap-matrix.sh` — an apt-level
pre-state matrix that runs bootstrap's `[1/6]` block in ephemeral
Debian 13 Docker containers against realistic customer starting
states (clean / `debian-docker-buildx` / `docker-io` /
`get-docker-com`). Fails CI if any pre-state regresses.

### Key decisions

- **Use `apt remove`, not `apt purge`.** Removing Debian's docker.io
  is the minimum needed to unblock docker-ce install; purging would
  wipe `/etc/docker/` and any user-created configs. `apt remove`
  leaves packages in `deinstall ok config-files` state, which
  satisfies dpkg's path-ownership constraint (binaries gone). The
  matrix's post-condition check had to handle this subtlety —
  `dpkg -s <pkg>` returns 0 for both "install ok installed" AND
  "deinstall ok config-files"; only the former is a regression.

- **Docker-based matrix, not LXD-based.** LXD is the right tool for
  the full wizard E2E (it exercises systemd + ports + Playwright).
  For apt/dpkg state verification, Docker containers start in ~1 s
  vs. LXD's ~15 s and don't require a bridge + NAT config. All four
  pre-states complete in ~10 min in Docker. Fewer moving parts =
  fewer CI flakes. The LXD harness (`wizard-ci.sh`) still owns the
  full wizard path.

- **Extract bootstrap slice via awk, not by copying or flag-gating.**
  The matrix runs the real `bootstrap.sh` source (no duplicated
  code; no test-mode flag on bootstrap itself). awk extracts the
  `[1/6] ... [2/6]` range at runtime. If the banner format ever
  changes, the matrix fails fast with a clear error.

### Notable bugs caught

- Beta-tester blocker (dpkg file conflict) → caught by the user
  uploading `docs/123_1 (5).jpeg` + `(6).jpeg` from the latest
  beta round → fixed in `fix(setup)` 59f00b5.
- Matrix post-condition false-positive: `dpkg -s docker.io`
  returns 0 for `deinstall ok config-files` too → caught by the
  `docker-io` pre-state failing in matrix runtime → fixed in the
  same commit as the matrix landing.

### Why internal missed it

Five independent reasons the signal was a false negative — saved
in memory as `feedback_test_harness_mirror_reality.md`:

1. **Internal dev Pi is a cherry-picked environment.** `dpkg -l
   docker-buildx docker-compose` → both "not installed" on our Pi.
2. **LXD harness uses `images:debian/trixie/cloud`.** Minimal cloud
   image, zero preinstalled Docker packages → our happy-path test
   never sees the conflict.
3. **Harness only exercised one starting state.** No pre-state
   matrix before today.
4. **Setup-remediation plan had a structural blind spot.** 4950 lines,
   50 tasks, zero mentions of `docker-buildx`, `purge`, or
   `file conflict`. Plan assumed a clean target.
5. **Bug hunts were static.** All three 2026-04-18 setup hunts read
   bootstrap.sh as source code; none ran it against a customer-like
   starting state.

### Commits

- `59f00b5 fix(setup): purge Debian-native docker packages before docker-ce install` — TDD: failing test + fix + end-to-end Docker verification that without the fix the beta error reproduces and with it bootstrap completes clean.
- (this commit) `test(harness): bootstrap pre-state matrix (Trixie docker conflict regression guard)` — `dev/harness/bootstrap-matrix.sh`, 4 pre-states, 8 canary pytests, README update.

### Outcome

- `fix(setup)` landed on `dev` and pushed to `origin/dev` so beta testers could `git pull && sudo ./bootstrap.sh` immediately for weekend-availability testing.
- 12/12 unit tests on the fix + matrix passing.
- Full 4-pre-state Docker matrix: 4/4 PASS in 605 s end-to-end.
- Follow-up queued: Tier 2 full-wizard LXD matrix (`wizard-ci.sh --pre-state=NAME`), currently blocked by LXD bridge being DOWN + NAT flushed by Docker on this host; needs a host networking fix before wiring up.

---

## 2026-04-19 PM — TileServer auto-restart on clean pipeline completion

**Released as:** not yet released (on `dev`, pending merge)
**Commit:** `f6f7365` (single commit, 2 files, +312 / −37)
**Bug hunt:** [dev/bug-hunts/2026-04-17-pipeline-completion-review.md](bug-hunts/2026-04-17-pipeline-completion-review.md) §Bug 1

### Summary
Long-standing bug where the map never auto-updated after a pipeline run finished cleanly. The admin service's reconciliation guard at `services/search/main.py:1473` only entered the WAL-checkpoint + TileServer-restart path when the pipeline had CRASHED (`status in ("running", "cancelling") and not container_running`). But every pipeline script writes `status="completed"` to the state file itself *before* the container exits, so the guard was false on clean exits and TileServer was never restarted. Widened the guard to include terminal states (`completed` / `completed_partial`) that have not yet been handed off — tracked via a new `tileserver_restarted_at` stamp on the state file that makes repeat polls no-ops. Runtime-validated live against the stuck Phoenix NOAA run.

### Key decisions
- **Idempotency via state-file stamp, not a background watcher.** Considered a dedicated `/admin/pipeline/finalize` endpoint or a docker-event-driven watcher. Stamp approach is minimally invasive (no new endpoints, no new threads), self-healing (swept a stuck elevation state as a side effect), and fires exactly once per run.
- **Dropped `PRAGMA journal_mode=DELETE`** from the search-service checkpoint. D3 (already shipped on dev) deliberately keeps WAL mode permanently; flipping to DELETE can fail against TileServer's live read-lock during handoff. TRUNCATE checkpoint alone suffices.
- **TDD end-to-end.** 5 new tests covering clean-completion, idempotency, `completed_partial`, and crash-path regression. Watched all fail first; implemented fix; watched all pass. No production behavior untouched by a test.

### Notable bugs caught
- 2026-04-17 §B1 (TileServer Never Restarted After Pipeline Completion) → `f6f7365`
- Symlink-hijack by pytest Task 42 fixture (parallel agent found + fixed as `a2cf6dc`) — not a Claude bug but surfaced during runtime validation.

### Commits
- `f6f7365` — fix(search): restart TileServer on clean pipeline completion (B1 2026-04-17)

### Outcome
- 5 new tests pass; full suite 784 passed (same 2 pre-existing M2M failures, 18 pre-existing env errors).
- Runtime validation on the actual stuck Phoenix state: `tileserver_restarted_at: 2026-04-19T12:57:25Z` written to `.pipeline-state.json`; TileServer StartedAt jumped `12:57:25 → 12:57:55`; `/data/imagery_noaa.json` now serves correct bounds + z9-17; sample tile `/data/imagery_noaa/9/93/202.jpeg` serves 200 OK 18.6 KB JPEG. Second poll idempotent (no double-restart). Self-healed `.elevation-state.json` as a bonus.
- Deferred (each a separate follow-up): B2 (NAIP/Sentinel state-file misnaming), B3 (NAIP/Sentinel missing from TileServer config), B6 (MapLibre base-imagery TileJSON cache).

---

## 2026-04-19 — Setup process remediation (v1.2 cycle)

**Scope:** 48 confirmed bugs (B1-B48) + 8 design decisions (D1-D8) + 3
out-of-scope items (O1-O3) across setup/main.py, setup/config.py,
setup/runner.py, setup/static/*, bootstrap.sh, docker-compose.yml,
nginx/entrypoint.sh, README.md.

**Outcome:** Wizard path is now end-to-end working on a fresh Debian
Trixie LXD container (verified via dev/harness/wizard-ci.sh --smoke).
Every .env VAR that docker-compose.yml references is emitted by
generate_env. TLS vocabulary canonicalized to http|https|tailscale.
Credentials flow through the keyring Unix socket (no more JSON
plaintext). PIPELINE_STEPS lifted to a frozen dataclass registry with
per-step command builders. Install-location UI finally wired through
to the running stack via symlink re-target on launch.

**Highlights:**
- New dev/harness/{wizard-ci.sh, drive-wizard.mjs} for regression
  testing the full setup flow in LXD.
- tools/build-tippecanoe.sh + bootstrap asset-download to eliminate
  the public-lands CAPTCHA + tippecanoe-from-source blockers.
- Shared showError helper in setup.js; all saves now awaited before
  navigation.
- Preflight now covers tippecanoe, python pipeline deps, keyring
  agent socket, cgroup memory, openssl. No more /api/fix-dependency
  (users re-run sudo ./bootstrap.sh with copy-paste).
- Memory profile retuned to "good neighbor" ceilings leaving 3-4 GB
  host headroom (Cameron's architectural call during execution).
- Process rigor (3-agent subagent-driven-development workflow) caught
  several plan-level inconsistencies: tippecanoe 2.80.0 upstream-
  missing, sudo -H missing for pip --user, test-class misclassification,
  keyring socket protocol mismatch.

**Deferred to v1.2 appendix (B44-B48):** response-shape unification,
preflight row-level UI nit, stderr color coding, tls-scan tool-missing
signal, post_credentials empty-field semantics (partially covered
already by skip-empty in Task 23).

**Pitfalls added to dev/testing-pitfalls.md:** TOCTOU in async
endpoints (from Task 30).

---

## 2026-04-19 — GX-01 adapter HAT: JLC bundle correctness + mechanical design paused

**Released as:** ongoing (internal hardware work; no user-facing release)
**Plan / spec:** [docs/superpowers/plans/2026-04-18-gx-01-pcb-completion.md](../docs/superpowers/plans/2026-04-18-gx-01-pcb-completion.md) (Phase 0 paused; see Status block)
**Design doc:** [hardware/gx01-path-c-mockup.html](../hardware/gx01-path-c-mockup.html) (open in a browser)

### Summary
User attempted to upload `hardware/gx01-adapter-pcb/jlc_bundle.zip` to JLCPCB; three rounds of 3D preview review caught distinct issues: (1) all components offset ~60 mm above the board outline due to Y-sign in CPL, (2) J1/J2 large headers placed ~24 mm off due to using footprint anchor instead of pad-bbox-center, (3) four LCSC parts physically mismatched their footprints (lead pitch, pin count, B2B-vs-S2B sub-variant). All three classes fixed. Final bundle verifies clean and ships 7/7 parts correctly placed in JLC's viewer. Then a mechanical concern surfaced: the adapter HAT's top-surface connectors (J2 at ~11 mm + ribbon) exceed the case's ~10 mm top-plate clearance. Iterative mockup and dimensional analysis produced two viable paths (A: taller case, C: flip J2 to B.Cu and sandwich with LCD); decision formally deferred until X1100 (arriving 2026-04-19) and SparkFun LCD-00710 (~1 week) are in hand to measure.

### Key decisions
- **CPL positions come from `pcbnew` pad-bbox centers, not `kicad-cli pcb export pos`.** `kicad-cli` passes the footprint anchor through unchanged; the KiCad GUI has a "Use pad origin as reference" toggle that isn't exposed in the CLI. For JLC CPL "Mid X/Mid Y" correctness, we must compute pad bbox centers ourselves in `pcbnew`.
- **Trust the JLC catalog description over the 3D preview.** R1's preview rendering looked suspicious but the description (`Plugin,D2.4xL6.3mm`) confirms it matches our DIN0207 footprint. Placeholder 3D models are common for Extended-tier THT parts. Kept C1370997 unchanged.
- **Design decision deferred pending hardware.** Both Path A (case +20 mm height, keep PCB) and Path C (flip J2 to B.Cu, LCD+HAT sandwich) are mechanically viable. Committing to Path C costs a PCB refab (~$80, ~14 days); Path A costs case proportions. Decision needs physical measurements of X1100 + LCD to confirm the vertical void budget above the X1207 battery cradle.
- **Don't delete the bug-hunt evidence.** JLC 3D preview screenshots (`hardware/jlc_misalignment_v{2,3,4}.jpg`) committed as design history — they're the only record of what the three misalignment classes looked like.

### Notable bugs caught
- **CPL Y-sign flip** — KiCad internal coords are Y-down, Gerbers and JLC CPL expect Y-up. Components rendered ~60 mm above the board outline in the JLC viewer. Fixed by applying `Y = -Y` in the CPL generator.
- **Anchor-vs-center offset for THT headers** — `pcbnew.FOOTPRINT.GetPosition()` returns the anchor (pin 1), but JLC's "Mid X/Mid Y" expects the geometric pad center. For a 2×20 header this was 24 mm off. Fixed by iterating pads and merging bounding boxes.
- **LCSC part mismatch against footprint (×4)** — `verify_lcsc.py`'s THT-vs-SMD heuristic doesn't check pin count, lead pitch, or connector sub-variant. C254085 (5.08 mm pitch vs our 2.5 mm), C124378 (4-pin vs 1×20), C146125 (S-series side-entry vs B-series top-entry). All 4 were clean per the existing verification; all 4 physically wouldn't have fit. `verify_lcsc.py` hardening noted as follow-up.

### Commits
- `fix(hardware): correct JLC bundle CPL geometry and LCSC part selections` — pad-bbox-center computation, Y-axis flip, 4 LCSC part swaps (C254085→C524651, C124378→C50981, C146125→C158012 for J3 and J4)
- `docs(hardware): pause GX-01 PCB completion pending X1100+LCD arrival` — Plan 3 status block, Path C mockup, JLC preview screenshots, this implementation-log entry

### Outcome
- 7/7 parts verify clean against JLC's live catalog via `verify_lcsc.py`.
- `jlc_bundle.zip` regenerated (33 KB, 11 files); BOM and CPL confirmed matching via diff against `kicad-cli pcb export pos`.
- PCB work paused for ≤1 week awaiting hardware; resumption criteria documented in [session handoff memory](../../../home/administrator/.claude/projects/-home-administrator-Code-geographica/memory/handoff_20260419_gx01_cpl_path_c.md) (out-of-repo).

---

## 2026-04-18 — NOAA Imagery Pipeline Remediation (on dev, awaiting runtime validation)

**Released as:** not yet released — all 13 commits on `dev` only, pending end-to-end validation on a Flagstaff-size bbox after the current ~494-quad production pipeline finishes (~2026-04-19)
**Plan / spec:** [dev/plans/2026-04-18-noaa-imagery-pipeline-remediation-plan.md](plans/2026-04-18-noaa-imagery-pipeline-remediation-plan.md)
**Bug hunts:** [dev/bug-hunts/2026-04-18-noaa-imagery-pipeline-consolidated.md](bug-hunts/2026-04-18-noaa-imagery-pipeline-consolidated.md) (+ exploratory/holistic/multipass individual reports)
**Adversarial reviews:** 5 prior reports at `dev/adversarial/2026-04-16-*.md` (used as reference only; not authoritative for this cycle)

### Summary
Fresh 3-hunter bug-hunt cycle on the imagery pipeline (5161 LOC) because OOM crashes since the 2026-04-16/17 adversarial review may have caused the then-deferred 9-item list to drift. Result: 16 confirmed bugs (11 new) + 6 design decisions. Scope-locked to 13 bugs + 3 design decisions (B6, B8 deferred for Chesterton's Fence — they'd re-touch `e7e3b32` and `1bab361` code that fixed user-observed imagery artifacts; D4/D5/D6 deferred for scope). All 13 executed via subagent-driven development on `dev`, each fix behind its own commit. Ship deferred pending runtime validation — a production NOAA run is currently blocking the Pi.

### Key decisions
- **Fresh hunt over re-validating the stale deferred list.** Prior 9 deferred items were from 2026-04-16 review; many OOM crashes since could have landed fixes without session notes. New hunt found 11 bugs absent from the old list — the instinct to re-run was right.
- **Chesterton's Fence on B6 and B8.** Hunters flagged `merge_mbtiles` compositing and erosion-after-overview ordering, but commits `e7e3b32` and `1bab361` added those behaviors *specifically* to fix user-observed imagery loss / black quadrant artifacts. Deferred both pending visual-regression testing on a small bbox.
- **Source-inspection tests for Phase 5 rewrite.** Task 9 combines B1 + D1 + D3 with 4 cancel-guard sites, erosion gating, WAL-mode keep-forever. Real end-to-end tests would require mocking gdaladdo + rasterio + interrupting mid-operation — out of scope for this cycle's test harness. Tests verify *code shape* (string presence) not *runtime behavior*. This is named technical debt to revisit.
- **Don't ship to main until live-tested.** Per Cameron's judgment: 13 commits on `dev` + runtime validation later > 13 commits on `main` now + debugging the next NOAA run.

### Notable bugs caught
- **B8 (erosion-after-overview)** — matches `docs/flagstaff_rendering_issue.jpg`. Deferred pending validation.
- **B6 (merge_mbtiles re-composites every overlap)** — progressive JPEG generation loss at quad boundaries. Deferred.
- **B1 (cancel ignored during Phase 5)** — user-visible UX bug: cancel click ignored for 30+ minutes of post-processing. Task 9, commit `48092e6`.
- **B9/D1 (erosion non-idempotent on resume)** — incremental bbox expansion could silently delete valid tiles. Task 9, commit `48092e6`.
- **B14 (wrong MBTiles WAL-checkpointed for elevation)** — only bug outside `scripts/`. Task 4, commit `38b9d32`.
- Plan's own self-inconsistency (explanatory comment contained forbidden string the test asserted against) — caught by Task 9 implementer; reviewer validated rephrase was correct.

### Commits (on dev, not yet on main)
Filtered to remediation work (Cameron's concurrent hardware commits excluded):
- `aace75c` — fix(pipeline): capture rasterio src dims before with exits (B3)
- `ffb93f3` — fix(pipeline): reject fully-out-of-bounds tiles in rasterize (B4)
- `6f26ed5` — fix(pipeline): count composite errors in merge_mbtiles (B7)
- `38b9d32` — fix(search): target WAL checkpoint by pipeline type, not mode (B14)
- `d943968` — fix(pipeline): detect short-reads and reuse cached staging tiles (B10, B11)
- `c619ec4` — fix(pipeline): write progress on _merger failure branches (B12)
- `e8f5f2b` — fix(pipeline): honor cancel during M2M overview build (B2)
- `fc7e03d` — fix(pipeline): share cancellable GDAL subprocess wrapper (B5)
- `48092e6` — fix(pipeline): cancel guards + WAL mode + no-erode-on-resume in NOAA Phase 5 (B1, B9, D1, D3)
- `6e253be` — fix(pipeline): add completed_partial status for NOAA runs with failures (D2)
- `8aa827c` — fix(pipeline): detect _noaa_checkpoint divergence from tiles table (B13)
- `b1086ab` — refactor(pipeline): write progress state once per call (B15)
- `1f77a70` — fix(pipeline): wire NAIP --concurrency via asyncio.gather (B16)

### Outcome (as of 2026-04-18)
- **624 tests pass** on `dev` (up from 596 baseline → 28 new tests for this cycle); 2 + 9 pre-existing failures unchanged — no regressions introduced by any of the 13 fixes.
- **Production NOAA pipeline currently running** with the *old* code (Python imports happened at startup; disk edits don't affect an in-flight process). Expected completion ~2026-04-19.
- **Runtime validation pending:** once production pipeline finishes, run a Flagstaff-size bbox (~10 quads) with the new code, visual-diff the output against a known-good baseline, then merge `dev` → `main` to feed Release PR #2.
- **Deferred follow-ups:** B6 + B8 (need visual-regression proofing before fixes land); D4/D5/D6 (architectural cleanups out of this cycle's scope). Fully documented in the remediation plan's appendix.

### Resume instructions for tomorrow
1. Confirm current production pipeline has completed cleanly.
2. Run `python -m pytest tests/ services/search/tests/ -v` — expect 624 pass, 2 + 9 pre-existing.
3. Execute a validation run on a small bbox (Flagstaff, e.g. `-112.0,35.1,-111.5,35.4`) with the new code. Verify: pipeline completes, tiles render correctly at all zooms, cancel mid-Phase-5 is honored, resume run doesn't re-erode valid tiles.
4. If validation passes: `git switch main && git merge --ff-only dev && git push origin main`. Release PR #2 will update with the 13 new fixes.
5. If validation reveals an issue: identify the specific task → `git revert <sha>` on dev → iterate.
6. After v1.1.0 ships, revisit B6 + B8 with proper visual-regression tests.

---

## 2026-04-18 — Version Control Strategy Adoption

**Released as:** to be included in v1.1.0 (opened retroactively by
`release-please` on first run)
**Plan / spec:** [docs/superpowers/specs/2026-04-18-version-control-strategy-design.md](../docs/superpowers/specs/2026-04-18-version-control-strategy-design.md)
                 [docs/superpowers/plans/2026-04-18-version-control-strategy.md](../docs/superpowers/plans/2026-04-18-version-control-strategy.md)
**Bug hunts:** none (pure documentation + CI work)
**Adversarial reviews:** none; CVErt-Ops reference survey informed design
(see `Key decisions`)

### Summary
Formalized Geographica's versioning regime: SemVer with project-specific
breaking-change rules (the user's data directory and un-edited infra
files are the contract), Conventional Commits enforcement via
`release-please` GitHub Action, lazy release branches, CHANGELOG and
UPGRADING docs, AGENTS.md mirror of CLAUDE.md for non-Claude harnesses,
and this implementation log as the narrative companion to CHANGELOG.

### Key decisions
- **SemVer, not CalVer or custom.** Matches stack upstreams (Docker,
  nginx, MapLibre, Valhalla). Lowest cognitive load for future users.
- **One-line rule for MAJOR bumps:** "If a user with a working install
  has to edit a file to upgrade, that's a MAJOR." Mechanical, no
  judgement calls at midnight.
- **release-please over git-cliff.** Cameron delegates commits to AI
  agents, so the commit-discipline cost of strict Conventional Commits is
  zero. That inverts the usual calculus: the bureaucracy-saving bot wins
  decisively for a time-constrained solo dev. `git-cliff` remains the
  escape hatch if GitHub Actions setup hits friction.
- **Lazy release branches.** Tag `main` by default; create `release/X.Y`
  only when a critical hotfix is actually needed. No dormant branches.
- **No phase framing.** Considered during brainstorming after surveying
  CVErt-Ops (github.com/scarson/CVErt-Ops). Rejected because
  date-stamped plans + SemVer + CHANGELOG + this log already cover every
  benefit phases would provide. CVErt-Ops uses phases as their *only*
  organizing frame because they have no releases; Geographica does, so
  phases would be redundant.
- **Fresh CHANGELOG at v1.0.0.** Pre-1.0 commits were experimental;
  retroactive CHANGELOG would be revisionist and noisy.

### Notable bugs caught
- Spec self-review caught off-by-one in deliverable count (said "8" new
  files, actual count was 9) and rollout commit count (said "four",
  actual "five"). Fixed inline before user review.
- Spec claimed release-please would not open a Release PR on first run
  "because no `feat:`/`fix:`/`perf:` commits are present yet." Actually
  false: the 6+ post-v1.0.0 NOAA hardening commits already on main are
  qualifying. Corrected before writing implementation plan; the
  retroactive v1.1.0 Release PR is now a deliberate outcome rather than
  a surprise.

### Commits
- `60d6f63` — docs: add version control strategy design spec
- `afb360d` — docs: correct spec prediction of first release-please run
- `0bb6d1a` — docs: add version control strategy implementation plan
- `5191996` — docs: adopt semver and conventional commits
- `da8f0c3` — docs: add implementation log with seed entries
- `627ff1e` — docs: align continuation line in 2026-04-18 implementation log entry
- `8bcd056` — docs(claude): add project ethos, commit discipline, and mirror to AGENTS.md
- `f1292f9` — ci: add release-please workflow for automated versioning
- `40d8175` — docs: mark versioning strategy complete in START.md
- `09ef5ce` — docs: record 2026-04-18 regression check in implementation log

### Outcome
- 2026-04-18 regression check: 579 tests pass, 2 pre-existing M2M failures + 9 pre-existing OSM POI errors (unchanged from 2026-04-17).
- First release-please workflow run on `main` failed with `GitHub Actions is not permitted to create or approve pull requests`. Root cause: repo-level setting `can_approve_pull_request_reviews=false` (default). Fixed by `gh api -X PUT /repos/cameronzucker/geographica/actions/permissions/workflow -f default_workflow_permissions=write -F can_approve_pull_request_reviews=true`. Predictable in hindsight — called out in spec's Risks section. Worth adding to a general "Actions setup checklist" for future projects.
- After permission fix, re-ran workflow (`gh run rerun 24600998329`) — succeeded.
- Release PR opened: [PR #1 — chore(main): release 1.1.0](https://github.com/cameronzucker/geographica/pull/1). Retroactively covers the post-v1.0.0 NOAA hardening work: 5 Features + 9 Bug Fixes, each linked to the originating commit SHA.
- Final holistic code review (sonnet) caught a stale-intro issue in CHANGELOG.md: intro said "Entries from v1.0.1 onward are generated automatically" but first generated entry is v1.1.0 (no v1.0.1 will ever exist). Fixed with a single `docs:` commit (`fc51642`) before merging the Release PR. release-please did not automatically regenerate PR #1 because `docs:` doesn't qualify as a new release. Forced regeneration by deleting `release-please--branches--main` via `gh api DELETE`; auto-closed PR #1. Re-ran workflow, which opened clean [PR #2](https://github.com/cameronzucker/geographica/pull/2) with the corrected intro. Pattern learned: to regenerate a stale Release PR, delete its branch and re-run the workflow — release-please will rebuild from current main.
- PR #2 is the canonical v1.1.0 Release PR. Left unmerged for Cameron to review and decide merge timing (immediate release v1.1.0, or bundle more NOAA deferred fixes first).
- Machinery is live. Future `feat:` / `fix:` / `perf:` commits on `main` will be aggregated into the next Release PR automatically (release-please updates the PR in place on each push of qualifying commits).

---

## 2026-04-15 — v1.0.0 Initial Release

**Released as:** v1.0.0
**Plan / spec:** (retroactive entry; spec/plan pairs exist per
subsystem under `docs/superpowers/specs/` and `docs/plans/`)
**Bug hunts:** Many under `dev/bug-hunts/` through 2026-04-15.
**Adversarial reviews:** Many under `dev/adversarial/` through 2026-04-15.

### Summary
First stable release of Geographica. Ships 7 Docker services (tileserver,
valhalla, nominatim, gps, search, stt, frontend), a browser-based setup
wizard, imagery pipeline with USGS / NOAA NAIP / M2M modes, city-aware
spatial search, public lands layer, GNOME-Keyring-backed credential
storage, and a companion utility for fast bulk imagery processing (lives
in a separate repo, `/home/administrator/Code/geographica-companion`).

### Commits
Git log is authoritative through commit `b3e1afe` (2026-04-17) for
post-v1.0.0 state. For the v1.0.0 commit itself and the work leading to
it, see the session handoff files in agent memory (handoff_20260415.md,
handoff_20260415b.md).

### Outcome
v1.0.0 tagged 2026-04-15. 579 tests passing at release time.
