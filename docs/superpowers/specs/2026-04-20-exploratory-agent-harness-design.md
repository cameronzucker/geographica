# Exploratory-Agent Beta-Tester Harness — Design Spec

**Date:** 2026-04-20
**Scope:** A new mode of `dev/harness/` that dispatches a Claude-powered agent to walk the setup wizard like a bug-bounty tester. Catches new-shape input-validation / resilience / UX bugs before human beta testers hit them.
**Files (new):** `dev/harness/exploratory_agent/` (Python package), `dev/harness/findings/`, `tests/test_exploratory_agent.py`
**Files (modified):** `dev/harness/wizard-ci.sh`, `dev/harness/README.md`, `.github/workflows/wizard-ci.yml`
**Source of motivation:** five consecutive beta-tester bug reports in April 2026, each a novel input/resilience class that the deterministic smoke + pipeline-start harness couldn't preempt without knowing the shape in advance:
1. Debian Trixie `docker-buildx` file-conflict (pre-existing host state)
2. `websockets` missing from `setup/requirements.txt` (post-preflight failure)
3. OSM PBF corruption from interrupted `wget -c` (mid-pipeline)
4. CSRF token regenerated on `setup.sh` restart (stale-tab resilience)
5. Trailing slash in custom data path (input-normalization)

---

## Summary

`dev/harness/` currently has two deterministic modes:

- `--smoke` — asserts the wizard loads through Step 4 with preflight green (~5 min).
- `--pipeline-start` — smoke plus one additional assertion: clicking "Start Pipeline" emits a `step_start` WebSocket frame within 30 s (~5 min).

Both modes only catch regressions in classes we already know about. Every new beta-tester bug this April was a class we hadn't asserted. The pattern is: human hits bug → screenshot → diagnose → fix → add regression assertion. We are reactive.

This spec adds a third mode:

- `--exploratory` — launches an LXD container, stands up the wizard, then dispatches a Claude agent (Sonnet 4.6 via the Anthropic Python SDK) with Playwright-like tools + API probes + container-state mutation. The agent is prompted as a bug-bounty-style beta tester, given a seed list of bug-class hypotheses (all five April classes plus standard OWASP-adjacent input fuzzing), and told to report every suspicious observation via a structured `report_finding()` tool. Output is a machine-readable YAML plus a human-readable markdown report committed to `dev/harness/findings/YYYY-MM-DD-HHMM.md`.

Findings do NOT auto-fail the harness (would be noisy). They are reviewed by hand; each real bug becomes a new scripted assertion in `drive-wizard.mjs` or a pytest regression, same pattern we've been using manually. The agent is the **discovery** layer; the scripts remain the **regression** layer. Same economics as fuzzing: the fuzzer finds crashes, the unit tests prevent them.

### Why not just extend `drive-wizard.mjs`?

`drive-wizard.mjs` tests a fixed, deterministic walk. Each new assertion added there increases coverage of one known class. An exploratory agent covers a combinatorial space of inputs and sequences that no finite script enumerates. They compose: the deterministic harness catches regressions cheaply; the agent catches novel classes at higher cost.

---

## Goals

1. **Catch novel input-validation bugs.** Trailing slash was the symptom this week; next week's will be something else. Broad input fuzzing against every form field, every API endpoint, every wizard step.
2. **Catch resilience bugs.** Restart setup.sh mid-flow. Refresh the browser at arbitrary step boundaries. Double-click Next. Navigate backward then forward. Fill inputs out of order.
3. **Produce human-auditable evidence.** Every finding gets a markdown entry with reproduction steps + observed vs. expected behaviour + DOM/console/network snapshot paths. A human can sanity-check each in ~30 seconds.
4. **Integrate with existing harness plumbing.** Reuse `wizard-ci.sh`'s LXD-container + setup.sh + proxy infrastructure. Add a mode flag, not a parallel tool.
5. **Non-blocking by default.** The `--exploratory` run produces findings but does NOT gate CI merges. Findings are surfaced for human triage, then converted (by hand, by another agent, or by review) into deterministic assertions in `drive-wizard.mjs`.

## Non-goals

- **Not a fuzzer for the pipeline code itself.** The pipeline container + pipeline scripts are out of scope. The exploratory agent drives the wizard UI + API; the pipeline runs for minutes-to-hours and is covered separately by `--pipeline-start` + `--full`.
- **Not a security pentest.** We assume the wizard binds `127.0.0.1` and the attacker model is "confused beta tester," not "hostile LAN peer." True security review is out of scope.
- **Not a replacement for human beta testing.** Humans find UX bugs an agent won't — emotional friction, confusing copy, counter-intuitive flow. Agent finds input/resilience bugs cheaply + continuously; humans still catch the rest.
- **Not auto-fixing.** Agent reports; humans and other agents fix.

---

## Architecture

```
wizard-ci.sh --exploratory
  │
  ├─ [existing] lxc launch images:debian/trixie/cloud
  ├─ [existing] copy repo via git ls-files | tar
  ├─ [existing] ./bootstrap.sh
  ├─ [existing] systemd-run ./setup.sh
  ├─ [existing] LXD proxy: host 127.0.0.1:18099 → container 127.0.0.1:8099
  │
  └─ NEW: python3 -m dev.harness.exploratory_agent
            --url=http://127.0.0.1:18099
            --container=$CONTAINER
            --max-minutes=15
            --output=dev/harness/findings/2026-04-20-1430.md
              │
              ├─ Loads ANTHROPIC_API_KEY from env
              ├─ Instantiates Anthropic Python SDK client
              ├─ Enters tool-use message loop (max 200 turns OR max_minutes)
              ├─ Each turn:
              │     send system+history to claude-sonnet-4-6
              │     receive either:
              │       - text message → log to transcript
              │       - tool_use block → dispatch to tool handler → append tool_result
              ├─ Tools (Python functions invoked from the loop) — see contract below.
              └─ On loop exit: render findings markdown, exit 0 (pass) or 2 (runtime error)
```

**Agent SDK choice:** Anthropic Python SDK (`pip install anthropic`), message API with tool use. Not the higher-level Agent SDK — we want explicit control of the tool handlers (they invoke shell + Playwright + the LXD CLI, so the security-relevant surface lives in our code).

**Playwright surface:** One long-lived Chromium instance per run. The Python side owns it via the `playwright` Python package (`pip install playwright` + `playwright install chromium`). The agent does NOT write Playwright code; it calls high-level tool wrappers we maintain.

**Claude model:** `claude-sonnet-4-6`. Haiku 4.5 would be cheaper but loses on reasoning about "is this DOM state correct." Budget is ~$2–5 per run at 15 min; acceptable for nightly CI.

**Prompt caching:** Enable `cache_control: {type: "ephemeral"}` on the system prompt + bug-class seed list (both static per run). That block is ~5 KB; cache-hit on every turn after the first reduces per-turn cost materially.

---

## Tool surface (interface contract)

Every tool is a Python function with a JSON-schema-describable signature. The list below is the complete v1 surface. Additions after v1 are fine; no removals without spec update.

### Browser tools (stateful — one Playwright page shared across calls)

```
page_goto(url: str) -> { "status": int, "final_url": str }
page_click(selector: str) -> { "ok": bool, "error"?: str }
page_fill(selector: str, value: str) -> { "ok": bool, "error"?: str }
page_select_option(selector: str, value: str) -> { "ok": bool, "error"?: str }
page_press(selector: str, key: str) -> { "ok": bool, "error"?: str }
page_inner_text(selector: str) -> { "ok": bool, "text"?: str, "error"?: str }
page_is_visible(selector: str) -> { "ok": bool, "visible"?: bool, "error"?: str }
page_body_text() -> { "text": str }    # document.body.innerText, truncated to 16 KB
page_console_errors() -> { "errors": list[str] }    # accumulated, not cleared
page_pageerrors() -> { "errors": list[str] }
page_websocket_frames() -> { "frames": list }    # truncated 4KB/frame, 200 frame cap
page_reload() -> { "status": int }
page_screenshot(label: str) -> { "path": str }    # writes PNG into findings/screenshots/
```

### API tools (bypass the browser entirely)

```
api_request(method: str, path: str, headers?: dict, json?: dict, raw_body?: str, csrf: "auto"|"skip"|str = "auto") -> {
  "status": int,
  "headers": dict,
  "body_text": str,    # truncated to 8 KB
  "body_json"?: any
}
# csrf="auto": fetch current CSRF token from meta tag and include in header
# csrf="skip": don't send CSRF header (tests whether endpoint allows it)
# csrf="<literal>": send the given string (tests stale/forged token handling)
```

### Container tools (disruption)

```
container_run_command(command: str) -> { "exit": int, "stdout": str, "stderr": str }
# Shells out to `lxc exec $CONTAINER -- bash -c "$command"`.
# stdout/stderr truncated to 4 KB each.

container_restart_wizard() -> { "ok": bool }
# Restarts the systemd-run wizard unit inside the container.
# Used to test CSRF persistence / stale-tab recovery.

container_fs_write(path: str, content: str) -> { "ok": bool }
# Writes a file inside the container (for pre-state seeding).
# Refuses paths outside /srv, /tmp, /run.

container_fs_read(path: str) -> { "ok": bool, "content"?: str }
# Truncates to 8 KB.
```

### Control flow

```
wait_seconds(n: int) -> { "waited": int }    # capped at 30
describe_wizard_state() -> {
  "step": int|null, "step_name": str|null,
  "visible_error_banners": list[str],
  "preflight_dots": list,
  "btn_next_text": str|null,
  "btn_next_disabled": bool|null
}
# Convenience summary so the agent doesn't have to ask 10 page_* questions
# every turn.
```

### Reporting

```
report_finding(
  classification: str,        # one of the seeded classes OR "novel"
  severity: "critical"|"high"|"medium"|"low"|"cosmetic",
  title: str,                 # one-line summary
  reproduction_steps: list[str],
  input: dict,                # inputs that triggered the finding
  observed: str,
  expected: str,
  evidence: dict              # paths to screenshots/dom/console snapshots
) -> { "id": str }

checkpoint(message: str) -> { "ok": bool }
# Logs a progress marker to the transcript without being a finding.

stop(reason: str) -> { "stopped": true }
# Agent signals it's done. Loop exits after logging the reason.
```

### Tool contract invariants

1. Every tool returns JSON-serialisable output. No exceptions leak to the agent.
2. Every tool validates its arguments against its JSON schema; invalid arguments produce `{"ok": false, "error": "..."}`.
3. Tool output is truncated at documented limits. The agent is not trusted with unbounded logs.
4. `container_fs_write` and `container_run_command` are **NOT** sandboxed inside the agent's process — they run against the LXD container. The container is ephemeral and deleted at the end of the run, so destructive operations are acceptable and expected. This is a deliberate design choice for "disruption" coverage.

---

## System prompt structure

The prompt is stored in `dev/harness/exploratory_agent/prompts.py` and injected verbatim into every session. Rough shape:

1. **Persona.** "You are an adversarial beta-tester for Geographica..."
2. **Environment.** URL, container name, caveat that the container is ephemeral and can be disrupted.
3. **Seed bug-class list** (stored separately at `dev/harness/exploratory_agent/bug_classes.md` so it can evolve):
   - Input validation: trailing/leading whitespace, trailing slashes, doubled slashes, unicode, emoji, extremely long (>4KB), empty, path traversal, null bytes, relative paths, shell metacharacters.
   - Resilience: stale CSRF after wizard restart, backward-then-forward nav, double-click Next, refresh mid-step, two tabs, brief network loss, fields in reverse order.
   - Validation feedback: silent swallow, unhelpful error copy, raw Python tracebacks in UI, auto-dismiss banners, misleading button labels.
   - Protocol/API: missing CSRF, wrong Content-Type, malformed JSON, missing required field, extra unexpected field, huge payload, idempotency (POST /api/start twice).
   - Novel: anything else that looks wrong.
4. **Already-known bug list** so the agent doesn't waste budget rediscovering the five April bugs. Each entry: class + one-line description.
5. **Stop conditions** (time-box, turn-cap, exhaustion).
6. **Reporting rules** (one finding per bug; reproduction steps required; before/after screenshots).
7. **Tool usage guidance** (`describe_wizard_state` at start of each new hypothesis; `page_body_text` to scan for Traceback; `api_request` with `csrf="skip"` for API-level tests; `container_restart_wizard` sparingly — 20 s cost each).

---

## Findings file format

`dev/harness/findings/YYYY-MM-DD-HHMM.md`:

```
# Exploratory-Agent Findings — 2026-04-20 14:30

**Container:** images:debian/trixie/cloud
**Pre-state:** clean
**Agent model:** claude-sonnet-4-6
**Runtime:** 14:30 to 14:44 (14m 12s)
**Turns used:** 83 / 200
**Transcript:** dev/harness/findings/2026-04-20-1430.transcript.jsonl
**Findings:** 7

---

## Finding 1 — HIGH — input-validation

**Title:** Pasting a BOM (U+FEFF) at the start of #data-custom-path makes
validate-path reject the path with a confusing "Path not absolute" message
even though the visible text starts with /.

**Reproduction:**
1. Launch wizard, reach Step 1.
2. Choose "Other (custom path)".
3. Paste U+FEFF + "/srv/geographica/data" into the input.
4. Click Next.
5. Observe the error banner.

**Input:** {"field": "#data-custom-path", "value": "<BOM>/srv/geographica/data"}

**Observed:** Error banner reads "Invalid data path: Path must be absolute (start with /)".

**Expected:** Either (a) input is silently stripped of BOM and validated normally, or (b) error message explicitly names the offending character.

**Evidence:**
- Screenshot before: screenshots/f1-before.png
- Screenshot after: screenshots/f1-after.png
- DOM snapshot: dom/f1.html

---

## Finding 2 — ...
```

Every finding must be standalone-readable. Human reviewer decides fix vs. dismiss vs. defer. Dismissed findings go into `findings/dismissed/` with a one-line note explaining why.

---

## Integration with existing harness

`wizard-ci.sh` gains one new mode:

```
./wizard-ci.sh --exploratory [--image=ALIAS] [--pre-state=NAME] [--max-minutes=N]
```

Flow:
1. Same container launch + bootstrap + setup.sh start + proxy setup as existing modes.
2. Instead of invoking `node drive-wizard.mjs`, invoke
   `python3 -m dev.harness.exploratory_agent --url="$WIZARD_URL" --container="$CONTAINER" --max-minutes="${MAX_MINUTES:-15}" --output="$OUTPUT_PATH"`.
3. Output path is `dev/harness/findings/$(date +%Y-%m-%d-%H%M).md` by default; overridable via `--output=...`.
4. Exit 0 regardless of findings (non-blocking by design). Exit 2 on agent runtime error (missing API key, Playwright install broken, LXD container died, etc.).

CI wiring (`.github/workflows/wizard-ci.yml`):

- **On push/PR:** nothing changes. `--smoke` + `--pipeline-start` remain the gate.
- **Nightly schedule:** add a new job `wizard-exploratory` that runs `--exploratory --max-minutes=15` and uploads `dev/harness/findings/*.md` as a workflow artifact. Does not fail the workflow on findings.
- **Manual dispatch:** add `exploratory` as a mode option.

The `ANTHROPIC_API_KEY` secret must be configured on the self-hosted Pi runner. Plan Task covers this.

---

## Acceptance criteria

1. `./wizard-ci.sh --exploratory --max-minutes=5` runs to completion on a clean Pi with the self-hosted runner's `ANTHROPIC_API_KEY` set. Produces a findings file. No crashes.
2. A findings file is parseable: has the header, ≥0 findings in the specified format, all referenced screenshots actually exist.
3. Running the agent against a **deliberately broken wizard** (e.g. rolling back one of the April fixes) produces a finding that identifies that class. Regression-tested in CI against the websockets-removed and trailing-slash-accepted rollbacks.
4. Running against the **current main** yields ≥0 findings (we expect some novel findings on the first real run; ≥1 novel finding is evidence the agent is doing useful work; 0 is acceptable but should be re-verified after expanding the bug-class prompt).
5. Every tool has a unit test covering at least one successful call and one error case. Mocked Playwright / SDK / LXD; no real containers in unit tests.
6. README (`dev/harness/README.md`) gains a section explaining the mode, its cost (~$2–5/run), its output, and the "findings → scripted assertions" workflow.

---

## Out-of-scope for v1

- Multi-agent / parallel exploration
- Cross-image matrix (raspios, pre-states)
- Auto-conversion of findings into scripted tests
- Statistical analysis of findings over time
- Cost-optimisation beyond prompt caching (Haiku fallback for cheap sub-tasks)
- Running inside CI push-trigger (cost too high for every PR; nightly only for v1)
- Container-disruption tools doing real kernel/network disruption (tc, iptables) — too environment-fragile for v1

All of these are reasonable v2 work once v1 proves useful.

---

## Open questions

1. **Findings review responsibility.** Initially a human reviews every findings file. Does v2 use a second agent to triage-and-file them as GitHub issues? Out of scope for v1, mentioned here so the finding format stays machine-readable.
2. **Deterministic re-play.** Finding 1's "paste U+FEFF" is reproducible because it names an exact input. But an agent-explored sequence of 40 clicks that reveals a race — how do we re-play it? Transcript is JSONL of every tool call + result; a future `replay-transcript.py` could re-drive a container from that JSONL. Out of scope for v1.
3. **Prompt injection.** If the wizard ever renders user-supplied strings, and the agent reads those back via `page_body_text`, a crafted wizard response could theoretically redirect the agent. Low risk for a setup wizard (no user-authored content), but worth revisiting if the wizard ever gains user-content surfaces.

---

## Summary of deliverables

- `dev/harness/exploratory_agent/` Python package (see plan for file list)
- `dev/harness/findings/` directory + `.gitkeep`
- `dev/harness/wizard-ci.sh` updated with `--exploratory` mode
- `dev/harness/README.md` updated
- `.github/workflows/wizard-ci.yml` updated (nightly schedule + manual-dispatch option)
- `tests/test_exploratory_agent.py` unit tests for tool handlers
- At least one real-run findings file committed as evidence (`dev/harness/findings/2026-04-20-<time>.md`)
- Rollback-regression fixtures (see plan Task 9) — one broken-wizard config per already-known bug class, run as a CI gate to verify the agent still catches them
