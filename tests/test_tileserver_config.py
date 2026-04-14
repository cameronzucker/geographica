"""Tests for TileServer config.json updater."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from tileserver_config import add_mbtiles_to_config


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
