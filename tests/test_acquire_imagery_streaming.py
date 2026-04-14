"""Tests for streaming download (fetch_to_file) in acquire_imagery.py and acquire_naip.py.

Verifies that large downloads stream to disk instead of buffering in memory (B3 fix).
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class FakeStreamResponse:
    """Mock aiohttp response that yields chunks via iter_chunked."""

    def __init__(self, data: bytes, status: int = 200):
        self.status = status
        self._data = data
        self.content = self

    async def iter_chunked(self, chunk_size: int):
        for i in range(0, len(self._data), chunk_size):
            yield self._data[i:i + chunk_size]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class FakeErrorResponse:
    """Mock aiohttp response with non-200 status."""

    def __init__(self, status: int):
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class TestFetchToFileImagery:
    """Test fetch_to_file in acquire_imagery.py."""

    @pytest.mark.asyncio
    async def test_streams_to_disk(self, tmp_path):
        """Data is written to file via streaming, not loaded into memory."""
        from acquire_imagery import fetch_to_file

        data = b"x" * (256 * 1024)  # 256 KB
        dest = tmp_path / "test.tif"

        session = MagicMock()
        session.get = MagicMock(return_value=FakeStreamResponse(data))

        result = await fetch_to_file(session, "https://example.com/test.tif", dest)

        assert result is True
        assert dest.exists()
        assert dest.read_bytes() == data

    @pytest.mark.asyncio
    async def test_max_size_enforced(self, tmp_path):
        """Download exceeding max_size is aborted and file deleted."""
        from acquire_imagery import fetch_to_file

        data = b"x" * (1024 * 1024)  # 1 MB
        dest = tmp_path / "too_big.tif"

        session = MagicMock()
        session.get = MagicMock(return_value=FakeStreamResponse(data))

        result = await fetch_to_file(
            session, "https://example.com/big.tif", dest,
            max_size=512 * 1024,  # 512 KB limit
        )

        assert result is False
        assert not dest.exists()

    @pytest.mark.asyncio
    async def test_retries_on_server_error(self, tmp_path):
        """HTTP 500 triggers retry, eventual success writes file."""
        from acquire_imagery import fetch_to_file

        data = b"retry_data"
        dest = tmp_path / "retry.tif"

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return FakeErrorResponse(500)
            return FakeStreamResponse(data)

        session = MagicMock()
        session.get = MagicMock(side_effect=side_effect)

        with pytest.importorskip("unittest.mock").patch(
            "acquire_imagery.asyncio.sleep", new_callable=AsyncMock
        ):
            result = await fetch_to_file(session, "https://example.com/retry.tif", dest)

        assert result is True
        assert dest.read_bytes() == data

    @pytest.mark.asyncio
    async def test_returns_false_on_permanent_error(self, tmp_path):
        """HTTP 404 returns False without retry."""
        from acquire_imagery import fetch_to_file

        dest = tmp_path / "not_found.tif"

        session = MagicMock()
        session.get = MagicMock(return_value=FakeErrorResponse(404))

        result = await fetch_to_file(session, "https://example.com/missing.tif", dest)

        assert result is False
        assert not dest.exists()


class TestFetchToFileNaip:
    """Test fetch_to_file in acquire_naip.py."""

    @pytest.mark.asyncio
    async def test_streams_jp2_to_disk(self, tmp_path):
        """JP2 data is streamed to disk."""
        from acquire_naip import fetch_to_file

        data = b"\x00\x00\x00\x0cjP  " + b"\x00" * 1000  # fake JP2
        dest = tmp_path / "county.jp2"

        session = MagicMock()
        session.get = MagicMock(return_value=FakeStreamResponse(data))

        result = await fetch_to_file(session, "https://example.com/county.jp2", dest)

        assert result is True
        assert dest.exists()
        assert len(dest.read_bytes()) == len(data)

    @pytest.mark.asyncio
    async def test_enforces_max_jp2_size(self, tmp_path):
        """Download exceeding max_size is aborted."""
        from acquire_naip import fetch_to_file

        data = b"x" * (1024 * 1024)  # 1 MB
        dest = tmp_path / "huge.jp2"

        session = MagicMock()
        session.get = MagicMock(return_value=FakeStreamResponse(data))

        # Override max_size to something small for testing
        result = await fetch_to_file(
            session, "https://example.com/huge.jp2", dest,
            max_size=100,
        )

        assert result is False
        assert not dest.exists()
