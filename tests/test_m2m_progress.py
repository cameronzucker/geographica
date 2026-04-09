"""Tests for phase-aware M2M progress reporting in acquire_imagery.py."""

import json
import sys
from pathlib import Path

import pytest

# Import update_progress from scripts/acquire_imagery.py
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from acquire_imagery import update_progress, write_pipeline_state


class TestM2MProgressPhases:
    """Test that M2M phase-aware fields are written correctly."""

    def test_downloading_phase_writes_all_geotiff_fields(self, tmp_path):
        output = tmp_path / "imagery.mbtiles"
        update_progress(
            output, "m2m", "-112,33,-111,34", "n/a",
            0, 0,
            phase="downloading",
            scenes_total=42,
            geotiffs_downloaded=10,
            geotiffs_total=42,
            geotiffs_bytes=1024000,
            current_batch=2,
            total_batches=5,
        )
        state_path = tmp_path / ".pipeline-state.json"
        state = json.loads(state_path.read_text())
        assert state["phase"] == "downloading"
        assert state["scenes_total"] == 42
        assert state["geotiffs_downloaded"] == 10
        assert state["geotiffs_total"] == 42
        assert state["geotiffs_bytes"] == 1024000
        assert state["current_batch"] == 2
        assert state["total_batches"] == 5

    def test_converting_phase_writes_phase_field(self, tmp_path):
        output = tmp_path / "imagery.mbtiles"
        update_progress(
            output, "m2m", "-112,33,-111,34", "n/a",
            0, 0,
            phase="converting",
            geotiffs_downloaded=42,
        )
        state_path = tmp_path / ".pipeline-state.json"
        state = json.loads(state_path.read_text())
        assert state["phase"] == "converting"
        assert state["geotiffs_downloaded"] == 42

    def test_complete_phase_sets_status_completed(self, tmp_path):
        output = tmp_path / "imagery.mbtiles"
        update_progress(
            output, "m2m", "-112,33,-111,34", "n/a",
            0, 0,
            status="completed",
            phase="complete",
        )
        state_path = tmp_path / ".pipeline-state.json"
        state = json.loads(state_path.read_text())
        assert state["status"] == "completed"
        assert state["phase"] == "complete"

    def test_direct_mode_unaffected_backward_compat(self, tmp_path):
        """Callers that don't pass M2M kwargs should produce the same output."""
        output = tmp_path / "imagery.mbtiles"
        update_progress(
            output, "direct", "-112,33,-111,34", "0-14",
            50, 100, rate=12.5,
        )
        state_path = tmp_path / ".pipeline-state.json"
        state = json.loads(state_path.read_text())
        assert state["mode"] == "direct"
        assert state["tiles_done"] == 50
        assert state["tiles_total"] == 100
        # M2M fields should NOT be present
        assert "phase" not in state
        assert "scenes_total" not in state
        assert "geotiffs_downloaded" not in state
        assert "geotiffs_total" not in state
        assert "geotiffs_bytes" not in state
        assert "current_batch" not in state
        assert "total_batches" not in state

    def test_state_file_merges_existing_fields(self, tmp_path):
        """M2M progress should merge with existing state, not overwrite."""
        output = tmp_path / "imagery.mbtiles"
        state_path = tmp_path / ".pipeline-state.json"
        # Pre-seed with admin metadata
        state_path.write_text(json.dumps({
            "type": "naip",
            "estimated_tiles": 9999,
            "bbox": "-112,33,-111,34",
        }))
        update_progress(
            output, "m2m", "-112,33,-111,34", "n/a",
            0, 0,
            phase="searching",
        )
        state = json.loads(state_path.read_text())
        # Original fields preserved
        assert state["type"] == "naip"
        assert state["estimated_tiles"] == 9999
        # New fields present
        assert state["phase"] == "searching"
        assert state["status"] == "running"
