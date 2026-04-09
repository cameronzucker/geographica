"""Tests for pipeline_security.py — path traversal prevention, magic byte
validation, and identifier sanitization for external data ingestion."""

import tempfile
from pathlib import Path

import pytest

from scripts.pipeline_security import (
    safe_staging_path,
    sanitize_fips,
    sanitize_scene_id,
    validate_file_header,
)


# ---------------------------------------------------------------------------
# safe_staging_path
# ---------------------------------------------------------------------------

class TestSafeStagingPath:
    def setup_method(self):
        self.staging_dir = Path(tempfile.mkdtemp())

    def test_valid_filename(self):
        result = safe_staging_path(self.staging_dir, "naip_04013.jp2")
        assert result == self.staging_dir / "naip_04013.jp2"

    def test_rejects_path_traversal_dotdot(self):
        with pytest.raises(ValueError, match="path traversal"):
            safe_staging_path(self.staging_dir, "../etc/passwd")

    def test_rejects_absolute_path(self):
        with pytest.raises(ValueError):
            safe_staging_path(self.staging_dir, "/etc/passwd")

    def test_rejects_null_bytes(self):
        with pytest.raises(ValueError):
            safe_staging_path(self.staging_dir, "file\x00.tif")

    def test_rejects_backslash(self):
        with pytest.raises(ValueError):
            safe_staging_path(self.staging_dir, "..\\etc\\passwd")


# ---------------------------------------------------------------------------
# validate_file_header
# ---------------------------------------------------------------------------

class TestValidateFileHeader:
    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def _write_file(self, name: str, content: bytes) -> Path:
        p = self.tmpdir / name
        p.write_bytes(content)
        return p

    def test_valid_geotiff_little_endian(self):
        f = self._write_file("le.tif", b"II\x2a\x00" + b"\x00" * 100)
        assert validate_file_header(f, "geotiff") is True

    def test_valid_geotiff_big_endian(self):
        f = self._write_file("be.tif", b"MM\x00\x2a" + b"\x00" * 100)
        assert validate_file_header(f, "geotiff") is True

    def test_valid_jp2(self):
        f = self._write_file("test.jp2", b"\x00\x00\x00\x0cjP  \r\n\x87\x0a")
        assert validate_file_header(f, "jp2") is True

    def test_rejects_wrong_format(self):
        f = self._write_file("evil.tif", b"<!DOCTYPE html><html>...")
        assert validate_file_header(f, "geotiff") is False

    def test_rejects_empty_file(self):
        f = self._write_file("empty.tif", b"")
        assert validate_file_header(f, "geotiff") is False


# ---------------------------------------------------------------------------
# sanitize_scene_id
# ---------------------------------------------------------------------------

class TestSanitizeSceneId:
    def test_valid_scene_id(self):
        scene_id = "S2B_MSIL2A_20260401T123456"
        assert sanitize_scene_id(scene_id) == scene_id

    def test_scene_id_strips_special_chars(self):
        # Each non-[a-zA-Z0-9_] char becomes "_"; leading/trailing "_" stripped.
        # "../evil;rm -rf /" → "_evil_rm__rf_" → strip → "evil_rm__rf"
        result = sanitize_scene_id("../evil;rm -rf /")
        assert result == "evil_rm__rf"


# ---------------------------------------------------------------------------
# sanitize_fips
# ---------------------------------------------------------------------------

class TestSanitizeFips:
    def test_valid_fips(self):
        assert sanitize_fips("04013") == "04013"

    def test_fips_rejects_non_numeric(self):
        with pytest.raises(ValueError, match="FIPS"):
            sanitize_fips("0401X")

    def test_fips_rejects_wrong_length(self):
        with pytest.raises(ValueError, match="FIPS"):
            sanitize_fips("123")
