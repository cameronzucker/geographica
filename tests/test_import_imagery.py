"""Tests for BYO GeoTIFF import pipeline."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from import_imagery import scan_import_directory, resolve_output_path


class TestScanImportDirectory:
    def test_finds_tif_files(self, tmp_path):
        (tmp_path / "a.tif").write_bytes(b"II\x2a\x00" + b"\x00" * 100)
        (tmp_path / "b.tiff").write_bytes(b"II\x2a\x00" + b"\x00" * 100)
        (tmp_path / "c.txt").write_text("not a tif")
        result = scan_import_directory(tmp_path)
        assert len(result["tif_files"]) == 2
        assert result["other_geo_files"] == []

    def test_finds_jp2_as_other(self, tmp_path):
        (tmp_path / "a.jp2").write_bytes(b"\x00" * 100)
        result = scan_import_directory(tmp_path)
        assert len(result["tif_files"]) == 0
        assert len(result["other_geo_files"]) == 1
        assert result["other_geo_files"][0].suffix == ".jp2"

    def test_one_level_subdirectory(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "a.tif").write_bytes(b"II\x2a\x00" + b"\x00" * 100)
        result = scan_import_directory(tmp_path)
        assert len(result["tif_files"]) == 1

    def test_rejects_symlinks(self, tmp_path):
        real = tmp_path / "real.tif"
        real.write_bytes(b"II\x2a\x00" + b"\x00" * 100)
        link = tmp_path / "link.tif"
        link.symlink_to(real)
        result = scan_import_directory(tmp_path)
        assert len(result["tif_files"]) == 1
        assert result["tif_files"][0].name == "real.tif"

    def test_empty_directory(self, tmp_path):
        result = scan_import_directory(tmp_path)
        assert result["tif_files"] == []
        assert result["total_bytes"] == 0


class TestResolveOutputPath:
    def test_default_name(self, tmp_path):
        result = resolve_output_path(tmp_path, None)
        assert result == tmp_path / "imagery_custom.mbtiles"

    def test_empty_name(self, tmp_path):
        result = resolve_output_path(tmp_path, "")
        assert result == tmp_path / "imagery_custom.mbtiles"

    def test_named_layer(self, tmp_path):
        result = resolve_output_path(tmp_path, "Phoenix Drone 2026")
        assert result == tmp_path / "imagery_phoenix_drone_2026.mbtiles"

    def test_path_traversal_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            resolve_output_path(tmp_path, "../../etc/passwd")
