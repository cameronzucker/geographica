"""Tests for per-stage progress emission in run_noaa."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from acquire_imagery import update_progress


def test_update_progress_persists_tiles_reprojected(tmp_path):
    """New tiles_reprojected param must land in the state file."""
    out = tmp_path / "imagery.mbtiles"
    update_progress(
        out, "noaa", "-112,33,-111,34", "n/a",
        tiles_done=2, tiles_total=10, rate=0.5,
        phase="downloading",
        geotiffs_downloaded=8,
        geotiffs_total=10,
        tiles_reprojected=5,
    )
    state = json.loads((tmp_path / ".pipeline-state.json").read_text())
    assert state["tiles_reprojected"] == 5
    assert state["geotiffs_downloaded"] == 8
    assert state["tiles_done"] == 2
    assert state["rate_per_sec"] == 0.5  # round(0.5, 4) == 0.5


def test_update_progress_omits_tiles_reprojected_when_unset(tmp_path):
    """Backward compat: callers that don't pass the new param don't see it."""
    out = tmp_path / "imagery.mbtiles"
    update_progress(
        out, "direct", "-112,33,-111,34", "0-12",
        tiles_done=100, tiles_total=1000, rate=2.0,
    )
    state = json.loads((tmp_path / ".pipeline-state.json").read_text())
    assert "tiles_reprojected" not in state
