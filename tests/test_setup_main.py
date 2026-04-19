"""Tests for setup/main.py — FastAPI setup wizard with CSRF protection."""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from setup.main import app, CSRF_TOKEN, current_state
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


@pytest.fixture
def fake_keyring_socket(tmp_path):
    """Unix-socket mock for the keyring agent — matches the real agent's
    one-message-per-connection protocol."""
    import socket
    import threading
    socket_path = tmp_path / "keyring.sock"
    captured = []
    stop_event = threading.Event()

    def server():
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(socket_path))
        srv.listen(5)
        srv.settimeout(0.1)
        try:
            while not stop_event.is_set():
                try:
                    conn, _ = srv.accept()
                except socket.timeout:
                    continue
                try:
                    data = b""
                    while b"\n" not in data:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    try:
                        msg = json.loads(data.decode().strip())
                        captured.append(msg)
                        conn.sendall(b'{"ok":true}\n')
                    except Exception:
                        conn.sendall(b'{"ok":false,"error":"bad_json"}\n')
                finally:
                    conn.close()
        finally:
            srv.close()

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    yield socket_path, captured
    stop_event.set()
    thread.join(timeout=2.0)


class TestCredentialsEndpointKeyring:
    def test_post_credentials_writes_each_field(self, fake_keyring_socket, monkeypatch):
        socket_path, captured = fake_keyring_socket
        monkeypatch.setattr("setup.main.KEYRING_SOCKET_PATH", str(socket_path))
        client = TestClient(app)
        resp = client.post(
            "/api/credentials",
            json={"m2m_username": "alice", "m2m_token": "t0k3n",
                  "copernicus_username": "bob", "copernicus_password": "secret"},
            headers={"X-CSRF-Token": CSRF_TOKEN},
        )
        assert resp.status_code == 200
        # Must write exactly 4 store actions with specific fields
        assert len(captured) == 4
        stored = {(m["type"], m["key"]): m["value"] for m in captured}
        assert stored[("m2m", "username")] == "alice"
        assert stored[("m2m", "token")] == "t0k3n"
        assert stored[("copernicus", "username")] == "bob"
        assert stored[("copernicus", "password")] == "secret"

    def test_post_credentials_skips_empty_fields(self, fake_keyring_socket, monkeypatch):
        socket_path, captured = fake_keyring_socket
        monkeypatch.setattr("setup.main.KEYRING_SOCKET_PATH", str(socket_path))
        client = TestClient(app)
        resp = client.post(
            "/api/credentials",
            json={"m2m_username": "alice", "m2m_token": "",
                  "copernicus_username": "", "copernicus_password": ""},
            headers={"X-CSRF-Token": CSRF_TOKEN},
        )
        assert resp.status_code == 200
        # Only m2m/username should have been written; blanks skipped
        assert len(captured) == 1
        assert captured[0]["type"] == "m2m"
        assert captured[0]["key"] == "username"

    def test_post_credentials_surfaces_socket_failure(self, monkeypatch, tmp_path):
        missing = tmp_path / "does-not-exist.sock"
        monkeypatch.setattr("setup.main.KEYRING_SOCKET_PATH", str(missing))
        client = TestClient(app)
        resp = client.post(
            "/api/credentials",
            json={"m2m_username": "alice", "m2m_token": "t"},
            headers={"X-CSRF-Token": CSRF_TOKEN},
        )
        assert resp.status_code == 503
        assert "systemctl" in resp.json()["detail"]


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


class TestLaunchReTargetsSymlink:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_launch_repoints_data_symlink(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        env_file = repo_root / ".env"
        new_data = tmp_path / "custom_data"
        new_data.mkdir()
        env_file.write_text(f"DATA_HOST_PATH={new_data}\n")
        old_data = tmp_path / "old_data"
        old_data.mkdir()
        (repo_root / "data").symlink_to(old_data)

        from setup import main as mod
        monkeypatch.setattr(mod, "ENV_PATH", str(env_file))

        async def fake_run(args, cwd, on_output, env_extra=None):
            return 0
        monkeypatch.setattr(mod, "run_command", fake_run)

        async def fake_exec(*args, **kwargs):
            class P:
                returncode = 0
                async def communicate(self):
                    return (b"", b"")
            return P()
        monkeypatch.setattr(mod.asyncio, "create_subprocess_exec", fake_exec)

        monkeypatch.chdir(repo_root)
        resp = self.client.post("/api/launch", headers=self.headers)
        assert resp.status_code == 200
        assert (repo_root / "data").resolve() == new_data.resolve()


class TestStartRequestLayerConfig:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_start_accepts_per_layer_bbox(self, tmp_path, monkeypatch):
        from setup import main as mod
        async def fake_run(args, cwd, on_output, env_extra=None):
            return 0
        monkeypatch.setattr(mod, "run_command", fake_run)
        resp = self.client.post("/api/start", json={
            "bbox": "-114.8,31.3,-109.0,37.0",
            "layers": {"basemap": "download", "base_imagery": "naip",
                       "detail_imagery": "skip", "elevation": "download"},
            "data_path": str(tmp_path),
            "base_imagery_zoom": 15,
            "layer_bbox": {
                "basemap": "-114.8,31.3,-109.0,37.0",
                "base_imagery": "-113.0,33.0,-111.0,34.0",
                "detail_imagery": ""
            }
        }, headers=self.headers)
        assert resp.status_code == 200, resp.text

    def test_start_rejects_unknown_field(self):
        resp = self.client.post("/api/start", json={
            "bbox": "-114.8,31.3,-109.0,37.0",
            "layers": {"basemap": "download"},
            "data_path": "/srv/geographica/data",
            "random_garbage_field": "boom",
        }, headers=self.headers)
        assert resp.status_code == 422
