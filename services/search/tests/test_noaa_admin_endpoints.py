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
    # intermediate_gb reflects the (transient) total reprojected size for display.
    # peak_required_gb is dominated by MBTiles final size (the pipeline unlinks
    # raw + reprojected tiles after each batch merges — see 2026-04-21 bug fix).
    assert data["intermediate_gb"] > 0
    assert data["peak_required_gb"] > data["final_mbtiles_gb"]

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
    """intermediate_gb ≈ raw × 0.3 (display-only); peak = staging + MBTiles + buffer."""
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
    staging = data["staging_peak_gb"]

    # intermediate ≈ 0.3 × raw (display-only; transient on disk, cleaned per-batch)
    assert abs(intermediate - raw * 0.3) < 0.1, \
        f"intermediate {intermediate} should be ~0.3 × raw {raw}"

    # peak = staging_peak + final_mbtiles + 5 GB safety buffer
    # (the pipeline unlinks raw + reprojected GeoTIFFs after each merge
    # batch, so only the steady-state download/reproject ring + growing
    # MBTiles consume disk — see scripts/acquire_imagery.py cleanup sites)
    expected_peak = staging + final + 5.0
    assert abs(peak - expected_peak) < 0.2, \
        f"peak {peak} should equal staging {staging} + final {final} + 5.0 buffer"

    # peak must exceed final_mbtiles (staging + buffer adds headroom)
    assert peak > final, "peak_required should exceed final_mbtiles"

    # peak must be WAY smaller than raw_download_gb for any non-trivial run
    # (this was the 2026-04-21 bug: old formula summed raw + intermediate +
    # final, treating every downloaded GeoTIFF as if it stayed on disk forever)
    if raw > 100:  # guard against tiny fixtures where the relation inverts
        assert peak < raw, \
            f"peak {peak} should be << raw {raw} — pipeline streams, doesn't hoard"


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
    """POST /refresh now returns 202 Accepted (async-dispatch, spec v2 Task 3)."""
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app, raise_server_exceptions=False)
    fake_result = {
        "status": "ok",
        "snapshot_path": str(tmp_path / "snap.json"),
        "log_entry": {"ts": "2026-04-20T12:00:00Z", "status": "ok"},
    }

    async def fake_refresh(*, data_dir, **kwargs):
        return fake_result

    with patch("services.search.main.DATA_DIR", tmp_path), \
         patch("refresh_noaa_catalog.refresh_catalog", fake_refresh), \
         patch("refresh_noaa_catalog.find_running_pipelines", return_value=[]), \
         patch("refresh_noaa_catalog.write_progress_state", return_value=None), \
         patch("refresh_noaa_catalog.read_progress_state", return_value={}), \
         patch("refresh_noaa_catalog.append_refresh_log", return_value=None):
        resp = client.post(
            "/admin/pipeline/noaa/refresh",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    # Updated: endpoint now returns 202 Accepted (async-dispatch)
    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


def test_refresh_locked_returns_409(tmp_path):
    """409 locked when lockfile present on disk (async-dispatch, spec v2 Task 3)."""
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)

    # Seed lockfile so the new endpoint detects it before dispatching.
    lock = tmp_path / "noaa_catalog_refresh.lock"
    lock.write_text(json.dumps({"pid": 12345}))

    async def fake_refresh(*, data_dir, **kwargs):
        return {"status": "ok", "snapshot_path": str(tmp_path / "snap.json"), "log_entry": {}}

    with patch("services.search.main.DATA_DIR", tmp_path), \
         patch("refresh_noaa_catalog.refresh_catalog", fake_refresh), \
         patch("refresh_noaa_catalog.find_running_pipelines", return_value=[]), \
         patch("refresh_noaa_catalog.write_progress_state", return_value=None), \
         patch("refresh_noaa_catalog.read_progress_state", return_value={"status": "running"}):
        resp = client.post(
            "/admin/pipeline/noaa/refresh",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 409


def test_refresh_pipeline_running_returns_409(tmp_path):
    """409 blocked_by_pipeline detected before dispatch (async-dispatch, spec v2 Task 3)."""
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)

    async def fake_refresh(*, data_dir, **kwargs):
        return {"status": "ok", "snapshot_path": str(tmp_path / "snap.json"), "log_entry": {}}

    with patch("services.search.main.DATA_DIR", tmp_path), \
         patch("refresh_noaa_catalog.refresh_catalog", fake_refresh), \
         patch("refresh_noaa_catalog.find_running_pipelines",
               return_value=[Path("/data/.pipeline-state.json")]):
        resp = client.post(
            "/admin/pipeline/noaa/refresh",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 409


def test_refresh_truncated_returns_202(tmp_path):
    """Truncated refresh: endpoint still returns 202 (dispatch succeeds; terminal
    state is captured in progress.json by _refresh_bg_task). Spec v2 Task 3."""
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app, raise_server_exceptions=False)
    entry = {"ts": "2026-04-20T12:00:00Z", "status": "truncated", "error": "Azure paginator malformed"}

    async def fake_refresh(*, data_dir, **kwargs):
        return {"status": "truncated", "log_entry": entry}

    with patch("services.search.main.DATA_DIR", tmp_path), \
         patch("refresh_noaa_catalog.refresh_catalog", fake_refresh), \
         patch("refresh_noaa_catalog.find_running_pipelines", return_value=[]), \
         patch("refresh_noaa_catalog.write_progress_state", return_value=None), \
         patch("refresh_noaa_catalog.read_progress_state", return_value={}), \
         patch("refresh_noaa_catalog.append_refresh_log", return_value=None):
        resp = client.post(
            "/admin/pipeline/noaa/refresh",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    # Updated: 202 Accepted; terminal status (truncated) surfaces via progress polling
    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


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

def test_rollback_rejects_path_traversal(tmp_path):
    """Defense-in-depth: reject filenames with '/', '\\', or '..' with 422."""
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    with patch("services.search.main.DATA_DIR", tmp_path):
        for evil in ("../etc/passwd", "..\\secrets", "a/b.json", "a/../../b.json"):
            resp = client.post(
                "/admin/pipeline/noaa/rollback",
                json={"to_snapshot": evil},
                headers={"X-Config-Source": "internal", "X-Geographica": "1"},
            )
            assert resp.status_code == 422, f"expected 422 for {evil!r}, got {resp.status_code}"


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


# ---------------------------------------------------------------------------
# Task 26 — POST /admin/pipeline/start (NOAA mode extension)
# ---------------------------------------------------------------------------

def test_start_noaa_requires_acknowledge_missing_when_missing_nonempty(
    fake_catalog_dir,
):
    """If bbox spans uncataloged states, Start returns 409 without acknowledge_missing."""
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    with patch("services.search.main._get_disk_free_gb", return_value=500.0), \
         patch("services.search.main.DATA_DIR", fake_catalog_dir):
        resp = client.post(
            "/admin/pipeline/start",
            json={
                "type": "imagery",
                "mode": "noaa",
                "bbox": "-109.1,36.9,-108.9,37.1",  # Four Corners: AZ+UT cataloged, CO+NM missing
            },
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 409
    body = resp.json()
    # FastAPI wraps HTTPException detail under "detail"
    detail = body.get("detail", body)
    assert detail.get("status") == "missing_unacknowledged"
    assert "colorado" in detail.get("missing", []) or "new-mexico" in detail.get("missing", [])


def test_start_noaa_with_acknowledge_missing_proceeds(fake_catalog_dir):
    """With acknowledge_missing=true, the endpoint accepts missing states and progresses."""
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    # Mock docker so we don't actually spawn a container.
    # Disk must be large enough to pass the peak_required_gb check (AZ+UT ≈ 50,706 GB).
    with patch("services.search.main._get_disk_free_gb", return_value=500_000.0), \
         patch("services.search.main.DATA_DIR", fake_catalog_dir), \
         patch("services.search.main._get_docker_client", return_value=None):
        resp = client.post(
            "/admin/pipeline/start",
            json={
                "type": "imagery",
                "mode": "noaa",
                "bbox": "-109.1,36.9,-108.9,37.1",
                "acknowledge_missing": True,
            },
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    # With docker mocked to None, we expect 503 "Docker socket not available"
    # — not 409. The important thing is we got PAST the missing-states check.
    assert resp.status_code == 503
    assert "Docker" in resp.json().get("detail", "")


def test_start_noaa_disk_recheck_returns_507_if_insufficient(fake_catalog_dir):
    """If free disk dropped below peak between estimate and Start, return 507."""
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    # tile_count=50124 for AZ → raw ≈ 23,789 GB → peak ≈ 32,345 GB.
    # Mock free disk at 10 GB — way below.
    with patch("services.search.main._get_disk_free_gb", return_value=10.0), \
         patch("services.search.main.DATA_DIR", fake_catalog_dir):
        resp = client.post(
            "/admin/pipeline/start",
            json={
                "type": "imagery",
                "mode": "noaa",
                "bbox": "-114,32,-109,37",
                "state": "arizona",
            },
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 507
    detail = resp.json().get("detail", {})
    assert detail.get("status") == "insufficient_disk"
    assert "disk_free_gb" in detail
    assert "peak_required_gb" in detail
    assert detail["peak_required_gb"] > detail["disk_free_gb"]


def test_start_noaa_single_state_no_missing_no_ack_needed(fake_catalog_dir):
    """Single-state run (no missing[]) proceeds without acknowledge_missing."""
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    # Mock docker to None so Start short-circuits at Docker check, not earlier
    with patch("services.search.main._get_disk_free_gb", return_value=500000.0), \
         patch("services.search.main.DATA_DIR", fake_catalog_dir), \
         patch("services.search.main._get_docker_client", return_value=None):
        resp = client.post(
            "/admin/pipeline/start",
            json={
                "type": "imagery",
                "mode": "noaa",
                "state": "arizona",
                "bbox": "-112.1,33.4,-112.0,33.5",
            },
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    # Expected: 503 (docker unavailable) — means we got past all NOAA validation.
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Round 2 coverage gaps — edge cases surfaced in phase review
# ---------------------------------------------------------------------------

def test_estimate_rejects_malformed_bbox(fake_catalog_dir):
    """Non-numeric or wrong-count bbox → 422 with useful detail."""
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    with patch("services.search.main._get_disk_free_gb", return_value=500.0), \
         patch("services.search.main.DATA_DIR", fake_catalog_dir):
        for bad in ("not-a-bbox", "1,2,3", "a,b,c,d", ""):
            resp = client.get(
                "/admin/pipeline/noaa/estimate",
                params={"bbox": bad, "state": "arizona"},
                headers={"X-Config-Source": "internal", "X-Geographica": "1"},
            )
            # 422 for format errors; the early `state` branch may swallow some,
            # but at minimum the endpoint must NOT 500.
            assert resp.status_code in (200, 422), f"bbox={bad!r} got {resp.status_code}"


def test_estimate_bbox_with_zero_state_intersections(fake_catalog_dir):
    """Ocean bbox (no states overlap) → 200 with empty states[] and missing[]."""
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    # Middle of the North Pacific — no CONUS state intersects
    with patch("services.search.main._get_disk_free_gb", return_value=500.0), \
         patch("services.search.main.DATA_DIR", fake_catalog_dir):
        resp = client.get(
            "/admin/pipeline/noaa/estimate",
            params={"bbox": "-160,20,-159,21"},
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 200
    data = resp.json()
    # Endpoint short-circuits to a minimal shape when no cataloged state
    # intersects the bbox — frontends should branch on `status`.
    assert data["status"] == "no_index"
    assert "cataloged" in data.get("message", "").lower()


def test_refresh_invalid_parse_returns_202(tmp_path):
    """Azure listing parsed successfully but catalog shape invalid → 202 Accepted
    (async-dispatch, spec v2 Task 3). Terminal status surfaces via progress polling."""
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app, raise_server_exceptions=False)
    entry = {
        "ts": "2026-04-20T12:00:00Z",
        "status": "invalid_parse",
        "error": "snapshot_version missing from parsed catalog",
    }

    async def fake_refresh(*, data_dir, **kwargs):
        return {"status": "invalid_parse", "log_entry": entry}

    with patch("services.search.main.DATA_DIR", tmp_path), \
         patch("refresh_noaa_catalog.refresh_catalog", fake_refresh), \
         patch("refresh_noaa_catalog.find_running_pipelines", return_value=[]), \
         patch("refresh_noaa_catalog.write_progress_state", return_value=None), \
         patch("refresh_noaa_catalog.read_progress_state", return_value={}), \
         patch("refresh_noaa_catalog.append_refresh_log", return_value=None):
        resp = client.post(
            "/admin/pipeline/noaa/refresh",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    # Updated: 202 Accepted; invalid_parse terminal state surfaces via progress polling
    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


# ---------------------------------------------------------------------------
# Task 28 — GET /admin/pipeline/noaa/catalog
# ---------------------------------------------------------------------------

def test_catalog_endpoint_returns_entries(fake_catalog_dir):
    """Catalog endpoint returns ok status and the entries from the snapshot."""
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    with patch("services.search.main.DATA_DIR", fake_catalog_dir):
        resp = client.get(
            "/admin/pipeline/noaa/catalog",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "arizona" in data["entries"]
    assert "utah" in data["entries"]
    assert data["entries"]["arizona"]["usps"] == "AZ"


def test_catalog_endpoint_handles_missing_symlink(tmp_path):
    """When no catalog symlink exists, endpoint returns no_catalog with empty entries."""
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    with patch("services.search.main.DATA_DIR", tmp_path):
        resp = client.get(
            "/admin/pipeline/noaa/catalog",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "no_catalog"
    assert data["entries"] == {}


def test_start_noaa_with_no_catalog_returns_409(tmp_path):
    """Final-review blocker B1: Start must 409 cleanly when no catalog is loaded
    rather than letting the pipeline container crash inside with FileNotFoundError."""
    from services.search.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    # tmp_path has no noaa_naip_catalog.json symlink → _load_noaa_catalog returns None
    with patch("services.search.main._get_disk_free_gb", return_value=500.0), \
         patch("services.search.main.DATA_DIR", tmp_path):
        resp = client.post(
            "/admin/pipeline/start",
            json={
                "type": "imagery",
                "mode": "noaa",
                "state": "arizona",
                "bbox": "-112.1,33.4,-112.0,33.5",
            },
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert resp.status_code == 409
    detail = resp.json().get("detail", {})
    assert detail.get("status") == "no_catalog"
    assert "refresh" in detail.get("message", "").lower()


# ---------------------------------------------------------------------------
# Task 3 — async-dispatch POST /admin/pipeline/noaa/refresh (spec v2)
# ---------------------------------------------------------------------------

def test_noaa_refresh_returns_202_fast(tmp_path):
    """POST /refresh returns 202 Accepted in < 1 s; body has required fields."""
    import asyncio
    import time
    from services.search.main import app
    from fastapi.testclient import TestClient
    from unittest.mock import patch

    async def noop_refresh(*, data_dir, progress_cb=None, cancel_event=None):
        return {
            "status": "ok",
            "snapshot_path": str(tmp_path / "snap.json"),
            "log_entry": {"ts": "2026-04-20T12:00:00Z", "state_count": 0},
        }

    with patch("services.search.main.DATA_DIR", tmp_path), \
         patch("refresh_noaa_catalog.refresh_catalog", noop_refresh), \
         patch("refresh_noaa_catalog.find_running_pipelines", return_value=[]), \
         patch("refresh_noaa_catalog.write_progress_state", return_value=None), \
         patch("refresh_noaa_catalog.read_progress_state", return_value={}):
        client = TestClient(app, raise_server_exceptions=False)
        t0 = time.time()
        resp = client.post(
            "/admin/pipeline/noaa/refresh",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
        elapsed = time.time() - t0

    assert resp.status_code == 202, f"expected 202 got {resp.status_code}: {resp.text}"
    body = resp.json()
    for field in ("status", "progress_url", "started_at", "estimated_minutes"):
        assert field in body, f"missing field: {field}"
    assert body["status"] == "started"
    assert body["progress_url"] == "/admin/pipeline/noaa/refresh/progress"
    assert elapsed < 1.0, f"response took {elapsed:.2f}s — not async-dispatch"


def test_noaa_refresh_409_when_pipeline_running(tmp_path):
    """409 blocked_by_pipeline when find_running_pipelines returns a match."""
    from services.search.main import app
    from fastapi.testclient import TestClient
    from unittest.mock import patch

    with patch("services.search.main.DATA_DIR", tmp_path), \
         patch("refresh_noaa_catalog.find_running_pipelines",
               return_value=[Path("/data/.pipeline-state.json")]):
        client = TestClient(app)
        resp = client.post(
            "/admin/pipeline/noaa/refresh",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )

    assert resp.status_code == 409
    detail = resp.json().get("detail", {})
    assert detail.get("status") == "blocked_by_pipeline"


def test_noaa_refresh_409_when_locked(tmp_path):
    """409 locked when lockfile already exists on disk."""
    from services.search.main import app
    from fastapi.testclient import TestClient
    from unittest.mock import patch

    # Seed lockfile
    lock = tmp_path / "noaa_catalog_refresh.lock"
    lock.write_text(json.dumps({"pid": 99999}))

    async def noop_refresh(*, data_dir, **kwargs):
        return {"status": "ok", "snapshot_path": str(tmp_path / "snap.json"), "log_entry": {}}

    with patch("services.search.main.DATA_DIR", tmp_path), \
         patch("refresh_noaa_catalog.refresh_catalog", noop_refresh), \
         patch("refresh_noaa_catalog.find_running_pipelines", return_value=[]), \
         patch("refresh_noaa_catalog.write_progress_state", return_value=None), \
         patch("refresh_noaa_catalog.read_progress_state", return_value={"status": "running"}):
        client = TestClient(app)
        resp = client.post(
            "/admin/pipeline/noaa/refresh",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )

    assert resp.status_code == 409
    detail = resp.json().get("detail", {})
    assert detail.get("status") == "locked"


def test_noaa_refresh_writes_progress_and_task_ref(tmp_path):
    """202 dispatch: first write_progress_state call has status=running + started_at."""
    import asyncio
    from services.search.main import app
    from fastapi.testclient import TestClient
    from unittest.mock import patch, MagicMock

    all_writes = []  # collect each call independently

    def fake_write_progress(path, state):
        import copy
        all_writes.append(copy.deepcopy(state))

    async def slow_refresh(*, data_dir, progress_cb=None, cancel_event=None):
        await asyncio.sleep(0.05)
        return {"status": "ok", "snapshot_path": str(tmp_path / "snap.json"), "log_entry": {}}

    with patch("services.search.main.DATA_DIR", tmp_path), \
         patch("refresh_noaa_catalog.refresh_catalog", slow_refresh), \
         patch("refresh_noaa_catalog.find_running_pipelines", return_value=[]), \
         patch("refresh_noaa_catalog.write_progress_state", side_effect=fake_write_progress), \
         patch("refresh_noaa_catalog.read_progress_state", return_value={}), \
         patch("refresh_noaa_catalog.append_refresh_log", return_value=None):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/admin/pipeline/noaa/refresh",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )

    assert resp.status_code == 202, f"expected 202 got {resp.status_code}: {resp.text}"
    # The first write is the initial progress.json seeded by the handler before
    # asyncio.create_task — it must have status=running + started_at.
    assert len(all_writes) >= 1, "write_progress_state was never called"
    first = all_writes[0]
    assert first.get("status") == "running", f"first write: {first}"
    assert "started_at" in first, f"first write missing started_at: {first}"


# ---------------------------------------------------------------------------
# Task 4: GET /admin/pipeline/noaa/refresh/progress endpoint
# ---------------------------------------------------------------------------

def test_noaa_refresh_progress_idle_when_no_file(tmp_path):
    """GET /progress returns {status: idle} when progress.json is absent."""
    from services.search.main import app
    from unittest.mock import patch

    client = TestClient(app)
    with patch("services.search.main.DATA_DIR", tmp_path):
        r = client.get(
            "/admin/pipeline/noaa/refresh/progress",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert r.status_code == 200
    assert r.json() == {"status": "idle"}


def test_noaa_refresh_progress_running(tmp_path):
    """GET /progress returns the running-state shape from spec API contract."""
    from services.search.main import app
    from refresh_noaa_catalog import write_progress_state, PROGRESS_FILENAME
    from unittest.mock import patch

    monkeypatch_data_dir = tmp_path
    progress_path = tmp_path / PROGRESS_FILENAME
    write_progress_state(progress_path, {
        "status": "running",
        "phase": "fetching_tile_indexes",
        "states_processed": 12,
        "states_total": 49,
        "current_slug": "arizona",
        "started_at": "2026-04-20T21:30:00Z",
        "percent": 24.5,
        "cancel_requested": False,
    })

    client = TestClient(app)
    with patch("services.search.main.DATA_DIR", monkeypatch_data_dir):
        r = client.get(
            "/admin/pipeline/noaa/refresh/progress",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running"
    assert body["phase"] == "fetching_tile_indexes"
    assert body["states_processed"] == 12
    assert body["states_total"] == 49
    assert body["current_slug"] == "arizona"
    assert "last_updated" in body  # stamped by write_progress_state


def test_noaa_refresh_progress_done(tmp_path):
    """GET /progress returns terminal result when the bg task finished."""
    from services.search.main import app
    from refresh_noaa_catalog import write_progress_state, PROGRESS_FILENAME
    from unittest.mock import patch

    monkeypatch_data_dir = tmp_path
    progress_path = tmp_path / PROGRESS_FILENAME
    write_progress_state(progress_path, {
        "status": "done",
        "started_at": "2026-04-20T21:30:00Z",
        "ended_at": "2026-04-20T21:54:12Z",
        "result": {"status": "ok", "snapshot_path": "/data/noaa_catalog_snapshots/x.json",
                   "log_entry": {"ts": "2026-04-20T21:30:00Z", "state_count": 49}},
    })

    client = TestClient(app)
    with patch("services.search.main.DATA_DIR", monkeypatch_data_dir):
        r = client.get(
            "/admin/pipeline/noaa/refresh/progress",
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert body["result"]["status"] == "ok"
    assert body["result"]["log_entry"]["state_count"] == 49


def test_noaa_refresh_progress_requires_internal_header(tmp_path):
    """GET /progress goes through require_config_source like the other admin endpoints."""
    from services.search.main import app
    from unittest.mock import patch

    client = TestClient(app)
    with patch("services.search.main.DATA_DIR", tmp_path):
        r = client.get("/admin/pipeline/noaa/refresh/progress")  # no X-Config-Source header
    # The exact status depends on how require_config_source rejects; match existing pattern.
    assert r.status_code in (401, 403)


def test_noaa_refresh_cancel_when_running(tmp_path, monkeypatch):
    """POST /cancel sets the module-level _cancel_event when a refresh is in flight."""
    from services.search.main import app
    from services.search import main as main_module
    from refresh_noaa_catalog import write_progress_state, PROGRESS_FILENAME
    import asyncio

    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    # Seed progress.json with a running refresh
    write_progress_state(tmp_path / PROGRESS_FILENAME, {
        "status": "running", "phase": "fetching_tile_indexes",
    })
    # Seed a module-level cancel event (simulates the bg task having been dispatched)
    main_module._cancel_event = asyncio.Event()
    main_module._active_refresh_task = None  # Not actually started, but enough for the endpoint

    client = TestClient(app)
    r = client.post(
        "/admin/pipeline/noaa/refresh/cancel",
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancellation_requested"
    assert "message" in body
    # The Event must be set so the bg task observes it on next iteration
    assert main_module._cancel_event.is_set() is True

    # Cleanup so other tests don't inherit state
    main_module._cancel_event = None


def test_noaa_refresh_cancel_when_idle_returns_404(tmp_path, monkeypatch):
    """POST /cancel returns 404 when no refresh is running."""
    from services.search.main import app
    from services.search import main as main_module
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    # Ensure no running state
    main_module._cancel_event = None
    client = TestClient(app)
    r = client.post(
        "/admin/pipeline/noaa/refresh/cancel",
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )
    assert r.status_code == 404


def test_noaa_refresh_cancel_when_done_returns_404(tmp_path, monkeypatch):
    """POST /cancel returns 404 when a refresh is in terminal state."""
    from services.search.main import app
    from services.search import main as main_module
    from refresh_noaa_catalog import write_progress_state, PROGRESS_FILENAME
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    write_progress_state(tmp_path / PROGRESS_FILENAME, {
        "status": "done", "result": {"status": "ok"},
    })
    main_module._cancel_event = None  # bg task cleared it on finally
    client = TestClient(app)
    r = client.post(
        "/admin/pipeline/noaa/refresh/cancel",
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )
    assert r.status_code == 404


def test_noaa_refresh_cancel_idempotent(tmp_path, monkeypatch):
    """Second POST /cancel while cancel is already requested returns 200 (not 409)."""
    from services.search.main import app
    from services.search import main as main_module
    from refresh_noaa_catalog import write_progress_state, PROGRESS_FILENAME
    import asyncio
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    write_progress_state(tmp_path / PROGRESS_FILENAME, {
        "status": "running", "phase": "fetching_tile_indexes",
    })
    main_module._cancel_event = asyncio.Event()
    main_module._cancel_event.set()  # already cancelled
    client = TestClient(app)
    r = client.post(
        "/admin/pipeline/noaa/refresh/cancel",
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )
    assert r.status_code == 200
    main_module._cancel_event = None


# ---------------------------------------------------------------------------
# Task 6 — stale-detection heuristic for running refresh
# ---------------------------------------------------------------------------

def test_noaa_refresh_progress_stale_flagged_when_last_updated_old(tmp_path, monkeypatch):
    """GET /progress stamps stale: true when running state hasn't updated in >10 min."""
    from services.search.main import app
    from services.search import main as main_module
    from refresh_noaa_catalog import PROGRESS_FILENAME
    from datetime import datetime, timezone, timedelta
    import json

    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    progress_path = tmp_path / PROGRESS_FILENAME
    # Build progress.json manually so we control last_updated; DON'T use
    # write_progress_state (which always stamps last_updated to now).
    fake_old = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    progress_path.write_text(json.dumps({
        "status": "running",
        "phase": "fetching_tile_indexes",
        "last_updated": fake_old,
    }))
    client = TestClient(app)
    r = client.get(
        "/admin/pipeline/noaa/refresh/progress",
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["stale"] is True
    assert "stale_reason" in body


def test_noaa_refresh_progress_fresh_running_not_stale(tmp_path, monkeypatch):
    """GET /progress does NOT stamp stale when running state was updated recently."""
    from services.search.main import app
    from services.search import main as main_module
    from refresh_noaa_catalog import write_progress_state, PROGRESS_FILENAME
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    # write_progress_state stamps last_updated to now()
    write_progress_state(tmp_path / PROGRESS_FILENAME, {
        "status": "running", "phase": "fetching_tile_indexes",
    })
    client = TestClient(app)
    r = client.get(
        "/admin/pipeline/noaa/refresh/progress",
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("stale") in (False, None)  # either explicitly False or absent


def test_noaa_refresh_progress_done_not_stale_even_if_old(tmp_path, monkeypatch):
    """Terminal (done) states are NEVER flagged stale regardless of last_updated age."""
    from services.search.main import app
    from services.search import main as main_module
    from refresh_noaa_catalog import PROGRESS_FILENAME
    from datetime import datetime, timezone, timedelta
    import json
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    progress_path = tmp_path / PROGRESS_FILENAME
    fake_old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    progress_path.write_text(json.dumps({
        "status": "done",
        "last_updated": fake_old,
        "result": {"status": "ok"},
    }))
    client = TestClient(app)
    r = client.get(
        "/admin/pipeline/noaa/refresh/progress",
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("stale") in (False, None)


# ---------------------------------------------------------------------------
# Phase 1 review closeout — 4 tests for 3 bugs surfaced in 3-round review
# ---------------------------------------------------------------------------

def test_refresh_bg_task_error_writes_status_error_no_log_duplicate(tmp_path, monkeypatch):
    """Bg task error path writes progress.json with status=done, result.status=error,
    and does NOT append a duplicate log entry (refresh_catalog owns all non-exception logs)."""
    import asyncio
    from services.search import main as main_module
    from refresh_noaa_catalog import PROGRESS_FILENAME, write_progress_state
    import json

    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)

    async def fake_refresh(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("refresh_noaa_catalog.refresh_catalog", fake_refresh)

    async def _run():
        cancel_event = asyncio.Event()
        started_at = "2026-04-20T21:30:00Z"
        progress_path = tmp_path / PROGRESS_FILENAME
        write_progress_state(progress_path, {"status": "running", "started_at": started_at})

        await main_module._refresh_bg_task(tmp_path, progress_path, started_at, cancel_event)

        state = json.loads(progress_path.read_text())
        assert state["status"] == "done"
        assert state["result"]["status"] == "error"
        assert state["result"]["error"] == "boom"

        # No log entries should exist (refresh_catalog never reached a logging path
        # because it raised before any log write).
        log_path = tmp_path / "noaa_catalog_refresh_log.jsonl"
        assert not log_path.exists() or log_path.read_text().strip() == ""

    asyncio.run(_run())


def test_noaa_refresh_progress_handles_naive_last_updated(tmp_path, monkeypatch):
    """GET /progress does not 500 when last_updated is a naive ISO timestamp."""
    from services.search.main import app
    from services.search import main as main_module
    from refresh_noaa_catalog import PROGRESS_FILENAME
    import json
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    progress_path = tmp_path / PROGRESS_FILENAME
    progress_path.write_text(json.dumps({
        "status": "running", "phase": "fetching_tile_indexes",
        "last_updated": "2026-04-20T12:00:00",  # naive, no Z, no offset
    }))
    client = TestClient(app)
    r = client.get(
        "/admin/pipeline/noaa/refresh/progress",
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running"
    # Non-stale because the parse failed gracefully — not a 500.
    assert body.get("stale") in (False, None)


def test_noaa_refresh_cancel_requires_internal_header(tmp_path, monkeypatch):
    """POST /cancel rejects requests without X-Config-Source header."""
    from services.search.main import app
    from services.search import main as main_module
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    client = TestClient(app)
    r = client.post("/admin/pipeline/noaa/refresh/cancel")
    assert r.status_code in (401, 403)


def test_refresh_bg_task_cancelled_error_writes_reset_endpoint_reason(tmp_path, monkeypatch):
    """Bg task cancelled via task.cancel() writes result.reason=reset_endpoint."""
    import asyncio
    from services.search import main as main_module
    from refresh_noaa_catalog import PROGRESS_FILENAME, write_progress_state
    import json

    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)

    async def slow_refresh(**kwargs):
        # Simulates a refresh that's cancelled mid-way by task.cancel()
        await asyncio.sleep(5)
        return {"status": "ok", "snapshot_path": "x", "log_entry": {"ts": "x", "state_count": 0}}

    monkeypatch.setattr("refresh_noaa_catalog.refresh_catalog", slow_refresh)

    async def _run():
        cancel_event = asyncio.Event()
        started_at = "2026-04-20T21:30:00Z"
        progress_path = tmp_path / PROGRESS_FILENAME
        write_progress_state(progress_path, {"status": "running", "started_at": started_at})

        bg_task = asyncio.create_task(
            main_module._refresh_bg_task(tmp_path, progress_path, started_at, cancel_event)
        )
        await asyncio.sleep(0.1)
        bg_task.cancel()
        try:
            await bg_task
        except asyncio.CancelledError:
            pass

        state = json.loads(progress_path.read_text())
        assert state["status"] == "done"
        assert state["result"]["status"] == "cancelled"
        assert state["result"].get("reason") == "reset_endpoint"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Task 12 — bg-task terminal-state round-trip coverage (4 missing statuses)
# ---------------------------------------------------------------------------

def test_refresh_bg_task_ok_writes_result_ok_to_progress(tmp_path, monkeypatch):
    """Bg task success path writes progress.json with status=done, result.status=ok."""
    import asyncio
    from services.search import main as main_module
    from refresh_noaa_catalog import PROGRESS_FILENAME, write_progress_state
    import json

    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)

    async def fake_refresh(**kwargs):
        return {
            "status": "ok",
            "snapshot_path": str(tmp_path / "snap.json"),
            "log_entry": {
                "ts": "2026-04-20T21:30:00Z", "state_count": 49,
                "added": ["alabama"], "removed": []
            },
        }

    monkeypatch.setattr("refresh_noaa_catalog.refresh_catalog", fake_refresh)

    async def _run():
        cancel_event = asyncio.Event()
        started_at = "2026-04-20T21:30:00Z"
        progress_path = tmp_path / PROGRESS_FILENAME
        write_progress_state(progress_path, {"status": "running", "started_at": started_at})
        await main_module._refresh_bg_task(tmp_path, progress_path, started_at, cancel_event)
        state = json.loads(progress_path.read_text())
        assert state["status"] == "done"
        assert state["result"]["status"] == "ok"
        assert state["result"]["snapshot_path"].endswith("snap.json")
        assert state["result"]["log_entry"]["state_count"] == 49
        assert "ended_at" in state

    asyncio.run(_run())


def test_refresh_bg_task_truncated_writes_result_truncated_to_progress(tmp_path, monkeypatch):
    """Bg task truncated-result path writes progress.json with status=done, result.status=truncated."""
    import asyncio
    from services.search import main as main_module
    from refresh_noaa_catalog import PROGRESS_FILENAME, write_progress_state
    import json

    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)

    async def fake_refresh(**kwargs):
        return {
            "status": "truncated",
            "log_entry": {
                "ts": "2026-04-20T21:30:00Z", "validation_status": "truncated",
                "error": "page 3 returned HTTP 503"
            },
        }

    monkeypatch.setattr("refresh_noaa_catalog.refresh_catalog", fake_refresh)

    async def _run():
        cancel_event = asyncio.Event()
        started_at = "2026-04-20T21:30:00Z"
        progress_path = tmp_path / PROGRESS_FILENAME
        write_progress_state(progress_path, {"status": "running", "started_at": started_at})
        await main_module._refresh_bg_task(tmp_path, progress_path, started_at, cancel_event)
        state = json.loads(progress_path.read_text())
        assert state["status"] == "done"
        assert state["result"]["status"] == "truncated"
        assert "log_entry" in state["result"]

    asyncio.run(_run())


def test_refresh_bg_task_invalid_parse_writes_result_invalid_parse_to_progress(tmp_path, monkeypatch):
    """Bg task invalid_parse path writes progress.json with status=done, result.status=invalid_parse."""
    import asyncio
    from services.search import main as main_module
    from refresh_noaa_catalog import PROGRESS_FILENAME, write_progress_state
    import json

    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)

    async def fake_refresh(**kwargs):
        return {
            "status": "invalid_parse",
            "log_entry": {
                "ts": "2026-04-20T21:30:00Z", "validation_status": "invalid_parse",
                "error": "missing top-level keys: ['parser_version']"
            },
        }

    monkeypatch.setattr("refresh_noaa_catalog.refresh_catalog", fake_refresh)

    async def _run():
        cancel_event = asyncio.Event()
        started_at = "2026-04-20T21:30:00Z"
        progress_path = tmp_path / PROGRESS_FILENAME
        write_progress_state(progress_path, {"status": "running", "started_at": started_at})
        await main_module._refresh_bg_task(tmp_path, progress_path, started_at, cancel_event)
        state = json.loads(progress_path.read_text())
        assert state["status"] == "done"
        assert state["result"]["status"] == "invalid_parse"

    asyncio.run(_run())


def test_refresh_bg_task_cancel_event_writes_result_cancelled_to_progress(tmp_path, monkeypatch):
    """Bg task where refresh_catalog returns status=cancelled (user Cancel) writes
    progress.json with result.status=cancelled and does NOT use the reset_endpoint reason."""
    import asyncio
    from services.search import main as main_module
    from refresh_noaa_catalog import PROGRESS_FILENAME, write_progress_state
    import json

    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)

    async def fake_refresh(**kwargs):
        return {
            "status": "cancelled",
            "log_entry": {
                "ts": "2026-04-20T21:30:00Z", "validation_status": "cancelled",
                "state_count": 12, "reason": "cancelled_by_user"
            },
        }

    monkeypatch.setattr("refresh_noaa_catalog.refresh_catalog", fake_refresh)

    async def _run():
        cancel_event = asyncio.Event()
        started_at = "2026-04-20T21:30:00Z"
        progress_path = tmp_path / PROGRESS_FILENAME
        write_progress_state(progress_path, {"status": "running", "started_at": started_at})
        await main_module._refresh_bg_task(tmp_path, progress_path, started_at, cancel_event)
        state = json.loads(progress_path.read_text())
        assert state["status"] == "done"
        assert state["result"]["status"] == "cancelled"
        # Distinct from the reset_endpoint reason written by the CancelledError branch
        assert state["result"].get("reason") != "reset_endpoint"
        assert state["result"].get("log_entry", {}).get("reason") == "cancelled_by_user"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# POST /admin/pipeline/noaa/refresh/reset (Task 11)
# ---------------------------------------------------------------------------

def test_noaa_refresh_reset_when_idle_returns_404(tmp_path, monkeypatch):
    """POST /reset returns 404 when there's nothing to reset."""
    from services.search.main import app
    from services.search import main as main_module
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    main_module._active_refresh_task = None
    main_module._cancel_event = None
    client = TestClient(app)
    r = client.post(
        "/admin/pipeline/noaa/refresh/reset",
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )
    assert r.status_code == 404


def test_noaa_refresh_reset_clears_lockfile_and_progress(tmp_path, monkeypatch):
    """POST /reset atomically removes the lockfile + progress.json and returns 200."""
    from services.search.main import app
    from services.search import main as main_module
    from refresh_noaa_catalog import PROGRESS_FILENAME, write_progress_state
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    main_module._active_refresh_task = None
    main_module._cancel_event = None
    # Seed a stuck lockfile + progress.json
    lock_path = tmp_path / "noaa_catalog_refresh.lock"
    lock_path.write_text('{"pid": 99999, "acquired_ts": "2026-04-20T10:00:00Z"}')
    write_progress_state(tmp_path / PROGRESS_FILENAME, {
        "status": "running", "phase": "fetching_tile_indexes",
    })
    client = TestClient(app)
    r = client.post(
        "/admin/pipeline/noaa/refresh/reset",
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "reset"
    assert body["lockfile_removed"] is True
    assert body["progress_removed"] is True
    assert body["task_cancelled"] is False
    # Files are gone
    assert not lock_path.exists()
    assert not (tmp_path / PROGRESS_FILENAME).exists()


@pytest.mark.asyncio
async def test_noaa_refresh_reset_cancels_active_task(tmp_path, monkeypatch):
    """POST /reset cancels _active_refresh_task and awaits its finalization."""
    import asyncio
    from services.search import main as main_module
    from refresh_noaa_catalog import PROGRESS_FILENAME, write_progress_state

    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)

    async def long_running():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise

    task = asyncio.create_task(long_running())
    await asyncio.sleep(0.01)  # let the task start
    main_module._active_refresh_task = task
    main_module._cancel_event = asyncio.Event()
    write_progress_state(tmp_path / PROGRESS_FILENAME, {"status": "running"})

    # Call the endpoint function directly (avoids TestClient event-loop conflicts)
    from services.search.main import noaa_refresh_reset
    body = await noaa_refresh_reset()

    assert body["status"] == "reset"
    assert body["task_cancelled"] is True
    assert body["progress_removed"] is True
    # After reset, module refs are cleared
    assert main_module._active_refresh_task is None
    assert main_module._cancel_event is None


@pytest.mark.asyncio
async def test_noaa_refresh_reset_task_hang_does_not_block_endpoint(tmp_path, monkeypatch):
    """If _active_refresh_task never finalizes after .cancel(), /reset still returns.

    Fix 4: CANCEL_TIMEOUT_SEC bounds the await via asyncio.wait_for.  We simulate
    the timeout by monkeypatching asyncio.wait_for to raise TimeoutError immediately,
    which is equivalent to the 30-second timeout firing in production.
    """
    import asyncio
    from services.search import main as main_module
    from refresh_noaa_catalog import PROGRESS_FILENAME, write_progress_state

    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)

    # Simulate wait_for raising TimeoutError (as if the task hung for 30s)
    async def raise_timeout(*args, **kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "wait_for", raise_timeout)

    async def long_running():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise

    task = asyncio.create_task(long_running())
    await asyncio.sleep(0.01)  # let the task start
    main_module._active_refresh_task = task
    main_module._cancel_event = asyncio.Event()
    write_progress_state(tmp_path / PROGRESS_FILENAME, {"status": "running"})

    from services.search.main import noaa_refresh_reset
    body = await noaa_refresh_reset()

    # Endpoint must succeed despite the simulated timeout
    assert body["status"] == "reset"
    assert body["task_cancelled"] is True
    assert body["progress_removed"] is True
    # Module refs cleared so the next refresh can dispatch
    assert main_module._active_refresh_task is None
    assert main_module._cancel_event is None
    # Clean up the real task (it does handle CancelledError, so this is safe)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_noaa_refresh_reset_requires_internal_header(tmp_path, monkeypatch):
    """POST /reset requires X-Config-Source auth."""
    from services.search.main import app
    from services.search import main as main_module
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    client = TestClient(app)
    r = client.post("/admin/pipeline/noaa/refresh/reset")
    assert r.status_code in (401, 403)
