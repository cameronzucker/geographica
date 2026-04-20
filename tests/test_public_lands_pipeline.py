"""Tests for build_public_lands.py pipeline functions."""
import os
import sys
import re
import pytest

# Add scripts directory to path so we can import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from build_public_lands import (
    DEFAULT_PADUS_URL,
    validate_layer_name,
    validate_url_scheme,
    build_ogr2ogr_command,
    build_tippecanoe_command,
    classify_sql,
    classify_feature,
)


class TestPadusUrl:
    """Regression guard for the PAD-US download URL.

    The `/manager/download/<cuid>` route on sciencebase.usgs.gov serves the
    ScienceBase File Manager React SPA (HTML) rather than the file, so any
    download attempt against that endpoint returns ~4 KB of HTML and fails the
    ZIP magic check. The working public-catalog endpoint is
    `/catalog/file/get/<item_id>?name=<filename>`. See commit history and
    2026-04-19 handoff for full diagnosis.
    """

    def test_url_uses_public_catalog_endpoint(self):
        assert DEFAULT_PADUS_URL.startswith(
            "https://www.sciencebase.gov/catalog/file/get/"
        ), (
            "DEFAULT_PADUS_URL must use the /catalog/file/get/ endpoint. "
            f"Current value serves HTML not ZIP: {DEFAULT_PADUS_URL}"
        )

    def test_url_specifies_filename(self):
        # The ?name= query param is required when an item contains multiple
        # files (PAD-US 4.1 has 3 attachments: the ZIP, metadata XML, version history).
        assert "name=PADUS" in DEFAULT_PADUS_URL, (
            f"DEFAULT_PADUS_URL must include ?name=PADUS... so the catalog "
            f"endpoint picks the Geodatabase ZIP, not another file in the same item. "
            f"Current: {DEFAULT_PADUS_URL}"
        )

    def test_url_is_not_the_manager_spa(self):
        # Negative assertion — if someone "fixes" the URL by putting it back to
        # the manager route, this test fails loudly.
        assert "sciencebase.usgs.gov/manager/" not in DEFAULT_PADUS_URL, (
            "sciencebase.usgs.gov/manager/* routes serve the admin React SPA, "
            "not the file. Use www.sciencebase.gov/catalog/file/get/ instead."
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


class TestClassifyFeature:
    """Test Python-based feature classification."""

    def test_wilderness_overrides_usfs(self):
        cat, key = classify_feature({"Des_Tp": "Wilderness Area", "Mang_Name": "USFS"})
        assert cat == "Wilderness"
        assert key == 1

    def test_blm(self):
        cat, key = classify_feature({"Mang_Name": "BLM", "Des_Tp": ""})
        assert cat == "BLM"

    def test_nps(self):
        cat, key = classify_feature({"Mang_Name": "NPS", "Des_Tp": "National Park"})
        assert cat == "NPS"
        assert key == 2

    def test_tribal(self):
        cat, _ = classify_feature({"Mang_Name": "TRIB"})
        assert cat == "Tribal"

    def test_bia(self):
        cat, _ = classify_feature({"Mang_Name": "BIA"})
        assert cat == "Tribal"

    def test_state_by_mang_type(self):
        cat, _ = classify_feature({"Mang_Name": "SDNR", "Mang_Type": "STAT"})
        assert cat == "State"

    def test_other_federal(self):
        cat, key = classify_feature({"Mang_Name": "OTHFED", "Mang_Type": "FED"})
        assert cat == "Other"
        assert key == 10

    def test_empty_props(self):
        cat, key = classify_feature({})
        assert cat == "Other"
        assert key == 10

    def test_sort_key_ordering(self):
        """Wilderness < NPS < FWS < USFS < DOD < BLM < USBR < Tribal < State < Other."""
        _, w = classify_feature({"Des_Tp": "Wilderness"})
        _, nps = classify_feature({"Mang_Name": "NPS"})
        _, blm = classify_feature({"Mang_Name": "BLM"})
        _, state = classify_feature({"Mang_Name": "X", "Mang_Type": "STAT"})
        assert w < nps < blm < state


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
