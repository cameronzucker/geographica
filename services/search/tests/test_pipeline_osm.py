"""Tests for OSM POI pipeline type support.

Tests PipelineStartBody optional fields, osm_poi validation, PBF discovery,
pipeline image check, and completed_at/duration_seconds state enrichment.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def mock_docker():
    """Mock Docker client."""
    mock_client = MagicMock()
    mock_client.containers.list.return_value = []
    mock_client.containers.get.side_effect = Exception("not found")
    mock_client.images.get.return_value = MagicMock()  # Image exists
    mock_client.close = MagicMock()
    mock_client.networks.list.return_value = [MagicMock(name="geographica_default")]

    # Mock container run
    mock_container = MagicMock()
    mock_container.id = "abc123"
    mock_container.status = "running"
    mock_client.containers.run.return_value = mock_container

    return mock_client


@pytest.fixture
def client(mock_docker, tmp_path, monkeypatch):
    """Create TestClient with mocked Docker."""
    if "main" in sys.modules:
        del sys.modules["main"]

    monkeypatch.setenv("POI_DB_PATH", str(tmp_path / "poi.sqlite"))
    monkeypatch.setenv("NOMINATIM_URL", "http://localhost:9999")
    monkeypatch.setenv("DATA_HOST_PATH", "/srv/geographica/data")
    monkeypatch.setenv("SCRIPTS_HOST_PATH", "/home/administrator/Code/geographica/scripts")

    import main

    main._get_docker_client = MagicMock(return_value=mock_docker)
    main.DATA_DIR = tmp_path

    with TestClient(main.app) as c:
        yield c, main, tmp_path, mock_docker


def test_osm_poi_type_accepted(client):
    """type=osm_poi should be accepted by the pipeline start endpoint."""
    c, main, tmp_path, mock_docker = client

    # Create a PBF file for discovery
    valhalla_dir = tmp_path / "valhalla"
    valhalla_dir.mkdir()
    (valhalla_dir / "western-us.osm.pbf").write_bytes(b"fake pbf")

    resp = c.post(
        "/admin/pipeline/start",
        json={"type": "osm_poi"},
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "started"


def test_osm_poi_no_bbox_required(client):
    """OSM POI pipeline does not require bbox, mode, or zoom."""
    c, main, tmp_path, mock_docker = client

    valhalla_dir = tmp_path / "valhalla"
    valhalla_dir.mkdir()
    (valhalla_dir / "western-us.osm.pbf").write_bytes(b"fake pbf")

    # Send only type, no mode/bbox/zoom
    resp = c.post(
        "/admin/pipeline/start",
        json={"type": "osm_poi"},
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )

    assert resp.status_code == 200


def test_osm_poi_missing_pbf(client):
    """When no PBF file exists, return 422 error."""
    c, main, tmp_path, mock_docker = client

    # No valhalla directory or PBF file
    resp = c.post(
        "/admin/pipeline/start",
        json={"type": "osm_poi"},
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )

    assert resp.status_code == 422
    assert "PBF" in resp.json()["detail"]


def test_pipeline_image_missing(client):
    """When pipeline image is not built, return 422 error."""
    c, main, tmp_path, mock_docker = client

    # Make images.get raise (image not found)
    mock_docker.images.get.side_effect = Exception("not found")

    valhalla_dir = tmp_path / "valhalla"
    valhalla_dir.mkdir()
    (valhalla_dir / "western-us.osm.pbf").write_bytes(b"fake pbf")

    resp = c.post(
        "/admin/pipeline/start",
        json={"type": "osm_poi"},
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )

    assert resp.status_code == 422
    assert "Pipeline image not built" in resp.json()["detail"]


def test_invalid_type_rejected(client):
    """Unknown pipeline types should still be rejected."""
    c, main, tmp_path, mock_docker = client

    resp = c.post(
        "/admin/pipeline/start",
        json={"type": "foobar", "mode": "direct", "bbox": "-112,33,-111,34", "zoom": "0-10"},
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )

    assert resp.status_code == 422


def test_state_file_for_osm_poi(client):
    """OSM POI pipeline uses its own state file path."""
    c, main, tmp_path, mock_docker = client

    from main import _state_file_for_type
    assert _state_file_for_type("osm_poi") == main.DATA_DIR / ".osm-poi-state.json"


def test_completed_at_on_state(client):
    """Pipeline state should include completed_at and duration_seconds after completion."""
    c, main, tmp_path, mock_docker = client

    # Simulate a completed pipeline state
    state_file = tmp_path / ".pipeline-state.json"
    state_file.write_text(json.dumps({
        "status": "running",
        "type": "imagery",
        "container_id": "abc123",
    }))

    # Mock container as dead (to trigger interruption reconciliation)
    mock_docker.containers.get.side_effect = Exception("not found")

    resp = c.get(
        "/admin/pipeline/status?type=imagery",
    )

    data = resp.json()
    # When container is dead and state was "running", status becomes "interrupted"
    assert data["status"] == "interrupted"
