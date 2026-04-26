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

**🎉 SHIPPED — v2.0.0 (2026-04-26):** 363+ commits merged from `dev` to `main` via PR#14, release-please opened + Cameron merged the v2.0.0 release PR (PR#15), tag `v2.0.0` published, CHANGELOG regenerated. Major bump triggered by `feat(noaa)!:` commit removing the `--year` CLI flag in favor of `--state`/`--bbox`. CI green on main. The major release bundles:

- Nav voice TTM redesign (full architecture replacement; band-aid removed)
- Ruler / measurement tool Phases 0–2 (explicit-activation model, field-verified)
- README overhaul (838-line monolith → 5-doc set + ROI pitch + 6 captured screenshots + cost-methodology adversarial cycle catching 6-8× cost overstatement)
- NOAA CLI breaking change (`--year` removed)
- Sidebar BFCache restoration on iOS
- Voice picker UX refactor + persistence
- Wake-lock / screen keep-awake feature (HTTPS + HTTP fallback paths)
- Setup wizard remediation (50 tasks)
- Many other features and bug fixes — see [CHANGELOG.md](CHANGELOG.md) v2.0.0 section

**🔄 OPEN — back-merge release commits to dev:** main is 3 commits ahead of dev (release-please bot's manifest+CHANGELOG bump + the two merge commits). Standard post-release-please dance — should be back-merged to dev before the next dev-side push:

```bash
git switch dev
git merge origin/main           # standard merge commit; no conflicts expected since dev's changes
                                 # all came in via PR#14 and are now main's content
git push origin dev
```

---

### 1. Multi-state NAIP polygon fix (queued post-v2.0.0)

`scripts/common/state_bboxes.py::states_intersecting()` uses axis-aligned state bounding boxes, which overlap substantially in corners. Small bboxes near state corners (SW NV, NW AZ, NE CA, etc.) trigger a false-positive multi-state error in the NOAA NAIP pipeline. Cameron approved **Option B** (centroid + polygon containment heuristic) for the fix cycle. See memory `project_state_bbox_vs_polygon_distinction.md` for full context, workarounds, and three implementation paths.

**Surface area:** [scripts/common/state_bboxes.py](scripts/common/state_bboxes.py) + the multi-state guard at [scripts/acquire_imagery.py:2237-2241](scripts/acquire_imagery.py#L2237-L2241). Adds a state-polygon dependency (Census TIGER or Natural Earth shapefiles).

**Process:** fresh feature cycle (spec → adversarial review → plan → execute via subagent-driven-development).

### 2. GPS source default to "this device" (queued post-v2.0.0)

GPS navigation should auto-prefer the client device's `navigator.geolocation` when the browser exposes it (a phone accessing Geographica via the AREDN mesh wants its own GPS, not the host Pi's gpsd). Currently defaults to Pi gpsd regardless. See memory `project_gps_default_to_device_when_available.md` for design notes — browser-side capability detection on first nav entry, persist user manual override in localStorage.

**Surface area:** GPS source selector in the nav UI + initialization logic.

### 3. Ruler / measurement tool Phases 3–5 (23 tasks remain)

Phases 0–2 shipped in v2.0.0. Phase 3 onward (8 tasks for Phase 3, more for 4–5) remain per the plan at [docs/superpowers/plans/2026-04-24-ruler-plan.md](docs/superpowers/plans/2026-04-24-ruler-plan.md). Spec at [docs/superpowers/specs/2026-04-24-ruler-design.md](docs/superpowers/specs/2026-04-24-ruler-design.md). The "north star" for spatial tools is captured as memory `project_geographica_spatial_tools_north_star.md` — Ruler/Path/Polygon converge on Google Earth's create/refine/resolve UX with KMZ persistence as the resolve target.

### 4. README close-out (T6.1, T6.2, T6.4, T7) — light, quick

After the v2.0.0 ship, three small README polish items remain:

- **T6.1**: composite `docs/og-image.png` (1200×630 social-share card) from hero + favicon + wordmark via Pillow. Agent can do unilaterally.
- **T6.2**: upload OG image to repo Settings → Social preview. Cameron-only (GitHub UI step).
- **T6.4**: confirm Mermaid arch diagram renders correctly on github.com (essentially done — Cameron called the interactive flowchart "super high production value" in the 2026-04-25 session).
- **T7.1/T7.2**: Cameron reads all 5 docs end-to-end (might already be done implicitly), then a final impl-log close-out entry.

Phone-frame composite for `mobile-nav.png` (T5.9) is optional polish; current desktop-framed mobile shot reads fine on github.com.

### 5. NOAA NAIP CONUS expansion (10/39 tasks done — Phases 2–6 remain)

Multi-session implementation paused on `feat/noaa-conus`. Phases 0+1 committed (Tasks 1-10, 13 commits, 113 tests passing). Phases 2-6 (Tasks 11-39) remain. **Worktrees BANNED in this project per CLAUDE.md** — when resuming, do NOT use `.claude/worktrees/feat-noaa-conus/`; check out the same branch in the main repo instead.

- **Spec:** [docs/superpowers/specs/2026-04-20-noaa-naip-conus-expansion-design.md](docs/superpowers/specs/2026-04-20-noaa-naip-conus-expansion-design.md) (v2 — 15 MUST-FIX issues from 5-round adversarial review incorporated)
- **Plan:** [docs/superpowers/plans/2026-04-20-noaa-naip-conus-expansion.md](docs/superpowers/plans/2026-04-20-noaa-naip-conus-expansion.md) (1796 lines, all 39 tasks specified)
- **Full handoff:** [handoff_20260420_noaa_conus_phase1_complete](../memory/handoff_20260420_noaa_conus_phase1_complete.md) — execution protocol, per-phase model recommendations, the critical Task 10 runtime finding (tile-index URL pattern doesn't match NOAA's actual Azure layout — fix lands in Phase 5), pacing estimates, risk callouts, "what NOT to do" guardrails.

The multi-state polygon fix (item 1 above) is a sibling concern that may want to land before/alongside CONUS expansion since multi-state dispatch becomes the common case.

### 6. Deferred bug-hunt follow-ups (carried forward from pre-v2.0.0)

Documented in plan appendices and superseded handoffs; not blocking but worth tracking:

- **B6** (`merge_mbtiles` re-composites every overlap) and **B8** (erosion-after-overview order) — Chesterton's Fence (both touch user-observed-artifact fixes from `e7e3b32` and `1bab361`). Need visual-regression testing before the hunter-proposed fixes land.
- **NAIP/Sentinel state-file misnaming**: scripts write to `.pipeline-state.json` instead of `.naip-state.json`/`.sentinel-state.json`. Admin reads the type-specific file → NAIP runs look "interrupted" forever.
- **NAIP/Sentinel never register in TileServer config**: `acquire_naip.py` and `acquire_sentinel.py` never call `add_mbtiles_to_config`. Even a perfect restart 404s on `/tiles/data/imagery_naip.json`.
- **MapLibre base `imagery` TileJSON cache**: nothing refreshes the base imagery bounds after a basemap pipeline run. Overlay sources are fine (30-s poll).
- **docker.io → docker-ce swap + `cgroup_enable=memory` reboot**: currently running docker.io 26.1.5; canonical is docker-ce (29.x). Memory limits in docker-compose.yml silently discarded until `cgroup_enable=memory` is on cmdline.txt. One reboot lands both.

---


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
- **`main` (v2.0.0):** large suite, mix of broad-coverage + per-feature; CI green on `frontend-ci` workflow as of 2026-04-26 release. Ruler suite: 90/90 green. Wake-lock: 47/47 green. Voice picker: 53/53 JS + 12/12 Python. Run: `python -m pytest tests/ services/search/tests/ -v`. Pre-existing failures: 2 M2M (env-dependent), 18 Nominatim-env (need `docker compose up`).
- **`dev`:** parity with main minus the 3 post-release commits; back-merge pending. After back-merge, dev tracks main with whatever new in-flight feature work has landed since 2026-04-26.

### Key architectural details
- Combined imagery: Hybrid checkbox removed, basemap auto-shows, 28 paint overrides, tileSize:256
- Pipeline admin: card grid with non-destructive catalog polling (no DOM rebuild on poll)
- NOAA pipeline: 3-stage parallel (8 downloaders, 4 reproject workers, 1 serial merger), rasterio in-process (not GDAL CLI), GDAL_CACHEMAX=64, quad-level checkpoint dedup. Post-processing drains a persistent SQLite journal (`_overview_work_queue`) — incremental rebuilds, no nuke+rebuild
- TileServer: source unregistered during pipeline writes, WAL mode preserved, restart triggered on clean completion via `tileserver_restarted_at` idempotency stamp
- Keyring: host-side daemon on Unix socket, search container communicates via bind-mounted socket
- Pipeline container: 4 GB memory limit, bind-mounted scripts (:ro)
- Nav voice: time-to-maneuver model (replaced distance-thresholds), prompt-suppression floor, voice-picker single-source-of-truth `<select>` with auto/specific optgroups
- Wake-lock: navigator.wakeLock primary on Secure Context, silent-video fallback on plain HTTP
- Ruler: explicit-activation model with `[+ New measurement]` button, `body.ruler-active` sidebar pinning, vertex drag with rAF-coalesced source updates
- Release automation: `release-please` GitHub Action on push to main; manifest at `.github/.release-please-manifest.json` (currently `2.0.0`); workflow opens release PRs that bump the manifest + regenerate CHANGELOG, Cameron merges them to ship
