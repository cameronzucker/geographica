"""Test D2: run_noaa writes status='completed_partial' when tiles_failed > 0."""

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestCompletedPartialStatus:
    """Source-level assertion that the new branch exists."""

    def test_run_noaa_source_has_completed_partial_branch(self):
        import acquire_imagery
        src = inspect.getsource(acquire_imagery.run_noaa)
        assert "completed_partial" in src, (
            "D2 fix: run_noaa should write status='completed_partial' when "
            "tiles_done > 0 and tiles_failed > 0."
        )

    def test_completed_partial_gated_on_tiles_failed_gt_zero(self):
        """The branch must be gated on tiles_failed > 0, not just tiles_done > 0."""
        import acquire_imagery
        src = inspect.getsource(acquire_imagery.run_noaa)
        # Find the completed_partial reference and look for tiles_failed nearby
        idx = src.find("completed_partial")
        assert idx != -1
        context = src[max(0, idx - 300):idx + 100]
        assert "tiles_failed" in context, (
            "completed_partial branch must be gated by tiles_failed > 0"
        )
