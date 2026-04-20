# Phase 2 Review — NOAA NAIP CONUS expansion (Tasks 11-18)

**Branch:** `feat/noaa-conus` @ `eb30eb3` (pre-fix) → `3cd2e58` (post-fix)
**Reviewers:** Sonnet (architectural integrity), Haiku (test coverage), Codex (adversarial — failed to invoke, deferred)
**Date:** 2026-04-20

## Context

Per-task reviews approved each of Tasks 11-18 in isolation. This phase-level
review looked at the 8 commits as a cohesive whole to catch cross-task issues
and transitional-state bugs the per-task reviewers wouldn't see.

## Round 1 — Architectural integrity (Sonnet)

### Critical
- **`services/search/main.py:1318` passes `--year`** to the CLI that Task 17
  removed. After Phase 2 merges, every admin-initiated NOAA pipeline would
  argparse-fail at startup. Also passes BOTH `--state` and `--bbox`, which
  Task 17's mutual-exclusion guard now rejects.

### Important
- **`_finalize_noaa_status` clobbers `status=error`** with `partial_failed`
  on total-failure single-state runs (tiles_done == 0). Reconciler semantics
  differ between the two values.
- **`FileNotFoundError` / `SnapshotPrunedError`** surface as raw Python
  tracebacks — missing catalog symlink on a fresh dev machine prints a stack
  trace instead of "run refresh_catalog".
- **`tests/test_noaa_naip.py:79-87`** tests a local argparse parser that
  still includes `--year` — passes without validating the real CLI, defunct.

### Minor (deferred)
- Commit `00befb7` claims M4 in its message; spec's M4 is the disk-model,
  not resume-refuse. Documentation drift, no code defect.
- `_init_noaa_checkpoint(output)` called per-tile opens ~50k redundant
  SQLite connections in a full Arizona run. Optimize via run-lifetime flag.

## Round 2 — Test coverage (Haiku)

### Coverage gaps (pre-merge hardening; non-blocking for Phase 3)
- **Checkpoint migration:** no test for partial-migration crash state, DB
  lock during DROP, or migration-path INSERT via the legacy callsite.
- **Snapshot pinning:** no test for non-string `catalog_snapshot` values
  (null, int, dict), relative paths, symlink-race during `.resolve()`.
- **CLI normalization:** no test for whitespace-padded inputs (" AZ "),
  multi-word inputs ("AZ CA"), None.
- **partial_failed:** no test for empty `per_state={}`, non-"failed:"-prefix
  values (e.g., "cancelled"), long error messages in per_state.

### Confirmed strengths
- All 36 Phase 2 tests use `tmp_path` correctly, no env pollution.
- Mocking happens at boundaries (subprocess, sqlite), not business logic.
- Zero regressions in pre-existing NOAA/setup/state_bboxes tests.

## Round 3 — Codex adversarial (failed)

Attempted two invocations:
- `npx @openai/codex review --base fa13f06 "<prompt>"` — rejected because
  the v0.118.0 CLI refuses `--base` combined with a prompt argument.
- `cat prompt.txt | npx @openai/codex review --base fa13f06 -` — same
  rejection even via stdin sentinel `-`.

Codex's `--commit <SHA>` works for single commits but not for a range.
Phase 2 review proceeded with Rounds 1+2 findings. Codex adversarial is
deferred to a post-Phase-6 full-branch pass where `--base origin/dev`
(no prompt) will work for the consolidated review.

## Fixes applied (`3cd2e58`)

1. `services/search/main.py:1312-1320` — NOAA command rewritten: passes
   `--state` OR `--bbox` conditionally, never both; dropped `--year`.
2. `scripts/acquire_imagery.py:2820-2828` — `_finalize_noaa_status` call
   gated on `tiles_done > 0 or skip_to_postprocess`; total-failure
   single-state runs retain `status=error` correctly.
3. `scripts/acquire_imagery.py:2897-2917` — `main()` wraps
   `asyncio.run(run_noaa(args))` with `FileNotFoundError` and
   `SnapshotPrunedError` handlers, logs actionable remediation, exits 1.
4. `tests/test_noaa_naip.py:79-87` — defunct local-parser test deleted
   (real CLI contract covered by Task 17's tests in
   `tests/test_noaa_resolver.py`).

Plus 7 new tests in `tests/test_noaa_admin_endpoints.py` covering the
command-builder contract (state-only, bbox-only, no --year, bbox/state
values embedded correctly, `PipelineStartBody` accepts state without year).

**Post-fix test count:** 911 passed, 27 pre-existing failures unchanged.

## Deferred to pre-merge hardening (post-Phase-6)

- Round 2 edge-case tests (snapshot null/relative paths, CLI whitespace,
  partial_failed empty/unknown values, checkpoint migration lock scenarios).
- `_init_noaa_checkpoint` per-tile optimization.
- Commit message M4 documentation correction.
- Codex full-branch adversarial (`--base origin/dev` default-prompt mode).
