"""Test B12 fix: _merger calls _write_progress() on failure branches."""

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestMergerFailureProgress:
    """Verify _write_progress() is called in both _merger failure branches.

    _merger is a closure defined inside run_noaa, which makes unit-level
    invocation awkward. We assert the source structure: both failure
    branches must call _write_progress() before the `continue` or `break`.
    """

    def test_merger_failure_branches_write_progress(self):
        import acquire_imagery
        src = inspect.getsource(acquire_imagery.run_noaa)

        # Find the _merger body
        start = src.find("async def _merger()")
        assert start != -1, "_merger not found in run_noaa"
        # _merger ends at the next closure definition or outer block exit
        end = src.find("# Run all 3 stages concurrently", start)
        assert end != -1
        merger_src = src[start:end]

        # The two failure branches are:
        # 1. `if _cancel_requested or warped_path is None:` ... `tiles_failed += 1`
        # 2. `else:` (merge_ok is False) ... `tiles_failed += 1`
        #
        # Both must call _write_progress() before continuing/breaking.
        # We count occurrences: pre-fix = 1 success call; post-fix = 3 total.
        write_progress_calls = merger_src.count("_write_progress()")
        assert write_progress_calls >= 3, (
            f"Expected at least 3 _write_progress() calls in _merger "
            f"(one success + two failure branches); found {write_progress_calls}. "
            f"B12 fix not applied."
        )
