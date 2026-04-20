# NOAA NAIP CONUS Expansion — Design Spec

**Date:** 2026-04-20 (v2 — post 5-round adversarial review)
**Status:** Ready for plan phase
**Scope:** Expand NOAA NAIP imagery support from Arizona-only to all 48 contiguous US states + DC. Introduce a bbox-based custom-area mode alongside the existing whole-state mode. Replace the single-entry hardcoded catalog with a live-refreshable, versioned, snapshot-pinned catalog backed by the Azure blob listing API.
**Files (new):**
- `scripts/common/__init__.py`, `scripts/common/state_bboxes.py` — runtime-safe state bbox primitive (extracted from `setup/runner.py`)
- `config/noaa_naip_catalog.json` — CI-shipped baseline
- `scripts/refresh_noaa_catalog.py` — Azure blob listing + P7 versioning + tile-index pre-fetch
- `tests/fixtures/noaa_tile_indexes/` — synthetic shapefiles
- `tests/fixtures/azure_blob_list/` — XML fixtures for catalog refresh tests

**Files (modified):**
- [scripts/acquire_imagery.py](../../../scripts/acquire_imagery.py) — NOAA pipeline: bbox mode + snapshot pinning + multi-state checkpoint + peak-disk estimate
- [setup/runner.py](../../../setup/runner.py) — re-import `STATE_BBOXES` / `_states_intersecting` from `scripts.common.state_bboxes`
- [frontend/config/index.html](../../../frontend/config/index.html) — two-tab NOAA card
- [services/search/main.py](../../../services/search/main.py) — estimate endpoint extension + refresh/rollback/force-unlock + catalog pinning hooks

**Motivating evidence:** Beta testers hit the existing NOAA card at [frontend/config/index.html:1191](../../../frontend/config/index.html#L1191) and could not tell whether bbox or state/year was required. The catalog at [scripts/acquire_imagery.py:88-91](../../../scripts/acquire_imagery.py#L88) contained one entry (Arizona 2021). Cameron asked for NOAA NAIP to become a "core competency" across all CONUS.

**Review provenance:** v1 of this spec went through a 5-round adversarial review (Codex + 4 distinct-lens subagents) that surfaced 15 MUST-FIX findings. v2 incorporates all of them. See `## Change log` for the specific remediations.

---

## Summary

Today's NOAA card conflates two entry modes (whole-state and bbox-scoped) and supports exactly one state. This project:

1. **Splits the UI into two explicit tabs** inside one card: "Whole state" (default) and "Custom area" (rectangle draw).
2. **Expands the catalog to all 48 CONUS states + DC**, auto-discovered via the public Azure blob listing REST API using delimiter-based listing at the dataset-directory level. Pagination uses `<NextMarker>` (per Azure REST spec).
3. **Unifies pipeline entry points** into one code path — `--state` and `--bbox` both feed the same resolver. Whole-state mode short-circuits the per-tile spatial filter (the filter has a 60 s timeout that breaks on large states, so an always-on filter is not free).
4. **Introduces P7 catalog refresh mechanics with snapshot pinning** — versioned snapshots, completeness gate, refresh log with validation metadata, one-click rollback available on every completed refresh, concurrent-refresh lockfile, and most importantly: every pipeline run pins to the catalog snapshot present at Start; refresh/rollback only affect future runs.
5. **Extracts the `_states_intersecting` primitive** from `setup/runner.py` to `scripts/common/state_bboxes.py` so it is importable from the pipeline container (which does not mount `setup/`).

**Non-scope changes from v1:** The v1 claim that this work closes pre-existing bugs B2 and B3 was wrong — those are NAIP/Sentinel issues, not NOAA issues. That section has been removed.

Non-goals: year picker, AK/HI/territories, multi-year overlays, runtime-dynamic catalog lookups without local cache. See §7 for the full list.

---

## Goals

1. **Support all ~48 CONUS states + DC** without hand-curation of the catalog. Refresh is automatic (CI nightly) with human-triggered runtime refresh via admin UI.
2. **Custom-area downloads span intersecting states transparently.** A user drawing a bbox near Four Corners gets tiles from all cataloged intersecting states. States missing from the catalog are surfaced at estimate time; the user acknowledges explicitly before proceeding.
3. **First-time beta testers cannot be confused about bbox vs. state.** Whole-state mode is the default; bbox mode is opt-in and the shared map only appears when they click the Custom area tab.
4. **Robust to upstream shrinkage and parser drift.** Completeness gate rejects truncated listings. Every refresh is rollback-able regardless of add/remove counts. Validation metadata is logged for every refresh.
5. **Pipeline runs are reproducible.** Every run pins to a specific catalog snapshot at Start and reads exclusively from that snapshot until complete or cancelled. Refresh and rollback never mutate a live run's source of truth.
6. **Maximum code reuse of the 3-stage parallel pipeline.** That pipeline has absorbed most of the April 2026 bug-hunt fixes. Two separate code paths for whole-state and bbox would double the drift surface.
7. **`scripts/common/state_bboxes.py` is importable from both setup and pipeline containers.** No cross-layer imports of `setup/runner.py` inside the pipeline.

---

## Non-goals (explicit)

| # | Item | Reason |
|---|---|---|
| 1 | Year picker UI | Locked Decision #8: latest year per state, informational only. |
| 2 | Alaska, Hawaii, territories | NAIP is CONUS-only by NOAA mandate. Users needing AK/HI imagery use M2M or TNM modes. |
| 3 | Runtime catalog lookups without local cache | Offline-first invariant — every pipeline lookup reads on-disk catalog; no live Azure calls during runs. |
| 4 | Multi-year overlays of the same state | Single-year-per-state keeps catalog flat. |
| 5 | Automated "download adjacent states too" recommendations | Decision #7: what the user drew is what they get. |
| 6 | User-defined state aliases | Slugs internal (from `scripts/common/state_bboxes.py`), USPS for NOAA mapping, display names from a fixed table. |
| 7 | Mid-pipeline catalog refresh mutating a running job's source | Every run pins a snapshot at Start. Refresh/rollback affect future runs only. |
| 8 | Rollback beyond retained snapshots | P7 retains last 10 snapshots + the CI baseline as snapshot #0 (always preserved). Older user-generated snapshots pruned. |
| 9 | Silent partial coverage from failed state downloads | A mid-run state failure in a multi-state bbox results in a terminal partial-or-failed state, NOT automatic TileServer registration. (Distinct from pre-acknowledged "missing" states — see §3.2.) |

## Deferred (candidate future work)

| # | Item | Trigger to revisit |
|---|---|---|
| A | Admin UI for permanently pruning a state the operator knows NOAA dropped | If rollback-for-shrinkage UX gets annoying |
| B | Signed/checksummed catalog | If threat model expands to tampering on the Pi |
| C | CI job that opens PR on catalog baseline change | If manual refresh cadence becomes burdensome |
| D | Companion utility catalog parity | If `geographica-companion` grows its own NOAA download flow |

**In scope but worth callout:** Cross-state bbox with mixed years is supported. If AZ=2021 and UT=2023, a Four Corners bbox pulls both and the UI readout shows "Arizona (2021), Utah (2023) imagery."

---

## Locked design decisions

Fifteen decisions locked through the brainstorm + adversarial review process. Items marked **[v2]** were revised post-adversarial-review:

| # | Decision | Choice |
|---|---|---|
| 1 | UX model | **Option B** — one card, two tabs ("Whole state", "Custom area"). |
| 2 | Tab order | **Whole state** default → **Custom area** secondary. |
| 3 | Language | Plain English, MB/GB units, place-names. Never "NAIP", "tiles", or raw coordinates in UI copy. |
| 4 | Bbox visibility | **Hidden until Custom area tab is active.** |
| 5 | Scope | **B = CONUS (48 states + DC)** — not western 11, not runtime-dynamic. |
| 6 | Catalog mechanism **[v2]** | **Automated Azure blob listing via delimiter-based listing** at the Digital Coast dataset-directory level (one listing call, ≤5000 entries — fits in one page as of 2026-04-20). Pagination via `<NextMarker>` XML element if ever needed. CI generates baseline; admin panel "Refresh" button for runtime refresh. |
| 7 | Cross-state bbox | **Auto-download from all cataloged intersecting states.** Uncataloged intersecting states surfaced at estimate time via `missing[]` + explicit user acknowledgment. |
| 8 | Year handling | **Informational only, no picker.** Latest year per state from catalog. Displayed as "Arizona (2021)". |
| 9 | Place-name readout **[v2]** | **Nominatim reverse-geocode of bbox centroid, tier-down** (city → county → state → "coverage area"). **If bbox spans ≥2 states or > 5° width/height**, skip the centroid lookup and use "Coverage area across Arizona, Utah" (state-list format) directly — a centroid for such a bbox is meaningless. |
| 10 | Pipeline code path **[v2]** | **One shared queue-builder; filter short-circuited for whole-state mode.** CLI still has two entry points (`--state` or `--bbox`). Whole-state mode uses the full tile-index as its queue (no `ogr2ogr -spat` call). Bbox mode runs the filter per state. The filter's 60 s timeout cannot handle a Texas- or California-sized `-spat` call, which is why v1's "always-on filter" was wrong. |
| 11 | Catalog refresh policy **[v2]** | **P7 with snapshot pinning.** Completeness gate + versioned snapshots + full-metadata refresh log + rollback-on-every-refresh + atomic symlink swap + lockfile + pipeline-pinning. Refresh/rollback reject with 409 if ANY pipeline run is active. First-run rollback target is always the CI baseline (preserved as snapshot #0 forever). |
| 12 | Big-bbox confirmation **[v2]** | **Peak-working-set disk model, disk-relative, not GB-magic-number.** Estimate returns `raw_download_mb`, `intermediate_mb`, `final_mbtiles_mb`, `peak_required_mb`. UI warns at `peak > 0.85 * free_disk`; blocks at `peak > free_disk`. Start endpoint **re-checks** free disk before launching. |
| 13 | Pre-merge real-Azure integration test | **GitHub Action, manual dispatch + weekly schedule.** ubuntu-latest runner; uploads artifacts. |
| 14 | Partial-coverage policy **[v2, new]** | **Pre-run missing states:** surfaced at estimate, user acknowledges, pipeline proceeds. **Mid-run state failure:** terminal partial/failed state; MBTiles NOT auto-registered in TileServer; operator retries failed states or accepts partial via explicit UI action. |
| 15 | Multi-state checkpoint identity **[v2, new]** | **Checkpoint PK = `(catalog_snapshot, state_usps, tile_filename)`.** Today's PK of `tile_filename` would silently dedupe the NAIP border-quad case where NOAA ships the same filename in two states' directories. Snapshot component ensures a resume doesn't cross-contaminate between refresh snapshots. |

---

## Architecture

### 3.0 Runtime-safe module layout

`STATE_BBOXES` and `_states_intersecting` live in [setup/runner.py:200-290](../../../setup/runner.py#L200). The pipeline container's `services/pipeline/Dockerfile` mounts only `./scripts:/scripts:ro` and `./data:/data` — NOT `./setup`. Importing `setup.runner` from `acquire_imagery.py` would fail at runtime.

**Fix:** extract the primitive:

```
scripts/common/__init__.py
scripts/common/state_bboxes.py
    STATE_BBOXES: dict[str, tuple[float, float, float, float]]
    states_intersecting(bbox_str: str) -> list[str]
    # Plus canonicalization helpers — see §3.3a
```

`setup/runner.py` re-imports from `scripts.common.state_bboxes` (keep a shim assignment for external callers: `STATE_BBOXES = state_bboxes.STATE_BBOXES`). This is one commit; tests for the setup side already pass the same fixtures. The move is pure refactor with no behavior change for setup.

### 3.1 CLI entry points

```bash
# Whole-state mode (generalized from today's AZ-only flow)
python scripts/acquire_imagery.py --mode noaa --state arizona --output /data/imagery_noaa.mbtiles

# Custom-area mode (new)
python scripts/acquire_imagery.py --mode noaa --bbox W,S,E,N --output /data/imagery_noaa.mbtiles
```

`--state` and `--bbox` are mutually exclusive (argparse enforces). `--year` is removed — latest year per state is always used. **Breaking change for `--year`** is noted in the commit message per CLAUDE.md §Commit discipline.

`--state` takes the **canonical slug** (`arizona`, `georgia-us`, `district-of-columbia`) — matching `STATE_BBOXES` keys. Backward-compat: if `--state AZ` (USPS code) is passed, the CLI translates via the canonicalization table (§3.3a) before resolving, emitting a deprecation warning.

### 3.2 Central logic — resolver flow

```
MODE=state                              MODE=bbox
   │                                       │
   ▼                                       ▼
┌──────────────────────┐         ┌────────────────────────────────┐
│ candidates = [slug]  │         │ candidates =                   │
│                      │         │   states_intersecting(bbox)    │
└──────────┬───────────┘         └────────────────┬───────────────┘
           └──────────────┬──────────────────────┘
                          ▼
        ┌──────────────────────────────────────────┐
        │ Per-candidate catalog lookup             │
        │   slug → {year, dir, tile_count,         │
        │           tile_index_url, sha256}        │
        │ drop uncataloged states → `missing[]`    │
        └──────────────────┬───────────────────────┘
                           ▼
        ┌──────────────────────────────────────────┐
        │ Fetch + validate tile-index shapefile    │
        │ from local cache (sha256-verified) OR    │
        │ from tile_index_url; hard-error for      │
        │ that state only if fetch fails           │
        └──────────────────┬───────────────────────┘
                           ▼
        ┌──────────────────────────────────────────┐
        │ Per-candidate queue build:               │
        │ MODE=state → use FULL tile-index         │
        │              (no -spat call)             │
        │ MODE=bbox  → ogr2ogr -spat <user-bbox>   │
        │              with 300 s timeout          │
        └──────────────────┬───────────────────────┘
                           ▼
        ┌──────────────────────────────────────────┐
        │ Unified download queue                   │
        │ Each item: (state_usps, tile_filename,   │
        │             blob_url, catalog_snapshot)  │
        │ Feeds existing 3-stage parallel pipeline │
        └──────────────────────────────────────────┘
```

**Short-circuited filter for whole-state mode:** the `filter_tiles_by_bbox` function at [scripts/acquire_imagery.py:658](../../../scripts/acquire_imagery.py#L658) has a hardcoded 60 s timeout and returns `[]` on any error (including timeout). For Texas or California — tens of thousands of tile-index features serialized through a CSV pipe — the 60 s budget is insufficient; v1's "always-on filter" claim was wrong. Whole-state mode therefore skips the filter and uses the full tile-index as the queue directly. Bbox mode gets the filter with a bumped 300 s timeout; a failing filter is a per-state hard error (same policy as failed shapefile fetch).

**Filename uniqueness is NOT assumed.** NAIP border quads are sometimes shipped in both states' directories (real NOAA behavior per Codex review). The checkpoint primary key is `(catalog_snapshot, state_usps, tile_filename)` — see Decision #15. The merger is idempotent on tile coordinates; a border quad downloaded twice produces one output tile.

### 3.3 Catalog shape

```json
{
  "snapshot_version":  "2026-04-20T14:30:12Z",
  "parser_version":    3,
  "source_listing_url": "https://coastalimagery.blob.core.windows.net/digitalcoast?restype=container&comp=list&delimiter=/&prefix=",
  "validation_status": "ok",
  "entries": {
    "arizona": {
      "usps":           "AZ",
      "year":           2021,
      "dir":            "AZ_NAIP_2021_9596",
      "tile_count":     50124,
      "tile_index_url": "https://coastalimagery.blob.core.windows.net/digitalcoast/AZ_NAIP_2021_9596/tileindex/tileindex_AZ_NAIP_2021.zip",
      "tile_index_sha256": "abcd1234..."
    },
    "utah":      { "usps": "UT", "year": 2021, "dir": "UT_NAIP_2021_9601", "tile_count": 28451, ... },
    "district-of-columbia": { "usps": "DC", ... }
  }
}
```

State bboxes are NOT stored here — `scripts/common/state_bboxes.py` is authoritative.

### 3.3a Key canonicalization

Three namespaces are in play, and the mapping between them is explicit:

| Purpose | Namespace | Example | Source |
|---|---|---|---|
| Internal primary key | **Slug** | `arizona`, `georgia-us`, `district-of-columbia`, `new-york` | `scripts/common/state_bboxes.py::STATE_BBOXES` keys |
| NOAA directory parsing | **USPS code** | `AZ`, `GA`, `DC`, `NY` | Parsed from Azure directory names (e.g. `AZ_NAIP_2021_9596`) |
| UI display | **Title case** | `Arizona`, `Georgia`, `District of Columbia`, `New York` | Derived from slug via a `display_name` function |

Canonicalization table `scripts/common/state_bboxes.py::SLUG_BY_USPS`:

```python
SLUG_BY_USPS = {
    "AL": "alabama", "AK": None, "AZ": "arizona", "AR": "arkansas",
    "CA": "california", "CO": "colorado", "CT": "connecticut",
    "DE": "delaware", "DC": "district-of-columbia", "FL": "florida",
    "GA": "georgia-us", "HI": None, "ID": "idaho", "IL": "illinois",
    # ... complete 50-state table including AK/HI → None for unsupported
}
USPS_BY_SLUG = {v: k for k, v in SLUG_BY_USPS.items() if v is not None}
```

**Rule:** provider-specific names NEVER leak into internal identifiers. The catalog's `usps` field is a mapping aide for blob-URL construction; the primary key is always the slug.

### 3.4 Catalog locations + snapshot pinning

```
/srv/geographica/data/
├── noaa_naip_catalog.json             # symlink → current snapshot
├── noaa_catalog_snapshots/
│   ├── 0000_ci_baseline.json          # snapshot #0 — immutable, always preserved
│   ├── 20260419T143012Z.json          # timestamped snapshots
│   ├── 20260420T091234Z.json
│   └── ... (up to 10 most recent user-generated + #0 baseline = 11 total max)
├── noaa_catalog_refresh.lock          # flock sentinel
└── noaa_catalog_refresh_log.jsonl     # append-only refresh history
```

**Resolution order** (runtime and pipeline both):
1. `noaa_naip_catalog.json` symlink target if it exists AND parses AND points at an extant file
2. Fall back to `0000_ci_baseline.json` (always present; installed with the repo)
3. If both absent, 500 error with explicit "catalog unavailable — run Refresh"

**Pipeline snapshot pinning:** when a pipeline starts, it resolves the symlink to its current target (an absolute path to a snapshot file) and records that path in `.pipeline-state.json` under `catalog_snapshot`. All catalog reads for the duration of the run go against that path directly, not via the symlink. A refresh or rollback can freely change the symlink — the running pipeline is unaffected. On resume, the state file's `catalog_snapshot` field is consulted first; if that snapshot still exists, resume uses it; if it was pruned, resume refuses with a clear error: "Cannot resume — catalog snapshot X was pruned since this run started. Start a fresh run."

**Baseline immortality:** `0000_ci_baseline.json` is NEVER pruned. It is shipped with the repo. On fresh installs, the symlink initially points at it. Rollback offers it as "(factory baseline)" in the dropdown.

### 3.5 P7 catalog refresh

Refresh is triggered by (a) admin UI "Refresh NOAA catalog" button or (b) CI nightly GitHub Actions job. Both go through `scripts/refresh_noaa_catalog.py`.

```
┌─────────────────────────────────────────────────────────┐
│ 0. Check pipeline state                                 │
│    If any .pipeline-state.json shows status=running     │
│    → return 409 {blocked_by_pipeline: <state-file>}     │
└─────────────────────────┬───────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────┐
│ 1. Acquire lockfile (flock LOCK_EX | LOCK_NB)           │
│    If locked → return 409 {lock_holder_pid,             │
│                             lock_acquired_ts}           │
│    Admin UI shows [Force release] if lock > 10 min old  │
└─────────────────────────┬───────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────┐
│ 2. Azure delimiter-based listing                        │
│    GET .../digitalcoast?restype=container&comp=list     │
│        &delimiter=/&prefix=                             │
│    Walks pages until <NextMarker> is absent             │
│    (as of 2026-04-20 listing returns ~60 dirs in 1 page)│
│    If partial (NextMarker non-empty + network error)    │
│       → abort; log "truncated"; unchanged catalog       │
└─────────────────────────┬───────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────┐
│ 3. Parse NOAA directory names → {usps, year, dir}       │
│    Regex: ^([A-Z]{2})_NAIP_(\d{4})_\d+/$                │
│    Non-matching dirs (e.g. sidecar, tileindex/) ignored │
│    Map usps→slug via SLUG_BY_USPS                       │
└─────────────────────────┬───────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────┐
│ 4. For each candidate entry: HEAD-check tile-index      │
│    blob_url/tileindex/tileindex_<DIR>.zip               │
│    Size > 0, record sha256 header                       │
│    Record tile_count from shapefile `.dbf` feature count│
│    (streamed via partial-range fetch + ogr2ogr -ro)     │
│    Any state failing HEAD is DROPPED from the snapshot  │
│    and logged in validation_issues[]                    │
└─────────────────────────┬───────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────┐
│ 5. Structural validation                                │
│    - Assert every entry has {usps, year, dir, tile_count│
│      tile_index_url, tile_index_sha256}                 │
│    - Assert tile_count > 0 for every entry              │
│    - Assert usps values are subset of SLUG_BY_USPS keys │
│    - If validation fails → abort; log "invalid_parse"   │
└─────────────────────────┬───────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────┐
│ 6. Write snapshot (atomic)                              │
│    tmp_path = snapshots/<ts>.json.tmp                   │
│    json.dump + f.flush() + os.fsync()                   │
│    os.rename(tmp_path, snapshots/<ts>.json)             │
└─────────────────────────┬───────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────┐
│ 7. Atomic symlink swap                                  │
│    ln -sfn snapshots/<ts>.json \                        │
│        noaa_naip_catalog.json.tmp                       │
│    os.rename(                                           │
│        "noaa_naip_catalog.json.tmp",                    │
│        "noaa_naip_catalog.json")                        │
│    (tmp-symlink + rename == atomic symlink swap;        │
│     survives power-fail with invariant: symlink         │
│     either points at extant snapshot or is missing)     │
└─────────────────────────┬───────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────┐
│ 8. Append to refresh log                                │
│    {ts, snapshot_path, parser_version, state_count,     │
│     added, removed, changed, validation_issues,         │
│     pages_fetched, duration_s, hostname,                │
│     validation_status: ok|truncated|invalid_parse}      │
└─────────────────────────┬───────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────┐
│ 9. Prune old snapshots                                  │
│    Keep: 0000_ci_baseline.json (always)                 │
│          + 10 newest user-generated by mtime            │
│    Never prune the snapshot `current` points at         │
│    Never prune any snapshot currently pinned by a       │
│    .pipeline-state.json (scan before pruning)           │
└─────────────────────────┬───────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────┐
│ 10. Release lockfile                                    │
└─────────────────────────────────────────────────────────┘
```

**UI:** Admin panel shows refresh log. Every completed refresh (status=ok) renders with a `[Rollback]` button — NOT just shrinkage refreshes. Rollback copy shows "rollback to <snapshot_ts>: N states, parser version V." Rollback endpoint also rejects (409) if a pipeline is running.

**Rollback atomicity:** same tmp-symlink + rename idiom as step 7; log entry written for the rollback action.

**Concurrent-refresh semantics:** `flock(LOCK_EX | LOCK_NB)` — non-blocking. Second concurrent click returns 409 immediately with `{"status": "locked", "lock_age_s": 47, "lock_holder_pid": 12345}`. Admin UI shows "Refresh in progress" banner; [Force release] appears after 10 min stale-age.

**Force-release:** `POST /admin/pipeline/noaa/force-unlock` validates the lock holder PID is no longer alive (`os.kill(pid, 0)` raises); if so, removes the lockfile. If PID still alive, returns 409 with the process's `/proc/<pid>/cmdline`.

### 3.6 New admin endpoints

Existing `GET /admin/pipeline/noaa/estimate` is **extended** (not replaced), preserving backward compat with the current frontend card.

```
GET /admin/pipeline/noaa/estimate
Query: bbox=W,S,E,N  (whole-state mode uses state bbox)
       OR state=arizona   (slug)
       OR state=AZ        (USPS, translated internally)

Response (extended — new fields marked *):
{
  "tile_count":          920,
  "raw_download_gb":     0.41,
  "intermediate_gb":     1.2,        // *
  "final_mbtiles_gb":    0.38,       // *
  "peak_required_gb":    1.9,        // *
  "est_hours":           0.5,
  "disk_free_gb":        143,
  "states": [                        // *
    { "slug": "arizona", "usps": "AZ", "year": 2021,
      "tile_count": 920, "raw_download_gb": 0.41 }
  ],
  "missing":             [],         // *  ["wyoming"] if any intersecting state uncataloged
  "placename":           "Flagstaff area, Arizona",  // or "Coverage area across AZ/UT" for multi-state
  "catalog_snapshot":    "/srv/geographica/data/noaa_catalog_snapshots/20260419T143012Z.json"  // * — for start-request to pin
}

POST /admin/pipeline/noaa/refresh
Response: { "status": "ok|truncated|invalid_parse|locked|blocked_by_pipeline",
            "log_entry": {...},
            "lock_holder_pid": 12345  (if locked),
            "blocked_by_pipeline": ".../imagery_noaa.mbtiles/.pipeline-state.json"  (if blocked) }

POST /admin/pipeline/noaa/rollback
Body: { "to_snapshot": "0000_ci_baseline.json"  OR  "20260419T143012Z.json" }
Response: { "status": "ok|snapshot_pruned|not_found|blocked_by_pipeline",
            "active_snapshot": <snapshot_name_after> }

POST /admin/pipeline/noaa/force-unlock
Response: { "status": "ok|lock_holder_alive|no_lock",
            "previous_holder_pid": 12345 }

GET /admin/pipeline/noaa/refresh-log
Response: { "entries": [
  { "ts": "...", "snapshot_path": "...", "parser_version": 3,
    "state_count": 48, "added": ["vermont"], "removed": [],
    "validation_status": "ok", "validation_issues": [],
    "rollback_available": true }
] }
```

**Pipeline Start request** (the existing endpoint) is extended to accept and require `catalog_snapshot` when mode=noaa. If missing, the admin endpoint resolves it from the current symlink at Start time and pins. If the bbox's `missing[]` was non-empty at estimate, the Start request must include `acknowledge_missing: true` (new required field for that case).

### 3.7 Disk model — peak-working-set, disk-relative

The pipeline stages raw GeoTIFFs → reprojected intermediates → final MBTiles. Working-set is not final size. From existing code at [scripts/acquire_imagery.py](../../../scripts/acquire_imagery.py) (3-stage pipeline):

| Field | Meaning |
|---|---|
| `raw_download_gb` | Sum of GeoTIFFs fetched (transient — cleaned at each stage) |
| `intermediate_gb` | Reprojected tiles during the reproject stage |
| `final_mbtiles_gb` | Final MBTiles size (persisted) |
| `peak_required_gb` | `raw + intermediate + final_so_far` — worst-case simultaneous residence |

UI renders:
```
Download: 12 GB raw → 8 GB mbtiles
Peak during processing: 24 GB
Free disk: 43 GB
⚠ Peak uses 56% of free space. Continue?
```

- If `peak > 0.85 × free_disk` → yellow warning, Confirm required
- If `peak > free_disk` → red block, Start disabled, copy: "Not enough free disk space for this job."

**Freshness recheck at Start:** the Start endpoint recomputes `free_disk_mb` at request time and re-applies the block. If free disk dropped below `peak_required_mb` between estimate and Start, return 507 Insufficient Storage with the fresh number.

### 3.8 UI flow (validated via mockup `whole-page-flow-v4.html`)

Mockup persisted at `.superpowers/brainstorm/869511-1776625800/content/whole-page-flow-v4.html`.

```
NOAA NAIP card
├── Header: "Aerial photos from the air (NOAA)"
├── Tabs: [ Whole state ] [ Custom area ]    ← Whole state default
│
├── Stage 1: Whole state tab
│   ├── State dropdown (48 entries + DC, "Arizona (2021)")
│   ├── Estimate readout (includes peak disk warning if applicable)
│   └── [ Start download ]
│
└── Stage 2: Custom area tab
    ├── Shared Coverage Area map appears at top of page
    ├── Rectangle draw tool active
    ├── After rectangle drawn:
    │   ├── Estimate readout: "Flagstaff area, Arizona. 920 tiles, 410 MB raw, 380 MB mbtiles. Peak 1.9 GB."
    │   ├── If missing states: banner "Some of your bbox is in Wyoming (not yet available). You'll get tiles from Arizona only. [ Acknowledge ]"
    │   └── If peak > 0.85 × free: warning with [ Confirm ]
    └── [ Start download ]
```

---

## Failure modes

| # | Failure mode | Policy |
|---|---|---|
| 1 | Catalog refresh — truncated listing | Abort, keep symlink at previous snapshot, log `validation_status: truncated` with `pages_fetched`, `last_marker`. |
| 2 | Catalog refresh — parser drift (bad directory name format, missing HEAD on tile-index) | Abort, log `validation_status: invalid_parse` with `validation_issues[]`. Admin notified. |
| 3 | Catalog refresh while pipeline running | 409 with `blocked_by_pipeline` field; admin UI shows which state file is blocking. |
| 4 | Rollback while pipeline running | Same — 409. |
| 5 | Concurrent refresh (two admin clicks, or admin+CI) | `flock(LOCK_EX \| LOCK_NB)` → 409 with `lock_holder_pid`, `lock_age_s`. UI shows `[Force release]` after 10 min. |
| 6 | Stuck lockfile (process killed mid-refresh) | `POST /force-unlock` verifies PID is dead via `os.kill(pid, 0)`; if so, removes lock; if alive, refuses. |
| 7 | Half-written snapshot JSON | Impossible — tmp + fsync + atomic rename (step 6 / step 7). |
| 8 | Manual deletion of snapshot file | Symlink resolution checks target exists; rollback-log entry marked `[deleted]` in UI; click rolls back to CI baseline. |
| 9 | bbox intersects uncataloged state | Surfaced as `missing[]` at estimate. Start request MUST include `acknowledge_missing: true`. Pipeline proceeds only with cataloged states. |
| 10 | Mid-run state download failure | Pipeline terminates in `status: partial_failed` state. MBTiles NOT auto-registered. Operator presented with: [Retry failed states] \| [Accept partial — register as incomplete] \| [Abandon]. |
| 11 | Tile-index fetch fails for a state | Within-run hard error for that state (subset of #10). |
| 12 | User cancels mid-run | Existing behavior; checkpoint preserved; resume re-uses pinned snapshot (Decision #15 + §3.4). |
| 13 | Resume with pruned snapshot | Resume refuses cleanly: "Catalog snapshot X was pruned; cannot resume this run. Start fresh." |
| 14 | Placename for long/skinny/multi-state bbox | Skip centroid; use state-list format "Coverage area across AZ, UT" (Decision #9). |
| 15 | Nominatim unreachable / timeout | 3 s timeout; fallback string "Coverage area"; never blocks pipeline. Prefer local `geographica-nominatim` container over remote. |
| 16 | First-ever refresh on fresh install trips truncation gate | Keep baseline snapshot #0; refresh log shows truncated entry; admin retries. |
| 17 | Free disk drops between estimate and Start | Start endpoint re-checks; returns 507 with fresh `free_disk_mb`. |
| 18 | NOAA changes filename convention mid-shoot | Pre-flight HEAD on first tile filename per state during catalog refresh; state dropped with validation_issues entry if 404. |
| 19 | NAIP border quad appears in two states' directories | Decision #15 checkpoint PK `(snapshot, state_usps, filename)` stores both; merger is idempotent on tile coords. |

---

## Testing strategy

### Unit tests

| Layer | Covers |
|---|---|
| `scripts/common/state_bboxes.py` | Extracted primitive parity with old `setup/runner.py` implementation; canonicalization table round-trip (slug ↔ USPS); `None` handling for AK/HI |
| Catalog parser | NOAA directory regex; HEAD fallback failure; tile_count stream from `.dbf`; `SLUG_BY_USPS` mapping |
| Tile-index filter | Synthetic shapefiles in `tests/fixtures/noaa_tile_indexes/`; bbox→filenames; 300 s timeout; per-state hard-error on corrupt shapefile |
| P7 completeness gate | XML `<NextMarker>` parsing; truncated-on-error; full walk; fixture-based pagination |
| P7 atomic symlink swap | tmpdir, simulated power-fail between rename and symlink; assert symlink-points-at-extant-snapshot-or-missing invariant |
| P7 lockfile | flock LOCK_NB returns lock_holder_pid; force-unlock dead-pid and live-pid paths |
| P7 pipeline-block | refresh/rollback 409 when any `.pipeline-state.json` shows `status: running` |
| P7 snapshot pruning | Retain 10 newest + baseline; never prune pinned; never prune symlink target |
| Snapshot pinning | `.pipeline-state.json` persists `catalog_snapshot`; resume rejects if snapshot pruned |
| Multi-state checkpoint | PK `(snapshot, usps, filename)`; border-quad dedup; cancel/resume across multi-state bbox |
| Partial-coverage policy | mid-run state failure → `status: partial_failed`; TileServer registration suppressed; retry-failed-states action works |
| Estimate endpoint | Extended fields (`intermediate_gb`, `peak_required_gb`, `states[]`, `missing[]`, `catalog_snapshot`); backward-compat for existing frontend |
| Placename | State-list format for multi-state / > 5° bbox |

### Integration tests — two tiers

**CI tier (every push):**
- Mock Azure via `aioresponses`/`respx` — XML `<NextMarker>` pagination fixtures
- Synthetic tile-index shapefiles (2 states, ~10 tiles)
- End-to-end: estimate → start → checkpoint write → cancel/resume → completion
- No network

**Pre-merge tier (GitHub Action, manual dispatch + weekly):**
- Real Azure, public endpoints, no secrets
- Four Corners 0.1° × 0.1° bbox (straddles AZ/UT/CO/NM)
- Asserts: resolver returns correct state subset, border-quad dedup works, MBTiles opens, TileServer config registered, MBTiles visible tiles match a captured-baseline sample-grid hash (NOT byte-for-byte)
- Uploads MBTiles + pipeline log as artifacts (7-day retention)

### Regression tests

| Test | Covers |
|---|---|
| Arizona whole-state flow — **semantic equivalence** (same metadata keys, same tile count, same tile coordinate coverage, same sample-grid raster hashes) | No regression for today's working state. NOT byte-match — MBTiles ordering/timestamps/compression drift. |
| `setup/runner.py` imports from `scripts.common.state_bboxes` and OSM pipeline behavior unchanged | Extraction refactor is pure |

### Exploratory-agent seed

Add one class to the exploratory-agent harness's bug-class seed:
- "Catalog refresh returned fewer states than expected / parser skipped a directory"

---

## Open questions — resolved in v2

All v1 open questions resolved:
1. Filter always-on cost? → **No — filter short-circuits for whole-state** (Decision #10 revised).
2. Lockfile TOCTOU on Pi ext4+tmpfs? → **flock advisory + LOCK_NB; host and container share inode via bind-mount** (§3.5 step 1).
3. Estimate memoization? → **Not needed; client-side debounce 500 ms on bbox slider** (§3.6 response is cheap).
4. Snapshot retention time- vs count-based? → **Count-based: 10 newest user + baseline #0 always preserved** (§3.4).
5. In-flight pipeline + refresh? → **Pipeline pins to snapshot at Start; refresh/rollback gated 409 while running** (§3.4, Decision #11).

---

## References

- Previous session handoff (brainstorm pause): `memory/handoff_20260419_noaa_conus_brainstorm.md`
- Mockups: `.superpowers/brainstorm/869511-1776625800/content/` — especially `whole-page-flow-v4.html` (validated flow)
- Current `_states_intersecting` location: [setup/runner.py:257](../../../setup/runner.py#L257) (to be moved)
- Current NOAA catalog: [scripts/acquire_imagery.py:88-91](../../../scripts/acquire_imagery.py#L88)
- Current NOAA card UI: [frontend/config/index.html:1191](../../../frontend/config/index.html#L1191)
- Current `filter_tiles_by_bbox` (60 s timeout constraint): [scripts/acquire_imagery.py:658](../../../scripts/acquire_imagery.py#L658)
- Current `_noaa_checkpoint` schema (PK change target): [scripts/acquire_imagery.py:2306](../../../scripts/acquire_imagery.py#L2306)
- Current estimate endpoint (extend, don't replace): [services/search/main.py:1683](../../../services/search/main.py#L1683)
- Beta-triage marathon context (STATE_BBOXES origin, env-drift pattern): `memory/handoff_20260421_beta_triage_marathon.md`
- Adversarial review transcript: `/tmp/codex_review_noaa_r1.txt` + subagent tool results (2026-04-20 session)
- Pitfalls (applied during plan phase): [docs/pitfalls/testing-pitfalls.md](../../pitfalls/testing-pitfalls.md), [docs/pitfalls/implementation-pitfalls.md](../../pitfalls/implementation-pitfalls.md)

## Change log

- **2026-04-20 (v1)** — Initial draft. Brainstorm Sections 1–6 incorporated. 5-round adversarial review pending.
- **2026-04-20 (v2)** — Post-adversarial-review major revision. 15 MUST-FIX items incorporated:
  - M1: extracted `_states_intersecting` + `STATE_BBOXES` to `scripts/common/state_bboxes.py` (pipeline container deployment fix)
  - M2: revised Decision #10 — filter short-circuits for whole-state mode (60 s timeout can't handle TX/CA)
  - M3: snapshot pinning — estimate returns `catalog_snapshot`, Start pins it, pipeline state persists it
  - M4: peak-working-set disk model with `raw_download_gb / intermediate_gb / final_mbtiles_gb / peak_required_gb`
  - M5: removed incorrect "B2/B3 closed as side effect" claim (those are NAIP/Sentinel, not NOAA)
  - M6: explicit §3.3a namespace canonicalization (slug ↔ USPS ↔ NOAA dir ↔ display name)
  - M7: checkpoint PK changed to `(catalog_snapshot, state_usps, tile_filename)` (NAIP border-quad reality)
  - M8: new Decision #14 — partial-coverage terminal state for mid-run state failures
  - M9: Azure listing pagination via `<NextMarker>`, delimiter-based at directory level (not deferred)
  - M10: rollback affordance on every completed refresh, not only shrinkage; full validation metadata in log
  - M11: estimate endpoint extended (backward-compat), not replaced
  - M12: catalog refresh pre-fetches tile-index + stores feature count (enables estimate on fresh install)
  - M13: atomic symlink swap via tmp-symlink + rename
  - M14: refresh and rollback both 409 if any pipeline is running
  - M15: flock advisory + LOCK_NB; force-unlock endpoint with PID liveness check
