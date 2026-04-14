"""Tests for National Map NAIP tile URL builder."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from acquire_imagery import nationalmap_tile_url


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
