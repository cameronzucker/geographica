"""Tests for spatial search integration with OSM POIs."""
import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))

from spatial import parse_intent, SYNONYM_TABLE, _SYNONYM_LOOKUP


class TestPublicLandSynonyms:
    """Test new BLM/USFS/NPS synonym table entries."""

    def test_blm_synonym_exists(self):
        assert "blm" in _SYNONYM_LOOKUP
        assert "blm land" in _SYNONYM_LOOKUP
        assert "bureau of land management" in _SYNONYM_LOOKUP

    def test_usfs_synonym_exists(self):
        assert "national forest" in _SYNONYM_LOOKUP
        assert "usfs" in _SYNONYM_LOOKUP

    def test_nps_synonym_exists(self):
        assert "national park" in _SYNONYM_LOOKUP
        assert "nps" in _SYNONYM_LOOKUP

    def test_blm_has_osm_operator(self):
        entry = _SYNONYM_LOOKUP["blm"]
        assert entry.get("osm_operator") == "BLM"
        assert ("boundary", "protected_area") in entry["osm_types"]

    def test_usfs_has_osm_operator(self):
        entry = _SYNONYM_LOOKUP["national forest"]
        assert entry.get("osm_operator") == "USFS"
        assert ("boundary", "protected_area") in entry["osm_types"]

    def test_nps_has_osm_operator(self):
        entry = _SYNONYM_LOOKUP["national park"]
        assert entry.get("osm_operator") == "NPS"
        assert ("boundary", "national_park") in entry["osm_types"]
        assert ("boundary", "protected_area") in entry["osm_types"]

    def test_nps_has_gnis_class_park(self):
        entry = _SYNONYM_LOOKUP["national park"]
        assert entry["gnis_class"] == "Park"

    def test_existing_entries_no_osm_operator(self):
        """Existing synonym entries should not have osm_operator."""
        entry = _SYNONYM_LOOKUP["gas station"]
        assert entry.get("osm_operator") is None

    def test_no_conflict_with_forest_service(self):
        """'forest service' should still map to ranger station, not USFS."""
        entry = _SYNONYM_LOOKUP.get("forest service")
        assert entry is not None
        assert entry["fallback_text"] == "ranger station"

    def test_national_park_vs_park(self):
        """'national park' should match NPS entry, not generic 'park'."""
        entry = _SYNONYM_LOOKUP.get("national park")
        assert entry is not None
        assert entry.get("osm_operator") == "NPS"


class TestOsmOperatorInParseIntent:
    """Test osm_operator field in parse_intent() return."""

    def test_blm_query_returns_osm_operator(self):
        result = parse_intent("nearest BLM land", has_position=True, has_route=False)
        assert result["osm_operator"] == "BLM"
        assert result["category"] == "BLM land"

    def test_usfs_query_returns_osm_operator(self):
        result = parse_intent("national forest near me", has_position=True, has_route=False)
        assert result["osm_operator"] == "USFS"
        assert result["category"] == "national forest"

    def test_nps_query_returns_osm_operator(self):
        result = parse_intent("nearest national park", has_position=True, has_route=False)
        assert result["osm_operator"] == "NPS"

    def test_gas_station_no_osm_operator(self):
        result = parse_intent("nearest gas station", has_position=True, has_route=False)
        assert result["osm_operator"] is None

    def test_plain_query_no_osm_operator(self):
        result = parse_intent("Phoenix", has_position=False, has_route=False)
        assert result["osm_operator"] is None

    def test_corridor_blm(self):
        result = parse_intent("BLM land along my route", has_position=True, has_route=True)
        assert result["intent"] == "route_corridor"
        assert result["osm_operator"] == "BLM"

    def test_proximity_nps(self):
        result = parse_intent("NPS within 50 miles", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["osm_operator"] == "NPS"


class TestDirectSqlQueryPath:
    """Test the direct SQL query path for OSM POIs in spatial search."""

    @pytest.fixture
    def osm_db(self, tmp_path, monkeypatch):
        """Create a test database with osm_pois for spatial queries."""
        db_path = str(tmp_path / "test_poi.sqlite")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE osm_pois (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                osm_key TEXT NOT NULL,
                osm_value TEXT NOT NULL,
                operator TEXT,
                osm_type TEXT,
                osm_id INTEGER,
                lat REAL NOT NULL,
                lon REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE VIRTUAL TABLE osm_fts USING fts5(
                name, osm_value, operator,
                content=osm_pois,
                content_rowid=id
            )
        """)
        conn.execute("CREATE INDEX idx_osm_pois_latlon ON osm_pois (lat, lon)")
        conn.execute("CREATE INDEX idx_osm_pois_category_geo ON osm_pois (osm_key, osm_value, lat, lon)")

        # Insert test features along a route corridor (Phoenix to Flagstaff)
        route_features = [
            ("Shell Buckeye", "amenity", "fuel", None, 33.37, -112.58),
            ("Chevron Black Canyon", "amenity", "fuel", None, 34.07, -112.15),
            ("Circle K Camp Verde", "amenity", "fuel", None, 34.56, -111.86),
            ("Prescott NF", "boundary", "protected_area", "USFS", 34.55, -112.50),
            ("Coconino NF", "boundary", "protected_area", "USFS", 35.10, -111.70),
            ("BLM Agua Fria", "boundary", "protected_area", "BLM", 34.20, -112.10),
            ("Grand Canyon NP", "boundary", "national_park", "NPS", 36.05, -112.14),
            ("Montezuma Castle", "boundary", "protected_area", "NPS", 34.61, -111.84),
        ]
        for name, key, value, operator, lat, lon in route_features:
            cur = conn.execute(
                "INSERT INTO osm_pois (name, osm_key, osm_value, operator, lat, lon) VALUES (?,?,?,?,?,?)",
                (name, key, value, operator, lat, lon),
            )
            conn.execute(
                "INSERT INTO osm_fts (rowid, name, osm_value, operator) VALUES (?,?,?,?)",
                (cur.lastrowid, name, value, operator or ""),
            )
        conn.commit()
        conn.close()

        monkeypatch.setenv("POI_DB_PATH", db_path)

        import aiosqlite
        from main import state

        async def _setup():
            conn = await aiosqlite.connect(db_path)
            conn.row_factory = aiosqlite.Row
            state.poi_db = conn
            state.osm_pois_loaded = True
            state.poi_db_loaded = False

        asyncio.get_event_loop().run_until_complete(_setup())
        yield db_path

        async def _cleanup():
            if state.poi_db:
                await state.poi_db.close()
            state.poi_db = None
            state.osm_pois_loaded = False

        asyncio.get_event_loop().run_until_complete(_cleanup())

    def test_direct_query_fuel_in_bbox(self, osm_db):
        """Direct SQL should find fuel stations within bbox."""
        from main import state

        async def _test():
            sql = """
                SELECT name, osm_key, osm_value, operator, lat, lon
                FROM osm_pois
                WHERE osm_key = ? AND osm_value = ?
                AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
            """
            # Phoenix-Flagstaff corridor bbox
            async with state.poi_db.execute(
                sql, ["amenity", "fuel", 33.0, 35.0, -113.0, -111.0]
            ) as cur:
                rows = await cur.fetchall()
            names = [row[0] for row in rows]
            assert "Shell Buckeye" in names
            assert "Chevron Black Canyon" in names

        asyncio.get_event_loop().run_until_complete(_test())

    def test_operator_filter_usfs(self, osm_db):
        """osm_operator filter should return only USFS-managed areas."""
        from main import state

        async def _test():
            sql = """
                SELECT name FROM osm_pois
                WHERE osm_key = ? AND osm_value = ? AND operator = ?
                AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
            """
            async with state.poi_db.execute(
                sql, ["boundary", "protected_area", "USFS", 33.0, 36.0, -113.0, -111.0]
            ) as cur:
                rows = await cur.fetchall()
            names = [row[0] for row in rows]
            assert "Prescott NF" in names
            assert "Coconino NF" in names
            assert "BLM Agua Fria" not in names  # BLM, not USFS

        asyncio.get_event_loop().run_until_complete(_test())

    def test_operator_filter_blm(self, osm_db):
        """osm_operator filter should return only BLM-managed areas."""
        from main import state

        async def _test():
            sql = """
                SELECT name FROM osm_pois
                WHERE osm_key = ? AND osm_value = ? AND operator = ?
                AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
            """
            async with state.poi_db.execute(
                sql, ["boundary", "protected_area", "BLM", 33.0, 36.0, -113.0, -111.0]
            ) as cur:
                rows = await cur.fetchall()
            names = [row[0] for row in rows]
            assert "BLM Agua Fria" in names
            assert "Prescott NF" not in names

        asyncio.get_event_loop().run_until_complete(_test())

    def test_osm_pois_loaded_guard(self):
        """If osm_pois_loaded is False, direct queries should be skipped."""
        from main import state
        assert not state.osm_pois_loaded  # default without fixture
        # The guard in spatial.py checks state.osm_pois_loaded before querying
        # This test verifies the flag is correctly False when no DB is loaded
