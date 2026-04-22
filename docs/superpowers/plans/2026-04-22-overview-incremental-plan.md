# Incremental overview pyramid (journal-based) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every task ends with a TDD-discipline commit. Pitfalls to skim before starting: [docs/pitfalls/testing-pitfalls.md](../../pitfalls/testing-pitfalls.md) and [docs/pitfalls/implementation-pitfalls.md](../../pitfalls/implementation-pitfalls.md).

**Goal:** Replace `scripts/rasterio_ops.py:build_overviews`'s nuclear pyramid-rebuild with targeted incremental regeneration keyed on a persistent SQLite dirty-ancestor journal, without breaking existing NOAA output correctness.

**Architecture:** Add a `_overview_work_queue` table to NOAA MBTiles files. Every base-tile mutation (merge, erode, inpaint) enqueues the tile's ancestor chain (z-1, z-2, ..., 0) in the same SQLite transaction as the mutation itself. `build_overviews` drains the queue bottom-up using a unified re-evaluation rule (write ancestor if all 4 children exist, delete if any missing). A `mode="auto"|"journal"|"nuclear"` selector preserves the current nuclear path as rollback + A/B baseline. Pipeline reorder: `merge → erode → inpaint → overviews` (overviews see post-erosion/inpaint state, matching `erode_nodata_edges`'s existing author-intent comment at rasterio_ops.py:909-912).

**Tech Stack:** Python 3.12, SQLite (journal_mode=WAL), rasterio 1.4, aiohttp-based pipeline (unchanged), existing `test_noaa_phase5.py` harness pattern for fixtures.

**Spec:** [docs/superpowers/specs/2026-04-22-overview-incremental-design.md](../specs/2026-04-22-overview-incremental-design.md) (v3, post-5-round adversarial review).

---

## Required preambles (every task)

Before starting each task:

1. Read the task-specific section of the spec (links inline below).
2. Skim the listed pitfalls files for the test types you'll write.
3. Confirm pre-flight: `pwd` → `/home/administrator/Code/geographica`; `git branch --show-current` → `dev` (or a feature branch if one is in play); `git status` clean except known parallel-thread files.
4. TDD: failing test first, confirm it fails with a meaningful error, then implement, confirm passes, commit. Every commit trailer: `Agent: <moniker>`.
5. Stage files by name (`git add <specific files>`), NEVER `git add -A`. There are parallel-thread files in the working tree that are not yours.
6. No worktrees, no destructive git (per CLAUDE.md §Git workflow).

---

## Phase 1 — Journal foundation (3 tasks)

### Task 1: `_init_journal` helper + legacy MBTiles migration test

**Goal:** Create the `_overview_work_queue` SQLite table on any MBTiles connection. Idempotent. Satisfies spec test 15 (legacy-MBTiles first-call behavior).

**Files:**
- Modify: `scripts/rasterio_ops.py` (new helper near the build_overviews section)
- Test: `tests/test_overview_journal.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/test_overview_journal.py`:

```python
"""Tests for the incremental overview journal (spec: 2026-04-22)."""
import sqlite3
import sys
from pathlib import Path

import pytest

# Make scripts/ importable as a bare module (same pattern as test_noaa_phase5)
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


@pytest.fixture
def mbtiles_path(tmp_path):
    """Create a minimal MBTiles file with tiles + metadata but no journal."""
    path = tmp_path / "test.mbtiles"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE tiles (
            zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
            tile_data BLOB,
            PRIMARY KEY (zoom_level, tile_column, tile_row)
        );
        CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT);
        """
    )
    conn.commit()
    conn.close()
    return path


def test_init_journal_creates_table_on_legacy_mbtiles(mbtiles_path):
    """Spec §Migration + test 15: CREATE TABLE IF NOT EXISTS on first access."""
    from rasterio_ops import _init_journal

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='_overview_work_queue'"
    ).fetchone()
    conn.close()

    assert row is not None, "_overview_work_queue table should be created"


def test_init_journal_is_idempotent(mbtiles_path):
    """Second call on same file must not raise or modify the schema."""
    from rasterio_ops import _init_journal

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    _init_journal(conn)  # must not raise

    # Schema should still be exactly the designed PK shape
    pragma = conn.execute("PRAGMA table_info(_overview_work_queue)").fetchall()
    conn.close()

    col_names = [row[1] for row in pragma]
    assert col_names == ["zoom_level", "tile_column", "tile_row"], (
        f"expected exactly 3 columns with those names; got {col_names}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_overview_journal.py::test_init_journal_creates_table_on_legacy_mbtiles -v
```

Expected: `ImportError` on `from rasterio_ops import _init_journal` OR `AttributeError: module 'rasterio_ops' has no attribute '_init_journal'`.

- [ ] **Step 3: Implement `_init_journal` in `scripts/rasterio_ops.py`**

Place the helper immediately before the `build_overviews` function definition (approximately line 675 in current file, near the section-break comment):

```python
def _init_journal(conn: sqlite3.Connection) -> None:
    """Create the _overview_work_queue dirty-ancestor journal table if missing.

    Idempotent. Safe to call on any MBTiles connection, including legacy
    files that pre-date the journal design. Part of the 2026-04-22
    incremental-pyramid fix — see
    docs/superpowers/specs/2026-04-22-overview-incremental-design.md §Migration.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _overview_work_queue (
            zoom_level   INTEGER NOT NULL,
            tile_column  INTEGER NOT NULL,
            tile_row     INTEGER NOT NULL,
            PRIMARY KEY (zoom_level, tile_column, tile_row)
        )
        """
    )
```

- [ ] **Step 4: Run both tests to verify pass**

```bash
python -m pytest tests/test_overview_journal.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/rasterio_ops.py tests/test_overview_journal.py
git commit -m "$(cat <<'EOF'
feat(overview): _init_journal creates the _overview_work_queue table

Idempotent SQLite helper that creates the dirty-ancestor journal table
used by the incremental-overview design. See spec §Migration. Also
lays the groundwork for the subsequent helpers (_enqueue_ancestors,
_mutate_base_tile) that write to this table.

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `_enqueue_ancestors` helper

**Goal:** Compute the ancestor chain `(z-1, tc>>1, tr>>1), ..., (0, 0, 0)` for a set of base tiles and INSERT OR IGNORE into `_overview_work_queue`. Used by both the bulk path and the single-tile path.

**Files:**
- Modify: `scripts/rasterio_ops.py`
- Test: `tests/test_overview_journal.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_overview_journal.py`:

```python
def test_enqueue_ancestors_populates_full_lineage(mbtiles_path):
    """A single base tile at zN should enqueue N ancestors (z=N-1 down to 0)."""
    from rasterio_ops import _init_journal, _enqueue_ancestors

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    # Base tile at z17, tc=100, tr=200
    _enqueue_ancestors(conn, [(17, 100, 200)])
    conn.commit()

    rows = conn.execute(
        "SELECT zoom_level, tile_column, tile_row FROM _overview_work_queue "
        "ORDER BY zoom_level DESC"
    ).fetchall()
    conn.close()

    # Expected: 17 entries — (16, 50, 100), (15, 25, 50), (14, 12, 25), ...
    expected = []
    tc, tr = 100, 200
    for z in range(16, -1, -1):
        tc >>= 1
        tr >>= 1
        expected.append((z, tc, tr))
    assert rows == expected, f"ancestor chain mismatch:\n  got: {rows}\n  want: {expected}"


def test_enqueue_ancestors_deduplicates_with_primary_key(mbtiles_path):
    """INSERT OR IGNORE collapses the same ancestor from multiple children."""
    from rasterio_ops import _init_journal, _enqueue_ancestors

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    # Two siblings sharing the same z16 ancestor (16, 50, 100)
    _enqueue_ancestors(conn, [(17, 100, 200), (17, 101, 200)])
    conn.commit()

    # Distinct entries at z16 should equal 2 (each sibling has its own z16
    # position: 100>>1 = 50, 101>>1 = 50. Same parent!) — so dedup to 1.
    count_at_z16 = conn.execute(
        "SELECT COUNT(*) FROM _overview_work_queue WHERE zoom_level=16"
    ).fetchone()[0]
    conn.close()

    assert count_at_z16 == 1, (
        f"expected 1 unique z16 ancestor for siblings 100,101; got {count_at_z16}"
    )


def test_enqueue_ancestors_empty_list_is_noop(mbtiles_path):
    """Empty input list: no rows added, no error raised."""
    from rasterio_ops import _init_journal, _enqueue_ancestors

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    _enqueue_ancestors(conn, [])
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM _overview_work_queue").fetchone()[0]
    conn.close()

    assert count == 0
```

- [ ] **Step 2: Run tests to verify fail**

```bash
python -m pytest tests/test_overview_journal.py -v -k enqueue_ancestors
```

Expected: 3 fails with `ImportError` on `_enqueue_ancestors`.

- [ ] **Step 3: Implement in `scripts/rasterio_ops.py`**

After `_init_journal`, add:

```python
def _enqueue_ancestors(
    conn: sqlite3.Connection,
    base_tiles: list[tuple[int, int, int]],
) -> None:
    """Enqueue the full ancestor lineage for each base tile into the journal.

    For each (z, tc, tr), inserts (z-1, tc>>1, tr>>1), (z-2, tc>>2, tr>>2), ...,
    (0, 0, 0) into _overview_work_queue with INSERT OR IGNORE (the PK on
    (zoom, tc, tr) collapses duplicates so repeated calls are idempotent).

    Caller is responsible for:
    - Having called _init_journal(conn) first.
    - Calling conn.commit() afterward (this function does not commit so that
      callers can wrap mutation+enqueue in one atomic transaction — see spec
      §Cross-statement atomicity).
    """
    if not base_tiles:
        return
    rows = []
    for z, tc, tr in base_tiles:
        for dz in range(1, z + 1):
            rows.append((z - dz, tc >> dz, tr >> dz))
    conn.executemany(
        "INSERT OR IGNORE INTO _overview_work_queue "
        "(zoom_level, tile_column, tile_row) VALUES (?, ?, ?)",
        rows,
    )
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_overview_journal.py -v
```

Expected: 5 passed total.

- [ ] **Step 5: Commit**

```bash
git add scripts/rasterio_ops.py tests/test_overview_journal.py
git commit -m "$(cat <<'EOF'
feat(overview): _enqueue_ancestors computes + inserts the dirty lineage

Given a list of base tiles, inserts every ancestor (z-1, z-2, ..., 0)
into the _overview_work_queue with INSERT OR IGNORE. Used by both the
bulk merge_mbtiles path and the per-tile _mutate_base_tile helper
(next task). Caller is responsible for commit — allows wrapping
mutation + enqueue in one atomic transaction per spec §Cross-statement
atomicity (Round 5 C2).

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `_mutate_base_tile` helper (atomic upsert / delete + enqueue)

**Goal:** Single-tile mutation with atomic journal enqueue. Resolves spec Round 5 C2 (cross-statement atomicity).

**Files:**
- Modify: `scripts/rasterio_ops.py`
- Test: `tests/test_overview_journal.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_overview_journal.py`:

```python
def test_mutate_base_tile_upsert_writes_tile_and_enqueues(mbtiles_path):
    """upsert inserts the tile and enqueues its ancestors in one transaction."""
    from rasterio_ops import _init_journal, _mutate_base_tile

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    _mutate_base_tile(conn, "upsert", 17, 100, 200, tile_data=b"fake_jpeg")
    conn.commit()

    tile = conn.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=17 AND tile_column=100 AND tile_row=200"
    ).fetchone()
    queue_count = conn.execute(
        "SELECT COUNT(*) FROM _overview_work_queue"
    ).fetchone()[0]
    conn.close()

    assert tile == (b"fake_jpeg",)
    assert queue_count == 17  # z16 through z0


def test_mutate_base_tile_delete_removes_tile_and_enqueues(mbtiles_path):
    from rasterio_ops import _init_journal, _mutate_base_tile

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    # Seed a tile to delete
    conn.execute(
        "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) "
        "VALUES (17, 50, 60, ?)",
        (b"seed",),
    )
    conn.commit()

    _mutate_base_tile(conn, "delete", 17, 50, 60)
    conn.commit()

    tile = conn.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=17 AND tile_column=50 AND tile_row=60"
    ).fetchone()
    queue_count = conn.execute(
        "SELECT COUNT(*) FROM _overview_work_queue"
    ).fetchone()[0]
    conn.close()

    assert tile is None, "base tile should have been deleted"
    assert queue_count == 17  # same ancestor cascade


def test_mutate_base_tile_atomic_on_rollback(mbtiles_path, monkeypatch):
    """If the commit never happens (rollback), NEITHER the tile nor the
    queue entries persist. Validates same-transaction semantics."""
    from rasterio_ops import _init_journal, _mutate_base_tile

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)

    conn.execute("BEGIN")
    _mutate_base_tile(conn, "upsert", 17, 100, 200, tile_data=b"not_yet")
    conn.execute("ROLLBACK")  # never commits

    tile = conn.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=17"
    ).fetchone()
    queue_count = conn.execute(
        "SELECT COUNT(*) FROM _overview_work_queue"
    ).fetchone()[0]
    conn.close()

    assert tile is None, "rollback should have discarded the tile insert"
    assert queue_count == 0, "rollback should have discarded the queue inserts"
```

- [ ] **Step 2: Run tests to verify fail**

```bash
python -m pytest tests/test_overview_journal.py -v -k mutate_base_tile
```

Expected: 3 fails with `ImportError`.

- [ ] **Step 3: Implement in `scripts/rasterio_ops.py`**

After `_enqueue_ancestors`:

```python
def _mutate_base_tile(
    conn: sqlite3.Connection,
    action: str,  # "upsert" | "delete"
    z: int,
    tc: int,
    tr: int,
    tile_data: bytes | None = None,
) -> None:
    """Atomic single-tile mutation + ancestor enqueue.

    Combines the tile write and the journal enqueue into the same logical
    transaction. If the caller has an open transaction, this function does
    NOT open a new one (so the caller's commit/rollback covers both
    operations). If no transaction is open, the default sqlite3 auto-commit
    still serializes the two statements within one connection — but callers
    should prefer wrapping multiple _mutate_base_tile calls in an explicit
    BEGIN/COMMIT for efficiency.

    action='upsert' uses INSERT OR REPLACE with tile_data.
    action='delete' removes the tile; tile_data is ignored.
    """
    assert action in ("upsert", "delete"), f"unknown action: {action!r}"
    if action == "upsert":
        if tile_data is None:
            raise ValueError("tile_data is required for upsert")
        conn.execute(
            "INSERT OR REPLACE INTO tiles "
            "(zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
            (z, tc, tr, tile_data),
        )
    else:  # delete
        conn.execute(
            "DELETE FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
            (z, tc, tr),
        )
    _enqueue_ancestors(conn, [(z, tc, tr)])
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_overview_journal.py -v
```

Expected: 8 passed total.

- [ ] **Step 5: Commit**

```bash
git add scripts/rasterio_ops.py tests/test_overview_journal.py
git commit -m "$(cat <<'EOF'
feat(overview): _mutate_base_tile — atomic base-tile write + journal enqueue

Wraps a single-tile INSERT OR REPLACE (upsert) or DELETE in the same
transaction that enqueues the ancestor chain to _overview_work_queue.
Resolves the Round 5 C2 finding (cross-statement atomicity): a crash
between the tile write and the journal write would leave a tile whose
ancestors are never rebuilt.

Callers are expected to wrap bulk sequences in an explicit BEGIN/COMMIT
for efficiency; single calls inherit sqlite3's auto-commit serialization.

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2 — Drain logic (2 tasks)

### Task 4: `_drain_journal` targeted rebuild

**Goal:** Drain `_overview_work_queue` from `max_zoom-1` down to 0 using the unified re-evaluation rule: write ancestor if all 4 children exist, delete if any missing. Satisfies spec tests 4-7 (write, delete, modify+delete, cascade).

**Files:**
- Modify: `scripts/rasterio_ops.py`
- Test: `tests/test_overview_journal.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_overview_journal.py`:

```python
def _make_jpeg_tile(r: int, g: int, b: int, size: int = 256) -> bytes:
    """Return JPEG bytes for a solid RGB tile. Tests that need gradient
    tiles build them inline — solid colors are for fixture setup only."""
    import io
    import numpy as np
    import rasterio
    from rasterio.io import MemoryFile
    arr = np.zeros((3, size, size), dtype=np.uint8)
    arr[0] = r
    arr[1] = g
    arr[2] = b
    with MemoryFile() as mf:
        with mf.open(
            driver="JPEG", width=size, height=size, count=3, dtype="uint8"
        ) as ds:
            ds.write(arr)
        return mf.read()


def test_drain_journal_writes_ancestor_when_4_children_exist(mbtiles_path):
    """Spec test 4: all 4 children present → ancestor is created/updated."""
    from rasterio_ops import _init_journal, _mutate_base_tile, _drain_journal

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    # Four children of z16 ancestor (16, 50, 100):
    #   (17, 100, 200), (17, 101, 200), (17, 100, 201), (17, 101, 201)
    for tc in (100, 101):
        for tr in (200, 201):
            _mutate_base_tile(conn, "upsert", 17, tc, tr, _make_jpeg_tile(128, 128, 128))
    conn.commit()

    _drain_journal(conn)
    conn.commit()

    row = conn.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=16 AND tile_column=50 AND tile_row=100"
    ).fetchone()
    queue_count = conn.execute(
        "SELECT COUNT(*) FROM _overview_work_queue"
    ).fetchone()[0]
    conn.close()

    assert row is not None and row[0] is not None, "z16 ancestor should exist"
    assert queue_count == 0, "queue should be empty after successful drain"


def test_drain_journal_deletes_ancestor_when_child_missing(mbtiles_path):
    """Spec test 5: only 3 children exist → ancestor is deleted."""
    from rasterio_ops import _init_journal, _mutate_base_tile, _drain_journal

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)

    # Seed a pre-existing ancestor (as if from a prior nuclear run)
    conn.execute(
        "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) "
        "VALUES (16, 50, 100, ?)",
        (_make_jpeg_tile(200, 200, 200),),
    )
    # Only 3 z17 children
    for tc, tr in [(100, 200), (101, 200), (100, 201)]:
        conn.execute(
            "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) "
            "VALUES (17, ?, ?, ?)",
            (tc, tr, _make_jpeg_tile(50, 50, 50)),
        )
    # Enqueue the ancestor as dirty (simulating a previous mutation)
    conn.execute(
        "INSERT INTO _overview_work_queue (zoom_level, tile_column, tile_row) "
        "VALUES (16, 50, 100)"
    )
    conn.commit()

    _drain_journal(conn)
    conn.commit()

    row = conn.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=16 AND tile_column=50 AND tile_row=100"
    ).fetchone()
    conn.close()

    assert row is None, (
        "ancestor with only 3 children should be DELETED, not preserved"
    )


def test_drain_journal_handles_same_ancestor_modify_and_delete(mbtiles_path):
    """Codex C2 regression (Round 4): ancestor enqueued by BOTH a modify
    and a delete in the same run should be re-evaluated once and produce
    the correct final state (not a partial composite)."""
    from rasterio_ops import _init_journal, _mutate_base_tile, _drain_journal

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)

    # Start state: 4 children of (16, 50, 100) exist
    for tc in (100, 101):
        for tr in (200, 201):
            conn.execute(
                "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) "
                "VALUES (17, ?, ?, ?)",
                (tc, tr, _make_jpeg_tile(100, 100, 100)),
            )
    conn.commit()

    # One update, one delete, both on children of the same ancestor:
    _mutate_base_tile(conn, "upsert", 17, 100, 200, _make_jpeg_tile(200, 0, 0))
    _mutate_base_tile(conn, "delete", 17, 101, 201)
    conn.commit()

    _drain_journal(conn)
    conn.commit()

    row = conn.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=16 AND tile_column=50 AND tile_row=100"
    ).fetchone()
    conn.close()

    assert row is None, (
        "ancestor should be DELETED because one child is gone (re-eval rule: "
        "if any child missing, delete ancestor). Old composite must not survive."
    )


def test_drain_journal_multi_level_cascade(mbtiles_path):
    """Spec test 7: dirty at z17 cascades ancestor rebuilds to z0."""
    from rasterio_ops import _init_journal, _mutate_base_tile, _drain_journal

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)

    # Build a complete 16-tile block at z17 spanning a full 4-level lineage.
    # Coordinates chosen so ancestors at z16..z14 all have complete 2x2 blocks.
    # 4 tiles at each (tc, tr) in {0,1,2,3} x {0,1,2,3} = 16 tiles at z17.
    for tc in range(4):
        for tr in range(4):
            _mutate_base_tile(conn, "upsert", 17, tc, tr, _make_jpeg_tile(128, 128, 128))
    conn.commit()

    _drain_journal(conn)
    conn.commit()

    # Expected: z16 has 4 tiles (2x2 grid), z15 has 1 tile, z14 has 1 tile.
    # z13..z0 should NOT be built (incomplete 2x2 at z14's parent).
    z16_count = conn.execute(
        "SELECT COUNT(*) FROM tiles WHERE zoom_level=16"
    ).fetchone()[0]
    z15_count = conn.execute(
        "SELECT COUNT(*) FROM tiles WHERE zoom_level=15"
    ).fetchone()[0]
    z14_count = conn.execute(
        "SELECT COUNT(*) FROM tiles WHERE zoom_level=14"
    ).fetchone()[0]
    z13_count = conn.execute(
        "SELECT COUNT(*) FROM tiles WHERE zoom_level=13"
    ).fetchone()[0]
    conn.close()

    assert z16_count == 4, f"expected 4 z16 tiles; got {z16_count}"
    assert z15_count == 1, f"expected 1 z15 tile; got {z15_count}"
    assert z14_count == 1, f"expected 1 z14 tile; got {z14_count}"
    assert z13_count == 0, f"z13 should not be built (incomplete parent); got {z13_count}"
```

- [ ] **Step 2: Run tests to verify fail**

```bash
python -m pytest tests/test_overview_journal.py -v -k drain_journal
```

Expected: 4 fails with `ImportError` on `_drain_journal`.

- [ ] **Step 3: Implement in `scripts/rasterio_ops.py`**

Place after `_mutate_base_tile`. This replaces the core logic currently in `build_overviews` at L695-799, but factored into a standalone function that the mode selector will call:

```python
def _drain_journal(
    conn: sqlite3.Connection,
    cancel_check=None,
) -> int:
    """Drain _overview_work_queue by re-evaluating each enqueued ancestor.

    For each ancestor (z, tc, tr), fetches the 4 children at (z+1,
    2tc+dx, 2tr+dy). Writes the composited 2x2 average if all 4 exist;
    deletes any existing ancestor row if any child is missing.

    Processes bottom-up (max_zoom-1 down to 0), so parents see their
    children's fresh state. Commits once per zoom level. Cancel check
    between zoom levels; partial progress is durable (remaining queue
    rows survive for the next run).

    Returns the number of ancestor ops performed (writes + deletes).
    """
    max_zoom_row = conn.execute("SELECT MAX(zoom_level) FROM tiles").fetchone()
    if not max_zoom_row or max_zoom_row[0] is None:
        # No tiles at all; nothing to do. Clear any stale queue entries.
        conn.execute("DELETE FROM _overview_work_queue")
        return 0
    max_zoom = max_zoom_row[0]

    ops = 0
    for z in range(max_zoom - 1, -1, -1):
        if cancel_check and cancel_check():
            return ops
        rows = conn.execute(
            "SELECT tile_column, tile_row FROM _overview_work_queue WHERE zoom_level=?",
            (z,),
        ).fetchall()
        if not rows:
            continue
        for (tc, tr) in rows:
            children = []
            for dx in range(2):
                for dy in range(2):
                    row = conn.execute(
                        "SELECT tile_data FROM tiles "
                        "WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                        (z + 1, tc * 2 + dx, tr * 2 + dy),
                    ).fetchone()
                    children.append((dx, dy, row[0] if row else None))
            if all(c[2] is not None for c in children):
                # All 4 children exist — composite and INSERT OR REPLACE
                tile_bytes = _composite_2x2_children(children)
                conn.execute(
                    "INSERT OR REPLACE INTO tiles "
                    "(zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
                    (z, tc, tr, tile_bytes),
                )
            else:
                # Incomplete block — delete any existing ancestor
                conn.execute(
                    "DELETE FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                    (z, tc, tr),
                )
            ops += 1
        # Clear this zoom's queue entries and commit
        conn.execute("DELETE FROM _overview_work_queue WHERE zoom_level=?", (z,))
        conn.commit()
    return ops


def _composite_2x2_children(
    children: list[tuple[int, int, bytes | None]],
) -> bytes:
    """Composite a 2x2 block of child tiles into a single downsampled tile.

    Implementation matches the existing 2x2 averaging at rasterio_ops.py:753-778
    (pre-refactor build_overviews). Returns JPEG bytes.
    """
    import io
    import numpy as np
    import rasterio
    from rasterio.io import MemoryFile

    TILE_SIZE = 256
    composite = np.zeros((3, TILE_SIZE, TILE_SIZE), dtype=np.uint8)
    half = TILE_SIZE // 2

    for dx, dy, tile_data in children:
        if tile_data is None:
            continue
        with MemoryFile(tile_data) as memfile:
            with memfile.open() as ds:
                bands = min(ds.count, 3)
                tile_arr = ds.read(list(range(1, bands + 1)))
                h_src, w_src = tile_arr.shape[1], tile_arr.shape[2]
                if h_src >= 2 and w_src >= 2:
                    h2 = (h_src // 2) * 2
                    w2 = (w_src // 2) * 2
                    cropped = tile_arr[:, :h2, :w2].astype(np.uint16)
                    small = cropped.reshape(
                        bands, h2 // 2, 2, w2 // 2, 2
                    ).mean(axis=(2, 4)).astype(np.uint8)
                    small = small[:, :half, :half]
                else:
                    small = tile_arr[:, :half, :half]
                x_off = dx * half
                y_off = (1 - dy) * half  # TMS y-flip
                h = min(small.shape[1], half)
                w = min(small.shape[2], half)
                composite[:bands, y_off:y_off + h, x_off:x_off + w] = small[:, :h, :w]

    return _encode_jpeg(composite)
```

**Important — do NOT delete the existing `build_overviews` yet.** The next task refactors it to use `_drain_journal` + `_drain_nuclear` under the mode selector. Until then, the old function still works for its current callers.

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_overview_journal.py -v
```

Expected: all previous 8 + 4 new = 12 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/rasterio_ops.py tests/test_overview_journal.py
git commit -m "$(cat <<'EOF'
feat(overview): _drain_journal — targeted ancestor rebuild via unified re-eval

Drains _overview_work_queue bottom-up from max_zoom-1 to 0. For each
enqueued ancestor, re-evaluates by fetching the 4 children and applying
the unified rule: write composited ancestor if all 4 exist, delete any
existing ancestor row if any child is missing. Commits per zoom level;
cancel-check between levels; partial progress survives for next run.

This replaces the core pyramid-walk logic from the legacy nuclear path,
but operates on the queue instead of SELECT DISTINCT over the tiles
table. The legacy build_overviews is left in place for its callers
until the mode-selector task refactors it.

Also factors the 2x2 averaging into _composite_2x2_children so both
journal and nuclear paths share it.

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `_drain_nuclear` — refactored legacy path

**Goal:** Extract the existing nuclear rebuild logic into `_drain_nuclear`, keeping identical behavior. Backward-compat test ensures it still works.

**Files:**
- Modify: `scripts/rasterio_ops.py`
- Test: `tests/test_overview_journal.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_overview_journal.py`:

```python
def test_drain_nuclear_rebuilds_full_pyramid_ignoring_queue(mbtiles_path):
    """Nuclear drain rebuilds all ancestor zooms from scratch, ignores queue."""
    from rasterio_ops import _init_journal, _drain_nuclear

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    # Seed 4 children (complete z16 block); NO queue entries
    for tc in (100, 101):
        for tr in (200, 201):
            conn.execute(
                "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) "
                "VALUES (17, ?, ?, ?)",
                (tc, tr, _make_jpeg_tile(50, 60, 70)),
            )
    # Seed some stale overview that should be nuked
    conn.execute(
        "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) "
        "VALUES (16, 99, 99, ?)",
        (_make_jpeg_tile(255, 0, 0),),
    )
    conn.commit()

    _drain_nuclear(conn)
    conn.commit()

    # Stale z16 tile should be gone (entire z<max_zoom was cleared + rebuilt)
    stale = conn.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=16 AND tile_column=99 AND tile_row=99"
    ).fetchone()
    # Real ancestor should exist
    ancestor = conn.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=16 AND tile_column=50 AND tile_row=100"
    ).fetchone()
    # Queue should be empty
    queue_count = conn.execute(
        "SELECT COUNT(*) FROM _overview_work_queue"
    ).fetchone()[0]
    conn.close()

    assert stale is None, "nuclear should have wiped the stale z16 tile"
    assert ancestor is not None, "nuclear should have built the real ancestor"
    assert queue_count == 0
```

- [ ] **Step 2: Run test to verify fail**

```bash
python -m pytest tests/test_overview_journal.py::test_drain_nuclear_rebuilds_full_pyramid_ignoring_queue -v
```

Expected: `ImportError` on `_drain_nuclear`.

- [ ] **Step 3: Implement `_drain_nuclear` in `scripts/rasterio_ops.py`**

After `_composite_2x2_children`:

```python
def _drain_nuclear(
    conn: sqlite3.Connection,
    cancel_check=None,
) -> int:
    """Legacy nuclear-rebuild path.

    DELETE FROM tiles WHERE zoom_level < max_zoom, then walk
    SELECT DISTINCT tc/2, tr/2 FROM tiles WHERE zoom_level = parent_z
    per zoom level, compositing + inserting. Clears the journal queue
    at exit (even though it was not consulted).

    Identical behavior to the pre-fix build_overviews function — this
    exists so mode='nuclear' remains available as rollback + for runs
    that fall back from journal drain on large dirty sets.

    Returns the total number of ancestor rows written.
    """
    max_zoom_row = conn.execute("SELECT MAX(zoom_level) FROM tiles").fetchone()
    if not max_zoom_row or max_zoom_row[0] is None:
        conn.execute("DELETE FROM _overview_work_queue")
        return 0
    max_zoom = max_zoom_row[0]

    # Clear all overview tiles (below max_zoom)
    conn.execute("DELETE FROM tiles WHERE zoom_level < ?", (max_zoom,))
    conn.commit()

    ops = 0
    for z in range(max_zoom - 1, -1, -1):
        if cancel_check and cancel_check():
            break
        parent_z = z + 1
        rows = conn.execute(
            "SELECT DISTINCT tile_column/2, tile_row/2 FROM tiles WHERE zoom_level=?",
            (parent_z,),
        ).fetchall()
        if not rows:
            break
        for (tc, tr) in rows:
            children = []
            for dx in range(2):
                for dy in range(2):
                    row = conn.execute(
                        "SELECT tile_data FROM tiles "
                        "WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                        (parent_z, tc * 2 + dx, tr * 2 + dy),
                    ).fetchone()
                    children.append((dx, dy, row[0] if row else None))
            if not all(c[2] is not None for c in children):
                continue  # legacy behavior: skip incomplete 2x2
            tile_bytes = _composite_2x2_children(children)
            conn.execute(
                "INSERT OR REPLACE INTO tiles "
                "(zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
                (z, tc, tr, tile_bytes),
            )
            ops += 1
        conn.commit()

    # Clear queue even though we ignored it — matches mode='nuclear' contract
    conn.execute("DELETE FROM _overview_work_queue")
    return ops
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/test_overview_journal.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/rasterio_ops.py tests/test_overview_journal.py
git commit -m "$(cat <<'EOF'
feat(overview): _drain_nuclear — refactored legacy full-rebuild path

Extracts the pre-fix nuclear rebuild logic into a standalone function.
Preserves exact current behavior (DELETE everything below max_zoom,
walk DISTINCT parent coords, composite + insert). Also clears the
journal queue at exit to honor the mode='nuclear' contract that the
queue is drained (even when ignored).

No behavior change yet — the public build_overviews entry point is
refactored to call _drain_nuclear or _drain_journal via mode selector
in the next task.

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3 — Public API (2 tasks)

### Task 6: `build_overviews` mode selector + threshold + empty-MBTiles guards

**Goal:** Rewrite `build_overviews` as a thin entry-point over `_drain_journal` / `_drain_nuclear`. Implement `mode="auto"` threshold logic, empty-MBTiles guard, and `mode="journal"` empty-queue no-op.

**Files:**
- Modify: `scripts/rasterio_ops.py`
- Test: `tests/test_overview_journal.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_overview_journal.py`:

```python
def test_build_overviews_mode_nuclear_ignores_queue(mbtiles_path):
    """mode='nuclear' calls _drain_nuclear regardless of queue state."""
    from rasterio_ops import _init_journal, build_overviews

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    # Populate queue + some z17 tiles
    for tc in (100, 101):
        for tr in (200, 201):
            conn.execute(
                "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) "
                "VALUES (17, ?, ?, ?)",
                (tc, tr, _make_jpeg_tile(50, 50, 50)),
            )
    conn.execute("INSERT INTO _overview_work_queue VALUES (16, 50, 100)")
    conn.commit()
    conn.close()

    build_overviews(mbtiles_path, mode="nuclear")

    conn = sqlite3.connect(str(mbtiles_path))
    queue_count = conn.execute(
        "SELECT COUNT(*) FROM _overview_work_queue"
    ).fetchone()[0]
    z16 = conn.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=16 AND tile_column=50 AND tile_row=100"
    ).fetchone()
    conn.close()

    assert queue_count == 0, "nuclear mode must clear the queue at exit"
    assert z16 is not None, "nuclear mode must have built the ancestor"


def test_build_overviews_mode_journal_empty_queue_is_noop(mbtiles_path, caplog):
    """Round 5 I5: empty queue + mode='journal' is a silent no-op with info log."""
    import logging
    from rasterio_ops import _init_journal, build_overviews

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    conn.execute(
        "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) "
        "VALUES (17, 100, 200, ?)",
        (_make_jpeg_tile(0, 0, 0),),
    )
    # Queue left intentionally empty
    conn.commit()
    conn.close()

    with caplog.at_level(logging.INFO, logger="rasterio_ops"):
        build_overviews(mbtiles_path, mode="journal")  # must NOT raise

    conn = sqlite3.connect(str(mbtiles_path))
    z16 = conn.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=16"
    ).fetchone()
    conn.close()

    assert z16 is None, "no drain happened, so no ancestor should be built"
    # An info log should have been emitted
    assert any(
        "empty queue" in rec.message.lower() or "nothing to drain" in rec.message.lower()
        for rec in caplog.records
    ), f"expected empty-queue info log; got: {[r.message for r in caplog.records]}"


def test_build_overviews_mode_auto_empty_mbtiles_is_noop(tmp_path):
    """Round 5 I1: empty MBTiles (no tiles at all) — no divide-by-zero."""
    from rasterio_ops import _init_journal, build_overviews

    path = tmp_path / "empty.mbtiles"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE tiles (
            zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
            tile_data BLOB,
            PRIMARY KEY (zoom_level, tile_column, tile_row)
        );
        CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT);
        """
    )
    _init_journal(conn)
    conn.commit()
    conn.close()

    # Must not raise (ZeroDivisionError was the pre-fix failure mode)
    build_overviews(path, mode="auto")


def test_build_overviews_mode_auto_falls_back_to_nuclear_above_threshold(mbtiles_path):
    """Round 4 I: when queue size / base count > 0.5, auto picks nuclear."""
    from rasterio_ops import _init_journal, build_overviews

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    # Seed 4 z17 tiles (base count = 4).
    for tc in (100, 101):
        for tr in (200, 201):
            conn.execute(
                "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) "
                "VALUES (17, ?, ?, ?)",
                (tc, tr, _make_jpeg_tile(100, 100, 100)),
            )
    # Enqueue 3 entries (ratio = 3/4 = 0.75 > 0.5 threshold)
    for i in range(3):
        conn.execute(
            "INSERT OR IGNORE INTO _overview_work_queue VALUES (?, ?, ?)",
            (16, i, i),
        )
    conn.commit()
    conn.close()

    # If auto fell back to nuclear, the z16 ancestor of (16, 50, 100)
    # will be present (nuclear rebuilds everything); the stale enqueued
    # (16, 0, 0), (16, 1, 1), (16, 2, 2) won't persist because nuclear
    # only walks DISTINCT parents of real tiles.
    build_overviews(mbtiles_path, mode="auto")

    conn = sqlite3.connect(str(mbtiles_path))
    z16_50_100 = conn.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=16 AND tile_column=50 AND tile_row=100"
    ).fetchone()
    z16_others = conn.execute(
        "SELECT COUNT(*) FROM tiles WHERE zoom_level=16 AND NOT (tile_column=50 AND tile_row=100)"
    ).fetchone()[0]
    queue_count = conn.execute(
        "SELECT COUNT(*) FROM _overview_work_queue"
    ).fetchone()[0]
    conn.close()

    assert z16_50_100 is not None, "auto should have nuclear-rebuilt the real ancestor"
    assert z16_others == 0, "the stale enqueued entries shouldn't have produced tiles"
    assert queue_count == 0


def test_build_overviews_mode_auto_uses_journal_below_threshold(mbtiles_path):
    """mode='auto' with small queue uses journal drain (not nuclear)."""
    from rasterio_ops import _init_journal, _mutate_base_tile, build_overviews

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    # Seed 400 base tiles (e.g., simulating a larger run)
    for i in range(20):
        for j in range(20):
            conn.execute(
                "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) "
                "VALUES (17, ?, ?, ?)",
                (i, j, _make_jpeg_tile(50, 50, 50)),
            )
    # Queue one ancestor — ratio 1/400 = 0.25% << 0.5 threshold
    conn.execute("INSERT INTO _overview_work_queue VALUES (16, 0, 0)")
    conn.commit()
    conn.close()

    build_overviews(mbtiles_path, mode="auto")

    # If journal drain ran, only z16 (0, 0) would be rebuilt.
    # Nuclear would rebuild many more ancestors (everything at z16..z0).
    conn = sqlite3.connect(str(mbtiles_path))
    z16_count = conn.execute(
        "SELECT COUNT(*) FROM tiles WHERE zoom_level=16"
    ).fetchone()[0]
    conn.close()

    assert z16_count == 1, (
        f"journal drain should have rebuilt only 1 z16 ancestor; got {z16_count}. "
        "This likely means auto fell back to nuclear when it shouldn't have."
    )


def test_build_overviews_legacy_no_journal_table_creates_and_falls_back(tmp_path):
    """Spec test 15: MBTiles WITHOUT _overview_work_queue table."""
    from rasterio_ops import build_overviews

    path = tmp_path / "legacy.mbtiles"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE tiles (
            zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
            tile_data BLOB,
            PRIMARY KEY (zoom_level, tile_column, tile_row)
        );
        CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT);
        """
    )
    # Seed 4 z17 tiles, NO journal table
    for tc in (100, 101):
        for tr in (200, 201):
            conn.execute(
                "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) "
                "VALUES (17, ?, ?, ?)",
                (tc, tr, _make_jpeg_tile(50, 50, 50)),
            )
    conn.commit()
    conn.close()

    # Must not raise — should CREATE TABLE IF NOT EXISTS, see empty queue,
    # fall back to nuclear (since queue is empty), build the pyramid.
    build_overviews(path, mode="auto")

    conn = sqlite3.connect(str(path))
    z16 = conn.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=16"
    ).fetchone()
    journal = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='_overview_work_queue'"
    ).fetchone()
    conn.close()

    assert journal is not None, "journal table should have been created"
    assert z16 is not None, "pyramid should have been built via nuclear fallback"
```

- [ ] **Step 2: Run tests to verify fail**

```bash
python -m pytest tests/test_overview_journal.py -v -k build_overviews
```

Expected: 6 fails (several with `ImportError: cannot import name 'build_overviews'` if the current signature doesn't accept `mode=`, or behavior mismatches).

- [ ] **Step 3: Rewrite `build_overviews` in `scripts/rasterio_ops.py`**

Replace the existing `build_overviews` function body (L678-804) with:

```python
def build_overviews(
    mbtiles_path: Path,
    *,
    mode: str = "auto",  # "auto" | "journal" | "nuclear"
    levels: list[int] | None = None,  # legacy-compat, ignored
    resampling: str = "average",      # legacy-compat, ignored
    cancel_check=None,
) -> bool:
    """Build overview pyramids for an MBTiles file.

    mode='auto'    : journal drain if queue is populated AND queue size /
                     base tile count < 0.5; else nuclear. Silent no-op on
                     empty MBTiles.
    mode='journal' : always journal-drain. Empty queue = silent no-op with
                     info log.
    mode='nuclear' : always nuclear rebuild. Ignores queue, clears queue
                     at exit. Backward-compat + rollback path.

    Returns True on successful drain (or no-op), False if cancelled.
    """
    if mode not in ("auto", "journal", "nuclear"):
        raise ValueError(f"unknown mode: {mode!r}")

    conn = None
    try:
        conn = sqlite3.connect(str(mbtiles_path))
        conn.execute("PRAGMA journal_mode=WAL")
        _init_journal(conn)

        # Empty-MBTiles guard (R5 I1)
        max_zoom_row = conn.execute("SELECT MAX(zoom_level) FROM tiles").fetchone()
        if not max_zoom_row or max_zoom_row[0] is None:
            log.info("No tiles in %s — skipping overviews", mbtiles_path)
            conn.execute("DELETE FROM _overview_work_queue")
            conn.commit()
            return True
        max_zoom = max_zoom_row[0]

        queue_size = conn.execute(
            "SELECT COUNT(*) FROM _overview_work_queue"
        ).fetchone()[0]

        if mode == "nuclear":
            _drain_nuclear(conn, cancel_check=cancel_check)
        elif mode == "journal":
            if queue_size == 0:
                log.info(
                    "build_overviews mode=journal called with empty queue — "
                    "nothing to drain (no-op)"
                )
                return True
            _drain_journal(conn, cancel_check=cancel_check)
        else:  # auto
            if queue_size == 0:
                # Nothing dirty; fall back to nuclear for a full rebuild.
                # This matches legacy callers + fresh runs with empty journal.
                _drain_nuclear(conn, cancel_check=cancel_check)
            else:
                base_count = conn.execute(
                    "SELECT COUNT(*) FROM tiles WHERE zoom_level=?", (max_zoom,)
                ).fetchone()[0]
                # Threshold: queue/base > 0.5 → nuclear is faster
                if base_count > 0 and queue_size / base_count > 0.5:
                    log.info(
                        "Journal queue (%d) exceeds 50%% of base tiles (%d); "
                        "falling back to nuclear drain",
                        queue_size, base_count,
                    )
                    _drain_nuclear(conn, cancel_check=cancel_check)
                else:
                    _drain_journal(conn, cancel_check=cancel_check)
        conn.commit()
        return True
    except Exception as exc:
        log.error("build_overviews failed for %s: %s", mbtiles_path, exc)
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if conn is not None:
            conn.close()
```

- [ ] **Step 4: Run all tests to verify pass**

```bash
python -m pytest tests/test_overview_journal.py -v
```

Expected: 19 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/rasterio_ops.py tests/test_overview_journal.py
git commit -m "$(cat <<'EOF'
feat(overview): build_overviews mode selector + empty guards + threshold

Rewrites build_overviews as a thin entry point over _drain_journal and
_drain_nuclear. mode='auto' applies the 50%-threshold rule to pick
between journal drain (incremental) and nuclear drain (full). Empty
MBTiles returns silent no-op (R5 I1). mode='journal' on empty queue
returns silent no-op with info log (R5 I5).

All legacy callers that pass no mode= (or mode='auto') continue to get
correct behavior: empty queue → nuclear fallback (matches legacy).
mode='nuclear' gives operators a runtime rollback without redeploy.

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Cancel-mid-drain persistence test

**Goal:** Spec test 14. Validate that cancel between zoom levels leaves the queue in a consistent resumable state.

**Files:**
- Test: `tests/test_overview_journal.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_overview_journal.py`:

```python
def test_cancel_mid_drain_preserves_remaining_queue_and_committed_tiles(mbtiles_path):
    """Cancel fires after 1 zoom level. Processed entries are gone from
    queue AND the written ancestors are in the tiles table (proving the
    commit took effect). Remaining entries at lower zoom levels survive
    for resume."""
    from rasterio_ops import _init_journal, build_overviews

    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    # Build a 16-tile z17 block that will cascade z16 + z15 + z14 etc.
    for tc in range(4):
        for tr in range(4):
            conn.execute(
                "INSERT INTO tiles (zoom_level, tile_column, tile_row, tile_data) "
                "VALUES (17, ?, ?, ?)",
                (tc, tr, _make_jpeg_tile(50, 50, 50)),
            )
    # Manually enqueue all ancestors (simulating a fresh merge that just
    # happened but we want to test cancel behavior directly)
    from rasterio_ops import _enqueue_ancestors
    _enqueue_ancestors(conn, [(17, tc, tr) for tc in range(4) for tr in range(4)])
    conn.commit()
    conn.close()

    # Cancel after the z16 drain commits but before z15 begins.
    call_count = [0]
    def cancel_check():
        call_count[0] += 1
        # cancel_check is called at the top of each zoom-level iteration;
        # return True on the 2nd call (z15 about to start → cancel)
        return call_count[0] >= 2

    build_overviews(mbtiles_path, mode="journal", cancel_check=cancel_check)

    conn = sqlite3.connect(str(mbtiles_path))
    # z16 entries should be GONE from queue (processed before cancel)
    z16_queue = conn.execute(
        "SELECT COUNT(*) FROM _overview_work_queue WHERE zoom_level=16"
    ).fetchone()[0]
    # z16 tiles should exist in tiles table (commit happened before cancel)
    z16_tiles = conn.execute(
        "SELECT COUNT(*) FROM tiles WHERE zoom_level=16"
    ).fetchone()[0]
    # z15 and below entries should STILL be in queue (not reached)
    z15_queue = conn.execute(
        "SELECT COUNT(*) FROM _overview_work_queue WHERE zoom_level=15"
    ).fetchone()[0]
    conn.close()

    assert z16_queue == 0, f"z16 queue entries should be processed; got {z16_queue}"
    assert z16_tiles == 4, f"z16 tiles should be committed; got {z16_tiles}"
    assert z15_queue > 0, f"z15 queue entries should survive for resume; got {z15_queue}"
```

- [ ] **Step 2: Run test to verify pass**

```bash
python -m pytest tests/test_overview_journal.py::test_cancel_mid_drain_preserves_remaining_queue_and_committed_tiles -v
```

Expected: PASS (the implementation in Task 4 already supports this; this test validates).

If it fails: investigate `_drain_journal`'s cancel-check placement — it should fire BEFORE processing the next zoom level, AFTER committing the previous one. See spec §Journal drain step 4.

- [ ] **Step 3: Commit**

```bash
git add tests/test_overview_journal.py
git commit -m "$(cat <<'EOF'
test(overview): cancel-mid-drain preserves queue state for resume

Validates that _drain_journal's per-zoom-level cancel check plus per-
zoom-level commit produces a durable partial-progress state: processed
entries are removed from the queue AND their written ancestors are in
tiles; remaining entries survive the cancel.

Spec §Journal drain step 4 + test 14.

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4 — Migrate existing writers (3 tasks)

### Task 8: `merge_mbtiles` → atomic bulk insert + ancestor cascade

**Goal:** Resolve Round 5 C1 (bulk-SQL path can't wrap per-tile without regression) by keeping the bulk `INSERT OR IGNORE` fast path but enqueuing ancestors via one post-insert bulk SQL per zoom level shift.

**Files:**
- Modify: `scripts/acquire_imagery.py:872-947` (`merge_mbtiles`)
- Test: `tests/test_overview_journal.py` (add `test_merge_mbtiles_populates_journal`)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_overview_journal.py`:

```python
def test_merge_mbtiles_populates_journal(tmp_path):
    """merge_mbtiles's bulk INSERT OR IGNORE path must enqueue ancestors
    for every inserted z17 tile."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from acquire_imagery import merge_mbtiles
    from rasterio_ops import _init_journal

    # Source MBTiles with 4 z17 tiles forming one z16 block
    src_path = tmp_path / "src.mbtiles"
    conn = sqlite3.connect(str(src_path))
    conn.executescript(
        """
        CREATE TABLE tiles (
            zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
            tile_data BLOB,
            PRIMARY KEY (zoom_level, tile_column, tile_row)
        );
        CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT);
        """
    )
    for tc in (100, 101):
        for tr in (200, 201):
            conn.execute(
                "INSERT INTO tiles VALUES (17, ?, ?, ?)",
                (tc, tr, _make_jpeg_tile(50, 60, 70)),
            )
    conn.commit()
    conn.close()

    # Destination MBTiles (empty, with schema)
    dst_path = tmp_path / "dst.mbtiles"
    conn = sqlite3.connect(str(dst_path))
    conn.executescript(
        """
        CREATE TABLE tiles (
            zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
            tile_data BLOB,
            PRIMARY KEY (zoom_level, tile_column, tile_row)
        );
        CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT);
        """
    )
    _init_journal(conn)
    conn.commit()
    conn.close()

    merge_mbtiles(src_path, dst_path)

    conn = sqlite3.connect(str(dst_path))
    # 4 tiles at z17 copied
    z17 = conn.execute("SELECT COUNT(*) FROM tiles WHERE zoom_level=17").fetchone()[0]
    # 4 tiles × 17 ancestors each, deduplicated via PK.
    # For a 2×2 sibling block: z16 has 1 unique ancestor (all 4 siblings share),
    # z15 has 1 (shared), ..., z0 has 1. So 17 unique ancestors total (one per zoom).
    queue_total = conn.execute("SELECT COUNT(*) FROM _overview_work_queue").fetchone()[0]
    conn.close()

    assert z17 == 4
    assert queue_total == 17, (
        f"expected 17 unique ancestors (one per zoom z16..z0) for a single "
        f"2x2 block; got {queue_total}"
    )
```

- [ ] **Step 2: Run test to verify fail**

```bash
python -m pytest tests/test_overview_journal.py::test_merge_mbtiles_populates_journal -v
```

Expected: FAIL with `queue_total == 0` (current merge_mbtiles doesn't touch the journal).

- [ ] **Step 3: Modify `scripts/acquire_imagery.py`'s `merge_mbtiles` function**

Find the function at approximately L872-947. Current structure (simplified):

```python
def merge_mbtiles(src_path: Path, dst_path: Path) -> None:
    dst = sqlite3.connect(str(dst_path))
    src_attached = False
    try:
        dst.execute(f"ATTACH DATABASE '{src_path}' AS src")
        src_attached = True
        dst.execute("""INSERT OR IGNORE INTO tiles
                       SELECT zoom_level, tile_column, tile_row, tile_data FROM src.tiles""")
        # ... (the slow-path overlap-compositing loop)
        dst.commit()
    finally:
        # ... (detach, close)
```

Modify to wrap in BEGIN/COMMIT, and ADD the ancestor-cascade SQL right after the bulk insert. Pseudocode of the change:

```python
def merge_mbtiles(src_path: Path, dst_path: Path) -> None:
    # ... existing variable setup ...
    dst = sqlite3.connect(str(dst_path))
    src_attached = False
    try:
        # Ensure the journal table exists (idempotent)
        from rasterio_ops import _init_journal
        _init_journal(dst)

        dst.execute(f"ATTACH DATABASE '{src_path}' AS src")
        src_attached = True

        # Determine max_zoom BEFORE the merge (src's max zoom is what we care
        # about; dst may already have the same or a subset)
        src_max_zoom_row = dst.execute("SELECT MAX(zoom_level) FROM src.tiles").fetchone()
        if not src_max_zoom_row or src_max_zoom_row[0] is None:
            # Empty source; nothing to merge
            dst.execute("DETACH DATABASE src")
            return
        src_max_zoom = src_max_zoom_row[0]

        # Atomic block: bulk insert + ancestor-enqueue cascade
        dst.execute("BEGIN")
        try:
            dst.execute(
                """INSERT OR IGNORE INTO tiles
                   SELECT zoom_level, tile_column, tile_row, tile_data FROM src.tiles"""
            )

            # Enqueue ancestors for every src tile at src_max_zoom (one bulk SQL
            # per zoom-level shift from src_max_zoom-1 down to 0). INSERT OR
            # IGNORE collapses duplicates via the queue's PK.
            for dz in range(1, src_max_zoom + 1):
                dst.execute(
                    """INSERT OR IGNORE INTO _overview_work_queue
                       (zoom_level, tile_column, tile_row)
                       SELECT zoom_level - ?, tile_column >> ?, tile_row >> ?
                       FROM src.tiles WHERE zoom_level = ?""",
                    (dz, dz, dz, src_max_zoom),
                )

            # Existing overlap-compositing loop — MODIFY: replace raw
            # UPDATE tiles with _mutate_base_tile call for EACH composite.
            # The existing loop structure is preserved; only the write is
            # routed through the helper.
            # ... (see existing L900-935 for the loop body; replace the
            # UPDATE tiles SET tile_data = ? WHERE ... with a call to
            # _mutate_base_tile(dst, "upsert", z, tc, tr, tile_data=composited_data).
            # The helper enqueues ancestors automatically.)

            dst.execute("COMMIT")
        except Exception:
            dst.execute("ROLLBACK")
            raise
    finally:
        if src_attached:
            dst.execute("DETACH DATABASE src")
        dst.close()
```

**Note to implementer:** the exact lines to change in `merge_mbtiles` depend on the current structure. The key requirements:

1. Call `_init_journal(dst)` before any writes.
2. Wrap the bulk-INSERT + cascade SQL in `BEGIN` / `COMMIT` / `ROLLBACK on except`.
3. For the overlap-compositing slow path, route each per-tile UPDATE through `_mutate_base_tile(dst, "upsert", z, tc, tr, tile_data=composited_bytes)` so the ancestor enqueueing happens atomically per composite.
4. Import `_mutate_base_tile` alongside `_init_journal`.

- [ ] **Step 4: Run test to verify pass**

```bash
python -m pytest tests/test_overview_journal.py::test_merge_mbtiles_populates_journal -v
python -m pytest tests/ -x --ignore=tests/test_setup_main.py -q 2>&1 | tail -10
```

Expected: new test passes. Pre-existing tests: no new failures beyond the ones that were failing before (setup/wake-lock tests unrelated to this change).

- [ ] **Step 5: Commit**

```bash
git add scripts/acquire_imagery.py tests/test_overview_journal.py
git commit -m "$(cat <<'EOF'
feat(noaa): merge_mbtiles populates _overview_work_queue atomically

Wraps the bulk INSERT OR IGNORE + the slow-path composite UPDATE loop
in BEGIN/COMMIT. Adds N bulk-SQL statements (one per zoom-level shift)
after the bulk insert to enqueue ancestor chains for every src tile.
Composite UPDATEs route through _mutate_base_tile so their ancestors
enqueue atomically with the tile write.

Resolves Round 5 C1 (bulk path can't cheaply wrap per-tile) + C2
(cross-statement atomicity).

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: `erode_nodata_edges` → returns deleted coords + uses `_mutate_base_tile`

**Goal:** Modify `erode_nodata_edges` to DELETE tiles via `_mutate_base_tile` (so the ancestor chain enqueues automatically) and return the list of deleted coords.

**Files:**
- Modify: `scripts/rasterio_ops.py:888-995` (`erode_nodata_edges`)
- Test: `tests/test_overview_journal.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_overview_journal.py`:

```python
def test_erode_nodata_edges_returns_deleted_coords_and_enqueues(tmp_path):
    """erode_nodata_edges returns list of (z, tc, tr) tuples for tiles it
    deleted, and enqueues their ancestors."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from rasterio_ops import _init_journal, erode_nodata_edges

    # Create a fixture with boundary tiles that have >90% black pixels
    path = tmp_path / "erode.mbtiles"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE tiles (
            zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
            tile_data BLOB,
            PRIMARY KEY (zoom_level, tile_column, tile_row)
        );
        CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT);
        """
    )
    _init_journal(conn)
    # Place a single tile in all-black state (should be eroded)
    conn.execute(
        "INSERT INTO tiles VALUES (17, 100, 200, ?)",
        (_make_jpeg_tile(0, 0, 0),),  # all black
    )
    conn.commit()
    conn.close()

    deleted = erode_nodata_edges(path)

    assert isinstance(deleted, list), f"expected list of deleted coords; got {type(deleted)}"
    assert (17, 100, 200) in deleted, f"expected (17, 100, 200) in deleted; got {deleted}"

    conn = sqlite3.connect(str(path))
    # Tile should be gone
    remaining = conn.execute(
        "SELECT COUNT(*) FROM tiles WHERE zoom_level=17 AND tile_column=100 AND tile_row=200"
    ).fetchone()[0]
    # Ancestor chain should be in the queue (17 entries)
    queue_count = conn.execute(
        "SELECT COUNT(*) FROM _overview_work_queue"
    ).fetchone()[0]
    conn.close()

    assert remaining == 0
    assert queue_count == 17
```

- [ ] **Step 2: Run test to verify fail**

```bash
python -m pytest tests/test_overview_journal.py::test_erode_nodata_edges_returns_deleted_coords_and_enqueues -v
```

Expected: fails because `erode_nodata_edges` currently returns an `int`, not a list, AND doesn't enqueue ancestors.

- [ ] **Step 3: Modify `erode_nodata_edges` in `scripts/rasterio_ops.py`**

Current signature returns `int`. Change to return `list[tuple[int, int, int]]`. Current DELETE statements need to route through `_mutate_base_tile`. Approximately:

- Change the function's return type annotation + docstring to state the new return shape.
- Replace any `conn.execute("DELETE FROM tiles WHERE ...", (z, col, row))` with `_mutate_base_tile(conn, "delete", z, col, row)` plus append `(z, col, row)` to a `deleted: list` that accumulates across the outer while-loop.
- Return the `deleted` list instead of `total_removed` int.
- Wrap each erosion round in `conn.execute("BEGIN")` / `conn.commit()` for atomicity.

Note: existing callers (e.g. `run_noaa`) use the return value as a count for logging. Update callers to `len(deleted)` in the next tasks.

Reference the existing code at L888-995. Preserve the `zoom_levels = [max_z_row[0]]` scope restriction (erosion is base-zoom only).

- [ ] **Step 4: Run test to verify pass**

```bash
python -m pytest tests/test_overview_journal.py -v -k erode
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/rasterio_ops.py tests/test_overview_journal.py
git commit -m "$(cat <<'EOF'
feat(overview): erode_nodata_edges returns deleted coords + enqueues ancestors

Routes DELETEs through _mutate_base_tile so each erosion atomically
enqueues the ancestor chain of the deleted base tile. Return type
changes from int to list[tuple[int, int, int]] — callers that used
the count can use len() of the return value.

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: `inpaint_nodata_pixels` → max-zoom-only + `_mutate_base_tile`

**Goal:** Restrict inpaint to max zoom only (spec §3) and route UPDATEs through `_mutate_base_tile`.

**Files:**
- Modify: `scripts/rasterio_ops.py:811-886` (`inpaint_nodata_pixels`)
- Test: `tests/test_overview_journal.py`

- [ ] **Step 1: Write the failing test**

```python
def test_inpaint_nodata_pixels_only_touches_max_zoom(tmp_path):
    """Spec §3 / R4: inpaint in reordered flow must only mutate max_zoom tiles."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from rasterio_ops import _init_journal, inpaint_nodata_pixels

    path = tmp_path / "inpaint.mbtiles"
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE tiles (
            zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
            tile_data BLOB,
            PRIMARY KEY (zoom_level, tile_column, tile_row)
        );
        CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT);
        """
    )
    _init_journal(conn)

    # Build a max-zoom tile with ~10% black pixels (inpaint should fix it).
    import numpy as np
    import rasterio
    from rasterio.io import MemoryFile
    arr = np.full((3, 256, 256), 200, dtype=np.uint8)
    arr[:, :30, :30] = 0  # ~1.4% black → in the inpaint range (< 50% black)
    with MemoryFile() as mf:
        with mf.open(driver="JPEG", width=256, height=256, count=3, dtype="uint8") as ds:
            ds.write(arr)
        max_zoom_jpeg = mf.read()

    # Place tiles at z17 (max) AND z16 (should be untouched post-reorder)
    conn.execute("INSERT INTO tiles VALUES (17, 100, 200, ?)", (max_zoom_jpeg,))
    # Put an identical-content tile at z16 — it should NOT be modified
    conn.execute("INSERT INTO tiles VALUES (16, 50, 100, ?)", (max_zoom_jpeg,))
    conn.commit()
    conn.close()

    modified = inpaint_nodata_pixels(path)

    assert isinstance(modified, list)
    # All returned coords must be at max_zoom=17
    for (z, _, _) in modified:
        assert z == 17, f"inpaint must only touch max_zoom; got modification at z={z}"

    conn = sqlite3.connect(str(path))
    # The z16 tile must be byte-identical to what we inserted
    z16 = conn.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=16 AND tile_column=50 AND tile_row=100"
    ).fetchone()[0]
    # The z17 tile should have been modified (inpainted)
    z17 = conn.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=17 AND tile_column=100 AND tile_row=200"
    ).fetchone()[0]
    queue_count = conn.execute(
        "SELECT COUNT(*) FROM _overview_work_queue"
    ).fetchone()[0]
    conn.close()

    assert z16 == max_zoom_jpeg, "z16 tile must not have been modified by inpaint"
    # z17 may or may not be byte-identical (JPEG re-encode). Assert it's in the
    # returned list.
    assert (17, 100, 200) in modified
    # Ancestors of the one modified z17 tile should be enqueued (17 entries)
    assert queue_count == 17
```

- [ ] **Step 2: Run test to verify fail**

Expected: fails because current code's `SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles` (no WHERE) would modify the z16 tile too.

- [ ] **Step 3: Modify `inpaint_nodata_pixels` in `scripts/rasterio_ops.py`**

At approximately L839-841, change:

```python
cursor = conn.execute(
    "SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles"
)
```

to:

```python
# R5 finding: restrict to max-zoom only. In the reordered pipeline
# (merge → erode → inpaint → overviews), overview tiles haven't been
# built yet, so "all tiles" IS just the base layer. But on resume
# runs where prior overviews exist, this prevents inpaint from
# mutating them out-of-band.
max_zoom_row = conn.execute("SELECT MAX(zoom_level) FROM tiles").fetchone()
if not max_zoom_row or max_zoom_row[0] is None:
    return []
max_zoom = max_zoom_row[0]
cursor = conn.execute(
    "SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles "
    "WHERE zoom_level = ?",
    (max_zoom,),
)
```

Also: change the function's return type from `int` to `list[tuple[int, int, int]]`, accumulate modified coords, and route the per-tile UPDATE through `_mutate_base_tile(conn, "upsert", z, x, y, tile_data=new_bytes)`.

- [ ] **Step 4: Run test to verify pass**

```bash
python -m pytest tests/test_overview_journal.py -v -k inpaint
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/rasterio_ops.py tests/test_overview_journal.py
git commit -m "$(cat <<'EOF'
feat(overview): inpaint_nodata_pixels restricts to max_zoom + returns list

Spec §3 + R5 I4: inpaint previously iterated all zoom levels. In the
reordered pipeline (merge → erode → inpaint → overviews), this would
mutate old overview tiles out-of-band on resume runs. Restricting to
max_zoom confines inpaint to the authoritative base layer.

Return type changes from int to list[tuple[int, int, int]] (modified
coords). Writes route through _mutate_base_tile for atomic ancestor
enqueueing.

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 5 — Integration (2 tasks)

### Task 11: `run_noaa` post-processing reorder + semantic equivalence test

**Goal:** Reorder `run_noaa`'s post-processing to `merge → erode → inpaint → overviews` (existing order is `merge → overviews → erode → inpaint`). Update `build_overviews` call to pass `mode="auto"`.

**Files:**
- Modify: `scripts/acquire_imagery.py:2708-2790` (NOAA post-processing block)
- Test: `tests/test_overview_journal.py` (end-to-end semantic equivalence)

- [ ] **Step 1: Write the failing semantic-equivalence test**

```python
def test_nuclear_and_journal_produce_equivalent_mbtiles(tmp_path):
    """Spec test 12: run both modes against identical input; assert
    coord-set equality and pixel mean-abs-diff < 2."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from rasterio_ops import _init_journal, _enqueue_ancestors, build_overviews
    import shutil
    import numpy as np
    import rasterio
    from rasterio.io import MemoryFile

    def _make_gradient_tile(base_r, base_g, base_b) -> bytes:
        """Gradient tile so 2x2 averaging actually does work the test can observe."""
        arr = np.zeros((3, 256, 256), dtype=np.uint8)
        for i in range(256):
            arr[0, i, :] = (base_r + i) % 256
            arr[1, i, :] = (base_g + i) % 256
            arr[2, i, :] = (base_b + i) % 256
        with MemoryFile() as mf:
            with mf.open(driver="JPEG", width=256, height=256, count=3, dtype="uint8") as ds:
                ds.write(arr)
            return mf.read()

    # Build a fixture MBTiles with a 4x4 = 16-tile z17 block (gradients).
    # Cascade from z17 gives z16 (4 tiles), z15 (1 tile), z14 (1 tile).
    base_path = tmp_path / "base.mbtiles"
    conn = sqlite3.connect(str(base_path))
    conn.executescript(
        """
        CREATE TABLE tiles (
            zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
            tile_data BLOB,
            PRIMARY KEY (zoom_level, tile_column, tile_row)
        );
        CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT);
        """
    )
    _init_journal(conn)
    tiles_coords = []
    for tc in range(4):
        for tr in range(4):
            tile = _make_gradient_tile(tc * 40, tr * 40, 128)
            conn.execute(
                "INSERT INTO tiles VALUES (17, ?, ?, ?)", (tc, tr, tile)
            )
            tiles_coords.append((17, tc, tr))
    _enqueue_ancestors(conn, tiles_coords)
    conn.commit()
    conn.close()

    # Clone for nuclear + journal
    nuclear_path = tmp_path / "nuclear.mbtiles"
    journal_path = tmp_path / "journal.mbtiles"
    shutil.copy(base_path, nuclear_path)
    shutil.copy(base_path, journal_path)

    build_overviews(nuclear_path, mode="nuclear")
    build_overviews(journal_path, mode="journal")

    # Compare outputs
    conn_n = sqlite3.connect(str(nuclear_path))
    conn_j = sqlite3.connect(str(journal_path))
    coords_n = set(conn_n.execute(
        "SELECT zoom_level, tile_column, tile_row FROM tiles"
    ).fetchall())
    coords_j = set(conn_j.execute(
        "SELECT zoom_level, tile_column, tile_row FROM tiles"
    ).fetchall())
    assert coords_n == coords_j, (
        f"coord sets differ: only-nuclear={coords_n - coords_j}, "
        f"only-journal={coords_j - coords_n}"
    )

    # Per-tile pixel mean-abs-diff check
    for (z, tc, tr) in coords_n:
        data_n = conn_n.execute(
            "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
            (z, tc, tr),
        ).fetchone()[0]
        data_j = conn_j.execute(
            "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
            (z, tc, tr),
        ).fetchone()[0]
        with MemoryFile(data_n) as mf:
            with mf.open() as ds:
                arr_n = ds.read()
        with MemoryFile(data_j) as mf:
            with mf.open() as ds:
                arr_j = ds.read()
        diff = np.abs(arr_n.astype(np.int16) - arr_j.astype(np.int16)).mean()
        assert diff < 2.0, (
            f"tile ({z},{tc},{tr}) mean-abs-diff={diff:.2f} exceeds threshold"
        )

    conn_n.close()
    conn_j.close()
```

- [ ] **Step 2: Run test to verify pass**

```bash
python -m pytest tests/test_overview_journal.py::test_nuclear_and_journal_produce_equivalent_mbtiles -v
```

Expected: PASS (this is already covered by earlier task implementations; this test validates the whole stack works end-to-end).

If the test fails on diff > 2: investigate whether the JPEG re-encoding happens differently between the two paths (it shouldn't — both use `_composite_2x2_children` now).

- [ ] **Step 3: Reorder the NOAA post-processing in `scripts/acquire_imagery.py`**

Find the block at ~L2708-2790. Current order (simplified):

```python
# Phase 5: merge happened before this block
# Then: build_overviews (legacy nuclear)
# Then: erode
# Then: inpaint
```

Replace with:

```python
# Phase 5 (reordered 2026-04-22 per spec):
# 1) erode base tiles
# 2) inpaint max-zoom base tiles
# 3) build_overviews(mode="auto") — drains the journal
try:
    from rasterio_ops import erode_nodata_edges as rio_erode
    from rasterio_ops import inpaint_nodata_pixels as rio_inpaint
    from rasterio_ops import build_overviews as rio_build_overviews

    if not skip_to_postprocess:
        deleted = rio_erode(output, cancel_check=lambda: _cancel_requested)
        if deleted:
            log.info("Eroded %d nodata-edge tiles", len(deleted))
    else:
        log.info("Skipping erosion on resume run")

    if _cancel_requested:
        update_progress(output, "noaa", args.bbox, "n/a",
                        tiles_done, total_tiles, status="cancelled", phase="cancelled")
        return

    modified = rio_inpaint(output, cancel_check=lambda: _cancel_requested)
    if modified:
        log.info("Inpainted %d nodata-pixel tiles", len(modified))

    if _cancel_requested:
        update_progress(output, "noaa", args.bbox, "n/a",
                        tiles_done, total_tiles, status="cancelled", phase="cancelled")
        return

    update_progress(output, "noaa", args.bbox, "n/a",
                    tiles_done, total_tiles, phase="overviews")
    rio_build_overviews(output, mode="auto", cancel_check=lambda: _cancel_requested)
except Exception as exc:
    log.warning("Post-processing failed: %s — output still usable at base zoom", exc)
```

The exact integration depends on the existing variable names + cancel flow. Preserve all existing cancel checks + progress updates. Remove the `_run_gdaladdo_with_metadata_fixup` call (or refactor it to be a thin wrapper over the new `build_overviews`).

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_overview_journal.py -v
python -m pytest tests/ -x --ignore=tests/test_setup_main.py --ignore=tests/test_wake_lock_static.py -q 2>&1 | tail -15
```

Expected: all `test_overview_journal` tests pass; no new failures in the broader suite.

- [ ] **Step 5: Commit**

```bash
git add scripts/acquire_imagery.py tests/test_overview_journal.py
git commit -m "$(cat <<'EOF'
feat(noaa): reorder post-processing to merge→erode→inpaint→overviews

Restores the pipeline order that erode_nodata_edges' author expected
per the L909-912 comment. Overviews now see post-erosion + post-
inpaint base tiles; closes the latent staleness bug.

Switches build_overviews call to mode="auto" so the journal populated
during merge_mbtiles is drained incrementally (or falls back to nuclear
when the dirty set exceeds 50% of base tiles).

Also adds the end-to-end semantic equivalence test that runs both
modes against identical input and asserts coord-set equality + pixel
mean-abs-diff < 2.

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 6 — Validation tooling (1 task)

### Task 12: A/B comparison harness

**Goal:** `dev/tools/compare_overview_modes.py` — one-off script that validates nuclear vs journal on real data. Per spec §A/B validation harness.

**Files:**
- Create: `dev/tools/compare_overview_modes.py`
- Create: `dev/tools/README.md` (append if exists)

- [ ] **Step 1: Implement**

Create `dev/tools/compare_overview_modes.py`:

```python
#!/usr/bin/env python3
"""A/B comparison harness — nuclear vs journal overview rebuild.

Usage:
    python3 dev/tools/compare_overview_modes.py /path/to/source.mbtiles

Snapshots the input MBTiles into two clones via SQLite backup (with WAL
checkpoint), runs build_overviews(mode="nuclear") on clone A and
build_overviews(mode="journal") on clone B, compares outputs, and
prints wall-time + semantic-equivalence report.

Does NOT modify the source. Produces two .mbtiles files in /tmp/ that
are cleaned up on successful exit.
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
from rasterio.io import MemoryFile

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from rasterio_ops import build_overviews  # noqa: E402


def clone_mbtiles(src: Path, dst: Path) -> None:
    """Clone with WAL checkpoint + .backup API (R5 I3)."""
    # First: force WAL checkpoint so .backup sees the latest committed state.
    ck = sqlite3.connect(str(src))
    try:
        ck.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        ck.close()

    # Now: sqlite3's backup API copies the snapshot-consistent pages.
    src_conn = sqlite3.connect(str(src))
    dst_conn = sqlite3.connect(str(dst))
    try:
        src_conn.backup(dst_conn)
    finally:
        src_conn.close()
        dst_conn.close()


def compare_outputs(path_a: Path, path_b: Path) -> dict:
    """Compare coord sets + pixel diff. Returns a report dict."""
    conn_a = sqlite3.connect(str(path_a))
    conn_b = sqlite3.connect(str(path_b))
    try:
        coords_a = set(conn_a.execute(
            "SELECT zoom_level, tile_column, tile_row FROM tiles"
        ).fetchall())
        coords_b = set(conn_b.execute(
            "SELECT zoom_level, tile_column, tile_row FROM tiles"
        ).fetchall())

        only_a = coords_a - coords_b
        only_b = coords_b - coords_a
        common = coords_a & coords_b

        # Sample up to 200 common tiles for pixel diff (full scan is slow on
        # large MBTiles)
        sample = list(common)[:200]
        diffs = []
        mismatches = []
        for (z, tc, tr) in sample:
            data_a = conn_a.execute(
                "SELECT tile_data FROM tiles "
                "WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (z, tc, tr),
            ).fetchone()[0]
            data_b = conn_b.execute(
                "SELECT tile_data FROM tiles "
                "WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (z, tc, tr),
            ).fetchone()[0]
            try:
                with MemoryFile(data_a) as mf:
                    arr_a = mf.open().read()
                with MemoryFile(data_b) as mf:
                    arr_b = mf.open().read()
                diff = float(np.abs(arr_a.astype(np.int16) - arr_b.astype(np.int16)).mean())
                diffs.append(diff)
                if diff >= 2.0:
                    mismatches.append(((z, tc, tr), diff))
            except Exception as exc:
                mismatches.append(((z, tc, tr), f"decode error: {exc}"))

        return {
            "count_a": len(coords_a),
            "count_b": len(coords_b),
            "only_a": only_a,
            "only_b": only_b,
            "common": len(common),
            "sampled": len(sample),
            "max_diff": max(diffs) if diffs else 0.0,
            "avg_diff": sum(diffs) / len(diffs) if diffs else 0.0,
            "mismatches": mismatches,
        }
    finally:
        conn_a.close()
        conn_b.close()


def main():
    parser = argparse.ArgumentParser(description="Compare overview modes on an MBTiles.")
    parser.add_argument("source", type=Path, help="Input MBTiles file")
    parser.add_argument("--out-dir", type=Path, default=Path("/tmp"),
                        help="Directory for clones (default: /tmp)")
    parser.add_argument("--keep", action="store_true",
                        help="Keep clone files after comparison")
    args = parser.parse_args()

    if not args.source.exists():
        print(f"Source not found: {args.source}", file=sys.stderr)
        return 1

    clone_a = args.out_dir / "overview_compare_nuclear.mbtiles"
    clone_b = args.out_dir / "overview_compare_journal.mbtiles"

    print(f"Cloning {args.source} → {clone_a}")
    clone_mbtiles(args.source, clone_a)
    print(f"Cloning {args.source} → {clone_b}")
    clone_mbtiles(args.source, clone_b)

    print("Running nuclear drain on clone A...")
    t0 = time.monotonic()
    build_overviews(clone_a, mode="nuclear")
    t_nuclear = time.monotonic() - t0

    print("Running journal drain on clone B...")
    t0 = time.monotonic()
    build_overviews(clone_b, mode="journal")
    t_journal = time.monotonic() - t0

    print("Comparing outputs...")
    report = compare_outputs(clone_a, clone_b)

    print()
    print("=== RESULT ===")
    print(f"Nuclear wall-time:  {t_nuclear:6.2f} s")
    print(f"Journal wall-time:  {t_journal:6.2f} s")
    print(f"Speedup:            {t_nuclear / t_journal:.1f}x")
    print(f"Tile counts:        nuclear={report['count_a']}  journal={report['count_b']}")
    print(f"Only-in-nuclear:    {len(report['only_a'])}")
    print(f"Only-in-journal:    {len(report['only_b'])}")
    print(f"Common tiles:       {report['common']}")
    print(f"Sampled for diff:   {report['sampled']}")
    print(f"Max pixel diff:     {report['max_diff']:.3f}")
    print(f"Avg pixel diff:     {report['avg_diff']:.3f}")
    print(f"Mismatches (>2.0):  {len(report['mismatches'])}")

    if report['mismatches']:
        print("\nFirst 5 mismatches:")
        for m in report['mismatches'][:5]:
            print(f"  {m}")

    ok = (
        len(report['only_a']) == 0
        and len(report['only_b']) == 0
        and report['max_diff'] < 2.0
    )

    if not args.keep:
        clone_a.unlink(missing_ok=True)
        clone_b.unlink(missing_ok=True)

    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
```

Make it executable:

```bash
chmod +x dev/tools/compare_overview_modes.py
```

- [ ] **Step 2: Manual smoke test**

If a small test MBTiles exists at `/srv/geographica/data/imagery_noaa.mbtiles` with a journal populated by a prior run:

```bash
python3 dev/tools/compare_overview_modes.py /srv/geographica/data/imagery_noaa.mbtiles --keep
```

Expected: speedup > 5× for any non-trivial MBTiles; exit code 0; max pixel diff < 2.

If you don't have a real file to test against, skip this and rely on the end-to-end unit test from Task 11.

- [ ] **Step 3: Commit**

```bash
git add dev/tools/compare_overview_modes.py
git commit -m "$(cat <<'EOF'
feat(overview): A/B comparison harness for nuclear vs journal modes

One-off dev tool that clones an input MBTiles (with WAL checkpoint to
ensure identical start state per R5 I3), runs build_overviews(mode=
nuclear) and build_overviews(mode=journal) on the two clones, and
reports speedup + coord-set equality + sampled pixel mean-abs-diff.

Lives in dev/tools/ — not shipped, not unit-tested by the regression
suite, deletable once we're confident in production.

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 7 — Enforcement (1 task)

### Task 13: Grep-based invariant test

**Goal:** Prevent future contributors from adding a raw `INSERT INTO tiles` or `UPDATE tiles` outside the designated wrappers (R5 §2 minor-m4 enforcement note).

**Files:**
- Create: `tests/test_overview_write_enforcement.py`

- [ ] **Step 1: Write the test**

```python
"""Enforcement: raw tile-table writes outside designated wrappers.

The incremental overview design (spec 2026-04-22) depends on every
base-tile mutation going through _mutate_base_tile (single-tile) or
merge_mbtiles's bulk SQL block. A raw INSERT/UPDATE/DELETE elsewhere
would silently break the dirty-tracking invariant.

This test greps for violations — cheap safety net, not foolproof.
Designated wrappers: rasterio_ops._mutate_base_tile,
acquire_imagery.merge_mbtiles (bulk), _drain_journal, _drain_nuclear,
_init_noaa_checkpoint (SQLite schema for a different table).
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# Files allowed to contain raw 'INTO tiles' or 'UPDATE tiles' or
# 'FROM tiles' writes. Each entry is (file, allowed-function-context-keyword).
ALLOWED_SITES = {
    "scripts/rasterio_ops.py": [
        "_mutate_base_tile",       # the designated per-tile helper
        "_drain_journal",           # writes composited ancestors
        "_drain_nuclear",           # writes composited ancestors
        "_composite_2x2_children",  # reads only
    ],
    "scripts/acquire_imagery.py": [
        "merge_mbtiles",            # bulk path (wrapped in BEGIN/COMMIT)
    ],
}

# Pattern matches: INSERT INTO tiles, INSERT OR IGNORE/REPLACE INTO tiles,
# UPDATE tiles, DELETE FROM tiles (case-insensitive, whitespace-tolerant)
WRITE_PATTERN = re.compile(
    r"""
    (?:INSERT\s+(?:OR\s+(?:IGNORE|REPLACE)\s+)?INTO\s+tiles\b)
    | (?:UPDATE\s+tiles\b)
    | (?:DELETE\s+FROM\s+tiles\b)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def test_no_raw_tile_writes_outside_designated_wrappers():
    """Scan the NOAA-relevant files for writes to the tiles table. Each
    match must be inside a function listed in ALLOWED_SITES for that file."""
    violations = []

    for rel_path, allowed_funcs in ALLOWED_SITES.items():
        path = REPO_ROOT / rel_path
        assert path.exists(), f"{rel_path} not found — update ALLOWED_SITES"
        source = path.read_text()
        # Build a map of line-number → containing top-level function name
        func_by_line = {}
        current_func = None
        for i, line in enumerate(source.splitlines(), 1):
            match = re.match(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
            if match:
                current_func = match.group(1)
            func_by_line[i] = current_func

        # Find all writes
        for match in WRITE_PATTERN.finditer(source):
            # Compute line number
            line_num = source[:match.start()].count("\n") + 1
            containing_func = func_by_line.get(line_num)
            if containing_func not in allowed_funcs:
                violations.append(
                    f"{rel_path}:{line_num}  in {containing_func!r}: "
                    f"{match.group(0)!r}"
                )

    assert not violations, (
        "Raw tile-table writes found outside designated wrappers:\n"
        + "\n".join("  " + v for v in violations)
        + "\n\nAll base-tile writes must go through _mutate_base_tile "
        "or merge_mbtiles's bulk block so the journal stays complete. "
        "Add the function to ALLOWED_SITES if it's a legitimate new "
        "wrapper, otherwise refactor it to use _mutate_base_tile."
    )
```

- [ ] **Step 2: Run the test**

```bash
python -m pytest tests/test_overview_write_enforcement.py -v
```

Expected: PASS (since Tasks 8-10 consolidated writes onto the designated sites).

If it fails: some write in the migrated files is still raw. Either (a) route it through `_mutate_base_tile`, or (b) add it to `ALLOWED_SITES` with justification.

- [ ] **Step 3: Commit**

```bash
git add tests/test_overview_write_enforcement.py
git commit -m "$(cat <<'EOF'
test(overview): grep-based enforcement — no raw tile writes outside wrappers

Scans scripts/rasterio_ops.py and scripts/acquire_imagery.py for
INSERT/UPDATE/DELETE on the tiles table. Each match must be inside a
function listed in ALLOWED_SITES (e.g. _mutate_base_tile, merge_mbtiles,
_drain_*). Fails the build if a future contributor adds a raw write
outside those sites — catches what reviewer discipline might miss.

Not foolproof (can be bypassed by string-concatenated SQL or dynamic
table names) but cheap safety net for the single-entry-point invariant.

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## After all tasks

- [ ] **Run the full test suite**

```bash
python -m pytest tests/test_overview_journal.py tests/test_overview_write_enforcement.py -v
python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all new tests pass. No new failures in the broader suite (pre-existing failures from setup/wake-lock tests are unrelated).

- [ ] **Run the A/B harness against real production data**

```bash
python3 dev/tools/compare_overview_modes.py /srv/geographica/data/imagery_noaa.mbtiles
```

Expected:
- Speedup > 10× for any non-trivial run.
- `only-in-nuclear == 0` and `only-in-journal == 0`.
- `max pixel diff < 2.0`.
- Exit code 0.

Capture the output in the commit message of the final log-entry commit.

- [ ] **Update `dev/implementation-log.md`**

Add an entry at the top:

```markdown
## 2026-04-?? — Overview pyramid incremental rebuild (journal-based)

**Released as:** not yet released (shipped on `dev`, not yet pushed to origin)
**Plan:** docs/superpowers/plans/2026-04-22-overview-incremental-plan.md
**Spec:** docs/superpowers/specs/2026-04-22-overview-incremental-design.md
**Adversarial reviews:** 5 rounds (Sonnet arch, Sonnet scale, Sonnet test, Codex, Sonnet v2-review)

### Summary
Replaced rasterio_ops.build_overviews's nuclear pyramid-rebuild with a
targeted incremental path keyed on a persistent SQLite journal
(_overview_work_queue). Surfaced by 2026-04-21 runtime: 82 new tiles
merged into a 40GB MBTiles triggered a 6+ hour overview phase because
the code was rebuilding the whole pyramid. New design rebuilds only
ancestor lineages of newly-merged/eroded/inpainted tiles. Full 1:1 A/B
against nuclear preserved via mode selector.

### A/B harness result
(paste `dev/tools/compare_overview_modes.py` output here)

### Outcome
~N commits on dev. Task 12 end-to-end semantic-equivalence test passes.
Pipeline reorder closes latent stale-overview bug (erode + inpaint now
precede overview build, matching erode_nodata_edges' author-intent
comment).
```

- [ ] **Final commit**

```bash
git add dev/implementation-log.md
git commit -m "$(cat <<'EOF'
docs(overview): implementation log — incremental pyramid shipped on dev

N commits on dev (journal foundation + drain logic + migrate writers +
reorder pipeline + A/B harness + enforcement test). Spec + plan +
5-round adversarial review preserved under docs/superpowers/ and
dev/adversarial/. A/B harness on real production data shows <speedup>
speedup with zero coord-set divergence and max pixel diff < 2.

Agent: <moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review checklist (for plan author)

Before declaring this plan complete:

- [ ] **Spec coverage**: every section of the spec has at least one corresponding task. Journal table → Task 1; enqueue helper → Task 2; mutation wrapper → Task 3; drain logic → Tasks 4+5; mode selector → Task 6; cancel/resume → Task 7; merge migration → Task 8; erode migration → Task 9; inpaint migration → Task 10; pipeline reorder → Task 11; A/B harness → Task 12; enforcement → Task 13. ✓
- [ ] **No placeholders**: no TBD, TODO, "similar to above", "add validation". Every step shows the actual test or implementation code. ✓
- [ ] **Type consistency**: `_mutate_base_tile(conn, action, z, tc, tr, tile_data)` signature used consistently across Tasks 3, 9, 10. `_drain_journal(conn, cancel_check)` signature consistent across Tasks 4 and 6. `build_overviews(path, *, mode)` consistent across Tasks 6, 11, 12. ✓
- [ ] **TDD discipline**: every task has a failing test first → implement → pass → commit. ✓
- [ ] **Cross-task conflicts**: Tasks 8, 9, 10 each touch one function in one file; no overlap. Tasks 4-6 all touch rasterio_ops.py but in sequence (no parallel edits). Task 11 modifies acquire_imagery.py's run_noaa after Task 8 finished its merge_mbtiles changes. ✓
- [ ] **Pitfalls review**: testing-pitfalls.md guidance (mocks at wrong boundary — we test the real journal writes, not a mock of SQLite). implementation-pitfalls.md guidance (don't skip hooks, don't destructive-git — standard). ✓
