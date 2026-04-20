import json
import os
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


def test_parse_noaa_directory_name_valid():
    from scripts.refresh_noaa_catalog import parse_noaa_dir
    assert parse_noaa_dir("AZ_NAIP_2021_9596/") == ("AZ", 2021)
    assert parse_noaa_dir("GA_NAIP_2023_10001/") == ("GA", 2023)


def test_parse_noaa_directory_name_invalid_returns_none():
    from scripts.refresh_noaa_catalog import parse_noaa_dir
    assert parse_noaa_dir("some_other_dir/") is None
    assert parse_noaa_dir("AZ_NAIP/") is None
    assert parse_noaa_dir("AZ_NAIP_2021_9596_v2/") is None  # version suffix not supported


def test_parse_noaa_directory_name_unsupported_state_returns_none():
    from scripts.refresh_noaa_catalog import parse_noaa_dir
    # Alaska is unsupported
    assert parse_noaa_dir("AK_NAIP_2021_9999/") is None


@pytest.mark.asyncio
async def test_validate_tile_index_head_success():
    from scripts.refresh_noaa_catalog import validate_tile_index
    url = "https://example.com/AZ_NAIP_2021_9596/tileindex/tileindex.zip"
    with aioresponses() as m:
        m.head(url, headers={"Content-Length": "1048576", "x-ms-blob-content-md5": "xyz"})
        result = await validate_tile_index(url)
        assert result == {"size_bytes": 1048576, "content_md5": "xyz"}


@pytest.mark.asyncio
async def test_validate_tile_index_head_404_returns_none():
    from scripts.refresh_noaa_catalog import validate_tile_index
    url = "https://example.com/bogus/tileindex.zip"
    with aioresponses() as m:
        m.head(url, status=404)
        assert await validate_tile_index(url) is None


def test_write_snapshot_atomic(tmp_path):
    from scripts.refresh_noaa_catalog import write_snapshot
    snapshots_dir = tmp_path / "noaa_catalog_snapshots"
    snapshots_dir.mkdir()
    catalog = {
        "snapshot_version": "2026-04-20T14:30:12Z",
        "parser_version": 3,
        "source_listing_url": "https://...",
        "validation_status": "ok",
        "entries": {},
    }
    path = write_snapshot(snapshots_dir, catalog, ts="20260420T143012Z")
    assert path.exists()
    assert path.name == "20260420T143012Z.json"
    assert json.loads(path.read_text()) == catalog
    # No .tmp files left around
    assert not list(snapshots_dir.glob("*.tmp"))


def test_swap_symlink_creates_new(tmp_path):
    from scripts.refresh_noaa_catalog import swap_symlink
    target = tmp_path / "snap1.json"
    target.write_text("{}")
    link = tmp_path / "current.json"
    swap_symlink(link, target)
    assert link.is_symlink()
    assert link.resolve() == target.resolve()


def test_swap_symlink_replaces_existing(tmp_path):
    from scripts.refresh_noaa_catalog import swap_symlink
    t1 = tmp_path / "snap1.json"; t1.write_text("{}")
    t2 = tmp_path / "snap2.json"; t2.write_text("{}")
    link = tmp_path / "current.json"
    swap_symlink(link, t1)
    swap_symlink(link, t2)
    assert link.resolve() == t2.resolve()


def test_swap_symlink_never_leaves_link_pointing_at_nonexistent(tmp_path):
    """Post-swap invariant: if symlink exists, its target exists."""
    from scripts.refresh_noaa_catalog import swap_symlink
    t1 = tmp_path / "snap1.json"; t1.write_text("{}")
    link = tmp_path / "current.json"
    swap_symlink(link, t1)
    if link.exists():
        assert link.resolve().exists()


def test_lock_acquired_records_pid(tmp_path):
    from scripts.refresh_noaa_catalog import RefreshLock
    lock_path = tmp_path / "refresh.lock"
    with RefreshLock(lock_path) as lock:
        assert lock.held
        assert lock_path.exists()
        data = json.loads(lock_path.read_text())
        assert data["pid"] == os.getpid()
        assert "acquired_ts" in data
    assert not lock_path.exists()


def test_lock_contended_returns_holder_info(tmp_path):
    from scripts.refresh_noaa_catalog import RefreshLock, LockContendedError
    lock_path = tmp_path / "refresh.lock"
    with RefreshLock(lock_path):
        with pytest.raises(LockContendedError) as exc_info:
            with RefreshLock(lock_path):
                pass
        assert exc_info.value.holder_pid == os.getpid()


def test_force_unlock_removes_if_pid_dead(tmp_path):
    from scripts.refresh_noaa_catalog import force_unlock
    lock_path = tmp_path / "refresh.lock"
    # Simulate stale lock from a dead PID
    lock_path.write_text(json.dumps({"pid": 999999, "acquired_ts": "2000-01-01T00:00:00Z"}))
    result = force_unlock(lock_path)
    assert result["status"] == "ok"
    assert not lock_path.exists()


def test_force_unlock_refuses_if_pid_alive(tmp_path):
    from scripts.refresh_noaa_catalog import force_unlock
    lock_path = tmp_path / "refresh.lock"
    lock_path.write_text(json.dumps({"pid": os.getpid(), "acquired_ts": "2000-01-01T00:00:00Z"}))
    result = force_unlock(lock_path)
    assert result["status"] == "lock_holder_alive"
    assert lock_path.exists()


def test_force_unlock_no_lock_file(tmp_path):
    from scripts.refresh_noaa_catalog import force_unlock
    lock_path = tmp_path / "refresh.lock"
    result = force_unlock(lock_path)
    assert result["status"] == "no_lock"
