"""Tests for OSM POI search integration in main.py."""
import asyncio
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))

from main import _deduplicate, _query_osm_pois, haversine_m, state


def _create_test_db(db_path: str) -> None:
    """Create a test SQLite database with osm_pois and osm_fts tables."""
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

    # Insert test data
    test_data = [
        ("Shell Station", "amenity", "fuel", "Shell", "node", 1, 33.45, -112.07),
        ("Desert Cafe", "amenity", "restaurant", None, "way", 2, 33.42, -111.95),
        ("Prescott NF", "boundary", "protected_area", "USFS", "relation", 3, 34.5, -112.1),
        ("BLM Land", "boundary", "protected_area", "BLM", "relation", 4, 35.0, -111.5),
        ("Holiday Inn", "tourism", "hotel", None, "node", 5, 36.0, -115.0),
    ]
    for name, key, value, operator, osm_type, osm_id, lat, lon in test_data:
        cur = conn.execute(
            "INSERT INTO osm_pois (name, osm_key, osm_value, operator, osm_type, osm_id, lat, lon) VALUES (?,?,?,?,?,?,?,?)",
            (name, key, value, operator, osm_type, osm_id, lat, lon),
        )
        conn.execute(
            "INSERT INTO osm_fts (rowid, name, osm_value, operator) VALUES (?,?,?,?)",
            (cur.lastrowid, name, value, operator or ""),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def osm_db(tmp_path, monkeypatch):
    """Create a temporary OSM POI database and configure state."""
    db_path = str(tmp_path / "test_poi.sqlite")
    _create_test_db(db_path)
    monkeypatch.setenv("POI_DB_PATH", db_path)

    import aiosqlite

    async def _setup():
        conn = await aiosqlite.connect(db_path)
        conn.row_factory = aiosqlite.Row
        state.poi_db = conn
        state.osm_pois_loaded = True
        state.poi_db_loaded = False  # No GNIS in this test db

    asyncio.get_event_loop().run_until_complete(_setup())
    yield db_path

    async def _cleanup():
        if state.poi_db:
            await state.poi_db.close()
        state.poi_db = None
        state.osm_pois_loaded = False

    asyncio.get_event_loop().run_until_complete(_cleanup())


class TestQueryOsmPois:
    """Test _query_osm_pois() function."""

    @pytest.mark.asyncio
    async def test_returns_results_for_matching_query(self, osm_db):
        results = await _query_osm_pois("Shell", 10, None)
        assert len(results) >= 1
        assert results[0]["name"] == "Shell Station"
        assert results[0]["type"] == "osm_poi"
        assert results[0]["osm_key"] == "amenity"
        assert results[0]["osm_value"] == "fuel"

    @pytest.mark.asyncio
    async def test_token_query_matches_across_columns(self, osm_db):
        # "fuel" is in osm_value column, not name
        results = await _query_osm_pois("fuel", 10, None)
        assert len(results) >= 1
        fuel_names = [r["name"] for r in results]
        assert "Shell Station" in fuel_names

    @pytest.mark.asyncio
    async def test_operator_searchable(self, osm_db):
        results = await _query_osm_pois("BLM", 10, None)
        assert len(results) >= 1
        assert any(r["operator"] == "BLM" for r in results)

    @pytest.mark.asyncio
    async def test_bbox_filtering(self, osm_db):
        # Tight bbox around Phoenix area only
        bbox = "-112.5,33.0,-111.5,34.0"
        results = await _query_osm_pois("Shell", 10, bbox)
        # Shell Station is at 33.45, -112.07 -- inside bbox
        assert len(results) >= 1

        # Tight bbox around Las Vegas -- Shell is outside
        bbox_lv = "-116.0,35.5,-114.0,36.5"
        results_lv = await _query_osm_pois("Shell", 10, bbox_lv)
        assert len(results_lv) == 0

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, osm_db):
        results = await _query_osm_pois("", 10, None)
        assert results == []

    @pytest.mark.asyncio
    async def test_single_char_tokens_skipped(self, osm_db):
        # Single-character tokens are filtered out
        results = await _query_osm_pois("a", 10, None)
        assert results == []


class TestGracefulDegradation:
    """Test behavior when osm_pois table is missing."""

    @pytest.mark.asyncio
    async def test_missing_table_returns_empty(self):
        # Reset state to simulate missing table
        old_loaded = state.osm_pois_loaded
        state.osm_pois_loaded = False
        try:
            results = await _query_osm_pois("Shell", 10, None)
            assert results == []
        finally:
            state.osm_pois_loaded = old_loaded

    @pytest.mark.asyncio
    async def test_none_db_returns_empty(self):
        old_db = state.poi_db
        old_loaded = state.osm_pois_loaded
        state.poi_db = None
        state.osm_pois_loaded = True
        try:
            results = await _query_osm_pois("Shell", 10, None)
            assert results == []
        finally:
            state.poi_db = old_db
            state.osm_pois_loaded = old_loaded


class TestThreeWayDedup:
    """Test _deduplicate() with three result sources."""

    def test_backward_compatible_two_args(self):
        nom = [{"name": "A", "lat": 33.0, "lon": -112.0}]
        poi = [{"name": "B", "lat": 34.0, "lon": -112.0}]
        merged = _deduplicate(nom, poi)
        assert len(merged) == 2

    def test_three_way_merge(self):
        nom = [{"name": "A", "lat": 33.0, "lon": -112.0}]
        poi = [{"name": "B", "lat": 34.0, "lon": -112.0}]
        osm = [{"name": "C", "lat": 35.0, "lon": -112.0}]
        merged = _deduplicate(nom, poi, osm)
        assert len(merged) == 3

    def test_osm_deduped_against_nominatim(self):
        nom = [{"name": "Shell", "lat": 33.0, "lon": -112.0}]
        poi = []
        osm = [{"name": "Shell Station", "lat": 33.0, "lon": -112.0}]  # Same location
        merged = _deduplicate(nom, poi, osm)
        assert len(merged) == 1  # OSM result dropped (within 100m of Nominatim)

    def test_osm_deduped_against_gnis(self):
        nom = []
        poi = [{"name": "Test Peak", "lat": 33.0, "lon": -112.0}]
        osm = [{"name": "Test Peak", "lat": 33.0001, "lon": -112.0}]  # ~11m away
        merged = _deduplicate(nom, poi, osm)
        assert len(merged) == 1  # OSM result dropped (within 100m of GNIS)

    def test_osm_kept_when_distant(self):
        nom = [{"name": "A", "lat": 33.0, "lon": -112.0}]
        poi = [{"name": "B", "lat": 33.0, "lon": -111.0}]
        osm = [{"name": "C", "lat": 35.0, "lon": -110.0}]  # Far from both
        merged = _deduplicate(nom, poi, osm)
        assert len(merged) == 3

    def test_none_osm_arg_backward_compat(self):
        nom = [{"name": "A", "lat": 33.0, "lon": -112.0}]
        poi = [{"name": "B", "lat": 34.0, "lon": -112.0}]
        merged = _deduplicate(nom, poi, None)
        assert len(merged) == 2

    def test_priority_order_nominatim_first(self):
        """Nominatim results should appear before GNIS and OSM."""
        nom = [{"name": "Nom", "lat": 33.0, "lon": -112.0}]
        poi = [{"name": "GNIS", "lat": 34.0, "lon": -112.0}]
        osm = [{"name": "OSM", "lat": 35.0, "lon": -112.0}]
        merged = _deduplicate(nom, poi, osm)
        assert merged[0]["name"] == "Nom"
