"""Tests for MBTiles metadata schema fixes (B3, B5).

Verifies:
- UNIQUE constraint on metadata.name prevents duplicates
- minzoom, maxzoom, bounds are written when provided
- Existing duplicate rows are cleaned up on init
"""
import asyncio
import sqlite3
import tempfile
from pathlib import Path

import pytest
import aiosqlite

# Import the functions under test by adding scripts to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from acquire_imagery import init_mbtiles as imagery_init_mbtiles
from download_elevation import init_mbtiles as elevation_init_mbtiles


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "test.mbtiles"


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestImageryInitMbtiles:
    def test_no_duplicate_metadata_after_multiple_runs(self, tmp_db):
        """B3: Running init_mbtiles multiple times should not create duplicates."""
        run_async(imagery_init_mbtiles(tmp_db, bbox="-112,33,-111,34", zoom="0-14"))
        run_async(imagery_init_mbtiles(tmp_db, bbox="-112,33,-111,34", zoom="0-14"))
        run_async(imagery_init_mbtiles(tmp_db, bbox="-112,33,-111,34", zoom="0-14"))

        conn = sqlite3.connect(str(tmp_db))
        rows = conn.execute("SELECT name, value FROM metadata").fetchall()
        names = [r[0] for r in rows]
        # Each name should appear exactly once
        assert len(names) == len(set(names)), f"Duplicate metadata names: {names}"
        conn.close()

    def test_writes_minzoom_maxzoom_bounds(self, tmp_db):
        """B5: init_mbtiles should write minzoom, maxzoom, and bounds."""
        run_async(imagery_init_mbtiles(tmp_db, bbox="-124.8,31.3,-102.0,49.0", zoom="0-16"))

        conn = sqlite3.connect(str(tmp_db))
        meta = dict(conn.execute("SELECT name, value FROM metadata").fetchall())
        assert meta["minzoom"] == "0"
        assert meta["maxzoom"] == "16"
        assert meta["bounds"] == "-124.8,31.3,-102.0,49.0"
        assert meta["format"] == "jpeg"
        assert meta["type"] == "baselayer"
        conn.close()

    def test_cleans_up_preexisting_duplicates(self, tmp_db):
        """B3: init_mbtiles should clean up duplicates from prior schema."""
        # Simulate the old schema (no UNIQUE constraint)
        conn = sqlite3.connect(str(tmp_db))
        conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
        for _ in range(5):
            conn.execute("INSERT INTO metadata VALUES ('name', 'usgs_imagery')")
            conn.execute("INSERT INTO metadata VALUES ('format', 'jpeg')")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM metadata").fetchone()[0] == 10
        conn.close()

        # Now run init_mbtiles — it should deduplicate
        run_async(imagery_init_mbtiles(tmp_db, bbox="-112,33,-111,34", zoom="0-14"))

        conn = sqlite3.connect(str(tmp_db))
        names = [r[0] for r in conn.execute("SELECT name, value FROM metadata").fetchall()]
        assert len(names) == len(set(names)), f"Still has duplicates: {names}"
        conn.close()

    def test_without_bbox_zoom_no_optional_metadata(self, tmp_db):
        """When bbox/zoom not provided, only core metadata is written."""
        run_async(imagery_init_mbtiles(tmp_db))

        conn = sqlite3.connect(str(tmp_db))
        meta = dict(conn.execute("SELECT name, value FROM metadata").fetchall())
        assert "minzoom" not in meta
        assert "maxzoom" not in meta
        assert "bounds" not in meta
        assert meta["name"] == "usgs_imagery"
        conn.close()


class TestElevationInitMbtiles:
    def test_no_duplicate_metadata_after_multiple_runs(self, tmp_db):
        """B3: Same dedup test for elevation pipeline."""
        run_async(elevation_init_mbtiles(tmp_db, bbox="-112,33,-111,34", zoom="0-12"))
        run_async(elevation_init_mbtiles(tmp_db, bbox="-112,33,-111,34", zoom="0-12"))
        run_async(elevation_init_mbtiles(tmp_db, bbox="-112,33,-111,34", zoom="0-12"))

        conn = sqlite3.connect(str(tmp_db))
        rows = conn.execute("SELECT name, value FROM metadata").fetchall()
        names = [r[0] for r in rows]
        assert len(names) == len(set(names)), f"Duplicate metadata names: {names}"
        conn.close()

    def test_writes_minzoom_maxzoom_bounds(self, tmp_db):
        """B5: Elevation init_mbtiles should write zoom/bounds metadata."""
        run_async(elevation_init_mbtiles(tmp_db, bbox="-124.8,31.3,-102.0,49.0", zoom="0-12"))

        conn = sqlite3.connect(str(tmp_db))
        meta = dict(conn.execute("SELECT name, value FROM metadata").fetchall())
        assert meta["minzoom"] == "0"
        assert meta["maxzoom"] == "12"
        assert meta["bounds"] == "-124.8,31.3,-102.0,49.0"
        assert meta["format"] == "png"
        assert meta["type"] == "overlay"
        conn.close()
