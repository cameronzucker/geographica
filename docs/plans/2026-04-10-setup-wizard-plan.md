# Setup Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a browser-based setup wizard that replaces manual README steps 2-12 with a guided 5-step flow: `sudo ./bootstrap.sh` then `./setup`.

**Architecture:** Two entry points: `bootstrap.sh` (sudo, system prereqs) and `setup` (user, launches FastAPI wizard on localhost:8099). The wizard is a single-page app served by FastAPI with WebSocket progress streaming. Five steps: Network config, Region/data selection, Credentials, Download with progress, Launch + verify. The wizard generates `.env`, downloads data, builds Docker images, launches the stack, and exits.

**Tech Stack:** Python/FastAPI/uvicorn (backend), Vanilla HTML/JS/CSS + MapLibre GL JS from CDN (frontend), WebSocket (progress streaming), asyncio subprocess (command execution)

**Spec:** `docs/superpowers/specs/2026-04-10-setup-wizard-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `bootstrap.sh` | System prerequisites (sudo): apt install, docker group, data dir |
| Create | `setup` | Thin wrapper: venv, pip install, launch wizard |
| Create | `setup/__init__.py` | Package marker |
| Create | `setup/main.py` | FastAPI app: API routes, WebSocket, CSRF, subprocess runner |
| Create | `setup/config.py` | System detection (IP, RAM, disk, storage), .env generation, RAM profiles |
| Create | `setup/runner.py` | Subprocess executor with WebSocket streaming, checkpoint management |
| Create | `setup/requirements.txt` | fastapi, uvicorn, httpx |
| Create | `setup/static/index.html` | Single-page wizard app |
| Create | `setup/static/setup.js` | Wizard logic, WebSocket client, map picker |
| Create | `setup/static/setup.css` | Dark-mode-aware styles |
| Create | `tests/test_setup_config.py` | Unit tests for config detection, .env generation, bbox validation |
| Create | `tests/test_setup_runner.py` | Unit tests for checkpoint management, command argument building |
| Modify | `.gitignore` | Un-ignore frontend/vendor JS/CSS files |
| Modify | `README.md` | Add Quick Start section pointing to bootstrap.sh + setup |

---

## Task 1: Commit Vendor JS Files + Shell Scripts

BEFORE starting work:
1. Read docs/pitfalls/implementation-pitfalls.md

**Files:**
- Modify: `.gitignore` (remove vendor JS/CSS ignore rules)
- Create: `bootstrap.sh`
- Create: `setup` (wrapper script)
- Create: `setup/__init__.py`
- Create: `setup/requirements.txt`

- [ ] **Step 1: Un-ignore and commit vendor JS files**

Edit `.gitignore` — remove these two lines:
```
frontend/vendor/*.js
frontend/vendor/*.css
```

Then force-add the existing vendor files:
```bash
git add -f frontend/vendor/maplibre-gl.js frontend/vendor/maplibre-gl.css \
  frontend/vendor/togeojson.js frontend/vendor/jszip.min.js \
  frontend/vendor/dompurify.min.js
git add .gitignore
```

- [ ] **Step 2: Create bootstrap.sh**

Create `bootstrap.sh` at the repo root. Make executable (`chmod +x bootstrap.sh`).

The script must:
1. Check running as root (`$EUID -ne 0` -> exit)
2. Detect actual user via `$SUDO_USER`
3. Check repo dir is NOT world-writable (security — `stat -c %a`, refuse if last digit >= 6)
4. `apt update && apt install -y` all prerequisites: docker.io, docker-compose, python3, python3-venv, python3-pip, gdal-bin, osmium-tool, gpsd, gpsd-clients, git, wget, curl, unzip
5. `usermod -aG docker $ACTUAL_USER`
6. `systemctl start docker && systemctl enable docker`
7. `mkdir -p /srv/geographica/data/{pbf,nominatim,valhalla}`
8. `chown -R $ACTUAL_USER:$ACTUAL_USER /srv/geographica`
9. Create symlink: `ln -sf /srv/geographica/data $REPO_DIR/data`
10. Print completion message with `./setup` instructions and SSH tunnel guidance

Use the exact script from the spec (lines 249-308) as the base, adding the world-writable check after the root check.

- [ ] **Step 3: Create setup wrapper script**

Create `setup` at the repo root. Make executable (`chmod +x setup`).

The script must:
1. `cd` to its own directory
2. Check Docker is accessible (`docker info > /dev/null 2>&1`) — exit with helpful error if not
3. Create venv at `setup/.venv` (NOT `.venv` — separate from project venv)
4. `source setup/.venv/bin/activate`
5. `pip install -q -r setup/requirements.txt`
6. Print URL and SSH tunnel guidance
7. `python3 -m uvicorn setup.main:app --host 127.0.0.1 --port 8099`

- [ ] **Step 4: Create setup package files**

Create empty `setup/__init__.py`.

Create `setup/requirements.txt`:
```
fastapi>=0.115.0
uvicorn>=0.32.0
httpx>=0.27.0
```

- [ ] **Step 5: Commit**

```bash
git add bootstrap.sh setup setup/__init__.py setup/requirements.txt \
  frontend/vendor/ .gitignore
git commit -m "feat(setup): add bootstrap.sh, setup wrapper, commit vendor JS files"
```

---

## Task 2: Backend — System Detection and Config Generation

BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/ (or invoke /test-driven-development)
2. Read docs/pitfalls/testing-pitfalls.md

Follow TDD: write failing test -> implement fix -> verify green.

**Files:**
- Create: `setup/config.py`
- Create: `tests/test_setup_config.py`

`setup/config.py` provides:

**Constants:**
- `REGION_PRESETS` — dict mapping preset names to `{"label", "bbox", "states", "geofabrik"}`. Must include: western_us, eastern_us, full_us, arizona, california, nevada, europe. All bboxes must pass `validate_bbox()`.
- `_RAM_PROFILE_16GB` and `_RAM_PROFILE_8GB` — dicts with keys: `nominatim_memory`, `postgres_shared_buffers`, `postgres_maintenance_work_mem`, `postgres_effective_cache_size`, `valhalla_memory`, `valhalla_threads`, `tileserver_memory`, `stt_memory`, `pipeline_memory`, `pipeline_gdal_cache`, `imagery_concurrency_naip`, `imagery_concurrency_sentinel`, `imagery_concurrency_direct`, `m2m_batch_size`, `planetiler_heap`. Values from the spec's RAM profile table (lines 98-111).

**Functions:**
- `validate_bbox(bbox_str: str) -> bool` — parse 4 floats, validate ranges (-180..180 lon, -90..90 lat), validate west < east, south < north. Reject non-numeric input.
- `get_ram_profile(ram_mb: int) -> dict` — return 16GB profile if ram >= 12000 MB, else 8GB profile.
- `detect_host_ip() -> str` — use `ip route get 1`, extract src IP, exclude 172.17.x (docker) and 127.0.0.1.
- `detect_ram_mb() -> int` — read `/proc/meminfo` MemTotal.
- `detect_storage() -> list[dict]` — parse `/proc/mounts`, filter skip_fs, return `[{"device", "path", "total_gb", "free_gb", "fstype"}]` sorted by free_gb desc.
- `generate_env(host_ip, tls_mode, ram_profile, bbox, data_path) -> str` — returns .env file content string.

**Tests must include:**
- Bbox: valid western US, valid AZ, invalid lon > 180, invalid lat > 90, west > east, south > north, non-numeric, wrong format (2 values), injection attempt (semicolon)
- RAM profiles: 16GB values, 8GB values, 12GB -> 16GB profile, 6GB -> 8GB profile
- Env generation: verify HOST_IP, TLS_MODE, POSTGRES_SHARED_BUFFERS appear in output for both profiles
- Region presets: all presets have valid bbox
- Host IP: returns string, not localhost, not docker bridge
- RAM detection: returns positive int
- Storage detection: returns list with required fields

- [ ] **Step 1: Write all tests**
- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement config.py**
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

```bash
git add setup/config.py tests/test_setup_config.py
git commit -m "feat(setup): system detection, config generation, bbox validation"
```

BEFORE marking this task complete:
1. Review tests against docs/pitfalls/testing-pitfalls.md
2. Verify: injection test, boundary values, both RAM profiles covered
3. Run tests, confirm green

---

## Task 3: Backend — Subprocess Runner with Checkpoint Management

BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/ (or invoke /test-driven-development)
2. Read docs/pitfalls/testing-pitfalls.md

Follow TDD: write failing test -> implement fix -> verify green.

**Files:**
- Create: `setup/runner.py`
- Create: `tests/test_setup_runner.py`

**WARNING:** Do NOT use `shell=True`. Always `create_subprocess_exec` with argument lists.
**WARNING:** Force `PYTHONUNBUFFERED=1` in subprocess environment.
**WARNING:** Drain both stdout and stderr concurrently via separate asyncio tasks to prevent deadlock.

`setup/runner.py` provides:

**Checkpoint class:**
- `__init__(path: str)` — load existing checkpoint or create empty
- `is_completed(step: str) -> bool`
- `mark_completed(step: str)` — persist to JSON file
- `get_completed() -> list[str]`
- `reset()` — clear all, delete file

**Command builders (return `list[str]`, never shell strings):**
- `geofabrik_url(state_slug) -> str` — `https://download.geofabrik.de/north-america/us/{slug}-latest.osm.pbf`
- `planetiler_cmd(pbf_path, output_path, heap) -> list[str]` — docker run command
- `poi_build_cmd(bbox, states, output) -> list[str]`
- `osm_pois_cmd(pbf_path, output, bbox) -> list[str]`
- `elevation_cmd(bbox, output) -> list[str]`

**Async executor:**
- `run_command(args, cwd, on_output, env_extra) -> int` — spawn subprocess, drain both pipes concurrently (4096-byte chunks, not line-by-line), call `on_output(source, chunk)`, return exit code. Track PIDs in `_active_processes` list.
- `shutdown_children()` — SIGTERM to all active children.

**Tests must include:**
- Checkpoint: new has no completed, mark completed, persistence (write then re-read), reset, get_all
- Command builders: geofabrik URL format, hyphenated state, planetiler args contain --force and heap, poi_build args contain --bbox

- [ ] **Step 1: Write all tests**
- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement runner.py**
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

```bash
git add setup/runner.py tests/test_setup_runner.py
git commit -m "feat(setup): subprocess runner with checkpoint management"
```

BEFORE marking this task complete:
1. Review tests against docs/pitfalls/testing-pitfalls.md
2. Verify: checkpoint persistence, command arg safety
3. Run tests, confirm green

---

After Tasks 2 and 3:
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues. Then
update your private journal and continue onto the next tasks.

---

## Task 4: Backend — FastAPI App with CSRF and API Routes

BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/ (or invoke /test-driven-development)
2. Read docs/pitfalls/testing-pitfalls.md
3. Read `setup/config.py` and `setup/runner.py` (created in Tasks 2-3) fully

Follow TDD: write failing test -> implement fix -> verify green.

**Files:**
- Create: `setup/main.py`
- Create: `tests/test_setup_main.py`

**WARNING — SECURITY:** Generate CSRF token at startup via `secrets.token_hex(32)`. Embed in HTML via template. Validate `X-CSRF-Token` header on ALL POST endpoints. Set CORS `Access-Control-Allow-Origin` to reject non-localhost origins.

**WARNING:** Credential output path is HARDCODED to `/srv/geographica/data/credentials.json`. The API endpoint that saves credentials must NOT accept a path parameter from the client.

**WARNING — pitfall #9:** This is a separate app from the main frontend. Keep fully self-contained in `setup/`.

`setup/main.py` implements:

**Startup:**
- Generate CSRF token: `secrets.token_hex(32)`
- CORS middleware: allow origin `http://localhost:8099` only
- CSRF middleware: check `X-CSRF-Token` header on POST/PUT/DELETE requests
- Mount `setup/static/` as static files at `/static`
- Inactivity timer: 30 minutes. Reset on any HTTP request, WebSocket message, or subprocess activity. Auto-shutdown via `asyncio.get_event_loop().call_later()`.
- Register SIGTERM handler calling `runner.shutdown_children()`

**API Routes:**
- `GET /` — return `index.html` with CSRF token injected into a `<meta>` tag
- `GET /api/system` — return JSON: `{host_ip, ram_mb, ram_profile, storage: [...], existing_env: bool}`
- `GET /api/presets` — return `REGION_PRESETS`
- `POST /api/validate-bbox` — body `{bbox: str}`, return `{valid: bool}`
- `POST /api/config` — body `{host_ip, tls_mode, ram_profile_name, bbox, data_path, layers: {...}}`, writes `.env`, returns `{ok: true}`
- `POST /api/credentials` — body `{m2m_username, m2m_token, copernicus_client_id, copernicus_client_secret}`, writes to HARDCODED path, returns `{ok: true}`
- `POST /api/tls/generate` — runs `scripts/generate_tls.sh` via `runner.run_command()`, returns output
- `POST /api/tls/scan` — scans `/etc/letsencrypt/live/*/`, `/srv/geographica/tls/`, returns found cert files (CN, issuer, expiry). Does NOT read private key contents.
- `WebSocket /ws/progress` — on connect: send ring buffer state. Then stream progress events as JSON: `{step, substep, progress_pct, output, source}`. Maintain list of connected clients.
- `POST /api/start` — body `{config}`, starts download/build sequence in background task. Uses `Checkpoint`. Runs substeps sequentially via `runner.run_command()`. Streams progress to all connected WebSockets. Checks disk space every 60 seconds during downloads (warn <10 GB, abort <5 GB).
- `POST /api/launch` — generates `docker-compose.wizard.yml` (relaxed Nominatim dep), runs `docker compose -f docker-compose.yml -f docker-compose.wizard.yml up -d`
- `GET /api/health` — runs `docker compose ps --format json`, returns parsed service statuses
- `GET /api/status` — returns current progress state (step, substep, pct, recent log lines) for WebSocket reconnect

**Tests (in `tests/test_setup_main.py`):**
- `GET /api/system` returns valid JSON with required fields
- `POST /api/validate-bbox` with valid bbox returns `{valid: true}`
- `POST /api/validate-bbox` with invalid bbox returns `{valid: false}`
- `POST /api/config` without CSRF token returns 403
- `POST /api/config` with CSRF token succeeds
- `GET /api/presets` returns region presets
- `GET /api/status` returns progress state

- [ ] **Step 1: Write tests**
- [ ] **Step 2: Run tests, verify fail**
- [ ] **Step 3: Implement main.py**
- [ ] **Step 4: Run tests, verify pass**
- [ ] **Step 5: Commit**

```bash
git add setup/main.py tests/test_setup_main.py
git commit -m "feat(setup): FastAPI wizard app with CSRF, WebSocket, API routes"
```

BEFORE marking this task complete:
1. Review tests against docs/pitfalls/testing-pitfalls.md
2. Verify: CSRF validation tested, credential path not client-controlled
3. Run tests, confirm green

---

## Task 5: Frontend — Wizard HTML/JS/CSS

BEFORE starting work:
1. Read docs/pitfalls/implementation-pitfalls.md — pitfall #9: separate from app.js
2. Read the mockup at `.superpowers/brainstorm/794363-1775786564/content/region-wizard-v3.html` for dark mode CSS reference

**Files:**
- Create: `setup/static/index.html`
- Create: `setup/static/setup.js`
- Create: `setup/static/setup.css`

This task creates the entire wizard frontend as a single-page app.

**index.html must include:**
- `<meta name="csrf-token" content="{{ csrf_token }}">` (FastAPI injects this)
- MapLibre GL JS from CDN: `https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js` and CSS
- Link to `setup.css` and `setup.js`
- 5 step containers (divs), only one visible at a time
- Step navigation buttons (Back, Next, Skip)

**setup.css must include:**
- CSS custom properties for light and dark themes
- `@media (prefers-color-scheme: dark)` with full dark palette
- `.container` with `max-width: 800px; margin: 0 auto;`
- Layer card styles with color coding: `.layer.green`, `.layer.blue`, `.layer.purple`, `.layer.orange`
- Wizard tab bar styles
- Progress bar styles
- Health dashboard styles (service status dots: red/yellow/green)
- Skip-all warning box (amber background)

**setup.js must include:**
- Read CSRF token from meta tag, send as `X-CSRF-Token` on all fetch POST
- Step navigation state machine (currentStep, showStep, nextStep, prevStep)
- Step 1: `fetch('/api/system')` on load, populate IP/RAM/storage/TLS fields
- Step 2: Initialize MapLibre map with OSM raster tiles, draggable bbox rectangle, preset dropdown that updates bbox, layer cards with source toggles, zoom slider, running totals (calculate from bbox area)
- Step 3: Credential form with test-connection buttons (POST to M2M/Copernicus test endpoints)
- Step 4: WebSocket connect to `ws://localhost:8099/ws/progress`, render progress bars per substep, collapsible log viewer, retry/skip buttons on error
- Step 5: Poll `GET /api/health` every 5 seconds, render service status table, show completion message with link to main app
- WebSocket reconnect: on close, wait 2 seconds, reconnect, fetch `GET /api/status` for current state

**Do NOT:**
- Import anything from `frontend/app.js`
- Add npm dependencies or build tools
- Use any CSS framework

- [ ] **Step 1: Create index.html with step containers and CDN imports**
- [ ] **Step 2: Create setup.css with dark mode support (use mockup as reference)**
- [ ] **Step 3: Create setup.js with all wizard logic**
- [ ] **Step 4: Test: run `./setup` and verify page loads at http://localhost:8099**
- [ ] **Step 5: Commit**

```bash
git add setup/static/
git commit -m "feat(setup): wizard frontend — 5-step SPA with dark mode and map picker"
```

---

After Tasks 4 and 5:
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues. Then
update your private journal and continue onto the next tasks.

---

## Task 6: Integration — README Update and Smoke Test

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add Quick Start section to README**

Add at the beginning of the Setup guide section (before "### Prerequisites"), a new subsection:

```markdown
## Quick Start

For a guided setup experience, use the setup wizard:

\`\`\`bash
git clone https://github.com/cdzucker/geographica.git
cd geographica
sudo ./bootstrap.sh    # Install system prerequisites
./setup                # Launch browser-based setup wizard
\`\`\`

Then open http://localhost:8099 in your browser. The wizard will guide you through
region selection, data downloads, and stack deployment.

> **Headless access:** If accessing the Pi remotely via SSH, use a VNC session
> or SSH tunnel: `ssh -L 8099:localhost:8099 user@your-pi-ip`, then open
> http://localhost:8099 locally.

The manual setup steps below are still available for advanced users or automation.

---
```

- [ ] **Step 2: Run full test suite**

```bash
cd /home/administrator/Code/geographica && python -m pytest tests/ -v
```

Expected: ALL PASS

- [ ] **Step 3: Smoke test the wizard**

```bash
./setup
```

Open http://localhost:8099 and verify:
- Page loads, dark mode works if OS is in dark mode
- Step 1 shows detected system info
- Step navigation works (Next/Back)
- Step 2 shows map (requires internet for CDN tiles)

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add Quick Start section pointing to setup wizard"
```

You MUST carefully review the complete implementation from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues.
