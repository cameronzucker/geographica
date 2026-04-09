"""Tests for GPS /status endpoint.

Tests three states:
1. GPS working with 3D fix
2. GPS connected but no fix (indoors)
3. gpsd unreachable
"""

import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

# Add parent dir to path so we can import main
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def client():
    """Create a TestClient with mocked startup tasks (no real gpsd connection)."""
    # Remove cached main module to force clean re-import
    if "main" in sys.modules:
        del sys.modules["main"]

    # Patch asyncio.create_task to prevent actual gpsd connection attempts
    with patch("asyncio.create_task"):
        import main

    # Clear startup handlers so TestClient doesn't spawn real gpsd tasks
    main.app.router.on_startup.clear()

    with TestClient(main.app) as c:
        yield c, main


def test_status_3d_fix(client):
    """GPS working with 3D fix returns ok status with fix=3d and accuracy."""
    c, main = client
    main._gps_connected = True
    main._position = {
        "lat": 33.45, "lon": -112.07, "alt": 340.0,
        "speed": 0.0, "heading": 0.0, "fix": 3,
        "stale": False, "accuracy": 2.1,
        "timestamp": "2026-04-09T00:00:00+00:00",
    }

    resp = c.get("/status")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "ok"
    assert data["fix"] == "3d"
    assert data["accuracy_m"] == 2.1
    # Security: lat/lon must NOT be in the response
    assert "lat" not in data
    assert "lon" not in data
    assert "alt" not in data
    assert "speed" not in data
    assert "heading" not in data


def test_status_2d_fix(client):
    """GPS working with 2D fix returns ok status with fix=2d."""
    c, main = client
    main._gps_connected = True
    main._position = {
        "lat": 33.45, "lon": -112.07, "alt": 0.0,
        "speed": 0.0, "heading": 0.0, "fix": 2,
        "stale": False, "accuracy": 5.3,
        "timestamp": "2026-04-09T00:00:00+00:00",
    }

    resp = c.get("/status")
    data = resp.json()

    assert data["status"] == "ok"
    assert data["fix"] == "2d"
    assert data["accuracy_m"] == 5.3


def test_status_no_fix(client):
    """GPS connected but no fix (indoors/no hardware) returns ok with fix=none."""
    c, main = client
    main._gps_connected = True
    main._position = {
        "lat": 0.0, "lon": 0.0, "alt": 0.0,
        "speed": 0.0, "heading": 0.0, "fix": 0,
        "stale": True, "accuracy": None,
        "timestamp": "2026-04-09T00:00:00+00:00",
    }

    resp = c.get("/status")
    data = resp.json()

    assert data["status"] == "ok"
    assert data["fix"] == "none"
    assert data["accuracy_m"] is None


def test_status_no_gpsd(client):
    """gpsd unreachable returns no_gpsd status with null fix."""
    c, main = client
    main._gps_connected = False
    main._position = {
        "lat": 0.0, "lon": 0.0, "alt": 0.0,
        "speed": 0.0, "heading": 0.0, "fix": 0,
        "stale": True, "accuracy": None,
        "timestamp": "2026-04-09T00:00:00+00:00",
    }

    resp = c.get("/status")
    data = resp.json()

    assert data["status"] == "no_gpsd"
    assert data["fix"] is None
    assert data["accuracy_m"] is None
