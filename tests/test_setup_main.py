"""Tests for setup/main.py — FastAPI setup wizard with CSRF protection."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from setup.main import app, CSRF_TOKEN, CREDENTIALS_PATH, current_state
from fastapi.testclient import TestClient


class TestCSRFProtection:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)

    def test_post_without_csrf_returns_403(self):
        resp = self.client.post("/api/validate-bbox",
            json={"bbox": "-114.8,31.3,-109.0,37.0"})
        assert resp.status_code == 403

    def test_post_with_wrong_csrf_returns_403(self):
        resp = self.client.post("/api/validate-bbox",
            json={"bbox": "-114.8,31.3,-109.0,37.0"},
            headers={"X-CSRF-Token": "wrong"})
        assert resp.status_code == 403

    def test_post_with_correct_csrf_succeeds(self):
        resp = self.client.post("/api/validate-bbox",
            json={"bbox": "-114.8,31.3,-109.0,37.0"},
            headers={"X-CSRF-Token": CSRF_TOKEN})
        assert resp.status_code == 200

    def test_get_does_not_require_csrf(self):
        resp = self.client.get("/api/system")
        assert resp.status_code == 200

    def test_csrf_token_is_64_hex_chars(self):
        assert len(CSRF_TOKEN) == 64
        assert all(c in "0123456789abcdef" for c in CSRF_TOKEN)


class TestSystemEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)

    def test_system_returns_json(self):
        resp = self.client.get("/api/system")
        assert resp.status_code == 200
        data = resp.json()
        assert "host_ip" in data
        assert "ram_mb" in data
        assert "storage" in data
        assert "existing_env" in data

    def test_ram_mb_is_positive(self):
        resp = self.client.get("/api/system")
        assert resp.json()["ram_mb"] > 0

    def test_ram_profile_included(self):
        resp = self.client.get("/api/system")
        data = resp.json()
        assert "ram_profile" in data
        assert "nominatim_memory" in data["ram_profile"]


class TestPresetsEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)

    def test_returns_presets(self):
        resp = self.client.get("/api/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert "western_us" in data
        assert "arizona" in data

    def test_presets_have_bbox(self):
        resp = self.client.get("/api/presets")
        data = resp.json()
        for name, preset in data.items():
            assert "bbox" in preset, f"Preset {name} missing bbox"


class TestBboxValidation:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_valid_bbox(self):
        resp = self.client.post("/api/validate-bbox",
            json={"bbox": "-114.8,31.3,-109.0,37.0"},
            headers=self.headers)
        assert resp.json()["valid"] is True

    def test_invalid_bbox(self):
        resp = self.client.post("/api/validate-bbox",
            json={"bbox": "abc,31.3,-102.0,49.0"},
            headers=self.headers)
        assert resp.json()["valid"] is False

    def test_empty_bbox(self):
        resp = self.client.post("/api/validate-bbox",
            json={"bbox": ""},
            headers=self.headers)
        assert resp.json()["valid"] is False


class TestConfigEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}
        self.env_file = tmp_path / ".env"

    def test_config_writes_env(self, tmp_path, monkeypatch):
        env_path = tmp_path / ".env"
        monkeypatch.setattr("setup.main.ENV_PATH", str(env_path))
        resp = self.client.post("/api/config", json={
            "tls_mode": "http",
            "bbox": "-114.8,31.3,-109.0,37.0",
            "data_path": "/srv/geographica/data",
        }, headers=self.headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert env_path.exists()
        content = env_path.read_text()
        assert "DATA_HOST_PATH=/srv/geographica/data" in content

    def test_config_rejects_invalid_bbox(self, tmp_path, monkeypatch):
        env_path = tmp_path / ".env"
        monkeypatch.setattr("setup.main.ENV_PATH", str(env_path))
        resp = self.client.post("/api/config", json={
            "tls_mode": "http",
            "bbox": "not-a-bbox",
            "data_path": "/srv/geographica/data",
        }, headers=self.headers)
        assert resp.status_code == 400

    def test_config_rejects_deprecated_tls_mode(self):
        """Stale clients POSTing pre-canonicalization TLS_MODE values should 400."""
        for bad in ("self-signed", "external", "existing", "acme", ""):
            resp = self.client.post("/api/config", json={
                "tls_mode": bad,
                "bbox": "-124.8,31.3,-102.0,49.0",
                "data_path": "/srv/geographica/data",
            }, headers=self.headers)
            assert resp.status_code == 400, f"expected 400 for tls_mode={bad!r}, got {resp.status_code}"
            assert "tls_mode" in resp.json().get("detail", "").lower()


class TestCredentialsEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_credentials_path_is_hardcoded(self):
        assert CREDENTIALS_PATH == "/srv/geographica/data/credentials.json"

    def test_credentials_writes_file(self, tmp_path, monkeypatch):
        cred_path = tmp_path / "credentials.json"
        monkeypatch.setattr("setup.main.CREDENTIALS_PATH", str(cred_path))
        resp = self.client.post("/api/credentials", json={
            "m2m_username": "user",
            "m2m_token": "tok",
            "copernicus_client_id": "cid",
            "copernicus_client_secret": "csec",
        }, headers=self.headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        import json
        data = json.loads(cred_path.read_text())
        assert data["m2m_username"] == "user"

    def test_credentials_requires_csrf(self):
        resp = self.client.post("/api/credentials", json={
            "m2m_username": "user",
            "m2m_token": "tok",
            "copernicus_client_id": "cid",
            "copernicus_client_secret": "csec",
        })
        assert resp.status_code == 403


class TestStatusEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)

    def test_returns_state(self):
        resp = self.client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "step" in data
        assert "running" in data

    def test_initial_state_is_idle(self):
        resp = self.client.get("/api/status")
        data = resp.json()
        assert data["step"] == "idle"
        assert data["running"] is False


class TestIndexRoute:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)

    def test_index_returns_html(self, tmp_path, monkeypatch):
        static_dir = tmp_path / "static"
        static_dir.mkdir()
        index = static_dir / "index.html"
        index.write_text('<html><meta name="csrf-token" content="PLACEHOLDER"></html>')
        monkeypatch.setattr("setup.main.STATIC_DIR", str(static_dir))
        resp = self.client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert CSRF_TOKEN in resp.text
        assert "PLACEHOLDER" not in resp.text


class TestCORSHeaders:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)

    def test_cors_allows_localhost_8099(self):
        resp = self.client.options("/api/system", headers={
            "Origin": "http://localhost:8099",
            "Access-Control-Request-Method": "GET",
        })
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:8099"

    def test_cors_rejects_other_origin(self):
        resp = self.client.options("/api/system", headers={
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "GET",
        })
        # Should not include the evil origin
        assert resp.headers.get("access-control-allow-origin") != "http://evil.com"


class TestValidatePathEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_valid_path(self):
        resp = self.client.post("/api/validate-path",
            json={"path": "/srv/geographica/data"},
            headers=self.headers)
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_invalid_path(self):
        resp = self.client.post("/api/validate-path",
            json={"path": "/etc/passwd"},
            headers=self.headers)
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_requires_csrf(self):
        resp = self.client.post("/api/validate-path",
            json={"path": "/srv/geographica/data"})
        assert resp.status_code == 403

    def test_path_traversal_rejected(self):
        resp = self.client.post("/api/validate-path",
            json={"path": "/srv/../etc/passwd"},
            headers=self.headers)
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_empty_path_rejected(self):
        resp = self.client.post("/api/validate-path",
            json={"path": ""},
            headers=self.headers)
        assert resp.status_code == 200
        assert resp.json()["valid"] is False


class TestPreflightEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)

    def test_preflight_returns_checks(self):
        resp = self.client.get("/api/preflight")
        assert resp.status_code == 200
        data = resp.json()
        assert "checks" in data
        assert isinstance(data["checks"], list)
        assert len(data["checks"]) > 0

    def test_preflight_checks_have_required_fields(self):
        resp = self.client.get("/api/preflight")
        data = resp.json()
        for check in data["checks"]:
            assert "name" in check
            assert "status" in check
            assert check["status"] in ("ok", "missing", "error")


class TestFixDependencyEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_requires_csrf(self):
        resp = self.client.post("/api/fix-dependency",
            json={"dependency": "docker"})
        assert resp.status_code == 403

    def test_rejects_unknown_dependency(self):
        resp = self.client.post("/api/fix-dependency",
            json={"dependency": "rm -rf /"},
            headers=self.headers)
        assert resp.status_code == 400

    def test_rejects_shell_injection(self):
        resp = self.client.post("/api/fix-dependency",
            json={"dependency": "docker; rm -rf /"},
            headers=self.headers)
        assert resp.status_code == 400


class TestCreateDirectoryEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_requires_csrf(self):
        resp = self.client.post("/api/create-directory",
            json={"path": "/srv/geographica/data"})
        assert resp.status_code == 403

    def test_rejects_disallowed_path(self):
        resp = self.client.post("/api/create-directory",
            json={"path": "/etc/evil"},
            headers=self.headers)
        assert resp.status_code == 400

    def test_creates_directory_in_allowed_path(self, tmp_path, monkeypatch):
        # Monkeypatch the ALLOWED_PATH_PREFIXES to include tmp_path
        import setup.config as config_mod
        original = config_mod.ALLOWED_PATH_PREFIXES
        monkeypatch.setattr(config_mod, "ALLOWED_PATH_PREFIXES", original + (str(tmp_path),))

        test_dir = tmp_path / "test_create" / "subdir"
        resp = self.client.post("/api/create-directory",
            json={"path": str(test_dir)},
            headers=self.headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert test_dir.exists()
