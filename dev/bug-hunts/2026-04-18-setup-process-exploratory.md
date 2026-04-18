# Bug Hunt Report — Setup Process Exploratory

## Scope
Explored the Geographica beta-tester setup flow end-to-end, treating the pipeline
orchestrator `setup/main.py:_run_pipeline` and the credentials/TLS plumbing as
the highest-risk surfaces. Files read deeply:

- `README.md` (full, 833 lines)
- `bootstrap.sh` (full)
- `setup.sh` (full)
- `setup/main.py` (full) — pipeline orchestrator, CSRF middleware, API endpoints
- `setup/config.py` (full) — path/bbox validation, env generation
- `setup/runner.py` (full) — subprocess runner + command builders
- `setup/static/index.html` (full) — wizard UI
- `setup/static/setup.js` (full) — wizard frontend
- `docker-compose.yml` (full) — to cross-check what the wizard launches
- `tests/test_setup_main.py`, `tests/test_setup_config.py` — to understand the
  contracts currently asserted
- `services/keyring-agent/agent.py` — to check credential pipeline after wizard
- `nginx/entrypoint.sh` — to check TLS mode handshake
- `scripts/acquire_imagery.py`, `scripts/build_public_lands.py`,
  `scripts/download_elevation.py`, `scripts/requirements.txt` — to see what the
  pipeline step names map to

Known regressions from the user's prompt are NOT re-reported (README cdzucker
lines 111/185; data-path dropdown at Step 1; `_run_pipeline` no-op). Those are
already in flight.

---

## Bugs

### TLS mode values the wizard writes are unknown to nginx — self-signed silently becomes HTTP
**Location:** `setup/static/index.html:42-48` and `setup/static/setup.js:22-23,157,500-509` vs `nginx/entrypoint.sh:2-54`
**Severity:** critical
**Evidence:** The wizard `<select id="tls-mode">` offers four values: `http`,
`self-signed`, `existing`, `external`. The frontend passes the raw value straight
to `/api/config`, and `generate_env()` writes `TLS_MODE=self-signed` (or
`existing`, or `external`) into `.env`. The nginx `entrypoint.sh` only branches
on `https` and `tailscale`; everything else (including `self-signed`,
`existing`, `external`) falls into the `else` clause that installs the empty
TLS include and runs plain HTTP on :8093. In addition, `.env.example` documents a
third spelling — `http | tls-published | tls-standard` — that matches nothing
on either side. No cert generation is ever triggered (`POST /api/tls/generate`
endpoint exists but setup.js never calls it).
**Impact:** A user who picks "Self-signed certificate" in the wizard gets a
working HTTP-only stack with NO certificate and NO warning. Browser-Geolocation
and STT features that require a secure context silently break. Worse, port 443
is still exposed by the frontend container binding with no TLS handler, so the
user also doesn't notice because http://pi-ip:8093 just works. Completely
defeats the wizard's TLS step.

### Credentials field-name mismatch: wizard writes `copernicus_client_id`/`_secret`, the rest of the stack expects `copernicus_username`/`_password`
**Location:** `setup/main.py:136-141,302-314` vs `services/keyring-agent/agent.py:24-28` and `services/search/main.py:79-82,1040-1054`
**Severity:** critical
**Evidence:** The wizard's `CredentialsRequest` model uses OAuth2 naming
(`copernicus_client_id`, `copernicus_client_secret`) and writes them verbatim
to `/srv/geographica/data/credentials.json`. The keyring agent's
`CREDENTIAL_KEYS = {"copernicus": ["username", "password"], ...}` and the
admin-panel `CredentialRequest` use `copernicus_username` /
`copernicus_password`. The keyring agent's `_migrate_json_credentials()`
function only looks at `.credentials.json` (dot-prefix) at
`/srv/geographica/data/.credentials.json` or `/data/.credentials.json`
(agent.py:31-34). The wizard writes to `credentials.json` (no dot prefix), so
the migration step won't even pick it up on daemon restart.
**Impact:** (a) Copernicus credentials entered in the wizard can never be used
by any downstream pipeline — the wrong keys are stored. (b) The whole
`credentials.json` file is orphaned — agent can't see it, admin panel doesn't
read it, pipeline launcher doesn't read it. (c) The promise in README line 36
("credentials stored in GNOME Keyring ... no plaintext credential files") is
broken: the wizard re-introduces a plaintext file at `/srv/geographica/data/credentials.json`.

### `_run_pipeline` silently no-ops — Downloads step completes in seconds with no work done
**Location:** `setup/main.py:458-519` (already known; amplifying details below)
**Severity:** critical
**Evidence:** The step loop defines `on_output` inside the loop body but never
passes it to `run_command` (runner.py:103) — no subprocess is ever spawned.
Each step just broadcasts `step_start`, marks itself complete in the checkpoint,
and broadcasts `step_done`. The frontend (`setup.js:754-760`) then treats
`pipeline_done` as success and auto-advances to Step 5 (Launch).
**Impact:** User clicks "Start Pipeline," sees 13 steps zip by in under a
second, the wizard auto-advances and says "Setup Complete". `docker compose up -d`
on Step 5 succeeds (services start with empty data), but the app is totally
unusable — no tiles, no geocoder, no routing. No error is shown at any point.

### Pipeline never builds the on-demand `pipeline` service — admin-panel downloads will fail
**Location:** `setup/main.py:560-564` and `docker-compose.yml:207-224`
**Severity:** significant
**Evidence:** The final launch step runs `docker compose -f docker-compose.yml up -d`
with no `--profile pipeline`. The `pipeline` service in docker-compose.yml is
gated behind `profiles: ["pipeline"]` so it is never built by the wizard.
README §11 explicitly says `docker compose --profile pipeline build` must run.
Nowhere in the wizard or bootstrap does that happen.
**Impact:** Admin-panel imagery/elevation/OSM-POI pipelines (which call
`docker compose run pipeline ...`) will fail at first use with "image not
found" because the pipeline image was never built.

### `SCRIPTS_HOST_PATH` default is hardcoded to Cameron's dev path
**Location:** `docker-compose.yml:125`
**Severity:** significant
**Evidence:** `SCRIPTS_HOST_PATH: "${SCRIPTS_HOST_PATH:-/home/administrator/Code/geographica/scripts}"`.
The wizard's `generate_env()` (config.py:323-365) never writes `SCRIPTS_HOST_PATH`
to `.env`, and neither does `bootstrap.sh`. Any user whose repo lives outside
`/home/administrator/Code/geographica/` (i.e. essentially every user except
Cameron) will have the search container advertising a bogus host path to the
Docker socket when launching pipeline containers.
**Impact:** `services/search/main.py:1368,1792` reads `SCRIPTS_HOST_PATH` to
mount the scripts directory into the pipeline container. The bind mount will
silently fail (or mount an empty/absent directory), so every admin-panel
pipeline run will fail with import errors inside the pipeline container.
`DATA_HOST_PATH` has the same default-hardcoding problem but `/srv/geographica/data`
is at least the same path bootstrap.sh creates.

### `validate_path` prefix matching passes `/srvattacker`, `/homeroot`, `/mntfoo`
**Location:** `setup/config.py:286-292`
**Severity:** significant
**Evidence:** `any(resolved.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES)`
with prefixes `("/srv", "/mnt", "/media", "/home")`. String `startswith` doesn't
enforce a path boundary — `/srvattacker/malicious`.startswith(`/srv`) is True.
Verified empirically:
```
>>> validate_path('/srvattacker/malicious')
{'valid': True, 'free_gb': 387.7, 'total_gb': 879.6}
>>> validate_path('/srv')    # root of allowed prefix — also allowed
{'valid': True, ...}
>>> validate_path('/home')   # root of all homes — also allowed
{'valid': True, ...}
```
The docstring claims "Path must start with an allowed prefix (ALLOWLIST)" but the
check doesn't match what a reasonable reader would expect. Since the endpoint
calls `mkdir(parents=True, exist_ok=True)`, an attacker who gains POST + CSRF
could `mkdir /srvfoo/anything` or `mkdir /homesqueezedrive/anything` on disk.
**Impact:** Weakens the security claim of the allowlist. The practical attack
surface is limited (still needs CSRF token, still runs as unprivileged user,
still bounded to `/srv*`/`/mnt*`/`/media*`/`/home*` prefixes), but it violates
what the tests in test_setup_config.py assume.

### Setup wizard claims "Existing .env found — values pre-filled" but never reads the .env
**Location:** `setup/static/setup.js:263-265` and `setup/main.py:175-185`
**Severity:** significant
**Evidence:** `get_system()` returns `"existing_env": os.path.exists(ENV_PATH)`
and setup.js shows "Existing .env found — values pre-filled" when true. But
nothing parses the existing .env — `host_ip` comes from `detect_host_ip()` (fresh
`ip route get 1` call), `tls_mode` defaults to `'http'` (setup.js:23),
`bbox`/`data_path` default to blank/default. When the user clicks Next, the
unchanged defaults overwrite the existing `.env` completely.
**Impact:** A user re-running the wizard to fix one setting loses all prior
configuration (BBOX, TLS_MODE, custom DATA_PATH, postgres tunings in
.env.example, etc.). The UI message is actively misleading.

### `saveConfig()` error-swallowing — user never learns .env write failed
**Location:** `setup/static/setup.js:500-509` (and `saveCredentials` at 511-528)
**Severity:** significant
**Evidence:** Both functions `.catch(err => console.error(...))` with no UI
surface. `/api/config` returns 400 on an invalid bbox (e.g. user got to Step 3
with a syntactically-bad bbox, or all-skipped path without a bbox). The wizard
then advances to the next step as if success. Also, `saveConfig` is fire-and-
forget — `nextStep()` immediately continues to `showStep(currentStep + 1)`
without awaiting completion. On Step 2 skip-all, `saveConfig(); showStep(5)`
starts the Launch step before the `.env` write finishes (race, but minor).
**Impact:** Silent configuration-not-saved. User proceeds to Launch thinking
everything is persisted. Launch eventually reads `.env` but finds stale
values from a prior run (or none). Combined with the "existing .env" bug above,
this makes recovery from config mistakes really painful.

### Disk-critically-low path still reports `pipeline_done` and advances to Launch
**Location:** `setup/main.py:485-513`
**Severity:** significant
**Evidence:** If `free_gb < 5`, broadcast `error` and `break` out of the
for-loop. Then control falls through to lines 511-513:
```python
current_state["step"] = "done"
current_state["progress_pct"] = 100
await broadcast({"type": "pipeline_done"})
```
The frontend handles `pipeline_done` (setup.js:754-760) by showing 100% and
auto-advancing to Step 5. The earlier `error` event did set
`current_state["step"] = "error"` is NEVER set in this path — only
line 515-516 in the `except Exception` branch does that.
**Impact:** Disk-error condition presents as success. User advances to Launch
and tries to start services with no data and no disk. At best they notice
services crashing; at worst they think setup worked.

### `sed -i` on `/boot/firmware/cmdline.txt` is silent no-op on older Pi OS where file lives at `/boot/cmdline.txt`
**Location:** `bootstrap.sh:51-55`
**Severity:** significant
**Evidence:** `grep -q cgroup_enable=memory /boot/firmware/cmdline.txt 2>/dev/null`
swallows errors including "file not found". On Raspberry Pi OS Bullseye and
earlier, cmdline is at `/boot/cmdline.txt`; on Bookworm+ it's at
`/boot/firmware/cmdline.txt`. If the Bullseye path is used, grep silently
fails ("no match"), control enters the if-body, `sed -i` fails silently (file
not found, suppressed by `2>/dev/null`... actually sed error is NOT
suppressed here), but `NEEDS_REBOOT=1` gets set anyway. Worse, with `set -e`
active on line 2 of the script, a failing `sed` without redirection exits
bootstrap.sh abruptly mid-way, and the keyring service step never runs.
**Impact:** On older Pi OS, bootstrap aborts partway through (after apt
installs, before keyring setup). The user sees a cryptic sed error and an
incomplete install — no data directory creation, no keyring agent. README §"OS
supported" claims Bookworm works; it does, but Bullseye and earlier break
hard.

### Preflight missing several deps the pipeline/scripts actually need
**Location:** `setup/main.py:52-62`
**Severity:** significant
**Evidence:** PREFLIGHT_CHECKS verifies: docker, docker-compose (via
`docker compose version`), python3, gdal-bin, osmium-tool, gpsd, wget, curl,
git. It does NOT check:
- **tippecanoe** — required by `scripts/build_public_lands.py:169` for the
  `public_lands` step listed in PIPELINE_STEPS:431. README §7c explicitly notes
  ARM64 users must build it from source. Bootstrap doesn't install it.
- **Java JRE** — required by Planetiler (the `planetiler_pull`/`planetiler_build`
  steps at PIPELINE_STEPS:429-430 run Planetiler via docker, so Docker handles
  Java _inside_ the container. This one is probably fine).
- **python3-pip** / **python3-venv** — needed to install `scripts/requirements.txt`
  (rasterio, shapely, numpy, scipy, aiohttp, aiosqlite, tqdm). FIX_REGISTRY has
  `python3-venv` but PREFLIGHT_CHECKS doesn't check for it. Bootstrap apt-installs
  both, so this is OK if bootstrap ran successfully.
- **rasterio / shapely / numpy / scipy Python packages** — setup wizard never
  runs `pip install -r scripts/requirements.txt`. Without these, scripts like
  build_osm_pois.py will ImportError at runtime. README §7b says "Requires
  osmium and shapely" but the wizard doesn't install shapely.
- **GNOME keyring agent running** — no check that
  `systemctl is-active geographica-keyring` returns active. Without the agent,
  credentials the admin panel saves never reach the pipeline.
- **cgroup memory support** — no preflight check for `docker info | grep "memory limit"`.
  Silently means all docker-compose memory limits are ignored.
**Impact:** Wizard declares green-checkmark on all deps but the pipeline will
fail at runtime when it tries to invoke tippecanoe or import rasterio. Given
the `_run_pipeline` no-op bug, this is currently masked — but fixing that bug
will expose these gaps.

### FIX_REGISTRY installs `docker-compose` from Debian — wrong version on Bookworm
**Location:** `setup/main.py:40-49` and `bootstrap.sh:31`
**Severity:** moderate
**Evidence:** FIX_REGISTRY maps `docker-compose` → `apt install -y docker-compose`.
On Debian Bookworm (stable), the `docker-compose` package is v1.29.2-ish (the
legacy Python binary that only supports `docker-compose` with a dash).
PREFLIGHT_CHECKS asserts `docker compose version` (no dash). README line 139
tells users to install `docker-compose-plugin` — but that package is only in
Docker's own apt repository, not the base Debian repo. Neither bootstrap.sh nor
FIX_REGISTRY adds Docker's repo.
**Impact:** On Bookworm, bootstrap.sh apt-installs v1 `docker-compose`,
PREFLIGHT_CHECKS fails `docker compose version`, user clicks "Install" on the
preflight UI, FIX_REGISTRY re-installs the same v1 package, preflight still
fails. No way to proceed. On Trixie this happens to work because Trixie's
`docker-compose` package is v2.

### Setup wizard exposes `0.0.0.0` binding when run via `python3 -m setup.main`
**Location:** `setup/main.py:596-598`
**Severity:** moderate
**Evidence:** `uvicorn.run(app, host="0.0.0.0", port=8099)` when run as
`__main__`. setup.sh correctly binds 127.0.0.1, but the docstring, plan docs,
and user muscle memory might tell them to run `python3 -m setup.main`.
**Impact:** Any user on the same LAN (or AREDN mesh) could hit the wizard's
API. CSRF token generation is `secrets.token_hex(32)` so brute force is infeasible,
but `GET /api/system` and `GET /api/preflight` are unauthenticated and disclose
host IP, RAM, storage devices/mounts, and installed package versions — useful
recon. More concerning: because the wizard writes .env and runs `apt install`
(via fix-dependency) and `docker compose up -d` (via launch), a CSRF token
leak would be catastrophic. The token is embedded in index.html served on the
same interface, so anyone on the LAN who can GET `/` at the right moment has
the token. Binding 127.0.0.1 is the only real defense.

### Bootstrap.sh still references `cdzucker` in the world-writable-repo error
**Location:** `bootstrap.sh:24`
**Severity:** minor
**Evidence:** `git clone https://github.com/cdzucker/geographica.git ~/geographica`
in the warning message. Already fixed on lines 111 and 185 of README.md per the
user's prompt, but this third instance in bootstrap.sh was missed. Plus README
line 576 also still has `cdzucker/geographica-companion` unfixed.
**Impact:** Copy-pasting the suggested command fails with 404. Cosmetic on a
rare error path, but demonstrates incomplete search-and-replace during the
prior fix.

### "Open Geographica" link defaults to `/` (the setup wizard itself) if health check never turns green
**Location:** `setup/static/index.html:276` and `setup/static/setup.js:879-886`
**Severity:** minor
**Evidence:** The anchor is hard-coded `href="/"` in HTML. setup.js only
rewrites the href when `allHealthy && services.length > 0`. If any service is
unhealthy at the moment the user clicks the link, they get booted back to the
wizard. There's no explicit "wait for healthy" gate on the button itself.
**Impact:** Confusing for a user who has opened the wizard via SSH tunnel and
expects `localhost:8099` to be the wizard URL, not the app URL. Also, for
`tls_mode === 'external'` (Tailscale), the generated href is
`https://<host_ip>` which is the wrong form — Tailscale HTTPS wants
`https://<hostname>.ts.net`, not an IP.

### Inactivity-timeout dead code (`INACTIVITY_TIMEOUT` / `_last_activity` updated but never checked)
**Location:** `setup/main.py:74-84, 110-111, 460, 499, 503`
**Severity:** minor
**Evidence:** `INACTIVITY_TIMEOUT = 30 * 60` is declared, `_last_activity` is
updated on every request and every subprocess output chunk, but no coroutine
or background task ever compares them to shut the wizard down after inactivity.
The wizard is supposed to be "ephemeral" (README / main.py docstring) but it
runs until the user kills it manually.
**Impact:** The wizard's "localhost-only, ephemeral" security posture is weaker
than the code documents. Not dangerous, but misleading.

### `Checkpoint.__init__` crashes on corrupt JSON
**Location:** `setup/runner.py:18-23`
**Severity:** minor
**Evidence:** `json.loads(self._path.read_text())` with no try/except. A
partial write from a previous crashed run (or a power loss mid-persist) leaves
invalid JSON — instantiating Checkpoint raises JSONDecodeError, which in the
`_run_pipeline` flow (main.py:462) is caught by the outer `except Exception`
and broadcast as a generic error. Recovery requires manually deleting
`.setup_checkpoint.json`.
**Impact:** Confusing user-facing error on re-run after a crash, with no UI
affordance to reset the checkpoint.

### WebSocket progress buffer drops history on long runs
**Location:** `setup/main.py:79` — `progress_buffer = deque(maxlen=100)`
**Severity:** minor
**Evidence:** A real pipeline run produces thousands of stdout/stderr chunks.
With maxlen 100, ~99% of historical output is dropped. When a user's browser
reconnects after a transient disconnect, only the last 100 events replay.
**Impact:** Users who briefly lose connection can't see what went wrong in the
middle of a step. Low priority given the `_run_pipeline` no-op but will bite
once that bug is fixed.

---

## Design Concerns

**`config.data_path` is advertised as configurable but isn't**. The wizard
exposes a dropdown for data storage path (Step 1 / Network & System), writes
`DATA_PATH=<choice>` to `.env`, and passes the choice to `/api/start`. But
docker-compose.yml does `./data:/data` bind mount, and `./data` is the
hardcoded symlink to `/srv/geographica/data` created by bootstrap.sh. Nothing
in docker-compose reads `${DATA_PATH}`. The .env variable is effectively
write-only. Any user who picks `/mnt/external/data` will have their checkpoint
file and disk-space checks run against `/mnt/external/data` while actual
pipeline output (if it ran) lands in `/srv/geographica/data`. Two paths in
play; user doesn't know.

**All credentials flows collide on the term `credentials`**. Three different
field-name conventions coexist (OAuth2 client_id/secret in setup wizard, admin
panel username/password, keyring agent type+key), plus the `.credentials.json`
vs `credentials.json` filename wrinkle, plus the README § "GNOME Keyring"
promise. Adding the missing keyring integration to the setup wizard (so
credentials go directly into the keyring) would consolidate this — and as a
bonus, eliminate the plaintext file the wizard currently drops on disk.

**CSRF token scope is whole-wizard, infinite-lifetime**. `CSRF_TOKEN = secrets.token_hex(32)`
is generated once at import and never rotated. Combined with the index.html
embedding the token, a cross-origin GET of index.html leaks the token. For a
localhost-only wizard, this is fine; but any relaxation of the 127.0.0.1 bind
turns into an un-patched CSRF vector (see `0.0.0.0` bug above).

**Multiple API endpoints are dead code**. `/api/validate-path`,
`/api/create-directory`, `/api/tls/generate`, `/api/tls/scan` are never called
from setup.js. They exist with real implementations but no UI path triggers
them. Either the frontend hasn't caught up (commit `5b55c16` reportedly
promised the path validation UI but didn't ship it), or the endpoints should
be deleted. Keeping them around makes future auditors ask "is this safe to
call?" — and the answer requires looking at the current JS, not the intent.

**PIPELINE_STEPS hardcoded, not derived from layer selections**. `_run_pipeline`
iterates all 13 PIPELINE_STEPS regardless of what the user picked in Step 2
(basemap/base_imagery/detail_imagery/elevation). The frontend sends `layers`
in `/api/start` but `_run_pipeline` ignores `body.layers`. So "Skip detail
imagery" and "Skip elevation" have no effect on the pipeline. (When the
`_run_pipeline` no-op is fixed, this will matter a lot.)
