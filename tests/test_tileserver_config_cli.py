"""CLI tests for scripts/tileserver_config.py — add/remove subcommands."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "tileserver_config.py"

MINIMAL_CONFIG = {
    "options": {"paths": {"mbtiles": "/data/"}},
    "data": {},
}


def _write_config(path: Path, config: dict) -> None:
    path.write_text(json.dumps(config, indent=2) + "\n")


# ---------------------------------------------------------------------------
# add subcommand
# ---------------------------------------------------------------------------

def test_add_source(tmp_path):
    cfg = tmp_path / "config.json"
    _write_config(cfg, MINIMAL_CONFIG)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "add", str(cfg), "imagery_test", "/data/test.mbtiles"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(cfg.read_text())
    assert "imagery_test" in data["data"]
    assert data["data"]["imagery_test"]["mbtiles"] == "/data/test.mbtiles"


def test_add_duplicate_exits_zero(tmp_path):
    cfg = tmp_path / "config.json"
    config = {**MINIMAL_CONFIG, "data": {"imagery_test": {"mbtiles": "/data/test.mbtiles"}}}
    _write_config(cfg, config)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "add", str(cfg), "imagery_test", "/data/test.mbtiles"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "already exists" in combined.lower()


# ---------------------------------------------------------------------------
# remove subcommand
# ---------------------------------------------------------------------------

def test_remove_source(tmp_path):
    cfg = tmp_path / "config.json"
    config = {**MINIMAL_CONFIG, "data": {"imagery_noaa": {"mbtiles": "/data/noaa.mbtiles"}}}
    _write_config(cfg, config)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "remove", str(cfg), "imagery_noaa"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(cfg.read_text())
    assert "imagery_noaa" not in data["data"]


def test_remove_nonexistent_exits_zero(tmp_path):
    cfg = tmp_path / "config.json"
    _write_config(cfg, MINIMAL_CONFIG)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "remove", str(cfg), "nonexistent_source"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# usage / error cases
# ---------------------------------------------------------------------------

def test_no_args_shows_usage():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
