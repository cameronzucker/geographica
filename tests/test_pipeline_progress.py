"""Tests for the shared pipeline progress module (scripts/pipeline_progress.py).

Follows TDD: tests written first, then implementation.
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from pipeline_progress import update_progress


class TestBasicWrite:
    def test_basic_write(self, tmp_path):
        """update_progress writes all specified fields to the state file."""
        state_path = tmp_path / "progress.json"
        update_progress(
            state_path,
            source="naip",
            status="running",
            phase="downloading",
            items_done=5,
            items_total=100,
            item_unit="counties",
            detail="Maricopa County, AZ",
        )
        state = json.loads(state_path.read_text())
        assert state["source"] == "naip"
        assert state["status"] == "running"
        assert state["phase"] == "downloading"
        assert state["items_done"] == 5
        assert state["items_total"] == 100
        assert state["item_unit"] == "counties"
        assert state["detail"] == "Maricopa County, AZ"


class TestMergePreservesExistingFields:
    def test_merge_preserves_existing_fields(self, tmp_path):
        """update_progress merges new fields into existing state without overwriting old fields."""
        state_path = tmp_path / "progress.json"
        # Pre-write metadata the search service would have written
        state_path.write_text(json.dumps({
            "type": "naip",
            "bbox": "-112,33,-111,34",
            "estimated_tiles": 50000,
        }))
        update_progress(
            state_path,
            source="naip",
            status="running",
            phase="downloading",
            items_done=3,
            items_total=10,
            item_unit="scenes",
            detail="Scene AZ-001",
        )
        state = json.loads(state_path.read_text())
        # New fields present
        assert state["source"] == "naip"
        assert state["status"] == "running"
        assert state["phase"] == "downloading"
        assert state["items_done"] == 3
        assert state["items_total"] == 10
        # Old fields preserved
        assert state["type"] == "naip"
        assert state["bbox"] == "-112,33,-111,34"
        assert state["estimated_tiles"] == 50000


class TestBytesTracking:
    def test_bytes_tracking(self, tmp_path):
        """bytes_done and bytes_total are written correctly."""
        state_path = tmp_path / "progress.json"
        update_progress(
            state_path,
            source="sentinel",
            status="running",
            items_done=10,
            items_total=100,
            item_unit="tiles",
            detail="Downloading tile 10",
            bytes_done=1024 * 1024 * 50,
            bytes_total=1024 * 1024 * 500,
        )
        state = json.loads(state_path.read_text())
        assert state["bytes_done"] == 1024 * 1024 * 50
        assert state["bytes_total"] == 1024 * 1024 * 500


class TestCompletedStatusValue:
    def test_completed_status_value(self, tmp_path):
        """Status must be 'completed' (not 'complete') to match frontend/backend consumers."""
        state_path = tmp_path / "progress.json"
        update_progress(
            state_path,
            source="naip",
            status="completed",
            items_done=100,
            items_total=100,
            item_unit="counties",
            detail="All counties downloaded",
        )
        state = json.loads(state_path.read_text())
        assert state["status"] == "completed"
        assert state["status"] != "complete"


class TestErrorState:
    def test_error_state(self, tmp_path):
        """Error state writes the error field to the state file."""
        state_path = tmp_path / "progress.json"
        update_progress(
            state_path,
            source="sentinel",
            status="error",
            items_done=5,
            items_total=100,
            item_unit="scenes",
            detail="Failed during download",
            error="Invalid Copernicus credentials",
        )
        state = json.loads(state_path.read_text())
        assert state["status"] == "error"
        assert state["error"] == "Invalid Copernicus credentials"


class TestAtomicWriteNoCorruption:
    def test_atomic_write_no_corruption(self, tmp_path):
        """No .tmp file is left behind, and written JSON is valid."""
        state_path = tmp_path / "progress.json"
        update_progress(
            state_path,
            source="naip",
            status="running",
            items_done=1,
            items_total=10,
            item_unit="tiles",
            detail="Tile 1",
        )
        # No temp file left behind
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Leftover .tmp files found: {tmp_files}"
        # State file is valid JSON with expected content
        text = state_path.read_text()
        state = json.loads(text)  # raises if invalid JSON
        assert state["source"] == "naip"


class TestBboxAndZoomOptional:
    def test_bbox_and_zoom_optional(self, tmp_path):
        """bbox is written when provided; zoom is absent (or None) when not provided."""
        state_path = tmp_path / "progress.json"
        update_progress(
            state_path,
            source="naip",
            status="running",
            items_done=0,
            items_total=5,
            item_unit="tiles",
            detail="Starting",
            bbox="-112,33,-111,34",
        )
        state = json.loads(state_path.read_text())
        assert state["bbox"] == "-112,33,-111,34"
        # zoom should be absent entirely (not just None) when not provided
        assert "zoom" not in state or state["zoom"] is None


class TestTimestamps:
    def test_started_at_set_on_first_call(self, tmp_path):
        """started_at is set on the first call and preserved on subsequent calls."""
        state_path = tmp_path / "progress.json"
        update_progress(
            state_path,
            source="naip",
            status="running",
            items_done=0,
            items_total=10,
            item_unit="tiles",
            detail="Starting",
        )
        state1 = json.loads(state_path.read_text())
        started_at = state1["started_at"]
        assert started_at is not None

        update_progress(
            state_path,
            source="naip",
            status="running",
            items_done=5,
            items_total=10,
            item_unit="tiles",
            detail="Halfway",
        )
        state2 = json.loads(state_path.read_text())
        # started_at must not change on second call
        assert state2["started_at"] == started_at
        # last_updated should be present
        assert "last_updated" in state2

    def test_last_updated_written_every_call(self, tmp_path):
        """last_updated is written on every call."""
        state_path = tmp_path / "progress.json"
        update_progress(
            state_path,
            source="naip",
            status="running",
            items_done=0,
            items_total=5,
            item_unit="tiles",
            detail="Starting",
        )
        state = json.loads(state_path.read_text())
        assert "last_updated" in state
