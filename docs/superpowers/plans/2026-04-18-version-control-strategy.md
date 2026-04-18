# Version Control Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt SemVer, Conventional Commits, and release-please automation for Geographica, plus an in-repo implementation log and AGENTS.md mirror of CLAUDE.md.

**Architecture:** Pure additive documentation + CI config. No service code changes. Rollout happens on the `dev` branch as five commits, then merges fast-forward to `main`. On the merge to `main`, the new `release-please` GitHub Action fires and opens a Release PR for v1.1.0 covering the post-v1.0.0 NOAA hardening work already present on `main`.

**Tech Stack:** Markdown docs, GitHub Actions YAML, JSON config files for `release-please` v4.

**Source of truth:** [docs/superpowers/specs/2026-04-18-version-control-strategy-design.md](../specs/2026-04-18-version-control-strategy-design.md) — all file contents below match this spec verbatim.

---

## Preflight — context for the executor

- You are working on branch `dev` in `/home/administrator/Code/geographica`. The design spec was committed at `60d6f63` (on `dev`). Do NOT rebase or squash that commit.
- Geographica's production services (7 Docker containers) are running. **Do not run `docker compose down`** or restart services — none of this work requires it.
- The repo already follows loose Conventional Commits. Your commit messages MUST follow the strict format defined in [CONTRIBUTING.md](../../CONTRIBUTING.md) once Task 1 creates that file.
- All file paths below are relative to the repo root unless otherwise noted.

---

## Task 1: Scaffold policy docs (VERSIONING, CHANGELOG, UPGRADING, CONTRIBUTING) and update README

**Files:**
- Create: `VERSIONING.md`
- Create: `CHANGELOG.md`
- Create: `UPGRADING.md`
- Create: `CONTRIBUTING.md`
- Modify: `README.md` (add "Versioning" section near bottom, before license)

### Steps

- [ ] **Step 1.1: Create VERSIONING.md**

Write the following content to `VERSIONING.md`:

```markdown
# Versioning Policy

Geographica is a self-hosted GIS appliance distributed as a git repository.
Users clone the repo, run the setup wizard, and deploy the stack. We follow
[Semantic Versioning](https://semver.org) (`MAJOR.MINOR.PATCH`) with the
project-specific adaptations below.

## What the version number promises

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

## MAJOR / MINOR / PATCH rules

| Level | Trigger | Conventional Commits marker |
|---|---|---|
| **MAJOR** (X → X+1.0.0) | Any change to the contract surface above. Data migration required; `docker-compose.yml` edits required; config format change; bootstrap assumption change. | `feat!:` / `fix!:` or `BREAKING CHANGE:` footer |
| **MINOR** (X.Y → X.Y+1.0) | New user-visible feature. New admin API endpoint. New pipeline mode. Non-breaking behavior changes. | `feat:` |
| **PATCH** (X.Y.Z → X.Y.Z+1) | Bug fix. Performance improvement. Dependency bump with no behavior change. Internal refactor. | `fix:`, `perf:`, `refactor:` |
| *(no bump)* | Docs-only change. Test-only change. CI / tooling change. Chore. | `docs:`, `test:`, `ci:`, `chore:`, `build:` |

## Branch model

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

## Hotfix recipe

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

## Tag format

Tags use the `v` prefix: `v1.0.0`, `v1.2.3`. This matches GitHub release
conventions and the `release-please` default with `include-v-in-tag: true`.

## Release cadence

No fixed schedule. Releases ship when there are meaningful user-visible
changes (`feat:`, `fix:`, or `perf:` commits) on `main`. In practice
`release-please` opens a Release PR within minutes of the first qualifying
commit; the maintainer merges it when ready.

## Pre-release markers

Reserved for future use. If needed, `-rc.N` suffix follows SemVer 2.0.0
(e.g., `v1.1.0-rc.1`). Not in use at adoption.

## Change history

See [CHANGELOG.md](CHANGELOG.md) for the user-visible change list per
release. See [UPGRADING.md](UPGRADING.md) for upgrade instructions on MAJOR
releases. See [dev/implementation-log.md](dev/implementation-log.md) for
the narrative reasoning behind each release (why a change was made, what
was considered, what bugs were caught in review).
```

- [ ] **Step 1.2: Verify VERSIONING.md structure**

Run:
```bash
grep -c "^## " VERSIONING.md
```
Expected output: `8` (eight level-2 headers: What the version number promises, MAJOR/MINOR/PATCH rules, Branch model, Hotfix recipe, Tag format, Release cadence, Pre-release markers, Change history).

- [ ] **Step 1.3: Create CHANGELOG.md**

Write the following to `CHANGELOG.md`:

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

- [ ] **Step 1.4: Create UPGRADING.md**

Write the following to `UPGRADING.md`:

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

- [ ] **Step 1.5: Create CONTRIBUTING.md**

Write the following to `CONTRIBUTING.md`:

```markdown
# Contributing to Geographica

## Conventional Commits format

All commits on `main` follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org):

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

### Supported types

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

### Breaking changes

Breaking changes trigger MAJOR regardless of type:

- Add `!` suffix to the type: `feat!:`, `fix!:`.
- And/or add a `BREAKING CHANGE:` footer with a one-line user-facing
  explanation.

Use `!` for quick signaling; add the footer when the change needs prose to
explain what users must do to upgrade (the footer text flows directly to
`CHANGELOG.md` and `UPGRADING.md`).

### Recommended scopes

`pipeline`, `tileserver`, `search`, `gps`, `stt`, `admin`, `frontend`,
`setup`, `keyring`, `docs`. Example: `feat(pipeline): add Sentinel-2 mode`.

### Subject line

Imperative mood (`add` not `added`/`adds`), ≤72 characters, no trailing
period. Body optional; use for non-obvious *why*.

## PR flow

Geographica currently has one active maintainer + AI agents. PRs are not
required for merges to `main`; direct commits to `main` with Conventional
Commits messages are the default flow. The one PR that does appear
automatically is the `release-please` Release PR (see
[VERSIONING.md](VERSIONING.md)).

If outside contributors appear, the flow becomes: fork, branch,
Conventional-Commits commits, open PR against `main`, squash-merge.

## Local verification

Before pushing, run the test suite:

```bash
python -m pytest tests/ services/search/tests/ -v
```
```

- [ ] **Step 1.6: Verify CONTRIBUTING.md content**

Run:
```bash
grep -c "| \`feat" CONTRIBUTING.md
```
Expected output: `1` (one row for `feat:` in the types table).

- [ ] **Step 1.7: Add "Versioning" section to README.md**

Read the current `README.md` first to locate the License section:
```bash
grep -n "^## License" README.md
```
Expected: one line number printed (e.g., `## License` at line N).

Insert the following section directly BEFORE the `## License` line:

```markdown
## Versioning

Geographica follows [Semantic Versioning](https://semver.org) with
project-specific rules described in [VERSIONING.md](VERSIONING.md). See
[CHANGELOG.md](CHANGELOG.md) for the release history and
[UPGRADING.md](UPGRADING.md) for upgrade instructions on MAJOR releases.

```

Use the `Edit` tool with `old_string` being the `## License` heading line and `new_string` being `## Versioning\n\n[content]\n\n## License`. Verify by re-reading the file to confirm the section landed above License.

- [ ] **Step 1.8: Verify README.md edit**

Run:
```bash
grep -n "^## Versioning\|^## License" README.md
```
Expected: two lines, with `## Versioning` appearing on a lower line number than `## License`.

- [ ] **Step 1.9: Commit policy docs**

Run:
```bash
git add VERSIONING.md CHANGELOG.md UPGRADING.md CONTRIBUTING.md README.md
git status --short
```
Expected output should show exactly 5 files staged (4 new, 1 modified):
```
A  CHANGELOG.md
A  CONTRIBUTING.md
A  UPGRADING.md
A  VERSIONING.md
M  README.md
```

Commit:
```bash
git commit -m "$(cat <<'EOF'
docs: adopt semver and conventional commits

Add VERSIONING.md (SemVer with project-specific breaking-change rules),
CHANGELOG.md (fresh start at v1.0.0), UPGRADING.md (stub for MAJOR
upgrades), and CONTRIBUTING.md (Conventional Commits format, PR flow).
README.md gets a brief Versioning section linking to the policy docs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Verify:
```bash
git log -1 --oneline
```
Expected: one line showing `docs: adopt semver and conventional commits`.

---

## Task 2: Create dev/implementation-log.md with seed entries

**Files:**
- Create: `dev/implementation-log.md`

### Steps

- [ ] **Step 2.1: Confirm dev/ directory exists**

Run:
```bash
ls dev/ | head -5
```
Expected: prints filenames (e.g., `adversarial/`, `bug-hunts/`, etc.). If the directory does not exist, create it: `mkdir -p dev`.

- [ ] **Step 2.2: Create dev/implementation-log.md**

Write the following to `dev/implementation-log.md`:

```markdown
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
- (rollout commits to be listed after implementation)

### Outcome
To be filled in after rollout: test counts, workflow first-run observation,
v1.1.0 Release PR outcome.

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
```

- [ ] **Step 2.3: Verify implementation log structure**

Run:
```bash
grep -c "^## 20" dev/implementation-log.md
```
Expected: `2` (two dated top-level entries).

- [ ] **Step 2.4: Commit implementation log**

```bash
git add dev/implementation-log.md
git commit -m "$(cat <<'EOF'
docs: add implementation log with seed entries

Narrative companion to CHANGELOG.md. Where CHANGELOG captures what
changed, this log captures why and how — reasoning, tradeoffs,
adversarial reviews, bugs caught. Seed entries document v1.0.0 and
the versioning strategy adoption itself. Pattern borrowed from
CVErt-Ops (github.com/scarson/CVErt-Ops) dev/implementation-log.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Verify:
```bash
git log -1 --oneline
```
Expected: `docs: add implementation log with seed entries`.

---

## Task 3: Update CLAUDE.md and create AGENTS.md mirror

**Files:**
- Modify: `CLAUDE.md` (append two new sections)
- Create: `AGENTS.md`

### Steps

- [ ] **Step 3.1: Read current CLAUDE.md**

Read the entire `CLAUDE.md` file to understand structure. Note the existing top-level sections (likely `# Geographica`, `## Project structure`, `## Commands`, `## Hardware`, `## Testing`, `## Skill routing`, `## Brainstorming preferences`).

- [ ] **Step 3.2: Append "Project ethos" section to CLAUDE.md**

Use `Edit` tool to append (add a new section at the very end of the file). The `old_string` should be the current last line of the file; the `new_string` should be that line plus the new section.

The section to append:

```markdown

## Project ethos

Geographica is Cameron's learning sandbox for AI-assisted development
techniques — custom skills, adversarial review, multi-agent teaming,
capability mapping — that he plans to transfer to high-stakes projects at
his employer. The shipped software matters, but **professional-development
outcomes are a first-class goal alongside features.**

Implications:
- Process rigor > raw velocity. Do the right thing, not the fast thing.
- Explain when/what for new workflows so Cameron builds transferable
  skill.
- Prefer patterns that generalize to multi-developer / higher-stakes
  environments.
- Signal professional polish even at A-audience scale — the surface area
  of the repo (commits, CHANGELOG, versioning, CI) teaches Cameron what
  "good" looks like and builds habits that transfer.
```

- [ ] **Step 3.3: Append "Commit and release discipline" section to CLAUDE.md**

Append the following section after "Project ethos":

```markdown

## Commit and release discipline

- Match the commit `type:` to the table in [CONTRIBUTING.md](CONTRIBUTING.md).
  Never use `fix:` for docs fixes or `feat:` for internal refactors.
- Before committing a change that touches `/srv/geographica/data/` schema,
  `docker-compose.yml`, `config/*.json`, keyring format, or bootstrap
  assumptions, add `!` suffix and a `BREAKING CHANGE:` footer with a
  one-line user-facing explanation.
- Prefer scoped commits (`feat(pipeline): ...`) when the change is
  localized to one subsystem. Recommended scopes: `pipeline`, `tileserver`,
  `search`, `gps`, `stt`, `admin`, `frontend`, `setup`, `keyring`, `docs`.
- Never ship a release manually — merging the `release-please` Release PR
  is the only release mechanism. If you need to ship and no Release PR
  exists, the last commits must not have included a `feat:` / `fix:` /
  `perf:` — that's fine, it means nothing user-visible has changed.
- On a hotfix, follow the runbook in [VERSIONING.md](VERSIONING.md) §Hotfix
  recipe exactly.
- Update `dev/implementation-log.md` after any significant work item: plan
  executed, feature shipped, bug hunt cycle completed, adversarial review
  completed. Entry goes at the top, reverse-chronological, keyed by
  date + topic.
```

- [ ] **Step 3.4: Verify CLAUDE.md edits**

Run:
```bash
grep -c "^## Project ethos\|^## Commit and release discipline" CLAUDE.md
```
Expected: `2`.

- [ ] **Step 3.5: Create AGENTS.md as mirror of CLAUDE.md**

Read the full updated `CLAUDE.md` content. Write the same content to `AGENTS.md`, with the following modifications:

1. Add the following note at the very top of `AGENTS.md`, right after the main `# Geographica` heading (insert as the first paragraph under that heading):

```markdown

> **Note:** This file mirrors [CLAUDE.md](CLAUDE.md) for non-Claude agent
> harnesses (Codex, etc.). When updating one, update the other to match.
> The substantive content is identical.

```

2. Do not rename "Claude" to anything generic; "Claude" mentions in prose are fine. The purpose of AGENTS.md is surface-level compatibility with emerging agent-instruction-file conventions (see CVErt-Ops for the prevailing pattern), not verbatim genericization.

- [ ] **Step 3.6: Verify AGENTS.md is present and contains the mirror note**

Run:
```bash
grep -c "^# Geographica" AGENTS.md && grep -c "mirrors \[CLAUDE.md\]" AGENTS.md
```
Expected: `1` and `1`.

- [ ] **Step 3.7: Verify shared sections exist in both files**

Run:
```bash
for f in CLAUDE.md AGENTS.md; do
  echo "=== $f ==="
  grep -c "^## Project ethos\|^## Commit and release discipline\|^## Skill routing" "$f"
done
```
Expected: each file prints `3`.

- [ ] **Step 3.8: Commit CLAUDE.md + AGENTS.md**

```bash
git add CLAUDE.md AGENTS.md
git commit -m "$(cat <<'EOF'
docs(claude): add project ethos, commit discipline, and mirror to AGENTS.md

Two new sections in CLAUDE.md: Project ethos (Geographica as AI-technique
learning sandbox) and Commit and release discipline (mechanical rules
for how Claude classifies commits and operates release-please). AGENTS.md
created as a near-duplicate of CLAUDE.md for non-Claude agent harnesses
(Codex, etc.).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Verify:
```bash
git log -1 --oneline
```
Expected: `docs(claude): add project ethos, commit discipline, and mirror to AGENTS.md`.

---

## Task 4: Create release-please workflow, config, manifest

**Files:**
- Create: `.github/workflows/release-please.yml`
- Create: `.github/release-please-config.json`
- Create: `.github/.release-please-manifest.json`

### Steps

- [ ] **Step 4.1: Confirm .github directory does not yet exist**

Run:
```bash
ls -la .github 2>/dev/null; echo "exit=$?"
```
Expected: `exit=2` (or similar — directory does not exist). If it does exist, inspect its contents before proceeding to avoid clobbering anything.

- [ ] **Step 4.2: Create .github/workflows/ directory**

```bash
mkdir -p .github/workflows
```

Verify:
```bash
ls -la .github/workflows/
```
Expected: empty directory listing (no files yet).

- [ ] **Step 4.3: Create release-please workflow**

Write the following to `.github/workflows/release-please.yml`:

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

- [ ] **Step 4.4: Validate workflow YAML syntax**

Run:
```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/release-please.yml'))" && echo "YAML OK"
```
Expected output: `YAML OK`. If `yaml` module is missing, install with `pip install pyyaml` first.

- [ ] **Step 4.5: Create release-please config**

Write the following to `.github/release-please-config.json`:

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

- [ ] **Step 4.6: Validate config JSON**

Run:
```bash
python -m json.tool .github/release-please-config.json > /dev/null && echo "JSON OK"
```
Expected: `JSON OK`.

- [ ] **Step 4.7: Create release-please manifest**

Write the following to `.github/.release-please-manifest.json`:

```json
{".": "1.0.0"}
```

- [ ] **Step 4.8: Validate manifest JSON**

Run:
```bash
python -m json.tool .github/.release-please-manifest.json
```
Expected: pretty-printed JSON showing `{".": "1.0.0"}`.

- [ ] **Step 4.9: Commit release-please setup**

```bash
git add .github/workflows/release-please.yml .github/release-please-config.json .github/.release-please-manifest.json
git status --short
```
Expected: three new files staged.

```bash
git commit -m "$(cat <<'EOF'
ci: add release-please workflow for automated versioning

On every push to main, release-please-action@v4 reads Conventional Commits
since the last release, maintains CHANGELOG.md automatically, and opens a
Release PR that bumps .release-please-manifest.json. Merging the PR
creates the tag and GitHub Release. Configuration pins Geographica at
v1.0.0 as the starting version; includes v-prefix tags and disables
pre-major bump-minor quirks (we're post-1.0).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Verify:
```bash
git log -1 --oneline
```
Expected: `ci: add release-please workflow for automated versioning`.

---

## Task 5: Update START.md to reflect task #1 completion

**Files:**
- Modify: `START.md`

### Steps

- [ ] **Step 5.1: Read current START.md**

Read the full file. The "What to work on next" section currently lists (in order):
1. Version Control Strategy (HIGH)
2. NOAA Pipeline Deferred Fixes (MEDIUM)
3. Visual Design Identity (MEDIUM)
4. Setup Wizard GUI Completion (MEDIUM)

The goal: remove item 1 (now done), promote items 2-4 up, and add a one-line note that the versioning strategy was completed.

- [ ] **Step 5.2: Edit START.md — delete the Version Control Strategy block**

Use `Edit` tool on `START.md`. Use this exact `old_string`:

```
### 1. Version Control Strategy (HIGH — blocking future releases)

The project is on v1.0.0 (tagged 2026-04-15) but has no formal versioning policy.
Other people may start using the shipped product, so we need to decide:

- **What necessitates major/minor/patch increments** — adopt Semantic Versioning
  (semver.org) or define project-specific rules? Consider: API changes (admin panel
  endpoints), data format changes (MBTiles schema, pipeline state file), Docker
  image changes, frontend behavior changes, config format changes.
- **When to create numbered version branches** — release branches (release/1.1.0)
  vs tagged commits on main? Hotfix workflow for critical bugs in released versions?
- **Industry best practice** — research Conventional Commits, semver, GitHub release
  workflow, changelog generation. The commit messages already follow Conventional
  Commits loosely (feat:, fix:, docs:). Formalize this.
- **Concrete deliverables**: VERSIONING.md documenting the policy, CI check for
  commit message format, CHANGELOG.md generation, tag + GitHub Release workflow.

### 2. NOAA Pipeline Deferred Fixes (MEDIUM — from adversarial review)
```

With this exact `new_string`:

```
### 1. NOAA Pipeline Deferred Fixes (HIGH — from adversarial review)
```

This single replacement both deletes the Version Control Strategy section and renumbers NOAA to item #1 (promoting it from MEDIUM to HIGH, since it's now the top priority).

- [ ] **Step 5.2a: Renumber Visual Design Identity to #2**

Use `Edit` tool. `old_string`: `### 3. Visual Design Identity (MEDIUM)`. `new_string`: `### 2. Visual Design Identity (MEDIUM)`.

- [ ] **Step 5.2b: Renumber Setup Wizard GUI Completion to #3**

Use `Edit` tool. `old_string`: `### 4. Setup Wizard GUI Completion (MEDIUM)`. `new_string`: `### 3. Setup Wizard GUI Completion (MEDIUM)`.

- [ ] **Step 5.3: Add "Recently completed" note**

Use `Edit` to insert a note just after the `## What to work on next` heading and before the first numbered item. The note should read:

```markdown

**Recently completed (2026-04-18):** Version Control Strategy.
SemVer + Conventional Commits adopted, `release-please` GitHub Action
live. See [VERSIONING.md](VERSIONING.md) for policy and
[CHANGELOG.md](CHANGELOG.md) for release history.

```

- [ ] **Step 5.4: Verify START.md structure**

Run:
```bash
grep -n "^### [0-9]" START.md
```
Expected: three lines, showing `### 1.`, `### 2.`, `### 3.` in that order.

```bash
grep -c "Version Control Strategy" START.md
```
Expected: `1` (only in the "Recently completed" note, not in the numbered list).

- [ ] **Step 5.5: Commit START.md update**

```bash
git add START.md
git commit -m "$(cat <<'EOF'
docs: mark versioning strategy complete in START.md

Remove task #1 (Version Control Strategy — now shipped), promote NOAA
deferred-item fixes to task #1, add a brief "Recently completed" note
pointing at VERSIONING.md and CHANGELOG.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Verify:
```bash
git log -1 --oneline
```
Expected: `docs: mark versioning strategy complete in START.md`.

- [ ] **Step 5.6: Confirm the five rollout commits**

Run:
```bash
git log --oneline -6
```
Expected: first line is `docs: add version control strategy design spec` from the brainstorming session, followed by the five rollout commits in reverse order. All five should be `docs:` or `ci:` types.

---

## Task 6: Regression check — run full test suite

**Files:** (none — this is a verification step)

### Steps

- [ ] **Step 6.1: Run the full test suite**

Run:
```bash
python -m pytest tests/ services/search/tests/ -v 2>&1 | tail -30
```

- [ ] **Step 6.2: Confirm expected pass/fail count**

Expected outcome (per handoff 2026-04-17):
- **579 tests pass.**
- **2 pre-existing failures** in M2M (documented; not regressions).
- **9 pre-existing errors** in OSM POI (documented; not regressions).

If additional tests fail or new errors appear, **stop and investigate**: purely additive doc/CI changes should not affect the test suite. If tests fail because the pre-existing failure count has changed (e.g., 3 failures instead of 2), still check the delta — a new failure mode needs root-cause analysis, not a rubber-stamp.

- [ ] **Step 6.3: Record test outcome in implementation log**

Append a line to the "Outcome" section of the 2026-04-18 entry in `dev/implementation-log.md`:

```markdown
- 2026-04-18 regression check: 579 tests pass, 2 pre-existing M2M
  failures + 9 pre-existing OSM POI errors (unchanged from 2026-04-17).
```

Commit the update:
```bash
git add dev/implementation-log.md
git commit -m "$(cat <<'EOF'
docs: record 2026-04-18 regression check in implementation log

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Ship — merge dev to main, push, observe first release-please run

**Files:** (no repo file changes; this task is pure git operations and observation)

### Steps

- [ ] **Step 7.1: Preflight — confirm dev is ahead of main**

Run:
```bash
git fetch origin
git log --oneline main..dev
```
Expected: at least 7 commits listed (the spec commit from brainstorming + 5 rollout commits from this plan + the regression-log amendment). If `main..dev` is empty, something has gone wrong — stop and investigate.

- [ ] **Step 7.2: Switch to main and fast-forward merge dev**

Run:
```bash
git switch main
git merge --ff-only dev
```
Expected: message like `Fast-forward` followed by a summary of updated refs. If git refuses because the merge is not a fast-forward, DO NOT create a merge commit — pause and ask Cameron how he'd like to handle the divergence (rebase? merge commit?). Do not force-push or reset.

- [ ] **Step 7.3: Push main to origin**

Run:
```bash
git push origin main
```
Expected: push succeeds. The `release-please` workflow is now live and will fire on this push.

- [ ] **Step 7.4: Observe the GitHub Actions workflow run**

Wait ~30-60 seconds, then run:
```bash
gh run list --workflow=release-please.yml --limit 3
```
Expected: one or more recent runs visible, topmost one should show `in_progress` or `completed` with status `success`.

If the run has completed with status `failure`, fetch the logs:
```bash
gh run view --log-failed
```
Common first-run failure causes:
- **Workflow permissions not enabled** — the repo's Settings → Actions → General → "Workflow permissions" may be set to "Read repository contents". Must be "Read and write" OR the per-job `permissions:` block in our YAML must be honored. If it's a permissions problem, the error message will be explicit; ask Cameron to flip the repo setting.
- **Branch protection blocks the bot PR** — if `main` has branch protection requiring PR reviews, the bot can't open PRs or push. Usually not a factor on a solo repo; if it is, ask Cameron to allow the bot.

If the run fails for any other reason, this is the "fall back to git-cliff" escape hatch — document the failure in `dev/implementation-log.md` and stop; do not attempt to force-fix CI in this task.

- [ ] **Step 7.5: Observe the first Release PR**

After the workflow succeeds, check for the Release PR:
```bash
gh pr list --label "autorelease: pending"
```
Expected: **one PR** titled something like `chore(main): release 1.1.0`. Body should show a changelog draft listing the post-v1.0.0 `feat:` / `fix:` commits (NOAA pipeline work) grouped under Features / Bug Fixes sections.

**Coaching note — what to look at in this PR:**
- The `CHANGELOG.md` diff should show a new `## [1.1.0]` section above the existing `## [1.0.0]` section.
- `.github/.release-please-manifest.json` should bump from `"1.0.0"` to `"1.1.0"`.
- The PR description mirrors the CHANGELOG entry — this is what becomes the GitHub Release body.

**Do NOT auto-merge this PR in Task 7.** Leave it open for Cameron to review. Merging is a user decision: he may want to wait until the next few NOAA deferred-item fixes land to bundle more into v1.1.0, or he may merge immediately to get a clean release point.

- [ ] **Step 7.6: Finalize the implementation log**

Return to `dev` branch so future work doesn't accidentally land on `main`:

```bash
git switch dev
```

Expected: `Switched to branch 'dev'`.

Update the "Commits" and "Outcome" sections of the 2026-04-18 entry in `dev/implementation-log.md` with the actual SHAs of the five rollout commits and the Release PR URL:

```markdown
### Commits
- `60d6f63` — docs: add version control strategy design spec
- `<sha>` — docs: adopt semver and conventional commits
- `<sha>` — docs: add implementation log with seed entries
- `<sha>` — docs(claude): add project ethos, commit discipline, and mirror to AGENTS.md
- `<sha>` — ci: add release-please workflow for automated versioning
- `<sha>` — docs: mark versioning strategy complete in START.md
- `<sha>` — docs: record 2026-04-18 regression check in implementation log

### Outcome
- 2026-04-18 regression check: 579 tests pass, 2 pre-existing M2M failures
  + 9 pre-existing OSM POI errors (unchanged from 2026-04-17).
- Merge to main triggered release-please on first run; Release PR for
  v1.1.0 opened at <PR URL>, retroactively covering the post-v1.0.0
  NOAA hardening work. Cameron to review and merge when ready.
- Machinery is live. Future commits with type `feat:` / `fix:` / `perf:`
  will be aggregated into the next Release PR automatically.
```

Commit:
```bash
git add dev/implementation-log.md
git commit -m "$(cat <<'EOF'
docs: finalize versioning strategy rollout log entry

Backfill commit SHAs, test counts, and Release PR URL into the
2026-04-18 implementation log entry.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Then push dev:
```bash
git push origin dev
```

- [ ] **Step 7.7: Final verification — the done criteria**

Walk through the verification list from the spec (§Verification / done criteria). Each item should be green:

1. Policy docs exist at repo root (`ls VERSIONING.md CHANGELOG.md UPGRADING.md CONTRIBUTING.md AGENTS.md`).
2. `.github/workflows/release-please.yml` + the two JSON configs exist.
3. `dev/implementation-log.md` exists with ≥2 seed entries (`grep -c "^## 20" dev/implementation-log.md` ≥ 2).
4. `CLAUDE.md` and `AGENTS.md` both contain matching `## Project ethos` and `## Commit and release discipline` sections.
5. `README.md` has a `## Versioning` section linking to the three policy docs.
6. `START.md` task #1 is now NOAA deferred items.
7. `git push origin main` completed; commits visible on GitHub.
8. GitHub Actions shows the `release-please` workflow ran successfully.
9. Release PR for v1.1.0 is open.
10. Test suite: 579 pass, 2+9 pre-existing non-regressions.

Any item not green → stop, do not mark the plan complete, investigate the specific item.

---

## Rollback plan (in case something goes wrong)

**If the merge to main creates a bad state:**
- The rollout commits are pure additions. Reverting is safe:
  ```bash
  git switch main
  git revert --no-commit <sha-of-ci-commit> <sha-of-claude-commit> \
    <sha-of-log-commit> <sha-of-policy-commit> <sha-of-start-commit>
  git commit -m "revert: roll back version control strategy rollout"
  git push origin main
  ```
- The new files can also be deleted in a single cleanup commit. Either approach is fine; `revert` preserves history, manual deletion looks cleaner.

**If release-please opens a Release PR with wrong content:**
- Do not merge it. Comment on the PR explaining what looks wrong. Options:
  - Tune `release-please-config.json`, push a fix, bot auto-updates the PR.
  - Close the PR without merging; the bot reopens it on the next push.
  - Delete the bot's branch (`autorelease/main`) to force a complete reset.

**If Actions fails entirely and GitHub setup is too time-consuming:**
- Fall back to `git-cliff` run locally before each tag. The Conventional Commits format is already in place, so no prep work is wasted. Document the pivot in `dev/implementation-log.md` and optionally remove the `.github/` files in a follow-up commit.

---

## Execution notes for subagent-driven development

- Fresh subagent per task is appropriate. Tasks are independent after Task 1 (Tasks 2-6 can run in order without Task 1 context; Task 7 depends on Tasks 1-6 being committed).
- Do NOT parallelize: Tasks 1-7 must run sequentially because each commit advances the HEAD and Task 7 depends on all prior commits being visible.
- Per-task review checkpoints are recommended after Task 1 (confirm policy docs land clean), after Task 4 (confirm CI files parse correctly), and after Task 7 (confirm release-please fired).

## Next work item after this plan

Per updated START.md §1: NOAA Pipeline Deferred Fixes (9 items from the
8-agent adversarial review, listed in handoff 2026-04-17). Those fixes
will be the first `fix:` commits to land after this rollout, and they
will appear in the v1.1.0 Release PR (already opened retroactively by
release-please on first run) or in a subsequent v1.1.1 PR depending on
merge timing.
