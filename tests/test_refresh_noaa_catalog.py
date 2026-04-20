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


import pytest
from aioresponses import aioresponses
from scripts.refresh_noaa_catalog import (
    azure_list_blob_prefixes,
    AzureTruncatedError,
    AZURE_LISTING_BASE,
)


@pytest.mark.asyncio
async def test_azure_listing_single_page_returns_prefixes():
    with aioresponses() as m:
        m.get(
            f"{AZURE_LISTING_BASE}?restype=container&comp=list&delimiter=/&prefix=",
            body=open("tests/fixtures/azure_blob_list/single_page_no_marker.xml").read(),
            headers={"Content-Type": "application/xml"},
        )
        prefixes = await azure_list_blob_prefixes()
        assert "AZ_NAIP_2021_9596/" in prefixes
        assert "UT_NAIP_2021_9601/" in prefixes
        assert "some_other_dir/" in prefixes


@pytest.mark.asyncio
async def test_azure_listing_paginates_via_next_marker():
    with aioresponses() as m:
        m.get(
            f"{AZURE_LISTING_BASE}?restype=container&comp=list&delimiter=/&prefix=",
            body=open("tests/fixtures/azure_blob_list/page1_with_marker.xml").read(),
        )
        m.get(
            f"{AZURE_LISTING_BASE}?restype=container&comp=list&delimiter=/&prefix=&marker=abc123",
            body=open("tests/fixtures/azure_blob_list/page2_final.xml").read(),
        )
        prefixes = await azure_list_blob_prefixes()
        assert "AZ_NAIP_2021_9596/" in prefixes
        assert "CA_NAIP_2022_8888/" in prefixes
        assert "NY_NAIP_2023_7777/" in prefixes
        assert "TX_NAIP_2022_6666/" in prefixes
        assert len(prefixes) == 4


@pytest.mark.asyncio
async def test_azure_listing_network_error_mid_page_raises_truncated():
    with aioresponses() as m:
        m.get(
            f"{AZURE_LISTING_BASE}?restype=container&comp=list&delimiter=/&prefix=",
            body=open("tests/fixtures/azure_blob_list/page1_with_marker.xml").read(),
        )
        m.get(
            f"{AZURE_LISTING_BASE}?restype=container&comp=list&delimiter=/&prefix=&marker=abc123",
            status=503,
        )
        with pytest.raises(AzureTruncatedError, match="page 2"):
            await azure_list_blob_prefixes()
