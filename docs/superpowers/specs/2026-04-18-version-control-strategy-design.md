# Version Control Strategy — Design Spec

**Status:** Draft for review
**Date:** 2026-04-18
**Author:** Cameron Zucker + Claude Opus 4.7
**Related work:** Task #1 in `START.md` (pre-merge priority before next feature work)

## Context

Geographica shipped v1.0.0 on 2026-04-15 with no formal version policy, no
`CHANGELOG.md`, no `CONTRIBUTING.md`, no CI, and ~100 pre-1.0 commits that
loosely followed Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`,
`perf:`). The project is in rapid development, has a handful of beta testers
(A-audience), and may eventually attract self-hosters and downstream
packagers from the AREDN community.

This spec adopts a **light-touch but professional versioning regime** that:

- Mechanically enforces Conventional Commits at release time via `release-please`.
- Adopts SemVer with project-specific "breaking change" rules suited to a
  self-hosted offline-first appliance (not a library).
- Produces every release deliverable (CHANGELOG entries, GitHub Release notes,
  version bump, tag) automatically, so Cameron's per-release manual work is
  "merge the Release PR."
- Signals the surface-area polish of a well-maintained project even while the
  audience is small, matching the upstream projects in Geographica's tech stack.
- Adds a narrative implementation log (`dev/implementation-log.md`) as the
  in-repo companion to `CHANGELOG.md`, capturing *why* and *how* where
  `CHANGELOG.md` captures *what*.

## Goals

1. Formalize and make mechanically enforceable the already-emergent
   Conventional Commits practice.
2. Define SemVer for Geographica with a clear, one-line rule for what counts as
   breaking.
3. Automate release bureaucracy via `release-please` so Cameron's per-release
   effort is one PR merge.
4. Establish a narrative implementation log that captures the reasoning
   behind releases, inside the repo rather than in ephemeral agent memory.
5. Build coaching moments into the workflow so Cameron internalizes the
   mechanics of professional release management for transfer to work projects.

## Non-goals (explicit YAGNI)

- **No deprecation cycles.** Breaks ship in the next MAJOR with `UPGRADING.md`
  notes. No "deprecated in v1.x, removed in v2.0" windows until the user base
  warrants it.
- **No migration scripts.** No `upgrade.py` automation for breaking releases.
  Upgrade instructions live in `UPGRADING.md`; users follow prose.
- **No eager release branches.** Every release is initially a tag on `main`.
  A `release/X.Y` branch is created lazily only when a hotfix is actually
  needed.
- **No commitlint CI gate.** Claude authors all commits; the discipline is
  free. Revisit if human contributors appear.
- **No PR / issue templates yet.** Zero outside contributors today; they'd
  sit empty.
- **No CHANGELOG backfill.** Commits prior to v1.0.0 were experimental;
  `CHANGELOG.md` begins at v1.0.0 as "Initial release."
- **No phase-based organizing frame.** Mechanisms already in place
  (date-stamped plans, topic-named specs, semver, CHANGELOG, implementation
  log) cover every benefit phase numbering would provide, at lower cost.

## Deliverables

New or modified files at end of implementation:

```
CHANGELOG.md                            NEW — starts fresh at v1.0.0
VERSIONING.md                           NEW — policy doc
UPGRADING.md                            NEW — stub; populated per MAJOR
CONTRIBUTING.md                         NEW — Conventional Commits format, PR flow
AGENTS.md                               NEW — near-duplicate of CLAUDE.md for Codex
                                              and other non-Claude agent harnesses
dev/implementation-log.md               NEW — narrative companion to CHANGELOG
.github/workflows/release-please.yml    NEW — release-please GitHub Action
.github/release-please-config.json      NEW — release-please configuration
.github/.release-please-manifest.json   NEW — tracks current version
CLAUDE.md                               MODIFIED — adds "Project ethos" and
                                                    "Commit and release discipline"
README.md                               MODIFIED — brief "Versioning" section
START.md                                MODIFIED — task #1 done; priorities shuffle
```

Totals: 9 new files, 3 modified. No service code changes. Purely additive
to repo surface.

---

## VERSIONING.md content

### 1. Scope

Geographica is a self-hosted GIS appliance distributed as a git repository.
Users clone the repo, run the setup wizard, and deploy the stack. SemVer
(`MAJOR.MINOR.PATCH`) applies with the project-specific adaptations below.

### 2. What the version number promises

Geographica's SemVer applies to the surfaces a user interacts with *without
editing repo files*:

- The data directory at `/srv/geographica/data/` — MBTiles, SQLite databases,
  checkpoint files, progress files, imagery and POI datasets.
- The installed set of Docker services and their compose structure — service
  names, port mappings, volume layout in `docker-compose.yml`.
- Config file formats — `config/*.json`, keyring schema, settings consumed
  by the setup wizard.
- Bootstrap and setup assumptions — data directory path, systemd unit names,
  required host packages, `bootstrap.sh` / `setup.sh` behavior.

A release that breaks any of the above requires a **MAJOR** bump. A release
that only touches the admin HTTP API, frontend URLs/state, or pipeline CLI
flags is currently *internal* and versioned as MINOR/PATCH. Those surfaces
will graduate to the contract when formally documented.

**The rule in one line:** *If a user with a working install has to edit a
file to upgrade, that's a MAJOR.*

### 3. MAJOR / MINOR / PATCH rules

| Level | Trigger | Conventional Commits marker |
|---|---|---|
| **MAJOR** (X → X+1.0.0) | Any change to the contract surface in §2. Data migration required; `docker-compose.yml` edits required; config format change; bootstrap assumption change. | `feat!:` / `fix!:` or `BREAKING CHANGE:` footer |
| **MINOR** (X.Y → X.Y+1.0) | New user-visible feature. New admin API endpoint. New pipeline mode. Non-breaking behavior changes. | `feat:` |
| **PATCH** (X.Y.Z → X.Y.Z+1) | Bug fix. Performance improvement. Dependency bump with no behavior change. Internal refactor. | `fix:`, `perf:`, `refactor:` |
| *(no bump)* | Docs-only change. Test-only change. CI / tooling change. Chore. | `docs:`, `test:`, `ci:`, `chore:`, `build:` |

### 4. Branch model

`main` is the release ledger. All versions (`v1.0.0`, `v1.0.1`, `v1.1.0`,
`v2.0.0`) are tagged commits on `main`. There are no proactively-created
release branches.

Release branches are escape hatches. A `release/X.Y` branch is created
lazily — only when a critical bug is reported against a released version
and the affected user cannot safely upgrade to the latest. The branch is
forked from the tag, the fix is applied and tagged, and the fix is
cherry-picked back to `main`.

**The default answer to bug reports against older versions is "upgrade to
latest and retest."** Hotfix branches exist for the case where that answer
is unacceptable (e.g., the user is stuck on v1.0 because v1.1 introduced a
data migration they aren't ready for).

Pre-1.0 commits (before 2026-04-15) are out of scope. The project was
experimental before v1.0.0; `CHANGELOG.md` and version history begin at
v1.0.0.

### 5. Hotfix recipe

```bash
# Step 1: branch from the release tag
git switch -c release/1.0 v1.0.0

# Step 2: apply the fix (or cherry-pick from main if already fixed there)
git cherry-pick <sha>

# Step 3: tag the patch release on the branch
git tag v1.0.1

# Step 4: push branch + tag; release-please picks it up and cuts a release
git push origin release/1.0 v1.0.1

# Step 5: ensure the fix also exists on main (cherry-pick if the release
#         branch was built from v1.0.0 before the fix landed on main)
git switch main
git cherry-pick <sha>  # if needed
```

### 6. Tag format

Tags use the `v` prefix: `v1.0.0`, `v1.2.3`. This matches GitHub release
conventions and the `release-please` default with `include-v-in-tag: true`.

### 7. Release cadence

No fixed schedule. Releases ship when there are meaningful user-visible
changes (`feat:`, `fix:`, or `perf:` commits) on `main`. In practice
`release-please` opens a Release PR within minutes of the first qualifying
commit; Cameron merges it when ready.

### 8. Pre-release markers

Reserved for future use. If needed, `-rc.N` suffix follows SemVer 2.0.0
(e.g., `v1.1.0-rc.1`). Not in use at adoption.

### 9. Change history

See `CHANGELOG.md` for the user-visible change list per release. See
`UPGRADING.md` for upgrade instructions on MAJOR releases. See
`dev/implementation-log.md` for the narrative reasoning behind each release
(why a change was made, what was considered, what bugs were caught in
review).

---

## CONTRIBUTING.md content

### Conventional Commits format

All commits on `main` follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org):

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

**Supported types:**

| Type | Version impact | Use when |
|---|---|---|
| `feat:` | MINOR | New user-visible feature |
| `fix:` | PATCH | Bug fix |
| `perf:` | PATCH | Performance improvement with no behavior change |
| `refactor:` | PATCH | Internal restructuring, no user-visible change |
| `docs:` | none | Documentation-only change |
| `test:` | none | Test-only change |
| `build:` | none | Build system / dependency change (Dockerfile, requirements.txt) |
| `ci:` | none | CI / workflow change |
| `chore:` | none | Housekeeping (`.gitignore`, editorconfig) |
| `revert:` | inherits | Revert a previous commit |

**Breaking changes** trigger MAJOR regardless of type:

- Add `!` suffix to the type: `feat!:`, `fix!:`.
- And/or add a `BREAKING CHANGE:` footer with a one-line user-facing
  explanation.

Use `!` for quick signaling; add the footer when the change needs prose to
explain what users must do to upgrade (the footer text flows directly to
`CHANGELOG.md` and `UPGRADING.md`).

**Recommended scopes:** `pipeline`, `tileserver`, `search`, `gps`, `stt`,
`admin`, `frontend`, `setup`, `keyring`, `docs`. Example:
`feat(pipeline): add Sentinel-2 mode`.

**Subject line:** imperative mood (`add` not `added`/`adds`), ≤72 characters,
no trailing period. Body optional; use for non-obvious *why*.

### PR flow

Geographica currently has one active developer + AI agents. PRs are not
required for merges to `main`; direct commits to `main` with Conventional
Commits messages are the default flow. The one PR that does appear
automatically is the `release-please` Release PR (see `VERSIONING.md`).

If outside contributors appear, the flow becomes: fork, branch,
Conventional-Commits commits, open PR against `main`, squash-merge.

### Local verification

Before pushing, run the test suite:

```bash
python -m pytest tests/ services/search/tests/ -v
```

579 tests currently pass. 2 pre-existing M2M failures and 9 pre-existing
OSM POI errors are tracked and expected.

---

## release-please files

### `.github/workflows/release-please.yml`

```yaml
name: release-please

on:
  push:
    branches: [main]

permissions:
  contents: write
  pull-requests: write

jobs:
  release-please:
    runs-on: ubuntu-latest
    steps:
      - uses: googleapis/release-please-action@v4
        with:
          config-file: .github/release-please-config.json
          manifest-file: .github/.release-please-manifest.json
```

### `.github/release-please-config.json`

```json
{
  "packages": {
    ".": {
      "release-type": "simple",
      "include-v-in-tag": true,
      "bump-minor-pre-major": false,
      "bump-patch-for-minor-pre-major": false,
      "changelog-sections": [
        {"type": "feat",     "section": "Features"},
        {"type": "fix",      "section": "Bug Fixes"},
        {"type": "perf",     "section": "Performance"},
        {"type": "refactor", "section": "Refactors"},
        {"type": "docs",     "section": "Documentation", "hidden": true},
        {"type": "test",     "section": "Tests",         "hidden": true},
        {"type": "ci",       "section": "CI",            "hidden": true},
        {"type": "build",    "section": "Build System",  "hidden": true},
        {"type": "chore",    "section": "Chores",        "hidden": true}
      ]
    }
  }
}
```

### `.github/.release-please-manifest.json`

```json
{".": "1.0.0"}
```

### Release PR flow

Post-rollout, the first `feat:` / `fix:` / `perf:` commit to `main` triggers:

1. Within ~1 minute, `release-please` opens a PR titled
   `chore(main): release X.Y.Z`.
2. The PR modifies exactly two files: `CHANGELOG.md` (new entry) and
   `.github/.release-please-manifest.json` (version bump).
3. The PR description previews the release notes.
4. Cameron merges the PR.
5. `release-please` then: creates the `vX.Y.Z` tag, creates a GitHub Release
   with the same notes, and closes the PR.

**Per-release manual work: one PR approval + merge.**

---

## CHANGELOG.md starting state

```markdown
# Changelog

All notable changes to Geographica are documented here.

This project adheres to [Semantic Versioning](https://semver.org) with
project-specific rules described in [VERSIONING.md](VERSIONING.md). Entries
from v1.0.1 onward are generated automatically by `release-please` from
Conventional Commits.

## [1.0.0] — 2026-04-15

Initial release. Commits prior to v1.0.0 were experimental and are not
retroactively documented. See `README.md` for the feature overview at
release time.
```

## UPGRADING.md starting state

```markdown
# Upgrading Geographica

This document lists upgrade instructions for each MAJOR release. If you are
upgrading across a MAJOR boundary (e.g., v1.x → v2.0), follow the matching
section before running `docker compose up -d`.

MINOR and PATCH upgrades are safe with no special steps — just `git pull`
and restart the stack.

## v1.0.0

Initial release; no prior version to upgrade from.
```

---

## CLAUDE.md additions

Two new sections appended to the existing `CLAUDE.md`:

### `## Project ethos`

```
Geographica is Cameron's learning sandbox for AI-assisted development
techniques — custom skills, adversarial review, multi-agent teaming,
capability mapping — that he plans to transfer to high-stakes projects at
his employer. The shipped software matters, but **professional-development
outcomes are a first-class goal alongside features.**

Implications:
- Process rigor > raw velocity. Do the right thing, not the fast thing.
- Explain when/what for new workflows so Cameron builds transferable skill.
- Prefer patterns that generalize to multi-developer / higher-stakes
  environments.
- Signal professional polish even at A-audience scale — the surface area of
  the repo (commits, CHANGELOG, versioning, CI) teaches Cameron what "good"
  looks like and builds habits that transfer.
```

### `## Commit and release discipline`

```
- Match commit type: to the table in CONTRIBUTING.md. Never use fix: for
  docs fixes or feat: for internal refactors.
- Before committing a change that touches /srv/geographica/data/ schema,
  docker-compose.yml, config/*.json, keyring format, or bootstrap
  assumptions, add `!` suffix and a `BREAKING CHANGE:` footer with a
  one-line user-facing explanation.
- Prefer scoped commits (feat(pipeline): ...) when the change is localized
  to one subsystem.
- Never ship a release manually — merging the release-please Release PR is
  the only release mechanism. If you need to ship and no Release PR exists,
  the last commits must not have included a feat: / fix: / perf: — that's
  fine, it means nothing user-visible has changed.
- On a hotfix, follow the runbook in VERSIONING.md §5 exactly.
- Update dev/implementation-log.md after any significant work item: plan
  executed, feature shipped, bug hunt cycle completed, adversarial review
  completed. Entry goes at the top, reverse-chronological, keyed by date +
  topic.
```

---

## AGENTS.md

A near-duplicate of `CLAUDE.md`, differing only where harness-specific tool
names appear. Purpose: if Cameron ever runs Codex or another non-Claude
agent harness on this project, the agent instructions are already present
in the expected location.

Implementation approach: copy `CLAUDE.md` verbatim, then:

- Replace "Claude" with "the agent" where it refers to the tool generically.
- Keep the `## Project ethos`, `## Commit and release discipline`, and
  `## Skill routing` sections identical.
- Note at the top: "This file mirrors CLAUDE.md. When updating one, update
  the other to match."

If they diverge over time, that's acceptable; but the cheap hedge is
keeping them in sync for now.

---

## README.md addition

A short "Versioning" section near the bottom of `README.md`, before the
License section:

```markdown
## Versioning

Geographica follows [Semantic Versioning](https://semver.org) with
project-specific rules described in [VERSIONING.md](VERSIONING.md). See
[CHANGELOG.md](CHANGELOG.md) for the release history and
[UPGRADING.md](UPGRADING.md) for upgrade instructions on MAJOR releases.
```

---

## dev/implementation-log.md

### Purpose

Narrative companion to `CHANGELOG.md`. Where `CHANGELOG.md` lists *what*
changed in each release, this log captures *why* and *how* — the reasoning,
tradeoffs, adversarial reviews, and bugs caught before release. This is the
in-repo analog to what currently lives in agent session memory; moving it
into the repo makes it inheritable by future collaborators (including
future Claude sessions with no memory).

### Format

- Reverse-chronological: newest entries at the top.
- One entry per significant work item (major feature, release, adversarial
  review cycle, migration).
- Each entry follows this template:

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
- Bug → where caught (adversarial review, bug hunt, integration test) →
  commit SHA that fixed it.

### Commits
Short list of notable commits (SHA + subject). Not exhaustive — the git
log is authoritative. List only the ones a reader would want to jump to.

### Outcome
Production results, test counts, any surprises.
```

### Seed entries (written at rollout)

Two entries seeded at rollout time, so the format is documented by example:

#### Entry 1 — 2026-04-18: Version Control Strategy Adoption

Covers this very spec: SemVer adoption, Conventional Commits formalization,
release-please setup, CHANGELOG fresh start, implementation log launch.
Links to this design doc and the forthcoming implementation plan.
Expected release: v1.0.1 after the first NOAA deferred-item fix lands.

#### Entry 2 — 2026-04-15: v1.0.0 Initial Release

Retroactive entry summarizing v1.0.0: 7 services, setup wizard, imagery
pipeline with USGS + NOAA + M2M modes, city-aware spatial search, public
lands layer, keyring credentials, companion utility (separate repo). Links
to `handoff_20260415b` in agent memory for the detailed session log.
Points to `docs/aredn_maps_stack_known_good.md` for the reference
deployment context.

Deeper history before v1.0.0 remains in agent memory handoff files; not
migrated.

---

## Rollout ordering

One implementation session, five commits, in this order:

1. **`docs: adopt semver and conventional commits`**
   - `VERSIONING.md`, `CHANGELOG.md`, `UPGRADING.md`, `CONTRIBUTING.md`
   - README.md "Versioning" section
   - Single commit (policy docs belong together).

2. **`docs: add implementation log with seed entries`**
   - `dev/implementation-log.md` with v1.0.0 + 2026-04-18 seed entries.
   - Separate commit so the log's birth is itself a log-worthy event.

3. **`docs(claude): add project ethos, commit discipline, and mirror to AGENTS.md`**
   - Append sections to `CLAUDE.md`.
   - Create `AGENTS.md` as near-duplicate.
   - Single commit.

4. **`ci: add release-please workflow for automated versioning`**
   - `.github/workflows/release-please.yml`
   - `.github/release-please-config.json`
   - `.github/.release-please-manifest.json`
   - Single commit.

5. **`docs: mark versioning strategy complete in START.md`**
   - Update `START.md` to remove task #1, promote NOAA deferred items to #1.
   - Single commit.

All five commits are `docs:` or `ci:` types → **the rollout itself
contributes no qualifying commits**. However, **`main` already contains
several post-v1.0.0 `feat:` and `fix:` commits** (the NOAA hardening
work completed between 2026-04-16 and 2026-04-17). When the
`release-please` workflow first runs on `main`, it will see those
commits and open a Release PR for **v1.1.0** retroactively covering
them. This is a desirable side effect — it gives that body of work a
proper CHANGELOG entry, a tag, and a GitHub Release — and it is the
coaching moment where Cameron sees the full release lifecycle play out
for the first time.

---

## Verification / done criteria

After rollout:

1. `ls` in repo root shows `VERSIONING.md`, `CHANGELOG.md`, `UPGRADING.md`,
   `CONTRIBUTING.md`, `AGENTS.md`.
2. `.github/workflows/release-please.yml` and the two config files exist.
3. `dev/implementation-log.md` exists with 2 seed entries.
4. `CLAUDE.md` and `AGENTS.md` contain matching `## Project ethos` and
   `## Commit and release discipline` sections.
5. `README.md` has a `## Versioning` section linking to the three policy
   docs.
6. `START.md` task #1 is marked complete; NOAA deferred items are task #1.
7. `git push origin main` has been run; the rollout commits are visible on
   GitHub.
8. GitHub Actions shows the `release-please` workflow ran successfully.
9. A `release-please` Release PR for **v1.1.0** appears within ~1 minute
   of the merge to `main`, retroactively covering the post-v1.0.0 NOAA
   hardening commits. This is the coaching-moment verification that the
   machinery works end-to-end. Cameron reviews the PR and merges it when
   ready; the bot then creates the `v1.1.0` tag, GitHub Release, and
   CHANGELOG entry automatically.
10. 579 tests still pass (no regressions; purely additive changes).

## Open questions

None at this time. All decisions consolidated above.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| GitHub Actions auth issues block `release-please` | Fall back to running `git-cliff` locally before each tag. The Conventional Commits format is unchanged either way, so no work is wasted. This is the "Option B escape hatch" from brainstorming. |
| Claude writes `fix:` for a docs fix and triggers a spurious v1.0.1 | CLAUDE.md `## Commit and release discipline` section calls out this specific mistake. Low-frequency; easy to revert a bad release PR before merging. |
| Rollout commit accidentally typed as `feat:` triggers a release | All rollout commits are `docs:` or `ci:` by design. Spec explicitly calls this out. Any Release PR that appears during rollout should be closed without merging. |
| AGENTS.md drifts out of sync with CLAUDE.md | Header note at top of both files reminds agents to keep them in sync. Acceptable failure mode: they diverge slightly; not a regression in functionality. |

## Next step

Invoke `superpowers:writing-plans` to produce the implementation plan,
breaking this spec into sequenced tasks with verification steps per task.
