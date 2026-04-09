"""Integration tests for geocode_place() — requires local Nominatim container."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))

import asyncio
import pytest
import httpx

NOMINATIM_URL = "http://localhost:8092"


@pytest.fixture(autouse=True)
def check_nominatim():
    """Fail immediately if Nominatim container is not responding."""
    try:
        resp = httpx.get(f"{NOMINATIM_URL}/status", timeout=2.0)
        resp.raise_for_status()
    except Exception:
        pytest.fail("Nominatim container not responding at " + NOMINATIM_URL)


@pytest.fixture(autouse=True)
def init_and_clear_geocode():
    """Initialize geocode module with HTTP client and clear cache between tests."""
    from geocode import init_geocode, clear_cache
    client = httpx.AsyncClient()
    init_geocode(client, NOMINATIM_URL)
    clear_cache()
    yield
    clear_cache()


class TestGeocodePlaceBasic:
    def test_geocode_flagstaff(self):
        from geocode import geocode_place
        result = asyncio.get_event_loop().run_until_complete(geocode_place("flagstaff"))
        assert result is not None
        assert abs(result["lat"] - 35.2) < 0.5
        assert abs(result["lon"] - (-111.65)) < 0.5
        assert "bbox" in result

    def test_geocode_phoenix(self):
        from geocode import geocode_place
        result = asyncio.get_event_loop().run_until_complete(geocode_place("phoenix"))
        assert result is not None
        assert abs(result["lat"] - 33.45) < 0.5
        assert abs(result["lon"] - (-112.07)) < 0.5

    def test_geocode_nonexistent(self):
        from geocode import geocode_place
        result = asyncio.get_event_loop().run_until_complete(
            geocode_place("xyzzy_nonexistent_place_12345")
        )
        assert result is None

    def test_geocode_zip_code(self):
        """Zip code geocoding — local Nominatim may lack postal data."""
        from geocode import geocode_place
        result = asyncio.get_event_loop().run_until_complete(geocode_place("85001"))
        # Local Nominatim with western US PBF may not have postal code data.
        # If it resolves, verify coordinates are in the Phoenix area.
        if result is not None:
            assert abs(result["lat"] - 33.45) < 0.5


class TestGeocodeBboxFormat:
    def test_bbox_is_internal_format(self):
        from geocode import geocode_place
        result = asyncio.get_event_loop().run_until_complete(geocode_place("flagstaff"))
        assert result is not None
        parts = result["bbox"].split(",")
        assert len(parts) == 4
        lon_min, lat_min, lon_max, lat_max = (float(p) for p in parts)
        assert lon_min < 0
        assert lon_max < 0
        assert lat_min > 0
        assert lat_max > 0
        assert lon_min <= lon_max
        assert lat_min <= lat_max


class TestGeocodeCache:
    def test_cache_returns_same_result(self):
        from geocode import geocode_place
        loop = asyncio.get_event_loop()
        r1 = loop.run_until_complete(geocode_place("flagstaff"))
        r2 = loop.run_until_complete(geocode_place("flagstaff"))
        assert r1 == r2

    def test_cache_is_case_insensitive(self):
        from geocode import geocode_place
        loop = asyncio.get_event_loop()
        r1 = loop.run_until_complete(geocode_place("Flagstaff"))
        r2 = loop.run_until_complete(geocode_place("flagstaff"))
        assert r1 == r2

    def test_cache_clear_works(self):
        from geocode import geocode_place, clear_cache, _geocode_cache
        loop = asyncio.get_event_loop()
        loop.run_until_complete(geocode_place("flagstaff"))
        assert len(_geocode_cache) > 0
        clear_cache()
        assert len(_geocode_cache) == 0


class TestGeocodeBias:
    def test_bias_toward_user_position(self):
        from geocode import geocode_place
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            geocode_place("mesa", bias_lat=33.45, bias_lon=-112.07)
        )
        assert result is not None
        assert abs(result["lat"] - 33.4) < 0.5
        assert abs(result["lon"] - (-111.8)) < 0.5


class TestGeocodeTimeout:
    def test_timeout_returns_none(self, monkeypatch):
        from geocode import geocode_place, clear_cache
        clear_cache()

        async def slow_get(self, *args, **kwargs):
            raise httpx.TimeoutException("simulated timeout")

        monkeypatch.setattr(httpx.AsyncClient, "get", slow_get)

        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(geocode_place("flagstaff"))
        assert result is None
