"""Test B13 fix: checkpoint repair re-derives _noaa_checkpoint from tiles table at pipeline start."""

import inspect
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestCheckpointRepair:
    """Verify a repair function exists and syncs _noaa_checkpoint with the tiles table."""

    def test_repair_function_exists(self):
        import acquire_imagery
        assert hasattr(acquire_imagery, "_repair_noaa_checkpoint"), (
            "B13 fix: _repair_noaa_checkpoint function must exist at module level"
        )

    def test_repair_populates_checkpoint_from_tiles(self, tmp_path):
        """Given an MBTiles with tiles but no _noaa_checkpoint, repair populates the table."""
        from acquire_imagery import _repair_noaa_checkpoint

        mb = tmp_path / "test.mbtiles"
        conn = sqlite3.connect(str(mb))
        conn.execute("""CREATE TABLE tiles (
            zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
            tile_data BLOB, PRIMARY KEY(zoom_level,tile_column,tile_row))""")
        conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
        conn.execute("INSERT INTO tiles VALUES (10, 1, 1, ?)", (b"tile1",))
        conn.commit()
        conn.close()

        # tile_filenames maps tile filenames to (z, x, y) — we provide a mapping
        # so the repair knows which filenames correspond to which tiles.
        # For this test we pass a simple list of (fname, z, x, y).
        tile_coord_map = {"tile_10_1_1.tif": (10, 1, 1)}
        _repair_noaa_checkpoint(mb, tile_coord_map)

        # After repair, _noaa_checkpoint should contain tile_10_1_1.tif
        conn = sqlite3.connect(str(mb))
        rows = conn.execute(
            "SELECT tile_filename FROM _noaa_checkpoint"
        ).fetchall()
        conn.close()
        filenames = [r[0] for r in rows]
        assert "tile_10_1_1.tif" in filenames, (
            f"Expected tile_10_1_1.tif in _noaa_checkpoint after repair; got {filenames}"
        )

    def test_repair_no_tiles_table_is_noop(self, tmp_path):
        """If the MBTiles has no tiles table (never opened), repair is a no-op."""
        from acquire_imagery import _repair_noaa_checkpoint
        mb = tmp_path / "empty.mbtiles"
        mb.touch()
        # Should not raise
        _repair_noaa_checkpoint(mb, {})

    def test_repair_called_in_run_noaa(self):
        """run_noaa must call _repair_noaa_checkpoint before the download loop."""
        import acquire_imagery
        src = inspect.getsource(acquire_imagery.run_noaa)
        assert "_repair_noaa_checkpoint" in src, (
            "run_noaa must invoke _repair_noaa_checkpoint at pipeline start (B13 fix)"
        )
