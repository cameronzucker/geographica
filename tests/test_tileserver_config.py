"""Tests for TileServer config.json updater."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from tileserver_config import add_mbtiles_to_config, remove_mbtiles_from_config
from pipeline_security import sanitize_layer_name


SAMPLE_CONFIG = {
    "options": {"paths": {"root": "/data", "fonts": "fonts-served", "styles": "styles"}},
    "data": {
        "southwest5": {"mbtiles": "southwest5.mbtiles"},
        "imagery": {"mbtiles": "/srv/data/imagery.mbtiles"},
    },
    "styles": {},
}


class TestAddMbtilesToConfig:
    def test_adds_new_entry(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(SAMPLE_CONFIG, indent=2))
        add_mbtiles_to_config(config_path, "imagery_noaa", "/srv/data/imagery_noaa.mbtiles")
        result = json.loads(config_path.read_text())
        assert "imagery_noaa" in result["data"]
        assert result["data"]["imagery_noaa"]["mbtiles"] == "/srv/data/imagery_noaa.mbtiles"

    def test_idempotent(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(SAMPLE_CONFIG, indent=2))
        add_mbtiles_to_config(config_path, "imagery_noaa", "/srv/data/imagery_noaa.mbtiles")
        add_mbtiles_to_config(config_path, "imagery_noaa", "/srv/data/imagery_noaa.mbtiles")
        result = json.loads(config_path.read_text())
        assert len([k for k in result["data"] if k == "imagery_noaa"]) == 1

    def test_preserves_existing_entries(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(SAMPLE_CONFIG, indent=2))
        add_mbtiles_to_config(config_path, "imagery_noaa", "/srv/data/imagery_noaa.mbtiles")
        result = json.loads(config_path.read_text())
        assert result["data"]["southwest5"] == {"mbtiles": "southwest5.mbtiles"}
        assert result["data"]["imagery"] == {"mbtiles": "/srv/data/imagery.mbtiles"}

    def test_preserves_styles_and_options(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(SAMPLE_CONFIG, indent=2))
        add_mbtiles_to_config(config_path, "test", "/srv/data/test.mbtiles")
        result = json.loads(config_path.read_text())
        assert result["options"] == SAMPLE_CONFIG["options"]

    def test_atomic_write(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(SAMPLE_CONFIG, indent=2))
        add_mbtiles_to_config(config_path, "test", "/srv/data/test.mbtiles")
        assert not list(tmp_path.glob("*.tmp"))


class TestRemoveMbtilesFromConfig:
    def test_removes_existing_source(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(SAMPLE_CONFIG, indent=2))
        result = remove_mbtiles_from_config(config_path, "imagery")
        assert result is True
        config = json.loads(config_path.read_text())
        assert "imagery" not in config["data"]

    def test_returns_false_if_not_present(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(SAMPLE_CONFIG, indent=2))
        result = remove_mbtiles_from_config(config_path, "nonexistent")
        assert result is False

    def test_preserves_other_sources(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(SAMPLE_CONFIG, indent=2))
        remove_mbtiles_from_config(config_path, "imagery")
        config = json.loads(config_path.read_text())
        assert config["data"]["southwest5"] == {"mbtiles": "southwest5.mbtiles"}
        assert config["options"] == SAMPLE_CONFIG["options"]
        assert config["styles"] == SAMPLE_CONFIG["styles"]

    def test_handles_empty_data_section(self, tmp_path):
        config_path = tmp_path / "config.json"
        empty_data_config = {**SAMPLE_CONFIG, "data": {}}
        config_path.write_text(json.dumps(empty_data_config, indent=2))
        result = remove_mbtiles_from_config(config_path, "anything")
        assert result is False


class TestSanitizeLayerName:
    def test_simple_name(self):
        assert sanitize_layer_name("phoenix drone") == "phoenix_drone"

    def test_uppercase_lowered(self):
        assert sanitize_layer_name("Phoenix 2024") == "phoenix_2024"

    def test_special_chars_stripped(self):
        assert sanitize_layer_name("my-layer (v2)!") == "my_layer_v2"

    def test_path_traversal_rejected(self):
        with pytest.raises(ValueError, match="path traversal"):
            sanitize_layer_name("../../etc/passwd")

    def test_slash_rejected(self):
        with pytest.raises(ValueError, match="path traversal"):
            sanitize_layer_name("foo/bar")

    def test_null_byte_rejected(self):
        with pytest.raises(ValueError, match="path traversal"):
            sanitize_layer_name("foo\x00bar")

    def test_max_length_32(self):
        result = sanitize_layer_name("a" * 50)
        assert len(result) <= 32

    def test_empty_after_sanitize_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            sanitize_layer_name("!!!")

    def test_leading_trailing_underscores_stripped(self):
        assert sanitize_layer_name("__test__") == "test"
