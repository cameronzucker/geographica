"""Tests for the extended /admin/pipeline/noaa/estimate endpoint (Task 19)
and the catalog management endpoints (Tasks 22–25).

Covers:
- New response fields: states, missing, placename, catalog_snapshot,
  intermediate_gb, peak_required_gb.
- Legacy field preservation (tile_count, raw_download_gb, etc.).
- no_catalog fallback when symlink is absent.
- USPS state param backward compat (state=AZ → slug=arizona).
- Bbox mode: cataloged vs. missing state resolution.
- POST /admin/pipeline/noaa/refresh (Task 22)
- POST /admin/pipeline/noaa/rollback (Task 23)
- POST /admin/pipeline/noaa/force-unlock (Task 24)
- GET  /admin/pipeline/noaa/refresh-log (Task 25)
"""
import json
import os
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
    # Task 20: intermediate_gb = raw × 0.3; peak = raw + intermediate + final
    assert data["intermediate_gb"] > 0
    assert data["peak_required_gb"] > data["raw_download_gb"]

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


def test_estimate_placename_multi_state_format(fake_catalog_dir):
    """Bbox spanning AZ + UT (both cataloged) → 'Coverage area across AZ, UT'."""
    from services.search.main import app
    client = TestClient(app)
    with patch("services.search.main._get_disk_free_gb", return_value=500.0), \
         patch("services.search.main.DATA_DIR", fake_catalog_dir):
        resp = client.get(
            "/admin/pipeline/noaa/estimate",
            params={"bbox": "-114,37,-109,40"},  # AZ + UT
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    data = resp.json()
    assert data["placename"] is not None
    assert data["placename"].startswith("Coverage area across")
    # USPS codes appear
    assert "AZ" in data["placename"]
    assert "UT" in data["placename"]


def test_estimate_placename_wide_bbox_uses_state_list(fake_catalog_dir):
    """Bbox width > 5° → state-list placename (no Nominatim call)."""
    from services.search.main import app
    client = TestClient(app)
    with patch("services.search.main._get_disk_free_gb", return_value=500.0), \
         patch("services.search.main.DATA_DIR", fake_catalog_dir):
        resp = client.get(
            "/admin/pipeline/noaa/estimate",
            params={"bbox": "-114,32,-108,37", "state": "arizona"},  # 6° wide
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    data = resp.json()
    # Width 6° > 5° threshold → multi-state placename even in state mode
    assert data["placename"] is not None
    assert data["placename"].startswith("Coverage area across")


def test_estimate_placename_single_state_small_bbox_falls_back_to_nominatim(
    fake_catalog_dir,
):
    """Small bbox in single state → try Nominatim; on failure return None."""
    from services.search.main import app
    client = TestClient(app)
    # Nominatim isn't running in the test env → Exception path → placename None
    with patch("services.search.main._get_disk_free_gb", return_value=500.0), \
         patch("services.search.main.DATA_DIR", fake_catalog_dir):
        resp = client.get(
            "/admin/pipeline/noaa/estimate",
            params={"bbox": "-112.1,33.4,-112.0,33.5", "state": "arizona"},
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    data = resp.json()
    # Either Nominatim returned a real name OR failed and returned None — both OK.
    # Key invariant: no exception propagates; placename is str or None.
    assert data["placename"] is None or isinstance(data["placename"], str)


def test_estimate_placename_nominatim_mocked_success(fake_catalog_dir):
    """Nominatim reverse-lookup returns display_name; small single-state bbox gets it."""
    from services.search.main import app, _noaa_placename
    import httpx
    import asyncio

    # Test the helper function directly with a mocked http_client
    async def test_helper():
        # Create a fake state object with mocked http_client
        class FakeState:
            pass

        class FakeResponse:
            def __init__(self, json_data):
                self._json_data = json_data

            def json(self):
                return self._json_data

            def raise_for_status(self):
                pass

        class FakeAsyncClient:
            async def get(self, url, **kwargs):
                return FakeResponse({"display_name": "Phoenix, Arizona, USA"})

        fake_state = FakeState()
        fake_state.http_client = FakeAsyncClient()

        # Temporarily swap state
        import services.search.main as search_main
        original_state = search_main.state
        search_main.state = fake_state

        try:
            result = await _noaa_placename(
                states=["arizona"],
                missing=[],
                bbox=(-112.1, 33.4, -112.0, 33.5),
                usps_by_slug={"arizona": "AZ"},
            )
            assert result == "Phoenix, Arizona, USA"
        finally:
            search_main.state = original_state

    asyncio.run(test_helper())


# ---------------------------------------------------------------------------
# Task 22 — POST /admin/pipeline/noaa/refresh
# ---------------------------------------------------------------------------

def test_refresh_happy_path(tmp_path):
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    fake_result = {
        "status": "ok",
        "snapshot_path": str(tmp_path / "snap.json"),
        "log_entry": {"ts": "2026-04-20T12:00:00Z", "status": "ok"},
    }

    async def fake_refresh(*, data_dir, **kwargs):
        return fake_result

    with patch("services.search.main.DATA_DIR", tmp_path), \
         patch("scripts.refresh_noaa_catalog.refresh_catalog", fake_refresh):
        resp = client.post(
            "/admin/pipeline/noaa/refresh",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_refresh_locked_returns_409(tmp_path):
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)

    async def fake_refresh(*, data_dir, **kwargs):
        return {"status": "locked", "lock_holder_pid": 12345}

    with patch("services.search.main.DATA_DIR", tmp_path), \
         patch("scripts.refresh_noaa_catalog.refresh_catalog", fake_refresh):
        resp = client.post(
            "/admin/pipeline/noaa/refresh",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 409


def test_refresh_pipeline_running_returns_409(tmp_path):
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)

    async def fake_refresh(*, data_dir, **kwargs):
        return {
            "status": "blocked_by_pipeline",
            "blocked_by_pipeline": "/data/.pipeline-state.json",
        }

    with patch("services.search.main.DATA_DIR", tmp_path), \
         patch("scripts.refresh_noaa_catalog.refresh_catalog", fake_refresh):
        resp = client.post(
            "/admin/pipeline/noaa/refresh",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 409


def test_refresh_truncated_returns_200(tmp_path):
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    entry = {"ts": "2026-04-20T12:00:00Z", "status": "truncated", "error": "Azure paginator malformed"}

    async def fake_refresh(*, data_dir, **kwargs):
        return {"status": "truncated", "log_entry": entry}

    with patch("services.search.main.DATA_DIR", tmp_path), \
         patch("scripts.refresh_noaa_catalog.refresh_catalog", fake_refresh):
        resp = client.post(
            "/admin/pipeline/noaa/refresh",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "truncated"


# ---------------------------------------------------------------------------

# Task 23 — POST /admin/pipeline/noaa/rollback
# ---------------------------------------------------------------------------

def test_rollback_happy_path(tmp_path):
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    # Seed: snapshot file + current symlink
    snaps = tmp_path / "noaa_catalog_snapshots"
    snaps.mkdir()
    target = snaps / "2026-04-20T12:00:00Z.json"
    target.write_text('{"entries": {}}')
    symlink = tmp_path / "noaa_naip_catalog.json"
    # Point at a "previous" snapshot (doesn't need to exist for symlink creation)
    symlink.symlink_to(snaps / "2026-04-19T00:00:00Z.json")

    with patch("services.search.main.DATA_DIR", tmp_path):
        resp = client.post(
            "/admin/pipeline/noaa/rollback",
            json={"to_snapshot": "2026-04-20T12:00:00Z.json"},
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 200
    assert symlink.resolve() == target.resolve()
    # log file appended
    assert (tmp_path / "noaa_catalog_refresh_log.jsonl").exists()


def test_rollback_missing_snapshot_returns_404(tmp_path):
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    (tmp_path / "noaa_catalog_snapshots").mkdir()
    with patch("services.search.main.DATA_DIR", tmp_path):
        resp = client.post(
            "/admin/pipeline/noaa/rollback",
            json={"to_snapshot": "nonexistent.json"},
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 404


def test_rollback_pipeline_running_returns_409(tmp_path):
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    # Create a fake running pipeline state file
    state = tmp_path / ".pipeline-state.json"
    state.write_text(json.dumps({"status": "running"}))
    with patch("services.search.main.DATA_DIR", tmp_path):
        resp = client.post(
            "/admin/pipeline/noaa/rollback",
            json={"to_snapshot": "anything.json"},
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------

# Task 24 — POST /admin/pipeline/noaa/force-unlock
# ---------------------------------------------------------------------------

def test_force_unlock_no_lock(tmp_path):
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    with patch("services.search.main.DATA_DIR", tmp_path):
        resp = client.post(
            "/admin/pipeline/noaa/force-unlock",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "no_lock"


def test_force_unlock_stale_lock_removed(tmp_path):
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    lock = tmp_path / "noaa_catalog_refresh.lock"
    # PID 999999999 is very unlikely to exist
    lock.write_text(json.dumps({"pid": 999999999}))
    with patch("services.search.main.DATA_DIR", tmp_path):
        resp = client.post(
            "/admin/pipeline/noaa/force-unlock",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert not lock.exists()


def test_force_unlock_live_holder_returns_409(tmp_path):
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    lock = tmp_path / "noaa_catalog_refresh.lock"
    lock.write_text(json.dumps({"pid": os.getpid()}))  # our own PID — alive
    with patch("services.search.main.DATA_DIR", tmp_path):
        resp = client.post(
            "/admin/pipeline/noaa/force-unlock",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------

# Task 25 — GET /admin/pipeline/noaa/refresh-log
# ---------------------------------------------------------------------------

def test_refresh_log_empty_when_no_file(tmp_path):
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    with patch("services.search.main.DATA_DIR", tmp_path):
        resp = client.get(
            "/admin/pipeline/noaa/refresh-log",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 200
    assert resp.json()["entries"] == []


def test_refresh_log_entries_in_reverse_chronological(tmp_path):
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    log_path = tmp_path / "noaa_catalog_refresh_log.jsonl"
    log_path.write_text(
        json.dumps({"ts": "2026-04-19T00:00:00Z", "status": "ok"}) + "\n"
        + json.dumps({"ts": "2026-04-20T00:00:00Z", "status": "ok"}) + "\n"
    )
    with patch("services.search.main.DATA_DIR", tmp_path):
        resp = client.get(
            "/admin/pipeline/noaa/refresh-log",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    entries = resp.json()["entries"]
    assert entries[0]["ts"] == "2026-04-20T00:00:00Z"  # newest first
    assert entries[1]["ts"] == "2026-04-19T00:00:00Z"


def test_refresh_log_rollback_available_flag(tmp_path):
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    snaps = tmp_path / "noaa_catalog_snapshots"
    snaps.mkdir()
    (snaps / "2026-04-20T00:00:00Z.json").write_text("{}")

    log_path = tmp_path / "noaa_catalog_refresh_log.jsonl"
    # Write oldest entry first, newest last (natural append order)
    log_path.write_text(
        json.dumps({
            "ts": "2026-04-19T00:00:00Z", "status": "ok",
            "snapshot_path": str(snaps / "pruned.json"),
        }) + "\n"
        + json.dumps({
            "ts": "2026-04-20T00:00:00Z", "status": "ok",
            "snapshot_path": str(snaps / "2026-04-20T00:00:00Z.json"),
        }) + "\n"
    )
    with patch("services.search.main.DATA_DIR", tmp_path):
        resp = client.get(
            "/admin/pipeline/noaa/refresh-log",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    entries = resp.json()["entries"]
    assert entries[0]["rollback_available"] is True   # newest, file exists
    assert entries[1]["rollback_available"] is False  # file pruned
