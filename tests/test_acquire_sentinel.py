"""Tests for acquire_sentinel.py — Sentinel-2 pipeline with mocked HTTP.

All network calls are mocked — no real STAC API or Copernicus auth calls.
"""

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure scripts/ is importable
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from scripts.acquire_sentinel import (
    CopernicusAuth,
    build_stac_query,
    compute_chunks,
    get_download_url,
    load_checkpoint,
    parse_bbox,
    save_checkpoint,
    stac_search,
)
from scripts.pipeline_security import sanitize_scene_id, validate_file_header


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scene(scene_id: str, cloud: float, url: str = "https://example.com/scene.tif"):
    """Build a minimal STAC feature dict."""
    return {
        "id": scene_id,
        "properties": {"eo:cloud_cover": cloud},
        "assets": {"visual": {"href": url}},
    }


def _make_stac_response(features, next_url=None):
    """Build a STAC search response dict."""
    links = []
    if next_url:
        links.append({"rel": "next", "href": next_url})
    return {"features": features, "links": links}


class FakeResponse:
    """Minimal aiohttp response stand-in for async context manager."""

    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def json(self):
        return self._payload

    async def text(self):
        return json.dumps(self._payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# 1. STAC query construction
# ---------------------------------------------------------------------------

class TestStacQueryConstruction:
    def test_bbox_in_query(self):
        q = build_stac_query((-112.0, 33.0, -111.0, 34.0), "2026-01-01", "2026-04-01", 20)
        assert q["bbox"] == [-112.0, 33.0, -111.0, 34.0]

    def test_datetime_range(self):
        q = build_stac_query((-112.0, 33.0, -111.0, 34.0), "2026-01-01", "2026-04-01", 20)
        assert q["datetime"] == "2026-01-01/2026-04-01"

    def test_cloud_cover_filter(self):
        q = build_stac_query((-112.0, 33.0, -111.0, 34.0), "2026-01-01", "2026-04-01", 15)
        f = q["filter"]
        assert f["op"] == "<="
        assert f["args"][0] == {"property": "eo:cloud_cover"}
        assert f["args"][1] == 15

    def test_collection(self):
        q = build_stac_query((-112.0, 33.0, -111.0, 34.0), "2026-01-01", "2026-04-01", 20)
        assert q["collections"] == ["sentinel-2-l2a"]

    def test_limit(self):
        q = build_stac_query((-112.0, 33.0, -111.0, 34.0), "2026-01-01", "2026-04-01", 20)
        assert q["limit"] == 500


# ---------------------------------------------------------------------------
# 2. Scene filtering by cloud cover
# ---------------------------------------------------------------------------

class TestSceneFiltering:
    def test_filters_by_max_cloud(self):
        """Given scenes at various cloud %, only those <= max_cloud are kept."""
        scenes_raw = [
            _make_scene("clear", 5),
            _make_scene("partly", 20),
            _make_scene("cloudy", 50),
            _make_scene("overcast", 90),
        ]
        max_cloud = 20

        # stac_search does client-side filtering too
        response = _make_stac_response(scenes_raw)

        session = MagicMock()
        session.post = MagicMock(return_value=FakeResponse(200, response))

        result = asyncio.get_event_loop().run_until_complete(
            stac_search(session, (-112, 33, -111, 34), "2026-01-01", "2026-04-01", max_cloud)
        )

        ids = [s["id"] for s in result]
        assert "clear" in ids
        assert "partly" in ids
        assert "cloudy" not in ids
        assert "overcast" not in ids


# ---------------------------------------------------------------------------
# 3. Pagination cap
# ---------------------------------------------------------------------------

class TestPaginationCap:
    def test_stops_after_100_pages(self):
        """Search stops at 100 pages even if next links keep coming."""
        page_count = 0

        def make_response(*args, **kwargs):
            nonlocal page_count
            page_count += 1
            scene = _make_scene(f"scene_{page_count}", 10)
            # Always provide a next link to simulate infinite pagination
            return FakeResponse(200, _make_stac_response(
                [scene], next_url="https://example.com/next"
            ))

        session = MagicMock()
        session.post = MagicMock(side_effect=make_response)
        session.get = MagicMock(side_effect=make_response)

        result = asyncio.get_event_loop().run_until_complete(
            stac_search(session, (-112, 33, -111, 34), "2026-01-01", "2026-04-01", 20)
        )

        # Should have stopped at MAX_PAGES (100) — first page is POST, rest are GET
        # Total pages = 100 (1 POST + 99 GETs = 100 iterations)
        assert page_count <= 101  # allow minor off-by-one
        assert len(result) <= 101


# ---------------------------------------------------------------------------
# 4. OAuth2 token refresh
# ---------------------------------------------------------------------------

class TestOAuth2TokenRefresh:
    def test_refresh_called_when_expiring(self):
        """If token expires within 60s, ensure_valid_token calls refresh."""
        auth = CopernicusAuth("user", "pass")
        auth.access_token = "old_token"
        auth.refresh_token = "refresh_tok"
        # Set expiry to 30s from now (within the 60s buffer)
        auth.expires_at = time.monotonic() + 30

        new_payload = {
            "access_token": "new_token",
            "refresh_token": "new_refresh",
            "expires_in": 600,
        }

        session = MagicMock()
        session.post = MagicMock(return_value=FakeResponse(200, new_payload))

        token = asyncio.get_event_loop().run_until_complete(
            auth.ensure_valid_token(session)
        )

        assert token == "new_token"
        assert auth.access_token == "new_token"
        session.post.assert_called_once()

    def test_no_refresh_when_valid(self):
        """If token is still valid, return it without refresh."""
        auth = CopernicusAuth("user", "pass")
        auth.access_token = "valid_token"
        auth.expires_at = time.monotonic() + 300  # 5 minutes left

        session = MagicMock()

        token = asyncio.get_event_loop().run_until_complete(
            auth.ensure_valid_token(session)
        )

        assert token == "valid_token"
        session.post.assert_not_called()

    def test_reauthenticate_on_refresh_failure(self):
        """If refresh returns non-200, fall back to full re-auth."""
        auth = CopernicusAuth("user", "pass")
        auth.access_token = "old_token"
        auth.refresh_token = "bad_refresh"
        auth.expires_at = time.monotonic() + 10  # expiring soon

        call_count = 0

        def post_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: refresh fails
                return FakeResponse(401, {"error": "invalid_grant"})
            else:
                # Second call: password auth succeeds
                return FakeResponse(200, {
                    "access_token": "fresh_token",
                    "refresh_token": "fresh_refresh",
                    "expires_in": 600,
                })

        session = MagicMock()
        session.post = MagicMock(side_effect=post_side_effect)

        token = asyncio.get_event_loop().run_until_complete(
            auth.ensure_valid_token(session)
        )

        assert token == "fresh_token"
        assert call_count == 2


# ---------------------------------------------------------------------------
# 5. Filename sanitization
# ---------------------------------------------------------------------------

class TestFilenameSanitization:
    def test_standard_scene_id(self):
        scene_id = "S2B_MSIL2A_20260401T183921_N0511_R070_T11SPA"
        expected = f"sentinel_{sanitize_scene_id(scene_id)}.tif"
        assert expected == "sentinel_S2B_MSIL2A_20260401T183921_N0511_R070_T11SPA.tif"

    def test_scene_id_with_dots_and_slashes(self):
        scene_id = "S2B.MSIL2A/20260401"
        sanitized = sanitize_scene_id(scene_id)
        filename = f"sentinel_{sanitized}.tif"
        # No dots or slashes in the sanitized part
        assert "/" not in sanitized
        assert ".." not in sanitized
        assert filename.startswith("sentinel_")
        assert filename.endswith(".tif")

    def test_malicious_scene_id(self):
        scene_id = "../../../etc/passwd"
        sanitized = sanitize_scene_id(scene_id)
        filename = f"sentinel_{sanitized}.tif"
        assert ".." not in sanitized
        assert "/" not in sanitized


# ---------------------------------------------------------------------------
# 6. File validation (magic bytes)
# ---------------------------------------------------------------------------

class TestFileValidation:
    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def test_valid_geotiff_accepted(self):
        f = self.tmpdir / "valid.tif"
        f.write_bytes(b"II\x2a\x00" + b"\x00" * 100)
        assert validate_file_header(f, "geotiff") is True

    def test_invalid_file_rejected(self):
        f = self.tmpdir / "bad.tif"
        f.write_bytes(b"<!DOCTYPE html><html>not a tiff</html>")
        assert validate_file_header(f, "geotiff") is False

    def test_empty_file_rejected(self):
        f = self.tmpdir / "empty.tif"
        f.write_bytes(b"")
        assert validate_file_header(f, "geotiff") is False

    def test_big_endian_tiff_accepted(self):
        f = self.tmpdir / "be.tif"
        f.write_bytes(b"MM\x00\x2a" + b"\x00" * 100)
        assert validate_file_header(f, "geotiff") is True


# ---------------------------------------------------------------------------
# 7. Search checkpoint
# ---------------------------------------------------------------------------

class TestSearchCheckpoint:
    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def test_save_and_load_checkpoint(self):
        scenes = [_make_scene("S1", 10), _make_scene("S2", 15)]
        save_checkpoint(self.tmpdir, scenes)

        loaded = load_checkpoint(self.tmpdir)
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[0]["id"] == "S1"

    def test_expired_checkpoint_returns_none(self):
        scenes = [_make_scene("S1", 10)]
        save_checkpoint(self.tmpdir, scenes)

        # Set file mtime to 25 hours ago
        cp = self.tmpdir / "searched_scenes.json"
        old_time = time.time() - 25 * 3600
        os.utime(str(cp), (old_time, old_time))

        loaded = load_checkpoint(self.tmpdir)
        assert loaded is None

    def test_missing_checkpoint_returns_none(self):
        loaded = load_checkpoint(self.tmpdir)
        assert loaded is None

    def test_corrupt_checkpoint_returns_none(self):
        cp = self.tmpdir / "searched_scenes.json"
        cp.write_text("not valid json {{{")
        loaded = load_checkpoint(self.tmpdir)
        assert loaded is None


# ---------------------------------------------------------------------------
# 8. Spatial chunking
# ---------------------------------------------------------------------------

class TestSpatialChunking:
    def test_small_bbox_no_chunking(self):
        """A 1x1 degree bbox should not be chunked."""
        chunks = compute_chunks((-112.0, 33.0, -111.0, 34.0))
        assert len(chunks) == 1
        assert chunks[0] == (-112.0, 33.0, -111.0, 34.0)

    def test_exactly_2x2_no_chunking(self):
        """A 2x2 degree bbox should not be chunked."""
        chunks = compute_chunks((-112.0, 33.0, -110.0, 35.0))
        assert len(chunks) == 1

    def test_10x10_splits_into_chunks(self):
        """A 10x10 degree bbox should be split into 2x2 degree chunks."""
        chunks = compute_chunks((-120.0, 30.0, -110.0, 40.0))
        # 10/2 = 5 cols, 10/2 = 5 rows => 25 chunks
        assert len(chunks) == 25

    def test_chunks_cover_full_bbox(self):
        """All chunks together should cover the original bbox."""
        bbox = (-120.0, 30.0, -110.0, 40.0)
        chunks = compute_chunks(bbox)

        # Verify coverage: min west, min south, max east, max north
        min_west = min(c[0] for c in chunks)
        min_south = min(c[1] for c in chunks)
        max_east = max(c[2] for c in chunks)
        max_north = max(c[3] for c in chunks)

        assert min_west == bbox[0]
        assert min_south == bbox[1]
        assert max_east == bbox[2]
        assert max_north == bbox[3]

    def test_non_even_bbox_still_covered(self):
        """A 5x3 degree bbox is fully covered by chunks."""
        bbox = (-115.0, 33.0, -110.0, 36.0)
        chunks = compute_chunks(bbox)
        # 5/2 = 3 cols (2+2+1), 3/2 = 2 rows (2+1) => 6 chunks
        assert len(chunks) == 6

        max_east = max(c[2] for c in chunks)
        max_north = max(c[3] for c in chunks)
        assert max_east == -110.0
        assert max_north == 36.0

    def test_all_chunks_are_at_most_2x2(self):
        """No chunk should exceed 2x2 degrees."""
        chunks = compute_chunks((-120.0, 30.0, -110.0, 40.0))
        for c in chunks:
            width = c[2] - c[0]
            height = c[3] - c[1]
            assert width <= 2.0 + 1e-9
            assert height <= 2.0 + 1e-9
