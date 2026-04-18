# Bug Hunt Report — Setup Process (holistic)

## Scope

Read end-to-end, line by line:

- `README.md` (833 lines)
- `bootstrap.sh`, `setup.sh`, `.env.example`
- `setup/main.py`, `setup/config.py`, `setup/runner.py`
- `setup/static/index.html`, `setup/static/setup.js`
- `tests/test_setup_main.py`, `tests/test_setup_config.py`, `tests/test_setup_runner.py`
- `docker-compose.yml`, `nginx/entrypoint.sh`, `nginx/nginx.conf`
- `scripts/build_poi_index.py`, `scripts/download_elevation.py`, `scripts/acquire_imagery.py`, `scripts/build_osm_pois.py`, `scripts/build_public_lands.py`, `scripts/generate_tls.sh`
- `services/keyring-agent/agent.py`, `services/search/main.py` (host-path resolution)

Approach: I chose this scope so I could reason about the *system* rather than individual modules. The wizard is a surface layer; whether it works depends on whether it agrees with `docker-compose.yml`, `nginx/entrypoint.sh`, the pipeline scripts, and the keyring agent. The bugs below come from those layers disagreeing.

Known regressions excluded (given by caller):
1. README clone URL typo (`cdzucker` → `cameronzucker`)
2. Missing custom-storage-path frontend wiring (commit `5b55c16` promise)
3. `_run_pipeline` no-op loop

Substantial overlap is expected with the multipass hunter's report. Where overlap exists I have tried to add a holistic/contract-level framing or an additional concrete impact. Bugs listed below are those my analysis surfaces independently; I flag overlap explicitly.

## Bugs

### TLS-mode vocabulary disagrees across four files — every non-`http` choice silently falls back

**Location:**
- `setup/static/index.html:42-47` — offers `http | self-signed | existing | external`
- `setup/static/setup.js:157` — writes whatever string the `<select>` emitted into `.env`
- `setup/config.py:333` — passes it through verbatim as `TLS_MODE=...`
- `.env.example:7` — documents `http | tls-published | tls-standard`
- `nginx/entrypoint.sh:5,40,52` — only recognises `http | https | tailscale`

**Severity:** critical

**Evidence:** Four files, four different sets of legal values. The wizard can write `TLS_MODE=self-signed` or `TLS_MODE=external`; nginx's entrypoint has no case for those strings, so it falls through the `elif`/`else` chain to the `else` at line 52 and copies `tls-include-empty.conf`. The `listen 443 ssl` block is never activated. There is no warning surfaced to the user — the container starts "successfully" on port 80 only, and the Launch step reports the stack as healthy.

Separately, if a user edits `.env.example`'s documented values (`tls-published`, `tls-standard`) into `.env`, nginx also falls through to empty-TLS silently.

**Impact:** Every TLS mode the wizard offers except "HTTP (no encryption)" is dead. A user who picked "Self-signed certificate" and sees "Setup Complete" gets HTTP-only, and the "Open Geographica" link builds an `https://` URL (see next bug) that doesn't resolve. The only way to get HTTPS is to bypass the wizard entirely and follow README §HTTPS via Tailscale manually.

**Found by:** holistic vocabulary audit — tracing every `TLS_MODE` string from source to consumer.

---

### Self-signed TLS selection writes `.env` but never runs cert generation

**Location:**
- `setup/static/setup.js:296-304` (TLS change handler)
- `setup/main.py:317-331` (`/api/tls/generate` endpoint)
- No call site in `setup/static/setup.js`

**Severity:** critical (downgraded to "significant" if the prior bug is counted: the string doesn't even reach nginx correctly.)

**Evidence:** `/api/tls/generate` exists in the backend, shells out to `scripts/generate_tls.sh`, and writes certs to `/srv/geographica/tls/`. It is **never called from `setup.js`**. Grep for `tls/generate` in `setup/static/` — zero hits. When the user chooses "self-signed", the UI only sets a hint and posts the TLS mode into `/api/config`. No certs get generated, `TLS_CERT_DIR` is not written into `.env`, and `generate_tls.sh` writes to `/srv/geographica/tls/` which requires root (the script has no sudo check and would fail silently in the wizard's non-root subprocess on a fresh machine).

**Impact:** "Self-signed" is a phantom option. A beta tester who picks it and follows the wizard never gets TLS, never gets a visible error, and ends up with a dead HTTPS endpoint. Overlaps with the multipass hunter's identical finding; included here because the fix is inseparable from the TLS-vocabulary bug above.

**Found by:** orphan-endpoint audit (cross-checked every `@app.post` and `@app.get` against `api('POST'` / `api('GET'` callsites).

---

### `/api/validate-path` and `/api/create-directory` are orphans — the wizard has no custom-path UI plumbing at all

**Location:**
- `setup/main.py:200-281`
- No call site in `setup/static/setup.js`

**Severity:** minor (the *feature* being missing is the known regression; the orphaned backend is the residue)

**Evidence:** Both endpoints are wired, pass all tests, and do real ALLOWLIST + symlink + traversal validation. The frontend never POSTs to either. Grep for `validate-path` / `create-directory` in `setup/static/` — zero hits. The `<select id="data-path">` in `index.html:68-72` has only the default option hardcoded (despite the commit message claiming "custom storage path").

**Impact:** Not a runtime bug — code that's merely unused — but evidence of a half-shipped feature. If someone later adds a text-input custom-path field without re-reading the backend, they may reimplement the validation in JS and bypass the server-side checks. Overlaps with multipass.

**Found by:** orphan-endpoint audit + commit-message-vs-diff drift check.

---

### `HOST_IP` is a fully dead variable — the wizard asks for it but nothing in the deployed stack reads it

**Location:**
- Written by `setup/config.py:333` and `bootstrap.sh` (indirectly via `.env.example`)
- `nginx/nginx.conf` uses `$http_host` and `$scheme` for rewrites; never `$HOST_IP`
- `docker-compose.yml` never references `HOST_IP`
- Every `.sh`, `.conf`, `.yml` in the repo: zero reads

**Severity:** significant

**Evidence:** Grep `"HOST_IP"` across the repo, restricted to non-doc files: only `setup/config.py`, `.env.example`, tests, and docs. The nginx proxy builds absolute tile URLs from `$scheme://$http_host` (the incoming request's `Host` header), not from `HOST_IP`. The `HOST_IP` value in `.env` is purely decorative.

Secondary problem: `detect_host_ip()` (`config.py:160-185`) returns `"0.0.0.0"` when the primary IP is loopback or docker0. The UI happily writes `HOST_IP=0.0.0.0` to `.env`. Then `setup.js:886` builds `http://0.0.0.0:8093` as the "Open Geographica" link — which resolves differently per OS and usually breaks for remote clients.

**Impact:**
1. The whole Step 1 Host-IP field is asking for data the stack doesn't use. Educates users incorrectly about what matters.
2. The "Open Geographica" link on the completion page is built from this field — which means a wrongly-detected LAN IP (or `0.0.0.0` fallback) becomes a broken app link.

**Found by:** grep-for-consumer audit on every env var emitted by `generate_env`. HOST_IP has zero consumers.

---

### Credential file path is `credentials.json` but keyring migration scans only `.credentials.json` — wizard-written credentials never reach the keyring

**Location:**
- `setup/main.py:65` — `CREDENTIALS_PATH = "/srv/geographica/data/credentials.json"` (no leading dot)
- `services/keyring-agent/agent.py:31-34` — `_MIGRATION_PATHS = [Path("/srv/geographica/data/.credentials.json"), Path("/data/.credentials.json")]` (with leading dot, both variants)
- `agent.py:164-186` (`_migrate_json_credentials`) runs **only on agent startup**

**Severity:** critical

**Evidence:** The setup wizard writes to `credentials.json`. The keyring-agent migrates from `.credentials.json`. They differ by one character. Additionally, the migration loop runs once at agent startup (`serve()` line 191). The agent is started by `bootstrap.sh:79` (`systemctl start geographica-keyring`) **before** the wizard runs. So even if the paths matched, the wizard writes credentials after the agent has already scanned and given up.

The `services/search` container reads credentials through the keyring client, not from the plaintext file. So the wizard's M2M and Copernicus credentials are *never used* by the running stack. The admin panel's Settings tab, which re-enters the same credentials via the keyring API, is the only path that actually works.

**Impact:** Step 3 of the wizard is effectively decorative. Users who enter credentials believe they are set up; the first pipeline run from the admin panel fails with authentication errors because the keyring is empty. The wizard never indicates the credentials aren't being stored where the stack can find them.

Additional security concern: the wizard writes `credentials.json` with default umask (world-readable on most Pis), not `0600`. The admin-panel flow explicitly chmods `0600` per design docs; the wizard does not.

**Found by:** cross-layer trace of "where does Step 3 data end up, and who reads it." The difference between `credentials.json` and `.credentials.json` only jumps out when you look at both call sites side by side.

---

### `SCRIPTS_HOST_PATH` defaults to a Cameron-only path; the wizard never overrides it

**Location:**
- `docker-compose.yml:125` — `SCRIPTS_HOST_PATH: "${SCRIPTS_HOST_PATH:-/home/administrator/Code/geographica/scripts}"`
- `setup/config.py:generate_env` — does not emit `SCRIPTS_HOST_PATH` (or `DATA_HOST_PATH`)
- `services/search/main.py:1367-1394` — falls back to container mount introspection if env is empty

**Severity:** critical

**Evidence:** `docker-compose.yml:125` hard-codes `/home/administrator/Code/geographica/scripts` as the default for `SCRIPTS_HOST_PATH`. Any beta tester cloning into `~/geographica` or `/opt/geographica` gets this wrong default. The wizard knows where it's running (`Path(__file__).parent.parent`), but `generate_env()` never writes `SCRIPTS_HOST_PATH` or `DATA_HOST_PATH`. The mount-introspection fallback in `search/main.py` is a band-aid that only works if the search container is already running with the correct `./data` mount — which depends on the `./data` symlink pointing somewhere. On a non-default data path the fallback introspects the wrong host dir.

**Impact:** Any pipeline started from the admin panel will mount the wrong scripts directory into the pipeline container. Since scripts are mounted read-only, this might silently work on Cameron's machine (where the hardcoded default matches reality) and fail obscurely on every other machine. This explains why the wizard "works" for the original developer but fails for beta testers — a class of bug that's invisible in normal testing.

**Found by:** tracing how pipeline container gets the scripts it executes; discovered by following the `SCRIPTS_HOST_PATH` env var from consumer back to source.

---

### `generate_env()` emits RAM-profile vars that `docker-compose.yml` ignores — wizard's "8 GB profile" promise is a lie

**Location:**
- `setup/config.py:323-365` emits `NOMINATIM_MEMORY`, `VALHALLA_MEMORY`, `TILESERVER_MEMORY`, `STT_MEMORY`, `PIPELINE_MEMORY`, `PIPELINE_GDAL_CACHE`, `IMAGERY_CONCURRENCY_*`, `M2M_BATCH_SIZE`, `PLANETILER_HEAP`
- `docker-compose.yml:15,45,79,107,141,163,198,221` — memory limits are hard-coded (`memory: 1G`, `memory: 8G`, etc.)
- `docker-compose.yml:216` — `GDAL_CACHEMAX: "1024"` hard-coded
- `scripts/acquire_imagery.py:1179` — `M2M_BATCH_SIZE = 50` module-level constant, not read from env

**Severity:** significant

**Evidence:** The wizard's `RAM_PROFILE_8GB` claims `nominatim_memory: "4G"`, `tileserver_memory: "512M"`, `pipeline_memory: "1G"`, `pipeline_gdal_cache: "256"`, `m2m_batch_size: "20"`. None of these flow through to actual runtime limits. Docker compose's hard-coded `memory: 8G` for nominatim is used whether the user has 8 GB or 16 GB RAM. The pipeline runs with `GDAL_CACHEMAX=1024` on an 8 GB Pi — which the multi-week bug-hunt thread identified as a common OOM trigger.

The only profile vars that *do* flow through are the PostgreSQL `POSTGRES_SHARED_BUFFERS`, `POSTGRES_MAINTENANCE_WORK_MEM`, `POSTGRES_EFFECTIVE_CACHE_SIZE`, and `VALHALLA_THREADS`.

**Impact:** An 8-GB Pi user thinks they're getting a tuned profile. They actually get the 16-GB defaults everywhere except Postgres. OOM likelihood during pipeline runs stays high. This makes the "RAM profile" UI a placebo.

**Found by:** reverse lookup — every var that `generate_env` writes, checked against every consumer in the deployed stack.

---

### Wizard's `/api/launch` never builds the pipeline image — admin-panel pipelines fail immediately afterward

**Location:**
- `setup/main.py:560-563` — launches with `docker compose -f docker-compose.yml up -d` (no `--profile pipeline build`)
- `docker-compose.yml:207-224` — `pipeline` service has `profiles: ["pipeline"]`
- `services/search/main.py:1243-1250` — admin API `pipeline_start` raises HTTP 422 "Pipeline image not built" if `client.images.get("geographica-pipeline")` throws
- `README.md:430` explicitly says `docker compose --profile pipeline build` must be run separately

**Severity:** significant

**Evidence:** The wizard's Launch step never invokes the pipeline-profile build. The pipeline image is only built on a `docker compose --profile pipeline build`. So immediately after wizard "success," any imagery download from the admin panel returns a 422 with the message "Pipeline image not built. Run 'docker compose build pipeline' first" — pointing the user to a manual step they were never told about.

**Impact:** The wizard advertises a turn-key deployment. The first thing a new user tries — opening the admin panel and hitting "Download NOAA imagery" — fails with a terminal-only remediation. User confidence in the wizard drops at the first click.

**Found by:** contract trace — README says pipeline image must be pre-built for admin-panel features; wizard's Launch doesn't do it.

---

### `bootstrap.sh` installs `docker-compose` (V1) but preflight and `/api/launch` use `docker compose` (V2 plugin)

**Location:**
- `bootstrap.sh:31` — `apt install -y ... docker.io docker-compose ...`
- `setup/main.py:54` — preflight check `["docker", "compose", "version"]` (plugin syntax)
- `setup/main.py:381-388, 532, 561` — every compose call uses `docker compose ...`
- `README.md:139` — documents `docker-compose-plugin` (correct) for manual setup

**Severity:** significant

**Evidence:** The Debian `docker-compose` apt package is the Python-based V1 client (standalone binary `docker-compose`). The wizard (and README quick start) instead rely on the Docker plugin invoked as `docker compose` (space, not hyphen). The plugin ships with `docker-compose-plugin` or `docker-ce` — **not** with the `docker.io` + `docker-compose` duo the bootstrap installs.

Therefore on a vanilla Debian Trixie Pi where `docker-compose-plugin` isn't a separate install, bootstrap may complete, but the preflight `docker compose version` returns a non-zero exit code (plugin missing). The `FIX_REGISTRY` entry for `docker-compose` would install the V1 package again — doesn't fix the plugin problem. The user is stuck in a loop.

**Impact:** This alone can kill a first-time install. And README §Prerequisites already diverges from bootstrap: README says `docker-compose-plugin`, bootstrap installs `docker-compose`. Two official install paths disagree.

**Found by:** comparing the apt package bootstrap installs vs the syntax the rest of the stack uses.

---

### `public_lands` pipeline step is structurally impossible to automate — requires a CAPTCHA-protected manual download

**Location:**
- `setup/main.py:428-432` — `public_lands` in `PIPELINE_STEPS`
- `scripts/build_public_lands.py:268-280` — script detects non-ZIP responses and raises "likely an HTML error page or CAPTCHA"
- `README.md:317-335` — explicit instructions to download PAD-US manually first via browser

**Severity:** significant

**Evidence:** The wizard advertises `public_lands` as a pipeline step. ScienceBase's large-file endpoint returns a CAPTCHA redirect for programmatic access. The script explicitly errors with the message "ScienceBase requires a browser for large file downloads. Please download manually from: https://www.sciencebase.gov/catalog/item/652d4fc5d34e44db0e2ee45e and save as {zip_dest}".

Additionally, `build_public_lands.py` requires Tippecanoe compiled from source on ARM64 — not in `FIX_REGISTRY`, not in `PREFLIGHT_CHECKS`, not installed by `bootstrap.sh`.

**Impact:** Even once `_run_pipeline` is wired to actually call scripts, the public_lands step cannot succeed on a clean machine. The user will see a failure with a wget-returned-HTML message, and they need Tippecanoe from source as well. The wizard should either (a) skip this step by default and surface a link to the manual PAD-US download, or (b) remove it from `PIPELINE_STEPS`.

**Found by:** tracing every `PIPELINE_STEPS` entry to an underlying script and checking what that script actually needs.

---

### `fonts` and `styles` pipeline steps have no script to drive them

**Location:**
- `setup/main.py:428-432` — `fonts` in `PIPELINE_STEPS`, but no `styles` step
- `README.md:344-370` — `fonts` requires `wget` + `unzip` + a specific URL; `styles` requires git-cloning two external repos for icons
- `setup/runner.py` — no command-builder for fonts or styles

**Severity:** significant

**Evidence:** `fonts` is listed as a pipeline step but `setup/runner.py` has no `fonts_cmd()` builder. No argv-list exists anywhere that downloads fonts. Even if `_run_pipeline` were wired up, there's nothing to run for this step.

Worse: the README's step 8 has *two* distinct actions — downloading fonts AND cloning the Positron/DarkMatter style icon directories — and `PIPELINE_STEPS` only names one.

**Impact:** Even after the no-op-loop bug is fixed, `fonts` produces nothing; the tileserver will 404 on glyph requests and the map will render without labels. `styles` icons are missing entirely — POIs render as empty circles.

**Found by:** cross-referencing `PIPELINE_STEPS` identifiers against `runner.py` command builders against README manual steps.

---

### Credentials file written with default umask (644) — plaintext M2M + Copernicus secrets readable by other local users

**Location:** `setup/main.py:302-314`

**Severity:** significant

**Evidence:** `Path.write_text(json.dumps(cred_data, indent=2))` uses default umask. No `chmod(0o600)` call. On a default Raspberry Pi OS install the umask is `022`, so `credentials.json` ends up `0644`. The admin-panel credential flow explicitly chmods 0600 per design doc `docs/superpowers/specs/2026-04-15-credential-keyring-design.md:642`.

Compare the keyring-agent path, which never writes plaintext secrets at all. The wizard's Step 3 is strictly less secure than the alternative path.

**Impact:** Any local user on the Pi (guest account, compromised service, etc.) can read the USGS and Copernicus tokens. For a device intended for DEF CON display this is reportable. Note this combines with the "credentials never migrated to keyring" bug above: the plaintext file not only exists but persists, since no migration empties it.

**Found by:** security audit of the Step 3 write path. The `Path.write_text` + `mkdir(parents=True, exist_ok=True)` pair has no security hardening.

---

### `main.py:598` binds `0.0.0.0:8099` when run as a script — defeats "localhost only" security claim

**Location:**
- `setup.sh:28` — binds `127.0.0.1` (correct)
- `setup/main.py:596-598` — `if __name__ == "__main__": uvicorn.run(app, host="0.0.0.0", port=8099)` (wrong)

**Severity:** minor (setup.sh is the documented path), **significant** if run as `python3 -m setup.main`

**Evidence:** Two entry points, two different bind addresses. `setup.sh` launches uvicorn with `--host 127.0.0.1`; the `__main__` block inside `main.py` launches with `host="0.0.0.0"`. If a user follows the secondary install method (install into a venv, run the module directly) they expose the wizard — including all the "sudo apt install" endpoints — to the LAN.

The CSRF token is embedded in the served `/` HTML. Any LAN device can curl `/`, extract the token, and POST `/api/fix-dependency` (which shell-quotes the FIX_REGISTRY commands to `sudo apt install -y ...`). These fail on a typical Pi because sudo needs a TTY — but any sudo-NOPASSWD config turns this into remote code execution.

**Impact:** Security footgun. The "localhost-only" claim in the README (line 624) and the design docs is only true for `setup.sh`.

**Found by:** contrast between the shell launcher and the Python `__main__` block — the two are meant to do the same thing and don't.

---

### `Checkpoint` construction isn't crash-resilient

**Location:** `setup/runner.py:18-23`

**Severity:** significant

**Evidence:** `json.loads(self._path.read_text())` with no try/except. `_persist()` writes non-atomically (`write_text` is not atomic — a SIGKILL mid-write truncates). On a disk-full or power-cut mid-pipeline, the next wizard run can't instantiate `Checkpoint()` without manual `rm`. The existing `try/except Exception` in `_run_pipeline:467` catches the failure but broadcasts only `str(e)` — "Expecting value: line 1 column 1 (char 0)" — with no remediation hint.

**Impact:** Broken state requires shell access to fix. The wizard's own "Retry" button cannot recover, because the retry path creates another `Checkpoint(...)` first and crashes identically. Overlaps with multipass hunter's identical finding.

**Found by:** failure-mode analysis on every external-file read inside the wizard.

---

### "Already healthy" detection matches `"unhealthy"` substring

**Location:** `setup/main.py:549-552`

**Severity:** significant

**Evidence:**
```python
all_healthy = all(
    "healthy" in (s.get("Health", "") or s.get("Status", ""))
    for s in existing_services
) if existing_services else False
```

`docker compose ps --format json` produces `Status: "Up 2 days (unhealthy)"`. Python's `in` is a substring test, so `"healthy" in "unhealthy"` is True. All-unhealthy stacks are reported as "already_healthy" → the wizard tells the user "all services already running and healthy" and points them to a broken app.

A user re-running `./setup.sh` against a previously-broken deployment gets a false all-green. Overlaps with multipass.

**Found by:** substring-match audit; this pattern is a well-known Python footgun.

---

### Step-2 "Detail imagery" zoom slider + source buttons have no wiring to the pipeline

**Location:**
- `setup/static/index.html:142-152` — UI for M2M / Copernicus / Skip + zoom slider
- `setup/static/setup.js:182` — stores `config.base_imagery_zoom` in JS state
- `setup/static/setup.js:628-632` — builds `layers` list for `/api/start`
- `setup/main.py:155-158, 458-519` — accepts `layers: list[str]` but never reads it

**Severity:** minor (cosmetic today, latent footgun once the no-op pipeline is fixed)

**Evidence:** The frontend collects detailed per-layer source choices and zoom ranges. The backend accepts a `layers` list on `/api/start` and never uses it. `config.base_imagery_zoom` is not sent to the backend at all. So even once `_run_pipeline` is fixed, imagery choices selected in Step 2 have no effect.

**Impact:** Fixing just the known `_run_pipeline` bug will still ignore the user's Step 2 choices. The Step 2 UI needs backend plumbing before the pipeline fix is complete.

**Found by:** following data from user input through to script invocation.

---

### `detect_host_ip` rejects `127.0.0.1` but not other loopback/link-local — and returns `0.0.0.0` as a user-visible value

**Location:** `setup/config.py:160-185`

**Severity:** minor

**Evidence:** Rejects exactly `127.0.0.1` and `172.17.*` prefix. Doesn't reject the rest of `127.0.0.0/8`, `169.254.*` link-local, or IPv6 loopback. The `0.0.0.0` fallback is then written into `.env` and into the "Open Geographica" link (`setup.js:886`). Also, on multi-homed Pis, `ip route get 1` picks whatever route serves `1.0.0.0` — not necessarily the LAN-facing interface.

**Impact:** Wrong-interface detection on Pis with Tailscale + LAN + docker0. User then clicks the completion link and sees "Can't connect" in their browser. Overlaps with `HOST_IP is dead` finding — the real fix is probably to remove the field altogether, since the stack doesn't consume the value.

**Found by:** boundary analysis of the detection function.

---

## Design Concerns

### The pipeline-steps list has no type discipline

`PIPELINE_STEPS` is a bare `list[str]` of identifiers. There's no single source of truth that says, for each step: which script builds it, which dependencies it needs, which env vars it reads, whether it's optional, whether it requires credentials. The information is spread across README, `runner.py` (half the builders), `FIX_REGISTRY`, and the scripts themselves. This is why the `fonts` and `styles` steps have no builder, `public_lands` has no CAPTCHA handling, and `layers` is ignored: no structure forces completeness.

A dataclass per step (`PipelineStep(id, label, cmd_builder, required_deps, required_creds, optional_flag)`) would make the entire category of drift impossible and would also let the UI offer per-step "skip" without a special all-or-nothing code path.

### The wizard is a façade that silently delegates hard decisions to manual steps

Step 1 asks for `HOST_IP` — decorative. Step 1 picks a data path — doesn't flow through. Step 1 offers TLS modes — half are no-ops. Step 2 picks imagery sources — ignored by pipeline. Step 3 writes credentials — stored where nothing reads them. Step 4 "runs the pipeline" — does nothing. Step 5 "launches the stack" — doesn't build the pipeline image.

Each individual bug has a concrete fix, but the meta-pattern is: **the wizard frontend was designed without first enumerating what the stack actually reads**. Every future setup-UI change should start with `grep env-var repo/**/*.{yml,conf,sh}` and work forward from there.

### `sudo apt install` via a web UI, without any UX for password prompts

`FIX_REGISTRY` commands begin with `sudo`. The subprocess has no TTY, so sudo will fail on any non-NOPASSWD machine. The wizard silently shows "Failed" and loses the `(a terminal is required to read the password)` stderr. The solution is to not run sudo at all from the wizard — drop the Install button entirely, and instead tell the user "run `sudo ./bootstrap.sh` to install dependencies." That also aligns with the already-documented flow.

### The keyring-agent startup migration is load-bearing but race-prone

Migration runs once at `serve()`, which is scheduled by systemd during bootstrap. The wizard writes credentials to JSON after the agent has already migrated (nothing to migrate → done). A periodic or filesystem-watch-triggered migration would be more robust, or the wizard should call the keyring agent directly (via the agent's Unix socket) instead of writing JSON at all.

### Bootstrap's PAM edit is surprisingly invasive for a setup script

`bootstrap.sh:41-48` appends two lines to `/etc/pam.d/common-auth` and `/etc/pam.d/common-session`. This makes GNOME Keyring auto-unlock work across reboots, but on a system where the user already has PAM configured for some other keyring or auth scheme, this silently adds second handlers. Bootstrap has no rollback path. At minimum, the edit should be gated behind a prompt.

## Notes on overlap with the multipass hunter

The multipass report covers most of the same ground with slightly different emphasis. Where we found the same issue, I've noted "Overlaps with multipass" and tried to add framing (contract-trace, data-flow reasoning) rather than just evidence. Unique bugs above — ones I don't see in multipass:

- TLS vocabulary disagrees across **four** files (multipass noted the orphan endpoint but not the four-way vocab mismatch)
- `SCRIPTS_HOST_PATH` hardcoded Cameron-specific default
- Wizard never builds pipeline image → admin panel pipelines 422 immediately
- `public_lands` CAPTCHA + Tippecanoe unautomatability
- `fonts`/`styles` have no command builder at all
- `credentials.json` vs `.credentials.json` keyring-agent path mismatch
- Credentials written 0644 instead of 0600
- `bootstrap.sh` installs `docker-compose` V1 but everything else expects V2 plugin
- `main.py:598` `0.0.0.0` bind when run as module
- PAM edit is invasive

Combined, my report and multipass cover ~25 distinct setup issues. The highest-severity items are the ones that make first-run deterministically fail for anyone who isn't Cameron: `SCRIPTS_HOST_PATH` hardcoding, missing pipeline image build, TLS vocabulary mismatch, keyring-agent path mismatch, the known no-op pipeline, and the docker-compose V1/V2 bootstrap mismatch.
