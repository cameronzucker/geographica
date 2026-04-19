"""Test B2 fix: run_m2m writes status='cancelled' when cancel fires during overview."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import acquire_imagery as ai


class TestM2MCancelDuringOverview:
    """If _cancel_requested is set during gdaladdo, final status must be 'cancelled'."""

    @pytest.fixture(autouse=True)
    def reset_cancel(self):
        ai._cancel_requested = False
        yield
        ai._cancel_requested = False

    @pytest.mark.asyncio
    async def test_cancel_during_overview_writes_cancelled(self, tmp_path):
        args = MagicMock()
        args.m2m_username = "u"
        args.m2m_token = "t"
        args.bbox = "-111,33,-110,34"
        args.staging = str(tmp_path / "staging")
        args.output = str(tmp_path / "out.mbtiles")
        args.concurrency = 2

        # Create a non-empty output file so the overview branch fires
        (tmp_path / "out.mbtiles").write_bytes(b"fake mbtiles")

        # Track update_progress calls
        progress_calls = []

        def _track_progress(*pos_args, **kwargs):
            progress_calls.append({"args": pos_args, "kwargs": kwargs})

        # Simulate SIGTERM during gdaladdo by having run_gdal_subprocess
        # set _cancel_requested and raise CalledProcessError.
        import subprocess

        def _fake_gdal(*args, **kwargs):
            ai._cancel_requested = True
            raise subprocess.CalledProcessError(1, args[0] if args else ["gdaladdo"])

        with patch.object(ai, "m2m_login", new_callable=AsyncMock, return_value="k"), \
             patch.object(ai, "m2m_logout", new_callable=AsyncMock), \
             patch.object(ai, "m2m_find_naip_dataset", new_callable=AsyncMock, return_value="a"), \
             patch.object(ai, "m2m_scene_search", new_callable=AsyncMock,
                          return_value=[{"entityId": "e1"}]), \
             patch.object(ai, "m2m_download_batched", new_callable=AsyncMock,
                          return_value=[tmp_path / "dummy.tif"]), \
             patch.object(ai, "run_gdal_subprocess", side_effect=_fake_gdal), \
             patch.object(ai, "update_progress", side_effect=_track_progress), \
             patch.object(ai, "convert_batch_to_mbtiles", return_value=True):

            await ai.run_m2m(args)

        # The LAST update_progress call should be status="cancelled", NOT "completed".
        assert progress_calls, "update_progress was never called"
        last = progress_calls[-1]
        assert last["kwargs"].get("status") == "cancelled", (
            f"Expected last status='cancelled' after overview cancel, "
            f"got status={last['kwargs'].get('status')}"
        )
