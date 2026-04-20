"""Tests for the extended /admin/pipeline/noaa/estimate endpoint (Task 19).

Covers:
- New response fields: states, missing, placename, catalog_snapshot,
  intermediate_gb, peak_required_gb.
- Legacy field preservation (tile_count, raw_download_gb, etc.).
- no_catalog fallback when symlink is absent.
- USPS state param backward compat (state=AZ → slug=arizona).
- Bbox mode: cataloged vs. missing state resolution.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_catalog_dir(tmp_path):
    """Build a tmp DATA_DIR with a noaa_naip_catalog.json symlink pointing at a snapshot."""
    snapshots = tmp_path / "noaa_catalog_snapshots"
    snapshots.mkdir()
    snap = snapshots / "2026-04-20T12:00:00Z.json"
    catalog = {
        "snapshot_version": "2026-04-20T12:00:00Z",
        "parser_version": 3,
        "entries": {
            "arizona": {
                "usps": "AZ",
                "year": 2021,
                "dir": "AZ_NAIP_2021_9596",
                "tile_count": 50124,
                "tile_index_url": "https://example.com/az.zip",
                "tile_index_sha256": "aabbcc",
            },
            "utah": {
                "usps": "UT",
                "year": 2021,
                "dir": "UT_NAIP_2021_9601",
                "tile_count": 28451,
                "tile_index_url": "https://example.com/ut.zip",
                "tile_index_sha256": "ddeeff",
            },
        },
    }
    snap.write_text(json.dumps(catalog))
    symlink = tmp_path / "noaa_naip_catalog.json"
    symlink.symlink_to(snap)
    return tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_estimate_returns_new_fields_in_state_mode(fake_catalog_dir):
    """State mode returns all new Task-19 fields alongside all preserved legacy fields."""
    from services.search.main import app
    client = TestClient(app)
    with patch("services.search.main._get_disk_free_gb", return_value=500.0), \
         patch("services.search.main.DATA_DIR", fake_catalog_dir):
        resp = client.get(
            "/admin/pipeline/noaa/estimate",
            params={"bbox": "-114,32,-109,37", "state": "arizona"},
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"

    # New fields
    for field in ("states", "missing", "placename", "catalog_snapshot",
                  "intermediate_gb", "peak_required_gb"):
        assert field in data, f"missing new field: {field}"

    # Legacy fields
    for field in ("tile_count", "raw_download_gb", "final_mbtiles_gb",
                  "staging_peak_gb", "est_hours", "est_days",
                  "per_tile_seconds", "download_concurrency",
                  "download_speed_mbs", "disk_free_gb"):
        assert field in data, f"missing legacy field: {field}"

    assert data["states"] == ["arizona"]
    assert data["missing"] == []           # state IS in catalog
    assert data["placename"] is None       # Task 21 stub
    assert data["intermediate_gb"] == 0.0  # Task 20 stub
    assert data["peak_required_gb"] == 0.0 # Task 20 stub

    # catalog_snapshot must be an absolute path
    assert data["catalog_snapshot"].startswith("/")


def test_estimate_returns_no_catalog_when_symlink_missing(tmp_path):
    """When noaa_naip_catalog.json is absent, return status=no_catalog."""
    from services.search.main import app
    client = TestClient(app)
    with patch("services.search.main._get_disk_free_gb", return_value=500.0), \
         patch("services.search.main.DATA_DIR", tmp_path):
        resp = client.get(
            "/admin/pipeline/noaa/estimate",
            params={"bbox": "-114,32,-109,37", "state": "arizona"},
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "no_catalog"
    assert "refresh_catalog" in data.get("message", ""), (
        f"Expected 'refresh_catalog' hint in message, got: {data.get('message')}"
    )


def test_estimate_usps_state_param_accepted(fake_catalog_dir):
    """Backward-compat: frontend sends state=AZ (USPS), endpoint translates to slug."""
    from services.search.main import app
    client = TestClient(app)
    with patch("services.search.main._get_disk_free_gb", return_value=500.0), \
         patch("services.search.main.DATA_DIR", fake_catalog_dir):
        resp = client.get(
            "/admin/pipeline/noaa/estimate",
            params={"bbox": "-114,32,-109,37", "state": "AZ", "year": 2021},
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["states"] == ["arizona"]


def test_estimate_bbox_mode_returns_cataloged_states(fake_catalog_dir):
    """Bbox spanning AZ+UT+CO+NM: only AZ+UT are in the catalog; CO+NM go to missing[]."""
    from services.search.main import app
    client = TestClient(app)
    # Four-Corners area — overlaps AZ, UT, CO, NM
    with patch("services.search.main._get_disk_free_gb", return_value=500.0), \
         patch("services.search.main.DATA_DIR", fake_catalog_dir):
        resp = client.get(
            "/admin/pipeline/noaa/estimate",
            params={"bbox": "-109.1,36.9,-108.9,37.1"},
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 200
    data = resp.json()

    assert set(data["states"]) == {"arizona", "utah"}
    # CO and NM intersect the Four-Corners bbox but are not in the fake catalog
    assert set(data.get("missing", [])) == {"colorado", "new-mexico"}


def test_estimate_intermediate_and_peak_fields_compute_correctly(fake_catalog_dir):
    """intermediate_gb ≈ raw × 0.3; peak_required_gb = raw + intermediate + final."""
    from services.search.main import app
    client = TestClient(app)
    with patch("services.search.main._get_disk_free_gb", return_value=500.0), \
         patch("services.search.main.DATA_DIR", fake_catalog_dir):
        resp = client.get(
            "/admin/pipeline/noaa/estimate",
            params={"bbox": "-114,32,-109,37", "state": "arizona"},
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    data = resp.json()
    raw = data["raw_download_gb"]
    intermediate = data["intermediate_gb"]
    final = data["final_mbtiles_gb"]
    peak = data["peak_required_gb"]

    # intermediate ≈ 0.3 × raw
    assert abs(intermediate - raw * 0.3) < 0.1, \
        f"intermediate {intermediate} should be ~0.3 × raw {raw}"

    # peak = raw + intermediate + final (within rounding)
    assert abs(peak - (raw + intermediate + final)) < 0.1, \
        f"peak {peak} should equal raw {raw} + intermediate {intermediate} + final {final}"

    # peak > raw (peak must be biggest)
    assert peak > raw, "peak_required should exceed raw"
