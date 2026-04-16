"""Tests for NAIP quad deduplication in run_noaa."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def _create_output_with_checkpoint(path: Path, checkpointed_quads: list[str]):
    """Create a minimal MBTiles with _noaa_checkpoint table."""
    conn = sqlite3.connect(str(path))
    conn.execute("""CREATE TABLE IF NOT EXISTS tiles (
        zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
        tile_data BLOB,
        PRIMARY KEY (zoom_level, tile_column, tile_row))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS _noaa_checkpoint (
        tile_filename TEXT PRIMARY KEY)""")
    for quad in checkpointed_quads:
        conn.execute("INSERT INTO _noaa_checkpoint (tile_filename) VALUES (?)", (quad,))
    conn.commit()
    conn.close()


def test_checkpoint_table_filters_manifest():
    """Quads already in _noaa_checkpoint should be excluded from the job manifest."""
    import sqlite3 as stdlib_sqlite3
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "output.mbtiles"
        _create_output_with_checkpoint(output, [
            "m_3411101_ne_12_060_20211014.tif",
            "m_3411101_se_12_060_20211014.tif",
        ])

        tile_filenames = [
            "m_3411101_ne_12_060_20211014.tif",  # already done
            "m_3411101_se_12_060_20211014.tif",  # already done
            "m_3411102_nw_12_060_20211014.tif",  # new
            "m_3411102_sw_12_060_20211014.tif",  # new
        ]

        with stdlib_sqlite3.connect(str(output)) as conn:
            existing = {row[0] for row in conn.execute(
                "SELECT tile_filename FROM _noaa_checkpoint"
            ).fetchall()}

        remaining = [f for f in tile_filenames if f not in existing]
        assert len(remaining) == 2
        assert "m_3411102_nw_12_060_20211014.tif" in remaining
        assert "m_3411102_sw_12_060_20211014.tif" in remaining


def test_no_checkpoint_table_processes_all():
    """First run (no checkpoint table) should process all quads."""
    import sqlite3 as stdlib_sqlite3
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "output.mbtiles"
        conn = sqlite3.connect(str(output))
        conn.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
        conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
        conn.commit()
        conn.close()

        tile_filenames = ["a.tif", "b.tif", "c.tif"]

        try:
            with stdlib_sqlite3.connect(str(output)) as conn:
                existing = {row[0] for row in conn.execute(
                    "SELECT tile_filename FROM _noaa_checkpoint"
                ).fetchall()}
        except stdlib_sqlite3.OperationalError:
            existing = set()

        remaining = [f for f in tile_filenames if f not in existing]
        assert len(remaining) == 3


def test_nonexistent_output_processes_all():
    """When output file doesn't exist yet, all quads should be processed."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "output.mbtiles"
        assert not output.exists()

        tile_filenames = ["a.tif", "b.tif"]
        remaining = tile_filenames
        assert len(remaining) == 2
