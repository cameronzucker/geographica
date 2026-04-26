# Geographica

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

## Extended capabilities available on this dev Pi

### OpenAI Codex CLI — for `build-robust-features`' "at least one adversarial round via Codex" requirement

**Codex IS installed on this Pi. It is NOT on `$PATH`.** `which codex` returns nothing, which is why assistants keep missing it. Invoke via `npx`:

```bash
# Non-interactive agent call
npx --yes @openai/codex exec "<prompt>"        # alias: codex e

# Purpose-built code review (what adversarial rounds typically want)
npx --yes @openai/codex review --commit <SHA> "<attack-angle prompt>"
npx --yes @openai/codex review --uncommitted "<prompt>"      # staged + unstaged + untracked
npx --yes @openai/codex review --base main    "<prompt>"     # current branch vs base

# Optional: stdin-piped prompt
cat spec.md | npx --yes @openai/codex exec -
```

- **Version on this Pi:** v0.118.0 (check: `npx --yes @openai/codex --version`).
- **Authentication:** ChatGPT-mode, cached at `~/.codex/auth.json`. Already authenticated — no setup needed.
- **Cached at:** `~/.npm/_npx/c8ab89660c602c20/node_modules/@openai/codex/`. Stays cached across runs; the `npx --yes` prefix won't redownload.
- **When to use:** when a workflow (notably `superpowers:build-robust-features`) explicitly calls for "at least one round via Codex." Substitute Claude agents only when this is genuinely unavailable — it isn't unavailable here.
- **MCP-server mode:** `npx --yes @openai/codex mcp-server` — expose Codex as an MCP server if you want the main loop to call it like a tool.

Write adversarial-review output to `dev/adversarial/<date>-<topic>-codex.md` to match the existing naming pattern.

### `url-to-markdown` skill — fetch FULL webpages, not summaries

Installed at `/home/administrator/.claude/skills/url-to-markdown/`. Invoke via the `Skill` tool (name: `url-to-markdown`) or directly:

```bash
python3 /home/administrator/.claude/skills/url-to-markdown/scripts/bootstrap.py "https://url" --json --out /tmp
```

**Prefer this over `WebFetch` whenever you need the full content of a page** (product pages, docs, wikis, articles). `WebFetch` runs the page through a summarizer that can drop critical details like dimensions, pin mappings, or spec tables. `url-to-markdown` downloads the raw content, converts to markdown with YAML frontmatter, and writes to disk so you can read it verbatim.

Returns a JSON envelope; parse the `output_path` and then `Read` the resulting `.md` file. Handles Cloudflare-class bot protection via TLS fingerprint impersonation. Gracefully reports paywalls, SPAs, PDFs, and feeds instead of producing garbage.

### PCB design pipeline (KiCad 9 + SKiDL + FreeRouting)

Installed + proven end-to-end on the Pi. For custom hardware design — breakouts, adapter HATs, small sensor modules — run:

```bash
# From a PCB project directory (e.g. hardware/gx01-adapter-pcb/):
python3 circuit.py          # SKiDL describes circuit; outputs netlist + ERC
python3 layout.py           # pcbnew Python API places footprints + draws zones
python3 autoroute.py        # FreeRouting 2.1.0 auto-routes all signals
kicad-cli pcb drc --output drc-report.txt --format report gx01-adapter.kicad_pcb
kicad-cli pcb export gerbers --output gerbers/ --layers "F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts" gx01-adapter.kicad_pcb
kicad-cli pcb export drill --output gerbers/ gx01-adapter.kicad_pcb
```

End-to-end ~90 seconds from Python source to DRC-clean Gerbers for a ~20-net 2-layer board. The canonical reference implementation is `hardware/gx01-adapter-pcb/` — copy its structure for new designs.

**Key gotcha**: after FreeRouting's SES import, call `pcbnew.ZONE_FILLER(board).Fill(board.Zones())` before saving. Without this, the pre-routing zone fill is stale and DRC flags zone-clearance violations.

**Dependencies verified installed on this machine**: `kicad` 9.0.2, `gerbv` 2.10, `default-jre-headless` 21, `skidl` 2.2.3 (via `pip install --user --break-system-packages skidl`), `pcbnew` Python bindings (ships with kicad apt package), FreeRouting 2.1.0 JAR vendored at `hardware/gx01-adapter-pcb/tools/freerouting-2.1.0.jar`.

**For PCB fabrication with hand-assembly**: upload Gerbers zip to OSH Park (~$5 for 3 boards, 2-week US-domestic turnaround). For populated boards / assembly service, JLCPCB PCBA accepts KiCad Gerbers + BOM CSV (see handoff or ask for guidance).

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

## Agent identity — pick a moniker at session start

**At the very start of every session** (after reading START.md and the most-recent handoff, before taking any action on the repo), pick a short moniker for yourself and state it in your first user-facing message. The moniker:

- Must be a single word, lowercase, no spaces, no punctuation.
- Must be **ctrl+F-friendly** — avoid words that already appear in the codebase/docs (run `grep -rci <name> .` mentally; if there are many hits, pick something else). Plant/animal/geographic nouns work well (`juniper`, `hemlock`, `sparrow`, `flint`).
- Avoid human first names to prevent confusion with Cameron, beta testers, or co-authors.
- Persists for the entire session — do not change it mid-session.
- Passes through to every subagent you dispatch: include `"You are agent <moniker>; use this in your commit trailers."` in each Agent tool prompt so subagent-authored commits are grep-discoverable too.

**Include the moniker in every git action as a commit trailer:** `Agent: <moniker>` on its own line in the commit message, alongside the existing `Co-Authored-By:` trailer.

```
<subject>

<body paragraphs>

Agent: juniper
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

**Also include in:** branch names when creating them (`agent-<moniker>/<topic>` for throwaway branches; regular `feat/` / `fix/` prefixes are fine for shared feature branches but still add the trailer inside commits), and PR titles if you open one (`[juniper] <subject>`).

**Why:** triage + forensics. When a session goes sideways — a mysterious `git reset --hard`, a stale regression, an unclear commit authorship — Cameron needs to grep the commit graph for "which agent did this" without reconstructing it from timestamps. `git log --grep="^Agent: juniper"` returns the full trail for this session. `git log --all --grep="^Agent:"` enumerates every agent that has ever touched the repo.

**If you forget to set a moniker early in the session:** pick one now and apply it to all forward commits. Do not retroactively amend earlier commits (amending shared/recent commits is banned — see below).

## Git workflow — worktrees are BANNED

Do NOT use `git worktree` in this project. All branch work happens via `git checkout` in the main repo at `/home/administrator/Code/geographica`.

**Rationale:** Two near-misses in 2026-04 where subagents `cd`'d out of a worktree and performed destructive operations on the main repo's branch (one `git reset --hard` wiped 6+ commits from `dev`'s tip pointer; recovered via reflog). Worktree topology multiplies the blast radius of "subagent forgets which checkout it's in" errors. See [docs/pitfalls/implementation-pitfalls.md](docs/pitfalls/implementation-pitfalls.md) §14 for the full write-up and recovery posture.

**If you encounter an existing worktree** (e.g., `.claude/worktrees/<name>/`): do NOT use it. Check out the same branch in the main repo instead, and suggest that the user remove the worktree with `git worktree remove`.

**If a session handoff tells you to "work in the worktree at X"**: override that instruction. Check out the branch in the main repo, and flag the deviation to the user.

## Git workflow — destructive commands are BANNED

Do NOT run destructive git commands. There is never a legitimate reason for an agent to run these unprompted. If you think you need one, **stop and ask the user**.

**Banned commands (no exceptions without explicit user authorization for this specific call):**
- `git reset --hard <ref>` — destroys uncommitted work AND rewinds the branch tip. Use `git revert <commit>` for an additive undo, or ask the user which specific file to restore with `git checkout -- <path>`.
- `git push --force` / `git push -f` / `git push --force-with-lease` — rewrites remote history. If you need to replace a pushed commit, open a new PR or ask.
- `git checkout -- .` / `git restore .` / `git clean -f` / `git clean -fd` — wipes entire working-tree state. If you want to discard one file, name it explicitly after checking with the user.
- `git branch -D <branch>` / `git branch --delete --force` — force-deletes a branch even if unmerged. Use `git branch -d`, which refuses to delete unmerged branches.
- `git rebase -i` with squash/fixup/drop on shared commits — rewrites history. (`--no-edit` is not a valid `git rebase` flag and should never be passed.)
- `git commit --amend` on any commit that has been pushed OR that was authored by someone else. Always create a **new** commit to correct earlier work.
- `git reflog expire --expire=now` / `git gc --prune=now` — strips the safety net that would let us recover from the commands above.
- `git filter-branch` / `git filter-repo` — mass history rewrite.
- `--no-verify` (skips hooks) / `--no-gpg-sign` / `-c commit.gpgsign=false` — bypasses the project's commit gates. The hooks exist for a reason; if one fails, fix the root cause instead of skipping.

**Rationale:** On 2026-04-20, a subagent ran `git reset --hard feat/noaa-conus` on the main checkout's `dev` branch, wiping 7 commits — including a runtime-validated bug fix that had been shipped to the live stack. Recovery took one `git merge` with manual conflict resolution, but only because all commits were still reachable via reflog; two weeks later and `git gc` would have pruned them permanently. Agents have no legitimate workflow that requires destructive operations; the pattern is always "something went wrong, let me start over" — which is a cue to **ask the user**, not reset.

**If you think you need one of these:** the correct action is to surface the situation to the user with a proposed non-destructive alternative. See [docs/pitfalls/implementation-pitfalls.md](docs/pitfalls/implementation-pitfalls.md) §15 for the recovery posture and non-destructive alternatives for common scenarios.

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
