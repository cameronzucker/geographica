"""Test B3 fix: reproject_to_mercator must not access src.width/src.height after close."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestReprojectClosedDatasetAccess:
    """Verify the log call at function end does not touch a closed rasterio dataset."""

    def test_no_attribute_access_after_with_exits(self, tmp_path):
        """Simulate a rasterio that raises on attribute access after close.

        If the code reads src.width or src.height after the `with` block exits,
        this test raises a RuntimeError tagged CLOSED_DATASET, which would be
        caught by the function's broad except and make it return False.
        A correct fix captures width/height into locals before the block exits.
        """
        import rasterio_ops

        class ClosedAfterExit:
            """Mock dataset that rasters-like attributes only INSIDE the with block."""

            def __init__(self):
                self._closed = False
                self.crs = "EPSG:4326"
                self.count = 3
                self.dtypes = ("uint8", "uint8", "uint8")
                self.shape = (100, 100)
                self.nodata = None

                class _Bounds:
                    left = -112.0
                    bottom = 33.0
                    right = -111.0
                    top = 34.0

                    def __iter__(self):
                        return iter([-112.0, 33.0, -111.0, 34.0])

                self.bounds = _Bounds()

                from rasterio.transform import Affine
                self.transform = Affine(0.0001, 0, -112.0, 0, -0.0001, 34.0)
                self.profile = {
                    "driver": "GTiff", "dtype": "uint8", "count": 3,
                    "width": 100, "height": 100, "crs": "EPSG:4326",
                    "transform": self.transform,
                }

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self._closed = True
                return False

            def _check(self):
                if self._closed:
                    raise RuntimeError("CLOSED_DATASET attribute access")

            @property
            def width(self):
                self._check()
                return 100

            @property
            def height(self):
                self._check()
                return 100

        fake_src = ClosedAfterExit()

        class FakeDst:
            def __init__(self, *args, **kwargs):
                self.dtypes = ("uint8", "uint8", "uint8")
                self.shape = (100, 100)
                self.nodata = None

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def write(self, *args, **kwargs):
                pass

        # Patch rasterio.open so first call returns fake_src (as-is, our object
        # is already a context manager), and subsequent calls return FakeDst()
        call_count = {"n": 0}

        def fake_open(path, mode="r", **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return fake_src
            return FakeDst()

        with patch("rasterio_ops.rasterio.open", side_effect=fake_open), \
             patch("rasterio_ops.calculate_default_transform",
                   return_value=(fake_src.transform, 100, 100)), \
             patch("rasterio_ops.reproject"):
            result = rasterio_ops.reproject_to_mercator(
                tmp_path / "src.tif", tmp_path / "dst.tif"
            )

        # If the code accesses src.width/src.height after the `with` exits,
        # ClosedAfterExit raises, the except returns False.
        # The fix captures to locals, so result should be True.
        assert result is True, (
            "reproject_to_mercator returned False — likely accessed closed dataset. "
            "Fix: capture src.width / src.height into locals before `with` exits."
        )
