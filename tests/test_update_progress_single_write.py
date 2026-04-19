"""Test B15 fix: update_progress writes the state file exactly once per call."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import acquire_imagery as ai


class TestSingleWrite:
    """update_progress must produce exactly one atomic rename, not two."""

    def test_single_rename_per_call(self, tmp_path, monkeypatch):
        """Patch os.replace to count invocations during a single update_progress call."""
        import os

        output = tmp_path / "out.mbtiles"
        # Need to pass a real file path; state file is derived as
        # output.parent / ".pipeline-state.json"

        rename_count = {"n": 0, "targets": []}
        real_replace = os.replace

        def _count_replace(src, dst):
            rename_count["n"] += 1
            rename_count["targets"].append(str(dst))
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", _count_replace)

        ai.update_progress(
            output, "noaa", "-111,33,-110,34", "n/a",
            tiles_done=5, tiles_total=10, rate=0.5,
            status="running", phase="downloading",
        )

        # Count renames that target the pipeline state file specifically
        state_targets = [t for t in rename_count["targets"]
                         if ".pipeline-state.json" in t
                         and not t.endswith(".tmp")]
        assert len(state_targets) == 1, (
            f"Expected exactly 1 atomic rename to .pipeline-state.json, "
            f"got {len(state_targets)} at: {state_targets}"
        )

    def test_state_file_always_has_compat_fields(self, tmp_path):
        """A single read of the state file must always have tiles_done, tiles_total, rate_per_sec, mode."""
        output = tmp_path / "out.mbtiles"

        ai.update_progress(
            output, "noaa", "-111,33,-110,34", "n/a",
            tiles_done=5, tiles_total=10, rate=0.5,
            status="running", phase="downloading",
        )

        state_path = output.parent / ".pipeline-state.json"
        data = json.loads(state_path.read_text())
        assert "tiles_done" in data
        assert "tiles_total" in data
        assert "rate_per_sec" in data
        assert "mode" in data
        assert data["mode"] == "noaa"
        assert data["tiles_done"] == 5
        assert data["tiles_total"] == 10

    def test_canonical_fields_preserved(self, tmp_path):
        """Canonical fields from _generic_progress must also be present (source, status, phase, detail, items_done, items_total, item_unit)."""
        output = tmp_path / "out.mbtiles"

        ai.update_progress(
            output, "noaa", "-111,33,-110,34", "n/a",
            tiles_done=5, tiles_total=10, rate=0.5,
            status="running", phase="downloading",
        )

        state_path = output.parent / ".pipeline-state.json"
        data = json.loads(state_path.read_text())
        # Canonical fields from pipeline_progress.update_progress
        for field in ("source", "status", "phase", "detail",
                      "items_done", "items_total", "item_unit"):
            assert field in data, f"Missing canonical field: {field}"
        assert data["source"] == "noaa"
        assert data["item_unit"] == "tiles"

    def test_m2m_downloading_phase_uses_geotiffs_unit(self, tmp_path):
        """Regression: during M2M downloading phase, item_unit='geotiffs' still set."""
        output = tmp_path / "out.mbtiles"

        ai.update_progress(
            output, "m2m", "-111,33,-110,34", "n/a",
            tiles_done=0, tiles_total=0, rate=0.0,
            status="running", phase="downloading",
            geotiffs_downloaded=3, geotiffs_total=5,
        )

        state_path = output.parent / ".pipeline-state.json"
        data = json.loads(state_path.read_text())
        assert data["item_unit"] == "geotiffs"
        assert data["items_done"] == 3
        assert data["items_total"] == 5

    def test_preserves_unrelated_fields(self, tmp_path):
        """update_progress must not drop fields written by other pipelines."""
        import json as _json
        output = tmp_path / "out.mbtiles"
        state_path = output.parent / ".pipeline-state.json"
        state_path.write_text(_json.dumps({"custom_field": "sentinel_value"}))

        ai.update_progress(
            output, "noaa", "-111,33,-110,34", "n/a",
            tiles_done=1, tiles_total=2, rate=0.1,
            status="running", phase="downloading",
        )

        data = _json.loads(state_path.read_text())
        assert data.get("custom_field") == "sentinel_value"
