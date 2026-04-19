"""Test B4 fix: _read_tile_from_array rejects tiles fully outside source extent."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from rasterio_ops import _read_tile_from_array
from rasterio.transform import Affine


class TestReadTileOutOfBounds:
    """Verify tiles whose pixel range is entirely outside the source array are rejected."""

    def _make_transform(self):
        """Identity-ish transform: 1 px per 0.01 degrees, origin (0,0)."""
        # Affine(a, b, c, d, e, f): x' = a*col + b*row + c ; y' = d*col + e*row + f
        # a=0.01 (x res), e=-0.01 (y res, negative because rows increase as lat decreases)
        # c=0 (origin lon), f=10 (origin lat, northernmost)
        return Affine(0.01, 0, 0.0, 0, -0.01, 10.0)

    def test_tile_entirely_above_array_returns_none(self):
        """Tile requesting lat 20-21 (above array's 9-10 extent) must return None, not misplaced pixels."""
        data = np.ones((3, 50, 50), dtype=np.uint8) * 100  # visible nonzero pixels
        transform = self._make_transform()
        # Tile bounds well above the array's top edge (lat 9-10)
        tile_bounds = (0.0, 20.0, 0.5, 21.0)  # west, south, east, north
        result = _read_tile_from_array(data, transform, tile_bounds, tile_size=256)
        assert result is None, (
            "Tile fully outside source extent should return None; "
            "otherwise valid pixels get stamped at geometrically wrong positions "
            "via numpy negative-index slicing."
        )

    def test_tile_entirely_below_array_returns_none(self):
        """Tile requesting lat -5 to -4 (below array) returns None."""
        data = np.ones((3, 50, 50), dtype=np.uint8) * 100
        transform = self._make_transform()
        tile_bounds = (0.0, -5.0, 0.5, -4.0)
        result = _read_tile_from_array(data, transform, tile_bounds, tile_size=256)
        assert result is None

    def test_tile_entirely_left_of_array_returns_none(self):
        """Tile requesting lon -5 to -4 (left of array) returns None."""
        data = np.ones((3, 50, 50), dtype=np.uint8) * 100
        transform = self._make_transform()
        tile_bounds = (-5.0, 0.0, -4.0, 0.1)
        result = _read_tile_from_array(data, transform, tile_bounds, tile_size=256)
        assert result is None

    def test_tile_entirely_right_of_array_returns_none(self):
        """Tile requesting lon 5 to 6 (right of 0-0.5 array) returns None."""
        data = np.ones((3, 50, 50), dtype=np.uint8) * 100
        transform = self._make_transform()
        tile_bounds = (5.0, 0.0, 6.0, 0.1)
        result = _read_tile_from_array(data, transform, tile_bounds, tile_size=256)
        assert result is None

    def test_tile_fully_inside_still_works(self):
        """Regression: a tile fully inside the array still returns a populated tile."""
        data = np.ones((3, 50, 50), dtype=np.uint8) * 100
        transform = self._make_transform()
        tile_bounds = (0.05, 9.5, 0.15, 9.6)  # inside the 0-0.5 lon × 9.5-10 lat array
        result = _read_tile_from_array(data, transform, tile_bounds, tile_size=256)
        assert result is not None
        assert result.shape == (3, 256, 256)
        # At least some pixels are nonzero (we sampled from inside the all-100 array)
        assert np.any(result > 0)
