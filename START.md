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

2. **Read CLAUDE.md** in the repo root — project structure, commands, hardware specs, skill routing.

3. **Data lives OUTSIDE the repo** at `/srv/geographica/data/` (symlinked from `data/`). Never create large files inside the git repo tree.

4. **Git push works from terminal** — `gh auth git-credential` is configured.

5. **Never stop the production stack** (`docker compose down`) without explicit user permission.

## What to work on next

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

**Custom adapter HAT PCB:** Fully designed and auto-routed via **FreeRouting**. DRC-clean Gerbers in [hardware/gx01-adapter-pcb/gerbers/](hardware/gx01-adapter-pcb/gerbers/). To regenerate end-to-end:

```bash
cd hardware/gx01-adapter-pcb
python3 circuit.py          # SKiDL → netlist + ERC
python3 layout.py           # pcbnew API → placed board + GND pour
python3 autoroute.py        # FreeRouting → fully routed board
kicad-cli pcb export gerbers --output gerbers/ \
    --layers "F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts" \
    gx01-adapter.kicad_pcb
kicad-cli pcb export drill --output gerbers/ gx01-adapter.kicad_pcb
```

**Immediate next action when resuming:**
1. When X1100 arrives (expected 2026-04-19): execute [Plan 2 Task 0.5](docs/superpowers/plans/2026-04-18-gx-01-case-hardware.md#task-05-on-x1100-arrival-measure-its-dimensions) — measure X1100 PCB, mounting-hole positions, USB3 bridge length, Pi standoff height. Update `hardware/gx01-case/parameters.scad` (create it per Plan 2 Task 1.1).
2. In parallel: start Plan 1 Phases 0-4 (status LCD daemon TDD; no hardware needed).
3. Once Plan 1 Phase 2 KS0108B driver is solid + X1100 is verified: order PCB (Plan 3 Phase 1) and BOM (Plan 3 Phase 2).

### 1. NOAA Pipeline Remediation — ship to main (BLOCKED on production pipeline finishing)

13 bug fixes + 3 design decisions committed on `dev` (not yet on `main`) from the 2026-04-18 fresh bug-hunt cycle. Reports at [dev/bug-hunts/2026-04-18-noaa-imagery-pipeline-consolidated.md](dev/bug-hunts/2026-04-18-noaa-imagery-pipeline-consolidated.md). Plan at [dev/plans/2026-04-18-noaa-imagery-pipeline-remediation-plan.md](dev/plans/2026-04-18-noaa-imagery-pipeline-remediation-plan.md). Narrative log at [dev/implementation-log.md](dev/implementation-log.md) (2026-04-18 NOAA remediation entry).

**Status:** all 13 commits on `dev`, 624 tests passing (0 regressions), but **not yet on `main`** — deferred pending runtime validation. Production NOAA pipeline (~494-quad run started 2026-04-17) is currently running and will finish ~2026-04-19; blocks the Pi from running a validation bbox.

**Resume steps when you come back:**
1. Confirm production pipeline finished cleanly (check admin panel / TileServer status)
2. Run `python -m pytest tests/ services/search/tests/ -v` — expect **624 pass, 2 pre-existing M2M fails, 9 pre-existing OSM POI errors**
3. Validate new code on a small bbox (Flagstaff `-112.0,35.1,-111.5,35.4`, ~10 quads). Verify: pipeline completes, tiles render at all zooms, cancel mid-Phase-5 is honored, resume run doesn't re-erode
4. If validation passes: `git switch main && git merge --ff-only dev && git push origin main` — Release PR #2 auto-updates with the 13 new fixes
5. If validation reveals an issue: identify the specific task → `git revert <sha>` on dev → iterate
6. After v1.1.0 ships, revisit B6 + B8 with visual-regression tests

**Deferred for follow-up (documented in the plan's appendix):**
- **B6** (`merge_mbtiles` re-composites every overlap) and **B8** (erosion-after-overview order) — Chesterton's Fence: both touch code added by commits `e7e3b32` and `1bab361` specifically to fix user-observed artifacts. Need visual-regression testing before the hunter-proposed fixes land. Likely candidates for the v1.2.0 cycle.
- **D4** (two-progress-writer consolidation), **D5** (4-script `fetch_*` consolidation), **D6** (`_noaa_checkpoint` sidecar JSON) — scope; cleanup passes for later.

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
- NOAA NAIP z17 + overviews z0-16 (8.6 GB, 419K tiles, northern AZ)
- M2M z19 partial
- Pipeline container has numpy/rasterio/scipy for in-process tile rendering

### Companion Utility
Separate repo at `/home/administrator/Code/geographica-companion`. Cross-platform desktop tool for fast imagery download/processing, SCP to Pi. Same pipeline code as main repo.

### Security
GNOME Keyring via host-side agent. tmpfs secrets for pipeline containers. No plaintext credentials.

### Tests
- **`main`:** 585 pass (after versioning adoption adds 6 tests for CI config); 2 pre-existing M2M failures, 9 pre-existing OSM POI errors.
- **`dev`:** 624 pass (remediation cycle adds 28 tests + 1 correction); same 2 + 9 pre-existing.
- Run: `python -m pytest tests/ services/search/tests/ -v`

### Key architectural details (describes `main`; dev has remediation changes not yet shipped)
- Combined imagery: Hybrid checkbox removed, basemap auto-shows, 28 paint overrides, tileSize:256
- Pipeline admin: card grid with non-destructive catalog polling (no DOM rebuild on poll)
- NOAA pipeline: 3-stage parallel (8 downloaders, 4 reproject workers, 1 serial merger), rasterio in-process (not GDAL CLI), GDAL_CACHEMAX=64, quad-level checkpoint dedup
- TileServer: source unregistered during pipeline writes, WAL→DELETE journal mode conversion on completion *(on dev: D3 keeps WAL mode permanently, removes the journal-mode flip)*
- Keyring: host-side daemon on Unix socket, search container communicates via bind-mounted socket
- Pipeline container: 4 GB memory limit, bind-mounted scripts (:ro)
- Release automation: `release-please` GitHub Action on push to main; v1.1.0 Release PR #2 currently accumulating commits pending merge
