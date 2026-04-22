"""Tests for NOAA NAIP download mode."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import acquire_imagery
from acquire_imagery import (
    NOAA_NAIP_CATALOG,
    noaa_blob_base_url,
    noaa_cache_dir,
    filter_tiles_by_bbox,
    run_noaa,
)


class TestNOAACatalog:
    def test_arizona_2021_in_catalog(self):
        assert ("AZ", 2021) in NOAA_NAIP_CATALOG
        assert NOAA_NAIP_CATALOG[("AZ", 2021)] == "AZ_NAIP_2021_9596"

    def test_blob_base_url(self):
        url = noaa_blob_base_url("AZ", 2021)
        assert url == "https://coastalimagery.blob.core.windows.net/digitalcoast/AZ_NAIP_2021_9596"

    def test_blob_base_url_missing_state(self):
        with pytest.raises(KeyError):
            noaa_blob_base_url("ZZ", 2099)

    def test_cache_dir_path(self):
        result = noaa_cache_dir(Path("/data"), "AZ", 2021)
        assert result == Path("/data/noaa_cache/AZ_2021")


class TestFilterTilesByBbox:
    @patch("acquire_imagery.subprocess.run")
    def test_returns_filenames_from_ogr2ogr(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="FileName\nm_3311001_ne_12_060_20211014.tif\nm_3311001_nw_12_060_20211014.tif\n",
        )
        result = filter_tiles_by_bbox(
            Path("/tmp/tile_index.shp"),
            west=-112.1, south=33.4, east=-112.0, north=33.5,
        )
        assert len(result) == 2
        assert "m_3311001_ne_12_060_20211014.tif" in result

    @patch("acquire_imagery.subprocess.run")
    def test_empty_bbox_returns_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="FileName\n")
        result = filter_tiles_by_bbox(
            Path("/tmp/tile_index.shp"),
            west=0.0, south=0.0, east=0.1, north=0.1,
        )
        assert result == []

    @patch("acquire_imagery.subprocess.run")
    def test_ogr2ogr_failure_returns_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        result = filter_tiles_by_bbox(
            Path("/tmp/tile_index.shp"),
            west=-112.1, south=33.4, east=-112.0, north=33.5,
        )
        assert result == []


class TestNOAAPipelineExists:
    def test_run_noaa_is_callable(self):
        assert callable(run_noaa)

    def test_run_gdal_subprocess_uses_popen(self):
        """Structural check: the shared helper uses Popen, not subprocess.run.

        After the B5 refactor, acquire_imagery.run_gdal_subprocess is a thin
        wrapper that delegates to gdal_subprocess.run_gdal_subprocess. The
        Popen call lives in the shared module — check there.
        """
        import ast, inspect
        import gdal_subprocess
        source = inspect.getsource(gdal_subprocess.run_gdal_subprocess)
        tree = ast.parse(source)
        popen_calls = [n for n in ast.walk(tree)
                       if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                       and n.func.attr == "Popen"]
        assert len(popen_calls) > 0, "gdal_subprocess.run_gdal_subprocess must use Popen"
