# Setup Process Bug Hunt — Consolidated Findings

**Date:** 2026-04-18
**Scope:** Geographica setup process end-to-end: `README.md`, `bootstrap.sh`,
`setup.sh`, `.env.example`, `setup/main.py`, `setup/config.py`, `setup/runner.py`,
`setup/static/*`, plus adjacent docker-compose, scripts, nginx entrypoint, and
keyring-agent files.
**Hunters:** Exploratory, Holistic, Multipass (opus, three independent methodologies).
**Starting context:** beta tester running setup right now, already blocked by
three bugs (wrong clone URL, unusable install-location dropdown, perceived
preflight timing issue). Hunters told to skip the three user-known regressions
and find every OTHER broken thing.

**Headline:** 48 unique confirmed bugs + 8 design decisions + 3 known-excluded
regressions. Of these, 10 are **critical** (deterministically break first-run
for any non-Cameron user on v1.1.0). The wizard has the shape of a working
product but the plumbing is wrong at nearly every layer-boundary.

---

## Confirmed Bugs

### Critical — first-run breaks deterministically on any non-dev machine

#### B1. TLS-mode vocabulary disagrees across four files — every non-`http` choice silently falls back to HTTP
**Consensus:** All 3 hunters.
**Location:**
- `setup/static/index.html:42-48` — UI offers `http | self-signed | existing | external`
- `setup/static/setup.js:157` — writes chosen string verbatim into `.env`
- `setup/config.py:334` — emits `TLS_MODE=<user choice>` unchanged
- `.env.example:7` — documents `http | tls-published | tls-standard`
- `nginx/entrypoint.sh:5,40,52` — only recognises `https` and `tailscale`
**Evidence:** I verified the nginx entrypoint. It runs `if [ "$TLS_MODE" = "https" ]`,
`elif [ "$TLS_MODE" = "tailscale" ]`, else copies `tls-include-empty.conf`. Any
value the wizard actually writes (`self-signed`, `existing`, `external`) falls
through to the empty-TLS branch, port 443 listens with no cert, no warning.
**Impact:** Every TLS option except "HTTP (no encryption)" is a phantom. The
completion-page "Open Geographica" link builds `https://<host>` for these modes
and points at a dead port. Browser Geolocation + STT also silently break.
**Blast radius:** Medium — fixing means picking one vocabulary and propagating
to all 4 files, plus wiring `/api/tls/generate` for the self-signed path (see B3).
**Fix approach:** Adopt `http | https | tailscale` as the canonical vocabulary.
Wizard maps UI labels ("Self-signed certificate" → `https`, "Existing certificate" →
`https`, "External proxy / Tailscale" → `tailscale`). Update `.env.example` too.

#### B2. Install-location chosen by the user never reaches Docker — `DATA_PATH` vs `DATA_HOST_PATH` / hardcoded `./data` symlink
**Consensus:** Multipass + holistic.
**Location:** `setup/config.py:336` writes `DATA_PATH=<choice>`; `docker-compose.yml:124`
reads `DATA_HOST_PATH` (not `DATA_PATH`); all service volumes use `./data` which
is a symlink `bootstrap.sh:70` created pointing at `/srv/geographica/data`.
**Evidence:** I verified `docker-compose.yml:124` reads `${DATA_HOST_PATH:-/srv/geographica/data}`.
The string `DATA_PATH` appears nowhere else in the repo's deployed-code paths.
Volumes are `./data:/data`, `./data:/srv/data`, `./data:/custom_files` — all
rely on the repo-relative symlink. The user's Step 1 choice is saved into `.env`
but the running stack reads from `/srv/geographica/data` regardless.
**Impact:** The one thing the user complained about — "can't define install
location" — isn't just a missing UI control. Even if a user types a valid path
in the (missing) custom-path input, the Docker stack ignores it and writes to
`/srv/geographica/data`. Disk-full checks and checkpoint persistence run against
the user's path; actual data lands elsewhere. Two-paths bug. The user's #2 complaint.
**Blast radius:** High — affects `DATA_HOST_PATH`, `SCRIPTS_HOST_PATH`, the
`./data` symlink semantics, and `bootstrap.sh` data-dir creation. The symlink
is the architectural contract that every service volume relies on; re-targeting
it (via `ln -sfn <user-choice> ./data`) is the least-disruptive fix.
**Fix approach:** Emit `DATA_HOST_PATH=<choice>` + `SCRIPTS_HOST_PATH=<repo>/scripts`
from `generate_env`. At `/api/launch`, re-target the `./data` symlink to the
user's chosen path before bringing up services. Separately, verify the chosen
path exists / create if missing via the existing `/api/create-directory`.

#### B3. `SCRIPTS_HOST_PATH` defaults to Cameron's home — breaks admin-panel pipelines for everyone else
**Consensus:** Exploratory + holistic.
**Location:** `docker-compose.yml:125`: `SCRIPTS_HOST_PATH: "${SCRIPTS_HOST_PATH:-/home/administrator/Code/geographica/scripts}"`.
**Evidence:** Verified at `docker-compose.yml:125`. The wizard's `generate_env`
never writes `SCRIPTS_HOST_PATH`. The search service reads this env to bind-mount
the scripts directory when it spawns on-demand pipeline containers
(`services/search/main.py:1367-1394`).
**Impact:** "Works on my machine" par excellence. A beta tester clones into
`/home/pi/geographica`; the search container ends up advertising a Cameron-only
host path to Docker, so admin-panel pipelines fail on the very first click with
an import error or empty mount. Invisible to the original developer.
**Blast radius:** Low; fix lives in `generate_env` + one `bootstrap.sh` addition.
**Fix approach:** Emit `SCRIPTS_HOST_PATH=<repo_dir>/scripts` from `generate_env`
(wizard already knows `Path(__file__).parent.parent`).

#### B4. Wizard never builds the `--profile pipeline` image → admin-panel pipelines 422 immediately after launch
**Consensus:** All 3 hunters.
**Location:** `setup/main.py:560-564` runs `docker compose ... up -d` with no
`--profile pipeline build` invocation; `docker-compose.yml:207-224` hides the
pipeline service behind `profiles: ["pipeline"]`; `services/search/main.py`
raises HTTP 422 "Pipeline image not built" on first admin-panel pipeline call.
**Evidence:** Verified `docker-compose.yml:211` has `profiles: ["pipeline"]`.
**Impact:** The first thing a new user tries in the admin panel — imagery
download — fails with a terminal-only remediation (`docker compose --profile pipeline build`).
Trust in the wizard collapses at click #1.
**Blast radius:** Low; single extra command in `/api/launch`.
**Fix approach:** In `post_launch()`, run `docker compose --profile pipeline build`
before (or alongside) the `up -d` call.

#### B5. `bootstrap.sh` installs Docker Compose v1, everything else requires v2 plugin → preflight infinite loop
**Consensus:** All 3 hunters.
**Location:** `bootstrap.sh:31` (`apt install -y ... docker.io docker-compose`);
`setup/main.py:40` (`FIX_REGISTRY["docker-compose"] = ... "docker-compose"`);
`setup/main.py:54` (preflight runs `docker compose version`, plugin syntax);
`README.md:139` (manual path correctly documents `docker-compose-plugin`).
**Evidence:** Verified `bootstrap.sh:31` installs the legacy `docker-compose`
package. Preflight at `setup/main.py:54` uses `["docker", "compose", "version"]`.
**Impact:** Fresh Debian Trixie users: bootstrap installs v1 (if available);
preflight `docker compose version` fails ("unknown command"); user clicks
"Install", FIX_REGISTRY re-installs v1, preflight still fails. No path to
proceed. This is likely the single biggest Quick-Start footgun for v1.1.0.
**Blast radius:** Medium; affects bootstrap, FIX_REGISTRY, and possibly
requires adding Docker's official apt repo.
**Fix approach:** Decide: stay with `docker.io` + `docker-compose-v2` from
Debian's repo (Trixie ships v2 under that name), OR add Docker's official repo
and install `docker-ce` + `docker-compose-plugin`. The Debian-repo path is
simplest and matches `docker.io`; update bootstrap + FIX_REGISTRY accordingly.

#### B6. Credentials flow is 100% decorative — `credentials.json` vs `.credentials.json` + OAuth2 vs username/password + 0644 umask + migration runs once at daemon start
**Consensus:** All 3 hunters (different facets).
**Location:**
- `setup/main.py:65`: `CREDENTIALS_PATH = "/srv/geographica/data/credentials.json"` (no dot)
- `services/keyring-agent/agent.py:32-33,165`: migration scans `/srv/geographica/data/.credentials.json` (with dot); migration runs once at `serve()` startup
- `setup/main.py:136-141`: `CredentialsRequest` uses `copernicus_client_id`/`_secret` (OAuth2)
- Admin panel + keyring agent use `copernicus_username`/`_password`
- `setup/main.py:311-313`: `write_text` without chmod → 0644 plaintext
**Evidence:** I read `agent.py` and confirmed both the dot-prefix mismatch and
the fact that `serve()` runs migration once at startup. `bootstrap.sh:79` starts
the keyring daemon **before** the wizard runs, so even with the path fixed the
daemon has already scanned and moved on.
**Impact:** Step 3 credentials are stored under the wrong key names, in the
wrong file, never migrated, and world-readable. The v1.0.0 "credentials in GNOME
Keyring, no plaintext" promise is broken for every wizard user.
**Blast radius:** Medium; cleanest fix is to have the wizard write credentials
directly through the keyring agent's Unix socket (cut the JSON path entirely).
That's a larger refactor than a simple filename fix. Alternative: rename path,
rename fields, chmod 0600, re-trigger migration via an agent SIGHUP or D-Bus
method.
**Fix approach:** Recommend direct keyring write via Unix socket
(`/run/geographica/keyring.sock`) — the admin panel already uses this
path, so the wizard just calls the same API. Remove `CREDENTIALS_PATH` and its
write entirely.

#### B7. `all_healthy` substring match: `"healthy" in "unhealthy"` is True
**Consensus:** Holistic + multipass.
**Location:** `setup/main.py:549-552`.
**Evidence:**
```python
all_healthy = all(
    "healthy" in (s.get("Health", "") or s.get("Status", ""))
    for s in existing_services
)
```
Docker compose ps fills `Status` with strings like `"Up 2 days (unhealthy)"`.
Substring match returns True.
**Impact:** Re-running `./setup.sh` against a broken stack reports
"already running and healthy" — user never sees the problem. Silent false
success.
**Blast radius:** Trivial; one function.
**Fix approach:** Check `Health == "healthy"` exactly, or parse `Status` with a
regex that distinguishes `(healthy)` from `(unhealthy)`.

#### B8. Multiple README + bootstrap URL typos: `cdzucker` (4 locations total)
**Consensus:** Multipass + exploratory (extends the user-known fix).
**Location:**
- `README.md:111` (known — Quick Start clone)
- `README.md:185` (known — Manual clone)
- `README.md:576` (NEW — Companion utility URL)
- `bootstrap.sh:24` (NEW — world-writable-repo warning message)
- `README.md:588` (NEW — `~/Code/geographica` hardcoded dev-Pi path, should be
  `~/geographica` per bootstrap's suggested clone path)
**Evidence:** Verified all four in the code. The world-writable warning in
bootstrap.sh:24 directs users to clone from the wrong URL.
**Impact:** Any user who hits one of these paths gets 404s on GitHub. Erodes
confidence.
**Blast radius:** Docs only.
**Fix approach:** Global find-and-replace `cdzucker` → `cameronzucker`. Update
line 588 to match the bootstrap-suggested `~/geographica`.

#### B9. Custom storage path UI missing from Step 1 (user-known, scoped here for completeness)
**Consensus:** All 3 hunters note the orphaned backend endpoints
(`/api/validate-path`, `/api/create-directory`).
**Location:** `setup/static/index.html:67-72`, `setup/static/setup.js:238-261`.
**Evidence:** The `<select id="data-path">` lists only auto-detected mount points
plus the default. No "Other" option, no text input, never calls the validation endpoint.
**Impact:** User's stated #2 complaint. They want drive-then-path + fully custom
paths (network drives, e.g. NFS mounts the wizard can't auto-detect).
**Blast radius:** Must coordinate with B2 (path has to actually propagate).
**Fix approach:** See Design Decision D1 below — this is the scope question
the user asked me to answer.

#### B10. `_run_pipeline` is a no-op (user-known)
**Consensus:** All 3 hunters note this as baseline context.
**Location:** `setup/main.py:458-519`.
**Evidence:** Loop defines `on_output` but never calls `run_command`. Extra
details found by hunters:
- Disk-full check swallows `FileNotFoundError` if path doesn't exist (M23)
- Disk-critically-low break branch still falls through to `pipeline_done` with
  `progress_pct=100` (E9) — presents disk error as success
- `/api/start` has a TOCTOU race allowing concurrent pipeline spawns (M25)
- `progress_buffer` mutated concurrently while iterated on WS connect crashes
  with `RuntimeError: deque mutated during iteration` (M26)
- `shutdown_children` doesn't kill grandchildren (no process group, M27)
- `broadcast` awaits per-socket serially, slow client stalls pipeline (M28)
- `except Exception` broadcast omits `step` field, UI swallows error (M32)
- `PIPELINE_STEPS` ignores user's `body.layers` + `base_imagery_zoom` (E+H+M)
- `fonts`, `styles`, and `public_lands` steps have NO command builder (H11)
- `public_lands` is structurally impossible (CAPTCHA + tippecanoe) (H10)
- Planetiler uses `:latest` tag in `setup/runner.py:61` but README pins `0.10.2` (M42)
**Impact:** Re-wiring the loop is the user's known #3 complaint (downstream of
"missing dependencies" — once wired, dependencies start being needed). The list
above is the full remediation scope, not just "call `run_command`".
**Blast radius:** High; touches runner.py, main.py, the per-step
command-builder library, and the schema of what a pipeline step IS (see HDC1).
**Fix approach:** See Plan — this is multiple tasks with clear test boundaries.

### Significant — breaks UX, leaks data, or creates latent failures

#### B11. `HOST_IP` field is fully dead (nothing reads the value) + `detect_host_ip` returns `0.0.0.0` as a user-visible fallback
**Consensus:** Holistic + multipass.
**Location:** `setup/config.py:160-185` + `setup/config.py:333`; no consumer in
any `.yml`, `.conf`, or `.sh` reads `HOST_IP`; `setup/static/setup.js:886` builds
the "Open Geographica" link from it.
**Evidence:** I grep-confirmed: the string `HOST_IP` appears in setup code, the
.env template, and tests — but nowhere in the running stack. NGINX uses
`$http_host` (request header), not `$HOST_IP`.
**Impact:** Step 1 asks for data the stack ignores; detection fallback writes
`HOST_IP=0.0.0.0`, which then becomes the href on the completion page. Users
click and get "Can't connect."
**Fix approach:** Remove the field from Step 1 and from `generate_env`. Build
the completion link from `window.location.hostname` or from `/api/health`
service-IP discovery.

#### B12. "Existing .env found — values pre-filled" is a lie; wizard clobbers existing `.env`
**Consensus:** Exploratory + multipass.
**Location:** `setup/main.py:184` sets the flag; `setup/static/setup.js:263-265`
shows the message; no code ever reads the existing `.env` values into form
fields; `setup/main.py:298` does a full overwrite via `write_text`.
**Impact:** A user re-running the wizard to change one setting loses all prior
config (`TLS_MODE=tailscale`, custom `DATA_PATH`, `STT_BACKEND=npu`, etc.).
**Fix approach:** Parse existing `.env` into `/api/system` response; pre-fill
form fields. At save time, merge with existing values (retain keys the wizard
doesn't know about) instead of overwriting.

#### B13. `saveConfig` / `saveCredentials` / `loadPresets` / `onTlsModeChange` silently swallow fetch errors
**Consensus:** All 3 hunters.
**Location:** `setup/static/setup.js:500-509, 511-528, 318-334, 273-305`.
**Impact:** User clicks Next; backend rejected save; UI advances as if
everything worked. Error surfaces far downstream (often at Launch). Classic
silent-failure pattern.
**Fix approach:** Single shared `showError(msg)` helper wired into every
`.catch` branch (MDC3). Await saves before navigating. Block Next until save
resolves.

#### B14. `Checkpoint` crashes on corrupt JSON + non-atomic persist + no reset UI + `_persist` fails if data path missing
**Consensus:** All 3 hunters.
**Location:** `setup/runner.py:18-23, 40-41`.
**Impact:** Any power-loss or SIGKILL mid-pipeline leaves a truncated JSON →
next run crashes on instantiation → wizard shows an opaque "Expecting value"
error with no path to recover. User must `rm .setup_checkpoint.json` manually.
**Fix approach:** Wrap `json.loads` in try/except returning empty dict;
atomic-write `_persist` (temp file + rename); add `/api/checkpoint/reset`
endpoint + button; ensure parent dir exists before `write_text`.

#### B15. `/api/start` TOCTOU race allows concurrent pipelines
**Consensus:** Multipass.
**Location:** `setup/main.py:446-455`.
**Impact:** Double-click spawns two pipelines writing the same checkpoint and
broadcasting duplicate events.
**Fix approach:** Set `current_state["running"] = True` synchronously inside
the `post_start` handler (before the `asyncio.create_task`), under an
`asyncio.Lock`. Return 409 if already running.

#### B16. `progress_buffer` iterated on WS connect while pipeline mutates → RuntimeError
**Consensus:** Multipass.
**Location:** `setup/main.py:411-414` vs `:437, :506`.
**Fix approach:** `for event in list(progress_buffer):` (snapshot via list copy).

#### B17. `shutdown_children` doesn't kill subprocess grandchildren
**Consensus:** Multipass.
**Location:** `setup/runner.py:121-127, 150-156`.
**Fix approach:** Spawn with `start_new_session=True`; `os.killpg(pgid, SIGTERM)`
on shutdown.

#### B18. `broadcast` serializes WebSocket writes — slow client stalls pipeline
**Consensus:** Multipass.
**Location:** `setup/main.py:435-443`.
**Fix approach:** `asyncio.gather(..., return_exceptions=True)` with per-socket
timeouts.

#### B19. Self-signed TLS option never calls `/api/tls/generate` (endpoint is orphaned)
**Consensus:** Holistic + multipass.
**Location:** `setup/main.py:317-331` + no call site in `setup.js`.
**Fix approach:** When `tls_mode=self-signed`, call `/api/tls/generate` during
Step 1 submit, or before `/api/launch`. Write `TLS_CERT_DIR` into `.env`.

#### B20. Step 2 zoom slider + layer source buttons never reach the backend
**Consensus:** Holistic + multipass.
**Location:** `setup/static/setup.js:32,182,628-632,951` vs
`setup/main.py:155-159` (StartRequest has no `zoom` or per-layer-source fields).
**Fix approach:** Extend `StartRequest` (and the pipeline dispatch) to accept
zoom and per-layer source; gate PIPELINE_STEPS by the user's choices.

#### B21. Preflight missing: `tippecanoe`, `rasterio`/`shapely`/`scipy`/`numpy` Python packages, keyring agent status, cgroup memory support, `openssl` (for tls/scan)
**Consensus:** Exploratory + holistic.
**Location:** `setup/main.py:52-62`.
**Impact:** Once `_run_pipeline` actually runs commands, every script that
imports rasterio/shapely will ImportError. `public_lands` fails on tippecanoe.
Container memory limits silently ignored if cgroup not enabled.
**Fix approach:** Add each check. For Python deps, run
`pip install -r scripts/requirements.txt` at bootstrap time (not wizard time)
into the setup venv, or ship a containerized runner (pipeline image already does
this — see D2 below about unifying paths).

#### B22. `FIX_REGISTRY` vs `PREFLIGHT_CHECKS` asymmetry: `python3` check has no fixer; `git` check has no fixer; `python3-venv` fixer has no check
**Consensus:** Multipass.
**Location:** `setup/main.py:39-62`.
**Impact:** Dead-end Install buttons.
**Fix approach:** Ensure each `PREFLIGHT_CHECKS[i].name` maps to a
`FIX_REGISTRY` entry. Or: drop Install buttons entirely and direct user to
re-run `sudo ./bootstrap.sh` (see D3 below).

#### B23. `FIX_REGISTRY["docker-compose"]` installs v1 → preflight still fails → infinite loop (sub-issue of B5)
**Consensus:** Multipass + exploratory.
**Location:** `setup/main.py:41`.
**Fix approach:** Change to `docker-compose-v2` on Debian (Trixie) or align
with whatever bootstrap decides (B5).

#### B24. `/api/fix-dependency` uses `sudo apt install` with no TTY → always fails on non-NOPASSWD Pi, UI shows "Failed" with no reason
**Consensus:** Holistic + multipass.
**Location:** `setup/main.py:39-49, 239-261`.
**Fix approach:** Drop the Install buttons altogether; tell user to re-run
`sudo ./bootstrap.sh`. Alternative (not recommended): ask for sudo via
`askpass`, but that's invasive and error-prone.

#### B25. Pipeline `except Exception` broadcasts without `step` field → UI drops error to log viewer (hidden)
**Consensus:** Multipass.
**Location:** `setup/main.py:515-517` + `setup/static/setup.js:740-752`.
**Fix approach:** Always include `step` in error broadcasts; surface errors in
the main progress panel, not only in the collapsed log viewer.

#### B26. `/api/credentials` write failures surface as generic 500; UI logs to console only
**Consensus:** Multipass.
**Location:** `setup/main.py:302-314`.
**Fix approach:** Wrap in try/except; return structured error; frontend
displays via shared `showError`.

#### B27. `public_lands` pipeline step requires CAPTCHA-protected manual download + tippecanoe compiled from source
**Consensus:** Holistic.
**Location:** `setup/main.py:428-432` lists it; `scripts/build_public_lands.py:268-280`
detects HTML/CAPTCHA response and errors; `README.md:317-335` documents the
manual workaround.
**Fix approach:** Remove `public_lands` from `PIPELINE_STEPS` for now. Surface
a separate "Manual PAD-US download" step in a follow-up that links to the
ScienceBase URL and accepts the downloaded zip via `/api/import-padus`.

#### B28. `fonts` step has no command builder; `styles` step (icon clone from upstream repos) isn't even listed in PIPELINE_STEPS
**Consensus:** Holistic.
**Location:** `setup/main.py:428-432`; `setup/runner.py` has no `fonts_cmd` or
`styles_cmd`.
**Fix approach:** Add commands to runner.py and register `styles` step. Or:
bundle fonts+styles into the repo so no pipeline step is needed (they're small).

#### B29. `generate_env` omits env vars docker-compose expects: `DATA_HOST_PATH`, `SCRIPTS_HOST_PATH`, `TLS_CERT_DIR`, `TLS_PORT`, `STT_BACKEND`, `POSTGRES_WORK_MEM`, `POSTGRES_AUTOVACUUM_WORK_MEM`
**Consensus:** Multipass + holistic.
**Location:** `setup/config.py:323-365`.
**Fix approach:** Audit every `${…}` reference in `docker-compose.yml` and
ensure `generate_env` emits them. For vars tied to user choice, derive from
Step 1/2 input; for secrets/credentials path, use the keyring Unix socket.

#### B30. RAM-profile vars are a placebo — only `POSTGRES_*` and `VALHALLA_THREADS` flow through
**Consensus:** Holistic.
**Location:** `setup/config.py:82-117` defines profile; `docker-compose.yml`
hard-codes most memory limits (`memory: 1G`, `memory: 8G`, etc.); scripts
hold module-level constants for `M2M_BATCH_SIZE`, `PLANETILER_HEAP`.
**Fix approach:** Change docker-compose memory limits to read env vars
(`memory: "${NOMINATIM_MEMORY:-8G}"`) and wire the script constants to env
reads. Update tests to verify round-trip.

#### B31. `bootstrap.sh` sed-edits `/boot/firmware/cmdline.txt` unconditionally if grep can't find file → aborts bootstrap on older Pi OS / generic Debian
**Consensus:** Exploratory + multipass.
**Location:** `bootstrap.sh:51-55`.
**Fix approach:** Detect which cmdline path exists (`/boot/firmware/cmdline.txt`
vs `/boot/cmdline.txt` vs neither) before editing. If neither, warn + skip.
Wrap the whole block in an "is-raspberry-pi" check (`[ -d /boot/firmware ]`
or `grep -q Raspberry /proc/cpuinfo`).

#### B32. `bootstrap.sh` `ln -sf` mis-handles existing `data/` directory
**Consensus:** Multipass.
**Location:** `bootstrap.sh:70`.
**Evidence:** GNU `ln -sf` with an existing *directory* target creates
`./data/data → /srv/geographica/data` (buried nest).
**Fix approach:** Use `ln -sfn` (force, no-deref) and explicitly `rm -f` any
existing symlink first.

#### B33. `bootstrap.sh` `chown -R /srv/geographica` clobbers bind-mounted volume perms on rerun
**Consensus:** Multipass.
**Location:** `bootstrap.sh:67`.
**Fix approach:** Only chown the top-level dir + immediate subdirs; skip if
owner is already correct; or skip entirely on rerun.

#### B34. `validate_path` prefix check doesn't enforce path boundary: `/srvattacker`, `/homeroot`, `/srv` alone all validate True
**Consensus:** Exploratory.
**Location:** `setup/config.py:286-292`.
**Fix approach:** Use `Path(prefix).is_relative_to(...)` (Python 3.9+) or
normalize prefixes with trailing `/`.

#### B35. `validate_path` symlink check is dead code — `Path.resolve()` already followed any symlinks
**Consensus:** Multipass.
**Location:** `setup/config.py:294-299`.
**Fix approach:** Walk the *original* `path_str` components (not `resolved`)
with `Path(component).is_symlink()`. Or accept that the security goal is
"prevent writes through attacker-controlled symlinks" and state that resolve-
based validation is the correct primitive (document the design decision).

#### B36. `main.py:598` binds `0.0.0.0:8099` when run as `python3 -m setup.main` (setup.sh binds 127.0.0.1 correctly)
**Consensus:** Exploratory + holistic.
**Location:** `setup/main.py:596-598`.
**Fix approach:** Change `host="0.0.0.0"` → `host="127.0.0.1"`. Document
`./setup.sh` as the only entry point.

#### B37. Bootstrap final message prints "Next step:" twice + doesn't mention log-out requirement before running `setup.sh`
**Consensus:** Multipass.
**Location:** `bootstrap.sh:90-108`.
**Evidence:** I verified: in NEEDS_REBOOT path, prints "After reboot, run:" +
"Next step:" + "./setup.sh". In non-reboot path, prints "Next step:" + "Next step:"
+ "./setup.sh" (duplicate).
**Fix approach:** Deduplicate. Add an explicit "Log out and back in before
running `./setup.sh` (the docker group needs to take effect)" line.

#### B38. README Tailscale instructions append `TLS_MODE=tailscale` to `.env` even if wizard wrote `TLS_MODE=http` first → duplicate keys + wrong value wins
**Consensus:** Multipass.
**Location:** `README.md:557-559`.
**Fix approach:** Either have the wizard offer a "Tailscale" TLS mode directly
(covered by B1), or update README to use `sed -i` replacement instead of `echo >>`.

#### B39. `detect_host_ip` returns `0.0.0.0` on failure; UI accepts it as a valid value
**Consensus:** Holistic + multipass.
**Location:** `setup/config.py:160-185` + `setup/static/setup.js:230`.
**Fix approach:** Return `None` on failure; UI shows error state; required-field
validator rejects `0.0.0.0`. Partial overlap with B11 (remove HOST_IP
altogether makes this moot).

#### B40. `host_ip` accepted without format validation (accepts `my-pi.local` with no domain, `192.168.1` with only 3 octets, etc.)
**Consensus:** Multipass.
**Location:** `setup/main.py:284-299`; `setup/static/setup.js:156-164`.
**Fix approach:** Validate with `ipaddress.ip_address()` or an FQDN regex
before writing `.env`.

#### B41. `detect_storage` offers mounts the ALLOWLIST rejects (e.g. `/boot/geographica/data` from `/boot` mount)
**Consensus:** Multipass.
**Location:** `setup/static/setup.js:244` + `setup/config.py:203-250, 14`.
**Fix approach:** Filter `detect_storage` results against `ALLOWED_PATH_PREFIXES`
before returning to the UI. Or: call `/api/validate-path` on the user's
selection before advancing past Step 1.

#### B42. `INACTIVITY_TIMEOUT` defined but never enforced — wizard's "ephemeral" claim is false
**Consensus:** Exploratory + multipass.
**Location:** `setup/main.py:74-84, 110-111, 460, 499, 503`.
**Fix approach:** Either implement the idle timer (background task that
`sys.exit()` after 30 min of no activity), or delete the variable and rewrite
the "ephemeral" claim. Recommend the timer (one more layer of defense for a
localhost-only service that runs `sudo apt install`).

### Minor — cosmetic / maintainability / low-impact UX

#### B43. WebSocket progress buffer `maxlen=100` drops 99%+ of history on long runs
**Location:** `setup/main.py:79`.
**Fix approach:** Bump to `maxlen=5000` or persist to a file that gets truncated
on completion.

#### B44. `/api/fix-dependency` / `/api/tls/generate` / `/api/launch` return inconsistent response shapes (`{ok, exit_code, output}` vs `{exit_code, output}` vs `{exit_code, output, state, existing_count}`)
**Location:** `setup/main.py:261, 331, 574-579`.
**Fix approach:** Unify to `{ok, exit_code, output, ...extras}`.

#### B45. `fixDependency` re-renders entire preflight list on success, losing sibling Install buttons mid-click
**Location:** `setup/static/setup.js:604-605`.
**Fix approach:** Surgically update just the row that installed; or disable all
Install buttons globally while any is in-flight.

#### B46. Subprocess stderr-only warnings indistinguishable from stdout in log viewer
**Location:** `setup/main.py:501-506`; `setup/static/setup.js:732-734`.
**Fix approach:** Color-code lines by `event.source`.

#### B47. `/api/tls/scan` silently swallows openssl errors; returns `{certs: []}` identical to "no certs"
**Location:** `setup/main.py:347-368`.
**Fix approach:** Return a separate `tool_missing: true` field if openssl not
found.

#### B48. `post_credentials` writes empty-string fields when only one credential set is filled — mixed semantics downstream
**Location:** `setup/main.py:302-314` + `setup/static/setup.js:511-528`.
**Fix approach:** Skip empty fields in the payload; backend treats missing keys
as "don't update".

---

## Design Decisions Requiring User Input

### D1. How should the install-location selector work? [USER EXPLICITLY ASKED FOR THIS]
**Concern:** Today the dropdown shows detected partitions only and the Docker
stack ignores the chosen path anyway (B2). User wants: drive-then-path (pick a
detected drive, then specify a directory on it) + fully custom paths (e.g. NFS
mount that auto-detect can't see).
**Options:**
- **D1-a** (recommended): Two-control layout. First control = drive dropdown
  (lists detected partitions — their mount points — plus an "Other" sentinel).
  Second control = text input for the path *under* the chosen drive. When
  "Other" is picked, the drive dropdown collapses and the text input accepts
  any absolute path. Frontend calls `/api/validate-path` (debounced on input
  blur) to validate allowlist membership and report disk-space. Frontend calls
  `/api/create-directory` on Next. Backend emits `DATA_HOST_PATH=<full_path>`
  and the `/api/launch` re-targets the `./data` symlink to the chosen path.
- **D1-b**: Single free-form text input for absolute path, pre-filled with the
  first detected mount's recommended subdir. Simpler UI but loses the hint
  about available drives and sizes.
- **D1-c**: Keep the dropdown, add a single "Other" option that reveals a
  text input. No "path on drive" distinction. Matches the commit message of
  5b55c16 but doesn't give the user drive-then-path control.

**Recommendation: D1-a.** Aligns with what the user described; reuses existing
backend endpoints; preserves the "here's how much space you have" affordance
for detected drives while also supporting network paths.

### D2. Is the wizard supposed to REPLACE the manual README path, or SUPPLEMENT it?
**Concern:** Today they diverge (different docker-compose version, different
Planetiler tag, different env-var set, different deps-install flow). Every bug
in this list exists partly because the two paths are independent.
**Options:**
- **D2-a**: Wizard is the primary path; README manual section is
  verify/troubleshoot-only. Bootstrap installs everything the wizard needs;
  `generate_env` emits every `${...}` referenced in docker-compose.
- **D2-b**: Manual path is primary; wizard is a convenience layer. All manual
  steps stay in README; wizard shells out to them.
- **D2-c**: Remove the wizard entirely for v2.0; ship a better `bootstrap.sh`
  + a CLI `geographica setup` that prints recommended values.

**Recommendation: D2-a.** v1.0 already shipped the wizard as the marquee "Quick
Start" flow. Investing in it and making it authoritative pays off; retreating
to manual-only is a product regression. This is a bigger scope decision than
the individual bugs — affects which tasks land in the plan.

### D3. Should `/api/fix-dependency` + Install buttons stay, or should missing deps route users back to `sudo ./bootstrap.sh`?
**Concern:** B24 shows sudo-via-no-TTY is architecturally broken. B22/B23 show
the check/fix asymmetry. Keeping the feature means fixing at least two real
problems and trusting `sudo apt install` via a web UI.
**Options:**
- **D3-a**: Remove `/api/fix-dependency` entirely. Preflight failure shows
  "run `sudo ./bootstrap.sh` to install [dep1, dep2]". User re-runs bootstrap,
  reloads wizard.
- **D3-b**: Keep the endpoint but gate it behind a check: if sudo prompts for
  password, error with a clear UI message. User still has to run bootstrap.
- **D3-c**: Status quo + fix the asymmetry (expensive, security risk).

**Recommendation: D3-a.** Smaller attack surface, simpler UX, matches the
docs ("sudo ./bootstrap.sh" is already the expected flow). One less endpoint to
maintain. Preflight still runs — just surfaces actions instead of performing them.

### D4. Credentials: write through the keyring agent Unix socket, or keep the JSON file path?
**Concern:** B6 breaks at 5 levels simultaneously. Clean fix is to stop writing
a file at all.
**Options:**
- **D4-a** (recommended): Wizard Step 3 calls the keyring agent's Unix socket
  directly (same API as the admin panel). Drop `CREDENTIALS_PATH` and its write
  entirely. The admin panel will read them through the keyring as designed.
- **D4-b**: Keep the JSON file but fix all 5 bugs (field names, filename,
  chmod, path, re-trigger migration). Fragile; re-introduces the plaintext
  file the v1.0 keyring work was trying to eliminate.

**Recommendation: D4-a.**

### D5. Should PIPELINE_STEPS be replaced with a structured dataclass?
**Concern:** HDC1. Current list-of-strings lets fonts/styles/public_lands have
no builders and the user's layer selections get silently ignored. A dataclass
forces each step to declare required deps, required credentials, and whether
it's skippable.
**Options:**
- **D5-a** (recommended): Introduce `@dataclass class PipelineStep: id,
  label, cmd_builder, required_deps, required_creds, skippable_by`. Iterate
  over these in `_run_pipeline`; reflect the user's layer choices by checking
  `step.skippable_by`.
- **D5-b**: Keep the list but add a parallel mapping of metadata. Less elegant
  but smaller diff.

**Recommendation: D5-a.** Larger refactor; justifies itself by eliminating an
entire category of drift forever.

### D6. Should the wizard still ask for `HOST_IP`?
**Concern:** B11 — nothing in the deployed stack reads it. The value exists
only to build a completion-page link.
**Options:**
- **D6-a** (recommended): Remove the field. Build the completion link from
  `window.location.hostname` (the IP the user already used to reach the wizard,
  through a tunnel or directly). No detection needed.
- **D6-b**: Keep it but validate it (B40) and use `None` sentinel for detection
  failure. Still asks for data the stack ignores.

**Recommendation: D6-a.**

### D7. Which minor bugs are worth fixing in this cycle vs deferring?
**Recommendation:** Fix all **critical** and **significant** bugs; defer most
**minor** bugs to a v1.2 cycle. Specific minor bugs worth including anyway
because they're one-line fixes: B8 (URL typo — already must be fixed to
unblock the beta tester), B37 (bootstrap duplicate "Next step:"), B43 (buffer
maxlen bump — one literal change). Everything else in the minor list can be
documented in the plan appendix.

### D8. Should we add an LXD/CI harness for the wizard path end-to-end? (MDC10)
**Concern:** The `lxd-validation` skill tests the README manual path; no
equivalent for the wizard. Would have caught most of these bugs.
**Options:**
- **D8-a**: Add to this cycle — Playwright-driven LXD flow that runs the
  wizard, asserts healthy services. Big scope.
- **D8-b**: Defer — land the fixes in this cycle, document the harness as v1.2
  work.

**Recommendation: D8-b.** The fixes are urgent (beta tester blocked); a
harness is a week+ of work. Add it after the fixes land.

---

## False Positives

### FP1. "validate_path symlink check is dead code"
**Flagged by:** Multipass (B35 above).
**Partial false positive, partial real bug:** The check IS dead code as
written — `Path.resolve()` follows symlinks so `is_symlink()` on the resolved
path is always False. BUT the protection was probably intended to prevent
writes through attacker-controlled symlinks into unexpected locations, and
`resolve()` collapsing them into a prefix-validated target might be the
correct primitive. Classifying as a real bug (B35) with a "fix or document
the design decision" choice.

---

## Bugs Outside Primary Scope (documented for future cycles)

### O1. `scripts/*.py` module-level constants vs env vars
**Location:** `scripts/acquire_imagery.py` module-level `M2M_BATCH_SIZE`;
similar in `acquire_sentinel.py`.
**Why outside scope:** This is scripts/ territory, not setup/. Part of the
remediation for B30 but broader.
**Recommendation:** Include in follow-up.

### O2. README §12 "Verify the deployment" mixes direct-port and nginx-proxied URLs
**Location:** `README.md:466-484`.
**Why outside scope:** README documentation cleanup, not setup wizard.
**Recommendation:** One-line fix during the README pass in this cycle (cheap).

### O3. No CI harness for wizard path (design D8)
**Recommendation:** Defer to v1.2.

---

## Test Gap Analysis

### B1 (TLS vocabulary mismatch)
**Why missed:** `tests/test_setup_config.py` validates `generate_env`'s output
*format* (that the line `TLS_MODE=...` appears) but not that the value is one
nginx understands. No end-to-end test round-trips an enum value through the
wizard→.env→nginx entrypoint stack.
**Pitfall coverage:** **New pitfall added by holistic hunter** (`dev/testing-pitfalls.md`):
"Multi-layer enum values diverge silently". Keep.
**Catch test:** Enumerate every option in `<select id="tls-mode">`, pass each
through `generate_env`, feed output to a parsed `nginx/entrypoint.sh` mock, and
assert the branch taken matches intent (`https` branch for self-signed, etc.).

### B2 (DATA_PATH vs DATA_HOST_PATH) + B3 (SCRIPTS_HOST_PATH) + B29 (missing env vars)
**Why missed:** No test asserts round-trip consistency between `generate_env`
output keys and docker-compose.yml `${…}` references.
**Pitfall coverage:** **New pitfall added by exploratory hunter**
("Hardcoded dev-machine paths as docker-compose env defaults"). Keep.
**Catch test:** Parse docker-compose.yml, extract every `${VAR}` reference;
assert `generate_env` emits each, or explicitly whitelist.

### B5 (docker-compose v1 bootstrap + v2 preflight)
**Why missed:** `tests/test_setup_main.py` doesn't exercise the bootstrap
script; preflight tests use a mocked subprocess that always succeeds.
**Pitfall coverage:** **New pitfall added by multipass hunter**
("Preflight/fix registries with parallel keys that drift"). Keep.
**Catch test:** Integration test — LXD container runs bootstrap, then
`docker compose version` should exit 0.

### B6 (credentials flow)
**Why missed:** Wizard credential tests write to a tempfile; keyring agent
tests exist separately. No cross-layer test verifies wizard input appears in
the keyring.
**Pitfall coverage:** Partial — the hunters' new pitfall "Fire-and-forget
async save from UI that silently swallows server errors" covers the error
surface but not the cross-layer routing.
**Catch test:** Write credentials via wizard endpoint → assert keyring agent
reports them via its query interface.

### B7 (substring healthy/unhealthy)
**Pitfall coverage:** **New pitfall added** ("Substring matching on status
strings false-positives on '(un)healthy' variants"). Keep.
**Catch test:** Parametrize `all_healthy` with 8 real docker-compose status
strings.

### B10 (`_run_pipeline` no-op)
**Pitfall coverage:** **New pitfall added** ("Orchestrator loops that iterate
steps without invoking subprocess"). Keep.
**Catch test:** Mock `runner.run_command`, drive `_run_pipeline`, assert
`run_command.call_count == len(PIPELINE_STEPS)`.

### B15 (TOCTOU) + B16 (deque iteration) + B17 (grandchildren)
**Pitfall coverage:**
- **New pitfall** ("Deque/list iteration during async-concurrent mutation") — keep.
- **New pitfall** ("Subprocess orphan: grandchildren survive wizard shutdown") — keep.
- No pitfall yet covers TOCTOU in async handlers. **Add one.**

### Testing Pitfalls Updates
Hunters pre-populated `dev/testing-pitfalls.md` with 11 new entries (reviewed
— all generalizable and accurate). Keep all. Will ADD one more pitfall in
Phase 4: "TOCTOU in async endpoints: mutex the gate synchronously, not from
within the spawned task."

---

## Completeness Check

Total unique findings (after dedup):
- Confirmed bugs: 48 (B1-B48)
- Design decisions: 8 (D1-D8)
- False positives: 1 (FP1, also counted as confirmed bug B35)
- Out-of-scope: 3 (O1-O3)

Source hunter reports:
- Exploratory: 17 bugs + 5 design concerns → all accounted for.
- Holistic: 17 bugs + 5 design concerns → all accounted for.
- Multipass: 48 bugs + 10 design concerns → all accounted for (with heavy dedup
  across hunters).

Grand total of raw findings across the three reports = 82 + 20 = 102 items;
consolidated to 48 + 8 + 3 = 59 unique items, with 5 user-known regressions
carried forward as context. Every raw finding is traceable into the consolidated
list or documented as a duplicate in the hunter report overlap notes.
