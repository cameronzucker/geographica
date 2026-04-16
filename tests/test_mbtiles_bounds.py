"""Tests for MBTiles bounds recalculation."""

import math
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def _tms_tile_for_point(lon, lat, zoom):
    """Convert a lon/lat to TMS tile coordinates."""
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y_slippy = int((1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n)
    y_tms = n - 1 - y_slippy
    return x, y_tms


def _create_mbtiles_with_tiles(path, tile_coords_z17, initial_bounds="0,0,0,0"):
    """Create MBTiles with tiles at given (x, y_tms) coords at zoom 17."""
    conn = sqlite3.connect(str(path))
    conn.execute("""CREATE TABLE tiles (
        zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
        tile_data BLOB, PRIMARY KEY (zoom_level, tile_column, tile_row))""")
    conn.execute("CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO metadata VALUES ('bounds', ?)", (initial_bounds,))
    conn.execute("INSERT INTO metadata VALUES ('format', 'jpeg')")
    for x, y in tile_coords_z17:
        conn.execute("INSERT INTO tiles VALUES (17, ?, ?, ?)", (x, y, b"fake"))
    conn.commit()
    conn.close()


def test_bounds_updated_to_match_tile_extent(tmp_path):
    """After recalculation, bounds should cover all tiles."""
    from acquire_imagery import _update_mbtiles_bounds

    mbtiles = tmp_path / "test.mbtiles"

    # Tiles spanning Sedona area: ~(-111.9, 34.8) to (-111.6, 34.9)
    sw_tile = _tms_tile_for_point(-111.9, 34.8, 17)
    ne_tile = _tms_tile_for_point(-111.6, 34.9, 17)
    tiles = [sw_tile, ne_tile]

    _create_mbtiles_with_tiles(mbtiles, tiles, initial_bounds="0,0,0,0")
    _update_mbtiles_bounds(mbtiles)

    conn = sqlite3.connect(str(mbtiles))
    bounds_str = conn.execute("SELECT value FROM metadata WHERE name='bounds'").fetchone()[0]
    conn.close()

    west, south, east, north = [float(x) for x in bounds_str.split(",")]
    assert west < -111.9, f"West bound {west} should be < -111.9"
    assert east > -111.6, f"East bound {east} should be > -111.6"
    assert south < 34.8, f"South bound {south} should be < 34.8"
    assert north > 34.9, f"North bound {north} should be > 34.9"


def test_bounds_not_updated_for_empty_mbtiles(tmp_path):
    """Empty MBTiles should keep original bounds (no crash)."""
    from acquire_imagery import _update_mbtiles_bounds

    mbtiles = tmp_path / "empty.mbtiles"
    conn = sqlite3.connect(str(mbtiles))
    conn.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
    conn.execute("CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO metadata VALUES ('bounds', 'original')")
    conn.commit()
    conn.close()

    _update_mbtiles_bounds(mbtiles)

    conn = sqlite3.connect(str(mbtiles))
    bounds = conn.execute("SELECT value FROM metadata WHERE name='bounds'").fetchone()[0]
    conn.close()
    assert bounds == "original"
