# M2M API End-to-End Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Validate the existing M2M imagery pipeline against the live USGS API and fix code gaps discovered during review.
**Architecture:** Fix missing SIGTERM handling and progress reporting in run_m2m(), then execute phased testing from auth smoke test through full download pipeline.
**Tech Stack:** Python, aiohttp, GDAL, Docker
**Spec:** docs/superpowers/specs/2026-04-08-m2m-api-test-plan.md

---

## Task 1: Fix run_m2m() Code Gaps

**File:** `scripts/acquire_imagery.py`
**Lines:** 695-741 (the `run_m2m()` function)
**Type:** Bug fix — adding missing cancellation, progress reporting, and error handling to existing code

### Context

The `run_direct()` function (lines 392-485) properly handles `_cancel_requested` checks and calls `update_progress()` throughout. The `run_m2m()` function has none of this. These are three distinct gaps identified in the spec review.

### Steps

#### Step 1.1: Add `_cancel_requested` checks in run_m2m()

The `run_direct()` mode checks `_cancel_requested` between batches (line 461). `run_m2m()` must do the same in the download flow and after each major stage.

In `scripts/acquire_imagery.py`, modify `run_m2m()` starting at line 695. Add cancellation checks after login, after scene search, after getting download URLs, and in the download loop.

```python
async def run_m2m(args):
    """Run the M2M imagery acquisition pipeline."""
    global _cancel_requested

    username = args.m2m_username
    token = args.m2m_token
    if not username or not token:
        log.error("M2M mode requires --m2m-username and --m2m-token "
                  "(or USGS_M2M_USERNAME / USGS_M2M_TOKEN env vars)")
        sys.exit(1)

    bbox = parse_bbox(args.bbox)
    staging = Path(args.staging)
    staging.mkdir(parents=True, exist_ok=True)
    checkpoint = staging / "m2m_checkpoint.json"
    output = Path(args.output)

    # Cap M2M concurrency to prevent API abuse
    m2m_concurrency = min(args.concurrency, 5)
    if args.concurrency > 5:
        log.warning("Capping M2M concurrency from %d to %d (API rate limit safety)",
                     args.concurrency, m2m_concurrency)

    os.environ.setdefault("GDAL_CACHEMAX", "1024")

    import datetime
    update_progress._started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    async with aiohttp.ClientSession() as session:
        # --- Login ---
        try:
            api_key = await m2m_login(session, username, token)
        except Exception as exc:
            log.error("M2M login failed: %s", exc)
            update_progress(output, "m2m", args.bbox, "n/a",
                            0, 0, status="error",
                            error=f"Login failed: {exc}")
            sys.exit(1)

        update_progress(output, "m2m", args.bbox, "n/a",
                        0, 0, status="running")

        if _cancel_requested:
            log.info("Cancellation requested after login — logging out")
            await m2m_logout(session, api_key)
            update_progress(output, "m2m", args.bbox, "n/a",
                            0, 0, status="cancelled")
            return

        try:
            # --- Find NAIP dataset alias ---
            dataset_alias = await m2m_find_naip_dataset(session, api_key)

            if _cancel_requested:
                log.info("Cancellation requested after dataset search — logging out")
                update_progress(output, "m2m", args.bbox, "n/a",
                                0, 0, status="cancelled")
                return

            # --- Search for scenes ---
            scenes = await m2m_scene_search(session, api_key, dataset_alias, bbox)
            if not scenes:
                log.error("No NAIP scenes found for bbox %s", args.bbox)
                update_progress(output, "m2m", args.bbox, "n/a",
                                0, 0, status="error",
                                error=f"No NAIP scenes found for bbox {args.bbox}")
                sys.exit(1)

            update_progress(output, "m2m", args.bbox, "n/a",
                            0, len(scenes), status="running")

            if _cancel_requested:
                log.info("Cancellation requested after scene search — logging out")
                update_progress(output, "m2m", args.bbox, "n/a",
                                0, len(scenes), status="cancelled")
                return

            # --- Get download URLs ---
            urls = await m2m_get_download_urls(
                session, api_key, dataset_alias, scenes
            )
            if not urls:
                log.error("No downloadable URLs obtained")
                update_progress(output, "m2m", args.bbox, "n/a",
                                0, len(scenes), status="error",
                                error="No downloadable GeoTIFF URLs obtained from M2M API")
                sys.exit(1)

            log.info("Got %d download URLs for %d scenes", len(urls), len(scenes))

        finally:
            await m2m_logout(session, api_key)

    if _cancel_requested:
        log.info("Cancellation requested before downloads — stopping")
        update_progress(output, "m2m", args.bbox, "n/a",
                        0, len(urls), status="cancelled")
        return

    # --- Download GeoTIFFs (reuse existing helper) ---
    update_progress(output, "m2m", args.bbox, "n/a",
                    0, len(urls), status="running")

    tif_paths = await download_geotiffs(
        urls, staging, checkpoint, concurrency=m2m_concurrency
    )

    if _cancel_requested:
        log.info("Cancellation requested after downloads — skipping conversion")
        update_progress(output, "m2m", args.bbox, "n/a",
                        len(tif_paths), len(urls), status="cancelled")
        return

    if not tif_paths:
        log.error("No GeoTIFF files were downloaded successfully")
        update_progress(output, "m2m", args.bbox, "n/a",
                        0, len(urls), status="error",
                        error="All GeoTIFF downloads failed")
        sys.exit(1)

    # --- Convert to MBTiles ---
    update_progress(output, "m2m", args.bbox, "n/a",
                    len(tif_paths), len(urls), status="running")

    try:
        convert_geotiffs_to_mbtiles(tif_paths, output)
    except Exception as exc:
        log.error("GDAL conversion failed: %s", exc)
        update_progress(output, "m2m", args.bbox, "n/a",
                        len(tif_paths), len(urls), status="error",
                        error=f"GDAL conversion failed: {exc}")
        sys.exit(1)

    update_progress(output, "m2m", args.bbox, "n/a",
                    len(urls), len(urls), status="completed")
    log.info("M2M pipeline complete: %s", output)
```

#### Step 1.2: Add product name logging in m2m_get_download_urls()

In `scripts/acquire_imagery.py`, inside `m2m_get_download_urls()` (line 616), add logging of ALL available product names before filtering. This is critical for diagnosis if the GeoTIFF filter matches nothing.

Find the download-options loop (lines 627-641) and add logging before the filter:

```python
        options = resp.get("data", [])
        # Log ALL product names for diagnosis before filtering
        all_product_names = set()
        for opt in options:
            pn = opt.get("productName", "")
            if pn:
                all_product_names.add(pn)
        if all_product_names:
            log.info("Available product names: %s", sorted(all_product_names))

        for opt in options:
            if not opt.get("available"):
                continue
            # Prefer GeoTIFF products
            product_name = (opt.get("productName", "") or "").lower()
            if "geotiff" in product_name or "tif" in product_name:
```

#### Step 1.3: Verify the changes

```bash
cd /home/administrator/Code/geographica
python3 -c "import ast; ast.parse(open('scripts/acquire_imagery.py').read()); print('Syntax OK')"
```

**Expected output:**
```
Syntax OK
```

### Pitfalls

- **Do NOT change the function signatures** of `m2m_login`, `m2m_scene_search`, etc. Only modify `run_m2m()` and the logging in `m2m_get_download_urls()`.
- **Do NOT change `_cancel_requested` to a function call.** It is a module-level bool set by the SIGTERM handler. Read it directly as `if _cancel_requested:`.
- **The `update_progress` function uses a `_started_at` attribute** set on it as a function attribute (see line 453 in `run_direct`). You must set `update_progress._started_at` at the start of `run_m2m()` the same way.
- **M2M concurrency must be capped.** The CLI default is `--concurrency 80`, which is fine for direct tile scraping but dangerous for M2M API calls. Cap at 5 for M2M mode. The spec calls this out as a known risk (#6).
- **Logout must happen in a `finally` block.** The existing code already does this (line 730-731). Preserve this pattern so the API key is always invalidated even if scene search or download-options fails.

### Commit

```bash
cd /home/administrator/Code/geographica
git add scripts/acquire_imagery.py
git commit -m "$(cat <<'EOF'
fix: add SIGTERM handling, progress reporting, and error exits to run_m2m()

Three code gaps identified during adversarial review of the M2M pipeline:
1. No _cancel_requested checks — docker stop kills uncleanly
2. No update_progress() calls — admin panel blind to M2M job status
3. Silent exit code 0 on zero scenes/URLs — pipeline state stuck in "running"

Also caps M2M concurrency at 5 (CLI default 80 is for direct tile scraping)
and logs all available product names before GeoTIFF filtering for diagnosis.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Mock-Based Unit Tests

**File to create:** `tests/test_m2m_api.py`
**Type:** New file — mock-based unit tests for M2M functions
**Dependencies:** Task 1 must be completed first (tests verify the fixed code)

### Context

All existing tests are in `/home/administrator/Code/geographica/tests/`. Tests import from `services/search/` or `scripts/` using `sys.path.insert(0, str(Path(__file__).parent.parent / ...))` (see `tests/test_pipeline_orchestrator.py` line 15 for the pattern). These tests use mocked HTTP responses only -- no live API calls, no credentials needed.

### Steps

#### Step 2.1: Create the test file

Create `tests/test_m2m_api.py`:

```python
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
        cancel_calls = [c for c in mock_progress.call_args_list
                        if len(c[0]) > 5 or c[1].get("status") == "cancelled"]
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
```

#### Step 2.2: Run the tests

```bash
cd /home/administrator/Code/geographica
python3 -m pytest tests/test_m2m_api.py -v
```

**Expected output:**
```
tests/test_m2m_api.py::TestM2MLogin::test_login_success PASSED
tests/test_m2m_api.py::TestM2MLogin::test_login_no_api_key PASSED
tests/test_m2m_api.py::TestM2MLogin::test_login_error_code PASSED
tests/test_m2m_api.py::TestM2MLogin::test_login_rate_limited_then_succeeds PASSED
tests/test_m2m_api.py::TestM2MSceneSearch::test_single_page PASSED
tests/test_m2m_api.py::TestM2MSceneSearch::test_multi_page_pagination PASSED
tests/test_m2m_api.py::TestM2MSceneSearch::test_empty_results PASSED
tests/test_m2m_api.py::TestM2MGetDownloadUrls::test_immediate_availability PASSED
tests/test_m2m_api.py::TestM2MGetDownloadUrls::test_polling_until_available PASSED
tests/test_m2m_api.py::TestM2MGetDownloadUrls::test_no_geotiff_products PASSED
tests/test_m2m_api.py::TestM2MGetDownloadUrls::test_deduplicates_urls PASSED
tests/test_m2m_api.py::TestRunM2MCancellation::test_cancel_after_login PASSED
tests/test_m2m_api.py::TestRunM2MProgress::test_progress_on_error PASSED
tests/test_m2m_api.py::TestRunM2MProgress::test_progress_on_no_scenes PASSED
```

If `pytest-asyncio` is not installed:
```bash
pip install pytest-asyncio
```

#### Step 2.3: Verify all existing tests still pass

```bash
cd /home/administrator/Code/geographica
python3 -m pytest tests/ -v
```

### Pitfalls

- **Use `Path(__file__).parent` for sys.path manipulation**, not hardcoded paths. See `tests/test_pipeline_orchestrator.py` line 15 for the established pattern.
- **Use `monkeypatch` for env var changes** (per testing-pitfalls.md item #8). The cancellation tests use `autouse=True` fixture to reset `_cancel_requested`.
- **Do NOT make live API calls.** Every HTTP interaction must be mocked. The test file should run without network access and without any credentials.
- **The mock structure must match aiohttp's context manager pattern.** `session.post()` returns a context manager, not a response directly. The `_make_m2m_response` helper handles this.
- **`asyncio.sleep` must be patched** in the polling test to avoid 10-second waits per poll iteration.
- **`pytest-asyncio` mode:** If using pytest-asyncio >= 0.21, you may need `@pytest.mark.asyncio` on each async test or configure `asyncio_mode = "auto"` in `pyproject.toml`. The explicit decorator is safer.

### Commit

```bash
cd /home/administrator/Code/geographica
git add tests/test_m2m_api.py
git commit -m "$(cat <<'EOF'
test: add mock-based unit tests for M2M API pipeline

14 tests covering login (success, failure, rate limit retry),
scene search pagination, download URL polling, cancellation
handling, and progress reporting. All tests use mocked HTTP
responses — no credentials or network access required.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Environment & Connectivity Check (Phase 0)

**Files:** None modified — this is a verification-only task
**Type:** Pre-flight checks before live API testing
**Dependencies:** None (can run in parallel with Tasks 1-2)

### Steps

#### Step 3.1: Verify GDAL tools in the pipeline container

Build the pipeline image first, then check GDAL availability inside it:

```bash
cd /home/administrator/Code/geographica
docker compose build pipeline
```

**Expected output:** Successful build ending with image tagged `geographica-pipeline`.

```bash
docker compose run --rm --entrypoint "" pipeline gdalinfo --version
docker compose run --rm --entrypoint "" pipeline gdalbuildvrt --version
docker compose run --rm --entrypoint "" pipeline gdal_translate --version
```

**Expected output (each):** Version string like `GDAL 3.x.x, released ...`

If any GDAL tool is missing, the pipeline Dockerfile (`services/pipeline/Dockerfile`) needs `gdal-bin` added to the `apt-get install` list. It is already present (line 4), so this should pass.

#### Step 3.2: Verify outbound connectivity to M2M API

```bash
curl -s -o /dev/null -w '%{http_code}' https://m2m.cr.usgs.gov/api/api/json/stable/
```

**Expected output:** `200` or `401` (both confirm the endpoint is reachable). If you get a connection timeout or DNS failure, check if the AREDN mesh interface is the default route.

#### Step 3.3: Check if AREDN mesh could interfere with routing

```bash
ip route show default
```

**Expected output:** Default route should go through the internet-facing interface (e.g., `eth0` or `wlan0`), NOT through an AREDN mesh interface (typically `wlan1` or a tunnel). If the AREDN interface is the default route:

```bash
# Temporarily check the route to the M2M host
ip route get 152.61.2.100
```

If it routes through the mesh, you need to add a specific route or temporarily disable the mesh interface for testing.

#### Step 3.4: Verify staging directory disk space

```bash
df -h /srv/geographica/data/
```

**Expected output:** At least 10 GB free. NAIP GeoTIFFs are 200MB-1GB each. The small Tucson test bbox should produce 1-3 scenes.

```bash
mkdir -p /srv/geographica/data/m2m_staging
```

#### Step 3.5: Check that env vars are set (without printing values)

```bash
# Verify credentials are set (prints length only, never the value)
echo "USGS_M2M_USERNAME length: ${#USGS_M2M_USERNAME}"
echo "USGS_M2M_TOKEN length: ${#USGS_M2M_TOKEN}"
```

**Expected output:** Both lengths should be > 0. If either is 0, the credentials are not set. Set them:

```bash
export USGS_M2M_USERNAME="<your-username>"
export USGS_M2M_TOKEN="<your-token>"
```

**SECURITY: Never echo the actual values. Never write them to a file. Never commit them.**

### Pitfalls

- **AREDN mesh routing is the most subtle failure mode.** The Pi may have the mesh interface as default route, which means `curl` to external hosts will fail. Check `ip route` before blaming the API.
- **Docker compose build may fail if the Pi's SD card is full.** Check `df -h /` first.
- **The pipeline service has `profiles: ["pipeline"]`** in docker-compose.yml (line 175), meaning it does NOT start with `docker compose up -d`. It must be started explicitly with `docker compose run --rm pipeline ...` or `docker compose --profile pipeline up`.
- **Do NOT store credentials in `.env` files.** The spec is explicit: environment variables only, passed at runtime.

### Commit

No commit for this task — it is verification only.

---

## Task 4: Authentication Smoke Test (Phase 1)

**Files:** None modified — this is a live API test
**Type:** Live verification against USGS M2M API
**Dependencies:** Task 3 (connectivity verified)

### Steps

#### Step 4.1: Run authentication smoke test via Docker

```bash
cd /home/administrator/Code/geographica

docker compose run --rm \
  -e USGS_M2M_USERNAME="$USGS_M2M_USERNAME" \
  -e USGS_M2M_TOKEN="$USGS_M2M_TOKEN" \
  pipeline python3 -c "
import asyncio
import aiohttp
import sys
import os

sys.path.insert(0, '/scripts')
from acquire_imagery import m2m_login, m2m_logout, M2M_API

async def smoke_test():
    username = os.environ['USGS_M2M_USERNAME']
    token = os.environ['USGS_M2M_TOKEN']

    # Log credential format for verification (NOT the values)
    print(f'Username length: {len(username)}')
    print(f'Token length: {len(token)}')
    print(f'Token starts with: {token[:4]}...' if len(token) > 4 else 'Token too short')
    print(f'M2M API base: {M2M_API}')
    print()

    async with aiohttp.ClientSession() as session:
        # Test login
        print('--- Testing login ---')
        api_key = await m2m_login(session, username, token)
        print(f'API key received: {len(api_key)} chars')
        print(f'API key prefix: {api_key[:8]}...')

        # Test logout
        print()
        print('--- Testing logout ---')
        await m2m_logout(session, api_key)
        print('Logout complete')

        # Verify token is invalidated by trying to use it again
        print()
        print('--- Verifying token invalidation ---')
        try:
            from acquire_imagery import m2m_request
            await m2m_request(session, 'dataset-search',
                              {'datasetName': 'naip'}, api_key=api_key)
            print('WARNING: API key still valid after logout!')
        except RuntimeError as e:
            print(f'Good: API key invalidated after logout ({e})')

asyncio.run(smoke_test())
"
```

**Expected output:**
```
Username length: <non-zero>
Token length: <non-zero>
Token starts with: <4 chars>...
M2M API base: https://m2m.cr.usgs.gov/api/api/json/stable/

--- Testing login ---
M2M login successful
API key received: <N> chars
API key prefix: <8 chars>...

--- Testing logout ---
M2M logout successful
Logout complete

--- Verifying token invalidation ---
Good: API key invalidated after logout (...)
```

### Failure modes and remediation

| Symptom | Cause | Fix |
|---------|-------|-----|
| `RuntimeError: M2M login-token failed: ...` | Invalid credentials | Verify ERS account, regenerate token at ers.cr.usgs.gov |
| `RuntimeError: M2M login-token returned no API key` | Account not approved for M2M | Apply at ers.cr.usgs.gov/profile/access (M2M API access is separate from ERS registration) |
| `aiohttp.ClientConnectorError` | Network/DNS failure | Check `curl https://m2m.cr.usgs.gov`, check AREDN routing |
| `asyncio.TimeoutError` | Slow connection or API down | Increase timeout in `m2m_request()`, try again later |
| Token still valid after logout | M2M logout is best-effort | Non-critical — token auto-expires after inactivity |

### Pitfalls

- **Do NOT run this on the host directly** unless GDAL and all Python deps are installed. Use the Docker pipeline container.
- **The `-c` flag with multiline Python works** but be careful with quoting. Use double quotes for the outer shell string, single quotes for Python strings inside.
- **If login fails with HTTP 403,** the ERS account may have M2M access pending. M2M API access requires separate approval from standard ERS registration. Check at `https://ers.cr.usgs.gov/profile/access`.
- **Never log the full API key or token.** Log only the length and a short prefix for debugging.

### Commit

No commit for this task — it is a live test with no code changes.

---

## Task 5: Scene Search Validation (Phase 2)

**Files:** None modified — this is a live API test
**Type:** Live verification of dataset discovery and scene search
**Dependencies:** Task 4 (authentication verified)

### Steps

#### Step 5.1: Run scene search validation via Docker

```bash
cd /home/administrator/Code/geographica

docker compose run --rm \
  -e USGS_M2M_USERNAME="$USGS_M2M_USERNAME" \
  -e USGS_M2M_TOKEN="$USGS_M2M_TOKEN" \
  pipeline python3 -c "
import asyncio
import aiohttp
import json
import sys
import os

sys.path.insert(0, '/scripts')
from acquire_imagery import (
    m2m_login, m2m_logout, m2m_find_naip_dataset,
    m2m_scene_search, m2m_request
)

BBOX = (-110.98, 32.20, -110.90, 32.28)  # Tucson area, ~8x9 km

async def scene_search_test():
    username = os.environ['USGS_M2M_USERNAME']
    token = os.environ['USGS_M2M_TOKEN']

    async with aiohttp.ClientSession() as session:
        api_key = await m2m_login(session, username, token)
        try:
            # Test dataset alias discovery
            print('--- Dataset alias discovery ---')
            dataset_alias = await m2m_find_naip_dataset(session, api_key)
            print(f'Dataset alias: {dataset_alias}')

            # Test scene search
            print()
            print('--- Scene search ---')
            scenes = await m2m_scene_search(
                session, api_key, dataset_alias, BBOX
            )
            print(f'Scenes found: {len(scenes)}')

            if scenes:
                print()
                print('--- First scene details ---')
                scene = scenes[0]
                print(f'  entityId: {scene.get(\"entityId\", \"MISSING\")}')
                print(f'  displayId: {scene.get(\"displayId\", \"MISSING\")}')
                print(f'  acquisitionDate: {scene.get(\"temporalCoverage\", {}).get(\"startDate\", \"MISSING\")}')

                # Also check what keys are present
                print()
                print('--- Scene keys ---')
                print(f'  {sorted(scene.keys())}')

                # Test download-options to see available products
                print()
                print('--- Download options for first scene ---')
                entity_ids = [scene['entityId']]
                resp = await m2m_request(session, 'download-options', {
                    'datasetName': dataset_alias,
                    'entityIds': entity_ids,
                }, api_key=api_key)
                options = resp.get('data', [])
                print(f'  Total options: {len(options)}')
                for opt in options:
                    print(f'  Product: {opt.get(\"productName\", \"?\")} | '
                          f'available: {opt.get(\"available\")} | '
                          f'filesize: {opt.get(\"filesize\", \"?\")}')
            else:
                print('ERROR: No scenes found — check bbox and date range')

        finally:
            await m2m_logout(session, api_key)

asyncio.run(scene_search_test())
"
```

**Expected output:**
```
--- Dataset alias discovery ---
Using NAIP dataset alias: <some_alias>
Dataset alias: <some_alias>

--- Scene search ---
Found <N> NAIP scenes
Scenes found: <N>  (should be >= 1)

--- First scene details ---
  entityId: <string>
  displayId: <string>
  acquisitionDate: <date>

--- Scene keys ---
  [list of keys in scene dict]

--- Download options for first scene ---
  Total options: <N>
  Product: <name> | available: True/False | filesize: <bytes>
  ...
```

**Critical observations to record:**
1. The exact `datasetAlias` returned — if it differs from what the code expects
2. The exact keys present in scene objects — if `entityId` is nested differently
3. The exact `productName` values — if "GeoTIFF" or "tif" are NOT among them, the filter in `m2m_get_download_urls()` will match nothing and the pipeline will fail with "No downloadable GeoTIFF products found"

### Pitfalls

- **The most likely failure point is the product name filter.** USGS may have renamed products (e.g., from "GeoTIFF" to "COG" for Cloud-Optimized GeoTIFF). The spec explicitly warns about this. If no products match, check the logged product names and update the filter in `m2m_get_download_urls()` accordingly.
- **The acquisition date filter is hardcoded to 2020-2025** in `m2m_scene_search()` (line 595-596). If the Tucson area only has older NAIP data, the search will return nothing. Widen the date range if needed.
- **Scene search pagination.** The Tucson bbox is small enough that pagination shouldn't be needed, but verify `totalHits` vs actual results returned.

### Commit

No commit for this task unless code fixes are needed based on API response format.

If fixes are needed:

```bash
cd /home/administrator/Code/geographica
git add scripts/acquire_imagery.py
git commit -m "$(cat <<'EOF'
fix: update M2M product name filter to match current USGS API

<describe what changed, e.g., "USGS now uses 'COG' instead of 'GeoTIFF'">
Discovered during live API validation (Phase 2).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Full Download Pipeline Test (Phase 3)

**Files:** None modified (unless fixes needed) — this is a live pipeline run
**Type:** End-to-end live test of the complete M2M pipeline
**Dependencies:** Tasks 1 (code fixes), 4 (auth verified), 5 (scene search verified)

### Steps

#### Step 6.1: Create staging directory

```bash
mkdir -p /srv/geographica/data/m2m_staging
```

#### Step 6.2: Run the full M2M pipeline with the small Tucson bbox

```bash
cd /home/administrator/Code/geographica

docker compose run --rm \
  -e USGS_M2M_USERNAME="$USGS_M2M_USERNAME" \
  -e USGS_M2M_TOKEN="$USGS_M2M_TOKEN" \
  pipeline python3 /scripts/acquire_imagery.py \
  --mode m2m \
  --bbox "-110.98,32.20,-110.90,32.28" \
  --output /data/test_m2m.mbtiles \
  --staging /data/m2m_staging \
  --concurrency 2
```

**Expected behavior (in order):**
1. Login to M2M API
2. Find NAIP dataset alias
3. Search for scenes covering the Tucson bbox
4. Log all available product names
5. Request downloads for GeoTIFF products
6. Poll until download URLs are available (may take minutes)
7. Download GeoTIFFs to `/data/m2m_staging/`
8. Build VRT from downloaded GeoTIFFs
9. Convert VRT to MBTiles at `/data/test_m2m.mbtiles`
10. Build overview pyramids
11. Logout from M2M API

**Expected output (abbreviated):**
```
M2M login successful
Using NAIP dataset alias: <alias>
Scene search starting at 1 ...
Found <N> NAIP scenes
Available product names: [...]
Fetching download options for <N> scenes
Requesting <N> downloads
Polling download-retrieve ...
  <N> available, <M> still queued — waiting 10s
  ...
Downloading GeoTIFFs: 100%|...
Building VRT from <N> files
Converting VRT to MBTiles: /data/test_m2m.mbtiles
Building overview pyramids
MBTiles written to /data/test_m2m.mbtiles
M2M pipeline complete: /data/test_m2m.mbtiles
```

**Timeout note:** The download polling can take up to 1 hour (360 polls x 10s). For a small bbox with 1-3 scenes, it should complete in under 5 minutes. If it exceeds 15 minutes, check the USGS M2M system status page.

#### Step 6.3: Verify the GeoTIFF downloads

```bash
ls -la /srv/geographica/data/m2m_staging/*.tif
```

**Expected output:** One or more `.tif` files, each 200MB-1GB.

```bash
docker compose run --rm --entrypoint "" pipeline gdalinfo /data/m2m_staging/*.tif | head -30
```

**Expected output:** GeoTIFF metadata including CRS (should be EPSG:26912 or similar UTM zone for Arizona), band count (4 for NAIP RGBI), pixel size.

#### Step 6.4: Verify the MBTiles output

```bash
docker compose run --rm pipeline python3 -c "
import sqlite3
conn = sqlite3.connect('/data/test_m2m.mbtiles')
print('=== Metadata ===')
for row in conn.execute('SELECT name, value FROM metadata'):
    print(f'  {row[0]}: {row[1]}')
print()
tile_count = conn.execute('SELECT COUNT(*) FROM tiles').fetchone()[0]
print(f'Total tiles: {tile_count}')
print()
zoom_levels = conn.execute(
    'SELECT zoom_level, COUNT(*) FROM tiles GROUP BY zoom_level ORDER BY zoom_level'
).fetchall()
print('Tiles per zoom level:')
for z, count in zoom_levels:
    print(f'  z{z}: {count}')
conn.close()
"
```

**Expected output:**
```
=== Metadata ===
  name: usgs_imagery
  format: jpeg
  type: baselayer
  bounds: <bbox values>

Total tiles: <N>  (should be > 0)

Tiles per zoom level:
  z<N>: <count>
  ...
```

#### Step 6.5: Verify pipeline state file was updated

```bash
cat /srv/geographica/data/.pipeline-state.json | python3 -m json.tool
```

**Expected output:** JSON with `"status": "completed"` and M2M-specific fields.

### Pitfalls

- **Use `--staging /data/m2m_staging`**, NOT `/tmp`. Inside the Docker container, `/tmp` is ephemeral and will not persist if the container restarts. `/data/` is the volume mount to `/srv/geographica/data/`.
- **NAIP GeoTIFFs can be very large.** Even for the small test bbox, expect 200MB+ per file. Verify disk space before running (Step 3.4).
- **The download polling loop can be slow.** USGS queues downloads asynchronously. For 1-3 scenes, expect 1-5 minutes. Do not kill the process during polling unless it exceeds 15 minutes.
- **The `--concurrency 2` flag is critical.** The default of 80 is for direct tile scraping. M2M mode should never exceed 5 concurrent requests.
- **If GDAL conversion fails with "ERROR 1: ..."**, check if the GeoTIFFs downloaded are actually GeoTIFFs (USGS sometimes returns HTML error pages as 200 responses). Use `file /data/m2m_staging/*.tif` to check.
- **Download URL expiry risk:** The current code calls `m2m_logout()` before downloading files (inside the `finally` block in Task 1's fix). Download URLs are time-limited but typically valid for hours. For a small test bbox this is not a concern, but for production runs with many files, consider deferring logout until after downloads.

### Commit

No commit unless code fixes are needed. If the pipeline succeeds, document results in Task 7.

If fixes are needed:

```bash
cd /home/administrator/Code/geographica
git add scripts/acquire_imagery.py
git commit -m "$(cat <<'EOF'
fix: <describe what was fixed based on live pipeline test>

Discovered during Phase 3 full pipeline test with Tucson bbox.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Quality Validation & Documentation (Phase 4-5)

**Files to create/modify:**
- `dev/m2m-test-results.md` (new — test results documentation)
- `TODOS.md` (update — mark M2M as validated)

**Type:** Validation and documentation
**Dependencies:** Task 6 (pipeline completed successfully)

### Steps

#### Step 7.1: Visual comparison with existing direct-mode tiles

If the existing `imagery.mbtiles` covers the Tucson area, compare tiles at the same location:

```bash
docker compose run --rm pipeline python3 -c "
import sqlite3
import math

# Helper to convert lat/lon to TMS tile coords
def latlng_to_tile(lat, lon, zoom):
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    # TMS y-flip
    tms_y = n - 1 - y
    return x, tms_y

# Check a tile from M2M output
lat, lon, zoom = 32.24, -110.94, 14
x, tms_y = latlng_to_tile(lat, lon, zoom)
print(f'Checking tile z={zoom} x={x} tms_y={tms_y} (lat={lat} lon={lon})')

for db_name, db_path in [
    ('M2M test', '/data/test_m2m.mbtiles'),
    ('Direct mode', '/data/imagery.mbtiles'),
]:
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            'SELECT length(tile_data) FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?',
            (zoom, x, tms_y)
        ).fetchone()
        if row:
            print(f'  {db_name}: tile found, {row[0]} bytes')
        else:
            print(f'  {db_name}: tile NOT found at this location')
        conn.close()
    except Exception as e:
        print(f'  {db_name}: error — {e}')
"
```

#### Step 7.2: Document results

Create `dev/m2m-test-results.md`:

```bash
ls -d /home/administrator/Code/geographica/dev/ 2>/dev/null || mkdir -p /home/administrator/Code/geographica/dev/
```

Write `dev/m2m-test-results.md` with the following template (fill in actual values during execution):

```markdown
# M2M API Test Results

**Date:** 2026-04-08
**Tester:** Cameron Zucker + Claude
**Spec:** docs/superpowers/specs/2026-04-08-m2m-api-test-plan.md

## Phase 0: Environment

- GDAL version: <fill in>
- Pipeline image: built successfully
- Connectivity to m2m.cr.usgs.gov: confirmed
- Disk space: <fill in> GB free
- AREDN routing: <no conflict / fixed>

## Phase 1: Authentication

- Login: <pass/fail>
- API key format: <length> chars
- Logout: <pass/fail>
- Token invalidation: <confirmed/not confirmed>

## Phase 2: Scene Search

- Dataset alias: <fill in exact string>
- Scenes found: <N> for Tucson bbox
- Scene keys present: <list>
- Available product names: <list all — critical for filter validation>
- GeoTIFF filter matched: <yes/no — if no, what product name should be used?>

## Phase 3: Full Pipeline

- GeoTIFFs downloaded: <N> files, <total size>
- MBTiles created: <yes/no>
- Total tiles: <N>
- Zoom levels: <list>
- Pipeline state: <completed/error>
- Duration: <time>

## Phase 4: Quality

- Resolution comparison: <M2M vs direct>
- Georeferencing: <correct/offset>
- Artifacts: <none/describe>

## API Quirks & Differences

<Document any differences between API documentation and actual behavior>

## Code Changes Required

<List any fixes made during testing, with commit hashes>
```

#### Step 7.3: Update TODOS.md

Find the M2M-related TODO item and mark it as validated:

```bash
cd /home/administrator/Code/geographica
grep -n -i "m2m" TODOS.md
```

Update the relevant line to mark it as completed. The exact edit depends on the current content of TODOS.md.

### Pitfalls

- **The direct-mode imagery.mbtiles may not cover the Tucson area.** The existing direct-mode pipeline was run with the full Western US bbox, but at zoom levels 0-14. The Tucson test area should be covered, but if tiles are missing at z14, try z12.
- **Do NOT create dev/m2m-test-results.md until the tests are actually run.** Fill in real values, not placeholders. A template with unfilled placeholders is worse than no documentation.
- **The dev/ directory is for development artifacts that should be tracked in git** but are not user-facing documentation. Do not put this in `docs/`.

### Commit

```bash
cd /home/administrator/Code/geographica
git add dev/m2m-test-results.md TODOS.md
git commit -m "$(cat <<'EOF'
docs: M2M API validation results and TODO update

Document Phase 0-4 test results from live USGS M2M API validation.
Mark M2M pipeline as validated in TODOS.md.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Dependency Graph

```
Task 1 (fix run_m2m)  ──► Task 2 (unit tests)  ──► [commit both]
                                                         │
Task 3 (env check)  ────► Task 4 (auth smoke)  ──► Task 5 (scene search)  ──► Task 6 (full pipeline)  ──► Task 7 (docs)
```

Tasks 1-2 and Task 3 can run in parallel. Tasks 4-7 are sequential.

## Security Checklist

- [ ] No credentials written to any file (plan, test, config, or code)
- [ ] All live test commands use `$USGS_M2M_USERNAME` and `$USGS_M2M_TOKEN` env vars
- [ ] API key length and prefix logged for debugging, never the full key
- [ ] Token value prefix logged (first 4 chars only) for format verification
- [ ] No `.env` files created or modified
- [ ] Commit messages contain no credentials
- [ ] Test file uses mocked HTTP only, no credentials needed
