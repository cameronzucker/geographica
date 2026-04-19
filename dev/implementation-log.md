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
