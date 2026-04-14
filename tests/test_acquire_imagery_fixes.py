"""Tests for B4, B6, B8, B10 fixes in acquire_imagery.py."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import acquire_imagery as ai


# ---------------------------------------------------------------------------
# B4: UnboundLocalError in run_m2m
# ---------------------------------------------------------------------------

class TestB4UnboundLocalError:
    """Verify original exception propagates, not UnboundLocalError."""

    @pytest.fixture(autouse=True)
    def reset_cancel(self):
        ai._cancel_requested = False
        yield
        ai._cancel_requested = False

    @pytest.mark.asyncio
    async def test_download_error_propagates_not_unbound(self, tmp_path):
        """When m2m_download_batched raises, the original error is visible."""
        args = MagicMock()
        args.m2m_username = "testuser"
        args.m2m_token = "testtoken"
        args.bbox = "-110.98,32.20,-110.90,32.28"
        args.staging = str(tmp_path / "staging")
        args.output = str(tmp_path / "output.mbtiles")
        args.concurrency = 2

        original_error = RuntimeError("simulated download failure")

        with patch.object(ai, "m2m_login",
                          new_callable=AsyncMock, return_value="mock-key"), \
             patch.object(ai, "m2m_logout", new_callable=AsyncMock), \
             patch.object(ai, "m2m_find_naip_dataset",
                          new_callable=AsyncMock, return_value="naip_alias"), \
             patch.object(ai, "m2m_scene_search",
                          new_callable=AsyncMock,
                          return_value=[{"entityId": "e1"}]), \
             patch.object(ai, "m2m_download_batched",
                          new_callable=AsyncMock,
                          side_effect=original_error), \
             patch.object(ai, "update_progress"):

            # The error should be RuntimeError, NOT UnboundLocalError
            with pytest.raises(RuntimeError, match="simulated download failure"):
                await ai.run_m2m(args)


# ---------------------------------------------------------------------------
# B6: Non-atomic checkpoint writes
# ---------------------------------------------------------------------------

class TestB6AtomicCheckpoint:
    """Verify checkpoint writes are atomic."""

    def test_atomic_write_json_creates_file(self, tmp_path):
        """_atomic_write_json creates a valid JSON file."""
        path = tmp_path / "test.json"
        data = {"key": "value", "count": 42}
        ai._atomic_write_json(path, data)
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded == data

    def test_atomic_write_json_overwrites(self, tmp_path):
        """_atomic_write_json replaces existing content atomically."""
        path = tmp_path / "test.json"
        path.write_text('{"old": true}')

        ai._atomic_write_json(path, {"new": True})

        loaded = json.loads(path.read_text())
        assert loaded == {"new": True}
        assert "old" not in loaded

    def test_no_tmp_file_left_behind(self, tmp_path):
        """After _atomic_write_json, no .tmp file remains."""
        path = tmp_path / "test.json"
        ai._atomic_write_json(path, {"x": 1})

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0, f"Temp files left behind: {tmp_files}"


# ---------------------------------------------------------------------------
# B8: Double subtraction in M2M polling
# ---------------------------------------------------------------------------

class TestB8DoubleSubtraction:
    """Verify remaining count is computed correctly in _m2m_request_and_poll_urls."""

    @pytest.mark.asyncio
    async def test_remaining_not_double_subtracted(self):
        """With 5 downloads and 1 failed, remaining should count seen_ids correctly."""
        downloads = [{"entityId": f"e{i}", "productId": f"p{i}"} for i in range(5)]

        # 1 failed, 2 available immediately, 2 preparing
        request_data = {
            "availableDownloads": [
                {"downloadId": 1, "url": "https://a.com/1.tif"},
                {"downloadId": 2, "url": "https://a.com/2.tif"},
            ],
            "preparingDownloads": [
                {"downloadId": 3},
                {"downloadId": 4},
            ],
            "newRecords": {"1": "l", "2": "l", "3": "l", "4": "l"},
            "failed": [{"entityId": "e5"}],
        }

        # First poll: 1 more ready
        retrieve_data_1 = {
            "available": [
                {"downloadId": 3, "url": "https://a.com/3.tif"},
            ],
            "requested": [],
        }
        # Second poll: last one ready
        retrieve_data_2 = {
            "available": [
                {"downloadId": 4, "url": "https://a.com/4.tif"},
            ],
            "requested": [],
        }

        request_cm = AsyncMock()
        request_resp = AsyncMock()
        request_resp.status = 200
        request_resp.json = AsyncMock(return_value={"data": request_data})
        request_cm.__aenter__ = AsyncMock(return_value=request_resp)
        request_cm.__aexit__ = AsyncMock(return_value=False)

        retrieve_cm_1 = AsyncMock()
        retrieve_resp_1 = AsyncMock()
        retrieve_resp_1.status = 200
        retrieve_resp_1.json = AsyncMock(return_value={"data": retrieve_data_1})
        retrieve_cm_1.__aenter__ = AsyncMock(return_value=retrieve_resp_1)
        retrieve_cm_1.__aexit__ = AsyncMock(return_value=False)

        retrieve_cm_2 = AsyncMock()
        retrieve_resp_2 = AsyncMock()
        retrieve_resp_2.status = 200
        retrieve_resp_2.json = AsyncMock(return_value={"data": retrieve_data_2})
        retrieve_cm_2.__aenter__ = AsyncMock(return_value=retrieve_resp_2)
        retrieve_cm_2.__aexit__ = AsyncMock(return_value=False)

        session = MagicMock()
        session.post = MagicMock(
            side_effect=[request_cm, retrieve_cm_1, retrieve_cm_2]
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            urls = await ai._m2m_request_and_poll_urls(
                session, "api-key", downloads, "test_label"
            )

        # Should get 4 URLs (5 downloads - 1 failed = 4 expected)
        assert len(urls) == 4, f"Expected 4 URLs, got {len(urls)}"


# ---------------------------------------------------------------------------
# B10: M2M_POLL_INTERVAL constant
# ---------------------------------------------------------------------------

class TestB10PollInterval:
    """Verify M2M_POLL_INTERVAL constant is used."""

    def test_poll_interval_is_30(self):
        """M2M_POLL_INTERVAL should be 30 (USGS guidance)."""
        assert ai.M2M_POLL_INTERVAL == 30
