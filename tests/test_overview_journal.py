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
