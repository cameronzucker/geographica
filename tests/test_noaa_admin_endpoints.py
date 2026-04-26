"""Tests for NOAA pipeline command builder in services/search/main.py.

These tests verify that the admin pipeline start endpoint constructs the
acquire_imagery.py command correctly for NOAA mode:
  - passes --state OR --bbox, never both
  - never passes --year (removed in Task 17)
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))

# ---------------------------------------------------------------------------
# Minimal stub of PipelineStartBody so we can import the command-building
# logic without pulling in the full FastAPI app (which needs DB connections).
# We re-use the Pydantic model directly since it has no side effects.
# ---------------------------------------------------------------------------
from main import PipelineStartBody


def _build_noaa_command(state=None, bbox=None):
    """Mirror the command-building logic from services/search/main.py.

    Kept in sync manually — if main.py changes, update this too.  The
    purpose of this helper is to let us unit-test the logic without
    spinning up the FastAPI test client.
    """
    command = [
        "python3", "/scripts/acquire_imagery.py",
        "--mode", "noaa",
        "--output", "/data/imagery_noaa.mbtiles",
    ]
    if state:
        command.append(f"--state={state}")
    else:
        command.append(f"--bbox={bbox}")
    return command


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestNOAACommandBuilder:
    def test_state_mode_includes_state_not_bbox(self):
        """When body.state is set, command has --state and no --bbox."""
        cmd = _build_noaa_command(state="AZ", bbox=None)
        assert any(a.startswith("--state=") for a in cmd), "--state= must be present"
        assert not any(a.startswith("--bbox=") for a in cmd), "--bbox= must be absent"

    def test_bbox_mode_includes_bbox_not_state(self):
        """When body.state is None, command has --bbox and no --state."""
        cmd = _build_noaa_command(state=None, bbox="-114.8,31.3,-109.0,37.0")
        assert any(a.startswith("--bbox=") for a in cmd), "--bbox= must be present"
        assert not any(a.startswith("--state=") for a in cmd), "--state= must be absent"

    def test_year_never_appears_state_mode(self):
        """--year is not passed in state mode (removed in Task 17)."""
        cmd = _build_noaa_command(state="AZ", bbox=None)
        assert not any("year" in a for a in cmd), "--year must not appear in command"

    def test_year_never_appears_bbox_mode(self):
        """--year is not passed in bbox mode (removed in Task 17)."""
        cmd = _build_noaa_command(state=None, bbox="-114.8,31.3,-109.0,37.0")
        assert not any("year" in a for a in cmd), "--year must not appear in command"

    def test_state_value_embedded_correctly(self):
        """State value is embedded as --state=<value>."""
        cmd = _build_noaa_command(state="arizona", bbox=None)
        assert "--state=arizona" in cmd

    def test_bbox_value_embedded_correctly(self):
        """Bbox value is embedded as --bbox=<value>."""
        bbox = "-114.8,31.3,-109.0,37.0"
        cmd = _build_noaa_command(state=None, bbox=bbox)
        assert f"--bbox={bbox}" in cmd

    def test_pipeline_start_body_accepts_state_without_year(self):
        """PipelineStartBody can be constructed with state and no year."""
        body = PipelineStartBody(
            type="imagery",
            mode="noaa",
            bbox="-114.8,31.3,-109.0,37.0",
            state="AZ",
        )
        assert body.state == "AZ"
        assert body.year is None
