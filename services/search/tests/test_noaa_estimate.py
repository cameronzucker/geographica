"""Tests for /admin/pipeline/noaa/estimate.

The endpoint must model the 3-stage pipeline — not the old sequential GDAL CLI
economics (which estimated ~6 min/tile and was 3-6x too pessimistic).
"""
from unittest.mock import patch
import struct
import pytest
from fastapi.testclient import TestClient


def test_estimate_per_tile_seconds_reflects_3_stage_pipeline():
    """Per-tile ETA should be dominated by the slowest stage (~20-45s), not 90s."""
    from services.search.main import app
    client = TestClient(app)

    from pathlib import Path
    data_dir = Path("/srv/geographica/data")
    with patch("services.search.main._get_disk_free_gb", return_value=500.0), \
         patch("services.search.main.DATA_DIR", data_dir):
        resp = client.get(
            "/admin/pipeline/noaa/estimate",
            params={"bbox": "-114,32,-109,37", "state": "AZ", "year": 2021},
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )

    # If the catalog or tile-index cache isn't present, skip the substantive
    # assertion — the test still exercises routing.
    data = resp.json()
    if data.get("status") in ("no_index", "no_catalog"):
        pytest.skip("NOAA catalog not present in CI environment")

    assert resp.status_code == 200
    assert "per_tile_seconds" in data
    assert data["per_tile_seconds"] < 60, \
        f"Per-tile ETA should be < 60s under 3-stage pipeline, got {data['per_tile_seconds']}"
    assert data["per_tile_seconds"] > 10, \
        "Per-tile ETA should be > 10s even in optimistic case (merge is serial)"
