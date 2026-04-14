"""Tests for National Map NAIP tile URL builder."""

import asyncio
import math
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from acquire_imagery import nationalmap_tile_url, run_direct


class TestNationalMapTileUrl:
    """Verify z/x/y -> ImageServer exportImage URL conversion."""

    def test_z0_whole_world(self):
        """z=0, x=0, y=0 should produce bbox covering the whole world."""
        url = nationalmap_tile_url(0, 0, 0)
        assert "bbox=-180.0" in url or "bbox=-180," in url
        assert "size=256,256" in url
        assert "format=jpgpng" in url
        assert "USGSNAIPPlus" in url

    def test_z15_phoenix(self):
        """z=15 tile over Phoenix — verify bbox is in the right ballpark."""
        # Tile 15/6183/13149 is near Phoenix, AZ (~-112.07, 33.45)
        url = nationalmap_tile_url(15, 6183, 13149)
        # Extract bbox from URL
        bbox_str = url.split("bbox=")[1].split("&")[0]
        west, south, east, north = [float(x) for x in bbox_str.split(",")]
        # Should be near Phoenix
        assert -113.0 < west < -111.0
        assert 33.0 < south < 34.0
        assert east > west
        assert north > south
        # Tile should be small (~0.01 degrees at z15)
        assert east - west < 0.02
        assert north - south < 0.02

    def test_z18_high_zoom(self):
        """z=18 tile — verify it produces a very small bbox."""
        url = nationalmap_tile_url(18, 50280, 100280)
        bbox_str = url.split("bbox=")[1].split("&")[0]
        west, south, east, north = [float(x) for x in bbox_str.split(",")]
        # At z18, each tile is ~0.001 degrees
        assert east - west < 0.002
        assert north - south < 0.002

    def test_url_format(self):
        """Verify URL has all required ImageServer parameters."""
        url = nationalmap_tile_url(15, 6285, 12535)
        assert url.startswith("https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer/exportImage")
        assert "bboxSR=4326" in url
        assert "imageSR=4326" in url
        assert "size=256,256" in url
        assert "format=jpgpng" in url
        assert "f=image" in url

    def test_tiles_dont_overlap(self):
        """Adjacent tiles should have contiguous non-overlapping bboxes."""
        url_a = nationalmap_tile_url(15, 100, 100)
        url_b = nationalmap_tile_url(15, 101, 100)
        bbox_a = url_a.split("bbox=")[1].split("&")[0]
        bbox_b = url_b.split("bbox=")[1].split("&")[0]
        west_a, south_a, east_a, north_a = [float(x) for x in bbox_a.split(",")]
        west_b, south_b, east_b, north_b = [float(x) for x in bbox_b.split(",")]
        # east edge of tile A should equal west edge of tile B
        assert abs(east_a - west_b) < 1e-10
        # north/south should be identical for same y
        assert abs(south_a - south_b) < 1e-10
        assert abs(north_a - north_b) < 1e-10


class TestNationalMapIntegration:
    """End-to-end test with mocked HTTP — verify tiles land in MBTiles."""

    def _make_jpeg_blob(self):
        """Return a minimal valid JPEG blob (SOI + EOI markers)."""
        return b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9"

    def test_tiles_written_to_mbtiles(self, tmp_path):
        """Mock aiohttp, run a tiny 2x2 bbox, verify tiles in MBTiles."""
        output = tmp_path / "test_naip.mbtiles"
        jpeg_blob = self._make_jpeg_blob()

        # Create a mock args object
        args = MagicMock()
        args.bbox = "-112.01,33.44,-112.0,33.45"
        args.zoom = "15-15"
        args.output = str(output)
        args.concurrency = 5
        args.mode = "nationalmap"

        # Mock fetch_with_retry to return our JPEG blob
        with patch("acquire_imagery.fetch_with_retry", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = jpeg_blob
            with patch("acquire_imagery._cancel_requested", False):
                asyncio.run(run_direct(args, url_fn=nationalmap_tile_url))

        # Verify MBTiles has tiles
        conn = sqlite3.connect(str(output))
        tile_count = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
        assert tile_count > 0, "Expected at least 1 tile in MBTiles"

        # Verify tile data is our JPEG blob
        row = conn.execute("SELECT tile_data FROM tiles LIMIT 1").fetchone()
        assert row[0] == jpeg_blob

        # Verify metadata
        meta = dict(conn.execute("SELECT name, value FROM metadata").fetchall())
        assert meta.get("format") == "jpeg"
        assert "bounds" in meta

        # Verify checkpoint table has entries
        cp_count = conn.execute("SELECT COUNT(*) FROM _checkpoint").fetchone()[0]
        assert cp_count == tile_count

        conn.close()
