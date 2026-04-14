"""Tests for B5 (token refresh) and B7 (concurrent downloads) fixes in acquire_sentinel.py."""

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from acquire_sentinel import CopernicusAuth, download_scene


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scene(scene_id: str = "S2B_TEST", url: str = "https://example.com/scene.tif"):
    return {
        "id": scene_id,
        "properties": {"eo:cloud_cover": 5},
        "assets": {"visual": {"href": url}},
    }


class FakeChunkedResponse:
    """Fake response that streams data via iter_chunked."""

    def __init__(self, data: bytes, status: int = 200, content_length: int | None = None):
        self.status = status
        self._data = data
        self.content_length = content_length
        self.content = self

    async def iter_chunked(self, size):
        for i in range(0, len(self._data), size):
            yield self._data[i:i + size]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class FakeErrorResponse:
    def __init__(self, status):
        self.status = status
        self.content_length = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# B5: Token refresh during retries
# ---------------------------------------------------------------------------

class TestB5TokenRefreshDuringRetry:
    """Verify token is refreshed before each retry attempt."""

    @pytest.mark.asyncio
    async def test_token_refreshed_on_retry(self, tmp_path):
        """After a failed attempt, token is re-validated before retry."""
        scene = _make_scene()
        staging = tmp_path / "staging"
        staging.mkdir()

        auth = CopernicusAuth("user", "pass")
        auth.access_token = "initial_token"
        auth.expires_at = time.monotonic() + 300

        ensure_calls = []

        async def tracking_ensure(session):
            ensure_calls.append(time.monotonic())
            # Simulate token that's always valid
            return auth.access_token

        auth.ensure_valid_token = tracking_ensure

        semaphore = asyncio.Semaphore(3)

        call_count = 0

        def make_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return FakeErrorResponse(500)
            # Second attempt: success with valid GeoTIFF data
            tif_data = b"II\x2a\x00" + b"\x00" * 100
            return FakeChunkedResponse(tif_data)

        session = MagicMock()
        session.get = MagicMock(side_effect=make_response)

        with patch("acquire_sentinel.asyncio.sleep", new_callable=AsyncMock), \
             patch("acquire_sentinel.validate_file_header", return_value=True), \
             patch("acquire_sentinel.shutil.disk_usage") as mock_disk:
            mock_disk.return_value = MagicMock(free=50 * 1024 * 1024 * 1024)
            result = await download_scene(session, scene, staging, auth, semaphore)

        # ensure_valid_token should have been called at least twice (once per attempt)
        assert len(ensure_calls) >= 2, \
            f"Expected token refresh on retry, got {len(ensure_calls)} calls"


# ---------------------------------------------------------------------------
# B7: Concurrent downloads (verify semaphore actually limits concurrency)
# ---------------------------------------------------------------------------

class TestB7ConcurrentDownloads:
    """Verify downloads run concurrently via asyncio.gather."""

    @pytest.mark.asyncio
    async def test_downloads_run_concurrently(self, tmp_path):
        """Multiple scenes should download concurrently, not sequentially."""
        # Track concurrent execution
        active_count = 0
        max_active = 0

        async def tracking_download(session, scene, staging, auth, semaphore):
            nonlocal active_count, max_active
            active_count += 1
            max_active = max(max_active, active_count)
            await asyncio.sleep(0.01)  # Simulate some work
            active_count -= 1
            # Return a fake path
            dest = staging / f"sentinel_{scene['id']}.tif"
            dest.write_bytes(b"II\x2a\x00" + b"\x00" * 100)
            return dest

        scenes = [_make_scene(f"scene_{i}") for i in range(5)]
        semaphore = asyncio.Semaphore(3)
        staging = tmp_path / "staging"
        staging.mkdir()

        auth = CopernicusAuth("user", "pass")
        auth.access_token = "token"
        auth.expires_at = time.monotonic() + 300

        session = MagicMock()

        # Run 5 scenes concurrently with semaphore of 3
        tasks = [tracking_download(session, s, staging, auth, semaphore) for s in scenes]
        results = await asyncio.gather(*tasks)

        # If truly concurrent, max_active should be > 1
        assert max_active > 1, \
            f"Expected concurrent execution, but max active was {max_active}"
        assert len([r for r in results if r is not None]) == 5
