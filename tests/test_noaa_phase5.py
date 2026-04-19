"""Tests for Task 9 changes: B1, D1, D3 in run_noaa Phase 5."""

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestPhase5CancelGuards:
    """B1: cancel guards must gate each Phase 5 sub-step."""

    def test_run_noaa_has_cancel_guards_between_phase5_steps(self):
        """The Phase 5 block must re-check _cancel_requested after overviews, erode, inpaint."""
        import acquire_imagery
        src = inspect.getsource(acquire_imagery.run_noaa)
        phase5_start = src.find("# Phase 5:")
        assert phase5_start != -1, "Phase 5 comment not found"
        phase5 = src[phase5_start:]

        # Must have at least 3 cancel checks between the 3 sub-steps
        # (after gdaladdo, after erode, after inpaint, before final status)
        cancel_checks = phase5.count("_cancel_requested")
        assert cancel_checks >= 4, (
            f"Phase 5 must have at least 4 _cancel_requested checks "
            f"(one existing at top + new ones between steps); got {cancel_checks}"
        )

    def test_erode_nodata_edges_accepts_cancel_check(self):
        """D1/B9: erode_nodata_edges must accept a cancel_check kwarg."""
        from rasterio_ops import erode_nodata_edges
        sig = inspect.signature(erode_nodata_edges)
        assert "cancel_check" in sig.parameters

    def test_inpaint_nodata_pixels_accepts_cancel_check(self):
        """B1: inpaint_nodata_pixels must accept a cancel_check kwarg."""
        from rasterio_ops import inpaint_nodata_pixels
        sig = inspect.signature(inpaint_nodata_pixels)
        assert "cancel_check" in sig.parameters


class TestPhase5EroderGatedOnResume:
    """D1/B9: erode must NOT run when skip_to_postprocess=True."""

    def test_phase5_erosion_gated_on_skip_to_postprocess(self):
        """Erosion call site must check `not skip_to_postprocess`."""
        import acquire_imagery
        src = inspect.getsource(acquire_imagery.run_noaa)
        # Find the erosion call
        erode_idx = src.find("rio_erode_nodata_edges(")
        assert erode_idx != -1, "erode_nodata_edges call not found"

        # The 400 chars before the call must contain a skip_to_postprocess check
        preceding = src[max(0, erode_idx - 400):erode_idx]
        assert "skip_to_postprocess" in preceding, (
            "Erosion call site must be gated by skip_to_postprocess. "
            "D1 fix: only erode on first run (not on resume), otherwise boundary shifts "
            "can destroy previously-valid tiles with no recovery path."
        )


class TestPhase5WalMode:
    """D3: keep WAL mode permanently — remove the PRAGMA journal_mode=DELETE flip."""

    def test_no_delete_journal_mode_flip(self):
        """Phase 5 final block must NOT flip to DELETE journal mode."""
        import acquire_imagery
        src = inspect.getsource(acquire_imagery.run_noaa)
        # Scan only Phase 5 tail (after "Final WAL checkpoint")
        tail_idx = src.find("Final WAL checkpoint")
        assert tail_idx != -1
        tail = src[tail_idx:]
        assert "journal_mode=DELETE" not in tail, (
            "D3 fix: do not flip to DELETE journal mode. "
            "TileServer reads WAL-mode SQLite correctly; the flip was defensive "
            "and caused recent 404 bugs."
        )

    def test_wal_truncate_checkpoint_preserved(self):
        """Phase 5 final block MUST still issue wal_checkpoint(TRUNCATE)."""
        import acquire_imagery
        src = inspect.getsource(acquire_imagery.run_noaa)
        tail_idx = src.find("Final WAL checkpoint")
        tail = src[tail_idx:]
        assert "wal_checkpoint(TRUNCATE)" in tail, (
            "TRUNCATE checkpoint must be preserved — it flushes WAL into main file "
            "so TileServer reads consistent data."
        )
