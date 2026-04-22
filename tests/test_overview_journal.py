"""Tests for the incremental overview journal (spec: 2026-04-22)."""
import sqlite3
import sys
from pathlib import Path

import pytest

# Make scripts/ importable as a bare module (same pattern as test_noaa_phase5)
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from rasterio_ops import _init_journal, _enqueue_ancestors  # noqa: E402


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
    assert rows == expected, f"ancestor chain mismatch:\n  got: {rows}\n  want: {expected}"


def test_enqueue_ancestors_deduplicates_with_primary_key(mbtiles_path):
    """INSERT OR IGNORE collapses the same ancestor from multiple children."""
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
    conn = sqlite3.connect(str(mbtiles_path))
    _init_journal(conn)
    _enqueue_ancestors(conn, [])
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM _overview_work_queue").fetchone()[0]
    conn.close()

    assert count == 0
