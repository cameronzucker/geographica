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
