# NOAA NAIP CONUS Expansion — Design Spec

**Date:** 2026-04-20
**Status:** Draft — brainstorm complete, 5-round adversarial review pending
**Scope:** Expand NOAA NAIP imagery support from Arizona-only to all 48 contiguous US states + DC. Introduce a bbox-based custom-area mode alongside the existing whole-state mode. Replace the single-entry hardcoded catalog with a live-refreshable versioned catalog backed by the Azure blob listing API.
**Files (new):** `config/noaa_naip_catalog.json` (CI-shipped baseline), `scripts/refresh_noaa_catalog.py` (Azure blob listing + P7 versioning), `tests/fixtures/noaa_tile_indexes/` (synthetic shapefiles)
**Files (modified):** [scripts/acquire_imagery.py](../../../scripts/acquire_imagery.py), [frontend/config/index.html](../../../frontend/config/index.html), [services/search/main.py](../../../services/search/main.py) (admin endpoints + refresh log)
**Motivating evidence:** Beta testers hit the existing NOAA card at [frontend/config/index.html:1191](../../../frontend/config/index.html#L1191) and could not tell whether bbox or state/year was required. The catalog at [scripts/acquire_imagery.py:88-91](../../../scripts/acquire_imagery.py#L88) contained one entry (Arizona 2021). Cameron asked for NOAA NAIP to become a "core competency" across all CONUS.

---

## Summary

Today's NOAA card conflates two entry modes (whole-state and bbox-scoped) and supports exactly one state. This project:

1. **Splits the UI into two explicit tabs** inside one card: "Whole state" (default) and "Custom area" (rectangle draw).
2. **Expands the catalog to all 48 CONUS states + DC**, auto-discovered via the public Azure blob listing REST API.
3. **Unifies pipeline entry points** into one code path — `--state` and `--bbox` both feed the same tile-index filter and 3-stage parallel pipeline.
4. **Introduces P7 catalog refresh mechanics** — versioned snapshots, completeness gate, refresh log, one-click rollback — to replace threshold-based atomic swap that was the original (arbitrary-number) proposal.
5. **Closes two pre-existing bugs** as a side effect: B2 (state-file naming mismatch) and B3 (missing `add_mbtiles_to_config` call) — both surfaced in the 2026-04-19 PM TileServer handoff fix follow-ups.

Non-goals: year picker, AK/HI/territories, multi-year overlays, runtime-dynamic catalog lookups without local cache. See §7 for the full list.

---

## Goals

1. **Support all ~48 CONUS states + DC** without hand-curation of the catalog. Refresh is automatic (CI nightly) with human-triggered runtime refresh via admin UI.
2. **Custom-area downloads span intersecting states transparently.** A user drawing a bbox near Four Corners gets tiles from all 4 states without choosing which.
3. **First-time beta testers cannot be confused about bbox vs. state.** Whole-state mode is the default; bbox mode is opt-in and the map only appears when they click the Custom area tab.
4. **Robust to upstream shrinkage.** An Azure listing that returns fewer states than we knew about does not silently destroy the catalog, and does not silently roll forward either. The user is informed; rollback is one click.
5. **Maximum code reuse of the 3-stage parallel pipeline.** That pipeline has absorbed most of the April 2026 bug-hunt fixes. Two separate code paths for whole-state and bbox would double the drift surface.
6. **Pre-existing `_states_intersecting` primitive is reused**, not duplicated. [setup/runner.py:257](../../../setup/runner.py#L257) already implements bbox→state resolution across 48 CONUS + DC.

---

## Non-goals (explicit)

| # | Item | Reason |
|---|---|---|
| 1 | Year picker UI | Locked Decision #8: latest year per state, informational only. NAIP refreshes on ~3-year cycles; latest is almost always what you want. |
| 2 | Alaska, Hawaii, territories | NAIP is CONUS-only by NOAA mandate. AK uses IfSAR; HI uses ad-hoc agency flights. Users needing AK/HI imagery use M2M or TNM modes. |
| 3 | Runtime catalog lookups without local cache | Offline-first invariant — every pipeline lookup reads on-disk catalog; no live Azure calls during runs. |
| 4 | Multi-year overlays of the same state | Single-year-per-state keeps catalog flat and UX simple. |
| 5 | Automated "download adjacent states too" recommendations | Decision #7: what the user drew is what they get. No second-guessing. |
| 6 | User-defined state aliases | Slugs from STATE_BBOXES internally, display names from a fixed table. No customization. |
| 7 | Mid-pipeline catalog refresh | Refresh button disabled while a pipeline is running. |
| 8 | Rollback beyond 10 snapshots | P7 retains last 10; older pruned. |

## Deferred (candidate future work)

| # | Item | Trigger to revisit |
|---|---|---|
| A | Admin UI for permanently pruning a dropped state | If NOAA drops a state and rollback-for-shrinkage UX gets annoying |
| B | Signed/checksummed catalog | If threat model expands to include tampering on the Pi |
| C | Multi-page Azure listing pagination | If NOAA's blob structure ever produces > 5000 entries per page |
| D | CI job that opens PR on catalog baseline change | If manual refresh cadence becomes burdensome |
| E | Companion utility catalog parity | If `geographica-companion` grows its own NOAA download flow |

**In scope but worth callout:** Cross-state bbox with mixed years is supported. If AZ=2021 and UT=2023, a Four Corners bbox pulls both and the UI readout shows "Arizona (2021), Utah (2023) imagery." No normalization.

---

## Locked design decisions (brainstorm)

Nine decisions locked during the 2026-04-19 NIGHT brainstorm (handoff: `handoff_20260419_noaa_conus_brainstorm.md`) plus four locked during the 2026-04-20 resumption:

| # | Decision | Choice |
|---|---|---|
| 1 | UX model | **Option B** — one card, two tabs ("Whole state", "Custom area"). Not two cards, not bbox-only. |
| 2 | Tab order | **Whole state** default → **Custom area** secondary. Default to the 90% path. |
| 3 | Language | Plain English, MB/GB units, place-names. Never "NAIP", "tiles", or raw coordinates in UI copy. |
| 4 | Bbox visibility | **Hidden until Custom area tab is active.** Shared top map only visible when some pipeline card needs a bbox. Whole state → no map. |
| 5 | Scope | **B = CONUS (48 states + DC)** — not western 11, not runtime-dynamic. |
| 6 | Catalog mechanism | **A + C + D combined.** Automated Azure blob listing discovery; CI generates baseline; admin panel "Refresh" button for runtime refresh. No manual fallback. |
| 7 | Cross-state bbox | **Auto-download from all intersecting states.** Bbox-scoped, never expanded to whole state. |
| 8 | Year handling | **Informational only, no picker.** Latest year per state from catalog. Displayed as "Arizona (2021)". |
| 9 | Place-name readout | **Nominatim reverse-geocode of bbox centroid, tier-down fallback** (city → county → state → "coverage area"). |
| 10 | Pipeline code path | **One unified pipeline, two CLI entry points** (`--state` or `--bbox`). Filter step **always runs** — no mode flag downstream of the CLI. Whole-state mode is a degenerate case of bbox mode. |
| 11 | Catalog refresh policy | **P7** — completeness gate + versioned snapshots + refresh log + one-click rollback + lockfile. Replaces threshold-based atomic swap. |
| 12 | Big-bbox confirmation | **Disk-relative, not GB-magic-number.** Warn if size > 85% of free disk; block if size > 100%. |
| 13 | Pre-merge real-Azure integration test | **GitHub Action, manual dispatch + weekly schedule.** Runs on ubuntu-latest; uploads artifacts. Environment drift is the dominant Geographica bug class; a neutral runner catches what a local harness cannot. |

---

## Architecture

### 3.1 One pipeline, two CLI entry points

```bash
# Whole-state mode (today's flow, generalized to any of 48 states)
python scripts/acquire_imagery.py --mode noaa --state arizona --output /data/imagery_noaa.mbtiles

# Custom-area mode (new)
python scripts/acquire_imagery.py --mode noaa --bbox W,S,E,N --output /data/imagery_noaa.mbtiles
```

`--state` and `--bbox` are mutually exclusive. `--year` is removed.

### 3.2 Central logic — `bbox → states` resolver

```
USER BBOX or STATE SLUG
         │
         ▼
┌──────────────────────────────────────────┐
│ 1. Candidate states                      │
│    bbox → _states_intersecting(bbox)     │   reuses setup/runner.py:257
│    state → [state]                       │
└─────────────────┬────────────────────────┘
                  ▼
┌──────────────────────────────────────────┐
│ 2. Per-state catalog lookup              │
│    slug → {year, blob_dir}               │
│    drop uncataloged states to `missing[]`│
└─────────────────┬────────────────────────┘
                  ▼
┌──────────────────────────────────────────┐
│ 3. Per-state tile index shapefile        │
│    fetch from NOAA or reuse local cache  │
│    run ogr2ogr -spat <bbox>              │
│    → subset of tile filenames per state  │
│    (runs even in whole-state mode;       │
│     filter is a no-op there, ~1s cost)   │
└─────────────────┬────────────────────────┘
                  ▼
┌──────────────────────────────────────────┐
│ 4. Unified download queue                │
│    concat(state_i.filenames × blob_base) │
│    → existing 3-stage parallel pipeline  │
│    (8 downloaders / 4 reproject / 1 merge)│
└──────────────────────────────────────────┘
```

**Why the filter always runs:** removing the whole-state-mode special case eliminates a conditional branch in the most-debugged code path. Whole-state `-spat <state-bbox>` returns every tile in the state (no-op at ~1 s cost). Per the brainstorm Section 3 insight: "one script, no mode flag past the CLI" is the genuinely simple design.

**Filename uniqueness:** NAIP tile filenames embed shoot date (`m_3511205_ne_12_060_20210923.tif`). Cross-year collisions are impossible by construction; cross-state within a year would require the NAIP grid to assign one tile to two states (it doesn't by design). Enforcement: catalog-build-time assertion rejects duplicates.

### 3.3 Catalog shape

```json
{
  "arizona":  { "year": 2021, "dir": "AZ_NAIP_2021_9596" },
  "utah":     { "year": 2021, "dir": "UT_NAIP_2021_9601" },
  "...":      { "year": 2023, "dir": "..." }
}
```

State bboxes are NOT stored in the catalog — [setup/runner.py:204](../../../setup/runner.py#L204) `STATE_BBOXES` is authoritative.

### 3.4 Catalog locations (priority order)

1. `/srv/geographica/data/noaa_naip_catalog.json` (symlink → latest snapshot) — runtime cache, refreshed live
2. `config/noaa_naip_catalog.json` — CI-generated baseline, shipped in repo

### 3.5 P7 catalog refresh (replaces "threshold atomic swap")

Refresh is triggered by (a) admin UI "Refresh NOAA catalog" button or (b) CI nightly GitHub Actions job. Both call the Azure blob listing REST API.

```
┌─────────────────────────────────────────────────────┐
│ 1. Acquire lockfile                                 │
│    /srv/geographica/data/noaa_catalog_refresh.lock  │
│    flock (blocks concurrent admin + CI refresh)     │
└────────────────────┬────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────┐
│ 2. Azure blob listing (paginated)                   │
│    Walk all pages until continuation_token is null  │
│    If truncated → abort, log, release lock          │
│    (completeness gate — all reviewers flagged this  │
│     as the worst silent-failure mode)               │
└────────────────────┬────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────┐
│ 3. Validate                                         │
│    Assert no duplicate tile filenames across states │
│    Parse state → {year, dir} from directory names   │
└────────────────────┬────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────┐
│ 4. Write snapshot                                   │
│    noaa_naip_catalog_YYYYMMDD_HHMM.json             │
│    Atomic move (tmp → final)                        │
│    Update `current` symlink                         │
└────────────────────┬────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────┐
│ 5. Log to refresh history                           │
│    {ts, total, added[], removed[], status}          │
│    Retain last 10 snapshots; prune older            │
└────────────────────┬────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────────────┐
│ 6. Release lock                                     │
└─────────────────────────────────────────────────────┘
```

**UI:** Admin panel shows refresh log (last 10 entries). Rows with `removed > 0` render a `[Rollback]` button that swaps the `current` symlink to the previous snapshot.

**Failure modes handled:**
- Azure truncates mid-listing → completeness gate aborts, catalog unchanged, log entry explains
- Network failure mid-listing → same path as truncation
- Concurrent admin + CI refresh → lockfile serializes
- Half-written JSON from host crash → atomic rename prevents visibility of partial file
- NOAA drops a state → shrinkage logged, admin clicks Rollback or accepts
- NOAA adds a state → silent ingestion, visible in log

### 3.6 New admin endpoints

```
POST /admin/pipeline/noaa/estimate
Body: { "bbox": [W,S,E,N] }  OR  { "state": "arizona" }
Response: {
  "states":         [{"state": "arizona", "tiles": 920, "size_mb": 410, "year": 2021}],
  "missing":        ["wyoming"],       // uncataloged intersecting states, if any
  "total_tiles":    920,
  "total_size_mb":  410,
  "free_disk_mb":   143000,
  "placename":      "Flagstaff area, Arizona"
}

POST /admin/pipeline/noaa/refresh
Response: { "status": "complete|truncated|locked", "log_entry": {...} }

GET /admin/pipeline/noaa/refresh-log
Response: { "entries": [{ts, total, added, removed, status}, ...] }

POST /admin/pipeline/noaa/rollback
Body: { "to_snapshot": "noaa_naip_catalog_20260419_1430.json" }
Response: { "status": "ok|not_found", "active": <snapshot_name> }
```

### 3.7 Big-bbox confirmation (disk-relative)

```javascript
// UI renders always:
"This download is 112 GB. You have 140 GB free."

// If total_size_mb > 0.85 * free_disk_mb:
"⚠ Uses 80% of free space — continue?" [Confirm] [Cancel]

// If total_size_mb > free_disk_mb:
Continue button disabled; message: "Not enough free disk space."
```

No arbitrary GB cutoff. The 85% threshold is a soft visual cue that doesn't affect correctness.

### 3.8 UI flow (validated via mockup `whole-page-flow-v4.html`)

Mockup persisted at `.superpowers/brainstorm/869511-1776625800/content/whole-page-flow-v4.html`.

```
NOAA NAIP card
├── Header: "Aerial photos from the air (NOAA)"
├── Tabs: [ Whole state ] [ Custom area ]    ← Whole state default
│
├── Stage 1: Whole state tab active (90% path)
│   ├── State dropdown (48 entries + DC, displays "Arizona (2021)")
│   ├── Estimate readout: "Arizona (2021): 50,124 tiles, 22 GB"
│   └── [ Start download ]
│
└── Stage 2: Custom area tab clicked
    ├── Shared Coverage Area map appears at top of page
    ├── Rectangle draw tool active
    ├── After rectangle drawn:
    │   ├── Estimate readout: "Flagstaff area, Arizona. 920 tiles, 410 MB."
    │   └── If bbox crosses uncataloged state: banner "Some of your bbox is in Wyoming, which isn't available yet. You'll get tiles from Arizona and Utah only."
    └── [ Start download ]
```

---

## Failure modes

| # | Failure mode | Policy |
|---|---|---|
| 1 | Catalog refresh (any kind of failure) | P7 — completeness gate + versioned snapshots + refresh log + rollback + lockfile |
| 2 | bbox intersects an uncataloged state | Partial coverage with `missing[]` in estimate response; UI banner names the missing states |
| 3 | Nominatim unreachable for placename readout | Tier-down (city → county → state → "coverage area") with 3 s timeout; pipeline never blocks |
| 4 | Tile-index shapefile missing/corrupt for a state | Re-download first; if that fails, hard-error **only** for that state (other states proceed) |
| 5 | NAIP filename collision across states | Catalog-build-time assertion fails CI on duplicate; refresh aborts |
| 6 | Bbox resolves to 0 tiles (e.g. over water) | Estimate returns zeros; UI shows "No NAIP coverage in this area" (NOT a 400) |
| 7 | User cancels mid-run | No new surface — existing `(state, filename)` checkpoint already multi-state-safe |

## Testing strategy

### Unit tests

| Layer | Covers | Style |
|---|---|---|
| Unit | Tile-index `-spat` filter | Synthetic shapefiles in `tests/fixtures/noaa_tile_indexes/` |
| Unit | Multi-state queue concatenation; filename uniqueness invariant | Fake 2–3 state entries |
| Unit | P7: completeness gate trips on truncated pagination | Mocked Azure `continuation_token` |
| Unit | P7: versioned snapshot write + symlink atomic swap | tmpdir, assert pre/post state |
| Unit | P7: shrinkage logged with `[Rollback]` affordance in log response | |
| Unit | P7: rollback endpoint unwinds snapshot correctly | |
| Unit | P7: lockfile serializes concurrent refresh | Spawn two refreshes, assert lock contention |
| Unit | Estimate endpoint shape (includes `missing[]`, `free_disk_mb`) | Mocked resolver |
| Unit | CLI: `--state` XOR `--bbox` | argparse errors |

### Integration tests — two tiers

**CI tier (runs on every push):**
- Local fake Azure blob server (fixture dir + `aiohttp` stub), ~10 tiles across 2 states
- Fast, deterministic, no network
- Validates pipeline end-to-end against a controlled mock

**Pre-merge tier (runs on manual dispatch + weekly schedule via GitHub Actions):**
- Real Azure, ~0.1° × 0.1° bbox over Four Corners AZ/UT/CO/NM intersection
- ~5–15 tiles total; runs in < 15 min on ubuntu-latest
- Azure blob listing is public → no secrets required
- Asserts: resolver returns correct state subset, no filename collisions, MBTiles valid and openable, TileServer config registered `imagery_noaa`
- Uploads MBTiles + pipeline log as artifacts (retained 7 days)

**Rationale for pre-merge as GitHub Action (not local harness):** Geographica's dominant bug class is environment drift — 15+ fixes in the 2026-04-21 beta-triage marathon were "worked on Cameron's Pi, failed on a beta tester's machine." A neutral GitHub runner catches what a local Pi-run cannot.

### Regression tests

| Test | Covers |
|---|---|
| Arizona whole-state flow byte-matches pre-refactor output | No regression for today's working state |
| B2 closure: `.noaa-state.json` written by runtime (not `.pipeline-state.json`) | |
| B3 closure: `add_mbtiles_to_config` called on completion | |

### Exploratory-agent seed

Add one class to the exploratory-agent harness's bug-class seed list:
- "Catalog refresh returned fewer states than expected" (fires P7 completeness gate regressions)

---

## Pre-existing bugs closed as side effect

**B2** (handoff_20260419_tileserver_handoff_fix): NOAA pipeline writes to `.pipeline-state.json` but admin reads `.noaa-state.json`. This refactor canonicalizes to `.noaa-state.json` throughout.

**B3** (same handoff): [scripts/acquire_imagery.py](../../../scripts/acquire_imagery.py) never calls `add_mbtiles_to_config` for `imagery_noaa` on completion. This refactor adds the call.

Both have regression tests above. Both are currently listed as "NAIP/Sentinel state-file misnaming" and "NAIP/Sentinel never register in TileServer config" in [START.md](../../../START.md) §1.

---

## Open questions (pending adversarial review)

To be stress-tested during the 5-round adversarial review phase:

1. Is the `--spat` filter always-on semantics really free, or does it introduce measurable latency on whole-state runs?
2. Is the P7 lockfile TOCTOU-safe under the specific filesystem semantics of the Pi's ext4 + tmpfs setup?
3. Does the estimate endpoint need memoization — how often will the UI re-query as the user tweaks the bbox?
4. Is 10 snapshots the right retention window, or should it be time-based (e.g. 90 days)?
5. What is the expected interaction when an in-progress pipeline is using snapshot N and a refresh creates snapshot N+1? Does the pipeline continue on N?

## References

- Previous session handoff (brainstorm pause): `memory/handoff_20260419_noaa_conus_brainstorm.md`
- Resumption session handoff (to be written): `memory/handoff_20260420_noaa_conus_brainstorm_complete.md`
- Mockups: `.superpowers/brainstorm/869511-1776625800/content/` — especially `whole-page-flow-v4.html` (validated flow)
- `STATE_BBOXES` primitive: [setup/runner.py:204](../../../setup/runner.py#L204)
- `_states_intersecting`: [setup/runner.py:257](../../../setup/runner.py#L257)
- Current NOAA catalog: [scripts/acquire_imagery.py:88-91](../../../scripts/acquire_imagery.py#L88)
- Current NOAA card UI: [frontend/config/index.html:1191](../../../frontend/config/index.html#L1191)
- Beta-triage marathon context (STATE_BBOXES origin, env-drift pattern): `memory/handoff_20260421_beta_triage_marathon.md`
- Pitfalls references (applied during plan phase): [docs/pitfalls/testing-pitfalls.md](../../pitfalls/testing-pitfalls.md), [docs/pitfalls/implementation-pitfalls.md](../../pitfalls/implementation-pitfalls.md)

## Change log

- **2026-04-20** — Initial draft. Brainstorm sections 1–6 incorporated. 5-round adversarial review pending.
