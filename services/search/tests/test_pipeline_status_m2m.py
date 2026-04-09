"""Tests for M2M pipeline support and service list filtering.

Tests M2M state handling (zoom="n/a"), completed-but-exited detection,
M2M pipeline_start without zoom, and KNOWN_SERVICES filtering.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

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


def test_m2m_state_no_500(client):
    """M2M state with zoom='n/a' returns 200, not 500."""
    c, main, tmp_path, mock_docker = client

    state_file = tmp_path / ".pipeline-state.json"
    state_file.write_text(json.dumps({
        "status": "completed",
        "type": "imagery",
        "mode": "m2m",
        "bbox": "-112,33,-111,34",
        "zoom": "n/a",
    }))

    resp = c.get("/admin/pipeline/status?type=imagery")
    assert resp.status_code == 200


def test_m2m_state_zoom_na_no_tile_estimate(client):
    """zoom='n/a' doesn't trigger tile estimation."""
    c, main, tmp_path, mock_docker = client

    state_file = tmp_path / ".pipeline-state.json"
    state_file.write_text(json.dumps({
        "status": "completed",
        "type": "imagery",
        "mode": "m2m",
        "bbox": "-112,33,-111,34",
        "zoom": "n/a",
    }))

    resp = c.get("/admin/pipeline/status?type=imagery")
    data = resp.json()
    # estimated_tiles should not be computed from zoom="n/a"
    assert data.get("estimated_tiles") is None


def test_completed_but_exited_detected(client):
    """Dead container + 'MBTiles written' in logs -> status=completed."""
    c, main, tmp_path, mock_docker = client

    state_file = tmp_path / ".pipeline-state.json"
    state_file.write_text(json.dumps({
        "status": "running",
        "type": "imagery",
        "mode": "m2m",
        "bbox": "-112,33,-111,34",
        "zoom": "n/a",
        "container_id": "abc123",
        "started_at": "2026-04-08T00:00:00+00:00",
    }))

    # Mock dead container that has "MBTiles written to" in logs
    dead_container = MagicMock()
    dead_container.logs.return_value = b"Processing...\nMBTiles written to /data/imagery.mbtiles\n"
    mock_docker.containers.get.side_effect = None
    mock_docker.containers.get.return_value = dead_container

    # No running pipeline container
    mock_docker.containers.list.return_value = []

    resp = c.get("/admin/pipeline/status?type=imagery")
    data = resp.json()
    assert data["status"] == "completed"


def test_m2m_start_no_zoom(client):
    """M2M start succeeds without zoom field."""
    c, main, tmp_path, mock_docker = client

    # Create fake credentials
    creds_path = tmp_path / ".credentials.json"
    creds_path.write_text(json.dumps({"m2m_username": "test", "m2m_token": "test"}))
    main.CREDENTIALS_PATH = creds_path

    resp = c.post(
        "/admin/pipeline/start",
        json={"type": "imagery", "mode": "m2m", "bbox": "-112,33,-111,34"},
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "started"

    # Verify command does NOT include --zoom
    call_args = mock_docker.containers.run.call_args
    command = call_args[1].get("command") or call_args[0][1]
    assert "--zoom" not in " ".join(command)
    assert "--mode" in command
    assert "m2m" in command
    assert "--staging" in command


def test_m2m_start_requires_bbox(client):
    """M2M start fails without bbox."""
    c, main, tmp_path, mock_docker = client

    creds_path = tmp_path / ".credentials.json"
    creds_path.write_text(json.dumps({"m2m_username": "test", "m2m_token": "test"}))
    main.CREDENTIALS_PATH = creds_path

    resp = c.post(
        "/admin/pipeline/start",
        json={"type": "imagery", "mode": "m2m"},
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )

    assert resp.status_code == 422
    assert "bbox" in resp.json()["detail"].lower()


def test_direct_start_still_requires_zoom(client):
    """Regression: direct mode still requires zoom."""
    c, main, tmp_path, mock_docker = client

    resp = c.post(
        "/admin/pipeline/start",
        json={"type": "imagery", "mode": "direct", "bbox": "-112,33,-111,34"},
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )

    assert resp.status_code == 422
    assert "zoom" in resp.json()["detail"].lower()


def test_pipeline_containers_filtered(client):
    """Pipeline container should not appear in service list."""
    c, main, tmp_path, mock_docker = client

    # Create mock containers including pipeline
    def make_container(name, status="running"):
        m = MagicMock()
        m.name = f"geographica-{name}"
        m.status = status
        m.attrs = {"State": {"Health": {"Status": "healthy"}, "StartedAt": "2026-04-08T00:00:00Z"}}
        return m

    mock_docker.containers.list.return_value = [
        make_container("frontend"),
        make_container("search"),
        make_container("pipeline"),
        make_container("redis"),
    ]

    resp = c.get("/admin/status")
    data = resp.json()
    service_names = [s["name"] for s in data["services"]]

    assert "frontend" in service_names
    assert "search" in service_names
    assert "pipeline" not in service_names
    assert "redis" not in service_names
