"""Tests for batch-level MBTiles merge in acquire_imagery.py.

Verifies that merge_mbtiles correctly appends tiles from multiple
batch MBTiles files into a single output, preserving tiles from all
batches (B2 fix).
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from acquire_imagery import merge_mbtiles


def _create_test_mbtiles(path: Path, tiles: list[tuple[int, int, int, bytes]],
                          metadata: dict | None = None) -> None:
    """Create a minimal MBTiles file with the given tiles."""
    conn = sqlite3.connect(str(path))
    conn.execute("""CREATE TABLE tiles (
        zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
        tile_data BLOB,
        PRIMARY KEY (zoom_level, tile_column, tile_row))""")
    conn.execute("""CREATE TABLE metadata (name TEXT, value TEXT)""")
    for z, x, y, data in tiles:
        conn.execute("INSERT INTO tiles VALUES (?, ?, ?, ?)", (z, x, y, data))
    if metadata:
        for k, v in metadata.items():
            conn.execute("INSERT INTO metadata VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()


def _read_tiles(path: Path) -> list[tuple[int, int, int, bytes]]:
    """Read all tiles from an MBTiles file."""
    conn = sqlite3.connect(str(path))
    rows = conn.execute(
        "SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles"
    ).fetchall()
    conn.close()
    return rows


def _read_metadata(path: Path) -> dict:
    """Read metadata from an MBTiles file."""
    conn = sqlite3.connect(str(path))
    rows = conn.execute("SELECT name, value FROM metadata").fetchall()
    conn.close()
    return dict(rows)


class TestMergeMbtiles:
    """Test merge_mbtiles function."""

    def test_first_batch_creates_tables_and_tiles(self, tmp_path):
        """First merge into a non-existent output creates tables."""
        src = tmp_path / "batch1.mbtiles"
        dst = tmp_path / "output.mbtiles"

        _create_test_mbtiles(src, [
            (0, 0, 0, b"tile_0_0_0"),
            (1, 0, 0, b"tile_1_0_0"),
        ], metadata={"name": "test", "format": "jpeg"})

        merge_mbtiles(src, dst)

        tiles = _read_tiles(dst)
        assert len(tiles) == 2
        meta = _read_metadata(dst)
        assert meta["name"] == "test"
        assert meta["format"] == "jpeg"

    def test_second_batch_appends_tiles(self, tmp_path):
        """Second merge appends new tiles without overwriting batch 1."""
        dst = tmp_path / "output.mbtiles"

        # Batch 1
        src1 = tmp_path / "batch1.mbtiles"
        _create_test_mbtiles(src1, [
            (0, 0, 0, b"batch1_tile"),
            (1, 0, 0, b"batch1_z1"),
        ], metadata={"name": "test"})
        merge_mbtiles(src1, dst)

        # Batch 2 -- different tile locations
        src2 = tmp_path / "batch2.mbtiles"
        _create_test_mbtiles(src2, [
            (1, 1, 0, b"batch2_z1_1"),
            (2, 0, 0, b"batch2_z2"),
        ])
        merge_mbtiles(src2, dst)

        tiles = _read_tiles(dst)
        assert len(tiles) == 4, f"Expected 4 tiles from 2 batches, got {len(tiles)}"

        # All tile data should be present
        tile_data = {t[3] for t in tiles}
        assert b"batch1_tile" in tile_data
        assert b"batch1_z1" in tile_data
        assert b"batch2_z1_1" in tile_data
        assert b"batch2_z2" in tile_data

    def test_overlapping_tiles_first_batch_kept_when_composite_fails(self, tmp_path):
        """When batches overlap and tiles can't be composited (not valid JPEG),
        the first batch's tile is preserved via INSERT OR IGNORE."""
        dst = tmp_path / "output.mbtiles"

        src1 = tmp_path / "batch1.mbtiles"
        _create_test_mbtiles(src1, [
            (0, 0, 0, b"old_data"),
        ])
        merge_mbtiles(src1, dst)

        src2 = tmp_path / "batch2.mbtiles"
        _create_test_mbtiles(src2, [
            (0, 0, 0, b"new_data"),
        ])
        merge_mbtiles(src2, dst)

        tiles = _read_tiles(dst)
        assert len(tiles) == 1
        # First batch preserved — compositing falls back to keeping existing
        assert tiles[0][3] == b"old_data"

    def test_metadata_from_first_batch_preserved(self, tmp_path):
        """Metadata from first batch is kept; later batches don't overwrite."""
        dst = tmp_path / "output.mbtiles"

        src1 = tmp_path / "batch1.mbtiles"
        _create_test_mbtiles(src1, [(0, 0, 0, b"t1")],
                              metadata={"name": "first", "format": "jpeg"})
        merge_mbtiles(src1, dst)

        src2 = tmp_path / "batch2.mbtiles"
        _create_test_mbtiles(src2, [(1, 0, 0, b"t2")],
                              metadata={"name": "second", "format": "png"})
        merge_mbtiles(src2, dst)

        meta = _read_metadata(dst)
        assert meta["name"] == "first", "First batch metadata should be preserved"
        assert meta["format"] == "jpeg"

    def test_many_batches_accumulate(self, tmp_path):
        """Simulate 5 batches each with 3 tiles -- all 15 tiles survive."""
        dst = tmp_path / "output.mbtiles"

        for batch_num in range(5):
            src = tmp_path / f"batch_{batch_num}.mbtiles"
            tiles = [
                (batch_num, i, 0, f"b{batch_num}_t{i}".encode())
                for i in range(3)
            ]
            _create_test_mbtiles(src, tiles,
                                  metadata={"name": f"batch_{batch_num}"})
            merge_mbtiles(src, dst)

        all_tiles = _read_tiles(dst)
        assert len(all_tiles) == 15, f"Expected 15 tiles, got {len(all_tiles)}"

    def test_empty_src_produces_no_error(self, tmp_path):
        """Merging an MBTiles with zero tiles succeeds."""
        dst = tmp_path / "output.mbtiles"

        src = tmp_path / "empty.mbtiles"
        _create_test_mbtiles(src, [])
        merge_mbtiles(src, dst)

        tiles = _read_tiles(dst)
        assert len(tiles) == 0
