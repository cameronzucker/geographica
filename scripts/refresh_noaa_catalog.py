"""NOAA NAIP catalog refresh — validation + (later) Azure listing + P7 mechanics.

Consumed by:
- scripts/acquire_imagery.py (NOAA pipeline path) — reads the catalog only
- services/search/main.py (admin endpoints) — triggers refresh, serves the log
- CI nightly — regenerates config/noaa_naip_catalog.json baseline

Catalog shape — see docs/superpowers/specs/2026-04-20-noaa-naip-conus-expansion-design.md §3.3.
"""
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
