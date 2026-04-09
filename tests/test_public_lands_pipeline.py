"""Tests for build_public_lands.py pipeline functions."""
import os
import sys
import re
import pytest

# Add scripts directory to path so we can import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from build_public_lands import (
    validate_layer_name,
    validate_url_scheme,
    build_ogr2ogr_command,
    build_tippecanoe_command,
    classify_sql,
)


class TestLayerNameValidation:
    """CSO requirement: reject shell metacharacters in layer names."""

    def test_valid_alphanumeric_underscore(self):
        assert validate_layer_name("PADUS4_0Combined_Fee") is True

    def test_valid_long_name(self):
        assert validate_layer_name("PADUS4_0Combined_Proclamation_Marine_Fee_Designation_Easement") is True

    def test_rejects_semicolon(self):
        assert validate_layer_name("layer; rm -rf /") is False

    def test_rejects_quotes(self):
        assert validate_layer_name("layer'DROP") is False

    def test_rejects_empty(self):
        assert validate_layer_name("") is False

    def test_rejects_spaces(self):
        assert validate_layer_name("layer name") is False

    def test_rejects_backticks(self):
        assert validate_layer_name("layer`cmd`") is False

    def test_rejects_dollar(self):
        assert validate_layer_name("layer$var") is False


class TestUrlValidation:
    """CSO requirement: enforce HTTPS for downloads."""

    def test_accepts_https(self):
        assert validate_url_scheme("https://example.com/file.gpkg") is True

    def test_rejects_http(self):
        assert validate_url_scheme("http://example.com/file.gpkg") is False

    def test_rejects_ftp(self):
        assert validate_url_scheme("ftp://example.com/file.gpkg") is False

    def test_rejects_empty(self):
        assert validate_url_scheme("") is False

    def test_rejects_no_scheme(self):
        assert validate_url_scheme("example.com/file.gpkg") is False


class TestClassifySQL:
    """Verify the classification SQL contains all required fields."""

    def test_contains_category(self):
        sql = classify_sql("TestLayer")
        assert "AS category" in sql

    def test_contains_sort_key(self):
        sql = classify_sql("TestLayer")
        assert "AS sort_key" in sql

    def test_contains_from_layer(self):
        sql = classify_sql("TestLayer")
        assert "FROM TestLayer" in sql

    def test_wilderness_classification(self):
        sql = classify_sql("TestLayer")
        assert "Wilderness" in sql

    def test_blm_classification(self):
        sql = classify_sql("TestLayer")
        assert "'BLM'" in sql

    def test_tribal_classification(self):
        sql = classify_sql("TestLayer")
        assert "'Tribal'" in sql

    def test_state_uses_mang_type(self):
        sql = classify_sql("TestLayer")
        assert "Mang_Type" in sql

    def test_sort_key_wilderness_first(self):
        """Wilderness should have lowest sort_key (renders on top)."""
        sql = classify_sql("TestLayer")
        # Find sort_key CASE: Wilderness should be THEN 1
        assert "Wilderness" in sql
        # The first THEN in sort_key should be 1 (for Wilderness)


class TestOgr2ogrCommand:
    """Verify ogr2ogr command structure for shell=False safety."""

    def test_returns_list_not_string(self):
        cmd = build_ogr2ogr_command(
            gpkg_path="/tmp/padus.gpkg",
            layer_name="PADUS4_0Combined_Fee",
            bbox="-115.5,35.5,-113.5,36.5",
            output_path="/tmp/out.geojson",
        )
        assert isinstance(cmd, list), "Must be a list for shell=False"

    def test_starts_with_ogr2ogr(self):
        cmd = build_ogr2ogr_command(
            gpkg_path="/tmp/padus.gpkg",
            layer_name="TestLayer",
            bbox="-115.5,35.5,-113.5,36.5",
            output_path="/tmp/out.geojson",
        )
        assert cmd[0] == "ogr2ogr"

    def test_contains_clipsrc(self):
        cmd = build_ogr2ogr_command(
            gpkg_path="/tmp/padus.gpkg",
            layer_name="TestLayer",
            bbox="-115.5,35.5,-113.5,36.5",
            output_path="/tmp/out.geojson",
        )
        assert "-clipsrc" in cmd

    def test_contains_srs_transform(self):
        cmd = build_ogr2ogr_command(
            gpkg_path="/tmp/padus.gpkg",
            layer_name="TestLayer",
            bbox="-115.5,35.5,-113.5,36.5",
            output_path="/tmp/out.geojson",
        )
        assert "-t_srs" in cmd
        idx = cmd.index("-t_srs")
        assert cmd[idx + 1] == "EPSG:4326"

    def test_sql_contains_category_and_sort_key(self):
        cmd = build_ogr2ogr_command(
            gpkg_path="/tmp/padus.gpkg",
            layer_name="TestLayer",
            bbox="-115.5,35.5,-113.5,36.5",
            output_path="/tmp/out.geojson",
        )
        sql_idx = cmd.index("-sql")
        sql = cmd[sql_idx + 1]
        assert "AS category" in sql
        assert "AS sort_key" in sql
        assert "FROM TestLayer" in sql

    def test_reads_from_gpkg(self):
        """The GeoPackage path must be the input file."""
        cmd = build_ogr2ogr_command(
            gpkg_path="/tmp/padus.gpkg",
            layer_name="TestLayer",
            bbox="-115.5,35.5,-113.5,36.5",
            output_path="/tmp/out.geojson",
        )
        assert "/tmp/padus.gpkg" in cmd


class TestTippecanoeCommand:
    """Verify Tippecanoe flags match adversarial review corrections."""

    def test_returns_list(self):
        cmd = build_tippecanoe_command("/tmp/out.mbtiles", "/tmp/in.geojson")
        assert isinstance(cmd, list)

    def test_no_drop_densest(self):
        cmd = build_tippecanoe_command("/tmp/out.mbtiles", "/tmp/in.geojson")
        cmd_str = " ".join(cmd)
        assert "--drop-densest-as-needed" not in cmd_str

    def test_no_extend_zooms(self):
        cmd = build_tippecanoe_command("/tmp/out.mbtiles", "/tmp/in.geojson")
        cmd_str = " ".join(cmd)
        assert "--extend-zooms-if-still-dropping" not in cmd_str

    def test_uses_coalesce_smallest(self):
        cmd = build_tippecanoe_command("/tmp/out.mbtiles", "/tmp/in.geojson")
        assert "--coalesce-smallest-as-needed" in cmd

    def test_max_tile_bytes(self):
        cmd = build_tippecanoe_command("/tmp/out.mbtiles", "/tmp/in.geojson")
        assert "--maximum-tile-bytes=500000" in cmd

    def test_layer_name_is_public_lands(self):
        cmd = build_tippecanoe_command("/tmp/out.mbtiles", "/tmp/in.geojson")
        assert "-l" in cmd
        idx = cmd.index("-l")
        assert cmd[idx + 1] == "public_lands"

    def test_no_deprecated_detect_shared_borders(self):
        cmd = build_tippecanoe_command("/tmp/out.mbtiles", "/tmp/in.geojson")
        cmd_str = " ".join(cmd)
        assert "--detect-shared-borders" not in cmd_str

    def test_uses_no_simplification_of_shared_nodes(self):
        cmd = build_tippecanoe_command("/tmp/out.mbtiles", "/tmp/in.geojson")
        assert "--no-simplification-of-shared-nodes" in cmd

    def test_zoom_range(self):
        cmd = build_tippecanoe_command("/tmp/out.mbtiles", "/tmp/in.geojson")
        assert "-Z0" in cmd
        assert "-z14" in cmd

    def test_force_overwrite(self):
        cmd = build_tippecanoe_command("/tmp/out.mbtiles", "/tmp/in.geojson")
        assert "-f" in cmd or "--force" in cmd
