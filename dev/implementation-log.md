# Implementation Log

Narrative companion to [CHANGELOG.md](../CHANGELOG.md). Where
`CHANGELOG.md` lists *what* changed in each release, this log captures
*why* and *how* — the reasoning, tradeoffs, adversarial reviews, and
bugs caught before release.

Entries are reverse-chronological (newest first). Each significant work
item gets one entry. The format:

```markdown
## YYYY-MM-DD — <topic>

**Released as:** vX.Y.Z (or "not yet released" / "ongoing")
**Plan / spec:** docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md
                 docs/plans/YYYY-MM-DD-<topic>-plan.md
**Bug hunts:** dev/bug-hunts/YYYY-MM-DD-<topic>-*.md (if any)
**Adversarial reviews:** dev/adversarial/YYYY-MM-DD-<topic>-*.md (if any)

### Summary
One paragraph: what was built, why, and the outcome.

### Key decisions
- Decision and rationale.
- Alternative considered and why rejected.

### Notable bugs caught
- Bug → where caught → commit SHA that fixed it.

### Commits
Short list of notable commits (SHA + subject). The git log is
authoritative; list only the ones a reader would want to jump to.

### Outcome
Production results, test counts, any surprises.
```

---

## 2026-04-19 NIGHT — Beta-tester preflight unblocker + wizard harness rebuild

**Released as:** `fix(setup): unblock beta testers stuck in preflight + bootstrap loops` (commit `5e400c5` on main). Harness rewrite lands with this commit on main.
**Plan / spec:** none — single-session debug off a beta-tester screenshot (docs/123_1 (7).jpeg).
**Bug hunts:** none — all found through the harness rewrite.
**Adversarial reviews:** none.

### Summary
Every beta tester attempting to set up Geographica since the 2026-04-19
setup-remediation landing hit a hard wizard-level block: preflight's
"Python pipeline deps" check reported `Missing: rasterio, shapely, scipy,
numpy` on every Pi, regardless of bootstrap success or reboot. The
wizard's "remedy" box told them to re-run `sudo ./bootstrap.sh` in what
was effectively an infinite loop. One beta tester looped this ~16 times
before giving up; another rebooted and still hit the same error.

Root cause (confirmed against beta tester's screenshot + end-to-end LXD
reproduction): the wizard's preflight check used in-process
`__import__('rasterio')`, which runs inside `setup/.venv` — the venv
setup.sh creates. That venv does NOT inherit the user's `~/.local/...`
where bootstrap's `pip install --user --break-system-packages` places
those packages. So the check ALWAYS reported missing on every Pi, forever.

Fix: preflight now shells out to `/usr/bin/python3 -c 'import <pkg>'` so
the check reflects the actual user environment bootstrap targeted, not
the venv. 6 regression tests in `tests/test_preflight_python_deps.py`
guard against the bug coming back.

Also shipped alongside:
- **bootstrap.sh curl/gpg prereq.** Bootstrap consumed `curl` + `gpg`
  for Docker repo setup BEFORE installing them. Fine on raspios Full
  (preinstalled) but broke on minimal Debian / raspios Lite.
- **bootstrap.sh completion-message overhaul.** Beta tester literally
  reported "exiting a screen and opening a new one counts as logging
  out, right?" — it doesn't. New message spells out 4 concrete options
  (reboot / ssh exit+reconnect / console logout / `newgrp docker`)
  and names what does NOT count. Includes a `groups` verification step.
- **setup.sh diagnostic message.** Distinguishes "Docker not installed"
  from "installed but your shell isn't in the docker group" and gives
  a specific fix for each (previously offered both as a list, asking
  the beta tester to guess).

Post-fix, the LXD harness got the rebuild it's needed since v1.0:

- **`dev/harness/drive-wizard.mjs` full rewrite.** Before: waited for
  `#step-4` selector, exited 0. Asserted nothing. After: asserts no
  error banners at any step boundary, no raw Python tracebacks in
  the DOM, preflight all dots are `.ok` (with a named exclusion for
  known-environmentally-unavoidable failures), `#btn-next` enabled
  + text appropriate, no pageerror / console.error events. RED-tested
  by injecting a bogus package into the preflight list — harness
  correctly failed with `ASSERT FAIL: 1 preflight check(s) failing`.
- **`dev/harness/wizard-ci.sh` fixes.** Four LXD-version bugs
  discovered during the rewrite: `lxc file push -r` syntax changed
  (swapped for `git ls-files | tar`); `lxc exec ... & ` never
  detaches (swapped for `systemd-run --unit=...`); setup.sh binds
  127.0.0.1 inside container, unreachable from host (added LXD proxy
  device on port 18099); cloud-init wait blocked on raspios
  (non-cloud-init images — now handles `done`/`disabled`/missing +
  installs systemd-networkd if eth0 has no IPv4).
- **`--image=ALIAS` + `--pre-state=NAME` flags** let the same harness
  run against Debian cloud, raspios, or arbitrary pre-conditioned
  environments.
- **`dev/harness/import-raspios.sh`**: one-shot importer that
  downloads latest raspios-lite-arm64, extracts the root partition,
  creates an LXD metadata tarball, imports as alias `raspios-trixie-lite`.
  Idempotent; cached.
- **`dev/harness/wizard-matrix.sh`**: iterates every `pre-states/*.sh`,
  runs a full wizard walkthrough per pre-state, fail-surfaces all
  failures in one run.
- **`.github/workflows/wizard-ci.yml` upgraded** from manual-dispatch
  only to: smoke mode on every push/PR to `main` or `dev` touching
  the setup code paths, plus manual-dispatch for `matrix`,
  `matrix-raspios`, and `full` modes.

### Notable bugs caught

- **Preflight python-deps infinite loop** (beta-blocker, 5e400c5).
- **LXD bridge down, NAT flushed by Docker** — the harness wouldn't
  run on this Pi AT ALL. Fixed with a `DOCKER-USER` ACCEPT rule +
  systemd unit for persistence (`lxd-docker-bridge.service`).
- **Old harness claimed to exercise the wizard but didn't.** Smoke
  mode exited as soon as `#step-4` rendered — never read any status.
  Every preflight regression since v1.0 would have slipped past.

### Why the 50-task setup-remediation missed the preflight bug

That plan focused on making bootstrap CORRECT; it assumed the wizard's
preflight check (set up well before the plan) was already correct.
In the beta-tester failure mode, bootstrap actually worked — the
wizard's check was broken. No number of bootstrap-focused tests would
catch it, and our LXD harness didn't assert anything beyond DOM-load.
The rewrite fixes the class — any future preflight regression will
fail CI instead of beta.

### Commits

- `5e400c5 fix(setup): unblock beta testers stuck in preflight + bootstrap loops` — setup/main.py + tests + bootstrap.sh curl prereq + completion msg + setup.sh diagnostic (on main).
- (this commit) `test(harness): real assertion-bearing wizard harness + raspios + pre-state matrix + CI gating` — harness rewrite + import-raspios.sh + wizard-matrix.sh + workflow update.

### Outcome

- **Beta testers unblocked**: 5e400c5 is on main. `git pull && sudo ./bootstrap.sh` (or just `./setup.sh` if bootstrap already succeeded) now proceeds past preflight.
- **Harness on the gate**: push to `main`/`dev` now runs the assertion-bearing smoke mode. Before: manual dispatch only + smoke-mode that passed even on the broken wizard.
- **One concrete known-limitation surfaced to a follow-up**: `--image=raspios-trixie-lite` launches the container fine and bootstrap's apt phase completes, but `systemctl start docker` inside raspios-LXD fails with "Job for docker.service canceled" after bootstrap edits `/boot/cmdline.txt` for cgroup_enable=memory. Does not affect the Debian-cloud smoke gate. Deferred for separate debug session.

---

## 2026-04-19 EVE — Trixie docker file-conflict: fix + pre-state harness

**Released as:** fix on `dev` (commit `59f00b5`); matrix landing with this commit.
**Plan / spec:** none — single-session debug + fix.
**Bug hunts:** none — the three 2026-04-18 setup hunts missed this (see "Why internal missed it" below).
**Adversarial reviews:** none.

### Summary
Every beta tester on Raspberry Pi OS Trixie with any prior Docker
attempt (`apt install docker.io`, `get.docker.com`, or `apt
full-upgrade` with docker.io on it) was hard-blocked at `./bootstrap.sh`
with a dpkg file-conflict. Debian 13 Trixie started shipping native
`docker-buildx` (0.13.1+ds1-3) and `docker-compose` (2.26.1-4) packages
that physically own the same paths as Docker's official
`docker-buildx-plugin` / `docker-compose-plugin`
(`/usr/libexec/docker/cli-plugins/docker-{buildx,compose}`); neither
side declares `Replaces`, so if either Debian package was installed,
our `apt install docker-ce ... docker-compose-plugin` aborted
mid-unpack. Observed tester looped bootstrap 16× before giving up
(docs/123_1 (6).jpeg). `apt --fix-broken install` couldn't help:
it only resolves dependency issues, not filesystem overwrites.

Fixed in `fix(setup)` 59f00b5: bootstrap now runs Docker's official
"Uninstall old versions" prerequisite step before the docker-ce
install. Idempotent (no-op on clean systems) so the internal dev
Pi and the LXD harness stay green.

Post-fix, built `dev/harness/bootstrap-matrix.sh` — an apt-level
pre-state matrix that runs bootstrap's `[1/6]` block in ephemeral
Debian 13 Docker containers against realistic customer starting
states (clean / `debian-docker-buildx` / `docker-io` /
`get-docker-com`). Fails CI if any pre-state regresses.

### Key decisions

- **Use `apt remove`, not `apt purge`.** Removing Debian's docker.io
  is the minimum needed to unblock docker-ce install; purging would
  wipe `/etc/docker/` and any user-created configs. `apt remove`
  leaves packages in `deinstall ok config-files` state, which
  satisfies dpkg's path-ownership constraint (binaries gone). The
  matrix's post-condition check had to handle this subtlety —
  `dpkg -s <pkg>` returns 0 for both "install ok installed" AND
  "deinstall ok config-files"; only the former is a regression.

- **Docker-based matrix, not LXD-based.** LXD is the right tool for
  the full wizard E2E (it exercises systemd + ports + Playwright).
  For apt/dpkg state verification, Docker containers start in ~1 s
  vs. LXD's ~15 s and don't require a bridge + NAT config. All four
  pre-states complete in ~10 min in Docker. Fewer moving parts =
  fewer CI flakes. The LXD harness (`wizard-ci.sh`) still owns the
  full wizard path.

- **Extract bootstrap slice via awk, not by copying or flag-gating.**
  The matrix runs the real `bootstrap.sh` source (no duplicated
  code; no test-mode flag on bootstrap itself). awk extracts the
  `[1/6] ... [2/6]` range at runtime. If the banner format ever
  changes, the matrix fails fast with a clear error.

### Notable bugs caught

- Beta-tester blocker (dpkg file conflict) → caught by the user
  uploading `docs/123_1 (5).jpeg` + `(6).jpeg` from the latest
  beta round → fixed in `fix(setup)` 59f00b5.
- Matrix post-condition false-positive: `dpkg -s docker.io`
  returns 0 for `deinstall ok config-files` too → caught by the
  `docker-io` pre-state failing in matrix runtime → fixed in the
  same commit as the matrix landing.

### Why internal missed it

Five independent reasons the signal was a false negative — saved
in memory as `feedback_test_harness_mirror_reality.md`:

1. **Internal dev Pi is a cherry-picked environment.** `dpkg -l
   docker-buildx docker-compose` → both "not installed" on our Pi.
2. **LXD harness uses `images:debian/trixie/cloud`.** Minimal cloud
   image, zero preinstalled Docker packages → our happy-path test
   never sees the conflict.
3. **Harness only exercised one starting state.** No pre-state
   matrix before today.
4. **Setup-remediation plan had a structural blind spot.** 4950 lines,
   50 tasks, zero mentions of `docker-buildx`, `purge`, or
   `file conflict`. Plan assumed a clean target.
5. **Bug hunts were static.** All three 2026-04-18 setup hunts read
   bootstrap.sh as source code; none ran it against a customer-like
   starting state.

### Commits

- `59f00b5 fix(setup): purge Debian-native docker packages before docker-ce install` — TDD: failing test + fix + end-to-end Docker verification that without the fix the beta error reproduces and with it bootstrap completes clean.
- (this commit) `test(harness): bootstrap pre-state matrix (Trixie docker conflict regression guard)` — `dev/harness/bootstrap-matrix.sh`, 4 pre-states, 8 canary pytests, README update.

### Outcome

- `fix(setup)` landed on `dev` and pushed to `origin/dev` so beta testers could `git pull && sudo ./bootstrap.sh` immediately for weekend-availability testing.
- 12/12 unit tests on the fix + matrix passing.
- Full 4-pre-state Docker matrix: 4/4 PASS in 605 s end-to-end.
- Follow-up queued: Tier 2 full-wizard LXD matrix (`wizard-ci.sh --pre-state=NAME`), currently blocked by LXD bridge being DOWN + NAT flushed by Docker on this host; needs a host networking fix before wiring up.

---

## 2026-04-19 PM — TileServer auto-restart on clean pipeline completion

**Released as:** not yet released (on `dev`, pending merge)
**Commit:** `f6f7365` (single commit, 2 files, +312 / −37)
**Bug hunt:** [dev/bug-hunts/2026-04-17-pipeline-completion-review.md](bug-hunts/2026-04-17-pipeline-completion-review.md) §Bug 1

### Summary
Long-standing bug where the map never auto-updated after a pipeline run finished cleanly. The admin service's reconciliation guard at `services/search/main.py:1473` only entered the WAL-checkpoint + TileServer-restart path when the pipeline had CRASHED (`status in ("running", "cancelling") and not container_running`). But every pipeline script writes `status="completed"` to the state file itself *before* the container exits, so the guard was false on clean exits and TileServer was never restarted. Widened the guard to include terminal states (`completed` / `completed_partial`) that have not yet been handed off — tracked via a new `tileserver_restarted_at` stamp on the state file that makes repeat polls no-ops. Runtime-validated live against the stuck Phoenix NOAA run.

### Key decisions
- **Idempotency via state-file stamp, not a background watcher.** Considered a dedicated `/admin/pipeline/finalize` endpoint or a docker-event-driven watcher. Stamp approach is minimally invasive (no new endpoints, no new threads), self-healing (swept a stuck elevation state as a side effect), and fires exactly once per run.
- **Dropped `PRAGMA journal_mode=DELETE`** from the search-service checkpoint. D3 (already shipped on dev) deliberately keeps WAL mode permanently; flipping to DELETE can fail against TileServer's live read-lock during handoff. TRUNCATE checkpoint alone suffices.
- **TDD end-to-end.** 5 new tests covering clean-completion, idempotency, `completed_partial`, and crash-path regression. Watched all fail first; implemented fix; watched all pass. No production behavior untouched by a test.

### Notable bugs caught
- 2026-04-17 §B1 (TileServer Never Restarted After Pipeline Completion) → `f6f7365`
- Symlink-hijack by pytest Task 42 fixture (parallel agent found + fixed as `a2cf6dc`) — not a Claude bug but surfaced during runtime validation.

### Commits
- `f6f7365` — fix(search): restart TileServer on clean pipeline completion (B1 2026-04-17)

### Outcome
- 5 new tests pass; full suite 784 passed (same 2 pre-existing M2M failures, 18 pre-existing env errors).
- Runtime validation on the actual stuck Phoenix state: `tileserver_restarted_at: 2026-04-19T12:57:25Z` written to `.pipeline-state.json`; TileServer StartedAt jumped `12:57:25 → 12:57:55`; `/data/imagery_noaa.json` now serves correct bounds + z9-17; sample tile `/data/imagery_noaa/9/93/202.jpeg` serves 200 OK 18.6 KB JPEG. Second poll idempotent (no double-restart). Self-healed `.elevation-state.json` as a bonus.
- Deferred (each a separate follow-up): B2 (NAIP/Sentinel state-file misnaming), B3 (NAIP/Sentinel missing from TileServer config), B6 (MapLibre base-imagery TileJSON cache).

---

## 2026-04-19 — Setup process remediation (v1.2 cycle)

**Scope:** 48 confirmed bugs (B1-B48) + 8 design decisions (D1-D8) + 3
out-of-scope items (O1-O3) across setup/main.py, setup/config.py,
setup/runner.py, setup/static/*, bootstrap.sh, docker-compose.yml,
nginx/entrypoint.sh, README.md.

**Outcome:** Wizard path is now end-to-end working on a fresh Debian
Trixie LXD container (verified via dev/harness/wizard-ci.sh --smoke).
Every .env VAR that docker-compose.yml references is emitted by
generate_env. TLS vocabulary canonicalized to http|https|tailscale.
Credentials flow through the keyring Unix socket (no more JSON
plaintext). PIPELINE_STEPS lifted to a frozen dataclass registry with
per-step command builders. Install-location UI finally wired through
to the running stack via symlink re-target on launch.

**Highlights:**
- New dev/harness/{wizard-ci.sh, drive-wizard.mjs} for regression
  testing the full setup flow in LXD.
- tools/build-tippecanoe.sh + bootstrap asset-download to eliminate
  the public-lands CAPTCHA + tippecanoe-from-source blockers.
- Shared showError helper in setup.js; all saves now awaited before
  navigation.
- Preflight now covers tippecanoe, python pipeline deps, keyring
  agent socket, cgroup memory, openssl. No more /api/fix-dependency
  (users re-run sudo ./bootstrap.sh with copy-paste).
- Memory profile retuned to "good neighbor" ceilings leaving 3-4 GB
  host headroom (Cameron's architectural call during execution).
- Process rigor (3-agent subagent-driven-development workflow) caught
  several plan-level inconsistencies: tippecanoe 2.80.0 upstream-
  missing, sudo -H missing for pip --user, test-class misclassification,
  keyring socket protocol mismatch.

**Deferred to v1.2 appendix (B44-B48):** response-shape unification,
preflight row-level UI nit, stderr color coding, tls-scan tool-missing
signal, post_credentials empty-field semantics (partially covered
already by skip-empty in Task 23).

**Pitfalls added to dev/testing-pitfalls.md:** TOCTOU in async
endpoints (from Task 30).

---

## 2026-04-19 — GX-01 adapter HAT: JLC bundle correctness + mechanical design paused

**Released as:** ongoing (internal hardware work; no user-facing release)
**Plan / spec:** [docs/superpowers/plans/2026-04-18-gx-01-pcb-completion.md](../docs/superpowers/plans/2026-04-18-gx-01-pcb-completion.md) (Phase 0 paused; see Status block)
**Design doc:** [hardware/gx01-path-c-mockup.html](../hardware/gx01-path-c-mockup.html) (open in a browser)

### Summary
User attempted to upload `hardware/gx01-adapter-pcb/jlc_bundle.zip` to JLCPCB; three rounds of 3D preview review caught distinct issues: (1) all components offset ~60 mm above the board outline due to Y-sign in CPL, (2) J1/J2 large headers placed ~24 mm off due to using footprint anchor instead of pad-bbox-center, (3) four LCSC parts physically mismatched their footprints (lead pitch, pin count, B2B-vs-S2B sub-variant). All three classes fixed. Final bundle verifies clean and ships 7/7 parts correctly placed in JLC's viewer. Then a mechanical concern surfaced: the adapter HAT's top-surface connectors (J2 at ~11 mm + ribbon) exceed the case's ~10 mm top-plate clearance. Iterative mockup and dimensional analysis produced two viable paths (A: taller case, C: flip J2 to B.Cu and sandwich with LCD); decision formally deferred until X1100 (arriving 2026-04-19) and SparkFun LCD-00710 (~1 week) are in hand to measure.

### Key decisions
- **CPL positions come from `pcbnew` pad-bbox centers, not `kicad-cli pcb export pos`.** `kicad-cli` passes the footprint anchor through unchanged; the KiCad GUI has a "Use pad origin as reference" toggle that isn't exposed in the CLI. For JLC CPL "Mid X/Mid Y" correctness, we must compute pad bbox centers ourselves in `pcbnew`.
- **Trust the JLC catalog description over the 3D preview.** R1's preview rendering looked suspicious but the description (`Plugin,D2.4xL6.3mm`) confirms it matches our DIN0207 footprint. Placeholder 3D models are common for Extended-tier THT parts. Kept C1370997 unchanged.
- **Design decision deferred pending hardware.** Both Path A (case +20 mm height, keep PCB) and Path C (flip J2 to B.Cu, LCD+HAT sandwich) are mechanically viable. Committing to Path C costs a PCB refab (~$80, ~14 days); Path A costs case proportions. Decision needs physical measurements of X1100 + LCD to confirm the vertical void budget above the X1207 battery cradle.
- **Don't delete the bug-hunt evidence.** JLC 3D preview screenshots (`hardware/jlc_misalignment_v{2,3,4}.jpg`) committed as design history — they're the only record of what the three misalignment classes looked like.

### Notable bugs caught
- **CPL Y-sign flip** — KiCad internal coords are Y-down, Gerbers and JLC CPL expect Y-up. Components rendered ~60 mm above the board outline in the JLC viewer. Fixed by applying `Y = -Y` in the CPL generator.
- **Anchor-vs-center offset for THT headers** — `pcbnew.FOOTPRINT.GetPosition()` returns the anchor (pin 1), but JLC's "Mid X/Mid Y" expects the geometric pad center. For a 2×20 header this was 24 mm off. Fixed by iterating pads and merging bounding boxes.
- **LCSC part mismatch against footprint (×4)** — `verify_lcsc.py`'s THT-vs-SMD heuristic doesn't check pin count, lead pitch, or connector sub-variant. C254085 (5.08 mm pitch vs our 2.5 mm), C124378 (4-pin vs 1×20), C146125 (S-series side-entry vs B-series top-entry). All 4 were clean per the existing verification; all 4 physically wouldn't have fit. `verify_lcsc.py` hardening noted as follow-up.

### Commits
- `fix(hardware): correct JLC bundle CPL geometry and LCSC part selections` — pad-bbox-center computation, Y-axis flip, 4 LCSC part swaps (C254085→C524651, C124378→C50981, C146125→C158012 for J3 and J4)
- `docs(hardware): pause GX-01 PCB completion pending X1100+LCD arrival` — Plan 3 status block, Path C mockup, JLC preview screenshots, this implementation-log entry

### Outcome
- 7/7 parts verify clean against JLC's live catalog via `verify_lcsc.py`.
- `jlc_bundle.zip` regenerated (33 KB, 11 files); BOM and CPL confirmed matching via diff against `kicad-cli pcb export pos`.
- PCB work paused for ≤1 week awaiting hardware; resumption criteria documented in [session handoff memory](../../../home/administrator/.claude/projects/-home-administrator-Code-geographica/memory/handoff_20260419_gx01_cpl_path_c.md) (out-of-repo).

---

## 2026-04-18 — NOAA Imagery Pipeline Remediation (on dev, awaiting runtime validation)

**Released as:** not yet released — all 13 commits on `dev` only, pending end-to-end validation on a Flagstaff-size bbox after the current ~494-quad production pipeline finishes (~2026-04-19)
**Plan / spec:** [dev/plans/2026-04-18-noaa-imagery-pipeline-remediation-plan.md](plans/2026-04-18-noaa-imagery-pipeline-remediation-plan.md)
**Bug hunts:** [dev/bug-hunts/2026-04-18-noaa-imagery-pipeline-consolidated.md](bug-hunts/2026-04-18-noaa-imagery-pipeline-consolidated.md) (+ exploratory/holistic/multipass individual reports)
**Adversarial reviews:** 5 prior reports at `dev/adversarial/2026-04-16-*.md` (used as reference only; not authoritative for this cycle)

### Summary
Fresh 3-hunter bug-hunt cycle on the imagery pipeline (5161 LOC) because OOM crashes since the 2026-04-16/17 adversarial review may have caused the then-deferred 9-item list to drift. Result: 16 confirmed bugs (11 new) + 6 design decisions. Scope-locked to 13 bugs + 3 design decisions (B6, B8 deferred for Chesterton's Fence — they'd re-touch `e7e3b32` and `1bab361` code that fixed user-observed imagery artifacts; D4/D5/D6 deferred for scope). All 13 executed via subagent-driven development on `dev`, each fix behind its own commit. Ship deferred pending runtime validation — a production NOAA run is currently blocking the Pi.

### Key decisions
- **Fresh hunt over re-validating the stale deferred list.** Prior 9 deferred items were from 2026-04-16 review; many OOM crashes since could have landed fixes without session notes. New hunt found 11 bugs absent from the old list — the instinct to re-run was right.
- **Chesterton's Fence on B6 and B8.** Hunters flagged `merge_mbtiles` compositing and erosion-after-overview ordering, but commits `e7e3b32` and `1bab361` added those behaviors *specifically* to fix user-observed imagery loss / black quadrant artifacts. Deferred both pending visual-regression testing on a small bbox.
- **Source-inspection tests for Phase 5 rewrite.** Task 9 combines B1 + D1 + D3 with 4 cancel-guard sites, erosion gating, WAL-mode keep-forever. Real end-to-end tests would require mocking gdaladdo + rasterio + interrupting mid-operation — out of scope for this cycle's test harness. Tests verify *code shape* (string presence) not *runtime behavior*. This is named technical debt to revisit.
- **Don't ship to main until live-tested.** Per Cameron's judgment: 13 commits on `dev` + runtime validation later > 13 commits on `main` now + debugging the next NOAA run.

### Notable bugs caught
- **B8 (erosion-after-overview)** — matches `docs/flagstaff_rendering_issue.jpg`. Deferred pending validation.
- **B6 (merge_mbtiles re-composites every overlap)** — progressive JPEG generation loss at quad boundaries. Deferred.
- **B1 (cancel ignored during Phase 5)** — user-visible UX bug: cancel click ignored for 30+ minutes of post-processing. Task 9, commit `48092e6`.
- **B9/D1 (erosion non-idempotent on resume)** — incremental bbox expansion could silently delete valid tiles. Task 9, commit `48092e6`.
- **B14 (wrong MBTiles WAL-checkpointed for elevation)** — only bug outside `scripts/`. Task 4, commit `38b9d32`.
- Plan's own self-inconsistency (explanatory comment contained forbidden string the test asserted against) — caught by Task 9 implementer; reviewer validated rephrase was correct.

### Commits (on dev, not yet on main)
Filtered to remediation work (Cameron's concurrent hardware commits excluded):
- `aace75c` — fix(pipeline): capture rasterio src dims before with exits (B3)
- `ffb93f3` — fix(pipeline): reject fully-out-of-bounds tiles in rasterize (B4)
- `6f26ed5` — fix(pipeline): count composite errors in merge_mbtiles (B7)
- `38b9d32` — fix(search): target WAL checkpoint by pipeline type, not mode (B14)
- `d943968` — fix(pipeline): detect short-reads and reuse cached staging tiles (B10, B11)
- `c619ec4` — fix(pipeline): write progress on _merger failure branches (B12)
- `e8f5f2b` — fix(pipeline): honor cancel during M2M overview build (B2)
- `fc7e03d` — fix(pipeline): share cancellable GDAL subprocess wrapper (B5)
- `48092e6` — fix(pipeline): cancel guards + WAL mode + no-erode-on-resume in NOAA Phase 5 (B1, B9, D1, D3)
- `6e253be` — fix(pipeline): add completed_partial status for NOAA runs with failures (D2)
- `8aa827c` — fix(pipeline): detect _noaa_checkpoint divergence from tiles table (B13)
- `b1086ab` — refactor(pipeline): write progress state once per call (B15)
- `1f77a70` — fix(pipeline): wire NAIP --concurrency via asyncio.gather (B16)

### Outcome (as of 2026-04-18)
- **624 tests pass** on `dev` (up from 596 baseline → 28 new tests for this cycle); 2 + 9 pre-existing failures unchanged — no regressions introduced by any of the 13 fixes.
- **Production NOAA pipeline currently running** with the *old* code (Python imports happened at startup; disk edits don't affect an in-flight process). Expected completion ~2026-04-19.
- **Runtime validation pending:** once production pipeline finishes, run a Flagstaff-size bbox (~10 quads) with the new code, visual-diff the output against a known-good baseline, then merge `dev` → `main` to feed Release PR #2.
- **Deferred follow-ups:** B6 + B8 (need visual-regression proofing before fixes land); D4/D5/D6 (architectural cleanups out of this cycle's scope). Fully documented in the remediation plan's appendix.

### Resume instructions for tomorrow
1. Confirm current production pipeline has completed cleanly.
2. Run `python -m pytest tests/ services/search/tests/ -v` — expect 624 pass, 2 + 9 pre-existing.
3. Execute a validation run on a small bbox (Flagstaff, e.g. `-112.0,35.1,-111.5,35.4`) with the new code. Verify: pipeline completes, tiles render correctly at all zooms, cancel mid-Phase-5 is honored, resume run doesn't re-erode valid tiles.
4. If validation passes: `git switch main && git merge --ff-only dev && git push origin main`. Release PR #2 will update with the 13 new fixes.
5. If validation reveals an issue: identify the specific task → `git revert <sha>` on dev → iterate.
6. After v1.1.0 ships, revisit B6 + B8 with proper visual-regression tests.

---

## 2026-04-18 — Version Control Strategy Adoption

**Released as:** to be included in v1.1.0 (opened retroactively by
`release-please` on first run)
**Plan / spec:** [docs/superpowers/specs/2026-04-18-version-control-strategy-design.md](../docs/superpowers/specs/2026-04-18-version-control-strategy-design.md)
                 [docs/superpowers/plans/2026-04-18-version-control-strategy.md](../docs/superpowers/plans/2026-04-18-version-control-strategy.md)
**Bug hunts:** none (pure documentation + CI work)
**Adversarial reviews:** none; CVErt-Ops reference survey informed design
(see `Key decisions`)

### Summary
Formalized Geographica's versioning regime: SemVer with project-specific
breaking-change rules (the user's data directory and un-edited infra
files are the contract), Conventional Commits enforcement via
`release-please` GitHub Action, lazy release branches, CHANGELOG and
UPGRADING docs, AGENTS.md mirror of CLAUDE.md for non-Claude harnesses,
and this implementation log as the narrative companion to CHANGELOG.

### Key decisions
- **SemVer, not CalVer or custom.** Matches stack upstreams (Docker,
  nginx, MapLibre, Valhalla). Lowest cognitive load for future users.
- **One-line rule for MAJOR bumps:** "If a user with a working install
  has to edit a file to upgrade, that's a MAJOR." Mechanical, no
  judgement calls at midnight.
- **release-please over git-cliff.** Cameron delegates commits to AI
  agents, so the commit-discipline cost of strict Conventional Commits is
  zero. That inverts the usual calculus: the bureaucracy-saving bot wins
  decisively for a time-constrained solo dev. `git-cliff` remains the
  escape hatch if GitHub Actions setup hits friction.
- **Lazy release branches.** Tag `main` by default; create `release/X.Y`
  only when a critical hotfix is actually needed. No dormant branches.
- **No phase framing.** Considered during brainstorming after surveying
  CVErt-Ops (github.com/scarson/CVErt-Ops). Rejected because
  date-stamped plans + SemVer + CHANGELOG + this log already cover every
  benefit phases would provide. CVErt-Ops uses phases as their *only*
  organizing frame because they have no releases; Geographica does, so
  phases would be redundant.
- **Fresh CHANGELOG at v1.0.0.** Pre-1.0 commits were experimental;
  retroactive CHANGELOG would be revisionist and noisy.

### Notable bugs caught
- Spec self-review caught off-by-one in deliverable count (said "8" new
  files, actual count was 9) and rollout commit count (said "four",
  actual "five"). Fixed inline before user review.
- Spec claimed release-please would not open a Release PR on first run
  "because no `feat:`/`fix:`/`perf:` commits are present yet." Actually
  false: the 6+ post-v1.0.0 NOAA hardening commits already on main are
  qualifying. Corrected before writing implementation plan; the
  retroactive v1.1.0 Release PR is now a deliberate outcome rather than
  a surprise.

### Commits
- `60d6f63` — docs: add version control strategy design spec
- `afb360d` — docs: correct spec prediction of first release-please run
- `0bb6d1a` — docs: add version control strategy implementation plan
- `5191996` — docs: adopt semver and conventional commits
- `da8f0c3` — docs: add implementation log with seed entries
- `627ff1e` — docs: align continuation line in 2026-04-18 implementation log entry
- `8bcd056` — docs(claude): add project ethos, commit discipline, and mirror to AGENTS.md
- `f1292f9` — ci: add release-please workflow for automated versioning
- `40d8175` — docs: mark versioning strategy complete in START.md
- `09ef5ce` — docs: record 2026-04-18 regression check in implementation log

### Outcome
- 2026-04-18 regression check: 579 tests pass, 2 pre-existing M2M failures + 9 pre-existing OSM POI errors (unchanged from 2026-04-17).
- First release-please workflow run on `main` failed with `GitHub Actions is not permitted to create or approve pull requests`. Root cause: repo-level setting `can_approve_pull_request_reviews=false` (default). Fixed by `gh api -X PUT /repos/cameronzucker/geographica/actions/permissions/workflow -f default_workflow_permissions=write -F can_approve_pull_request_reviews=true`. Predictable in hindsight — called out in spec's Risks section. Worth adding to a general "Actions setup checklist" for future projects.
- After permission fix, re-ran workflow (`gh run rerun 24600998329`) — succeeded.
- Release PR opened: [PR #1 — chore(main): release 1.1.0](https://github.com/cameronzucker/geographica/pull/1). Retroactively covers the post-v1.0.0 NOAA hardening work: 5 Features + 9 Bug Fixes, each linked to the originating commit SHA.
- Final holistic code review (sonnet) caught a stale-intro issue in CHANGELOG.md: intro said "Entries from v1.0.1 onward are generated automatically" but first generated entry is v1.1.0 (no v1.0.1 will ever exist). Fixed with a single `docs:` commit (`fc51642`) before merging the Release PR. release-please did not automatically regenerate PR #1 because `docs:` doesn't qualify as a new release. Forced regeneration by deleting `release-please--branches--main` via `gh api DELETE`; auto-closed PR #1. Re-ran workflow, which opened clean [PR #2](https://github.com/cameronzucker/geographica/pull/2) with the corrected intro. Pattern learned: to regenerate a stale Release PR, delete its branch and re-run the workflow — release-please will rebuild from current main.
- PR #2 is the canonical v1.1.0 Release PR. Left unmerged for Cameron to review and decide merge timing (immediate release v1.1.0, or bundle more NOAA deferred fixes first).
- Machinery is live. Future `feat:` / `fix:` / `perf:` commits on `main` will be aggregated into the next Release PR automatically (release-please updates the PR in place on each push of qualifying commits).

---

## 2026-04-15 — v1.0.0 Initial Release

**Released as:** v1.0.0
**Plan / spec:** (retroactive entry; spec/plan pairs exist per
subsystem under `docs/superpowers/specs/` and `docs/plans/`)
**Bug hunts:** Many under `dev/bug-hunts/` through 2026-04-15.
**Adversarial reviews:** Many under `dev/adversarial/` through 2026-04-15.

### Summary
First stable release of Geographica. Ships 7 Docker services (tileserver,
valhalla, nominatim, gps, search, stt, frontend), a browser-based setup
wizard, imagery pipeline with USGS / NOAA NAIP / M2M modes, city-aware
spatial search, public lands layer, GNOME-Keyring-backed credential
storage, and a companion utility for fast bulk imagery processing (lives
in a separate repo, `/home/administrator/Code/geographica-companion`).

### Commits
Git log is authoritative through commit `b3e1afe` (2026-04-17) for
post-v1.0.0 state. For the v1.0.0 commit itself and the work leading to
it, see the session handoff files in agent memory (handoff_20260415.md,
handoff_20260415b.md).

### Outcome
v1.0.0 tagged 2026-04-15. 579 tests passing at release time.
