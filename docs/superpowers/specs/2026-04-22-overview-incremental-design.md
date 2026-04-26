# Incremental overview pyramid — journal-based design (v3)

**Status:** v3 (post-round-5; v2 found 2 more Criticals specific to the journal shape)
**Author:** Agent `sycamore`, 2026-04-22
**Adversarial review:** 5 rounds —
- Rounds 1-4: Sonnet architectural + Sonnet scale + Sonnet testability + Codex, all attacking the original v1 in-memory-dirty-list design. Convergent Critical findings killed v1.
- Round 5: Sonnet attacking the revised v2 journal-based design on its own terms. Found 2 new Criticals specific to the bulk-insert SQL path + cross-statement atomicity.
Transcripts preserved inline in the commit history under [dev/adversarial/2026-04-22-overview-incremental-*.md](../../../dev/adversarial/) (to be written during implementation review).

## Problem

`scripts/rasterio_ops.py:build_overviews` at L711 executes `DELETE FROM tiles
WHERE zoom_level < max_zoom` on every run, then regenerates every downsampled
tile from the rebuilt pyramid base. For the 2026-04-21 runtime validation (82
new base tiles merged into an 11k-tile existing MBTiles), this produced a
6+ hour post-processing phase rebuilding ~1.5M overview tiles — ~99% of which
were unchanged from the prior run.

The structural deficiency is shared by all Geographica imagery pipelines
(NOAA, M2M, Sentinel, USGS-NAIP), but the others use the `gdaladdo` CLI
which has no incremental mode. This fix targets only the NOAA pipeline,
producing a reusable primitive the others can adopt later.

## Goals

- Targeted overview regeneration for incremental base-tile changes — only
  the ancestor pyramid of newly-merged / modified / deleted base tiles gets
  touched.
- Correctness preserved across all paths that mutate base tiles (merge,
  erode, inpaint) and across crash-resume scenarios.
- Full 1:1 parallel validation against the current nuclear behavior: same
  MBTiles input, runtime-selectable mode, byte-equivalent pixel output.
- Backward-compat nuclear mode always available as rollback + as the
  threshold fallback for near-full-rebuild cases.

## Non-goals

- M2M / Sentinel / USGS-NAIP migration off `gdaladdo` (separate cycle, one
  pipeline per PR).
- Changing the 3-stage parallel pipeline (download + reproject + merge).
- Schema changes beyond one additive table (`_overview_work_queue`).

## Architecture

### 1. Persistent dirty-ancestor journal

New SQLite table in each NOAA MBTiles file:

```sql
CREATE TABLE IF NOT EXISTS _overview_work_queue (
    zoom_level   INTEGER NOT NULL,
    tile_column  INTEGER NOT NULL,
    tile_row     INTEGER NOT NULL,
    PRIMARY KEY (zoom_level, tile_column, tile_row)
);
```

**Semantics:** an entry `(z, tc, tr)` means "this ancestor tile needs
re-evaluation before the next query reads it." There is no `kind` column
— re-evaluation is unified: fetch the 4 children at (z+1, 2tc+dx, 2tr+dy);
if all 4 exist, composite + INSERT OR REPLACE; if any missing, DELETE any
existing row. This rule is the Codex-correct fix for the v1 two-set
semantics bug (spec §Round 4 C2).

Persistence across crashes is automatic — the table is in the same SQLite
file as the tiles. No Python-memory state.

### 2. Ancestor enqueueing — hybrid bulk-SQL + per-tile helper

Round 5 finding C1: the naive "wrap every tile write in a Python helper"
approach is a 100-1000× throughput regression for the merge_mbtiles bulk
path, which uses `INSERT OR IGNORE INTO tiles SELECT … FROM src.tiles`
to import thousands of tiles in one SQL statement. Rewriting that as a
per-tile Python loop would add real runtime cost to the hot path.

Resolution: **bulk paths stay bulk; small-tile paths use a helper.**

Round 5 finding C2: across-statement atomicity. Two `conn.execute` calls
are not atomic unless wrapped in explicit `BEGIN`/`COMMIT`. A crash
between the tile write and the queue write would leave a tile with no
corresponding queue entry — silently stale pyramid. All journal writes
MUST be in the same transaction as the base-tile writes they describe.

#### For bulk paths (`merge_mbtiles` fast path)

```python
# acquire_imagery.merge_mbtiles L896 — ONE atomic block:
conn.execute("BEGIN")
try:
    conn.execute("""
        INSERT OR IGNORE INTO tiles (zoom_level, tile_column, tile_row, tile_data)
        SELECT zoom_level, tile_column, tile_row, tile_data FROM src.tiles
    """)
    # Enqueue ancestors for every tile in src at max_zoom.
    # Cascade: one INSERT per zoom-level shift (~17 statements for z17 → z0).
    # Each is a bulk SQL over src.tiles — fast.
    for dz in range(1, max_zoom + 1):
        conn.execute(f"""
            INSERT OR IGNORE INTO _overview_work_queue (zoom_level, tile_column, tile_row)
            SELECT zoom_level - ?, tile_column >> ?, tile_row >> ?
            FROM src.tiles WHERE zoom_level = ?
        """, (dz, dz, dz, max_zoom))
    conn.execute("COMMIT")
except Exception:
    conn.execute("ROLLBACK")
    raise
```

Over-enqueueing of ancestors for already-dedup'd tiles (whose INSERT OR
IGNORE was a no-op in src → dst) is harmless: the queue's PK-on-IGNORE
collapses duplicates, and drain re-evaluates ancestors idempotently.

#### For single-tile paths (composite overwrite, erode, inpaint)

Small helper that runs tile-write + queue-enqueue as a single atomic
block:

```python
def _mutate_base_tile(
    conn: sqlite3.Connection,
    action: Literal["upsert", "delete"],
    z: int, tc: int, tr: int,
    tile_data: bytes | None = None,
    *, max_zoom: int,
) -> None:
    """Atomic: base-tile mutation + ancestor enqueue. Caller must have
    already opened a transaction OR let this open one.
    """
    in_txn = conn.in_transaction
    if not in_txn:
        conn.execute("BEGIN")
    try:
        if action == "upsert":
            conn.execute(
                "INSERT OR REPLACE INTO tiles (zoom_level, tile_column, tile_row, tile_data) "
                "VALUES (?, ?, ?, ?)",
                (z, tc, tr, tile_data),
            )
        else:  # delete
            conn.execute(
                "DELETE FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (z, tc, tr),
            )
        # Enqueue ancestor chain — same (z, tc, tr) yields z-1, z-2, ..., 0.
        for dz in range(1, z + 1):
            conn.execute(
                "INSERT OR IGNORE INTO _overview_work_queue (zoom_level, tile_column, tile_row) "
                "VALUES (?, ?, ?)",
                (z - dz, tc >> dz, tr >> dz),
            )
        if not in_txn:
            conn.execute("COMMIT")
    except Exception:
        if not in_txn:
            conn.execute("ROLLBACK")
        raise
```

The three call sites:

- `acquire_imagery.merge_mbtiles` L896 — bulk path (uses the bulk SQL
  block above). This is the real NOAA output mutation point; v1 missed
  it by instrumenting the wrong function.
- `acquire_imagery.merge_mbtiles` L924 — single-tile UPDATE composites.
  Use `_mutate_base_tile(action="upsert", ...)`.
- `rasterio_ops.erode_nodata_edges` — DELETEs. Use
  `_mutate_base_tile(action="delete", ...)`.
- `rasterio_ops.inpaint_nodata_pixels` — UPDATEs. Use
  `_mutate_base_tile(action="upsert", ...)`. Also max-zoom-restricted
  per §3.

**Completeness guarantee is by convention**, not by architecture — the
v2 claim of "architecturally impossible to miss" was overstated.
Mitigation: a grep-based CI test asserts that `INSERT INTO tiles`,
`INSERT OR REPLACE INTO tiles`, `UPDATE tiles`, and `DELETE FROM tiles`
appear only inside either the bulk-path function or `_mutate_base_tile`
in the NOAA-relevant files. A reviewer following CLAUDE.md review
discipline can catch additions; the grep test is a safety net.

### 3. Inpaint restricted to base-tile zoom only

Today `inpaint_nodata_pixels` iterates `SELECT … FROM tiles` across every
zoom level. In the reordered pipeline (see §4), overview tiles from prior
runs are still present at the time inpaint runs, so a zoom-unrestricted
inpaint would mutate overview tiles out-of-band — a critical bug
(Round 4 finding IC4).

Change inpaint to `SELECT … FROM tiles WHERE zoom_level = ?` with the
max zoom. This preserves its erosion-style role (fix black JPEG seams at
NAIP quad boundaries) and confines its effect to the authoritative base
layer.

### 4. NOAA post-processing pipeline reorder

Current order in `acquire_imagery.run_noaa` L2708-2790:
`merge → overviews → erode → inpaint`

New order: `merge → erode → inpaint → overviews`

Justification: `erode_nodata_edges`' comment at rasterio_ops.py:909-912
already states "Overviews are rebuilt from post-erosion tiles" — the
reorder matches the function author's intent. The overview build sees final
tile state; the latent staleness bug (overviews pointing at pre-erosion
base tiles) is closed as a side effect.

Verified safe: no code between merge and current overview-build reads
overview tiles for functional purposes. `_update_mbtiles_bounds` reads
max_zoom only (`rasterio_ops.py:961-968`). TileServer registration
happens via the search service *after* pipeline completion, not during
post-processing.

### 5. `build_overviews` rewrite with mode selector

```python
def build_overviews(
    mbtiles_path: Path,
    *,
    mode: Literal["auto", "journal", "nuclear"] = "auto",
    levels: list[int] | None = None,
    resampling: str = "average",
    cancel_check=None,
) -> bool:
    """Build the overview pyramid.

    mode='auto'    : journal drain if queue is populated AND the queue
                     size is within threshold (default: < 50% of base
                     tile count); otherwise nuclear. Silent no-op if
                     there are zero base tiles (new/empty MBTiles).
    mode='journal' : always journal-drain. Empty queue = silent no-op
                     with an info-level log (R5 I5 — raising was wrong
                     for legitimate "nothing new to process" runs).
    mode='nuclear' : always nuclear. Ignores queue, clears queue at end.
                     Intended for rollback / large fresh runs / validation.

    Both modes drain the queue at exit (empty table on successful return).
    """
```

#### Journal drain (targeted path)

1. `SELECT COUNT(*) FROM _overview_work_queue` — determine dirty-set size.
2. For `mode="auto"`:
   - **R5 I1 fix — empty-MBTiles guard:** `SELECT MAX(zoom_level) FROM
     tiles`; if NULL (no tiles at all), return silently (no work to do).
   - `SELECT COUNT(*) FROM tiles WHERE zoom_level = max_zoom`. If that
     count is 0, same silent return.
   - Compute `ratio = queue_size / base_tile_count`. If ratio > 0.5,
     call through to nuclear drain.
3. Descend from `max_zoom-1` down to 0. At each zoom z:
   - Fetch all work entries at z: `SELECT tc, tr FROM _overview_work_queue
     WHERE zoom_level = ?`.
   - For each ancestor `(z, tc, tr)`:
     - Fetch 4 children at (z+1, 2tc+dx, 2tr+dy) for dx,dy ∈ {0,1}.
     - If all 4 exist: composite (existing 2×2 averaging from
       rasterio_ops.py:753-778) and `INSERT OR REPLACE`.
     - If any missing: `DELETE FROM tiles WHERE zoom_level=? AND
       tile_column=? AND tile_row=?`.
   - Remove processed entries from the queue.
   - `conn.commit()` per zoom level (matches existing commit granularity).
4. Cancel check between zoom levels; partial progress is durable (queue
   rows for unprocessed entries remain for next run's drain).

**Semantic note (R5 I4 — documented, not a bug):** if an incremental
bbox expansion touches only 1 of 4 z17 siblings whose z16 ancestor
previously had all 4 children from a prior nuclear run, the drain
correctly keeps the ancestor (all 4 children exist — the 3 from prior,
the 1 newly dirty). If the bbox expansion ADDS a z17 tile whose 3
siblings never existed, the z16 ancestor is correctly DELETED (the
unified re-eval rule treats incomplete 2×2 as "no overview"). This
is intentional: stale composites are worse than basemap-fallback.
Document in the admin-panel user-facing estimate so users aren't
surprised by overview coverage shrinking when they expand a sparse
bbox.

#### Nuclear drain (fallback / rollback)

Matches current behavior at `rasterio_ops.py:711-804`:
1. `DELETE FROM tiles WHERE zoom_level < max_zoom`.
2. For each zoom descending: `SELECT DISTINCT tc/2, tr/2 FROM tiles
   WHERE zoom_level = parent_z`, composite, `INSERT OR REPLACE`.
3. `DELETE FROM _overview_work_queue` — clears the queue even though
   it wasn't consulted.

### 6. Crash recovery

Because the queue is in the same SQLite file, a crash mid-overview-build
leaves the MBTiles in a well-defined state:
- Base tiles are in whatever state the last commit produced.
- Queue contains entries for ancestors not yet processed (partial drain).
- On next run, `build_overviews(mode="auto")` sees a populated queue and
  drains it — completing the prior run's work.

This also closes Round 3 failure mode #2 ("crash mid-overview leaves
permanently stale pyramid").

### 7. Wire-up in `run_noaa`

```python
# Phase 4: merge (populates _overview_work_queue via _mutate_base_tile)
# Phase 5.a: erode (populates queue on DELETEs)
# Phase 5.b: inpaint — max-zoom-only (populates queue on UPDATEs)
# Phase 5.c: build_overviews(mode="auto") — drains the queue
```

No run_noaa-side dirty list is needed. The queue owns the state.

## A/B validation harness

One-off dev tool at `dev/tools/compare_overview_modes.py` (not shipped,
not tested against regression).

Workflow:

1. Take a real MBTiles post-merge-erode-inpaint (snapshot from a running
   pipeline, or the 2026-04-21 LA run if still available).
2. Make two clones via `sqlite3 .backup`.
3. Run `build_overviews(clone_a, mode="nuclear")`. Wall-time it. Record
   final overview tile count.
4. Run `build_overviews(clone_b, mode="journal")`. Wall-time it. Record
   final overview tile count.
5. Compare outputs:
   - **Tile count**: must match exactly.
   - **Per-tile decode**: open each tile's JPEG via rasterio; collect
     RGB array. Mean absolute difference vs. the other clone's same-coord
     tile.
   - **Pass threshold**: mean-abs-diff < 2 on a 0-255 scale. Allows for
     any 1-LSB JPEG-encoding variance while catching real algorithmic
     divergence (e.g., off-by-one ancestor math, wrong downsample).
6. Report: speedup, count match, pixel-level equivalence.

The harness is deleted after initial validation or kept in `dev/tools/`
for future regression checks. No production code path depends on it.

## Testing strategy

Every new test runs against BOTH modes where applicable — nuclear as the
known-good baseline, journal as the new path — asserting the two produce
equivalent outputs. This is test-time 1:1 parallel validation on top of
the one-off harness run.

### Unit tests (synthetic fixtures)

1. **`test_journal_populated_on_merge_mbtiles`**: call `_mutate_base_tile`
   via the merge path N times; assert `_overview_work_queue` has the
   correct ancestor rows (N × 17-or-whatever-max-zoom).
2. **`test_journal_populated_on_erode`**: same for erosion DELETE path.
3. **`test_journal_populated_on_inpaint`**: same for inpaint UPDATE path,
   restricted to max-zoom only.
4. **`test_journal_drain_writes_ancestor_when_4_children_exist`**:
   fixture with complete 2×2 block; journal entry for the ancestor;
   drain; assert ancestor row exists and is the 2×2 average.
5. **`test_journal_drain_deletes_ancestor_when_child_missing`**:
   fixture with 3/4 children; pre-existing ancestor row; journal entry;
   drain; assert ancestor row is deleted.
6. **`test_journal_drain_handles_same_ancestor_with_modify_and_delete`**:
   Codex C2 regression test. Ancestor enqueued from both an UPDATE child
   and a DELETE child in the same run. Drain; assert the re-evaluate rule
   runs once per ancestor (not twice); final state correct.
7. **`test_multi_level_cascade`**: journal entry for z17 base tile;
   drain; assert ancestors at z16, z15, ..., z0 all exist (where 4
   children exist at each level).
8. **`test_mode_auto_falls_back_to_nuclear_on_large_queue`**: populate
   queue with entries > 50% of base tiles; `mode="auto"`; assert nuclear
   drain path ran.
9. **`test_mode_nuclear_clears_queue_at_exit`**: `mode="nuclear"`; assert
   `_overview_work_queue` is empty after return (even though it was
   ignored).
10. **`test_mode_journal_raises_on_empty_queue`**: documented contract.
11. **`test_cancel_between_zoom_levels_preserves_remaining_work`**:
    pre-populate queue; trigger cancel after z16 drain completes; assert
    z15..z0 entries remain in queue.

### Integration test (end-to-end semantic equivalence)

12. **`test_nuclear_and_journal_produce_equivalent_mbtiles`**: MBTiles
    fixture with **gradient tiles** (not solid colors — R5 m1: solid
    colors are averaging-invariant and let averaging bugs survive). Run
    mode=nuclear on clone A, mode=journal on clone B. Assert:
    - **Coordinate union check** (R5 m2): compute the set of
      (z, tc, tr) tuples present in EACH clone; assert the sets are
      equal (catches the case where counts match but coverage differs).
    - Per-tile decode + mean-abs-diff < 2 per decoded channel.

### Pipeline-reorder integration test

13. **`test_reordered_pipeline_inpaint_does_not_touch_overviews`**:
    fixture with pre-existing overview tiles from prior nuclear run;
    compute checksum per overview tile; run reordered post-processing;
    assert overview tile checksums are unchanged (proving inpaint's
    max-zoom restriction held).

### Resume/crash recovery test

14. **`test_crash_mid_drain_resumes_cleanly`**: populate queue; call
    `build_overviews` with a cancel_check that fires after 1 zoom level
    processed; assert:
    - queue has the expected remaining entries at z15..z0 (R5 m2:
      explicit assertion that z16 entries are GONE from queue);
    - `tiles` table contains the z16 ancestor rows that the drain
      wrote before cancel fired (proving the write committed, not
      just the queue deletion);
    - re-call without cancel; assert queue is empty and all ancestors
      correct.

### Legacy / migration tests

15. **`test_first_call_on_legacy_mbtiles_creates_journal_table`**
    (R5 m3): fixture MBTiles WITHOUT the `_overview_work_queue` table
    (simulates pre-fix files like Cameron's current AZ+LA file). Call
    `build_overviews(mode="auto")`. Assert: table is created, mode
    falls back to nuclear (empty queue → auto threshold ratio
    undefined → nuclear), pyramid is correct after run.

16. **`test_a_b_harness_clone_is_wal_clean`** (R5 I3): validate the
    `dev/tools/compare_overview_modes.py` helper calls
    `PRAGMA wal_checkpoint(TRUNCATE)` before `.backup`. Omitting this
    step silently produces non-identical clones when the source file
    has uncommitted WAL frames. Test asserts the harness performs the
    checkpoint.

17. **`test_mode_nuclear_is_crash_safe_wrt_queue`** (R5 I2): simulate
    a crash after nuclear rebuilds tiles but before it clears the
    queue. Next run with `mode="auto"` sees non-empty queue, drains
    it (redundant but correct re-evaluations against the
    already-correct pyramid). Assert: no tile corruption, drain
    completes successfully.

## Migration

Existing MBTiles files (e.g., Cameron's current 40 GB AZ+LA file) need
the journal table created on first access. Handled via
`CREATE TABLE IF NOT EXISTS` in a small `_init_journal(conn)` helper,
called from `build_overviews` and `_mutate_base_tile`. No data migration
needed; the queue starts empty on existing files. First post-migration
run will have an empty queue → `mode="auto"` picks nuclear (the safe
first-time behavior). Subsequent incremental runs populate the queue
and use journal drain.

No changes needed to non-NOAA MBTiles (basemap, elevation, etc.).

## Rollback

If the journal-based design misbehaves in production:

- **Immediate**: set `mode="nuclear"` via an env var or CLI flag. No
  code redeploy. Behavior matches pre-fix.
- **Dropped**: future PR removes `_mutate_base_tile`, restores direct
  INSERT/UPDATE/DELETE at the three call sites, drops the
  `_overview_work_queue` table (or leaves it as unused cruft — harmless).

## Portability

When we later migrate M2M, Sentinel, and USGS-NAIP off `gdaladdo`:

1. Replace `subprocess.run(["gdaladdo", ...])` with
   `build_overviews(mbtiles_path, mode="auto")`.
2. Route their tile-insertion paths through `_mutate_base_tile`.
3. The journal table materializes automatically per file.

One follow-up PR per pipeline. No changes to the journal primitive.

## Scope estimate

- `rasterio_ops.py`: +100 LOC (journal helper, mode selector, drain logic).
- `acquire_imagery.py`: ~30 LOC changed (route merge_mbtiles through
  `_mutate_base_tile`; reorder post-processing; pipeline wire-up).
- Tests: ~400 LOC across ~14 tests.
- `dev/tools/compare_overview_modes.py`: ~150 LOC one-off harness.

Total ~700 LOC. Larger than the original ~60 LOC estimate, but the scope
reflects doing it correctly per the adversarial review.

## Addressed findings from review rounds 1-5

| Finding | Round | Severity | Resolution in v3 |
|---|---|---|---|
| Wrong function instrumented (temp vs. output MBTiles) | 1-4 | Critical | Hybrid bulk-SQL + per-tile helper; both route through the real output mutation path in `merge_mbtiles` |
| Two-set re-evaluation rule fails on modify+delete | 1-4 | Critical | Single unified "re-evaluate: write if complete, delete if partial" |
| Crash-mid-overview leaves stale pyramid | 1-4 | Critical | Journal persists across crashes; resume drains remaining |
| Bulk `INSERT OR IGNORE INTO tiles SELECT…` can't wrap per-tile | 5 | Critical | Bulk path stays bulk; post-insert bulk-SQL enqueues ancestors; per-tile paths use `_mutate_base_tile` |
| Cross-statement atomicity (tile write vs. queue write) | 5 | Critical | All pairs wrapped in explicit `BEGIN; …; COMMIT;` or inside an existing transaction |
| Inpaint mutates overview tiles out-of-band | 1-4 | Important | Max-zoom-only filter |
| WAL amplification from many small DELETEs | 1-4 | Important | `executemany` + per-zoom-level commit; auto-fallback to nuclear for large queues |
| Fresh-run nuclear fallback threshold | 1-4 | Important | `mode="auto"` checks queue/base ratio; falls back at 50% |
| Divide-by-zero on empty MBTiles | 5 | Important | Explicit guard: if `max_zoom` is NULL or base count is 0, silent no-op |
| `mode="journal"` raised on empty queue | 5 | Important | Changed to silent no-op with info log |
| `mode="nuclear"` queue-clear not crash-safe | 5 | Important | Nuclear drain clears queue as part of the same commit that writes the final ancestor; test 17 validates |
| A/B harness `.backup` without WAL checkpoint | 5 | Important | Harness must `PRAGMA wal_checkpoint(TRUNCATE)` before `.backup`; test 16 validates |
| Sparse-bbox ancestor-deletion semantics | 5 | Info | Documented as intentional — "stale composite worse than basemap fallback" |
| Thread-safety of dirty list | 1-4 | Important (downgraded) | N/A — journal is SQLite; merge is serialized via `_merger` coroutine |
| Solid-color fixture masks averaging bugs | 5 | Minor | Tests use gradient tiles, not solid colors |
| Coordinate-set equivalence (count match ≠ coverage match) | 5 | Minor | Test 12 uses set-equality on coords, not just count |
| Legacy MBTiles first-call behavior | 5 | Minor | New test 15 validates `CREATE TABLE IF NOT EXISTS` path |
| Enforcement of single-entry-point invariant | 5 | Minor | Grep-based CI test (see §2); reviewer discipline |
| Existing test coverage missing | 1-4 | Important | 17 new tests including end-to-end equivalence, crash recovery, and legacy migration |

## Open questions (out of scope — flag for future)

1. **`gdaladdo`-using pipelines migration.** One follow-up PR per
   pipeline. Design reused as-is.
2. **Observability of the queue during runs.** Could surface a
   queue-depth metric via the existing pipeline progress endpoint.
3. **Threshold tuning.** 50% is a guess. Benchmark on real workloads
   post-ship and adjust if needed.
4. **Migration path for basemap/elevation MBTiles.** Out of scope; they
   have different characteristics and aren't part of this fix.
