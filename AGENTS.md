# Geographica

> **Note:** This file mirrors [CLAUDE.md](CLAUDE.md) for non-Claude agent
> harnesses (Codex, etc.). When updating one, update the other to match.
> The substantive content is identical.

Offline-first GIS platform for AREDN mesh networks, running on Raspberry Pi 5.

## Project structure

- `docker-compose.yml` — 7 persistent services + on-demand pipeline (tileserver, valhalla, nominatim, gps, search, stt, frontend)
- `services/gps/` — FastAPI GPS WebSocket service (reads gpsd)
- `services/search/` — FastAPI unified search (Nominatim + SQLite FTS5 POI + city-aware spatial search + geocode)
- `services/stt/` — FastAPI speech-to-text service (Whisper, CPU + NPU backends)
- `scripts/` — Offline data pipeline (imagery acquisition, POI indexer, elevation, public lands, county index)
- `frontend/` — Vanilla JS + MapLibre GL JS single-page app
- `nginx/` — Reverse proxy config with sub_filter URL rewriting
- `tileserver/` — TileServer GL config and styles (positron, darkmatter, hybrid)
- `setup/` — Browser-based setup wizard (FastAPI on localhost:8099, dark mode, 5-step guided deployment)
- `bootstrap.sh` — System prerequisites script (sudo): apt install, docker group, data directory
- `setup.sh` — Wizard launcher: creates venv, installs deps, starts FastAPI server
- `data/` — Symlink to /srv/geographica/data/ (gitignored) MBTiles, PBF, SQLite databases

## Commands

```bash
# Data pipeline (run once during setup, requires internet)
pip install -r scripts/requirements.txt
python scripts/build_poi_index.py --bbox "-124.8,31.3,-102.0,49.0" --states "AZ,CA,CO,ID,MT,NV,NM,OR,UT,WA,WY" --output /srv/geographica/data/poi.sqlite
python scripts/download_elevation.py --bbox "-124.8,31.3,-102.0,49.0" --zoom 0-14 --output /srv/geographica/data/elevation.mbtiles
python scripts/acquire_imagery.py --mode tnmaccess --bbox "-124.8,31.3,-102.0,49.0" --output /srv/geographica/data/imagery.mbtiles

# OSM POI extraction (run once, requires osmium)
python3 scripts/build_osm_pois.py \
  --pbf /srv/geographica/data/valhalla/western-us.osm.pbf \
  --output /srv/geographica/data/poi.sqlite \
  --bbox "-124.8,31.3,-102.0,49.0"

# Stack management
docker compose build         # build GPS, search, and STT service images
docker compose up -d         # start all services
docker compose ps            # check service health
docker compose logs -f gps   # tail GPS service logs
docker compose down          # stop everything
```

## Hardware

- Raspberry Pi 5, 16 GB RAM
- Intel D3-S4610 896 GB SATA SSD (~400 MB/s, boot + data drive)
- Waveshare LC29H GPS hat (gpsd on /dev/ttyAMA0) or USB GPS dongle
- Hailo 10H NPU (Phase 2, AI voice commands)

## Testing

```bash
# All tests (from repo root — includes parser, geocode, endpoint, pipeline tests)
python -m pytest tests/ -v

# Python service tests (individual)
cd services/gps && python -m pytest
cd services/search && python -m pytest

# Data pipeline smoke test
python scripts/build_poi_index.py --bbox "-112.1,-33.4,-112.0,33.5" --output /tmp/test_poi.sqlite

# Full stack E2E (requires Docker stack running)
# TODO: Playwright tests
```

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health

## Brainstorming preferences

- Always use the visual companion (browser mockups) during brainstorming — don't ask, just launch it
- Token budget is not a concern during design phases — be thorough

## Project ethos

Geographica is Cameron's learning sandbox for AI-assisted development
techniques — custom skills, adversarial review, multi-agent teaming,
capability mapping — that he plans to transfer to high-stakes projects at
his employer. The shipped software matters, but **professional-development
outcomes are a first-class goal alongside features.**

Implications:
- Process rigor > raw velocity. Do the right thing, not the fast thing.
- Explain when/what for new workflows so Cameron builds transferable
  skill.
- Prefer patterns that generalize to multi-developer / higher-stakes
  environments.
- Signal professional polish even at A-audience scale — the surface area
  of the repo (commits, CHANGELOG, versioning, CI) teaches Cameron what
  "good" looks like and builds habits that transfer.

## Commit and release discipline

- Match the commit `type:` to the table in [CONTRIBUTING.md](CONTRIBUTING.md).
  Never use `fix:` for docs fixes or `feat:` for internal refactors.
- Before committing a change that touches `/srv/geographica/data/` schema,
  `docker-compose.yml`, `config/*.json`, keyring format, or bootstrap
  assumptions, add `!` suffix and a `BREAKING CHANGE:` footer with a
  one-line user-facing explanation.
- Prefer scoped commits (`feat(pipeline): ...`) when the change is
  localized to one subsystem. Recommended scopes: `pipeline`, `tileserver`,
  `search`, `gps`, `stt`, `admin`, `frontend`, `setup`, `keyring`, `docs`.
- Never ship a release manually — merging the `release-please` Release PR
  is the only release mechanism. If you need to ship and no Release PR
  exists, the last commits must not have included a `feat:` / `fix:` /
  `perf:` — that's fine, it means nothing user-visible has changed.
- On a hotfix, follow the runbook in [VERSIONING.md](VERSIONING.md) §Hotfix
  recipe exactly.
- Update `dev/implementation-log.md` after any significant work item: plan
  executed, feature shipped, bug hunt cycle completed, adversarial review
  completed. Entry goes at the top, reverse-chronological, keyed by
  date + topic.
