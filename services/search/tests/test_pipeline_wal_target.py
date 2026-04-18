"""Test B14 fix: reconciliation WAL-checkpoints the correct MBTiles for each pipeline type."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestWalTargetPerType:
    """Verify each pipeline type's reconciliation path WAL-checkpoints the correct file."""

    def test_mbtiles_path_for_type_maps_elevation(self):
        """Sanity: _mbtiles_path_for_type returns elevation.mbtiles for 'elevation'."""
        import main

        # Patch DATA_DIR to a tmp location
        p = main._mbtiles_path_for_type("elevation")
        assert p.name == "elevation.mbtiles"

    def test_mbtiles_path_for_type_maps_naip(self):
        import main
        p = main._mbtiles_path_for_type("naip")
        assert p.name == "imagery_naip.mbtiles"

    def test_mbtiles_path_for_type_maps_sentinel(self):
        import main
        p = main._mbtiles_path_for_type("sentinel")
        assert p.name == "imagery_sentinel.mbtiles"

    def test_mbtiles_path_for_type_default_is_imagery(self):
        import main
        p = main._mbtiles_path_for_type("imagery")
        assert p.name == "imagery.mbtiles"
        p2 = main._mbtiles_path_for_type("unknown_type_xyz")
        assert p2.name == "imagery.mbtiles"

    def test_reconciliation_source_uses_type_not_mode(self):
        """The reconciliation block's WAL target must derive from `type`, not state['mode'].

        We verify this by scanning the source of pipeline_status for
        `_mbtiles_path_for_type(type)` (the correct pattern) and NOT
        `state_data.get("mode"` in the WAL block.
        """
        import inspect
        import main

        src = inspect.getsource(main.pipeline_status)
        # Must call the type-aware helper
        assert "_mbtiles_path_for_type(type)" in src, (
            "pipeline_status should call _mbtiles_path_for_type(type) in the WAL block"
        )
        # Must NOT build a mbtiles_candidates list by mode (old buggy pattern)
        assert "mbtiles_candidates" not in src, (
            "The old mbtiles_candidates iteration should be removed (B14 fix)"
        )
