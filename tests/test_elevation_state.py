"""Tests for elevation pipeline state merging (B7).

Verifies:
- write_pipeline_state merges with existing state (not overwrites)
- API metadata (estimated_tiles, type, bbox, zoom) is preserved
- Missing state file is handled gracefully
"""
import json
import tempfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from download_elevation import write_pipeline_state


class TestElevationWritePipelineState:
    def test_merges_with_existing_state(self, tmp_path):
        """B7: Progress writes should preserve API metadata fields."""
        db_path = tmp_path / "elevation.mbtiles"
        state_path = tmp_path / ".elevation-state.json"

        # Simulate search service writing initial state
        initial_state = {
            "type": "elevation",
            "mode": "direct",
            "bbox": "-124.8,31.3,-102.0,49.0",
            "zoom": "0-14",
            "estimated_tiles": 1474959,
            "status": "running",
        }
        state_path.write_text(json.dumps(initial_state))

        # Simulate pipeline writing progress update
        write_pipeline_state(str(db_path), {
            "status": "running",
            "tiles_done": 1000,
            "tiles_total": 1474959,
            "rate_per_sec": 34.1,
        })

        result = json.loads(state_path.read_text())
        # Progress fields should be present
        assert result["tiles_done"] == 1000
        assert result["rate_per_sec"] == 34.1
        # API metadata should be preserved (not overwritten)
        assert result["type"] == "elevation"
        assert result["bbox"] == "-124.8,31.3,-102.0,49.0"
        assert result["zoom"] == "0-14"
        assert result["estimated_tiles"] == 1474959

    def test_creates_state_file_if_missing(self, tmp_path):
        """State file should be created if it doesn't exist yet."""
        db_path = tmp_path / "elevation.mbtiles"
        state_path = tmp_path / ".elevation-state.json"

        write_pipeline_state(str(db_path), {
            "status": "running",
            "tiles_done": 0,
            "tiles_total": 100,
        })

        assert state_path.exists()
        result = json.loads(state_path.read_text())
        assert result["status"] == "running"
        assert result["tiles_done"] == 0

    def test_handles_corrupt_existing_state(self, tmp_path):
        """Corrupt JSON in state file should not crash the pipeline."""
        db_path = tmp_path / "elevation.mbtiles"
        state_path = tmp_path / ".elevation-state.json"
        state_path.write_text("not valid json{{{")

        write_pipeline_state(str(db_path), {
            "status": "running",
            "tiles_done": 50,
        })

        result = json.loads(state_path.read_text())
        assert result["status"] == "running"
        assert result["tiles_done"] == 50
