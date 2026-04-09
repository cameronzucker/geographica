"""Tests for scripts/acquire_naip.py — USDA NAIP county mosaic pipeline.

Uses real SQLite for county lookups (testing pitfall #1), mocked HTTP for
USDA Gateway calls.
"""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from acquire_naip import (
    check_disk_space,
    check_gdal_jp2_support,
    convert_jp2_to_geotiff,
    extract_download_urls,
    load_checkpoint,
    save_checkpoint,
    select_best_url,
)
from build_county_index import counties_for_bbox
from pipeline_security import sanitize_fips, validate_file_header


# ---------------------------------------------------------------------------
# Test fixture helpers (same pattern as test_county_lookup.py)
# ---------------------------------------------------------------------------

TEST_COUNTIES = [
    ("04013", "Maricopa",    "04", "AZ", 23828.0, -113.33, 32.51, -111.04, 34.04),
    ("04019", "Pima",        "04", "AZ", 23796.0, -112.87, 31.33, -110.45, 32.51),
    ("06037", "Los Angeles", "06", "CA", 12308.0, -118.95, 33.70, -117.65, 34.82),
    ("06073", "San Diego",   "06", "CA", 11721.0, -117.60, 32.53, -116.08, 33.51),
    ("32003", "Clark",       "32", "NV", 20489.0, -115.90, 35.00, -114.05, 36.85),
]


def _create_test_db(db_path: str) -> None:
    """Create schema and insert 5 known counties into a real SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE counties (
            fips TEXT PRIMARY KEY, name TEXT NOT NULL,
            state_fips TEXT NOT NULL, state_abbr TEXT NOT NULL,
            area_sq_km REAL, min_lon REAL, min_lat REAL, max_lon REAL, max_lat REAL
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE counties_rtree USING rtree(
            id, min_lon, max_lon, min_lat, max_lat
        )
    """)
    for row in TEST_COUNTIES:
        fips, name, state_fips, state_abbr, area, min_lon, min_lat, max_lon, max_lat = row
        conn.execute(
            "INSERT INTO counties VALUES (?,?,?,?,?,?,?,?,?)",
            (fips, name, state_fips, state_abbr, area, min_lon, min_lat, max_lon, max_lat),
        )
        rowid = conn.execute(
            "SELECT rowid FROM counties WHERE fips = ?", (fips,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO counties_rtree VALUES (?,?,?,?,?)",
            (rowid, min_lon, max_lon, min_lat, max_lat),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 1. County lookup — real SQLite
# ---------------------------------------------------------------------------

class TestCountyLookup:
    def test_bbox_finds_correct_counties(self, tmp_path):
        """Given a bbox around Phoenix, verify Maricopa found, LA not."""
        db = str(tmp_path / "counties.sqlite")
        _create_test_db(db)
        results = counties_for_bbox(db, west=-112.5, south=33.0, east=-111.5, north=33.8)
        fips_found = [r[0] for r in results]
        assert "04013" in fips_found, "Maricopa should be in results"
        assert "06037" not in fips_found, "Los Angeles should NOT be in results"

    def test_wide_bbox_finds_multiple_states(self, tmp_path):
        """Wide bbox should find counties across AZ, CA, NV."""
        db = str(tmp_path / "counties.sqlite")
        _create_test_db(db)
        results = counties_for_bbox(db, west=-118.0, south=32.0, east=-111.0, north=35.0)
        states = {r[2] for r in results}
        assert "AZ" in states
        assert len(results) >= 3


# ---------------------------------------------------------------------------
# 2. URL discovery — extract download URLs from HTML
# ---------------------------------------------------------------------------

class TestURLDiscovery:
    def test_extract_jp2_links(self):
        """Parse USDA Gateway HTML and find JP2 download URLs."""
        html = """
        <html><body>
        <a href="https://nrcs.usda.gov/data/naip/2023/az/04013/naip_04013_2023.jp2">Download JP2</a>
        <a href="https://nrcs.usda.gov/data/naip/2023/az/04013/naip_04013_2023.sid">Download SID</a>
        </body></html>
        """
        links = extract_download_urls(html)
        assert len(links) == 2
        jp2_links = [l for l in links if l["format"] == "jp2"]
        assert len(jp2_links) == 1
        assert jp2_links[0]["url"].endswith(".jp2")

    def test_extract_no_links(self):
        """HTML with no imagery links returns empty list."""
        html = "<html><body><p>No data available</p></body></html>"
        links = extract_download_urls(html)
        assert links == []

    def test_extract_case_insensitive(self):
        """URL extraction should be case-insensitive for extensions."""
        html = '<a href="https://example.com/file.JP2">JP2</a>'
        links = extract_download_urls(html)
        assert len(links) == 1
        assert links[0]["format"] == "jp2"


# ---------------------------------------------------------------------------
# 3. Format preference — JP2 over MrSID
# ---------------------------------------------------------------------------

class TestFormatPreference:
    def test_prefers_jp2_over_mrsid(self):
        """Given both JP2 and MrSID links, JP2 is chosen."""
        links = [
            {"url": "https://example.com/naip.sid", "format": "sid", "filename": "naip.sid"},
            {"url": "https://example.com/naip.jp2", "format": "jp2", "filename": "naip.jp2"},
        ]
        best = select_best_url(links)
        assert best is not None
        assert best["format"] == "jp2"

    def test_jp2_only(self):
        """When only JP2 available, it is selected."""
        links = [
            {"url": "https://example.com/naip.jp2", "format": "jp2", "filename": "naip.jp2"},
        ]
        best = select_best_url(links)
        assert best is not None
        assert best["format"] == "jp2"


# ---------------------------------------------------------------------------
# 4. MrSID skip — county with only MrSID
# ---------------------------------------------------------------------------

class TestMrSIDSkip:
    def test_mrsid_only_returns_none(self):
        """County with only MrSID links should be skipped (returns None)."""
        links = [
            {"url": "https://example.com/naip.sid", "format": "sid", "filename": "naip.sid"},
        ]
        best = select_best_url(links)
        assert best is None, "MrSID-only counties should return None (skip)"

    def test_mrsid_skip_tracked_in_checkpoint(self, tmp_path):
        """Skipped counties are recorded in the checkpoint file."""
        checkpoint = {
            "completed_counties": [],
            "skipped_counties": [
                {"fips": "04019", "name": "Pima", "reason": "MrSID only, unsupported on ARM64"}
            ],
            "discovered_urls": {},
        }
        save_checkpoint(tmp_path, checkpoint)
        loaded = load_checkpoint(tmp_path)
        assert len(loaded["skipped_counties"]) == 1
        assert loaded["skipped_counties"][0]["fips"] == "04019"
        assert "MrSID" in loaded["skipped_counties"][0]["reason"]


# ---------------------------------------------------------------------------
# 5. Filename sanitization
# ---------------------------------------------------------------------------

class TestFilenameSanitization:
    def test_naip_filename_pattern(self):
        """Verify naip_{sanitize_fips(fips)}.jp2 pattern."""
        fips = "04013"
        safe = sanitize_fips(fips)
        filename = f"naip_{safe}.jp2"
        assert filename == "naip_04013.jp2"

    def test_invalid_fips_rejected(self):
        """Non-5-digit FIPS codes are rejected."""
        with pytest.raises(ValueError, match="FIPS"):
            sanitize_fips("0401X")

    def test_short_fips_rejected(self):
        """Short FIPS codes are rejected."""
        with pytest.raises(ValueError, match="FIPS"):
            sanitize_fips("123")


# ---------------------------------------------------------------------------
# 6. File validation — JP2 magic bytes
# ---------------------------------------------------------------------------

class TestFileValidation:
    def test_valid_jp2_header(self, tmp_path):
        """JP2 file with correct magic bytes passes validation."""
        jp2 = tmp_path / "test.jp2"
        # JP2 magic: 00 00 00 0c 6a 50
        jp2.write_bytes(b"\x00\x00\x00\x0cjP  \r\n\x87\x0a" + b"\x00" * 100)
        assert validate_file_header(jp2, "jp2") is True

    def test_invalid_jp2_header(self, tmp_path):
        """Non-JP2 file fails validation."""
        bad = tmp_path / "bad.jp2"
        bad.write_bytes(b"<!DOCTYPE html><html>not a jp2</html>")
        assert validate_file_header(bad, "jp2") is False

    def test_empty_file_fails(self, tmp_path):
        """Empty file fails validation."""
        empty = tmp_path / "empty.jp2"
        empty.write_bytes(b"")
        assert validate_file_header(empty, "jp2") is False


# ---------------------------------------------------------------------------
# 7. Checkpoint save/load — resume skips completed
# ---------------------------------------------------------------------------

class TestCheckpointResumeSkips:
    def test_save_and_load_checkpoint(self, tmp_path):
        """Checkpoint round-trips correctly through save/load."""
        checkpoint = {
            "completed_counties": ["04013", "06037"],
            "skipped_counties": [
                {"fips": "04019", "name": "Pima", "reason": "MrSID only"}
            ],
            "discovered_urls": {"04013": {"url": "https://example.com/a.jp2"}},
        }
        save_checkpoint(tmp_path, checkpoint)
        loaded = load_checkpoint(tmp_path)
        assert loaded["completed_counties"] == ["04013", "06037"]
        assert len(loaded["skipped_counties"]) == 1

    def test_resume_skips_completed_counties(self, tmp_path):
        """Completed counties in checkpoint should be skippable on resume."""
        checkpoint = {
            "completed_counties": ["04013"],
            "skipped_counties": [],
            "discovered_urls": {},
        }
        save_checkpoint(tmp_path, checkpoint)
        loaded = load_checkpoint(tmp_path)
        completed = set(loaded["completed_counties"])
        # Simulating resume logic: 04013 already done, 06037 is not
        assert "04013" in completed
        assert "06037" not in completed

    def test_missing_checkpoint_returns_defaults(self, tmp_path):
        """Missing checkpoint file returns empty defaults."""
        loaded = load_checkpoint(tmp_path)
        assert loaded["completed_counties"] == []
        assert loaded["skipped_counties"] == []
        assert loaded["discovered_urls"] == {}

    def test_corrupt_checkpoint_returns_defaults(self, tmp_path):
        """Corrupt JSON checkpoint file returns defaults."""
        cp_path = tmp_path / "checkpoint.json"
        cp_path.write_text("{bad json")
        loaded = load_checkpoint(tmp_path)
        assert loaded["completed_counties"] == []


# ---------------------------------------------------------------------------
# 8. Disk space check
# ---------------------------------------------------------------------------

class TestDiskSpaceCheck:
    def test_low_disk_space_raises(self, tmp_path):
        """Mock shutil.disk_usage to return low free space, verify error raised."""
        mock_usage = MagicMock()
        mock_usage.free = 5 * 1024 * 1024 * 1024  # 5 GB (below 10 GB threshold)
        mock_usage.total = 100 * 1024 * 1024 * 1024

        with patch("acquire_naip.shutil.disk_usage", return_value=mock_usage):
            with pytest.raises(RuntimeError, match="Insufficient disk space"):
                check_disk_space(tmp_path)

    def test_sufficient_disk_space_ok(self, tmp_path):
        """Sufficient disk space does not raise."""
        mock_usage = MagicMock()
        mock_usage.free = 50 * 1024 * 1024 * 1024  # 50 GB
        mock_usage.total = 100 * 1024 * 1024 * 1024

        with patch("acquire_naip.shutil.disk_usage", return_value=mock_usage):
            # Should not raise
            check_disk_space(tmp_path)


# ---------------------------------------------------------------------------
# 9. GDAL driver check
# ---------------------------------------------------------------------------

class TestGDALDriverCheck:
    def test_missing_jp2_driver(self):
        """Mock subprocess to simulate missing JP2OpenJPEG, verify error."""
        mock_result = MagicMock()
        mock_result.stdout = "GTiff -raster- (rw+vs): GeoTIFF\nPNG -raster- (rwv): PNG"

        with patch("acquire_naip.subprocess.run", return_value=mock_result):
            assert check_gdal_jp2_support() is False

    def test_jp2_driver_present(self):
        """Mock subprocess showing JP2OpenJPEG present."""
        mock_result = MagicMock()
        mock_result.stdout = (
            "GTiff -raster- (rw+vs): GeoTIFF\n"
            "JP2OpenJPEG -raster,vector- (rwv): JPEG-2000 driver based on OpenJPEG\n"
        )

        with patch("acquire_naip.subprocess.run", return_value=mock_result):
            assert check_gdal_jp2_support() is True

    def test_gdalinfo_not_found(self):
        """If gdalinfo binary is missing, returns False."""
        with patch("acquire_naip.subprocess.run", side_effect=FileNotFoundError):
            assert check_gdal_jp2_support() is False
