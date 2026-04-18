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
