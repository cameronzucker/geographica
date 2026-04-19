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

    def test_start_rejects_bbox_outside_supported_regions(self):
        """2026-04-21 beta-tester report: a bbox outside the 11-state
        western-US set used to fall back to downloading all 11 states
        anyway (wasted bandwidth, wrong data). After the runner.py fix
        that returns an empty state list for unsupported bboxes,
        /api/start must reject such bboxes with a clear 400 listing
        the supported region names, instead of kicking off a broken
        pipeline."""
        # Middle of the North Atlantic — far from any US state.
        resp = self.client.post("/api/start", json={
            "bbox": "-40,40,-35,45",
            "layers": {"basemap": "download", "base_imagery": "skip",
                        "detail_imagery": "skip", "elevation": "skip"},
            "data_path": "/srv/geographica/data",
        }, headers=self.headers)
        assert resp.status_code == 400, resp.text
        detail = resp.json()["detail"]
        assert "does not intersect" in detail
        assert "48 contiguous US states" in detail
        # Names at least a few recognisable states so the user can tell
        # what's available.
        assert "texas" in detail
        assert "new-york" in detail

    def test_start_accepts_bbox_when_basemap_is_skipped(self, tmp_path, monkeypatch):
        """If the user skips every OSM-consuming layer
        (basemap + base_imagery), the bbox doesn't need to intersect
        any Geofabrik state. Elevation-only or imagery-only pipelines
        can target arbitrary regions."""
        from setup import main as mod
        async def fake_run(args, cwd, on_output, env_extra=None):
            return 0
        monkeypatch.setattr(mod, "run_command", fake_run)
        resp = self.client.post("/api/start", json={
            "bbox": "-40,40,-35,45",  # mid-Atlantic, no state intersection
            "layers": {"basemap": "skip", "base_imagery": "skip",
                        "detail_imagery": "skip", "elevation": "download"},
            "data_path": str(tmp_path),
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


class TestRunPipelineInvokesSubprocess:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_run_pipeline_calls_run_command_per_active_step(self, tmp_path, monkeypatch):
        import shutil
        from setup import main as mod
        from setup.pipeline_steps import ALL_PIPELINE_STEPS, filter_active_steps
        calls = []

        async def fake_run(args, cwd, on_output, env_extra=None):
            calls.append(args)
            on_output("stdout", b"")
            return 0

        monkeypatch.setattr(mod, "run_command", fake_run)
        monkeypatch.setattr(shutil, "disk_usage",
                            lambda p: shutil._ntuple_diskusage(100*1024**3, 10*1024**3, 90*1024**3))

        body = mod.StartRequest(
            bbox="-114.8,31.3,-109.0,37.0",
            layers={"basemap": "download", "base_imagery": "naip",
                    "detail_imagery": "skip", "elevation": "download"},
            data_path=str(tmp_path),
            base_imagery_zoom=15,
        )
        import asyncio as _a
        _a.run(mod._run_pipeline(body))

        expected_active = filter_active_steps(ALL_PIPELINE_STEPS, body.layers)
        expected_active_ids = [s.id for s in expected_active]
        assert len(expected_active_ids) == 12  # 13 total minus detail_imagery (skipped)
        assert len(calls) == 12
        ctx = {
            "bbox": body.bbox,
            "layer_bbox": {},
            "layers": body.layers,
            "data_path": body.data_path,
            "scripts_path": str(Path(mod.__file__).parent.parent / "scripts"),
            "base_imagery_zoom": body.base_imagery_zoom,
        }
        for step, actual in zip(expected_active, calls):
            assert actual == step.cmd_builder(ctx), f"Step {step.id} cmd mismatch"

    def test_run_pipeline_error_clears_running_flag(self, tmp_path, monkeypatch):
        """Every exit branch (including errors) must clear running=False."""
        import shutil
        from setup import main as mod
        call_count = [0]

        async def fake_run(args, cwd, on_output, env_extra=None):
            call_count[0] += 1
            if call_count[0] == 2:
                on_output("stderr", b"boom")
                return 1  # error on second step
            on_output("stdout", b"")
            return 0

        monkeypatch.setattr(mod, "run_command", fake_run)
        monkeypatch.setattr(shutil, "disk_usage",
                            lambda p: shutil._ntuple_diskusage(100*1024**3, 10*1024**3, 90*1024**3))

        body = mod.StartRequest(
            bbox="-114.8,31.3,-109.0,37.0",
            layers={"basemap": "download", "base_imagery": "naip",
                    "detail_imagery": "skip", "elevation": "download"},
            data_path=str(tmp_path),
            base_imagery_zoom=15,
        )
        mod.current_state["running"] = True
        import asyncio as _a
        _a.run(mod._run_pipeline(body))

        assert mod.current_state["running"] is False
        assert mod.current_state["step"] == "error"


class TestStartTOCTOU:
    @pytest.mark.asyncio
    async def test_start_toctou_under_real_await(self, monkeypatch):
        """Forces an async yield point, fires two concurrent requests,
        asserts exactly one wins (200) + one gets 409."""
        import asyncio as _a
        import httpx
        from setup.main import app, CSRF_TOKEN, current_state
        current_state["running"] = False

        monkeypatch.setattr("setup.main.validate_bbox", lambda b: True)

        spawn_count = [0]

        async def fake_pipeline(body):
            spawn_count[0] += 1
            await _a.Event().wait()  # hang so we observe both requests hit the gate

        monkeypatch.setattr("setup.main._run_pipeline", fake_pipeline)

        payload = {"bbox": "-124,31,-102,49", "data_path": "/tmp", "layers": {}}
        headers = {"X-CSRF-Token": CSRF_TOKEN}

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            async def fire():
                return await c.post("/api/start", json=payload, headers=headers)

            t1 = _a.create_task(fire())
            await _a.sleep(0.05)
            t2 = _a.create_task(fire())
            await _a.sleep(0.05)
            r1, r2 = await _a.gather(t1, t2)

        current_state["running"] = False  # reset
        statuses = sorted([r1.status_code, r2.status_code])
        assert statuses == [200, 409], f"expected one 200 + one 409, got {statuses}"
        assert spawn_count[0] == 1


def test_ws_progress_snapshots_buffer():
    """Source-level assertion that ws_progress iterates a snapshot, not the live deque."""
    from setup import main as mod
    import inspect
    src = inspect.getsource(mod.ws_progress)
    assert "list(progress_buffer)" in src or "list(mod.progress_buffer)" in src or \
           "snapshot" in src.lower(), (
        "ws_progress must snapshot progress_buffer via list(...) to avoid "
        "deque-mutated-during-iteration under concurrent pipeline output"
    )


def test_broadcast_uses_gather_with_timeout():
    """Source-level check: broadcast parallelizes via gather + per-socket timeout."""
    from setup import main as mod
    import inspect
    src = inspect.getsource(mod.broadcast)
    assert "asyncio.gather" in src
    assert "wait_for" in src or "timeout" in src.lower()


class TestCheckpointResetEndpoint:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_reset_endpoint_exists(self, tmp_path):
        from setup.main import ALLOWED_PATH_PREFIXES  # may or may not exist
        # Use a path under /tmp which is allowlist-rejected, so we verify the
        # endpoint returns 400 (not 404/405). A 200 is also acceptable if
        # /tmp is conditionally allowed.
        resp = self.client.post("/api/checkpoint/reset",
                                json={"data_path": "/tmp"},
                                headers=self.headers)
        assert resp.status_code in (200, 400), f"expected 200 or 400, got {resp.status_code}"

    def test_reset_endpoint_clears_existing_checkpoint(self, tmp_path, monkeypatch):
        # Bypass path allowlist so the endpoint reaches the delete logic.
        from setup import main as mod
        monkeypatch.setattr(mod, "validate_path", lambda p: {"valid": True})
        # Seed a checkpoint file.
        ckpt = tmp_path / ".setup_checkpoint.json"
        ckpt.write_text('{"completed": ["x"]}')
        assert ckpt.exists()
        resp = self.client.post("/api/checkpoint/reset",
                                json={"data_path": str(tmp_path)},
                                headers=self.headers)
        assert resp.status_code == 200, resp.text
        assert not ckpt.exists()


def test_disk_error_does_not_broadcast_pipeline_done(tmp_path, monkeypatch):
    import shutil
    from setup import main as mod
    events = []
    async def capture(evt):
        events.append(evt)
    monkeypatch.setattr(mod, "broadcast", capture)

    monkeypatch.setattr(
        shutil, "disk_usage",
        lambda p: shutil._ntuple_diskusage(1, 1, 1),  # 1 byte free — far below 5 GB
    )
    body = mod.StartRequest(
        bbox="-114.8,31.3,-109.0,37.0",
        layers={"basemap": "download"},
        data_path=str(tmp_path),
    )
    import asyncio as _a
    _a.run(mod._run_pipeline(body))
    assert not any(e.get("type") == "pipeline_done" for e in events), (
        "disk-critically-low must NOT broadcast success"
    )
    assert any(e.get("type") == "error" for e in events)
    assert mod.current_state["step"] == "error"


def test_pipeline_error_broadcast_includes_step_and_stderr(tmp_path, monkeypatch):
    import shutil
    from setup import main as mod
    events = []
    async def capture(evt):
        events.append(evt)
    monkeypatch.setattr(mod, "broadcast", capture)
    monkeypatch.setattr(shutil, "disk_usage",
                        lambda p: shutil._ntuple_diskusage(100*1024**3, 10*1024**3, 90*1024**3))

    async def failing_run(args, cwd, on_output, env_extra=None):
        on_output("stderr", b"boom stack trace line 1\nline 2\n")
        return 1

    monkeypatch.setattr(mod, "run_command", failing_run)
    body = mod.StartRequest(
        bbox="-114.8,31.3,-109.0,37.0",
        layers={"basemap": "download"},
        data_path=str(tmp_path),
    )
    import asyncio as _a
    _a.run(mod._run_pipeline(body))
    errors = [e for e in events if e.get("type") == "error"]
    assert errors
    e = errors[0]
    assert "step" in e
    assert "boom" in (e.get("message") or "")


class TestPreflightCoversAllDeps:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.client = TestClient(app)

    def test_preflight_includes_tippecanoe(self):
        resp = self.client.get("/api/preflight")
        names = [c["name"] for c in resp.json()["checks"]]
        assert "tippecanoe" in names

    def test_preflight_includes_pipeline_python_deps(self):
        resp = self.client.get("/api/preflight")
        names = [c["name"] for c in resp.json()["checks"]]
        assert "python-pipeline-deps" in names

    def test_preflight_includes_keyring_agent(self):
        resp = self.client.get("/api/preflight")
        names = [c["name"] for c in resp.json()["checks"]]
        assert "keyring-agent" in names

    def test_preflight_includes_cgroup_memory(self):
        resp = self.client.get("/api/preflight")
        names = [c["name"] for c in resp.json()["checks"]]
        assert "cgroup-memory" in names

    def test_preflight_includes_openssl(self):
        resp = self.client.get("/api/preflight")
        names = [c["name"] for c in resp.json()["checks"]]
        assert "openssl" in names

    def test_every_check_has_fix_hint(self):
        from setup.main import PREFLIGHT_CHECKS
        for entry in PREFLIGHT_CHECKS:
            assert "fix_hint" in entry, f"{entry.get('name','?')} missing fix_hint"


class TestFixDependencyRemoved:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_fix_dependency_endpoint_returns_404(self):
        resp = self.client.post("/api/fix-dependency",
                                json={"dependency": "docker"},
                                headers=self.headers)
        assert resp.status_code == 404


def test_main_binds_localhost_only():
    import re
    src = Path("setup/main.py").read_text()
    m = re.search(r'if __name__ == "__main__":[\s\S]+?uvicorn\.run\([^)]+\)', src)
    assert m, "could not find __main__ uvicorn.run"
    block = m.group(0)
    assert 'host="127.0.0.1"' in block or "host='127.0.0.1'" in block, \
        "must bind 127.0.0.1"
    assert '"0.0.0.0"' not in block, "must not bind 0.0.0.0"
    assert "os.getenv" not in block and "os.environ" not in block, \
        "no env-var backdoor allowed for host"


def test_progress_buffer_maxlen_is_5000():
    from setup.main import progress_buffer
    assert progress_buffer.maxlen == 5000


def test_launch_builds_pipeline_profile_when_image_missing(tmp_path, monkeypatch):
    from setup import main as mod
    recorded = []
    async def fake_run(args, cwd, on_output, env_extra=None):
        recorded.append(args)
        return 0
    monkeypatch.setattr(mod, "run_command", fake_run)

    # Fake `docker image inspect` to return non-zero (image missing)
    # AND fake `docker compose ps` to return empty.
    class _ProcMissing:
        returncode = 1
        async def wait(self): return None
        async def communicate(self): return (b"", b"")
    class _ProcOK:
        returncode = 0
        async def wait(self): return None
        async def communicate(self): return (b"", b"")

    async def fake_exec(*args, **kwargs):
        # Image inspect -> missing
        if args and args[0] == "docker" and len(args) > 2 and args[1] == "image" and args[2] == "inspect":
            return _ProcMissing()
        return _ProcOK()

    monkeypatch.setattr(mod.asyncio, "create_subprocess_exec", fake_exec)

    env = tmp_path / ".env"
    env.write_text(f"DATA_HOST_PATH={tmp_path}\n")
    monkeypatch.setattr(mod, "ENV_PATH", str(env))

    # Isolate the `./data` symlink retarget to tmp_path. post_launch resolves
    # the link path via `Path.cwd() / "data"` (so setup.sh invoked from the
    # repo root retargets the repo's symlink). Without this chdir, pytest
    # inherits the repo as cwd and would hijack the real ./data symlink to
    # a pytest tmpdir that gets cleaned up after the test, leaving a
    # dangling symlink that breaks the next `docker compose up`.
    monkeypatch.chdir(tmp_path)

    client = TestClient(mod.app)
    resp = client.post("/api/launch", headers={"X-CSRF-Token": mod.CSRF_TOKEN})
    assert resp.status_code == 200
    # At least one recorded run_command must include "--profile pipeline" + "build"
    has_pipeline_build = any(
        "--profile" in " ".join(c) and "pipeline" in " ".join(c) and "build" in c
        for c in recorded
    )
    assert has_pipeline_build, f"No pipeline build recorded: {recorded}"


def test_launch_test_has_cwd_isolation():
    """Regression tripwire: the Task 42 pipeline-build test MUST isolate cwd
    via monkeypatch.chdir(tmp_path), otherwise it hijacks the real repo's
    ./data symlink (post_launch uses Path.cwd() / "data" from Task 21)."""
    import inspect
    src = inspect.getsource(test_launch_builds_pipeline_profile_when_image_missing)
    assert "monkeypatch.chdir(tmp_path)" in src, (
        "test_launch_builds_pipeline_profile_when_image_missing must "
        "monkeypatch.chdir(tmp_path) to prevent ./data symlink hijack."
    )


class TestAllHealthyRegex:
    @pytest.mark.parametrize("svcs,expected,why", [
        ([{"Health": "healthy"}, {"Health": "healthy"}], True, "both healthy"),
        ([{"Health": "healthy"}, {"Health": "unhealthy"}], False, "one unhealthy"),
        ([{"Status": "Up 2 days (healthy)"}, {"Status": "Up 2 days (healthy)"}], True, "status healthy"),
        ([{"Status": "Up 2 days (unhealthy)"}], False, "status unhealthy"),
        ([{"Status": "Up 2 days (health: starting)"}], False, "starting is not healthy"),
        ([{"Status": "Up 5 minutes"}], False, "no health annotation"),
        ([{"Status": "Exited (1)"}], False, "exited"),
        ([{}], False, "no fields"),
        ([], False, "empty services list"),
    ])
    def test_all_healthy_classifier(self, svcs, expected, why):
        from setup.main import _is_all_healthy
        assert _is_all_healthy(svcs) is expected, why


class TestExistingEnvPreserved:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_system_includes_parsed_env(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("TLS_MODE=tailscale\nBBOX=-120,30,-100,45\nCUSTOM_KEY=foo\n")
        monkeypatch.setattr("setup.main.ENV_PATH", str(env))
        resp = self.client.get("/api/system")
        data = resp.json()
        assert data["existing_env"] is True
        assert data["existing_env_parsed"]["TLS_MODE"] == "tailscale"
        assert data["existing_env_parsed"]["CUSTOM_KEY"] == "foo"

    def test_post_config_preserves_custom_keys(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("CUSTOM_KEY=preserved\nTLS_MODE=http\n")
        monkeypatch.setattr("setup.main.ENV_PATH", str(env))
        resp = self.client.post("/api/config", json={
            "tls_mode": "https",
            "bbox": "-114.8,31.3,-109.0,37.0",
            "data_path": "/srv/geographica/data",
        }, headers=self.headers)
        assert resp.status_code == 200
        contents = env.read_text()
        assert "CUSTOM_KEY=preserved" in contents
        assert "TLS_MODE=https" in contents
