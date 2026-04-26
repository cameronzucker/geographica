"""Phase 5 integration test: catalog refresh → resolver → unified queue.

Exercises:
 - refresh_catalog() end-to-end against mocked Azure (fixtures)
 - tile-index URL pattern (the one fixed in 4ffd658):
     <base>/<dir>/tileindex_<USPS>_NAIP_<year>.zip
 - resolve_noaa_candidates on a multi-state bbox (Four Corners)
 - build_unified_queue producing the expected (snapshot, usps, fname, url) tuples
 - _init_noaa_checkpoint + _record_tile_complete for the border-quad scenario
   (same filename in two states → two distinct rows via composite PK)

Does NOT exercise: actual GeoTIFF downloads, reprojection, MBTiles merging.
Those are covered by the existing unit tests plus Task 36's pre-merge real-Azure
GitHub Action.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aioresponses import aioresponses

# Make scripts/ importable from the repo root
_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from scripts.refresh_noaa_catalog import (
    AZURE_LISTING_BASE,
    refresh_catalog,
)
from acquire_imagery import (
    _init_noaa_checkpoint,
    _record_tile_complete,
    build_unified_queue,
    pin_catalog_snapshot,
    resolve_noaa_candidates,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent.parent / "fixtures"
_AZURE_FIXTURES = _FIXTURES / "azure_blob_list"
_SHP_FIXTURES = _FIXTURES / "noaa_tile_indexes"

# Catalog directories that map to our AZ + UT synthetic shapefiles
_AZ_DIR = "AZ_NAIP_2021_9596"
_UT_DIR = "UT_NAIP_2021_9601"
_AZ_USPS = "AZ"
_UT_USPS = "UT"

# Four-Corners bbox — intersects AZ, UT, CO, NM; CO+NM will be missing
FOUR_CORNERS_BBOX = "-109.1,36.9,-109.0,37.1"

NOAA_BLOB_BASE = "https://coastalimagery.blob.core.windows.net/digitalcoast"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tile_index_dirs(data_dir: Path) -> None:
    """Copy the synthetic shapefiles into the convention-expected locations.

    The path convention (from _noaa_tile_index_shapefile_path):
        <data_dir>/tile-indexes/<dir>/tileindex_<dir>.shp

    We copy arizona_test.{shp,shx,dbf,prj} → tileindex_AZ_NAIP_2021_9596.{shp,...}
    and utah_test.*                          → tileindex_UT_NAIP_2021_9601.{shp,...}
    """
    for usps, src_stem, dest_dir in [
        (_AZ_USPS, "arizona_test", _AZ_DIR),
        (_UT_USPS, "utah_test", _UT_DIR),
    ]:
        dest_folder = data_dir / "tile-indexes" / dest_dir
        dest_folder.mkdir(parents=True, exist_ok=True)
        dest_stem = dest_folder / f"tileindex_{dest_dir}"
        for ext in (".shp", ".shx", ".dbf", ".prj"):
            src = _SHP_FIXTURES / (src_stem + ext)
            if src.exists():
                shutil.copy2(src, dest_stem.with_suffix(ext))


def _read_xml(name: str) -> str:
    return (_AZURE_FIXTURES / name).read_text(encoding="utf-8")


def _az_tileindex_url() -> str:
    return f"{NOAA_BLOB_BASE}/{_AZ_DIR}/tileindex_{_AZ_USPS}_NAIP_2021.zip"


def _ut_tileindex_url() -> str:
    return f"{NOAA_BLOB_BASE}/{_UT_DIR}/tileindex_{_UT_USPS}_NAIP_2021.zip"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_catalog_builds_az_ut_entries(tmp_path):
    """refresh_catalog() with mocked Azure returns entries for AZ + UT."""
    _make_tile_index_dirs(tmp_path)

    # fake tile-index ZIP in memory (must be a real .zip for zipfile.ZipFile)
    import io, zipfile as _zf

    def _fake_zip(shp_stem: str) -> bytes:
        """Return a zip containing a minimal .shp stub so zipfile.ZipFile won't crash."""
        buf = io.BytesIO()
        with _zf.ZipFile(buf, "w") as z:
            z.writestr(f"tileindex.shp", b"FAKE_SHP_CONTENT")
        return buf.getvalue()

    az_zip = _fake_zip(_AZ_DIR)
    ut_zip = _fake_zip(_UT_DIR)

    # We need to mock:
    #  1. azure_list_blob_prefixes → returns AZ + UT dirs
    #  2. validate_tile_index      → returns {size_bytes, content_md5}
    #  3. fetch_tile_count         → returns synthetic counts
    with (
        patch(
            "scripts.refresh_noaa_catalog.azure_list_blob_prefixes",
            new=AsyncMock(return_value=[f"{_AZ_DIR}/", f"{_UT_DIR}/"]),
        ),
        patch(
            "scripts.refresh_noaa_catalog.validate_tile_index",
            new=AsyncMock(return_value={"size_bytes": 1024, "content_md5": "abc123"}),
        ),
        patch(
            "scripts.refresh_noaa_catalog.fetch_tile_count",
            new=AsyncMock(return_value=10),
        ),
    ):
        result = await refresh_catalog(
            data_dir=tmp_path,
            no_lock=True,
            no_pipeline_check=True,
        )

    assert result["status"] == "ok", f"refresh_catalog returned {result!r}"

    # Snapshot must be written and symlink created
    snap_path = Path(result["snapshot_path"])
    assert snap_path.exists(), f"snapshot not found at {snap_path}"
    symlink = tmp_path / "noaa_naip_catalog.json"
    assert symlink.is_symlink(), "noaa_naip_catalog.json symlink not created"

    catalog = json.loads(snap_path.read_text())
    assert "arizona" in catalog["entries"], "arizona entry missing"
    assert "utah" in catalog["entries"], "utah entry missing"


@pytest.mark.asyncio
async def test_tile_index_url_matches_fixed_pattern(tmp_path):
    """Regression test for 4ffd658: URL must be tileindex_{USPS}_NAIP_{year}.zip.

    The old (broken) pattern was:
        {base}/{dir}/tileindex/tileindex_{dir}.zip   (spurious /tileindex/ subdir
                                                       + uses dir hash suffix)

    The correct pattern (fixed in 4ffd658) is:
        {base}/{dir}/tileindex_{USPS}_NAIP_{year}.zip
    """
    captured_urls: list[str] = []

    async def _capture_validate(url: str):
        captured_urls.append(url)
        return {"size_bytes": 512, "content_md5": "deadbeef"}

    with (
        patch(
            "scripts.refresh_noaa_catalog.azure_list_blob_prefixes",
            new=AsyncMock(return_value=[f"{_AZ_DIR}/"]),
        ),
        patch(
            "scripts.refresh_noaa_catalog.validate_tile_index",
            new=AsyncMock(side_effect=_capture_validate),
        ),
        patch(
            "scripts.refresh_noaa_catalog.fetch_tile_count",
            new=AsyncMock(return_value=5),
        ),
    ):
        result = await refresh_catalog(
            data_dir=tmp_path,
            no_lock=True,
            no_pipeline_check=True,
        )

    assert result["status"] == "ok"
    assert len(captured_urls) == 1

    url = captured_urls[0]
    expected = f"{NOAA_BLOB_BASE}/{_AZ_DIR}/tileindex_{_AZ_USPS}_NAIP_2021.zip"
    assert url == expected, (
        f"tile-index URL mismatch.\n"
        f"  expected: {expected}\n"
        f"  got:      {url}\n"
        "This is a regression guard for the 4ffd658 fix. "
        "Check that scripts/refresh_noaa_catalog.py still constructs "
        "the URL without a /tileindex/ subdirectory and without the "
        "numeric hash suffix from the directory name."
    )

    # Also verify the catalog entry records the correct URL
    snap_path = Path(result["snapshot_path"])
    catalog = json.loads(snap_path.read_text())
    assert catalog["entries"]["arizona"]["tile_index_url"] == expected


@pytest.mark.asyncio
async def test_resolver_four_corners_returns_az_ut_missing_co_nm(tmp_path):
    """resolve_noaa_candidates on Four Corners bbox returns AZ+UT as candidates
    and CO+NM as missing (not in our synthetic catalog).
    """
    _make_tile_index_dirs(tmp_path)

    with (
        patch(
            "scripts.refresh_noaa_catalog.azure_list_blob_prefixes",
            new=AsyncMock(return_value=[f"{_AZ_DIR}/", f"{_UT_DIR}/"]),
        ),
        patch(
            "scripts.refresh_noaa_catalog.validate_tile_index",
            new=AsyncMock(return_value={"size_bytes": 512, "content_md5": "abc"}),
        ),
        patch(
            "scripts.refresh_noaa_catalog.fetch_tile_count",
            new=AsyncMock(return_value=10),
        ),
    ):
        result = await refresh_catalog(
            data_dir=tmp_path,
            no_lock=True,
            no_pipeline_check=True,
        )

    assert result["status"] == "ok"
    snap_path = Path(result["snapshot_path"])
    catalog = json.loads(snap_path.read_text())

    candidates, missing = resolve_noaa_candidates(
        catalog, state=None, bbox=FOUR_CORNERS_BBOX
    )
    candidate_usps = {c["usps"] for c in candidates}
    assert candidate_usps == {"AZ", "UT"}, f"unexpected candidates: {candidate_usps}"
    assert set(missing) == {"colorado", "new-mexico"}, f"unexpected missing: {missing}"


@pytest.mark.asyncio
async def test_build_unified_queue_produces_correct_tuples(tmp_path):
    """build_unified_queue with real shapefiles produces correct QueueItem tuples."""
    _make_tile_index_dirs(tmp_path)

    # Build a minimal catalog directly (don't need full refresh for this test)
    snapshots_dir = tmp_path / "noaa_catalog_snapshots"
    snapshots_dir.mkdir()
    snap_file = snapshots_dir / "20260420T120000Z.json"
    catalog = {
        "snapshot_version": "20260420T120000Z",
        "parser_version": 3,
        "source_listing_url": "https://...",
        "validation_status": "ok",
        "entries": {
            "arizona": {
                "usps": _AZ_USPS, "year": 2021, "dir": _AZ_DIR,
                "tile_count": 10,
                "tile_index_url": _az_tileindex_url(),
                "tile_index_sha256": "abc",
            },
            "utah": {
                "usps": _UT_USPS, "year": 2021, "dir": _UT_DIR,
                "tile_count": 10,
                "tile_index_url": _ut_tileindex_url(),
                "tile_index_sha256": "def",
            },
        },
    }
    snap_file.write_text(json.dumps(catalog))
    symlink = tmp_path / "noaa_naip_catalog.json"
    symlink.symlink_to(snap_file)

    snapshot_path = pin_catalog_snapshot(tmp_path)
    candidates = list(catalog["entries"].values())

    # Use a Four-Corners bbox so AZ and UT tiles near the corner are returned
    # The border quad (-110, 36, -109, 37) intersects both AZ and UT shapefiles
    items = build_unified_queue(candidates, FOUR_CORNERS_BBOX, snapshot_path)

    # Must have at least one item from each state
    az_items = [i for i in items if i[1] == _AZ_USPS]
    ut_items = [i for i in items if i[1] == _UT_USPS]
    assert az_items, "no AZ items in queue"
    assert ut_items, "no UT items in queue"

    # Every item must be a 4-tuple: (snapshot_path, usps, filename, url)
    for item in items:
        assert len(item) == 4
        snap, usps, fname, url = item
        assert snap == snapshot_path
        assert usps in (_AZ_USPS, _UT_USPS)
        assert fname.endswith(".tif")
        assert url.startswith(f"{NOAA_BLOB_BASE}/")
        assert fname in url

    # Border quad must appear in both AZ and UT queues
    az_fnames = {i[2] for i in az_items}
    ut_fnames = {i[2] for i in ut_items}
    assert "m_border.tif" in az_fnames, "border quad missing from AZ queue"
    assert "m_border.tif" in ut_fnames, "border quad missing from UT queue"


def test_checkpoint_border_quad_composite_pk(tmp_path):
    """_init_noaa_checkpoint + _record_tile_complete: border-quad with same
    filename in two states gets TWO distinct rows via composite PK.

    This is the regression guard for Task 14's composite-PK schema.
    """
    db_path = tmp_path / "imagery.mbtiles"
    snap = "/data/snapshots/snap.json"

    _init_noaa_checkpoint(db_path)
    _record_tile_complete(db_path, snap, _AZ_USPS, "m_border.tif")
    _record_tile_complete(db_path, snap, _UT_USPS, "m_border.tif")

    # Both rows must exist — same filename, different usps
    con = sqlite3.connect(str(db_path))
    rows = con.execute(
        "SELECT catalog_snapshot, state_usps, tile_filename "
        "FROM _noaa_checkpoint ORDER BY state_usps"
    ).fetchall()
    con.close()

    assert len(rows) == 2, f"expected 2 rows, got {len(rows)}: {rows}"
    usps_set = {r[1] for r in rows}
    assert usps_set == {_AZ_USPS, _UT_USPS}
    assert all(r[2] == "m_border.tif" for r in rows)


def test_checkpoint_duplicate_is_idempotent(tmp_path):
    """INSERT OR IGNORE: recording the same tile twice should leave one row."""
    db_path = tmp_path / "imagery.mbtiles"
    snap = "/data/snapshots/snap.json"

    _init_noaa_checkpoint(db_path)
    _record_tile_complete(db_path, snap, _AZ_USPS, "m_az_0.tif")
    _record_tile_complete(db_path, snap, _AZ_USPS, "m_az_0.tif")  # duplicate

    con = sqlite3.connect(str(db_path))
    count = con.execute("SELECT COUNT(*) FROM _noaa_checkpoint").fetchone()[0]
    con.close()
    assert count == 1, f"expected 1 row after duplicate insert, got {count}"


@pytest.mark.asyncio
async def test_refresh_catalog_empty_azure_returns_ok_no_entries(tmp_path):
    """Azure returns zero blobs → catalog builds successfully with empty entries.

    Uses the empty_container.xml fixture (Task 34).
    """
    empty_xml = _read_xml("empty_container.xml")

    with aioresponses() as m:
        m.get(
            f"{AZURE_LISTING_BASE}?restype=container&comp=list&delimiter=/&prefix=",
            body=empty_xml,
            headers={"Content-Type": "application/xml"},
        )
        result = await refresh_catalog(
            data_dir=tmp_path,
            no_lock=True,
            no_pipeline_check=True,
        )

    # Empty catalog can't pass validate_catalog_structure (entries ok but parser
    # doesn't raise on empty dict) — but status should be "ok" with 0 entries
    # (validate_catalog_structure only checks *present* entries, not that there
    # are any).
    assert result["status"] == "ok"
    snap_path = Path(result["snapshot_path"])
    catalog = json.loads(snap_path.read_text())
    assert catalog["entries"] == {}


@pytest.mark.asyncio
async def test_refresh_catalog_mixed_valid_invalid_filters_junk(tmp_path):
    """mixed_valid_invalid.xml has 1 real AZ dir + 4 unparseable entries.

    refresh_catalog() should emit only the AZ entry; the junk dirs are silently
    skipped by parse_noaa_dir().

    Uses the mixed_valid_invalid.xml fixture (Task 34).
    """
    mixed_xml = _read_xml("mixed_valid_invalid.xml")

    with (
        aioresponses() as m,
        patch(
            "scripts.refresh_noaa_catalog.validate_tile_index",
            new=AsyncMock(return_value={"size_bytes": 512, "content_md5": "abc"}),
        ),
        patch(
            "scripts.refresh_noaa_catalog.fetch_tile_count",
            new=AsyncMock(return_value=7),
        ),
    ):
        m.get(
            f"{AZURE_LISTING_BASE}?restype=container&comp=list&delimiter=/&prefix=",
            body=mixed_xml,
            headers={"Content-Type": "application/xml"},
        )
        result = await refresh_catalog(
            data_dir=tmp_path,
            no_lock=True,
            no_pipeline_check=True,
        )

    assert result["status"] == "ok"
    snap_path = Path(result["snapshot_path"])
    catalog = json.loads(snap_path.read_text())
    assert "arizona" in catalog["entries"]
    # None of the invalid dirs should appear as entries
    for slug in ("xx", "badformat", "alaska", "some-random-file"):
        assert slug not in catalog["entries"], f"junk slug {slug!r} leaked into entries"


@pytest.mark.asyncio
async def test_pin_catalog_snapshot_after_refresh(tmp_path):
    """After a successful refresh, pin_catalog_snapshot() resolves to the
    snapshot written by refresh_catalog().
    """
    with (
        patch(
            "scripts.refresh_noaa_catalog.azure_list_blob_prefixes",
            new=AsyncMock(return_value=[f"{_AZ_DIR}/"]),
        ),
        patch(
            "scripts.refresh_noaa_catalog.validate_tile_index",
            new=AsyncMock(return_value={"size_bytes": 512, "content_md5": "abc"}),
        ),
        patch(
            "scripts.refresh_noaa_catalog.fetch_tile_count",
            new=AsyncMock(return_value=5),
        ),
    ):
        result = await refresh_catalog(
            data_dir=tmp_path,
            no_lock=True,
            no_pipeline_check=True,
        )

    assert result["status"] == "ok"
    expected_snap = Path(result["snapshot_path"])

    pinned = pin_catalog_snapshot(tmp_path)
    assert pinned == expected_snap.resolve(), (
        f"pin_catalog_snapshot returned {pinned}, "
        f"expected {expected_snap.resolve()}"
    )
