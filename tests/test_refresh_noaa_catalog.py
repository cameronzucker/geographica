import json
import pytest
from scripts.refresh_noaa_catalog import validate_catalog_structure, CatalogValidationError


VALID_CATALOG = {
    "snapshot_version": "2026-04-20T14:30:12Z",
    "parser_version": 3,
    "source_listing_url": "https://...",
    "validation_status": "ok",
    "entries": {
        "arizona": {
            "usps": "AZ", "year": 2021, "dir": "AZ_NAIP_2021_9596",
            "tile_count": 50124,
            "tile_index_url": "https://.../tileindex.zip",
            "tile_index_sha256": "abcd1234",
        }
    }
}


def test_valid_catalog_passes():
    validate_catalog_structure(VALID_CATALOG)  # no exception


def test_missing_entries_field_fails():
    bad = {k: v for k, v in VALID_CATALOG.items() if k != "entries"}
    with pytest.raises(CatalogValidationError, match="entries"):
        validate_catalog_structure(bad)


def test_entry_missing_usps_fails():
    bad = json.loads(json.dumps(VALID_CATALOG))
    del bad["entries"]["arizona"]["usps"]
    with pytest.raises(CatalogValidationError, match="usps"):
        validate_catalog_structure(bad)


def test_entry_with_tile_count_zero_fails():
    bad = json.loads(json.dumps(VALID_CATALOG))
    bad["entries"]["arizona"]["tile_count"] = 0
    with pytest.raises(CatalogValidationError, match="tile_count"):
        validate_catalog_structure(bad)


def test_entry_with_unknown_usps_fails():
    bad = json.loads(json.dumps(VALID_CATALOG))
    bad["entries"]["arizona"]["usps"] = "ZZ"
    with pytest.raises(CatalogValidationError, match="ZZ"):
        validate_catalog_structure(bad)


def test_entry_slug_not_in_state_bboxes_fails():
    bad = json.loads(json.dumps(VALID_CATALOG))
    bad["entries"]["atlantis"] = bad["entries"].pop("arizona")
    with pytest.raises(CatalogValidationError, match="atlantis"):
        validate_catalog_structure(bad)
