"""Tests for the incremental overview journal (spec: 2026-04-22)."""
import sqlite3
import sys
from pathlib import Path

import pytest

# Make scripts/ importable as a bare module (same pattern as test_noaa_phase5)
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from rasterio_ops import _init_journal, _enqueue_ancestors, _mutate_base_tile, _drain_journal, _drain_nuclear, build_overviews  # noqa: E402


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
    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='_overview_work_queue'"
    ).fetchone()
    conn.close()

    assert row is not None, "_overview_work_queue table should be created"


def test_init_journal_is_idempotent(mbtiles_path):
    """Second call on same file must not raise or modify the schema."""
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


def test_enqueue_ancestors_populates_full_lineage(mbtiles_path):
    """A single base tile at zN should enqueue N ancestors (z=N-1 down to 0)."""
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

    # Spot-checks against hand-verified values (catches off-by-one in the
    # implementation's `range(1, z + 1)` bounds; the full-list comparison
    # below would also pass if the implementation and the expected
    # construction drifted off-by-one in the same direction).
    assert len(rows) == 17, f"expected 17 ancestor entries for z=17; got {len(rows)}"
    assert rows[0] == (16, 50, 100), (
        f"first ancestor (z=16) should be (16, 50, 100) — 100>>1=50, 200>>1=100; "
        f"got {rows[0]}"
    )
    assert rows[-1] == (0, 0, 0), (
        f"final ancestor (z=0) should be the root (0, 0, 0); got {rows[-1]}"
    )

    assert rows == expected, f"ancestor chain mismatch:\n  got: {rows}\n  want: {expected}"


def test_enqueue_ancestors_deduplicates_with_primary_key(mbtiles_path):
    """INSERT OR IGNORE collapses the same ancestor from multiple children."""
    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    # Two siblings sharing the same z16 ancestor (16, 50, 100)
    _enqueue_ancestors(conn, [(17, 100, 200), (17, 101, 200)])
    conn.commit()

    # Both siblings map to the same z16 parent: 100>>1 == 101>>1 == 50.
    # INSERT OR IGNORE collapses them so z16 has exactly 1 row, not 2.
    count_at_z16 = conn.execute(
        "SELECT COUNT(*) FROM _overview_work_queue WHERE zoom_level=16"
    ).fetchone()[0]
    conn.close()

    assert count_at_z16 == 1, (
        f"expected 1 unique z16 ancestor for siblings 100,101; got {count_at_z16}"
    )


def test_enqueue_ancestors_empty_list_is_noop(mbtiles_path):
    """Empty input list: no rows added, no error raised."""
    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    _enqueue_ancestors(conn, [])
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM _overview_work_queue").fetchone()[0]
    conn.close()

    assert count == 0


def test_enqueue_ancestors_z0_base_tile_produces_no_rows(mbtiles_path):
    """A base tile already at z=0 has no ancestors; must not raise or enqueue."""
    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    _enqueue_ancestors(conn, [(0, 0, 0)])
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM _overview_work_queue").fetchone()[0]
    conn.close()

    assert count == 0, (
        f"z=0 base tile should produce 0 ancestor rows (range(1, 0+1) is empty); "
        f"got {count}"
    )


def test_mutate_base_tile_upsert_writes_tile_and_enqueues(mbtiles_path):
    """upsert inserts the tile and enqueues its ancestors in one transaction."""
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
    assert queue_count == 17  # 17 ancestors: z16 down to z0


def test_mutate_base_tile_delete_removes_tile_and_enqueues(mbtiles_path):
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
    assert queue_count == 17  # 17 ancestors: z16 down to z0 (same cascade on delete)


def test_mutate_base_tile_atomic_on_rollback(mbtiles_path, monkeypatch):
    """If the commit never happens (rollback), NEITHER the tile nor the
    queue entries persist. Validates same-transaction semantics.

    Uses isolation_level=None so BEGIN/ROLLBACK are explicit and the
    default-isolation auto-BEGIN doesn't collide with our explicit one.
    """
    conn = sqlite3.connect(str(mbtiles_path), isolation_level=None)
    _init_journal(conn)  # DDL auto-commits in manual mode too

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

    # Expected by the unified re-eval rule ("delete if any child missing"):
    #   z16: 4 tiles — each has all 4 z17 children → WRITE.
    #   z15: 1 tile  — (0,0) has all 4 z16 children {(0,0),(0,1),(1,0),(1,1)} → WRITE.
    #   z14: 0 tiles — (0,0) has z15 children {(0,0),(0,1),(1,0),(1,1)}, only (0,0)
    #                  exists → DELETE no-op. The queue walks the lineage, but
    #                  incomplete-parent never materializes.
    #   z13..z0: 0   — cascades same way down to z0.
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
    assert z14_count == 0, (
        f"expected 0 z14 tiles (z15 has only 1 of 4 children; unified rule "
        f"treats incomplete parent as delete); got {z14_count}. If this fails "
        f"with z14_count > 0, _drain_journal is preserving partial-child "
        f"ancestors — breaking Round 4 C2 invariant."
    )
    assert z13_count == 0, f"z13 should not be built (z14 incomplete); got {z13_count}"


def test_drain_nuclear_rebuilds_full_pyramid_ignoring_queue(mbtiles_path):
    """Nuclear drain rebuilds all ancestor zooms from scratch, ignores queue."""
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


def test_build_overviews_mode_nuclear_ignores_queue(mbtiles_path):
    """mode='nuclear' calls _drain_nuclear regardless of queue state."""
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


def test_cancel_mid_drain_preserves_remaining_queue_and_committed_tiles(mbtiles_path):
    """Cancel fires after 1 zoom level. Processed entries are gone from
    queue AND the written ancestors are in the tiles table (proving the
    commit took effect). Remaining entries at lower zoom levels survive
    for resume."""
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


def test_merge_mbtiles_populates_journal(tmp_path):
    """merge_mbtiles's bulk INSERT OR IGNORE path must enqueue ancestors
    for every inserted z17 tile."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from acquire_imagery import merge_mbtiles

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
