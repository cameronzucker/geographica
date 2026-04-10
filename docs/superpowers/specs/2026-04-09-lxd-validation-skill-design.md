# LXD Validation Skill — Generalized Design

**Date:** 2026-04-09
**Status:** Draft (pending review)
**Purpose:** Generalized, project-agnostic Claude Code skill for testing README/install documentation in isolated LXD containers. Designed for the superpowers plugin — usable across any project.

## Problem

Documentation rot is invisible until someone follows the instructions and fails. README setup guides accumulate stale package names, dead URLs, missing steps, and assumed knowledge as projects evolve. Manual validation is tedious and unrepeatable. AI agents can follow instructions literally, but a single agent with a single perspective misses issues that affect users with different skill levels.

We need a repeatable, multi-perspective validation process that:
- Tests docs from multiple skill levels (expert, junior, newcomer)
- Uses multiple models to cross-reference findings
- Runs in complete isolation (never touches host processes)
- Produces human-reviewable evidence (reports + screenshots)
- Works alongside running production stacks without interference

## Design Decisions

1. **Dispatch-and-consolidate pattern** (like bug-hunt-cycle) — a coordinator handles intake, setup, and consolidation; parallel agents provide multi-perspective coverage.
2. **Three test modes** — structural (no container, static analysis), quick (bind-mounted data), full (from-scratch download). Auto-selected by available resources.
3. **Agent-first** — the skill is executed by Claude Code agents. Output reports are human-reviewable.
4. **Never interfere with host** — the skill works within available headroom. It never stops host services or processes. If insufficient resources, it degrades to a lighter mode or stops and asks.
5. **Conservative OOM safety** — container memory = available RAM minus 2GB safety margin. Halt immediately if free RAM drops below 1.5GB.
6. **Single container, sequential execution + parallel analysis** — Agent 1 executes the full install; Agents 2-3 review the execution log through their personas in parallel.
7. **Commit reports, not screenshots** — markdown reports are committed to git. Screenshots stay on disk for human review, gitignored.

## Skill Metadata

```yaml
name: lxd-validation
description: >
  Test README/install docs in an isolated LXD container — dispatches multi-model,
  multi-persona agents to validate from different skill levels, then consolidates
  into a cross-referenced report with Playwright screenshots.
argument-hint: "<scope, e.g. 'README.md', 'docs/install.md', 'full stack'>"
```

Invocation: `/lxd-validation README.md` or `/lxd-validation docs/setup-guide.md`

`$ARGUMENTS` identifies the document(s) to validate. If omitted, the skill searches for README.md, INSTALL.md, docs/setup.md, or similar and asks the user to confirm.

Single SKILL.md file — no sub-files or helper scripts. Uses standard tools (Bash, Read, Agent, Playwright MCP).

---

## Phase 1: Intake & Project Analysis

Runs in the coordinator agent.

### 1a. Document Discovery

- Read `$ARGUMENTS` (or scan for README.md, INSTALL.md, SETUP.md, docs/install*, docs/setup*)
- Identify all instruction blocks (fenced code blocks, numbered steps, bullet commands)
- Build an ordered list of every command the document tells the user to execute

### 1b. Project Classification

Classify the project into categories that determine which validation phases apply:

| Category | Detected by | Enables |
|----------|------------|---------|
| Docker/Compose stack | `docker-compose.yml`, `Dockerfile`, `docker compose` commands | Container-in-container testing, service health checks |
| Web frontend | Port bindings on 80/443/8080/etc, browser references, HTML/JS | Playwright screenshots |
| CLI tool | `pip install`, `npm install -g`, `cargo install`, binary in PATH | Command execution + output validation |
| Library | `import`, test suites, no service startup | Build + test execution |
| Bare-metal services | `systemctl`, config files in /etc, no Docker | Service start + port checks |
| Data pipeline | Scripts that download/process/output files | File existence + size checks |

A project can belong to multiple categories simultaneously.

### 1c. Intake Questions

The skill presents the classification and asks targeted questions based on detected categories. Only relevant questions are asked.

1. "I've identified this as a [categories]. Is that correct, or am I missing something?"
2. "The docs reference these external dependencies/downloads: [list]. For quick mode, do you have pre-built data I should bind-mount? Where?"
3. "I see these hardware-specific references: [list]. Which should I skip vs. mock?"
4. "What does success look like beyond 'it starts'? Any specific functionality to verify?"
5. "Target audience for the docs — who is the intended reader?" (informs persona selection)

6. "The docs target [distro detected from context / unclear]. Should I test in Debian 13, Ubuntu 24.04, Fedora 41, or something else?" (determines container base image)

A simple CLI tool might only get questions 1 and 4. A Docker stack on Ubuntu gets 1-5. Question 6 is asked when the docs reference distro-specific commands or packages.

---

## Phase 2: Resource Assessment & Mode Selection

### 2a. Host Resource Survey

```bash
# Available RAM
free -m | awk '/^Mem:/{print $7}'

# Disk free on likely LXD storage locations
df -BG / /srv /var/lib/lxd 2>/dev/null

# What's consuming resources
docker ps --format '{{.Names}}\t{{.Status}}' 2>/dev/null
lxc list --format csv 2>/dev/null
```

### 2b. Mode Selection Matrix

| Available RAM | Available Disk | Selected Mode |
|--------------|---------------|---------------|
| < 2 GB | Any | Structural only |
| 2-4 GB | < 10 GB | Structural only |
| 2-4 GB | 10+ GB | Structural + Quick (reduced memory limit) |
| 4-8 GB | 10+ GB | Structural + Quick |
| 8+ GB | 30+ GB | Structural + Quick + Full |
| 8+ GB | < 30 GB | Structural + Quick |

The skill selects the heaviest mode that fits, then presents the decision:

> "Host has X GB RAM free and Y GB disk. Running containers: [list]. I'll run **[mode]** with a Z GB container memory limit (leaving 2 GB safety margin). To run a heavier mode, I'd need you to stop some services — but I won't do that without your approval."

### 2c. OOM Safety Invariant (HARD RULE)

- Container memory limit = `available_ram - 2GB` (floor 1GB; below 1GB → abort)
- Monitor `free -m` before dispatching each parallel agent
- If available RAM drops below 1.5GB at any point: **stop immediately**, clean up container, report what happened
- **Never** stop or modify host processes to free resources
- User can override the safety margin with explicit instruction, but the default is conservative

---

## Phase 3: Structural Analysis (Always Runs)

Runs before any container is created. Cheap, fast, catches many issues without resource cost.

### 3a. Command Extraction

Parse the target document. For each shell command, record:
- Command text
- Section/step it appears in
- Prerequisites implied by context

### 3b. Static Checks

| Check | How | Catches |
|-------|-----|---------|
| Package name validation | `apt-cache show`, `dnf info`, `brew info` on host or known databases | Wrong package names, distro-specific naming |
| URL reachability | `curl --head --max-time 10` for every URL | Dead links, placeholder URLs, moved downloads |
| File path references | Check if referenced paths exist in the repo | Missing or moved files |
| Command syntax | `bash -n` on script blocks, shellcheck if available | Syntax errors, unclosed quotes |
| Ordering analysis | Walk the command list — does each step's dependencies exist in prior steps? | Missing steps, out-of-order instructions |
| Implicit dependencies | Scan for tools not in prerequisites (`wget`, `curl`, `unzip`, `git`, `make`) | Undocumented tool requirements |
| Environment variables | Find all `$VAR` / `${VAR}` — is each set by a prior step or documented? | Undefined variables, unclear configuration |

### 3c. Ambiguity Scan

Read the document as prose looking for:
- Vague instructions: "set this to your IP address" (which IP? which interface?)
- Assumed knowledge: "configure the firewall" (how? which ports?)
- Conditional paths without clear guidance
- Placeholder values that look like real values (ports, IPs, domains)

### 3d. Structural Report

Write preliminary findings. These feed into parallel agent dispatch as context. If structural-only mode was selected (insufficient resources), this becomes the final output and the skill skips to Phase 7.

---

## Phase 4: Container Setup

Runs in the coordinator. Creates a single LXD container for the test agents to use.

### 4a. LXD Pre-flight

```bash
which lxc && lxc list
lxc storage list
```

If LXD isn't installed/initialized: stop and provide setup instructions. Don't auto-install. Detect storage pool misconfiguration (e.g., undersized loop file) and warn.

### 4b. Container Creation

```bash
lxc launch images:debian/13 validation-test \
  -c security.nesting=true \
  -c security.syscalls.intercept.mknod=true \
  -c security.syscalls.intercept.setxattr=true \
  -c limits.memory=${CALCULATED_LIMIT}
```

- **Base image:** `images:debian/13` by default. During intake, the skill asks if the project targets a different distro and substitutes accordingly (e.g., `images:ubuntu/24.04`, `images:fedora/41`).
- **Container name:** `validation-test`. The skill checks for and deletes any existing container with this name (after user confirmation) before creating.
- **Nesting flags:** Always set. Required for Docker-in-LXC on cgroup v2 kernels. If Docker still fails inside, add `raw.lxc: lxc.cgroup.relative = 0` as fallback.
- **Network:** Default LXD bridge. Verify connectivity immediately after launch:

```bash
lxc exec validation-test -- ping -c1 8.8.8.8
lxc exec validation-test -- apt update
```

Abort if the container can't reach the internet.

### 4c. Code Injection

```bash
# On host: archive the repo (respects .gitignore)
git archive HEAD --format=tar.gz -o /tmp/validation-code.tar.gz

# Push into container
lxc file push /tmp/validation-code.tar.gz validation-test/root/
lxc exec validation-test -- bash -c \
  "mkdir -p /root/project && tar -xzf /root/validation-code.tar.gz -C /root/project"
```

Note in the report that any `git clone` step was replaced with a tarball copy. Test the clone URL's reachability in the structural phase.

### 4d. Quick Mode Data Mounts

When the user identified pre-built data during intake:

```bash
lxc config device add validation-test hostdata disk \
  source=<user-specified-path> path=<target-path> readonly=true
```

For services needing write access, create writable overlays (copy from read-only mount). Document each mount and overlay in the report.

### 4e. Hardware Abstraction

For hardware references identified during intake (GPS, GPU, NPU, serial ports), create compose overrides or config patches to remove/mock hardware dependencies. Document each in the report as an expected environment limitation.

---

## Phase 5: Parallel Agent Dispatch

The core of the skill.

### 5a. Persona Definitions

| Persona | Model hint | Brief | Catches |
|---------|-----------|-------|---------|
| **Experienced Ops** | `opus` | Senior sysadmin. Follows precisely but notices underspecified, fragile, or non-idiomatic patterns. Tests edge cases proactively. | Missing error handling, security issues, non-portable assumptions, undocumented prerequisites |
| **Junior Developer** | `sonnet` | First job, comfortable with code but unfamiliar with Linux admin, Docker, networking. Follows literally. Picks the wrong interpretation when ambiguous. | Ambiguous instructions, assumed knowledge, missing context, unclear terminology |
| **Literal Newcomer** | `haiku` | Never used this software. Only does exactly what the document says. Doesn't infer, doesn't troubleshoot. Records errors and moves on. | Missing steps, implicit assumptions, gaps between steps, wrong command order |

Customizable during intake (e.g., "our audience is experienced Ruby developers" shifts the junior persona). Reduce to 2 agents if resources are tight.

### 5b. Sequential Execution, Parallel Analysis

The agents share one container. They cannot run simultaneously inside it.

1. **Agent 1 (Experienced Ops)** executes the full README in the container. Captures every command's output, takes Playwright screenshots at milestones. This agent is the "builder."
2. The coordinator notes the installed state.
3. **Agents 2 and 3 run in parallel** doing **analysis, not execution.** They receive Agent 1's full execution log (commands, outputs, errors, screenshots) plus the structural analysis from Phase 3. They review through their persona lens. They can run additional probing commands in the container if needed but don't re-run the install.

This means:
- One full execution pass (saves time and resources)
- All three personas produce independent findings
- Junior and newcomer agents flag things the ops agent breezed past
- Parallel analysis — agents 2 and 3 don't block each other

### 5c. Agent Prompt Template

Each agent receives:
1. The target document text
2. Project classification from Phase 1
3. Structural findings from Phase 3
4. Their persona brief
5. Agent 1's execution log (for agents 2 and 3)
6. Container IP and access method (`lxc exec validation-test -- bash -lc "..."`)
7. Report output path: `docs/validation/<date>-<persona>.md`
8. Critical instruction: **"You are testing the DOCUMENTATION, not the software. A command that works but isn't in the docs is a finding. A step that requires knowledge the docs don't provide is a finding. Your job is to identify every gap between what the docs say and what a person matching your persona would actually experience."**

### 5d. Playwright Evidence Collection

Agent 1 captures screenshots at detected milestones:
- After each service health check passes
- When a web UI is first accessible
- After performing any documented user action (search, login, etc.)
- On any error page or unexpected state

Uses Playwright MCP (`browser_navigate` + `browser_take_screenshot`), with `browser_run_code` for cases needing `acceptInsecureCerts: true`. Screenshots go to `docs/validation/<date>-screenshots/`.

**Guard:** Before capturing, verify the URL uses the container IP, not the host — prevents false passes from accidentally testing the production stack.

**Playwright availability:** Screenshots are only attempted when the project is classified as "Web frontend" AND Playwright MCP tools are available in the agent's environment. If Playwright is unavailable, the agent substitutes `curl` output and documents the limitation. Non-web projects skip this entirely.

### 5e. Shell State in LXC

`lxc exec` runs each command as a separate process — environment variables and `cd` don't persist between calls. The agent uses `bash -lc` for commands needing shell context:

```bash
lxc exec validation-test -- bash -lc "cd /root/project && source .venv/bin/activate && python setup.py"
```

Alternatively, for projects with many sequential commands, the agent can write a script to `/root/run-step-N.sh` and execute it. Each approach is documented in the execution log.

---

## Phase 6: Consolidation & Cross-Referencing

Runs in the coordinator after all agents complete.

### 6a. Enumerate All Findings

Read all agent reports. Build master list. Every finding must be accounted for — nothing silently dropped. The coordinator doesn't decide what's "too minor."

### 6b. Classify Each Finding

| Classification | Meaning |
|---------------|---------|
| **Doc Bug** | Documentation is wrong, missing, or misleading |
| **Ambiguity** | Documentation could be interpreted multiple ways |
| **Assumed Knowledge** | Step requires knowledge target audience may not have |
| **Environment Gap** | Works on tested distro but may not on others |
| **Software Bug** | Software doesn't work as documented |
| **Environment Limitation** | Expected difference from real deployment — not a bug |
| **False Positive** | Finding is incorrect — explain why |

### 6c. Consensus Weighting

- **3/3 agents** — high confidence, almost certainly real
- **2/3 agents** — likely real, verify evidence
- **1/3 agents** — extra scrutiny. Could be persona-specific. Cross-reference against the target audience from intake.

### 6d. Severity Assignment

| Severity | Criteria |
|----------|----------|
| **CRITICAL** | Blocks the user entirely. Cannot proceed past this step. |
| **HIGH** | User can work around it but wastes significant time or gets a broken result. |
| **MEDIUM** | User may be confused or get a suboptimal result but can proceed. |
| **LOW** | Cosmetic or minor friction. |

### 6e. Deduplication

Group findings describing the same underlying issue. Preserve each agent's phrasing — different perspectives often reveal different facets of the needed fix.

---

## Phase 7: Report Generation

### 7a. Report Location

Default: `docs/validation/<date>-<mode>-report.md`. Screenshots: `docs/validation/<date>-screenshots/`. Respect project-level overrides (CLAUDE.md, etc.).

### 7b. Report Structure

```markdown
# Validation Report — <date> (<mode>)

**Document tested:** <path>
**Duration:** X minutes
**Container:** validation-test (<distro>, <arch>)
**Mode:** structural | quick | full
**Agents:** Experienced Ops (opus), Junior Dev (sonnet), Literal Newcomer (haiku)

## Executive Summary

X findings: N critical, N high, N medium, N low, N false positives, N env limitations.
[1-2 sentence verdict]

## Findings by Severity

### CRITICAL

#### F1. <Title>
**Consensus:** <which agents flagged it>
**Doc location:** <section/line in the tested document>
**Evidence:** <what happened vs what the docs say>
**Impact:** <who gets stuck and how>
**Suggested fix:** <specific edit to the document>

(repeat for HIGH, MEDIUM, LOW)

## False Positives

### FP1. <Title>
**Flagged by:** <which agent>
**Why invalid:** <explanation>

## Environment Limitations
- <expected differences, not bugs>

## Execution Log Summary

| Step | Description | Status | Duration | Notes |
|------|-------------|--------|----------|-------|

## Steps Skipped (<mode> mode)
- <what was skipped and why>

## Screenshots
- [filename.png](screenshots/filename.png) — <description>

## Resource Usage

| Checkpoint | RAM Used | RAM Free | Status |
|-----------|----------|----------|--------|

## Methodology
- Structural analysis: <summary>
- Execution: <Agent 1 persona> ran full install
- Review: <Agents 2-3 personas> analyzed execution log + probed container
- Consolidation: cross-referenced N findings from 3 agents
```

### 7c. Git Commit

```bash
git add docs/validation/<date>-<mode>-report.md
git commit -m "docs(validation): <date> <mode> — N findings (N critical, N high)"
```

Add `docs/validation/*-screenshots/` to `.gitignore` if not already present. Screenshots are NOT committed.

---

## Phase 8: Cleanup & Safety Verification

### 8a. Container Deletion

If findings exist that the user might want to investigate interactively, ask before deleting:

> "Validation complete. The container `validation-test` is still running. Want to keep it for manual investigation, or should I clean it up?"

If the user says keep: report the container IP and access method, then exit. Otherwise:

```bash
lxc delete validation-test --force
```

### 8b. Post-Cleanup Verification

```bash
lxc list                                          # no validation containers
ls /tmp/validation-*                              # no temp files
free -m                                           # RAM recovered
df -BG /                                          # disk recovered
```

Report resource recovery.

### 8c. Host Process Verification

```bash
docker ps --format '{{.Names}}\t{{.Status}}'
ss -tlnp | grep -E ':(80|443|8[0-9]{3})\b'
```

Compare against the snapshot taken during Phase 2. Report any anomalies — this should never happen, but if it does, the user needs to know.

### 8d. Final Status

> "Validation complete. Report: `docs/validation/<date>-<mode>-report.md`. Screenshots: `docs/validation/<date>-screenshots/`. X findings (N critical, N high). Container cleaned up, host processes verified unchanged."

---

## What This Tests

- Every documented command is syntactically correct and executable
- Every URL is reachable
- Every prerequisite package exists under the documented name
- Every script runs without errors
- Every service starts and passes health checks (if applicable)
- Web frontend loads and renders (if applicable)
- Documented user workflows function end-to-end
- Instructions are unambiguous and followable by the target audience
- No undocumented implicit dependencies

## What This Does NOT Test

- Hardware-specific integrations (GPS, GPU, NPU) — mocked or skipped
- Performance under load
- Multi-user scenarios
- Platform-specific TLS (Tailscale, ACME) — only self-signed
- Proprietary credentials or auth flows

## Known Environment Differences

These are inherent to container-based testing and are NOT findings:

1. Code copied via tarball, not `git clone` (unless repo is public)
2. Hardware devices mocked or absent
3. Self-signed TLS instead of production certs
4. WebGL may use software rasterization (no GPU in container)
5. Reduced bbox/dataset in full mode (smaller than production)
