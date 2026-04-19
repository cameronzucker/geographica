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

## Files

- `wizard-ci.sh` — top-level shell script; manages LXD container lifecycle.
- `drive-wizard.mjs` — Playwright script; drives the wizard UI.
- `package.json` — pins Playwright version for reproducibility.
