# README Validation Harness

**Date:** 2026-04-09
**Status:** Approved

## Problem

As Geographica approaches release, the README setup instructions grow stale as features are added. There's no automated way to verify that a fresh user can follow the README from step 1 through a working deployment. Manual testing is tedious and error-prone. We need a repeatable validation process that an AI agent can execute in an isolated environment without affecting the running production stack.

## Design

An LXD-based test harness that creates a clean Debian container, then has an agent follow the README setup instructions step-by-step as if it were a first-time user with no project knowledge. The agent captures screenshots at key milestones and produces a structured pass/fail report.

### Two Modes

| Mode | Data strategy | Duration | When to use |
|------|--------------|----------|-------------|
| **Quick** | Bind-mount host's `/srv/geographica/data/` read-only | ~15 min | After README edits, frequent validation |
| **Full** | Download everything from scratch (small bbox) | Hours | Pre-release dress rehearsal |

### Host Prerequisites

One-time setup performed by the agent on first run:

1. Add current user to `lxd` group: `sudo usermod -aG lxd $USER`
2. Run `lxd init --minimal` (creates default storage pool + network bridge)
3. Verify with `lxc list`

The agent is authorized to run these commands. If permissions are needed, the user will approve interactively.

### LXC Container Configuration

- **Base image:** `images:debian/13` (Trixie arm64, matches Pi's OS)
- **Container name:** `geographica-test`
- **Nesting:** `security.nesting=true` (required for Docker-inside-LXC)
- **Network:** Default LXD bridge (`lxdbr0`) — container gets its own IP, routable from host
- **Storage:** Default LXD pool on existing SSD

**Quick mode only — bind-mount:**
```
lxc config device add geographica-test hostdata disk \
  source=/srv/geographica/data path=/srv/geographica/data readonly=true
```

### Agent Behavior

The agent operates as a first-time user with only basic Linux knowledge. It:

- Reads the README and follows instructions literally
- Does NOT use any project knowledge beyond what the README states
- Executes every command shown in the README
- Records the output of every command
- Notes any instruction that is ambiguous, missing context, or produces an unexpected result
- Does NOT fix issues — it reports them

**Quick mode deviations:** For steps 4-7 (data downloads), the agent verifies the bind-mounted files exist at the expected paths instead of downloading. It documents what was skipped.

**Full mode bbox:** Uses Arizona only (`"-114.8,31.3,-109.0,37.0"`) instead of the full 11-state Western US, to reduce download time and storage while still testing the complete pipeline.

### TLS Validation

The README documents three TLS modes. The agent tests **self-signed** mode:

1. Run `scripts/generate_tls.sh` as documented in the README
2. NGINX binds port 443 with the generated cert
3. Playwright connects with `--ignore-https-errors`

This validates the self-signed TLS path. Tailscale TLS cannot be tested in isolation (requires Tailscale auth + domain). The report notes this as "not tested — requires manual Tailscale setup."

HTTPS is required for STT (Web Audio API) and other browser APIs that need a secure context.

### Validation Screenshots

Captured via Playwright running on the host, connecting to the container's IP through the LXD bridge.

| # | Milestone | Modes | Filename |
|---|-----------|-------|----------|
| 01 | Stack healthy (`docker compose ps`) | Both | `01-stack-healthy.png` |
| 02 | Map loads (Positron default view) | Both | `02-map-loads.png` |
| 03 | Dark Matter style | Full | `03-dark-matter.png` |
| 04 | Hybrid imagery+roads style | Full | `04-hybrid-style.png` |
| 05 | Search results ("Phoenix") | Both | `05-search-results.png` |
| 06 | Spatial search ("gas stations in Flagstaff") | Full | `06-spatial-search.png` |
| 07 | Route rendered (Phoenix → Flagstaff) | Full | `07-route-rendered.png` |
| 08 | 3D terrain view | Full | `08-terrain-3d.png` |
| 09 | Public lands layer | Full | `09-public-lands.png` |
| 10 | Admin panel Dashboard | Full | `10-admin-dashboard.png` |
| 11 | Geocode verification (curl) | Both | `11-geocode-verify.png` |

Screenshots saved to `docs/validation/<date>-<mode>/`.

### Test Report Format

Output: `docs/validation/<date>-<mode>-report.md`

```markdown
# README Validation Report — <date> (<mode>)

**Duration:** X minutes
**Container:** geographica-test (Debian 13, arm64)
**Mode:** quick | full

## Results Summary

| Step | Description | Status | Duration | Notes |
|------|-------------|--------|----------|-------|
| Prerequisites | apt install, Docker setup | PASS | 2m | |
| 1. Clone | git clone | PASS | 0.5m | |
| ... | ... | ... | ... | |

## Steps Skipped (quick mode only)
- Step 4: OSM download — bind-mounted from host
- ...

## Ambiguities Found
- [any README instructions that were unclear or required interpretation]

## Errors Encountered
- [any commands that failed, with actual error output]

## Screenshots
![Stack healthy](01-stack-healthy.png)
...

## TLS Notes
- Self-signed TLS tested via generate_tls.sh
- Tailscale TLS not tested (requires manual auth)
- HTTPS-dependent features (STT) validated under self-signed cert

## Verdict
PASS / FAIL (with explanation)
```

### Container Lifecycle

1. **Create:** `lxc launch images:debian/13 geographica-test -c security.nesting=true`
2. **Run test:** Agent uses `lxc exec geographica-test -- <command>` to run README steps inside (no SSH needed)
3. **Screenshots:** Playwright on host hits container IP
4. **Report:** Written to `docs/validation/`
5. **Cleanup:** `lxc delete geographica-test --force` (or keep for debugging)

The container is disposable. Each test run starts fresh.

### What This Tests

- Every `apt install` package is correct
- Every `wget`/`curl` URL is reachable (full mode)
- Every script runs without errors
- Every Docker image builds successfully
- Every service starts and passes health checks
- The frontend loads and renders correctly
- Search, routing, and geocoding work end-to-end
- TLS (self-signed) works
- The README instructions are unambiguous and followable

### What This Does NOT Test

- Tailscale TLS (requires auth)
- GPS hardware integration (requires physical GPS hat)
- Hailo NPU acceleration (requires hardware)
- Performance under load
- Multi-user scenarios
