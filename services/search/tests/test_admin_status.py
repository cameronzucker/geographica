"""Tests for enriched /admin/status endpoint.

Tests the new sub-queries (STT, GPS, TLS, search_stats, disk) added to
the admin_status() function. Docker container listing is mocked to avoid
requiring a running Docker daemon.
"""

import json
import sys
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from fastapi.testclient import TestClient

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def mock_docker():
    """Mock Docker client that returns an empty container list."""
    mock_client = MagicMock()
    mock_client.containers.list.return_value = []
    mock_client.close = MagicMock()
    return mock_client


@pytest.fixture
def client(mock_docker, tmp_path, monkeypatch):
    """Create TestClient with mocked Docker and HTTP clients."""
    if "main" in sys.modules:
        del sys.modules["main"]

    monkeypatch.setenv("POI_DB_PATH", str(tmp_path / "poi.sqlite"))
    monkeypatch.setenv("NOMINATIM_URL", "http://localhost:9999")

    import main

    main._get_docker_client = MagicMock(return_value=mock_docker)

    with TestClient(main.app) as c:
        yield c, main, tmp_path


def _make_poi_db(tmp_path, gnis_count=1000, osm_count=500):
    """Create a real SQLite POI database with poi_features and osm_pois tables."""
    db_path = tmp_path / "poi.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS poi_features (id INTEGER PRIMARY KEY, name TEXT)")
    for i in range(gnis_count):
        conn.execute("INSERT INTO poi_features (name) VALUES (?)", (f"feature_{i}",))
    conn.execute("CREATE TABLE IF NOT EXISTS osm_pois (id INTEGER PRIMARY KEY, name TEXT)")
    for i in range(osm_count):
        conn.execute("INSERT INTO osm_pois (name) VALUES (?)", (f"osm_{i}",))
    conn.commit()
    conn.close()
    return db_path


class TestSTTAggregation:
    """Test STT health check aggregation in /admin/status."""

    def test_stt_healthy(self, client):
        """When STT /health returns 200, status shows backend info."""
        c, main, tmp_path = client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "ok",
            "backend": "cpu",
            "model": "base.en",
            "npu_available": False,
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            resp = c.get("/admin/status")

        data = resp.json()
        assert "stt" in data
        assert data["stt"]["status"] == "ok"
        assert data["stt"]["backend"] == "cpu"
        assert data["stt"]["model"] == "base.en"
        assert data["stt"]["npu_available"] is False

    def test_stt_unreachable(self, client):
        """When STT is unreachable, all fields are present with null/unreachable."""
        c, main, tmp_path = client

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=Exception("connect refused")):
            resp = c.get("/admin/status")

        data = resp.json()
        assert data["stt"]["status"] == "unreachable"
        assert data["stt"]["backend"] is None
        assert data["stt"]["model"] is None
        assert data["stt"]["npu_available"] is None


class TestGPSAggregation:
    """Test GPS status aggregation in /admin/status."""

    def test_gps_ok_3d(self, client):
        """When GPS /status returns ok with 3d fix, status reflects it."""
        c, main, tmp_path = client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "ok",
            "fix": "3d",
            "accuracy_m": 2.1,
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
            resp = c.get("/admin/status")

        data = resp.json()
        assert data["gps"]["status"] == "ok"
        assert data["gps"]["fix"] == "3d"
        assert data["gps"]["accuracy_m"] == 2.1
        # Security: no lat/lon in response
        assert "lat" not in data["gps"]
        assert "lon" not in data["gps"]

    def test_gps_unreachable(self, client):
        """When GPS service is unreachable, all fields present with null/unreachable."""
        c, main, tmp_path = client

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=Exception("connect refused")):
            resp = c.get("/admin/status")

        data = resp.json()
        assert data["gps"]["status"] == "unreachable"
        assert data["gps"]["fix"] is None
        assert data["gps"]["accuracy_m"] is None


class TestTLSAggregation:
    """Test TLS cert detection in /admin/status."""

    def test_tls_no_cert(self, client):
        """When no cert file exists, mode is http and all other fields null."""
        c, main, tmp_path = client

        # Point TLS_CERT_PATH to a non-existent file
        fake_cert = tmp_path / "nonexistent.crt"
        with patch.object(main, "TLS_CERT_PATH", fake_cert):
            resp = c.get("/admin/status")

        data = resp.json()
        assert data["tls"]["mode"] == "http"
        assert data["tls"]["hostname"] is None
        assert data["tls"]["cert_expires"] is None
        assert data["tls"]["cert_valid"] is None

    def test_tls_tailscale_cert(self, client):
        """When Tailscale cert exists, detect mode and parse expiry."""
        c, main, tmp_path = client

        cert_path = tmp_path / "server.crt"
        cert_path.write_text("fake cert")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "notAfter=Jul  7 00:00:00 2026 GMT"

        mock_subject = MagicMock()
        mock_subject.returncode = 0
        mock_subject.stdout = "subject=CN = pandora.twin-bramble.ts.net"

        def mock_subprocess_run(cmd, **kwargs):
            if "-enddate" in cmd:
                return mock_result
            if "-subject" in cmd:
                return mock_subject
            return MagicMock(returncode=1, stdout="")

        with patch.object(main, "TLS_CERT_PATH", cert_path), \
             patch("subprocess.run", side_effect=mock_subprocess_run):
            resp = c.get("/admin/status")

        data = resp.json()
        assert data["tls"]["mode"] == "tailscale"
        assert data["tls"]["hostname"] == "pandora.twin-bramble.ts.net"
        assert data["tls"]["cert_expires"] is not None
        assert data["tls"]["cert_valid"] is True


class TestSearchStats:
    """Test search_stats SQL queries in /admin/status."""

    def test_search_stats_with_osm(self, client):
        """When both GNIS and OSM tables exist, return both counts."""
        c, main, tmp_path = client
        db_path = _make_poi_db(tmp_path, gnis_count=100, osm_count=50)
        main.POI_DB_PATH = str(db_path)

        resp = c.get("/admin/status")
        data = resp.json()

        assert data["search_stats"]["gnis_count"] == 100
        assert data["search_stats"]["osm_pois_count"] == 50
        assert data["search_stats"]["osm_pois_loaded"] is True

    def test_search_stats_no_osm(self, client):
        """When only GNIS table exists (no OSM), osm count is 0."""
        c, main, tmp_path = client
        db_path = tmp_path / "poi.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE poi_features (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO poi_features (name) VALUES ('test')")
        conn.commit()
        conn.close()
        main.POI_DB_PATH = str(db_path)

        resp = c.get("/admin/status")
        data = resp.json()

        assert data["search_stats"]["gnis_count"] == 1
        assert data["search_stats"]["osm_pois_count"] == 0
        assert data["search_stats"]["osm_pois_loaded"] is False


class TestDiskInfo:
    """Test disk usage fields in /admin/status."""

    def test_disk_fields_present(self, client):
        """disk_free_gb, disk_total_gb, disk_used_pct always present."""
        c, main, tmp_path = client

        resp = c.get("/admin/status")
        data = resp.json()

        assert "disk_free_gb" in data
        assert "disk_total_gb" in data
        assert "disk_used_pct" in data
        assert isinstance(data["disk_free_gb"], float)
        assert isinstance(data["disk_total_gb"], float)
        assert isinstance(data["disk_used_pct"], int)


class TestResponseContract:
    """Test that the response always has all top-level keys."""

    def test_all_top_level_keys_present(self, client):
        """Even with Docker errors, all top-level keys must be present."""
        c, main, tmp_path = client

        resp = c.get("/admin/status")
        data = resp.json()

        required_keys = ["services", "data_tasks", "stt", "gps", "tls", "search_stats",
                         "disk_free_gb", "disk_total_gb", "disk_used_pct"]
        for key in required_keys:
            assert key in data, f"Missing required key: {key}"

    def test_stt_sub_keys_always_present(self, client):
        """STT object always has all 4 keys even when unreachable."""
        c, main, tmp_path = client

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=Exception("fail")):
            resp = c.get("/admin/status")

        stt = resp.json()["stt"]
        assert set(stt.keys()) == {"status", "backend", "model", "npu_available"}

    def test_gps_sub_keys_always_present(self, client):
        """GPS object always has all 3 keys even when unreachable."""
        c, main, tmp_path = client

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=Exception("fail")):
            resp = c.get("/admin/status")

        gps = resp.json()["gps"]
        assert set(gps.keys()) == {"status", "fix", "accuracy_m"}

    def test_tls_sub_keys_always_present(self, client):
        """TLS object always has all 4 keys even when no cert."""
        c, main, tmp_path = client

        resp = c.get("/admin/status")

        tls = resp.json()["tls"]
        assert set(tls.keys()) == {"mode", "hostname", "cert_expires", "cert_valid"}
