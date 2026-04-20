"""NOAA NAIP catalog refresh — validation + (later) Azure listing + P7 mechanics.

Consumed by:
- scripts/acquire_imagery.py (NOAA pipeline path) — reads the catalog only
- services/search/main.py (admin endpoints) — triggers refresh, serves the log
- CI nightly — regenerates config/noaa_naip_catalog.json baseline

Catalog shape — see docs/superpowers/specs/2026-04-20-noaa-naip-conus-expansion-design.md §3.3.
"""
import aiohttp
import xml.etree.ElementTree as ET
from scripts.common.state_bboxes import STATE_BBOXES, SLUG_BY_USPS


class CatalogValidationError(Exception):
    """Raised when a catalog JSON fails structural validation."""


REQUIRED_TOP_KEYS = {
    "snapshot_version", "parser_version", "source_listing_url",
    "validation_status", "entries",
}

REQUIRED_ENTRY_KEYS = {
    "usps", "year", "dir", "tile_count",
    "tile_index_url", "tile_index_sha256",
}


def validate_catalog_structure(catalog: dict) -> None:
    """Raise CatalogValidationError on any malformed catalog.

    Verifies:
    - All REQUIRED_TOP_KEYS present
    - Every entry has all REQUIRED_ENTRY_KEYS
    - Every entry's tile_count > 0
    - Every entry's usps is a known USPS code (present in SLUG_BY_USPS)
    - Every slug (entry key) is present in STATE_BBOXES
    """
    missing_top = REQUIRED_TOP_KEYS - set(catalog)
    if missing_top:
        raise CatalogValidationError(f"missing top-level keys: {sorted(missing_top)}")

    entries = catalog["entries"]
    if not isinstance(entries, dict):
        raise CatalogValidationError("entries must be a dict")

    for slug, entry in entries.items():
        if slug not in STATE_BBOXES:
            raise CatalogValidationError(f"slug {slug!r} not in STATE_BBOXES")
        missing_entry = REQUIRED_ENTRY_KEYS - set(entry)
        if missing_entry:
            raise CatalogValidationError(
                f"entry {slug!r} missing keys: {sorted(missing_entry)}"
            )
        if entry["tile_count"] <= 0:
            raise CatalogValidationError(
                f"entry {slug!r} has tile_count={entry['tile_count']!r} (must be > 0)"
            )
        if entry["usps"] not in SLUG_BY_USPS:
            raise CatalogValidationError(
                f"entry {slug!r} has unknown usps {entry['usps']!r}"
            )


AZURE_LISTING_BASE = "https://coastalimagery.blob.core.windows.net/digitalcoast"


class AzureTruncatedError(Exception):
    """Raised when blob listing terminates before NextMarker is empty."""


async def azure_list_blob_prefixes(
    *,
    timeout_s: float = 30.0,
    max_pages: int = 20,
) -> list[str]:
    """List top-level blob prefixes (directory names with trailing /).

    Uses delimiter-based listing so we only get directory entries, not
    individual blob files. Walks all pages via <NextMarker>. Raises
    AzureTruncatedError if pagination terminates due to network error or
    non-200 response before the final page (distinct from shrinkage,
    which is a successful walk with fewer results than before).
    """
    prefixes: list[str] = []
    marker: str | None = None
    page_num = 0

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_s)) as sess:
        while page_num < max_pages:
            page_num += 1
            params = {"restype": "container", "comp": "list", "delimiter": "/", "prefix": ""}
            if marker:
                params["marker"] = marker
            try:
                async with sess.get(AZURE_LISTING_BASE, params=params) as resp:
                    if resp.status != 200:
                        raise AzureTruncatedError(
                            f"page {page_num} returned HTTP {resp.status}"
                        )
                    body = await resp.text()
            except aiohttp.ClientError as e:
                raise AzureTruncatedError(f"page {page_num} network error: {e}") from e

            root = ET.fromstring(body)
            for bp in root.iter("BlobPrefix"):
                name = bp.findtext("Name")
                if name:
                    prefixes.append(name)

            next_marker_elem = root.find("NextMarker")
            marker = (next_marker_elem.text or "").strip() if next_marker_elem is not None else ""
            if not marker:
                return prefixes

    raise AzureTruncatedError(f"listing did not terminate in {max_pages} pages")
