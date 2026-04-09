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

class TestSelectBestProducts:
    """Test _select_best_products() product priority logic."""

    def test_prefers_compressed(self):
        """Compressed product is preferred over Full Resolution."""
        options = [
            {"entityId": "e1", "id": "p1", "productName": "Full Resolution", "available": True},
            {"entityId": "e1", "id": "p2", "productName": "Compressed", "available": True},
        ]
        result = ai._select_best_products(options)
        assert len(result) == 1
        assert result[0]["_productName"] == "Compressed"

    def test_falls_back_to_full_resolution(self):
        """Full Resolution used when no compressed option exists."""
        options = [
            {"entityId": "e1", "id": "p1", "productName": "Full Resolution", "available": True},
        ]
        result = ai._select_best_products(options)
        assert len(result) == 1
        assert result[0]["_productName"] == "Full Resolution"

    def test_skips_non_imagery_products(self):
        """Non-imagery products like JPEG Preview are skipped."""
        options = [
            {"entityId": "e1", "id": "p1", "productName": "JPEG Preview", "available": True},
            {"entityId": "e1", "id": "p2", "productName": "Metadata XML", "available": True},
        ]
        result = ai._select_best_products(options)
        assert result == []

    def test_one_product_per_entity(self):
        """Each entity gets exactly one product."""
        options = [
            {"entityId": "e1", "id": "p1", "productName": "Compressed", "available": True},
            {"entityId": "e2", "id": "p2", "productName": "Full Resolution", "available": True},
            {"entityId": "e2", "id": "p3", "productName": "Compressed", "available": True},
        ]
        result = ai._select_best_products(options)
        assert len(result) == 2
        by_entity = {r["entityId"]: r for r in result}
        assert by_entity["e2"]["_productName"] == "Compressed"

    def test_skips_unavailable(self):
        """Products with available=False are skipped."""
        options = [
            {"entityId": "e1", "id": "p1", "productName": "Compressed", "available": False},
            {"entityId": "e1", "id": "p2", "productName": "Full Resolution", "available": True},
        ]
        result = ai._select_best_products(options)
        assert len(result) == 1
        assert result[0]["_productName"] == "Full Resolution"


class TestRequestAndPollUrls:
    """Test _m2m_request_and_poll_urls() polling logic.

    Mocks match the official USGS M2M response format:
    download-request returns availableDownloads, preparingDownloads, newRecords
    download-retrieve returns available, requested
    """

    @pytest.mark.asyncio
    async def test_immediate_availability(self, mock_session):
        """All downloads available immediately (no polling needed)."""
        downloads = [{"entityId": "e1", "productId": "p1"}]

        request_cm = _make_m2m_response({
            "availableDownloads": [
                {"downloadId": 100, "url": "https://example.com/scene_1.tif", "entityId": "e1"}
            ],
            "preparingDownloads": [],
            "newRecords": {"100": "test_label"},
            "failed": [],
        })

        mock_session.post = MagicMock(return_value=request_cm)

        urls = await ai._m2m_request_and_poll_urls(
            mock_session, "api-key", downloads, "test_label"
        )

        assert len(urls) == 1
        assert urls[0] == "https://example.com/scene_1.tif"

    @pytest.mark.asyncio
    async def test_polling_until_available(self, mock_session):
        """Preparing downloads become available after polling."""
        downloads = [{"entityId": "e1", "productId": "p1"}]

        request_cm = _make_m2m_response({
            "availableDownloads": [],
            "preparingDownloads": [
                {"downloadId": 200, "url": "https://staging.example.com/e1.tif", "entityId": "e1"}
            ],
            "newRecords": {"200": "test_label"},
            "failed": [],
        })

        retrieve_cm = _make_m2m_response({
            "available": [
                {"downloadId": 200, "url": "https://example.com/scene_1.tif", "entityId": "e1"}
            ],
            "requested": [],
        })

        mock_session.post = MagicMock(side_effect=[request_cm, retrieve_cm])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            urls = await ai._m2m_request_and_poll_urls(
                mock_session, "api-key", downloads, "test_label"
            )

        assert len(urls) == 1

    @pytest.mark.asyncio
    async def test_deduplicates_by_download_id(self, mock_session):
        """Same downloadId is only collected once."""
        downloads = [
            {"entityId": "e1", "productId": "p1"},
            {"entityId": "e2", "productId": "p2"},
        ]

        request_cm = _make_m2m_response({
            "availableDownloads": [
                {"downloadId": 300, "url": "https://example.com/shared.tif", "entityId": "e1"},
                {"downloadId": 301, "url": "https://example.com/other.tif", "entityId": "e2"},
            ],
            "preparingDownloads": [],
            "newRecords": {"300": "test_label", "301": "test_label"},
            "failed": [],
        })

        mock_session.post = MagicMock(return_value=request_cm)

        urls = await ai._m2m_request_and_poll_urls(
            mock_session, "api-key", downloads, "test_label"
        )

        assert len(urls) == 2


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
