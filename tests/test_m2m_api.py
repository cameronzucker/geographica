"""Mock-based unit tests for M2M API functions in acquire_imagery.py.

Tests cover:
- Login success and failure
- Scene search pagination
- Download URL polling logic
- Cancellation handling in run_m2m()
- Progress reporting calls

All tests use mocked HTTP — no live API calls, no credentials needed.
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# Import the module under test
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import acquire_imagery as ai


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_session():
    """Create a mock aiohttp.ClientSession."""
    session = AsyncMock()
    return session


def _make_m2m_response(data, error_code=None, error_message=None, status=200):
    """Build a mock aiohttp response mimicking M2M API JSON structure."""
    body = {"data": data}
    if error_code:
        body["errorCode"] = error_code
        body["errorMessage"] = error_message

    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=body)

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# m2m_login tests
# ---------------------------------------------------------------------------

class TestM2MLogin:
    """Test m2m_login() with mocked HTTP responses."""

    @pytest.mark.asyncio
    async def test_login_success(self, mock_session):
        """Successful login returns an API key string."""
        mock_session.post = MagicMock(
            return_value=_make_m2m_response("mock-api-key-abc123")
        )

        api_key = await ai.m2m_login(mock_session, "testuser", "testtoken")

        assert api_key == "mock-api-key-abc123"
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        assert "login-token" in call_args[0][0]
        payload = call_args[1]["json"]
        assert payload["username"] == "testuser"
        assert payload["token"] == "testtoken"

    @pytest.mark.asyncio
    async def test_login_no_api_key(self, mock_session):
        """Login returning empty data raises RuntimeError."""
        mock_session.post = MagicMock(
            return_value=_make_m2m_response(None)
        )

        with pytest.raises(RuntimeError, match="no API key"):
            await ai.m2m_login(mock_session, "testuser", "testtoken")

    @pytest.mark.asyncio
    async def test_login_error_code(self, mock_session):
        """Login returning an error code raises RuntimeError."""
        mock_session.post = MagicMock(
            return_value=_make_m2m_response(
                None,
                error_code="AUTH_INVALID",
                error_message="Invalid credentials",
            )
        )

        with pytest.raises(RuntimeError, match="AUTH_INVALID"):
            await ai.m2m_login(mock_session, "baduser", "badtoken")

    @pytest.mark.asyncio
    async def test_login_rate_limited_then_succeeds(self, mock_session):
        """Login retries on HTTP 429 and succeeds on next attempt."""
        rate_limit_resp = AsyncMock()
        rate_limit_resp.status = 429
        rate_limit_resp.json = AsyncMock(return_value={"errorMessage": "rate limited"})
        rate_limit_cm = AsyncMock()
        rate_limit_cm.__aenter__ = AsyncMock(return_value=rate_limit_resp)
        rate_limit_cm.__aexit__ = AsyncMock(return_value=False)

        success_cm = _make_m2m_response("retry-key-xyz")

        mock_session.post = MagicMock(side_effect=[rate_limit_cm, success_cm])

        api_key = await ai.m2m_login(mock_session, "testuser", "testtoken")
        assert api_key == "retry-key-xyz"
        assert mock_session.post.call_count == 2


# ---------------------------------------------------------------------------
# m2m_scene_search tests
# ---------------------------------------------------------------------------

class TestM2MSceneSearch:
    """Test m2m_scene_search() pagination logic."""

    @pytest.mark.asyncio
    async def test_single_page(self, mock_session):
        """Scene search with results fitting in one page."""
        scenes = [
            {"entityId": f"scene_{i}", "displayId": f"NAIP_{i}"}
            for i in range(3)
        ]
        mock_session.post = MagicMock(
            return_value=_make_m2m_response({
                "results": scenes,
                "totalHits": 3,
            })
        )

        result = await ai.m2m_scene_search(
            mock_session, "api-key", "naip_alias",
            (-110.98, 32.20, -110.90, 32.28),
        )

        assert len(result) == 3
        assert result[0]["entityId"] == "scene_0"

    @pytest.mark.asyncio
    async def test_multi_page_pagination(self, mock_session):
        """Scene search paginates when totalHits exceeds page size."""
        page1_scenes = [{"entityId": f"scene_{i}"} for i in range(100)]
        page2_scenes = [{"entityId": f"scene_{i}"} for i in range(100, 150)]

        page1_cm = _make_m2m_response({
            "results": page1_scenes,
            "totalHits": 150,
        })
        page2_cm = _make_m2m_response({
            "results": page2_scenes,
            "totalHits": 150,
        })

        mock_session.post = MagicMock(side_effect=[page1_cm, page2_cm])

        result = await ai.m2m_scene_search(
            mock_session, "api-key", "naip_alias",
            (-110.98, 32.20, -110.90, 32.28),
        )

        assert len(result) == 150
        assert mock_session.post.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_results(self, mock_session):
        """Scene search returns empty list when no scenes match."""
        mock_session.post = MagicMock(
            return_value=_make_m2m_response({
                "results": [],
                "totalHits": 0,
            })
        )

        result = await ai.m2m_scene_search(
            mock_session, "api-key", "naip_alias",
            (-110.98, 32.20, -110.90, 32.28),
        )

        assert result == []


# ---------------------------------------------------------------------------
# m2m_get_download_urls tests
# ---------------------------------------------------------------------------

class TestM2MGetDownloadUrls:
    """Test m2m_get_download_urls() polling logic."""

    @pytest.mark.asyncio
    async def test_immediate_availability(self, mock_session):
        """Downloads available immediately (no polling needed)."""
        scenes = [{"entityId": "scene_1"}]

        # download-options response
        options_cm = _make_m2m_response([
            {
                "entityId": "scene_1",
                "productId": "prod_1",
                "productName": "GeoTIFF",
                "available": True,
            }
        ])

        # download-request response
        request_cm = _make_m2m_response({
            "availableDownloads": 1,
            "preparingDownloads": 0,
        })

        # download-retrieve response — all available immediately
        retrieve_cm = _make_m2m_response({
            "available": [
                {"url": "https://example.com/scene_1.tif", "entityId": "scene_1"}
            ],
            "requested": [],
        })

        mock_session.post = MagicMock(
            side_effect=[options_cm, request_cm, retrieve_cm]
        )

        urls = await ai.m2m_get_download_urls(
            mock_session, "api-key", "naip_alias", scenes
        )

        assert len(urls) == 1
        assert urls[0] == "https://example.com/scene_1.tif"

    @pytest.mark.asyncio
    async def test_polling_until_available(self, mock_session):
        """Downloads require polling — first call has requested items, second is ready."""
        scenes = [{"entityId": "scene_1"}]

        options_cm = _make_m2m_response([
            {
                "entityId": "scene_1",
                "productId": "prod_1",
                "productName": "GeoTIFF",
                "available": True,
            }
        ])

        request_cm = _make_m2m_response({
            "availableDownloads": 0,
            "preparingDownloads": 1,
        })

        # First poll: still queued
        retrieve_poll1 = _make_m2m_response({
            "available": [],
            "requested": [{"entityId": "scene_1", "statusText": "Queued"}],
        })

        # Second poll: ready
        retrieve_poll2 = _make_m2m_response({
            "available": [
                {"url": "https://example.com/scene_1.tif", "entityId": "scene_1"}
            ],
            "requested": [],
        })

        mock_session.post = MagicMock(
            side_effect=[options_cm, request_cm, retrieve_poll1, retrieve_poll2]
        )

        # Patch sleep to avoid actual waiting in tests
        with patch("asyncio.sleep", new_callable=AsyncMock):
            urls = await ai.m2m_get_download_urls(
                mock_session, "api-key", "naip_alias", scenes
            )

        assert len(urls) == 1

    @pytest.mark.asyncio
    async def test_no_geotiff_products(self, mock_session):
        """Returns empty list when no GeoTIFF products are available."""
        scenes = [{"entityId": "scene_1"}]

        # Products with names that don't match the geotiff filter
        options_cm = _make_m2m_response([
            {
                "entityId": "scene_1",
                "productId": "prod_1",
                "productName": "JPEG Preview",
                "available": True,
            },
            {
                "entityId": "scene_1",
                "productId": "prod_2",
                "productName": "Metadata XML",
                "available": True,
            },
        ])

        mock_session.post = MagicMock(return_value=options_cm)

        urls = await ai.m2m_get_download_urls(
            mock_session, "api-key", "naip_alias", scenes
        )

        assert urls == []

    @pytest.mark.asyncio
    async def test_deduplicates_urls(self, mock_session):
        """Same URL from multiple scenes is only returned once."""
        scenes = [{"entityId": "scene_1"}, {"entityId": "scene_2"}]

        options_cm = _make_m2m_response([
            {
                "entityId": "scene_1",
                "productId": "prod_1",
                "productName": "GeoTIFF",
                "available": True,
            },
            {
                "entityId": "scene_2",
                "productId": "prod_2",
                "productName": "GeoTIFF",
                "available": True,
            },
        ])

        request_cm = _make_m2m_response({
            "availableDownloads": 2,
            "preparingDownloads": 0,
        })

        # Both scenes resolve to the same URL (edge case)
        retrieve_cm = _make_m2m_response({
            "available": [
                {"url": "https://example.com/shared.tif", "entityId": "scene_1"},
                {"url": "https://example.com/shared.tif", "entityId": "scene_2"},
            ],
            "requested": [],
        })

        mock_session.post = MagicMock(
            side_effect=[options_cm, request_cm, retrieve_cm]
        )

        urls = await ai.m2m_get_download_urls(
            mock_session, "api-key", "naip_alias", scenes
        )

        assert len(urls) == 1


# ---------------------------------------------------------------------------
# run_m2m cancellation tests
# ---------------------------------------------------------------------------

class TestRunM2MCancellation:
    """Test _cancel_requested handling in run_m2m()."""

    @pytest.fixture(autouse=True)
    def reset_cancel(self):
        """Ensure _cancel_requested is False before each test."""
        ai._cancel_requested = False
        yield
        ai._cancel_requested = False

    @pytest.mark.asyncio
    async def test_cancel_after_login(self, tmp_path, monkeypatch):
        """Cancellation after login writes cancelled status and returns."""
        args = MagicMock()
        args.m2m_username = "testuser"
        args.m2m_token = "testtoken"
        args.bbox = "-110.98,32.20,-110.90,32.28"
        args.staging = str(tmp_path / "staging")
        args.output = str(tmp_path / "output.mbtiles")
        args.concurrency = 2

        async def mock_login(session, username, token):
            # Simulate SIGTERM arriving during login
            ai._cancel_requested = True
            return "mock-key"

        with patch.object(ai, "m2m_login", side_effect=mock_login), \
             patch.object(ai, "m2m_logout", new_callable=AsyncMock) as mock_logout, \
             patch.object(ai, "update_progress") as mock_progress:
            await ai.run_m2m(args)

        # Should have called logout
        mock_logout.assert_called_once()
        # Should have written cancelled status
        assert any(
            c[1].get("status") == "cancelled" or
            (len(c[0]) > 5 and c[0][5] == "cancelled")
            for c in mock_progress.call_args_list
        ), f"Expected cancelled status in progress calls: {mock_progress.call_args_list}"


# ---------------------------------------------------------------------------
# Progress reporting tests
# ---------------------------------------------------------------------------

class TestRunM2MProgress:
    """Test that run_m2m() calls update_progress() at key stages."""

    @pytest.fixture(autouse=True)
    def reset_cancel(self):
        ai._cancel_requested = False
        yield
        ai._cancel_requested = False

    @pytest.mark.asyncio
    async def test_progress_on_error(self, tmp_path, monkeypatch):
        """Login failure writes error status to progress."""
        args = MagicMock()
        args.m2m_username = "testuser"
        args.m2m_token = "testtoken"
        args.bbox = "-110.98,32.20,-110.90,32.28"
        args.staging = str(tmp_path / "staging")
        args.output = str(tmp_path / "output.mbtiles")
        args.concurrency = 2

        with patch.object(ai, "m2m_login",
                          side_effect=RuntimeError("bad creds")), \
             patch.object(ai, "update_progress") as mock_progress, \
             pytest.raises(SystemExit) as exc_info:
            await ai.run_m2m(args)

        assert exc_info.value.code == 1
        # Should have written error status
        error_calls = [c for c in mock_progress.call_args_list
                       if c[1].get("status") == "error" or
                       (len(c[0]) > 5 and "error" in str(c))]
        assert len(error_calls) > 0, \
            f"Expected error status in progress calls: {mock_progress.call_args_list}"

    @pytest.mark.asyncio
    async def test_progress_on_no_scenes(self, tmp_path, monkeypatch):
        """No scenes found writes error status and exits with code 1."""
        args = MagicMock()
        args.m2m_username = "testuser"
        args.m2m_token = "testtoken"
        args.bbox = "-110.98,32.20,-110.90,32.28"
        args.staging = str(tmp_path / "staging")
        args.output = str(tmp_path / "output.mbtiles")
        args.concurrency = 2

        with patch.object(ai, "m2m_login",
                          new_callable=AsyncMock, return_value="mock-key"), \
             patch.object(ai, "m2m_logout", new_callable=AsyncMock), \
             patch.object(ai, "m2m_find_naip_dataset",
                          new_callable=AsyncMock, return_value="naip_alias"), \
             patch.object(ai, "m2m_scene_search",
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(ai, "update_progress") as mock_progress, \
             pytest.raises(SystemExit) as exc_info:
            await ai.run_m2m(args)

        assert exc_info.value.code == 1
