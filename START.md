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

### 1. Companion Data Ingestion Utility (HIGH — spec ready)

**Spec:** `docs/superpowers/specs/2026-04-15-companion-utility-design.md`

Cross-platform desktop tool for fast imagery download/processing on a workstation, then SCP to Pi. Needs adversarial review → plan → execute.

### 2. Visual Design Identity (MEDIUM)

Meridian design system was attempted and reverted (contrast too low for field use). Revisit with sunlight readability as the #1 constraint.

### 3. Setup Wizard GUI Completion (MEDIUM)

Browser wizard at localhost:8099. Partially built. Needs keyring integration, map bbox selection, pipeline progress.

## Current system state

### Services
7 Docker services + 1 systemd service (keyring agent). All healthy.

### Admin Panel (localhost:8097)
4 tabs: Dashboard, Pipelines (7-source card grid), Inventory (coverage map + delete), Settings (keyring credentials)

### Imagery
USGS basemap z0-14 (26 GB), NOAA NAIP z14-18 (3 GB, 346K tiles with overviews), M2M z19 partial.

### Security
GNOME Keyring via host-side agent. tmpfs secrets for pipeline containers. No plaintext credentials.

### Tests
535 passing. `python -m pytest tests/ -v`

### Key architectural details
- Combined imagery: Hybrid checkbox removed, basemap auto-shows, 28 paint overrides, tileSize:256
- Pipeline admin: card grid with non-destructive catalog polling (no DOM rebuild on poll)
- TileServer: source unregistered during pipeline writes to prevent crash-looping
- Keyring: host-side daemon on Unix socket, search container communicates via bind-mounted socket
