# dev/harness — Setup wizard CI regression harness

Deterministic LXD + Playwright walkthrough of the browser-based setup wizard.
Pinpoints whether a known-good sequence of clicks still produces a healthy
Geographica stack, end-to-end.

## Setup (once per CI host)

LXD must be installed and initialized on the host:

```bash
sudo apt install lxd
sudo lxd init --minimal
```

Install harness dependencies:

```bash
cd dev/harness
npm install
npx playwright install chromium --with-deps
```

## Usage

Run the full harness (LXD launch → bootstrap → setup wizard walkthrough):

```bash
./wizard-ci.sh --smoke   # walks through Steps 1-4, exits clean (~3 min)
./wizard-ci.sh --full    # runs the pipeline + waits for healthy stack (~8 hr)
```

On CI (GitHub Actions), invoke via the manual-dispatch workflow at
`.github/workflows/wizard-ci.yml`.

## How it fits with the lxd-validation skill

The [lxd-validation skill](../../../.claude/skills/lxd-validation/) is
**agent-driven and exploratory** — it dispatches multi-persona AI testers
to catch usability gaps, confusing error messages, or missed prerequisites.
It's good at finding new classes of problem.

This harness is **deterministic and regression-focused** — it runs a fixed
sequence of clicks and asserts the stack reaches a healthy state. It's good
at catching regressions in code the skill has already vetted.

**Use both. They're complementary:**
- The skill catches "this workflow is confusing to a first-time user."
- The harness catches "this workflow, which worked yesterday, no longer
  produces a healthy stack."

## Pre-state matrix (`bootstrap-matrix.sh`)

The LXD harness above runs against a single, clean Debian cloud container
— it exercises the happy path. That's what our internal tests saw when
the 2026-04-19 beta-tester blocker was shipping: a dpkg file-conflict
between Debian-native `docker-buildx`/`docker-compose` and Docker's
`*-plugin` packages, which only materializes when the target system
already has the Debian packages installed. The clean cloud image never
saw that state, so the harness never caught it.

`bootstrap-matrix.sh` closes that gap by exercising bootstrap's apt
block against a **matrix of realistic customer starting states**, each
in an ephemeral Debian 13 Docker container. Runs in ~10 min across all
four pre-states.

```bash
./bootstrap-matrix.sh                   # all pre-states (~10 min)
./bootstrap-matrix.sh <pre-state-name>  # single pre-state (~3 min)
./bootstrap-matrix.sh --help            # list available pre-states
```

**Current pre-states** (in [`pre-states/`](pre-states/)):

| Name | What it simulates |
|------|-------------------|
| `clean` | Fresh system, no Docker packages. Baseline regression guard. |
| `debian-docker-buildx` | **THE 2026-04-19 beta blocker.** Debian's `docker-buildx` + `docker-compose` preinstalled. Exercises the `fix(setup): purge Debian-native docker packages` commit. |
| `docker-io` | User ran `sudo apt install docker.io` before finding bootstrap. Superset of the above: also exercises purge of `docker.io`, `containerd`, `runc`. |
| `get-docker-com` | User followed https://get.docker.com first. Exercises the `.asc` keyring guard added in commit `8608b6d` and asserts bootstrap is idempotent against the Docker convenience script. |

**How it works:** the runner extracts the `[1/6] Installing system
packages...` block from `bootstrap.sh` via awk (no duplicate source),
launches a fresh `debian:trixie` container per pre-state, seeds it
with baseline tooling (curl, gpg, ca-certificates — present on any
real Pi), sources the pre-state snippet, then executes the bootstrap
slice. On success it asserts `docker-ce`, `docker-ce-cli`,
`containerd.io`, and `docker-compose-plugin` are all installed AND
that no Debian-native conflicting package is in
`install ok installed` state (config-files state is fine — that's
how `apt remove` leaves packages, and we want to preserve user
config).

**Why Docker not LXD?** This matrix is apt/dpkg-focused and doesn't
exercise systemd, port binding, or the wizard UI — which LXD is
required for. Docker containers start in ~1 s vs. LXD's ~15 s per
container, so running four pre-states in Docker is ~10 min total
vs. ~30 min in LXD. The LXD harness (`wizard-ci.sh`) handles the
full wizard walkthrough once bootstrap has succeeded; this matrix
handles bootstrap itself.

**Adding a pre-state:** drop `foo.sh` in [`pre-states/`](pre-states/)
with `set -e` and whatever precondition commands the scenario needs
(`apt install -y ...`, `curl ... | sh`, etc.). The runner discovers
`*.sh` files automatically and dispatches by name. Add the new name
to `REQUIRED_PRE_STATES` in [tests/test_bootstrap_matrix.py] so the
canary fails if someone later deletes the file.

## Files

- `wizard-ci.sh` — top-level shell script; manages LXD container lifecycle.
- `drive-wizard.mjs` — Playwright script; drives the wizard UI.
- `package.json` — pins Playwright version for reproducibility.
- `bootstrap-matrix.sh` — apt-level pre-state matrix (runs in Docker, not LXD).
- `pre-states/` — modular pre-state snippets consumed by `bootstrap-matrix.sh`.
