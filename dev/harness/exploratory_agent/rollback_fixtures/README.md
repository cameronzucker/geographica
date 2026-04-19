# Rollback Regression Fixtures

Each `.patch` file here is a captured diff of a known-fixed bug. Applied
IN REVERSE inside an LXD container (via `patch -R -p1`), it restores the
broken state. Running the exploratory agent against the broken state
must produce a finding that identifies the bug class.

This is how we keep confidence that the agent still catches things as
prompts and tooling evolve. Without these fixtures, a future prompt
regression could silently stop finding real bugs.

## Files

- websockets-missing.patch — captured from ef28cd8. Restores the
  2026-04-19 report where setup/requirements.txt lacks `websockets`
  and /ws/progress silently 404s. Agent should report a WebSocket /
  progress-stream finding.
- trailing-slash-accepted.patch — captured from 1d59197. Restores
  the 2026-04-19 report where custom data paths with a trailing `/`
  propagate into bash string-concat and produce `//`. Agent should
  report an input-validation finding in Step 1.

## Usage

```
# Applied automatically by tests/test_exploratory_rollbacks.py.
# Manual:
cd /tmp && mkdir t && cd t
git clone --depth=1 /path/to/geographica .
patch -R -p1 < dev/harness/exploratory_agent/rollback_fixtures/websockets-missing.patch
# Rebuild the wizard container, run --exploratory, verify findings include
# a websockets-class finding.
```

v2: automate this via a new `--rollback=NAME` flag on wizard-ci.sh that
applies the patch in-container before the agent runs.
