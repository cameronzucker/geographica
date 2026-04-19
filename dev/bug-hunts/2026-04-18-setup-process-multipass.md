# Bug Hunt Report — Setup Process (post-v1.1.0)

## Scope
Analyzed files:
- `README.md` (833 lines)
- `bootstrap.sh` (108 lines)
- `setup.sh` (28 lines)
- `.env.example` (25 lines)
- `setup/main.py` (598 lines)
- `setup/config.py` (365 lines)
- `setup/runner.py` (156 lines)
- `setup/static/index.html` (291 lines)
- `setup/static/setup.js` (1048 lines)
- `docker-compose.yml` (229 lines)
- `scripts/requirements.txt`, `setup/requirements.txt`

All five passes performed.

Known regressions excluded:
- README.md lines 111 & 185 (`cdzucker` should be `cameronzucker`).
- Step 1 custom storage path UI missing.
- `setup/main.py:458-519` pipeline loop doesn't actually run commands.

## Bugs

### Custom data_path never propagates to Docker Compose
**Location:** `setup/config.py:323-365` (`generate_env`) + `docker-compose.yml:124,132`
**Severity:** critical
**Evidence:** The wizard stores the user's chosen storage location in `DATA_PATH=<dir>` in the generated `.env`, but `docker-compose.yml` reads the host path from the `DATA_HOST_PATH` env var (line 124) — not `DATA_PATH`. All service volumes (`./data:/data`, `./data:/srv/data`, `./data:/custom_files`) are relative to the repo root and resolve through the `./data` symlink created by `bootstrap.sh`, which hard-codes `/srv/geographica/data`. Likewise, `TLS_CERT_DIR`, `TLS_PORT`, `SCRIPTS_HOST_PATH`, `STT_BACKEND`, `POSTGRES_WORK_MEM`, `POSTGRES_AUTOVACUUM_WORK_MEM` are consumed by Compose but never written by `generate_env`.
**Impact:** If a user picks anything other than `/srv/geographica/data` in Step 1 (e.g. `/mnt/nvme/geographica/data` offered via storage detection), the `.env` claims that path but Docker actually still mounts `/srv/geographica/data` via the symlink. All pipeline outputs land in one place and all Docker services read from another — the stack will appear empty. This is the silent "picked the wrong drive" failure.
**Found in:** Pass 1 — Contract violations

### `generate_env` omits env vars that docker-compose.yml references
**Location:** `setup/config.py:323-365`
**Severity:** significant
**Evidence:** The generated `.env` does not include `POSTGRES_AUTOVACUUM_WORK_MEM`, `POSTGRES_WORK_MEM`, `TLS_CERT_DIR`, `TLS_PORT`, `DATA_HOST_PATH`, `SCRIPTS_HOST_PATH`, or `STT_BACKEND`. `.env.example` (line 17-18) includes `POSTGRES_AUTOVACUUM_WORK_MEM=256MB` and `POSTGRES_WORK_MEM=32MB` — so the manual path sets those, but the wizard path doesn't.
**Impact:** Wizard-generated deployments silently rely on Compose's hard-coded defaults. If those defaults drift from the wizard's RAM-profile intent, there is no single source of truth. The wizard's "8 GB profile" promises to reduce DB memory but `POSTGRES_WORK_MEM` stays at 32 MB regardless.
**Found in:** Pass 1 — Contract violations

### `all_healthy` check false-positives on "(unhealthy)" status string
**Location:** `setup/main.py:549-552`
**Severity:** significant
**Evidence:**
```python
all_healthy = all(
    "healthy" in (s.get("Health", "") or s.get("Status", ""))
    for s in existing_services
)
```
`docker compose ps --format json` fills `Status` with strings like `"Up 2 days (unhealthy)"`. Python's `in` treats `"healthy" in "unhealthy"` as True (substring match), so an entirely unhealthy stack is reported as `already_healthy` and the UI tells the user "all services running and healthy."
**Impact:** A beta tester re-running `./setup.sh` against a broken stack sees a "success" message and may open the app link to a broken system. No signal that services are unhealthy.
**Found in:** Pass 1 — Contract violations

### `validate_path` and `create_directory` endpoints are orphaned
**Location:** `setup/main.py:200-281`; no callers in `setup/static/setup.js`
**Severity:** minor (but related to known Step 1 gap)
**Evidence:** Grep for `validate-path` and `create-directory` in the frontend shows zero calls. The backend is ready; the UI wiring for custom path validation is absent.
**Impact:** Dead code + the storage-path UI cannot validate what the user types (once Step 1 regains the custom-path field). Also means any path-mkdir safety check is skipped.
**Found in:** Pass 1 — Contract violations

### `Checkpoint.__init__` crashes on corrupt JSON with no recovery
**Location:** `setup/runner.py:21-23`
**Severity:** significant
**Evidence:** `json.loads(self._path.read_text())` has no try/except. `_persist()` (line 40-41) writes non-atomically — power loss, SIGKILL, or full disk mid-write produces a truncated JSON. The next `./setup.sh` invocation instantiates `Checkpoint(...)` in `_run_pipeline`, raises `JSONDecodeError`, the exception is caught by the pipeline's `try/except` only *after* `Checkpoint(...)` has already blown up during construction — but that construction happens inside the try block, so the pipeline broadcasts an error. Still, the checkpoint is permanently unreadable until the user manually deletes it, and there is no "reset" UI.
**Impact:** A mid-pipeline crash bricks resume. The user has to `rm /srv/geographica/data/.setup_checkpoint.json` via shell to proceed — the wizard never tells them that.
**Found in:** Pass 1 — Contract violations

### `Checkpoint._persist` fails if `data_path` directory doesn't exist
**Location:** `setup/runner.py:40-41`
**Severity:** significant
**Evidence:** `_persist` calls `self._path.write_text(...)` but never `self._path.parent.mkdir(parents=True, exist_ok=True)`. The pipeline is invoked with `config.data_path` from the user — if the user picked a path that doesn't yet exist and the bootstrap-created `/srv/geographica/data` is empty but the path has been overridden to, say, `/mnt/nvme/geographica/data`, the first `mark_completed()` call raises `FileNotFoundError`.
**Impact:** Pipeline "runs" but no checkpoint is saved — on a retry, every step re-runs. Also, the FileNotFoundError gets swallowed into a generic "error" broadcast without directing the user to fix their path.
**Found in:** Pass 1 — Contract violations

### Pipeline runs against Launch tab port scheme that doesn't match README
**Location:** `setup/static/setup.js:883-886`; `README.md:486`
**Severity:** minor
**Evidence:** The wizard's completion link builds `http://<host>:8093` for HTTP mode, but the main app's documented URL is `http://<pi-ip>:8093` (line 486). That matches. However, `config.tls_mode === 'http'` is the only "no HTTPS" branch — for `tls_mode=external` (Tailscale), the link becomes `https://<host_ip>` which is wrong: Tailscale TLS uses `<hostname>.ts.net`, not the LAN IP. The README Tailscale section (line 571) explicitly says "Visit `https://<your-tailscale-hostname>`."
**Impact:** Users who chose "External proxy (Tailscale)" see a broken "Open Geographica" link pointing at `https://<lan-ip>` — the Tailscale cert doesn't cover the LAN IP, so the browser shows a cert error.
**Found in:** Pass 1 — Contract violations

### Self-signed TLS option has no code path that invokes `/api/tls/generate`
**Location:** `setup/static/setup.js:273-305` (TLS mode change handler); `setup/main.py:317-331` (endpoint)
**Severity:** critical
**Evidence:** When the user picks TLS mode `"self-signed"`, the UI shows the hint "A self-signed certificate will be generated" but never calls `/api/tls/generate`. Grep confirms zero callers of that endpoint in the frontend. The generated `.env` writes `TLS_MODE=self-signed`, then the Launch step runs `docker compose up -d`. Nginx entrypoint expects certificates at `${TLS_CERT_DIR:-./tls}` — that directory is empty, so nginx fails to start (or falls back to HTTP-only if `tls-include-empty.conf` is wired up).
**Impact:** User who picks "self-signed" believes they are getting HTTPS and gets either a broken frontend container or a silent fallback to HTTP. No hint to the user, no cert generation, no error.
**Found in:** Pass 2 — Cross-sibling patterns

### `PREFLIGHT_CHECKS` and `FIX_REGISTRY` disagree on `python3`
**Location:** `setup/main.py:39-62`
**Severity:** significant
**Evidence:** Preflight checks `python3 --version` keyed as `"python3"`. `FIX_REGISTRY` has `"python3-venv"` but no `"python3"`. The UI builds an `Install` button for any failing check using `check.name` (`setup.js:568`). Clicking Install for `python3` POSTs `{"dependency": "python3"}`, which hits `setup/main.py:247-248` → HTTP 400 "Unknown dependency: python3". The JS catch block just sets the button text to "Failed" with no reason shown.
**Impact:** A Pi without python3 (hypothetical on a fresh debootstrap) — or more realistically, a detection failure in `python3 --version` — lands in a dead-end UI with no path to recover.
**Found in:** Pass 2 — Cross-sibling patterns

### `PREFLIGHT_CHECKS` has `git` but `FIX_REGISTRY` doesn't
**Location:** `setup/main.py:39-62`
**Severity:** minor
**Evidence:** Same pattern as above — `git` is checked but the Install button can't fix it.
**Impact:** Dead-end UI; user has to install git manually and refresh. Would be more honest to either drop the Install button when there's no matching FIX_REGISTRY entry, or add git to the registry.
**Found in:** Pass 2 — Cross-sibling patterns

### `/api/fix-dependency` response shape drifts from `/api/tls/generate` and `/api/launch`
**Location:** `setup/main.py:261` (fix-dep), `:331` (tls-generate), `:574-579` (launch)
**Severity:** minor
**Evidence:** `/api/fix-dependency` returns `{ok, exit_code, output}`. `/api/tls/generate` returns `{exit_code, output}` (no `ok`). `/api/launch` returns `{exit_code, output, state, existing_count}` (no `ok`). Three subprocess wrappers, three shapes. Frontend code reflects the drift: `fixDependency` checks `data.ok` (setup.js:602); `launchStack` checks `data.exit_code === 0` (setup.js:895). If any future caller is written against the "wrong" convention, silent bugs result.
**Impact:** A latent maintainability footgun; today's real issue is limited to the inconsistency itself.
**Found in:** Pass 2 — Cross-sibling patterns

### `loadPresets` and `onTlsModeChange` silently swallow fetch failures
**Location:** `setup/static/setup.js:318-334` (loadPresets), `:273-305` (onTlsModeChange)
**Severity:** significant
**Evidence:** `loadPresets` has no `.catch` — if `/api/presets` 500s or the wizard is disconnected, the dropdown is silently empty. Same for the TLS cert scan call on line 281. Compare to `loadSystemInfo` which has an error branch that updates `host-ip-hint`.
**Impact:** The Region dropdown appears broken with no error message. User has no idea the wizard lost backend connectivity.
**Found in:** Pass 2 — Cross-sibling patterns

### `saveConfig` and `saveCredentials` log errors to console only; user never sees them
**Location:** `setup/static/setup.js:506-508, 525-527`
**Severity:** significant
**Evidence:** Both catch handlers call `console.error(...)` and return, then `nextStep()` advances the wizard as if they'd succeeded. If `.env` write fails (permissions, full disk) or the credentials POST fails, the pipeline will try to run without config.
**Impact:** Classic silent-failure UX — user clicks Next, thinks everything saved, and much later sees an unrelated pipeline failure because `.env` was never written. The broken state is indistinguishable from a successful save until the user reaches Step 4.
**Found in:** Pass 2 — Cross-sibling patterns

### `bootstrap.sh` installs Docker Compose v1 (`docker-compose`) but preflight expects v2 (`docker compose`)
**Location:** `bootstrap.sh:31`; `setup/main.py:54`; `README.md:157`
**Severity:** critical
**Evidence:** `apt install -y docker-compose` installs the legacy Python v1 package (deprecated since 2023 and missing from Debian Trixie). `setup/main.py:54` preflights `["docker", "compose", "version"]` (v2 plugin). The README manual path correctly calls out `docker-compose-plugin` (line 139) but bootstrap.sh does not. On a fresh Trixie Pi, `apt install docker-compose` either fails (no candidate) or installs v1; the wizard then reports "docker-compose missing" with an Install button that runs the same failing command.
**Impact:** Bootstrap either fails outright on Trixie or installs v1; preflight fails; user hits an infinite "Install → still missing" loop. This is arguably the single biggest footgun for brand-new users and likely the root cause for any beta tester who bootstrapped on Trixie.
**Found in:** Pass 3 — Failure modes

### `bootstrap.sh` sed-edits `/boot/firmware/cmdline.txt` unconditionally if grep finds nothing
**Location:** `bootstrap.sh:51-55`
**Severity:** significant
**Evidence:**
```bash
if ! grep -q "cgroup_enable=memory" /boot/firmware/cmdline.txt 2>/dev/null; then
    sed -i 's/$/ cgroup_enable=memory cgroup_memory=1/' /boot/firmware/cmdline.txt
```
The grep has `2>/dev/null` (quiets "file not found"), but if the file doesn't exist, `grep` returns non-zero, entering the branch — then `sed -i` runs without `2>/dev/null`, attempting to edit a non-existent file. With `set -e` at the top of the script, this aborts bootstrap, leaving the user partway through.
**Impact:** On non-Raspberry-Pi systems (LXD containers, generic Debian VMs used for testing) or Pis without `/boot/firmware` (legacy `/boot/cmdline.txt`), bootstrap aborts here with an opaque "sed: cannot open" error. The preceding docker group / package install steps complete, but the data dir and keyring agent never get set up.
**Found in:** Pass 3 — Failure modes

### `ln -sf data` silently mis-handles an existing `data/` directory
**Location:** `bootstrap.sh:70`
**Severity:** significant
**Evidence:** `ln -sf "$DATA_DIR" "$REPO_DIR/data"` with `-f` will overwrite a regular file, but with an existing *directory* named `data`, GNU `ln` creates `./data/data -> /srv/geographica/data` (symlink *inside* the dir). A user who already followed README manual step 2 (`ln -s /srv/geographica/data data`) and then re-runs bootstrap ends up with a buried symlink. Docker-compose bind mounts resolve `./data` to the empty regular directory and services start with no content.
**Impact:** Partially-set-up users who re-run bootstrap get a confusing mount layout. Nominatim can't find `region.osm.pbf`.
**Found in:** Pass 3 — Failure modes

### "Next step:" printed twice in bootstrap final message
**Location:** `bootstrap.sh:90-97`
**Severity:** minor
**Evidence:** Lines 90 (`echo "After reboot, run:"`) and 97 (`echo "Next step:"`) both run when `NEEDS_REBOOT=1`. The else branch at line 94 also prints `Next step:`. So reboot case prints "After reboot, run: / / Next step: / / ./setup.sh" — harmless but looks sloppy.
**Impact:** Cosmetic.
**Found in:** Pass 3 — Failure modes

### Wizard falsely advertises "Existing .env — values pre-filled"
**Location:** `setup/main.py:184` + `setup/static/setup.js:263-265`
**Severity:** minor
**Evidence:** `/api/system` returns `existing_env: True` when `.env` exists, and the JS sets `host-ip-hint` to "Existing .env found - values pre-filled". But nothing actually parses `.env` and pre-fills values — all fields use the *freshly detected* host IP, default TLS mode, default data path, etc. Step 3's `saveConfig` will then clobber the existing `.env`.
**Impact:** User who previously configured `TLS_MODE=tailscale` and runs `./setup.sh` again sees "values pre-filled", accepts the defaults (now `http`), and loses their TLS setup. No warning, no diff.
**Found in:** Pass 3 — Failure modes

### `/api/config` clobbers manual `.env` customizations (STT_BACKEND, TLS_CERT_DIR, etc.)
**Location:** `setup/main.py:298`; `setup/config.py:323-365`
**Severity:** significant
**Evidence:** `Path(ENV_PATH).write_text(env_content)` is a full overwrite. `generate_env` only knows about the wizard fields; anything else the user set manually (e.g., `STT_BACKEND=npu`, `TLS_CERT_DIR=/srv/geographica/tls/tailscale`) is silently lost.
**Impact:** Re-running the wizard is destructive. Users who did the manual path per README then want to tweak via wizard lose their customizations.
**Found in:** Pass 3 — Failure modes

### Tailscale TLS README workflow appends `TLS_MODE=tailscale` even if wizard wrote `TLS_MODE=http` first
**Location:** `README.md:557-559`; `setup/config.py:323-365`
**Severity:** significant
**Evidence:** The Tailscale setup steps append `TLS_MODE=tailscale` and `TLS_CERT_DIR=...` to `.env`. If a user ran the wizard first, then tries to add Tailscale by appending, they'll end up with duplicate `TLS_MODE` entries (wizard's `http` first, appended `tailscale` second). Docker Compose env var resolution picks the *first* occurrence in a `.env` file.
**Impact:** Tailscale setup silently fails; wizard users who try the README Tailscale steps get the wrong TLS mode.
**Found in:** Pass 3 — Failure modes

### `bootstrap.sh` `chown -R /srv/geographica` can clobber bind-mounted volume perms on rerun
**Location:** `bootstrap.sh:67`
**Severity:** minor (on fresh install); significant (on rerun over existing deployment)
**Evidence:** `chown -R "$ACTUAL_USER":"$ACTUAL_USER" /srv/geographica` walks the whole tree. Bind-mounted directories used by containers (e.g., valhalla tiles owned by container UID 1000) get forced to host user ownership.
**Impact:** Re-running bootstrap on an existing deployment could break subsequent `docker compose up` for containers that run as non-root internal users. Real-world risk is moderate — the "no migration" ethos means re-running bootstrap shouldn't be common.
**Found in:** Pass 3 — Failure modes

### README mandates `docker-compose-plugin` but bootstrap installs `docker-compose` — inconsistent guidance
**Location:** `README.md:139`; `bootstrap.sh:31`
**Severity:** significant
**Evidence:** Two different setup paths advertise two different Docker Compose packages. Quick Start uses bootstrap (v1). Manual setup uses `docker-compose-plugin` (v2). Both paths converge on `docker compose up -d`, requiring v2.
**Impact:** Users following Quick Start can't run the stack. Compounds the preflight dead-end bug above.
**Found in:** Pass 3 — Failure modes

### `_run_pipeline` disk-space check passes silently if `data_path` doesn't exist
**Location:** `setup/main.py:482-497`
**Severity:** significant
**Evidence:**
```python
try:
    usage = shutil.disk_usage(config.data_path)
    ...
except OSError:
    pass
```
If `config.data_path` doesn't exist, `shutil.disk_usage` raises `FileNotFoundError`. The bare `except OSError: pass` swallows it — the pipeline proceeds as if disk space were unlimited; subsequent steps fail when trying to write to the nonexistent path.
**Impact:** Silent skip of a safety check. Pipeline fails later with a confusing FileNotFoundError.
**Found in:** Pass 3 — Failure modes

### No UI path to reset checkpoint for re-running completed steps
**Location:** `setup/main.py:468-513`; `setup/runner.py:35-38` (reset exists but unused)
**Severity:** minor
**Evidence:** On a successful run, the checkpoint marks all steps complete. Re-running the wizard will broadcast `skip` for every step and jump to Launch. The `Checkpoint.reset()` method exists but there's no API endpoint or UI button.
**Impact:** Users expanding coverage to a new bbox can't trigger a re-run via the wizard — must manually `rm .setup_checkpoint.json`.
**Found in:** Pass 3 — Failure modes

### `/api/start` TOCTOU race allows concurrent pipelines
**Location:** `setup/main.py:446-455`
**Severity:** significant
**Evidence:**
The check `if current_state["running"]` and the `asyncio.create_task(_run_pipeline(body))` spawn are separated by event-loop yield points; the actual `current_state["running"] = True` assignment happens inside `_run_pipeline` (line 464). Two concurrent POSTs both see `running=False`, both spawn tasks. Two pipelines write to the same checkpoint, race on disk-space check, and double-broadcast every event.
**Impact:** Two users (or one user double-clicking "Start Pipeline") kicks off two pipelines. Corrupted checkpoint, doubled downloads, confused UI.
**Found in:** Pass 4 — Concurrency

### `progress_buffer` mutated concurrently while iterated on WebSocket connect
**Location:** `setup/main.py:411-414` (ws_progress iterates buffer), `:437, :506` (pipeline appends)
**Severity:** significant
**Evidence:** `ws_progress` does `for event in progress_buffer:` to replay history to a newly connected client. Meanwhile, the pipeline's on_output callback and `broadcast` both call `progress_buffer.append(...)` on the same deque. Python's `deque` raises `RuntimeError: deque mutated during iteration` when this happens.
**Impact:** A WebSocket reconnect during active pipeline output crashes the `ws_progress` coroutine, drops the connection, and the client sees repeated reconnect attempts. Progress events stream to a dead socket until the client reconnects again.
**Found in:** Pass 4 — Concurrency

### `shutdown_children` does not kill subprocess grandchildren (no process group)
**Location:** `setup/runner.py:121-127` (subprocess spawn); `:150-156` (shutdown)
**Severity:** significant
**Evidence:** The async subprocess spawn is called without `preexec_fn=os.setsid` or `start_new_session=True`. When `run_command` spawns `bash scripts/generate_tls.sh`, bash in turn spawns `openssl`. On SIGTERM, `shutdown_children` only signals the direct child (bash), which exits immediately — but openssl (the grandchild) keeps running, reparented to init.
**Impact:** Wizard SIGTERM handler claims to clean up child processes, but orphaned grandchildren continue consuming CPU/disk/network after the wizard exits. A user who kills the wizard mid-download may find their disk still filling.
**Found in:** Pass 4 — Concurrency

### `broadcast` serializes WebSocket writes; slow client stalls the pipeline
**Location:** `setup/main.py:435-443`
**Severity:** minor
**Evidence:** `broadcast` awaits each `ws.send_json(event)` serially. If a mobile client has high latency, the pipeline task — which calls `broadcast` directly after each step start/done — blocks until that WebSocket ACKs. No `asyncio.gather` or timeout.
**Impact:** One slow/stale WebSocket client can stall pipeline broadcast. Pipeline subprocesses keep running, but users see frozen progress.
**Found in:** Pass 4 — Concurrency

### `INACTIVITY_TIMEOUT` defined but never enforced — wizard runs forever
**Location:** `setup/main.py:74, 84, 110-111, 499, 502-503`
**Severity:** minor
**Evidence:** `INACTIVITY_TIMEOUT = 30 * 60` is set and `_last_activity` is touched in four places, but no task reads the timeout. The wizard's docstring advertises it as "ephemeral" but there's no idle-shutdown mechanism.
**Impact:** A user who runs `./setup.sh`, alt-tabs, and walks away leaves port 8099 listening forever. Minor security surface, not a functional bug.
**Found in:** Pass 4 — Concurrency

### `current_state` mutated without lock from pipeline task and read from `/api/status` handler
**Location:** `setup/main.py:80, 373-375, 464-475`
**Severity:** minor
**Evidence:** `current_state` is a plain dict mutated from the pipeline task and read from the status handler. CPython's GIL protects individual dict operations, but a client reading `/api/status` mid-update can observe a partial state (e.g., `step="osm_download"` + `progress_pct=58%` intended for a later step).
**Impact:** Visual glitches in the UI status display. Very minor.
**Found in:** Pass 4 — Concurrency

### `/api/fix-dependency` uses `sudo apt install` but wizard has no TTY for password prompt
**Location:** `setup/main.py:39-49` (FIX_REGISTRY)
**Severity:** significant
**Evidence:** Every command in `FIX_REGISTRY` begins with `sudo`. The wizard is launched via `./setup.sh` as a regular user (no sudo). The async subprocess has stdout/stderr as pipes — no TTY. `sudo` fails with "sudo: a terminal is required to read the password" unless the user has NOPASSWD configured. The error is captured in `output` but the JS only checks `data.ok` and shows a bare "Failed" button.
**Impact:** If any preflight dep is missing at setup time (bootstrap was skipped or partially ran), clicking Install is a dead end. The UI gives no hint that sudo is the issue or how to fix it. Needs either askpass integration or clearer guidance to re-run bootstrap.
**Found in:** Pass 5 — Error propagation

### Pipeline `except Exception` broadcasts error without `step` — UI drops detail
**Location:** `setup/main.py:515-517`; `setup/static/setup.js:740-752`
**Severity:** significant
**Evidence:**
```python
except Exception as e:
    current_state["step"] = "error"
    await broadcast({"type": "error", "message": str(e)})
```
No `"step"` field. The JS handler at line 740-748 falls into the `else` branch and calls `appendLog('[ERROR] ...')`. The log viewer is hidden by default. So a pipeline crash shows no visible error unless the user clicks "Show log".
**Impact:** Pipeline failures look like the pipeline just stopped — no indication what went wrong. User is stuck staring at a half-filled progress bar.
**Found in:** Pass 5 — Error propagation

### `/api/credentials` write failures surface as generic 500
**Location:** `setup/main.py:302-314`
**Severity:** significant
**Evidence:** No try/except around `cred_path.write_text(...)`. If `/srv/geographica/data/` is read-only (wrong ownership after bootstrap rerun) or full, FastAPI returns a generic 500. The JS `saveCredentials().catch(...)` logs to console only (line 525-527). User proceeds to Step 4 thinking credentials are saved; imagery download then fails auth.
**Impact:** Classic silent save failure. Compounds the pattern in `saveConfig`.
**Found in:** Pass 5 — Error propagation

### Subprocess stderr-only warnings indistinguishable from stdout in log viewer
**Location:** `setup/main.py:501-506`; `setup/static/setup.js:732-734`
**Severity:** minor
**Evidence:** `on_output(source, data)` gets `source="stdout"` or `"stderr"`, and includes that in the event — but the JS strips it and only appends `event.text`. Errors from subprocesses intermingle with progress output in the log, with no visual distinction.
**Impact:** Hard to find real errors in a wall of tqdm progress output. Not load-bearing but adds friction when debugging.
**Found in:** Pass 5 — Error propagation

### `/api/tls/scan` silently swallows openssl errors
**Location:** `setup/main.py:347-368`
**Severity:** minor
**Evidence:** The outer `try/except Exception: continue` swallows any error per cert. If `openssl` is not installed, every attempted cert parse raises FileNotFoundError and the loop just continues. The endpoint returns `{"certs": []}` — indistinguishable from "no certs on disk." The JS hints "No certificates found."
**Impact:** User who chose "Existing certificate" sees an empty list with no hint that openssl isn't installed.
**Found in:** Pass 5 — Error propagation

### `detect_host_ip` silently returns `0.0.0.0` on detection failure
**Location:** `setup/config.py:160-185`
**Severity:** minor
**Evidence:** On any failure, returns `"0.0.0.0"`. The JS writes this into the host-ip input and doesn't flag it as invalid. `saveConfig` writes `HOST_IP=0.0.0.0` to `.env`. The completion link becomes `http://0.0.0.0:8093` — not reachable from a browser.
**Impact:** User sees `0.0.0.0` pre-filled, doesn't realize detection failed, continues; the final "Open Geographica" link is dead. The error-ish output at 230 in setup.js treats `0.0.0.0` as a successful detection.
**Found in:** Pass 5 — Error propagation

### `host_ip` accepted without format validation
**Location:** `setup/main.py:284-299`; `setup/static/setup.js:156-164`
**Severity:** minor
**Evidence:** `post_config` does `validate_bbox` but not `validate_host_ip`. The JS only checks non-empty. A user who types `my-pi.local` (valid mDNS) or `192.168.1` (invalid) both pass.
**Impact:** Bad values silently land in `.env` → nginx config → confusing 500s later.
**Found in:** Pass 5 — Error propagation

### Pipeline task crash doesn't surface to UI's health polling
**Location:** `setup/main.py:518-519`
**Severity:** minor
**Evidence:** On unhandled exception, `finally: current_state["running"] = False`. The UI has no way to tell "pipeline crashed" vs "pipeline finished." The only signal is whether `pipeline_done` was broadcast. If WebSocket is disconnected during the crash, the client never sees the error event and hangs on "Running...".
**Impact:** Browser UI can appear stuck indefinitely if network blipped at the wrong moment.
**Found in:** Pass 5 — Error propagation

### README Troubleshooting mentions `docker-compose-plugin` / `memory limits` but Quick Start never runs cgroup check
**Location:** `README.md:163-169`, `:643-648`; `bootstrap.sh` handles cgroup but not the verify-then-rerun flow
**Severity:** minor
**Evidence:** README Manual step includes `docker info 2>&1 | grep "memory limit"` verification. The wizard's preflight checks version strings of the binaries but does NOT verify that cgroup memory support is enabled. On a Pi that bootstrapped but didn't reboot, memory limits are silent no-ops. The user hits OOM issues later with no wizard signal.
**Impact:** Users who skip or forget the bootstrap-prompted reboot see random container kills during the pipeline. Preflight could `docker info` and flag this.
**Found in:** Pass 5 — Error propagation

### README companion URL also has `cdzucker` typo
**Location:** `README.md:576`
**Severity:** minor
**Evidence:** Line 576 references `https://github.com/cdzucker/geographica-companion` — same typo as the two known regressions on lines 110 and 185. Presumably the GitHub owner is `cameronzucker`.
**Impact:** Clicking the companion link gives a 404.
**Found in:** Pass 5 — Error propagation

### README line 588 hardcodes `~/Code/geographica` specific to developer's environment
**Location:** `README.md:588`
**Severity:** minor
**Evidence:** `ssh user@pi-ip "cd ~/Code/geographica && ..."` — the home-directory path `~/Code/geographica` matches Cameron's dev Pi layout, not the `~/geographica` path advised by `bootstrap.sh:24` (`git clone https://github.com/cdzucker/geographica.git ~/geographica`).
**Impact:** User who followed the Quick Start's clone path and then follows the companion instructions gets "directory not found." Trivial fix, easy to miss.
**Found in:** Pass 5 — Error propagation

### Planetiler image tag drifts: README pins `0.10.2`, wizard uses `latest`
**Location:** `README.md:266`; `setup/runner.py:61`
**Severity:** significant
**Evidence:** README uses `ghcr.io/onthegomap/planetiler:0.10.2`. `setup/runner.py:planetiler_cmd` uses `ghcr.io/onthegomap/planetiler:latest`. Image tag `latest` is a moving target; if upstream makes a breaking change, the wizard picks it up but manual users stay on 0.10.2. Reproducibility is broken between the two install paths.
**Impact:** Wizard-based installs may silently break at upstream's next release. Even worse, the wizard install differs from the well-tested manual install.
**Found in:** Pass 5 — Error propagation

### `config.base_imagery_zoom` slider value never sent to backend
**Location:** `setup/static/setup.js:32, 182, 951`; `setup/main.py:155-159` (StartRequest)
**Severity:** significant
**Evidence:** The Step 2 UI includes a zoom slider (10-17) for base imagery. JS stores the value in `config.base_imagery_zoom`. But `/api/start` accepts only `{bbox, layers, data_path}` and StartRequest has no `zoom` field. The user's zoom choice is silently discarded.
**Impact:** User picks z17 expecting high-resolution imagery; pipeline runs with whatever default the imagery script uses (often z14). Wasted decision, silent divergence from user intent.
**Found in:** Pass 5 — Error propagation

### `validate_path` symlink check is dead code (already resolved)
**Location:** `setup/config.py:294-299`
**Severity:** minor
**Evidence:** The symlink check walks `Path(resolved)` — but `Path.resolve()` follows symlinks, so `resolved` cannot contain any symlinks. The loop can never find one. The check is a no-op masquerading as a security control.
**Impact:** Falsely advertises symlink rejection. If the security rationale was to prevent writes through symlinks (e.g., user-writable symlink pointing into a dangerous location), that protection does not exist.
**Found in:** Pass 5 — Error propagation

### Old `docker-compose v1` in FIX_REGISTRY, wizard can never actually fix Docker Compose v2
**Location:** `setup/main.py:41`
**Severity:** significant
**Evidence:** `FIX_REGISTRY["docker-compose"] = ["sudo", "apt", "install", "-y", "docker-compose"]` — installs v1, not the plugin. Preflight key `"docker-compose"` maps to the v2 subcommand check. So when preflight fails "docker-compose" (no v2 plugin), clicking Install runs apt to install v1 — which doesn't provide `docker compose` subcommand. Preflight still fails. Infinite loop.
**Impact:** Beta tester whose Pi doesn't have the plugin has no way to fix it via the wizard.
**Found in:** Pass 5 — Error propagation

### `FIX_REGISTRY` uses `docker.io` package — wrong on Debian Bookworm/Trixie for modern Docker
**Location:** `setup/main.py:40`; `bootstrap.sh:31`
**Severity:** minor
**Evidence:** `docker.io` is Debian's older Docker package. Official Docker CE (from docker.com's repo) is the recommended path for current releases. Installing `docker.io` may work but conflicts with Docker-provided CE repo. The README doesn't call out which to use.
**Impact:** Users who already added Docker's official apt repo see apt conflicts when bootstrap runs.
**Found in:** Pass 5 — Error propagation

### README port-verification block mixes 8093 (via nginx) and 8094 (direct) inconsistently
**Location:** `README.md:466-484`
**Severity:** minor
**Evidence:** Health checks use `curl -s http://localhost:8090/health` (direct tileserver), `:8092/search` (direct nominatim), `:8094/route` (direct valhalla), `:8096/search` (direct search) — then `http://localhost:8093/stt/health` (via nginx proxy).
**Impact:** User following README literally checks STT through nginx (which might be down) while checking Valhalla directly. If nginx is broken but other services are fine, STT verification appears to fail in a confusing way.
**Found in:** Pass 5 — Error propagation

### `detect_storage` lists mounts but JS assumes each gets a writable `${path}/geographica/data` subdir
**Location:** `setup/static/setup.js:244`; `setup/config.py:203-250`
**Severity:** minor
**Evidence:**
```js
var path = s.path === '/' ? '/srv/geographica/data' : s.path + '/geographica/data';
```
For a detected mount like `/boot` (small, read-only-ish), the JS offers `/boot/geographica/data` as a valid-looking option. `validate_path`'s ALLOWLIST (`/srv, /mnt, /media, /home`) excludes `/boot`, so the path would be rejected — but the UI still shows it in the dropdown. When the user picks it, no immediate error is shown (Step 1 doesn't call validate-path).
**Impact:** User picks a mount that's actually invalid per the allowlist; discovers the problem much later or silently falls through to Docker using the default path.
**Found in:** Pass 5 — Error propagation

### Wizard writes `credentials.json` but keyring migration only scans `.credentials.json`
**Location:** `setup/main.py:65, 311-313`; `services/keyring-agent/agent.py:32-33, 165`
**Severity:** significant
**Evidence:** `CREDENTIALS_PATH = "/srv/geographica/data/credentials.json"` (no leading dot). Keyring agent migration paths: `Path("/srv/geographica/data/.credentials.json")` and `Path("/data/.credentials.json")` (both have the leading dot). Beyond the name mismatch, migration runs once at agent startup (`serve()` line ~191), and the agent is started by `bootstrap.sh:79` **before** the wizard ever runs.
**Impact:** Credentials entered through the wizard remain plaintext on disk forever — the v1.0.0 "credentials stored in GNOME Keyring" promise is broken for wizard users. Pipeline scripts that expect credentials via tmpfs will also fail to find them.
**Found in:** Pass 5 — Error propagation (cross-layer)

### Wizard writes credentials with default umask (0644), not 0600
**Location:** `setup/main.py:311-313`
**Severity:** significant
**Evidence:** `cred_path.write_text(json.dumps(cred_data, indent=2))` uses the process umask. On Raspberry Pi OS default umask 022, this yields mode 0644 (world-readable). The admin-panel credential handler, per design docs, explicitly chmods 0600. The wizard does not.
**Impact:** Any local user on the Pi (or anyone with SSH login) can read M2M and Copernicus API secrets. Violates the security posture of the keyring work.
**Found in:** Pass 5 — Error propagation (cross-layer)

### Wizard never invokes TLS generation script or verifies cert presence before launch
**Location:** `setup/main.py:525-579` (post_launch flow)
**Severity:** significant
**Evidence:** `/api/launch` runs `docker compose up -d` without checking whether `${TLS_CERT_DIR}/cert.pem` exists. If `TLS_MODE=self-signed` and no cert was generated (see earlier bug), nginx fails its healthcheck during launch. The health polling then shows `frontend` as unhealthy, with no indication that the root cause is a missing cert.
**Impact:** Doubly-broken TLS flow: Step 1 says "a cert will be generated" (false), and Step 5 launches without verifying one exists (false-positive success).
**Found in:** Pass 5 — Error propagation

### `fixDependency` after success re-runs `runPreflightChecks` but preserves old error UI
**Location:** `setup/static/setup.js:604-605`
**Severity:** minor
**Evidence:** `setTimeout(runPreflightChecks, 500)` runs after install succeeds — good. But `runPreflightChecks` clears the list (`list.textContent = ''`) and re-renders. So the button the user clicked gets replaced with a fresh element. Since the user might have multiple missing deps, they'd expect all Install buttons to persist; instead only one re-renders at a time. Minor UX.
**Impact:** Stuttery UX when installing multiple missing deps in sequence.
**Found in:** Pass 5 — Error propagation

### `post_credentials` writes empty-string fields (doesn't skip blank inputs)
**Location:** `setup/main.py:302-314`; `setup/static/setup.js:511-528`
**Severity:** minor
**Evidence:** `saveCredentials` checks if ALL four fields are blank (line 518) and skips the call. But if ONE is filled, the other three are written as empty strings. Downstream code that checks `if creds["m2m_username"]:` treats empty string as false (OK), but `if "m2m_username" in creds:` sees True. Mixed semantics.
**Impact:** Flaky credential checks downstream. A user who only configured Copernicus may see M2M-required errors.
**Found in:** Pass 5 — Error propagation

### Bootstrap final message tells user to log out/back in, but `setup.sh` aborts with terse message
**Location:** `bootstrap.sh:82-108`; `setup.sh:6-11`
**Severity:** minor
**Evidence:** `bootstrap.sh` doesn't print a log-out instruction — the only hint the user gets is in the README Quick Start ("Log out and back in so the docker group takes effect"). If the user misses that and runs `./setup.sh`, they get:
```
Docker is not accessible. You may need to:
  1. Run: sudo ./bootstrap.sh
  2. Log out and back in (for docker group to take effect)
```
That's fine, but **bootstrap also prints "Bootstrap complete! Next step: ./setup.sh"** right afterward, without mentioning the log-out requirement. The sequence is: bootstrap finishes → user runs setup.sh → fails → user confused.
**Impact:** A predictable, avoidable UX papercut right at the critical "first impression" moment. Bootstrap should tell the user to log out before `./setup.sh`.
**Found in:** Pass 5 — Error propagation

## Design Concerns

### Two parallel source-of-truth paths (Quick Start wizard vs Manual setup) diverge
`.env.example` is the canonical template but the wizard's `generate_env` writes a subset of that template; neither is a strict superset of the other. The Quick Start and Manual paths install *different* Docker Compose variants (`docker-compose` vs `docker-compose-plugin`), pin Planetiler to *different* versions (`latest` vs `0.10.2`), and lead to different `.env` contents. There is no test that exercises the wizard end-to-end and verifies Docker Compose actually boots. Every edit to one path risks breaking the other silently.

### Wizard assumes "sudo works without password" across every fix-dependency path
The entire FIX_REGISTRY is `sudo apt install -y ...` — but the wizard runs as a plain user. The architectural answer is either (a) require NOPASSWD sudo for a narrow set of commands (dangerous), (b) have the wizard print "please run `sudo apt install ...`" instead of pretending to install, or (c) have bootstrap handle all installs and the wizard only verify. Today it does none of the above cleanly.

### Error propagation to frontend is best-effort only
`saveConfig`, `saveCredentials`, `loadPresets`, `onTlsModeChange` all silently swallow fetch errors (to console or nothing). There is no global error toast / banner. A user's first indication that Step 1→3 saves are broken is an unrelated pipeline failure in Step 4. A single shared `showError(msg)` helper wired into every .catch branch would eliminate ~7 distinct bugs.

### Pipeline loop's skeleton implementation mixes "real" with "not-yet-real"
The stubbed-out command execution (known issue) coexists with carefully-written disk-space checks, checkpoint management, and error broadcasting. A reader can't tell at a glance which parts work and which don't. Comments like `# TODO: run the command` would mitigate this.

### Checkpoint is not atomic; no schema version; no reset UI
`_persist()` writes non-atomically, `__init__` has no try/except, there's no versioning of the JSON schema, and `reset()` is unused. For a resume-after-failure feature this is fragile. A bad checkpoint bricks future runs.

### WebSocket broadcasts inherit pipeline flow control
`broadcast` awaits per-socket writes serially from inside the pipeline task. Any slow client is a pipeline stall. Should be `asyncio.gather(..., return_exceptions=True)` with per-socket timeouts.

### Wizard should enforce "one-shot" semantics
`INACTIVITY_TIMEOUT` is defined but unused. If the wizard is meant to be ephemeral, it should enforce that. If it's meant to be a persistent admin panel, it shouldn't have a "CSRF token generated once at startup" design (regenerate on each run).

### Port 443 HTTPS completion link assumes DNS/cert setup users never declared
`setup.js:885` builds `https://<host>:443` for any TLS mode other than `http`. But "self-signed" and "external proxy" need different URLs (IP-with-cert-warning vs hostname.ts.net). The link target should be mode-specific.

### `/api/health` and `/api/status` expose different shapes of the same underlying idea
`/api/status` returns `current_state` (wizard's progress view). `/api/health` returns Docker Compose services. They overlap conceptually at "is the thing ready?" but use different vocabularies. Either consolidate or document the distinction clearly.

### No LXD/CI harness exercises the wizard path end-to-end
The `lxd-validation` skill tests the README manual path. There's no equivalent for the wizard. All the wizard-specific bugs above could be caught by an automated flow that: creates LXD container, runs `./bootstrap.sh`, spawns the wizard, drives it via Playwright, asserts `docker compose ps` shows healthy services.
