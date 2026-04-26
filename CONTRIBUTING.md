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

## Regression gates

### Nav keep-awake

Changes to any of these files require re-running the manual field acceptance checklist in [docs/superpowers/specs/2026-04-20-nav-keep-awake-design.md](docs/superpowers/specs/2026-04-20-nav-keep-awake-design.md) §6.3 on a real phone, with screenshot/video evidence attached to the PR body:

- `frontend/wake-lock.js`
- `frontend/silent-video-lock.js`
- `frontend/vendor/silent.mp4`
- The hook lines in `frontend/nav-ui.js` (`WakeLock.acquire()` / `WakeLock.release()`)
- `nginx/nginx.conf` when adding `Content-Security-Policy` or `Permissions-Policy` headers (per spec §13)
