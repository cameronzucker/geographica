---
name: lxd-validation
description: Test README/install docs in an isolated LXD container — dispatches multi-model, multi-persona agents to validate from different skill levels, then consolidates into a cross-referenced report with Playwright screenshots. Use when validating setup documentation, testing install guides, or auditing README accuracy.
argument-hint: "<document, e.g. 'README.md', 'docs/install.md', 'full stack'>"
---

# LXD Validation

Testing documentation for: **$ARGUMENTS**

This is a multi-phase workflow. Follow each phase in order. Do not skip phases.

## HARD RULES — Read Before Anything Else

These rules are non-negotiable. They override any judgment call you might make.

1. **NEVER stop, restart, or modify any host process or service.** Not Docker containers, not systemd services, not cron jobs, nothing. You work within available headroom or you degrade to a lighter test mode.
2. **If available RAM drops below 1.5 GB at any point: STOP IMMEDIATELY.** Clean up the container, report what happened, and ask the user. Do not attempt to free resources.
3. **Container memory limit = available RAM minus 2 GB.** Floor of 1 GB. If less than 1 GB is available after the safety margin, abort and explain why.
4. **Never test against the host's services.** All Playwright screenshots and curl checks must target the container IP. Verify this before every capture.
5. **Ask before deleting existing LXD containers.** If `validation-test` already exists, confirm before removing it.
6. **The user can override safety margins** with explicit instruction, but you never assume permission.

---

## Phase 1: Intake & Project Analysis

Read the target document and the codebase to understand what you're validating.

### 1a. Document Discovery

If `$ARGUMENTS` specifies a file, read it. If `$ARGUMENTS` is vague or omitted, scan for:
- `README.md`, `INSTALL.md`, `SETUP.md`
- `docs/install*`, `docs/setup*`, `docs/getting-started*`

Present what you found and confirm with the user.

### 1b. Command Inventory

Extract every shell command from the document:
- Fenced code blocks (```bash, ```sh, ```)
- Inline commands in numbered steps or bullets
- Commands embedded in prose paragraphs

For each command, record: the command text, which section/step it appears in, and any prerequisites implied by surrounding context.

### 1c. Project Classification

Classify the project. A project can belong to multiple categories.

| Category | Detected by | Validation it enables |
|----------|------------|----------------------|
| Docker/Compose stack | `docker-compose.yml`, `Dockerfile`, `docker compose` in docs | Container-in-container testing, service health checks |
| Web frontend | Port bindings (80, 443, 3000, 8080, etc.), browser references, HTML/JS | Playwright screenshots |
| CLI tool | `pip install`, `npm install -g`, `cargo install`, binary in PATH | Command execution + output validation |
| Library | `import` statements, test suites, no service startup | Build + test suite execution |
| Bare-metal services | `systemctl`, config in /etc, no Docker | Service start + port checks |
| Data pipeline | Scripts that download/process/output files | File existence + size validation |

### 1d. Intake Questions

Present the classification and ask targeted questions. Only ask questions relevant to the detected categories. Do not ask all of these for every project.

1. "I've identified this as a **[categories]**. Is that correct, or am I missing something?"
2. "The docs reference these external dependencies/downloads: **[list]**. For quick mode, do you have pre-built data I should bind-mount? Where?" *(Docker/pipeline projects only)*
3. "I see these hardware-specific references: **[list]**. Which should I skip vs. mock?" *(only if hardware refs detected)*
4. "What does success look like beyond 'it starts'? Any specific functionality to verify?" *(always ask)*
5. "Target audience for the docs — who is the intended reader?" *(always ask — informs persona selection)*
6. "The docs target **[distro]**. Should I test in Debian 13, Ubuntu 24.04, Fedora 41, or something else?" *(only if distro-specific commands detected)*

A simple CLI tool gets questions 1, 4, 5. A Docker stack gets all six.

**Wait for user answers before proceeding.**

---

## Phase 2: Resource Assessment & Mode Selection

### 2a. Host Resource Survey

Run these commands and record the output:

```bash
# Available RAM (MB)
free -m | awk '/^Mem:/{print $7}'

# Disk free on likely storage locations
df -BG / /srv /var/lib/lxd 2>/dev/null

# Running Docker containers (snapshot for post-cleanup verification)
docker ps --format '{{.Names}}\t{{.Status}}' 2>/dev/null

# Running LXD containers
lxc list --format csv 2>/dev/null

# Listening ports (snapshot for post-cleanup verification)
ss -tlnp | grep -E ':(80|443|[0-9]{4})\b' 2>/dev/null
```

Save the Docker, LXD, and port snapshots — you need them in Phase 8 for host verification.

### 2b. Mode Selection

Use this matrix to select the heaviest safe mode:

| Available RAM | Available Disk | Selected Mode |
|--------------|---------------|---------------|
| < 2 GB | Any | **Structural only** |
| 2-4 GB | < 10 GB | **Structural only** |
| 2-4 GB | 10+ GB | **Structural + Quick** (reduced container memory) |
| 4-8 GB | 10+ GB | **Structural + Quick** |
| 8+ GB | 30+ GB | **Structural + Quick + Full** |
| 8+ GB | < 30 GB | **Structural + Quick** |

Calculate the container memory limit: `available_ram_mb - 2048` (floor: 1024 MB).

Present the decision to the user:

> "Host has **X GB RAM free** and **Y GB disk free**. Running containers: [list]. I'll run **[selected mode]** with a **Z MB container memory limit** (2 GB safety margin for host). To run a heavier mode, I'd need you to free resources — but I won't do that myself."

**Wait for user confirmation before proceeding.**

### 2c. OOM Monitoring

Throughout all subsequent phases, check `free -m` before any resource-intensive operation (launching container, starting Docker inside container, dispatching parallel agents). If available RAM has dropped below 1.5 GB since last check:

1. Stop what you're doing
2. Run `lxc delete validation-test --force` if the container exists
3. Clean up temp files
4. Report: "Available RAM dropped to X MB. Cleaned up container. Here's what I completed before stopping: [summary]."
5. Ask the user how to proceed

---

## Phase 3: Structural Analysis

**This phase always runs**, even in structural-only mode. It's cheap and catches many issues without needing a container.

### 3a. Static Checks

Run these checks against the command inventory from Phase 1:

**Package name validation:**
For each `apt install`, `dnf install`, `brew install`, `pip install`, `npm install` command, verify the package exists:
```bash
apt-cache show <package> 2>&1 | head -1    # Debian/Ubuntu
```
If the host runs a different distro than the target, note this as "cannot verify on host — will verify in container."

**URL reachability:**
For every URL in the document, test reachability:
```bash
curl --head --max-time 10 --silent --output /dev/null --write-out "%{http_code}" "<url>"
```
Flag: 404, 000 (unreachable), 301/302 (moved — doc should update), placeholder patterns (your-org, example.com, TODO).

**File path references:**
For every path referenced in the document, check if it exists in the repo:
```bash
ls -la <path> 2>&1
```
Distinguish between: paths that should exist in the repo (bug if missing), paths created by earlier steps (ordering dependency), and paths on the target system (cannot verify on host).

**Command syntax:**
For multi-line script blocks, check syntax:
```bash
bash -n <<'SCRIPT'
<extracted commands>
SCRIPT
```
Run `shellcheck` if available.

**Implicit dependencies:**
Scan all commands for tools not listed in the document's prerequisites section. Common culprits: `wget`, `curl`, `unzip`, `git`, `make`, `gcc`, `python3`, `pip`, `node`, `npm`.

**Environment variables:**
Find all `$VAR` and `${VAR}` references. For each, verify it's either set by a prior step in the document, or documented as needing user configuration.

**Ordering analysis:**
Walk the command list sequentially. For each command, check whether its dependencies (files, packages, env vars, running services) are satisfied by prior steps. Flag gaps.

### 3b. Ambiguity Scan

Read the document as prose (not just the commands). Flag:

- **Vague instructions:** "set this to your IP address" — which IP? which interface?
- **Assumed knowledge:** "configure the firewall" — how? which tool? which ports?
- **Missing conditional guidance:** "if you're using X, do Y" — what if not using X?
- **Placeholder values that look real:** IP addresses, ports, domain names that might be examples but aren't marked as such
- **Unexplained jargon:** terminology the target audience (from intake) may not know

### 3c. Structural Report

Write preliminary findings to `docs/validation/<date>-structural.md`. This report:
- Lists every finding with its category and evidence
- Feeds into the parallel agent dispatch as context
- Becomes the **final output** if structural-only mode was selected (skip to Phase 7)

If structural-only mode: skip to Phase 7 now. Otherwise, continue to Phase 4.

---

## Phase 4: Container Setup

### 4a. LXD Pre-flight

```bash
which lxc || echo "LXD not installed"
lxc list 2>&1
lxc storage list 2>&1
```

**If LXD is not installed:** Stop. Tell the user:
> "LXD is not installed. To set up LXD for validation testing:
> 1. `sudo snap install lxd` (or `sudo apt install lxd` on Debian)
> 2. `sudo usermod -aG lxd $USER` then log out/in
> 3. `lxd init --minimal` — verify storage pool is `dir`-backed on your main disk, not a loop file
> 4. `lxc list` to verify
> Re-run this skill after setup."

Do NOT auto-install LXD.

**If LXD is installed but no storage pool or a loop-backed pool:** Warn about the loop file footgun (default is often a tiny loop file that fills up during Docker image pulls).

**If `validation-test` container already exists:** Ask the user before deleting it.

### 4b. Container Creation

Determine architecture and base image:
```bash
ARCH=$(uname -m)   # aarch64 or x86_64
# Use the distro from intake question 6, default to images:debian/13
```

Create the container:
```bash
lxc launch images:debian/13 validation-test \
  -c security.nesting=true \
  -c security.syscalls.intercept.mknod=true \
  -c security.syscalls.intercept.setxattr=true \
  -c limits.memory=${CALCULATED_LIMIT}MB
```

**Immediately verify networking:**
```bash
lxc exec validation-test -- ping -c1 8.8.8.8
lxc exec validation-test -- bash -c "apt update && echo 'DNS+HTTPS OK'"
```

If either fails, abort: "Container has no internet connectivity. Check LXD bridge config (`lxc network list`, `lxc network show lxdbr0`)."

**Get the container IP** (needed for Playwright later):
```bash
CONTAINER_IP=$(lxc exec validation-test -- hostname -I | awk '{print $1}')
```

### 4c. Code Injection

```bash
# On host: archive the repo (respects .gitignore, excludes large data files)
cd <repo-root> && git archive HEAD --format=tar.gz -o /tmp/validation-code.tar.gz

# Push into container and extract
lxc file push /tmp/validation-code.tar.gz validation-test/root/
lxc exec validation-test -- bash -c \
  "mkdir -p /root/project && tar -xzf /root/validation-code.tar.gz -C /root/project"

# Clean up host temp file
rm /tmp/validation-code.tar.gz
```

Note in the report: any `git clone` step in the docs was replaced with a tarball copy. The clone URL's reachability was already tested in Phase 3.

### 4d. Quick Mode Data Mounts

If the user identified pre-built data during intake:

```bash
lxc config device add validation-test hostdata disk \
  source=<user-specified-path> path=<target-path> readonly=true
```

For services needing write access to mounted data (databases, caches), create writable overlays:
```bash
lxc exec validation-test -- mkdir -p /path/to/writable
lxc exec validation-test -- cp -a /path/to/readonly/subdir/* /path/to/writable/
```

Document every mount and overlay in the report.

### 4e. Hardware Abstraction

For each hardware reference identified during intake that the user said to skip or mock:

- **Docker device mappings** (`/dev/ttyAMA0`, `/dev/video0`, etc.): Create a `docker-compose.override.yml` that removes the `devices:` section
- **systemd hardware services:** Skip or create stub configs
- **GPU/NPU references:** Note in the report as environment limitation

Document each abstraction in the report.

### 4f. Shell State Note

`lxc exec` runs each command as a separate process. Environment variables and working directory do NOT persist between calls. Use `bash -lc` for commands needing context:

```bash
lxc exec validation-test -- bash -lc "cd /root/project && source .venv/bin/activate && python setup.py"
```

For projects with many sequential commands, write a step script:
```bash
lxc exec validation-test -- bash -c 'cat > /root/run-step.sh << "SCRIPT"
#!/bin/bash
set -euo pipefail
cd /root/project
# ... commands from the doc ...
SCRIPT'
lxc exec validation-test -- bash /root/run-step.sh
```

---

## Phase 5: Parallel Agent Dispatch

This is the core of the validation. You dispatch agents with different perspectives to maximize finding coverage.

### 5a. Persona Definitions

| Persona | Model hint | Brief | What it catches |
|---------|-----------|-------|-----------------|
| **Experienced Ops** | `opus` | Senior sysadmin with 15 years of experience. Follows instructions precisely but notices when something is underspecified, fragile, non-portable, or non-idiomatic. Proactively tests edge cases. Knows what "should" happen and flags deviations. | Security issues, non-portable assumptions, missing error handling, undocumented prerequisites, fragile workarounds |
| **Junior Developer** | `sonnet` | First professional job. Comfortable writing code but unfamiliar with Linux administration, Docker networking, firewall rules, and system configuration. Follows instructions literally. When a step is ambiguous, picks the most common wrong interpretation. | Ambiguous instructions, assumed sysadmin knowledge, missing context, unclear terminology, steps that require googling |
| **Literal Newcomer** | `haiku` | Has never used this kind of software. Only does exactly what the document says — no inference, no troubleshooting, no "obviously you need to also do X." If a command fails, records the error and moves to the next step. | Missing steps, implicit assumptions, gaps between steps, wrong command order, assumed tool familiarity |

**Persona customization:** If the user described a specific target audience during intake, adjust the Junior Developer persona to match (e.g., "experienced Ruby developer new to Docker" instead of generic junior dev).

**Resource-constrained mode:** If resources are tight, reduce to 2 agents (Experienced Ops + Literal Newcomer — these have the most divergent perspectives).

### 5b. Execution Strategy

The agents share one container. They cannot execute simultaneously inside it.

**Step 1 — Agent 1 (Experienced Ops) executes the full document:**
This agent runs as a foreground agent. It:
- Follows every step in the document inside the container
- Captures the full output of every command (stdout + stderr)
- Takes Playwright screenshots at every detected milestone (see 5d)
- Records timing for each step
- Writes its findings to `docs/validation/<date>-ops.md`
- Returns its complete execution log in the response

**Step 2 — Agents 2 and 3 analyze in parallel:**
After Agent 1 completes, dispatch Agents 2 and 3 concurrently. They are **reviewers, not executors.** Each receives:
- Agent 1's full execution log
- The structural findings from Phase 3
- The target document text
- Their persona brief
- Access to the container for probing commands (read-only exploration, additional curl tests, checking file permissions, etc.)

They review the execution through their persona lens and write findings to their respective report files.

### 5c. Agent Prompt Template

Each agent gets this prompt structure. Fill in the bracketed sections.

**Agent 1 (Experienced Ops):**
```
You are validating setup documentation by following it step-by-step in a clean
LXD container. Your persona: senior sysadmin, 15 years experience. You follow
instructions precisely but you NOTICE and FLAG when something is underspecified,
fragile, non-portable, or non-idiomatic.

CRITICAL FRAMING: You are testing the DOCUMENTATION, not the software. A command
that works but isn't in the docs is a finding. A step that requires knowledge
the docs don't provide is a finding. Your job is to identify every gap between
what the docs say and what a real person would experience.

DOCUMENT BEING TESTED:
[paste full document text]

PROJECT TYPE: [classification from Phase 1]

STRUCTURAL FINDINGS (pre-identified issues to verify during execution):
[paste Phase 3 findings]

CONTAINER ACCESS:
- Container name: validation-test
- Container IP: [IP]
- Execute commands: lxc exec validation-test -- bash -lc "<command>"
- All commands run as root inside the container

SUCCESS CRITERIA (from user):
[paste answer to intake question 4]

INSTRUCTIONS:
1. Follow every step in the document, in order
2. For each step, record: the command you ran, its full output, pass/fail, and
   any observations about the documentation quality
3. If a step fails, record the error and attempt to continue (note the failure)
4. If you need to deviate from the docs (e.g., fix a broken step to continue),
   record BOTH the failure and your workaround — the workaround is NOT a fix,
   it's evidence of a doc gap
5. Take Playwright screenshots at milestones (see screenshot instructions below)
6. Write your report to docs/validation/<date>-ops.md
7. Return your complete execution log and findings in your response

[paste screenshot instructions from 5d if web frontend detected]

REPORT FORMAT:
# Ops Agent Report — <date>
## Execution Log
| Step | Command | Status | Duration | Observations |
## Findings
### [Title]
**Category:** Doc Bug | Ambiguity | Assumed Knowledge | Environment Gap | Software Bug
**Doc location:** [section/step in the document]
**Evidence:** [what happened vs what the docs say]
**Impact:** [who gets stuck and how]
## Screenshots
[list with descriptions]
```

**Agents 2 and 3 (Junior Dev / Literal Newcomer):**
```
You are reviewing a documentation validation run from the perspective of a
[persona description]. You did NOT execute the steps yourself — another agent
did. Your job is to review the execution log and the documentation, and flag
issues that someone matching your persona would encounter.

CRITICAL FRAMING: You are testing the DOCUMENTATION, not the software. You are
looking for gaps between what the docs say and what a person matching your
persona would actually experience. The ops agent who executed the steps may have
breezed past issues that would block you.

YOUR PERSONA:
[paste full persona brief]

DOCUMENT BEING TESTED:
[paste full document text]

EXECUTION LOG FROM OPS AGENT:
[paste Agent 1's complete execution log]

STRUCTURAL FINDINGS:
[paste Phase 3 findings]

CONTAINER ACCESS (for probing — do NOT re-execute the install):
- lxc exec validation-test -- bash -lc "<command>"
- Use this to check things like: file permissions, what config files look like,
  whether endpoints respond, what error messages say

INSTRUCTIONS:
1. Read the document through your persona's eyes. For EVERY step, ask: "Would I
   understand what to do here? Would I succeed?"
2. Cross-reference against the ops agent's execution log — where the ops agent
   succeeded, would you have succeeded following the same docs?
3. Flag any step where you would be confused, stuck, or would make a mistake
4. You may run probing commands in the container to verify your concerns
5. Write your report to docs/validation/<date>-[junior|newcomer].md
6. Return your findings in your response

REPORT FORMAT:
# [Persona] Agent Report — <date>
## Findings
### [Title]
**Step:** [which doc step]
**Persona impact:** [what would happen to someone like me]
**Category:** Doc Bug | Ambiguity | Assumed Knowledge | Environment Gap
**Severity:** CRITICAL | HIGH | MEDIUM | LOW
**Evidence:** [specific doc text that's problematic + what would actually happen]
```

### 5d. Playwright Evidence Collection

Only applicable when the project is classified as **Web frontend** AND Playwright MCP tools are available.

Agent 1 captures screenshots at these milestones:
- After all services pass health checks (if applicable)
- When a web UI is first accessible
- After performing each documented user-facing action (search, navigate, login, etc.)
- On any error page or unexpected visual state
- Success criteria tests from intake question 4

**Standard capture:**
```
Use browser_navigate to go to http://<CONTAINER_IP>:<PORT>
Then use browser_take_screenshot to capture the result
Save to docs/validation/<date>-screenshots/<NN>-<description>.png
```

**Self-signed TLS capture (if HTTPS is tested):**
```
Use browser_run_code with this script:
const context = await browser.newContext({
  acceptInsecureCerts: true,
  viewport: { width: 1280, height: 800 }
});
const page = await context.newPage();
await page.goto('https://<CONTAINER_IP>');
await page.screenshot({ path: '/tmp/screenshot.png' });
Then retrieve the file.
```

**GUARD: Before every screenshot, verify the target URL uses the container IP, not the host IP or localhost. Log the IP check in the execution log. Testing the host's services instead of the container is a critical error that invalidates the entire run.**

**If Playwright MCP is not available:** Substitute `curl -s <url> | head -50` for HTTP verification. Document in the report: "Playwright unavailable — HTTP responses verified via curl, no visual screenshots."

**WebGL note:** MapLibre, Three.js, and similar WebGL applications may not render in headless browsers inside LXC containers (no GPU). If the canvas is blank, document as an environment limitation, not a doc bug.

---

## Phase 6: Consolidation & Cross-Referencing

After all agents complete, read all reports and cross-reference findings.

### 6a. Completeness Requirement

You MUST account for every single finding from every agent report. Before starting consolidation, enumerate all findings across all reports. Every finding must appear in the consolidated report. You do NOT get to decide what's "too minor" — that's the user's decision.

### 6b. Deduplication

Group findings that describe the same underlying issue. Preserve each agent's phrasing — different perspectives on the same problem reveal different facets of the fix.

### 6c. Consensus Weighting

For each unique finding, note which agents flagged it:
- **3/3 agents** — high confidence, almost certainly a real issue
- **2/3 agents** — likely real, verify the evidence
- **1/3 agents** — needs extra scrutiny. Could be persona-specific. Cross-reference: does the target audience match the persona that flagged it? If only the newcomer flagged it and the docs target experienced sysadmins, it's lower priority but still documented.

### 6d. Classification

Classify each finding:

| Classification | Meaning |
|---------------|---------|
| **Doc Bug** | Documentation is factually wrong, has a missing step, or a dead link |
| **Ambiguity** | Documentation could reasonably be interpreted multiple ways |
| **Assumed Knowledge** | Step requires knowledge the target audience may not have |
| **Environment Gap** | Works on the tested distro but may fail on others |
| **Software Bug** | The software itself doesn't work as the documentation claims |
| **Environment Limitation** | Expected difference from real deployment (no hardware, no GPU, etc.) |
| **False Positive** | Finding is incorrect — explain why |

### 6e. Severity Assignment

| Severity | Criteria |
|----------|----------|
| **CRITICAL** | Blocks the user entirely. Cannot proceed past this step without external help. |
| **HIGH** | User can work around it but wastes significant time or gets a broken/partial result. |
| **MEDIUM** | User may be confused or get a suboptimal result but can proceed. |
| **LOW** | Cosmetic, minor friction, or affects only edge-case users. |

---

## Phase 7: Report Generation

### 7a. Consolidated Report

Write the final report to `docs/validation/<date>-<mode>-report.md`.

If the project's CLAUDE.md, AGENTS.md, or similar specifies a different validation output path, use that instead.

```markdown
# Validation Report — <date> (<mode>)

**Document tested:** <path to the document>
**Duration:** X minutes
**Container:** validation-test (<distro>, <arch>)
**Mode:** structural | quick | full
**Agents:** Experienced Ops (opus), Junior Dev (sonnet), Literal Newcomer (haiku)

## Executive Summary

X findings: N critical, N high, N medium, N low. N false positives. N environment limitations.
[1-2 sentence verdict: PASS, CONDITIONAL PASS, or FAIL with explanation]

## Findings by Severity

### CRITICAL

#### F1. <Title>
**Consensus:** <which agents flagged it — e.g., "3/3 agents", "Ops + Newcomer">
**Classification:** <Doc Bug | Ambiguity | Assumed Knowledge | Environment Gap | Software Bug>
**Doc location:** <section/step in the tested document>
**Evidence:** <what happened vs what the docs say — include actual error output>
**Impact:** <who gets stuck, on what step, and what they see>
**Suggested fix:** <specific edit to the document — quote the current text and proposed replacement>

(repeat for each finding, grouped by severity: CRITICAL, HIGH, MEDIUM, LOW)

## False Positives

### FP1. <Title>
**Flagged by:** <which agent>
**Why invalid:** <brief explanation with evidence>

## Environment Limitations
- <hardware absent, WebGL unavailable, etc. — expected, not bugs>

## Execution Log Summary

| Step | Description | Status | Duration | Notes |
|------|-------------|--------|----------|-------|
| ... | ... | PASS/FAIL/SKIP | Xm | ... |

## Steps Skipped (<mode> mode)
- <what was skipped and why — bind-mounted data, hardware absent, etc.>

## Screenshots
- [01-description.png](<date>-screenshots/01-description.png) — <what it shows>
- ...
(or "Playwright unavailable — HTTP verified via curl" if no screenshots)

## Resource Usage

| Checkpoint | RAM Used | RAM Free | Status |
|-----------|----------|----------|--------|
| Pre-test host | X GB | X GB | Baseline |
| After container launch | X GB | X GB | ... |
| Peak (during build/start) | X GB | X GB | ... |
| After cleanup | X GB | X GB | Recovered |

## Methodology
- **Structural analysis:** Checked N commands, N URLs, N package names, N env vars
- **Execution:** Experienced Ops agent ran full install in [distro] container
- **Review:** Junior Dev + Literal Newcomer analyzed execution log in parallel
- **Consolidation:** Cross-referenced N total findings from 3 agents, deduplicated to M unique
```

### 7b. Verdict Criteria

- **PASS** — All documented steps succeed. No critical or high findings. Minor issues only.
- **CONDITIONAL PASS** — Core functionality works. Critical/high findings exist but have clear fixes. A user could succeed with some difficulty.
- **FAIL** — Documented steps do not produce a working result. Blocking issues with no workaround.

### 7c. Git Commit

```bash
# Commit the report (not screenshots)
git add docs/validation/<date>-<mode>-report.md

# Add screenshot directory to gitignore if not already there
if ! grep -q 'docs/validation/.*-screenshots/' .gitignore 2>/dev/null; then
  echo 'docs/validation/*-screenshots/' >> .gitignore
  git add .gitignore
fi

git commit -m "docs(validation): <date> <mode> — N findings (N critical, N high)"
```

---

## Phase 8: Cleanup & Safety Verification

### 8a. Offer Container Preservation

If there are CRITICAL or HIGH findings, ask before deleting:

> "Validation complete with N critical/high findings. The container `validation-test` is still running at [IP]. Want to keep it for manual investigation, or should I clean it up?"

If the user says keep: report the container IP, access method (`lxc exec validation-test -- bash`), and exit. Otherwise, proceed with cleanup.

If there are no critical/high findings, proceed directly to cleanup.

### 8b. Container Cleanup

```bash
lxc delete validation-test --force
rm -f /tmp/validation-code.tar.gz
```

### 8c. Post-Cleanup Verification

```bash
lxc list                              # no validation containers remain
ls /tmp/validation-* 2>/dev/null      # no temp files remain
free -m                               # RAM recovered
df -BG /                              # disk recovered
```

Report resource recovery:
> "Cleanup complete. Recovered X GB RAM, X GB disk."

### 8d. Host Process Verification

Compare current state against the snapshots taken in Phase 2a:

```bash
docker ps --format '{{.Names}}\t{{.Status}}' 2>/dev/null
ss -tlnp | grep -E ':(80|443|[0-9]{4})\b' 2>/dev/null
```

If the output differs from the Phase 2 snapshot, report the anomaly:
> "WARNING: Host state changed during validation. Before: [snapshot]. After: [current]. This should not happen — please investigate."

If identical:
> "Host processes verified unchanged."

### 8e. Final Status

> "Validation complete. Report: `docs/validation/<date>-<mode>-report.md`. Screenshots: `docs/validation/<date>-screenshots/`. **N findings (N critical, N high).** Container cleaned up, host processes verified unchanged."
