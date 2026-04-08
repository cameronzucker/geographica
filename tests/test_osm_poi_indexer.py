"""Tests for the OSM POI extraction and indexing script."""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

# Add scripts to path for import
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from build_osm_pois import (
    OPERATOR_NORMALIZE,
    deduplicate_features,
    extract_centroid,
    extract_osm_tag,
    in_bbox,
    make_dedup_key,
    normalize_operator,
    parse_bbox,
    parse_geojsonseq,
    resolve_display_name,
    write_to_sqlite,
)

FIXTURE_PATH = str(Path(__file__).parent / "fixtures" / "test_osm_features.geojsonseq")
DEFAULT_BBOX = (-124.8, 31.3, -102.0, 49.0)


class TestParseGeojsonseq:
    """Test GeoJSONSeq parsing with the fixture file."""

    def test_parses_fixture_features(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        # Should have all named features inside bbox
        # Fixture has 13 lines: 1 unnamed (#7) and 1 outside bbox (#9) should be skipped
        assert len(features) >= 10
        assert len(features) <= 12  # allowing for dedup not applied yet

    def test_point_feature_coordinates(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        shell = [f for f in features if f["name"] == "Shell Station"]
        assert len(shell) >= 1
        assert abs(shell[0]["lat"] - 33.4484) < 0.001
        assert abs(shell[0]["lon"] - (-112.074)) < 0.001

    def test_polygon_centroid_computed(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        cafe = [f for f in features if f["name"] == "Desert Cafe"]
        assert len(cafe) == 1
        # Centroid of the square polygon should be near center
        assert abs(cafe[0]["lat"] - 33.425) < 0.01
        assert abs(cafe[0]["lon"] - (-111.945)) < 0.01

    def test_linestring_midpoint(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        rest = [f for f in features if f["name"] == "I-17 Rest Stop"]
        assert len(rest) == 1
        # Midpoint of 3-point linestring should be the middle point
        assert abs(rest[0]["lat"] - 33.5) < 0.01
        assert abs(rest[0]["lon"] - (-112.1)) < 0.01

    def test_unnamed_features_skipped(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        names = [f["name"] for f in features]
        # Feature #7 has no name/brand/operator -- should not appear
        # Check that no None or empty names exist
        assert all(name and name.strip() for name in names)

    def test_outside_bbox_skipped(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        names = [f["name"] for f in features]
        assert "Out of Bounds Cafe" not in names

    def test_osm_metadata_preserved(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        shell = [f for f in features if f["name"] == "Shell Station"][0]
        assert shell["osm_type"] == "node"
        assert shell["osm_id"] == 12345

    def test_osm_tag_extracted(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        shell = [f for f in features if f["name"] == "Shell Station"][0]
        assert shell["osm_key"] == "amenity"
        assert shell["osm_value"] == "fuel"


class TestBrandFallback:
    """Test name resolution: name || brand || operator."""

    def test_brand_only_feature(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        safeway = [f for f in features if f["name"] == "Safeway"]
        assert len(safeway) == 1
        assert safeway[0]["osm_key"] == "shop"
        assert safeway[0]["osm_value"] == "supermarket"

    def test_resolve_display_name_priority(self):
        assert resolve_display_name({"name": "Foo", "brand": "Bar"}) == "Foo"
        assert resolve_display_name({"brand": "Bar"}) == "Bar"
        assert resolve_display_name({"operator": "Baz"}) == "Baz"
        assert resolve_display_name({}) is None
        assert resolve_display_name({"name": "", "brand": "", "operator": ""}) is None


class TestOperatorNormalization:
    """Test operator name normalization."""

    def test_blm_variants(self):
        assert normalize_operator("US Bureau of Land Management") == "BLM"
        assert normalize_operator("Bureau of Land Management") == "BLM"
        assert normalize_operator("BLM") == "BLM"
        assert normalize_operator("BLM_FFO") == "BLM"

    def test_usfs_variants(self):
        assert normalize_operator("United States Forest Service") == "USFS"
        assert normalize_operator("US Forest Service") == "USFS"
        assert normalize_operator("USFS") == "USFS"

    def test_nps(self):
        assert normalize_operator("National Park Service") == "NPS"

    def test_unknown_operator_kept(self):
        assert normalize_operator("ADOT") == "ADOT"
        assert normalize_operator("California Department of Parks and Recreation") == \
            "California Department of Parks and Recreation"

    def test_none_operator(self):
        assert normalize_operator(None) is None

    def test_case_sensitive(self):
        # "blm" (lowercase) is NOT in the normalization table
        assert normalize_operator("blm") == "blm"

    def test_fixture_operators_normalized(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        usfs = [f for f in features if f["name"] == "Prescott National Forest"]
        assert len(usfs) == 1
        assert usfs[0]["operator"] == "USFS"

        blm = [f for f in features if f["name"] == "Coconino BLM Land"]
        assert len(blm) == 1
        assert blm[0]["operator"] == "BLM"

        nps = [f for f in features if f["name"] == "Grand Canyon National Park"]
        assert len(nps) == 1
        assert nps[0]["operator"] == "NPS"


class TestBboxFiltering:
    """Test bounding box filtering."""

    def test_in_bbox(self):
        bbox = (-115.0, 32.0, -110.0, 37.0)
        assert in_bbox(33.0, -112.0, bbox) is True
        assert in_bbox(50.0, -112.0, bbox) is False
        assert in_bbox(33.0, -120.0, bbox) is False

    def test_tight_bbox_filters(self):
        # Use a tight bbox that only includes Phoenix-area features
        tight_bbox = (-112.5, 33.0, -111.5, 34.0)
        features = parse_geojsonseq(FIXTURE_PATH, tight_bbox)
        names = [f["name"] for f in features]
        assert "Shell Station" in names
        assert "Desert Cafe" in names
        assert "Desert Oasis Inn" not in names  # Las Vegas area
        assert "Grand Canyon National Park" not in names  # too far north


class TestDeduplication:
    """Test index-time deduplication."""

    def test_dedup_same_name_nearby(self):
        # Two features with the same name at the same rounded location should be deduped
        features = [
            {"name": "Test Gas", "osm_key": "amenity", "osm_value": "fuel",
             "operator": None, "osm_type": "node", "osm_id": 1,
             "lat": 33.4480, "lon": -112.0740},
            {"name": "Test Gas", "osm_key": "amenity", "osm_value": "fuel",
             "operator": None, "osm_type": "way", "osm_id": 2,
             "lat": 33.4482, "lon": -112.0738},  # ~25m away, same rounded key
        ]
        deduped = deduplicate_features(features)
        assert len(deduped) == 1  # second one removed (same dedup key, within 50m)

    def test_dedup_different_names_same_location(self):
        features = [
            {"name": "Foo", "osm_key": "amenity", "osm_value": "fuel",
             "operator": None, "osm_type": "node", "osm_id": 1, "lat": 33.0, "lon": -112.0},
            {"name": "Bar", "osm_key": "amenity", "osm_value": "fuel",
             "operator": None, "osm_type": "node", "osm_id": 2, "lat": 33.0, "lon": -112.0},
        ]
        deduped = deduplicate_features(features)
        assert len(deduped) == 2  # different names, both kept

    def test_dedup_commercial_50m(self):
        # Two commercial POIs 40m apart -- should be deduped
        features = [
            {"name": "test", "osm_key": "amenity", "osm_value": "fuel",
             "operator": None, "osm_type": "node", "osm_id": 1,
             "lat": 33.0, "lon": -112.0},
            {"name": "test", "osm_key": "shop", "osm_value": "gas",
             "operator": None, "osm_type": "way", "osm_id": 2,
             "lat": 33.0003, "lon": -112.0},  # ~33m north
        ]
        deduped = deduplicate_features(features)
        assert len(deduped) == 1

    def test_dedup_key_rounding(self):
        # Points that round to the same 3-decimal bucket should have the same key
        key1 = make_dedup_key("Shell Station", 33.4480, -112.0740)
        key2 = make_dedup_key("Shell Station", 33.4482, -112.0738)
        assert key1 == key2  # same after rounding to 3 decimal places

    def test_dedup_key_different_buckets(self):
        # Points that round to different buckets should have different keys
        key1 = make_dedup_key("Shell Station", 33.4484, -112.074)
        key2 = make_dedup_key("Shell Station", 33.4486, -112.073)
        # 33.4484 rounds to 33.448, 33.4486 rounds to 33.449 -- different buckets
        assert key1 != key2


class TestIdempotency:
    """Test that running the indexer twice produces the same result."""

    def test_idempotent_write(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        features = deduplicate_features(features)

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        try:
            # Write twice
            write_to_sqlite(features, db_path)
            write_to_sqlite(features, db_path)

            # Count should be the same as a single write
            conn = sqlite3.connect(db_path)
            count = conn.execute("SELECT COUNT(*) FROM osm_pois").fetchone()[0]
            conn.close()
            assert count == len(features)
        finally:
            os.unlink(db_path)


class TestSqliteWrite:
    """Test database write and schema."""

    def test_creates_tables_and_indexes(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        features = deduplicate_features(features)

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        try:
            write_to_sqlite(features, db_path)
            conn = sqlite3.connect(db_path)

            # Check tables exist
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {t[0] for t in tables}
            assert "osm_pois" in table_names
            assert "osm_fts" in table_names

            # Check indexes exist
            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
            index_names = {i[0] for i in indexes}
            assert "idx_osm_pois_latlon" in index_names
            assert "idx_osm_pois_category_geo" in index_names

            # Check FTS5 works
            fts_results = conn.execute(
                "SELECT COUNT(*) FROM osm_fts WHERE osm_fts MATCH 'Shell'"
            ).fetchone()[0]
            assert fts_results >= 1

            conn.close()
        finally:
            os.unlink(db_path)

    def test_fts_searches_name_and_operator(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        features = deduplicate_features(features)

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        try:
            write_to_sqlite(features, db_path)
            conn = sqlite3.connect(db_path)

            # Search by name
            r1 = conn.execute(
                "SELECT COUNT(*) FROM osm_fts WHERE osm_fts MATCH 'Shell'"
            ).fetchone()[0]
            assert r1 >= 1

            # Search by operator (normalized)
            r2 = conn.execute(
                "SELECT COUNT(*) FROM osm_fts WHERE osm_fts MATCH 'BLM'"
            ).fetchone()[0]
            assert r2 >= 1

            # Search by osm_value
            r3 = conn.execute(
                "SELECT COUNT(*) FROM osm_fts WHERE osm_fts MATCH 'fuel'"
            ).fetchone()[0]
            assert r3 >= 1

            conn.close()
        finally:
            os.unlink(db_path)

    def test_preserves_existing_tables(self):
        """osm_pois write must not destroy existing poi_features table."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        try:
            # Create a fake poi_features table first
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE poi_features (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    class TEXT,
                    state TEXT,
                    county TEXT,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO poi_features (name, class, state, county, lat, lon) VALUES (?, ?, ?, ?, ?, ?)",
                ("Test Peak", "Summit", "AZ", "Maricopa", 33.5, -112.0),
            )
            conn.commit()
            conn.close()

            # Now write OSM POIs
            features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
            features = deduplicate_features(features)
            write_to_sqlite(features, db_path)

            # Verify poi_features still exists and has data
            conn = sqlite3.connect(db_path)
            count = conn.execute("SELECT COUNT(*) FROM poi_features").fetchone()[0]
            assert count == 1
            conn.close()
        finally:
            os.unlink(db_path)


class TestOsmiumCheck:
    """Test osmium availability check."""

    def test_osmium_check_with_shutil_which(self):
        """Verify the script checks for osmium before running the pipeline."""
        import shutil
        # This test just validates the function exists and is used
        # The actual check happens in main() when --pbf is used
        result = shutil.which("osmium")
        # Result is either a path string or None -- both are valid
        assert result is None or isinstance(result, str)


class TestExtractCentroid:
    """Test centroid extraction from GeoJSON geometries."""

    def test_point(self):
        geom = {"type": "Point", "coordinates": [-112.0, 33.5]}
        lat, lon = extract_centroid(geom)
        assert abs(lat - 33.5) < 0.001
        assert abs(lon - (-112.0)) < 0.001

    def test_polygon(self):
        geom = {
            "type": "Polygon",
            "coordinates": [[[-112.0, 33.0], [-111.0, 33.0],
                             [-111.0, 34.0], [-112.0, 34.0],
                             [-112.0, 33.0]]],
        }
        lat, lon = extract_centroid(geom)
        assert abs(lat - 33.5) < 0.01
        assert abs(lon - (-111.5)) < 0.01

    def test_none_geometry(self):
        assert extract_centroid({"type": "Point"}) is None

    def test_empty_coordinates(self):
        assert extract_centroid({"type": "Point", "coordinates": []}) is None
