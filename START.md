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

### 1. NOAA Pipeline Deferred Fixes (HIGH — from adversarial review)

9 deferred items from the 8-agent adversarial review (2026-04-16). See
`~/.claude/projects/-home-administrator-Code-geographica/memory/handoff_20260417.md`
for the full list. Key items: checkpoint atomicity gap, atomic temp-file downloads,
disk-full preflight, parallelized tile rendering.

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
579 passing (2 pre-existing M2M failures, 9 pre-existing OSM POI errors). `python -m pytest tests/ services/search/tests/ -v`

### Key architectural details
- Combined imagery: Hybrid checkbox removed, basemap auto-shows, 28 paint overrides, tileSize:256
- Pipeline admin: card grid with non-destructive catalog polling (no DOM rebuild on poll)
- NOAA pipeline: 3-stage parallel (8 downloaders, 4 reproject workers, 1 serial merger), rasterio in-process (not GDAL CLI), GDAL_CACHEMAX=64, quad-level checkpoint dedup
- TileServer: source unregistered during pipeline writes, WAL→DELETE journal mode conversion on completion
- Keyring: host-side daemon on Unix socket, search container communicates via bind-mounted socket
- Pipeline container: 4 GB memory limit, bind-mounted scripts (:ro)
