"""Test B7 fix: merge_mbtiles counts and logs composite errors."""

import logging
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from acquire_imagery import merge_mbtiles


def _create_mbtiles(path: Path, tiles: list[tuple[int, int, int, bytes]]) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("""CREATE TABLE tiles (
        zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
        tile_data BLOB,
        PRIMARY KEY (zoom_level, tile_column, tile_row))""")
    conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    for z, x, y, d in tiles:
        conn.execute("INSERT INTO tiles VALUES (?, ?, ?, ?)", (z, x, y, d))
    conn.commit()
    conn.close()


class TestMergeMbtilesErrorCounting:
    """Verify composite loop counts decode errors and emits a warning."""

    def test_corrupt_overlap_logs_warning(self, tmp_path, caplog):
        """Corrupt JPEG in overlap path triggers at least one WARNING log, not silent pass."""
        src = tmp_path / "src.mbtiles"
        dst = tmp_path / "dst.mbtiles"

        # Same (z,x,y) in both, different bytes → overlap path fires.
        _create_mbtiles(src, [(10, 1, 1, b"CORRUPT_NOT_A_JPEG_SRC_______")])
        _create_mbtiles(dst, [(10, 1, 1, b"CORRUPT_NOT_A_JPEG_DST_______")])

        with caplog.at_level(logging.WARNING, logger="acquire_imagery"):
            merge_mbtiles(src, dst)

        # The decode will fail in the composite path. Before B7 fix: silent pass.
        # After B7 fix: at least one WARNING mentioning merge / composite failure.
        warning_messages = [r.getMessage() for r in caplog.records
                            if r.levelno >= logging.WARNING]
        assert any("composite" in m.lower() or "merge" in m.lower()
                   for m in warning_messages), (
            f"Expected a WARNING about failed composite; got: {warning_messages}"
        )

    def test_many_errors_capped_to_summary(self, tmp_path, caplog):
        """When >5 overlap tiles fail, a summary warning names the total count."""
        src = tmp_path / "src.mbtiles"
        dst = tmp_path / "dst.mbtiles"

        # 7 overlapping tiles, all corrupt
        tiles_src = [(10, i, 0, f"CORRUPT_SRC_{i}_XXXXXXX".encode()) for i in range(7)]
        tiles_dst = [(10, i, 0, f"CORRUPT_DST_{i}_XXXXXXX".encode()) for i in range(7)]
        _create_mbtiles(src, tiles_src)
        _create_mbtiles(dst, tiles_dst)

        with caplog.at_level(logging.WARNING, logger="acquire_imagery"):
            merge_mbtiles(src, dst)

        summary = [r.getMessage() for r in caplog.records
                   if r.levelno >= logging.WARNING
                   and "suppressed" in r.getMessage().lower()]
        assert summary, (
            "Expected a summary log line with 'suppressed' naming the error total; "
            f"no matching record in: {[r.getMessage() for r in caplog.records]}"
        )
