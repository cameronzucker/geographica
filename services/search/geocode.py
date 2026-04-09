"""Async geocode helper with position-biased caching.

Geocodes place names via local Nominatim. Separate from _query_nominatim()
which does bounded POI search (bounded=1). This function does ranking-biased
geocoding (bounded=0 or omitted).
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Async-safe cache: dict + lock.
# Key is (normalized_name, lat_bucket, lon_bucket).
# DO NOT use functools.lru_cache — it caches coroutine objects, not resolved values.
_geocode_cache: dict[tuple[str, int, int], Optional[dict]] = {}
_geocode_lock = asyncio.Lock()

# Module-level HTTP client and URL — set by init_geocode()
_http_client = None
_nominatim_url = None


def init_geocode(http_client, nominatim_url: str):
    """Initialize the geocode module with shared HTTP client and Nominatim URL."""
    global _http_client, _nominatim_url
    _http_client = http_client
    _nominatim_url = nominatim_url


def clear_cache():
    """Clear the geocode cache. Used by tests."""
    _geocode_cache.clear()


async def geocode_place(
    place_name: str,
    bias_lat: float = None,
    bias_lon: float = None,
) -> Optional[dict]:
    """Geocode a place name via local Nominatim.

    Returns {"lat": float, "lon": float, "bbox": str} or None.
    bbox is in internal format: "lon_min,lat_min,lon_max,lat_max".

    Args:
        place_name: City, town, zip code, or other place name.
        bias_lat: User latitude for ranking bias (not hard filtering).
        bias_lon: User longitude for ranking bias.
    """
    # Cache key: normalized name + coarse 1-degree position bucket
    bias_bucket = (round(bias_lat or 0), round(bias_lon or 0))
    cache_key = (place_name.lower().strip(), bias_bucket[0], bias_bucket[1])

    async with _geocode_lock:
        if cache_key in _geocode_cache:
            return _geocode_cache[cache_key]

    # Build Nominatim request
    params: dict = {"q": place_name, "limit": 1, "format": "jsonv2"}
    if bias_lat is not None and bias_lon is not None:
        # Ranking bias (NOT bounded) — Nominatim prefers results in this box
        params["viewbox"] = f"{bias_lon - 2},{bias_lat + 2},{bias_lon + 2},{bias_lat - 2}"
        # Do NOT set bounded=1 — we want ranking bias, not hard filtering

    result = None
    try:
        resp = await _http_client.get(
            f"{_nominatim_url}/search", params=params, timeout=1.0
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            item = data[0]
            bb = item["boundingbox"]  # [south_lat, north_lat, west_lon, east_lon] as strings
            # Convert to internal format: lon_min,lat_min,lon_max,lat_max
            lat_min = float(bb[0])
            lat_max = float(bb[1])
            lon_min = float(bb[2])
            lon_max = float(bb[3])
            # Pad by ~2km (0.02 degrees)
            bbox_str = (
                f"{lon_min - 0.02},{lat_min - 0.02},"
                f"{lon_max + 0.02},{lat_max + 0.02}"
            )
            result = {
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "bbox": bbox_str,
            }
        else:
            logger.info("Geocode found no results for '%s'", place_name)
    except Exception as exc:
        logger.warning("Geocode failed for '%s': %s", place_name, exc)

    async with _geocode_lock:
        _geocode_cache[cache_key] = result

    return result
