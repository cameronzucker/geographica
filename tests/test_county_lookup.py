"""Tests for county lookup database (rtree spatial index).

Uses a REAL in-memory SQLite database with real schema and data.
See testing-pitfalls.md #1: Don't mock SQLite queries.
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from build_county_index import counties_for_bbox, estimate_download_gb


# ---------------------------------------------------------------------------
# Test fixture helpers
# ---------------------------------------------------------------------------

# (fips, name, state_fips, state_abbr, area_sq_km, min_lon, min_lat, max_lon, max_lat)
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
        # Fetch the rowid just inserted to use as rtree id
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
# counties_for_bbox tests
# ---------------------------------------------------------------------------

class TestCountiesForBbox:
    def test_bbox_covering_phoenix(self, tmp_path):
        """bbox around Phoenix should find Maricopa, not LA."""
        db = str(tmp_path / "counties.sqlite")
        _create_test_db(db)
        results = counties_for_bbox(db, west=-112.5, south=33.0, east=-111.5, north=33.8)
        fips_found = [r[0] for r in results]
        assert "04013" in fips_found, "Maricopa should be in results"
        assert "06037" not in fips_found, "Los Angeles should NOT be in results"

    def test_bbox_spanning_az_ca(self, tmp_path):
        """Wide bbox spanning AZ and CA should find both state counties."""
        db = str(tmp_path / "counties.sqlite")
        _create_test_db(db)
        results = counties_for_bbox(db, west=-118.0, south=32.0, east=-111.0, north=35.0)
        fips_found = {r[0] for r in results}
        # Must include AZ counties
        assert "04013" in fips_found, "Maricopa should be found"
        assert "04019" in fips_found, "Pima should be found"
        # Must include at least one CA county
        assert "06037" in fips_found or "06073" in fips_found, "At least one CA county should be found"

    def test_bbox_outside_us(self, tmp_path):
        """bbox over Hawaii (not in test data) returns empty list."""
        db = str(tmp_path / "counties.sqlite")
        _create_test_db(db)
        results = counties_for_bbox(db, west=-160.0, south=20.0, east=-155.0, north=25.0)
        assert results == [], f"Expected empty list, got {results}"

    def test_single_county_bbox(self, tmp_path):
        """Tight bbox over San Diego should find San Diego."""
        db = str(tmp_path / "counties.sqlite")
        _create_test_db(db)
        results = counties_for_bbox(db, west=-117.2, south=32.7, east=-116.5, north=33.2)
        fips_found = [r[0] for r in results]
        assert "06073" in fips_found, "San Diego should be found"

    def test_results_ordered_by_state_and_name(self, tmp_path):
        """Results should be ordered by state_abbr then name (AZ < CA < NV)."""
        db = str(tmp_path / "counties.sqlite")
        _create_test_db(db)
        # Wide bbox to capture all 5 counties
        results = counties_for_bbox(db, west=-120.0, south=30.0, east=-110.0, north=37.5)
        assert len(results) > 0, "Expected at least one result"
        state_abbrs = [r[2] for r in results]  # index 2 = state_abbr
        # All AZ results come before CA, which come before NV
        state_order = []
        for s in state_abbrs:
            if not state_order or state_order[-1] != s:
                state_order.append(s)
        for i in range(len(state_order) - 1):
            assert state_order[i] <= state_order[i + 1], (
                f"States not in order: {state_order}"
            )
        # Within AZ, Maricopa comes before Pima alphabetically
        az_names = [r[1] for r in results if r[2] == "AZ"]
        if len(az_names) >= 2:
            assert az_names == sorted(az_names), f"AZ counties not sorted: {az_names}"

    def test_result_tuple_structure(self, tmp_path):
        """Each result should be a (fips, name, state_abbr, area_sq_km) tuple."""
        db = str(tmp_path / "counties.sqlite")
        _create_test_db(db)
        results = counties_for_bbox(db, west=-112.5, south=33.0, east=-111.5, north=33.8)
        assert len(results) >= 1
        row = results[0]
        assert len(row) == 4, f"Expected 4-tuple, got {len(row)}-tuple"
        fips, name, state_abbr, area_sq_km = row
        assert isinstance(fips, str)
        assert isinstance(name, str)
        assert isinstance(state_abbr, str)
        assert isinstance(area_sq_km, float)


# ---------------------------------------------------------------------------
# estimate_download_gb tests
# ---------------------------------------------------------------------------

class TestEstimateDownloadGb:
    def test_estimate_formula(self):
        """Maricopa (23828 sq km) should estimate ~9.5 GB."""
        result = estimate_download_gb(23828.0)
        expected = 23828.0 * 0.4 / 1000
        assert abs(result - expected) < 0.001, f"Expected ~{expected:.3f}, got {result:.3f}"

    def test_zero_area(self):
        """Zero area should return 0.0."""
        result = estimate_download_gb(0.0)
        assert result == 0.0
