"""Tests for NOAA NAIP download mode."""

import argparse
import sqlite3
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
    _run_gdaladdo_with_metadata_fixup,
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

    def test_argparse_accepts_noaa_mode(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--mode", choices=["tnmaccess", "direct", "m2m", "nationalmap", "noaa"])
        parser.add_argument("--state")
        parser.add_argument("--year", type=int, default=2021)
        args = parser.parse_args(["--mode", "noaa", "--state", "AZ"])
        assert args.mode == "noaa"
        assert args.state == "AZ"
        assert args.year == 2021


# ---------------------------------------------------------------------------
# Helpers for gdaladdo / metadata fixup tests
# ---------------------------------------------------------------------------

def _create_test_mbtiles(path, tile_zooms, meta_minzoom=18, meta_maxzoom=18):
    """Create a minimal MBTiles file with tiles at given zoom levels."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tiles "
        "(zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"
    )
    conn.execute("INSERT OR REPLACE INTO metadata VALUES ('minzoom', ?)", (str(meta_minzoom),))
    conn.execute("INSERT OR REPLACE INTO metadata VALUES ('maxzoom', ?)", (str(meta_maxzoom),))
    for z in tile_zooms:
        conn.execute("INSERT INTO tiles VALUES (?, 0, 0, X'00')", (z,))
    conn.commit()
    conn.close()


def _read_metadata(path):
    """Read all metadata key-value pairs from an MBTiles file."""
    conn = sqlite3.connect(str(path))
    rows = conn.execute("SELECT name, value FROM metadata").fetchall()
    conn.close()
    return dict(rows)


# ---------------------------------------------------------------------------
# TestGdaladdoCancelSupport
# ---------------------------------------------------------------------------

class TestGdaladdoCancelSupport:
    """Verify gdaladdo uses run_gdal_subprocess (Popen), not subprocess.run."""

    def test_gdaladdo_uses_run_gdal_subprocess(self, tmp_path):
        mbtiles = tmp_path / "test.mbtiles"
        _create_test_mbtiles(mbtiles, [18])

        with patch.object(acquire_imagery, "run_gdal_subprocess") as mock_gdal, \
             patch.object(acquire_imagery, "_cancel_requested", False):
            _run_gdaladdo_with_metadata_fixup(mbtiles)
            mock_gdal.assert_called_once()
            cmd = mock_gdal.call_args[0][0]
            assert cmd[0] == "gdaladdo"
            assert "-r" in cmd
            assert "average" in cmd

    def test_run_gdal_subprocess_uses_popen(self):
        """Structural check: run_gdal_subprocess uses Popen, not subprocess.run."""
        import ast, inspect
        source = inspect.getsource(acquire_imagery.run_gdal_subprocess)
        tree = ast.parse(source)
        popen_calls = [n for n in ast.walk(tree)
                       if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                       and n.func.attr == "Popen"]
        assert len(popen_calls) > 0, "run_gdal_subprocess must use Popen"


# ---------------------------------------------------------------------------
# TestMetadataFixup
# ---------------------------------------------------------------------------

class TestMetadataFixup:
    """Verify metadata is updated to reflect actual tile zoom levels."""

    def test_metadata_updated_after_gdaladdo(self, tmp_path):
        mbtiles = tmp_path / "test.mbtiles"
        _create_test_mbtiles(mbtiles, [15, 16, 17, 18])

        meta_before = _read_metadata(mbtiles)
        assert meta_before["minzoom"] == "18"

        with patch.object(acquire_imagery, "run_gdal_subprocess"), \
             patch.object(acquire_imagery, "_cancel_requested", False):
            _run_gdaladdo_with_metadata_fixup(mbtiles)

        meta_after = _read_metadata(mbtiles)
        assert meta_after["minzoom"] == "15"
        assert meta_after["maxzoom"] == "18"

    def test_metadata_fixup_skipped_on_cancel(self, tmp_path):
        mbtiles = tmp_path / "test.mbtiles"
        _create_test_mbtiles(mbtiles, [15, 18])

        with patch.object(acquire_imagery, "_cancel_requested", True):
            _run_gdaladdo_with_metadata_fixup(mbtiles)

        meta = _read_metadata(mbtiles)
        assert meta["minzoom"] == "18", "Metadata should not change on cancel"

    def test_metadata_fixup_single_zoom(self, tmp_path):
        mbtiles = tmp_path / "test.mbtiles"
        _create_test_mbtiles(mbtiles, [14], meta_minzoom=18, meta_maxzoom=18)

        with patch.object(acquire_imagery, "run_gdal_subprocess"), \
             patch.object(acquire_imagery, "_cancel_requested", False):
            _run_gdaladdo_with_metadata_fixup(mbtiles)

        meta = _read_metadata(mbtiles)
        assert meta["minzoom"] == "14"
        assert meta["maxzoom"] == "14"
