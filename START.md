# Geographica — Session Start Prompt

Read this file to understand the current state of the project before beginning work.

## Project overview

Geographica is an offline-first GIS platform for AREDN amateur radio mesh networks, running on a Raspberry Pi 5 (16GB RAM, 896GB SATA SSD, GPS hat, Hailo 10H NPU). It combines aspects of Google Earth and Google Maps while being entirely self-hostable and offline-capable after initial data download.

**Owner:** Cameron Zucker (cameronzucker@gmail.com)
**Repo:** /home/administrator/Code/geographica (branch: dev)
**Version:** v1.0.0 (tagged 2026-04-15)
**License:** MIT

## Critical context — read before making any changes

1. **Read MEMORY.md** at `~/.claude/projects/-home-administrator-Code-geographica/memory/MEMORY.md` — it indexes all session handoffs. Start with the most recent.

2. **Read CLAUDE.md** in the repo root — project structure, commands, hardware specs, skill routing. **After reading this file and the most-recent handoff, before your first action on the repo, pick a short lowercase moniker for yourself** and state it in your first user-facing message. The moniker goes into every commit as an `Agent: <moniker>` trailer, into any branch names you create, and into subagent prompts you dispatch. See CLAUDE.md §"Agent identity — pick a moniker at session start" for the full convention.

3. **Data lives OUTSIDE the repo** at `/srv/geographica/data/` (symlinked from `data/`). Never create large files inside the git repo tree.

4. **Git push works from terminal** — `gh auth git-credential` is configured.

5. **Never stop the production stack** (`docker compose down`) without explicit user permission.

6. **Worktrees and destructive git commands are BANNED.** See CLAUDE.md §"Git workflow — worktrees are BANNED" and §"Git workflow — destructive commands are BANNED". If a situation seems to require one, stop and ask.

## What to work on next

**🎯 READY FOR SHIP — Overview-incremental rebuild (13/13 tasks shipped, dev HEAD `5705062`, awaiting A/B harness field-run):**

All 13 tasks of the overview-incremental plan shipped via `superpowers:subagent-driven-development` on 2026-04-22. Agent moniker for the cycle: `tamarack`. **21 commits on `dev`**, pushed to `origin/dev`. The NOAA pipeline's post-processing now drains a persistent SQLite journal (`_overview_work_queue`) instead of nuking+rebuilding the whole pyramid — eliminating the 6+ hour overview phase the 2026-04-21 runtime surfaced.

- **Spec + plan:** [docs/superpowers/specs/2026-04-22-overview-incremental-design.md](docs/superpowers/specs/2026-04-22-overview-incremental-design.md) · [docs/superpowers/plans/2026-04-22-overview-incremental-plan.md](docs/superpowers/plans/2026-04-22-overview-incremental-plan.md) (plan updated 2026-04-22 pre-dispatch by controller-side review — commit `5483971` fixed 6 ambiguity/drift items including a mathematically-wrong test assertion).
- **Implementation log:** [dev/implementation-log.md](dev/implementation-log.md) (2026-04-22 entry at top — 18 commits across 7 phases, per-task review findings, deferred items).
- **Full handoff:** [handoff_20260422_overview_incremental_SHIPPED](../memory/handoff_20260422_overview_incremental_SHIPPED.md) — **READ THIS FIRST** when resuming. Contains: commit-by-commit trail, A/B harness OOM finding + remediation recipe, pre-existing test failure to expect, deferred follow-ups, and "what NOT to do" guardrails.
- **Tests:** 944 green on `dev` (26 new overview/enforcement + 918 broader) with 1 pre-existing unrelated failure (`test_bootstrap_messaging.py::test_next_step_appears_at_most_once_per_branch`). Semantic equivalence of nuclear vs journal modes proven by `test_nuclear_and_journal_produce_equivalent_mbtiles` (4×4 z17 gradient fixture, pixel mean-abs-diff < 2).

**Ship gate before `dev → main` merge**: Cameron runs the A/B harness against a **small-bbox extract** (NOT the full 38 GB `/srv/geographica/data/imagery_noaa.mbtiles` — doing so while the Docker stack is up OOM'd the harness within 30 minutes on 2026-04-22).

```bash
# Cancel or complete any active pipelines, then:
docker compose down
python3 dev/tools/compare_overview_modes.py <small-bbox-extract.mbtiles> --seed-journal --keep
docker compose up -d
```

Expected outcome: `only_in_a == 0 AND only_in_b == 0 AND max_pixel_diff < 2.0`, exit code 0. Then `git switch main && git merge --ff-only dev && git push origin main` → release-please auto-bumps to `v1.3.0` (feature is additive — `CREATE TABLE IF NOT EXISTS` + keyword-only `mode=` parameter — no breaking change).

**Deferred follow-ups** (all documented, none blocking):
- N+1 query batching in `_drain_journal` (4-SELECT-per-ancestor → 1 via `(tc, tr) IN (...)` tuple-IN). Flagged "Important" by Task 4 reviewer; ms-scale savings vs hour-scale win already delivered.
- `--sequential` mode for the A/B harness so cloning doesn't peak at 2× disk space. Makes live-stack-friendly runs possible.
- Port the journal pattern to M2M / Sentinel / NAIP pipelines (one follow-up PR per pipeline per spec §Portability).

---

**🚗 OPEN — Voice announcement TTM redesign (B1 full fix, band-aid currently masking):**

Field testing on 2026-04-20 (Cameron) surfaced that the deferred B1 voice-over-announcement bug is dramatically worse in urban/surface-street driving than pre-remediation observation suggested. A rerouted detour through a dense turn cluster (2235 W Villa Rita Dr → North Phoenix Costco, with a westerly detour) fired **up to 9 voice prompts in ~200 ft of driving** — past helpful, into actively dangerous. Distance-threshold model was the wrong architecture for a range of driving speeds; it needs replacement with a time-to-maneuver (TTM) model.

- **Band-aid is LIVE on dev** (commit `e63f6d9`, dropped voice tiers from `[800, 200, 50]` to `[400, 50]`, caps announcements at 2/maneuver). Buys safety while the redesign runs. **The band-aid will be removed entirely when TTM lands** — that's the design intent.
- **Redesign handoff:** [handoff_20260420_nav_voice_ttm_kickoff](../memory/handoff_20260420_nav_voice_ttm_kickoff.md) — **READ THIS FIRST.** Contains the problem statement, the target TTM model (`[30s, 3s]` with a 50m distance floor), 10 pre-identified design open questions, the suggested process (brainstorm → adversarial review → spec v2 → plan → subagent-driven execution → field-test), files-to-touch list, and "what NOT to do."
- **Process discipline:** full brainstorm + 5+ round adversarial review (include Codex cross-validation round) + spec v2 + plan + subagent-driven execution + integration review, same as the 2026-04-20 nav UX remediation. Unit-tests-alone are insufficient — the 2026-04-20 cycle's tests all passed while the field scenario produced 9 prompts. **TTM merge candidates must re-drive the Villa Rita → Costco detour** as a regression gate before merge.
- **Explicit non-goals:** no more distance-threshold tuning (that's pure band-aid), no amending the band-aid commit (it's the safety net), no skipping adversarial review.

**🚗 READY FOR SHIP — Nav voice picker (23/23 tasks + UX refactor + sidebar tab persistence, field-verified 2026-04-21):**

All 23 tasks of the voice-picker plan shipped via `superpowers:subagent-driven-development`. Phase 1/3/5 review loops ran clean (3 rounds each). After initial ship, field testing surfaced two issues, both fixed and re-verified:

1. **UX refactor** (`97922b8`): gender-buttons + advanced-disclosure-dropdown design was UX-incoherent — picking a specific voice then tapping Male/Female appeared to "reset" the dropdown because no `<option>` had `selected=true` in non-specific modes. Collapsed both widgets into a single `<select>` with two `<optgroup>`s ("Automatic" with Default / Any male / Any female, then "Specific voices"). One source of truth, one selected value at all times. **Supersedes spec §6.1** — read `voice-picker.js` as source of truth for the rendered picker going forward, not the spec.
2. **Sidebar tab persistence** (`f1687df`): sidebar tab (Layers / Route / Import / Admin) was resetting to Layers on close/open — couldn't repro in headless Chrome, likely iOS memory-kill reload or similar device-specific page reset. Shipped defensive localStorage-based persistence + restored-on-DOMContentLoaded-after-initAdmin (adversarial review caught a null-deref and polling-race footgun before merge).

Cameron confirmed **"Working now"** on the live dev stack.

- **Spec (v2, post 5-round adversarial review):** [docs/superpowers/specs/2026-04-21-nav-voice-picker-design.md](docs/superpowers/specs/2026-04-21-nav-voice-picker-design.md) (574 lines, commit `e6c8098`) — §6.1 superseded by the refactor.
- **Plan (historical):** [docs/superpowers/plans/2026-04-21-nav-voice-picker-plan.md](docs/superpowers/plans/2026-04-21-nav-voice-picker-plan.md) (2901 lines, 23 tasks / 7 phases, commit `dceca6e`).
- **Full handoff:** [handoff_20260421_voice_picker_complete](../memory/handoff_20260421_voice_picker_complete.md) — commit-by-commit trail, 4 plan-vs-reality deviations (all Cameron-approved), process wins, test-harness notes.
- **Tests:** 53/53 JS + 12/12 Python (run JS with `node --test --test-force-exit`, the flag that cleanly exits past the `setInterval` in `initBootstrap` — pre-existing "lingering test exit" pain point closable across voice-picker AND nav keep-awake suites now).
- **Ship gate:** §10.3 manual acceptance checklist (14 items across desktop Chrome + iOS Safari + Android Chrome). Cameron runs it when ready; feature does NOT ship to main without explicit go-ahead.
- **Pre-existing wake-lock regression** (parallel nav-session fault): `tests/test_wake_lock_static.py::test_wake_lock_js_exists_and_exports_api` fails because `6bc0ba3` (nav keep-awake session) tightened the guard-clause string but didn't update the static test. Voice-picker work didn't touch wake-lock. Tiny follow-up commit or nav-session fix needed before the next merge to main.

---

**🚧 IN-FLIGHT WORK — NOAA NAIP CONUS expansion (10/39 tasks done, branch `feat/noaa-conus`):**

A multi-session implementation is in progress on the `feat/noaa-conus` worktree. Phases 0+1 are committed (Tasks 1-10, 13 commits, 113 tests passing in worktree). Phases 2-6 (Tasks 11-39) remain. **The next agent is expected to punch through all remaining work** following the subagent-driven-development protocol.

- **Worktree:** `/home/administrator/Code/geographica/.claude/worktrees/feat-noaa-conus`
- **Spec:** [docs/superpowers/specs/2026-04-20-noaa-naip-conus-expansion-design.md](docs/superpowers/specs/2026-04-20-noaa-naip-conus-expansion-design.md) (v2 — post 5-round adversarial review, 15 MUST-FIX incorporated)
- **Plan:** [docs/superpowers/plans/2026-04-20-noaa-naip-conus-expansion.md](docs/superpowers/plans/2026-04-20-noaa-naip-conus-expansion.md) (1796 lines, all 39 tasks specified)
- **Full handoff:** [handoff_20260420_noaa_conus_phase1_complete](../memory/handoff_20260420_noaa_conus_phase1_complete.md) — **READ THIS FIRST** if you are picking up this work. It contains: execution protocol (subagent-driven-development), per-phase model recommendations (Haiku vs. Sonnet), the critical Task 10 runtime finding (tile-index URL pattern doesn't match NOAA's actual Azure layout — fix lands in Phase 5), pacing estimates (~7-8 hours of focused work remaining), risk callouts for the load-bearing Phase 2 tasks, and "what NOT to do" guardrails.
- **Quick resume:** `cd .claude/worktrees/feat-noaa-conus && git log --oneline -15` (HEAD should be `fa13f06`).

The 5-round adversarial review (Codex + 4 distinct-lens subagents) on spec v1 surfaced 15 MUST-FIX issues that would have broken production in at least 3 ways (cross-container import, filter-always-runs timeout failure on TX/CA, checkpoint PK silent dedupe of NAIP border quads). v2 spec addresses all 15. Don't redesign — implement.

---

**🛏️ READY FOR FIELD TESTING — Nav keep-awake (dev HEAD `b127060`, agent-complete 2026-04-20):**

Two-layer screen keep-awake during active nav. Primary: `navigator.wakeLock.request('screen')` on Secure Context. Fallback: first-party `SilentVideoLock` helper (silent 2×2 H.264 MP4, no audio track) for plain HTTP. Generation-counter race safety. iOS PWA bypass. A11y-safe hidden `<video>`. Entirely passive to the driver — no UI indicator, the existing nav banner is the evidence. Voice-continuity under tab-backgrounding is deliberately out-of-scope (future sibling spec).

- **Dev HEAD:** `b127060` (19 commits since spec v1, pushed). Stack is live — `geographica-frontend` bind-mounts serve the new files immediately. No restart needed to test.
- **Spec (v2, post-adversarial):** [docs/superpowers/specs/2026-04-20-nav-keep-awake-design.md](docs/superpowers/specs/2026-04-20-nav-keep-awake-design.md)
- **Plan:** [docs/superpowers/plans/2026-04-20-nav-keep-awake-plan.md](docs/superpowers/plans/2026-04-20-nav-keep-awake-plan.md) (16 tasks, 5 phases)
- **6-round adversarial review** (R1-R5 Claude, R6 Codex cross-validation): [dev/adversarial/2026-04-20-nav-keep-awake-r{1..6}-*.md](dev/adversarial/)
- **Full handoff:** [handoff_20260420_nav_keep_awake](../memory/handoff_20260420_nav_keep_awake.md) — **READ THIS FIRST** when resuming. Contains regression invariants, deferred follow-ups, process findings, and commit-by-commit trail.
- **Tests:** 47/47 green (`node --test frontend/tests/wake-lock/` = 34; `python -m pytest tests/test_wake_lock_static.py` = 13). New `.github/workflows/frontend-ci.yml` running on ubuntu-latest — CI green at `b127060`.

**Resume task — §6.3 manual field acceptance checklist** (spec §6.3, 10 items). This is the ship gate. Agent-complete ≠ ship-complete per the build-robust-features discipline. Checklist items:

1. HTTPS/Tailscale: start nav, set phone down, screen stays on until nav ends.
2. HTTP/LAN: repeat test 1 via plain HTTP origin. Screen stays on via silent-video fallback.
3. Phone-call interruption: answer a call during nav, end it, return — screen still on, nav continues without user action.
4. Arrival: 3-second arrival banner with screen on; normal auto-dim resumes after auto-stop.
5. iOS Low Power Mode: documented-degradation path; no crashes, no console errors. Screen may dim on normal idle (expected per spec §5.19).
6. Screen-reader (VoiceOver/TalkBack) during nav: rotor / swipe navigation MUST NOT expose the hidden `<video>` media control.
7. Voice-TTS with fallback video active (HTTP mode): voice prompts MUST fire normally through the phone speaker while the silent video plays.
8. Voice-TTS with STT active (HTTPS mode): STT start/stop works; nav voice prompts continue.
9. Battery cost informational: 30-min nav session on fallback path vs baseline.
10. Duplicate-tab behavior: two tabs with nav active both hold independent locks.

If all pass → `git switch main && git merge --ff-only dev && git push origin main` (or open PR if preferred). release-please auto-generates the release PR at next trigger.

If any fail → file issues; stay on dev until triaged.

**Known limitation documented in CHANGELOG:** iOS Low Power Mode disables screen keep-awake. Disable LPM or keep phone plugged in for uninterrupted navigation.

**3 minor test-hardening follow-ups** (flagged by Task 9 reviewer, all non-blocking): see handoff section "What's DEFERRED to a future session" #2. None urgent.

---

**Recently completed (2026-04-21 beta-triage marathon — main HEAD `3ba8885`):**

15+ bug fixes shipped in response to a stream of beta-tester screenshots.
Every one was a different class — docker-buildx conflict, websockets
missing from setup venv, corrupt PBF detection, CSRF token staleness,
trailing-slash paths, log-output `undefined` spam, planetiler
`--download` missing, osmium 1.18 flag incompatibility, btn-next stale
text, state-coverage bbox handling (both the "downloads all 11 states
for Phoenix" bug AND the "11 western only, breaks elsewhere" bug it
created), and pipeline scripts invoking bare `python3` from the setup
venv. Full commit-by-commit rundown + invariants + next-session
priorities in [handoff_20260421_beta_triage_marathon](../memory/handoff_20260421_beta_triage_marathon.md).

**In parallel at shutdown:** a separate session is implementing the
exploratory-agent harness per [docs/superpowers/plans/2026-04-20-exploratory-agent-harness.md](docs/superpowers/plans/2026-04-20-exploratory-agent-harness.md).
Tasks 1-9 landed (commits `e8eb158`..`fa17eca`). Task 10 (first real
agent run + findings evidence + README) remains — requires
`ANTHROPIC_API_KEY` on the Pi runner. When resuming, first verify the
parallel session's state before restarting it.

**Regression invariants to NOT break** (all have tests):
- `setup/runner.py` pipeline scripts MUST use `/usr/bin/python3` (not bare `python3`).
- `STATE_BBOXES` MUST have ≥49 entries (48 contiguous US states + DC).
- `_states_intersecting` MUST return empty list (not fallback-to-all) for unsupported bboxes; `/api/start` returns 400 with supported regions listed.
- `setup/requirements.txt` MUST pin `websockets>=12.0`.
- Preflight `python-pipeline-deps` MUST shell to `/usr/bin/python3`.
- CSRF_TOKEN MUST be loaded from `/run/geographica-setup/csrf-token` when present.

**Next-session priorities:**
1. Verify parallel exploratory-agent session completed Task 10 (check `git log origin/main`).
2. Trigger one nightly `--exploratory` run manually to dogfood end-to-end.
3. Review first findings file; convert real bugs to scripted assertions.
4. Audit harness for today's exposed gaps — multi-step pipeline coverage, runtime bash-script verification against fixtures, seed-list updates for exploratory-agent.

---

**⏸ Paused mid-session (2026-04-19 NIGHT) — resume when rested:**
- **NOAA NAIP CONUS expansion — brainstorm paused at Section 3.** Cameron asked for NOAA NAIP (currently AZ-only at [scripts/acquire_imagery.py:88](scripts/acquire_imagery.py#L88)) to become a core competency across all ~48 CONUS states. Brainstorm ran through 9 locked design decisions (UX Option B with Whole state/Custom area tabs, shared top-map hides-by-default architecture, Azure blob listing API for catalog discovery, C+D catalog mechanism, bbox auto-spans intersecting states, no year picker, Nominatim place-names). **Section 3 (pipeline architecture) was presented but not yet Cameron-approved.** Full state + resume instructions in [handoff_20260419_noaa_conus_brainstorm](../memory/handoff_20260419_noaa_conus_brainstorm.md). Visual companion mockups preserved at `.superpowers/brainstorm/869511-1776625800/`. **No code written yet.** Cameron cited 12-hour-day fatigue; default to shorter sessions when resuming.

**Recently completed (2026-04-19 EVE):**
- **GX-01 v2 HAT exploration — full scripted-PCB pipeline stress test.** Designed a 2-board respin (main HAT + separate Front Panel Board) via `superpowers:brainstorming`, then took both boards end-to-end through circuit→layout→autoroute→DRC→Gerbers→BOM→CPL→JLC designer. Both boards pass JLC designer pre-flight as of this session; not fabbed (experimental, waiting on X1100 + LCD dimensions). **Four skill-friction classes surfaced and documented**, with three fixes landed in-session: (1) rotation-correction DB wired into `make_jlc_bundle.py` using the community `cpl_rotations_db.csv`; (2) `connect_pad` helper fixed to handle footprints with duplicate pad numbers (tactile switches, coin cell holders) — previously left half the pads unnetted; (3) JLC PCBA-library verification now uses the correct API endpoint (LCSC bulk catalog ≠ JLC assembly library). Full handoff: [handoff_20260419_gx01_v2_exploration](../memory/handoff_20260419_gx01_v2_exploration.md). Artifacts: [hardware/gx01-adapter-v2/](hardware/gx01-adapter-v2/) + [hardware/gx01-front-panel/](hardware/gx01-front-panel/).

**Recently completed (2026-04-19 PM):**
- **TileServer handoff fix (2026-04-17 B1 closed).** Pipelines now correctly trigger TileServer restart on clean completion — map auto-updates without manual reload. Widened reconciliation guard in `services/search/main.py` + new `tileserver_restarted_at` idempotency stamp. TDD (5 new tests), runtime-validated against the stuck Phoenix NOAA run. See [handoff](../memory/handoff_20260419_tileserver_handoff_fix.md) — commit `f6f7365`. Self-healed both Phoenix `imagery_noaa.mbtiles` + a stuck `elevation.mbtiles` state as a side effect.
- **Setup-remediation plan COMPLETE.** All 50 tasks shipped (57 commits on `dev`). 779 → 784 tests passing. 6 ship-blockers caught by 3-agent review. Pending merge to `main` + docker-ce swap + reboot to land cgroup memory flag. See handoff `handoff_20260419_setup_remediation_complete.md`.

**Recently completed (2026-04-19 AM):**
- **GX-01 adapter HAT — JLC bundle correctness + Path C deferral.** Three iterative rounds with the JLCPCB 3D preview surfaced CPL coordinate bugs (Y-flip + pad-anchor-vs-center), 4 LCSC physical-dimension mismatches, and a mechanical clearance issue with the adapter HAT in the current case. All CPL/LCSC issues fixed; mechanical design (Path A taller case vs. Path C sandwich) formally paused pending X1100 + LCD arrival. See [hardware/gx01-path-c-mockup.html](hardware/gx01-path-c-mockup.html) + [docs/superpowers/plans/2026-04-18-gx-01-pcb-completion.md](docs/superpowers/plans/2026-04-18-gx-01-pcb-completion.md) (Status block at top).
- **Hardware workflow captured as user-level skills** at `~/.claude/skills/`:
  - `jlc-pcba` — triggered by JLCPCB PCBA submission tasks, CPL generation, LCSC part verification. Catches the three pitfall classes from this session (CPL geometry, LCSC physical mismatch, 3D preview interpretation).
  - `kicad-scripted-pcb` — triggered by scripted PCB design with SKiDL/pcbnew/FreeRouting. End-to-end pipeline reference.
  - Both deployed via the RED-GREEN TDD protocol from `superpowers:writing-skills`; cold-agent baseline tests confirmed `jlc-pcba` prevents the pad-anchor bug that would otherwise ship broken CPLs.

**Recently completed (2026-04-18):**
- Version Control Strategy (SemVer + Conventional Commits + release-please). See [VERSIONING.md](VERSIONING.md) and [CHANGELOG.md](CHANGELOG.md).
- **GX-01 personal hardware project** — full spec → fab-ready custom PCB → 3 implementation plans. See below + [hardware/gx01-adapter-pcb/](hardware/gx01-adapter-pcb/).
- **NOAA imagery pipeline remediation** — fresh 3-hunter bug hunt (16 confirmed bugs, 11 new vs the stale 2026-04-16 list), 13 fixes + 3 design decisions committed on `dev`. **Not yet shipped to `main`** — awaiting runtime validation on a Flagstaff-size bbox after the currently-running production pipeline finishes (~2026-04-19). See Task #1 below for resume instructions.

### 0. GX-01 hardware project (IN PROGRESS — waiting on parts)

Cameron's personal Pi 5 dev/demo unit for Geographica. Hybrid FDE PETG + bronze-anodized aluminum desk enclosure housing Pi 5 + Geekworm X1100 (SATA shield, on-order) + X1207 (PoE+UPS, installed) + 21700 cell + AI HAT+ 2 + LC29H + custom adapter HAT + SparkFun GDM12864H 128×64 KS0108B LCD + 2× 40 mm fans.

**Spec:** [docs/superpowers/specs/2026-04-18-gx-01-case-design.md](docs/superpowers/specs/2026-04-18-gx-01-case-design.md) (v3, post-X1100 redesign)

**Plans (ordered by lead time, not execution order):**
1. [Plan 2 — case hardware](docs/superpowers/plans/2026-04-18-gx-01-case-hardware.md) (OpenSCAD + CNC aluminum + assembly + thermal validation)
2. [Plan 3 — PCB fab + assembly](docs/superpowers/plans/2026-04-18-gx-01-pcb-completion.md) (upload Gerbers to OSH Park, DigiKey BOM, solder, bench test)
3. [Plan 1 — status LCD daemon](docs/superpowers/plans/2026-04-18-gx-01-status-lcd-daemon.md) (TDD KS0108B driver, Python systemd service — doesn't need hardware for Phases 0-4)

**Hardware timeline (as of 2026-04-18):**
- Geekworm X1100 SATA shield: arriving **2026-04-19** (Amazon)
- SparkFun LCD-00710 (GDM12864H): **~1 week**
- Custom PCB (OSH Park) + BOM (DigiKey): TBD, order pending Plan 3 Phase 1 kick-off

**Custom adapter HAT PCB:** Fully designed and auto-routed via **FreeRouting**. DRC-clean Gerbers in [hardware/gx01-adapter-pcb/gerbers/](hardware/gx01-adapter-pcb/gerbers/). JLC PCBA bundle at [hardware/gx01-adapter-pcb/jlc_bundle.zip](hardware/gx01-adapter-pcb/jlc_bundle.zip) — verified against JLC's catalog (7/7 parts clean) but **do NOT order yet** pending the Path A vs Path C decision (see Plan 3's "Status: PAUSED" block). To regenerate end-to-end:

```bash
cd hardware/gx01-adapter-pcb
python3 circuit.py          # SKiDL → netlist + ERC
python3 layout.py           # pcbnew API → placed board + GND pour
python3 autoroute.py        # FreeRouting → fully routed board
kicad-cli pcb export gerbers --output gerbers/ \
    --layers "F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts" \
    gx01-adapter.kicad_pcb
kicad-cli pcb export drill --output gerbers/ gx01-adapter.kicad_pcb
python3 ../_shared/verify_lcsc.py --pcb gx01-adapter.kicad_pcb --mapping lcsc_mapping.yaml
python3 ../_shared/make_jlc_bundle.py --pcb gx01-adapter.kicad_pcb --mapping lcsc_mapping.yaml --gerbers gerbers/ --output jlc_bundle.zip
```

**Skills cover this workflow:** when starting any PCB task, relevant skills auto-surface via trigger match — `kicad-scripted-pcb` for the design pipeline, `jlc-pcba` for the JLC handoff. Claude will invoke them via the Skill tool without needing to be told.

**Mechanical clearance decision pending:** the current adapter HAT, as designed to stack on top of the LC29H, has ~11 mm of vertical connector height (J2 + ribbon plug) but the case has only ~10 mm of top-plate clearance. Two paths; neither decided:
- **Path A**: grow case height 95 → 115 mm, keep the current PCB (zero fab cost).
- **Path C sandwich**: flip J2 to B.Cu, hard-solder LCD directly to the HAT (requires PCB respin ~$80 + ~14 days at JLC).

The browser mockup at [hardware/gx01-path-c-mockup.html](hardware/gx01-path-c-mockup.html) has the dimensional analysis; open it locally (or re-start a Python HTTP server) when hardware arrives. Plan 3's Status block has the 5-item resumption checklist.

**Immediate next action when resuming:**
1. When X1100 arrives (expected 2026-04-19): execute [Plan 2 Task 0.5](docs/superpowers/plans/2026-04-18-gx-01-case-hardware.md#task-05-on-x1100-arrival-measure-its-dimensions) — measure X1100 PCB, mounting-hole positions, USB3 bridge length, Pi standoff height. Update `hardware/gx01-case/parameters.scad` (create it per Plan 2 Task 1.1).
2. **Also measure** the 5 items in the Plan 3 Status block to settle Path A vs Path C.
3. In parallel: start Plan 1 Phases 0-4 (status LCD daemon TDD; no hardware needed).
4. Once Plan 1 Phase 2 KS0108B driver is solid + X1100 is verified + Path decision made: order PCB (Plan 3 Phase 1) and BOM (Plan 3 Phase 2).

### 1. Merge `dev` → `main` (UNBLOCKED — runtime validation done)

`dev` is now ~60 commits ahead of `origin/dev` (not pushed). Includes:
- 13 NOAA-pipeline remediation commits (2026-04-18 bug hunt)
- 57 setup-remediation commits (all 50 tasks)
- TileServer handoff fix `f6f7365` (just runtime-validated)
- Task 42 test-isolation fixup `a2cf6dc` (prevents pytest from hijacking `./data` symlink)
- Docker keyring guard broadening `8608b6d`

**Status:** 784 tests passing (up from 624 baseline at start of April 18); same 2 pre-existing M2M failures; 18 pre-existing env errors (need Nominatim up).

**Resume steps:**
1. `git push origin dev` first (60-commit backlog)
2. Optional: one more small-bbox NOAA validation run to confirm the B1→B16 fixes hold at runtime — Flagstaff `-112.0,35.1,-111.5,35.4` (~10 quads, ~10 min)
3. `git switch main && git merge --ff-only dev && git push origin main`
4. Release PR auto-updates; tag `v1.2.0` when ready
5. After merge, queue the known follow-ups below

**Deferred for follow-up (documented in the plan's appendix):**
- **B6** (`merge_mbtiles` re-composites every overlap) and **B8** (erosion-after-overview order) — Chesterton's Fence: both touch code added by commits `e7e3b32` and `1bab361` specifically to fix user-observed artifacts. Need visual-regression testing before the hunter-proposed fixes land. Likely candidates for the v1.2.0 cycle.
- **D4** (two-progress-writer consolidation), **D5** (4-script `fetch_*` consolidation), **D6** (`_noaa_checkpoint` sidecar JSON) — scope; cleanup passes for later.

**New follow-ups from 2026-04-19 PM TileServer handoff fix (all small, high-leverage):**
- **NAIP/Sentinel state-file misnaming (B2 from completion bug hunt):** scripts write to `.pipeline-state.json` instead of `.naip-state.json`/`.sentinel-state.json`. Admin reads the type-specific file → NAIP runs look "interrupted" forever.
- **NAIP/Sentinel never register in TileServer config (B3):** `acquire_naip.py` and `acquire_sentinel.py` never call `add_mbtiles_to_config`. Even a perfect restart would 404 on `/tiles/data/imagery_naip.json`.
- **MapLibre base `imagery` TileJSON cache (B6):** nothing refreshes the base imagery bounds after a basemap pipeline run. Overlay sources are fine (30-s poll).
- **docker.io → docker-ce swap + cgroup_enable=memory reboot:** currently running docker.io 26.1.5; Task 4 canonical is docker-ce (29.x). Memory limits in docker-compose.yml silently discarded until `cgroup_enable=memory` is on cmdline.txt. One reboot lands both.

### 2. Visual Design Identity (MEDIUM)

Meridian design system was attempted and reverted (contrast too low for field use). Revisit with sunlight readability as the #1 constraint.

### 3. Setup Wizard GUI Completion (MEDIUM)

Browser wizard at localhost:8099. Partially built. Needs keyring integration, map bbox selection, pipeline progress.

## Current system state

### Services
7 Docker services + 1 systemd service (keyring agent). All healthy.

### Admin Panel (localhost:8097)
4 tabs: Dashboard, Pipelines (7-source card grid with draw-to-select bbox), Inventory (coverage map + delete), Settings (keyring credentials).

Pipeline features: start/cancel for all modes, 3-stage progress tracking for NOAA (downloaded/reprojected/merged + live ETA), pre-run tile count and time estimates, NAIP quad deduplication for incremental coverage expansion.

### Imagery
- USGS basemap z0-14 (26 GB)
- NOAA NAIP z17 + overviews z0-16 (39 GB, 1.84M tiles, Phoenix + northern AZ as of 2026-04-19 run)
- M2M z19 partial
- Pipeline container has numpy/rasterio/scipy for in-process tile rendering

### Companion Utility
Separate repo at `/home/administrator/Code/geographica-companion`. Cross-platform desktop tool for fast imagery download/processing, SCP to Pi. Same pipeline code as main repo.

### Security
GNOME Keyring via host-side agent. tmpfs secrets for pipeline containers. No plaintext credentials.

### Tests
- **`main`:** 585 pass (after versioning adoption adds 6 tests for CI config); 2 pre-existing M2M failures, 9 pre-existing OSM POI errors.
- **`dev`:** 784 pass (NOAA remediation + setup remediation + TileServer handoff fix); same 2 pre-existing M2M failures; the 9 OSM POI errors were resolved as a side effect of the setup conftest.py asyncio fix. 18 Nominatim-env errors require `docker compose up` to clear.
- Run: `python -m pytest tests/ services/search/tests/ -v`

### Key architectural details (describes `main`; dev has remediation changes not yet shipped)
- Combined imagery: Hybrid checkbox removed, basemap auto-shows, 28 paint overrides, tileSize:256
- Pipeline admin: card grid with non-destructive catalog polling (no DOM rebuild on poll)
- NOAA pipeline: 3-stage parallel (8 downloaders, 4 reproject workers, 1 serial merger), rasterio in-process (not GDAL CLI), GDAL_CACHEMAX=64, quad-level checkpoint dedup
- TileServer: source unregistered during pipeline writes, WAL→DELETE journal mode conversion on completion *(on dev: D3 keeps WAL mode permanently; 2026-04-19 PM fix also triggers TileServer restart on clean completion via `tileserver_restarted_at` idempotency stamp)*
- Keyring: host-side daemon on Unix socket, search container communicates via bind-mounted socket
- Pipeline container: 4 GB memory limit, bind-mounted scripts (:ro)
- Release automation: `release-please` GitHub Action on push to main; v1.1.0 Release PR #2 currently accumulating commits pending merge
