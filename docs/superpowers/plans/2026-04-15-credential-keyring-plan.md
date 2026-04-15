# Credential Keyring Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace plaintext JSON credential storage with GNOME Keyring via a host-side agent daemon, eliminating all plaintext credential persistence and Docker env var exposure.

**Architecture:** A host-side Python daemon (`keyring-agent`) manages GNOME Keyring via `secret-tool` and listens on a Unix socket. The search container communicates with it via a client module. Pipeline containers receive credentials through tmpfs-backed files that never touch the SSD. Migration imports existing JSON credentials into the keyring on first run.

**Tech Stack:** Python 3, asyncio (agent), `secret-tool` / `libsecret`, Unix domain sockets, systemd, Docker bind mounts

**Spec:** `docs/superpowers/specs/2026-04-15-credential-keyring-design.md`

---

## File Map

| File | Role | Tasks |
|------|------|-------|
| `services/keyring-agent/agent.py` | Host-side keyring daemon | 1 |
| `services/keyring-agent/geographica-keyring.service` | Systemd unit file | 1 |
| `tests/test_keyring_agent.py` | Agent protocol tests | 1 |
| `services/search/keyring_client.py` | Unix socket client | 2 |
| `tests/test_keyring_client.py` | Client mock tests | 2 |
| `services/search/main.py` | Credential endpoint refactor | 3 |
| `docker-compose.yml` | Mount socket + secrets dir | 3 |
| `scripts/acquire_imagery.py` | Read from /secrets/ tmpfs | 4 |
| `scripts/acquire_sentinel.py` | Read from /secrets/ tmpfs | 4 |
| `bootstrap.sh` | Install gnome-keyring + PAM | 5 |
| `.gitignore` | Add credential patterns | 5 |

**Cross-task dependencies:**
- Tasks 1 and 2 are independent (agent + client, different files) — can run in parallel
- Task 3 depends on Task 2 (uses keyring_client)
- Task 4 is independent (pipeline scripts, different files)
- Task 5 is independent (bootstrap, different file)
- Tasks 1+2 should complete before Task 3

---

## Task 1: Keyring Agent Daemon

**Files:**
- Create: `services/keyring-agent/agent.py`
- Create: `services/keyring-agent/geographica-keyring.service`
- Create: `tests/test_keyring_agent.py`

BEFORE starting work:
1. Read the spec at `docs/superpowers/specs/2026-04-15-credential-keyring-design.md` — focus on "Host-Side Keyring Agent", "Socket Protocol", and "Secret Attributes"
2. Read `dev/testing-pitfalls.md`
Follow TDD: write failing test -> implement fix -> verify green.

**Context:** This is a new host-side daemon (NOT inside Docker). It manages GNOME Keyring via `secret-tool` CLI and listens on a Unix domain socket for JSON requests from the search container. The socket lives at `/run/geographica/keyring.sock`. Systemd manages the process and creates `/run/geographica/` via `RuntimeDirectory`.

**WARNING:** This script runs on the HOST, not in a container. It must use standard Python 3.11+ (Raspberry Pi OS ships this). No pip dependencies — stdlib only.

- [ ] **Step 1: Write agent protocol tests**

Create `tests/test_keyring_agent.py`. Since the agent calls `secret-tool` via subprocess, mock `subprocess.run` in all tests. Test the protocol handlers, not the actual keyring.

```python
"""Tests for keyring agent protocol handlers."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "keyring-agent"))

from agent import handle_request


class TestStoreHandler:
    @patch("agent.subprocess.run")
    def test_store_calls_secret_tool(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = handle_request({"action": "store", "type": "m2m", "key": "username", "value": "testuser"})
        assert result["ok"] is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "secret-tool"
        assert "store" in cmd

    @patch("agent.subprocess.run")
    def test_store_missing_fields_returns_error(self, mock_run):
        result = handle_request({"action": "store", "type": "m2m"})
        assert result["ok"] is False
        assert "error" in result
        mock_run.assert_not_called()


class TestLookupHandler:
    @patch("agent.subprocess.run")
    def test_lookup_returns_value(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="my_secret_value")
        result = handle_request({"action": "lookup", "type": "m2m", "key": "token"})
        assert result["ok"] is True
        assert result["value"] == "my_secret_value"

    @patch("agent.subprocess.run")
    def test_lookup_not_found(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="No such secret")
        result = handle_request({"action": "lookup", "type": "m2m", "key": "token"})
        assert result["ok"] is False
        assert result["error"] == "not_found"


class TestDeleteHandler:
    @patch("agent.subprocess.run")
    def test_delete_calls_clear(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = handle_request({"action": "delete", "type": "m2m"})
        assert result["ok"] is True
        # Should call secret-tool clear for each key (username + token)
        assert mock_run.call_count == 2


class TestStatusHandler:
    @patch("agent.subprocess.run")
    def test_status_detects_configured(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="value")
        result = handle_request({"action": "status"})
        assert result["ok"] is True
        assert result["m2m_configured"] is True
        assert result["copernicus_configured"] is True
        assert result["keyring_available"] is True

    @patch("agent.subprocess.run")
    def test_status_detects_not_configured(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="No such secret")
        result = handle_request({"action": "status"})
        assert result["ok"] is True
        assert result["m2m_configured"] is False
        assert result["copernicus_configured"] is False

    @patch("agent.subprocess.run")
    def test_status_detects_keyring_locked(self, mock_run):
        mock_run.side_effect = Exception("Cannot autolaunch D-Bus")
        result = handle_request({"action": "status"})
        assert result["ok"] is False
        assert result["error"] == "keyring_unavailable"


class TestPrepareSecrets:
    @patch("agent.subprocess.run")
    def test_prepare_writes_tmpfs_file(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="test_value")
        with patch("agent.SECRETS_DIR", tmp_path):
            result = handle_request({"action": "prepare_secrets", "types": ["m2m"], "session_id": "test123"})
        assert result["ok"] is True
        secret_file = tmp_path / "test123.json"
        assert secret_file.exists()
        creds = json.loads(secret_file.read_text())
        assert "m2m_username" in creds

    @patch("agent.subprocess.run")
    def test_cleanup_deletes_file(self, mock_run, tmp_path):
        secret_file = tmp_path / "test123.json"
        secret_file.write_text('{"m2m_username": "x"}')
        with patch("agent.SECRETS_DIR", tmp_path):
            result = handle_request({"action": "cleanup_secrets", "session_id": "test123"})
        assert result["ok"] is True
        assert not secret_file.exists()


class TestUnknownAction:
    def test_unknown_action_returns_error(self):
        result = handle_request({"action": "nonexistent"})
        assert result["ok"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_keyring_agent.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement agent.py**

Create `services/keyring-agent/agent.py`:

```python
#!/usr/bin/env python3
"""Geographica Keyring Agent — host-side daemon for credential management.

Manages GNOME Keyring via secret-tool CLI. Listens on a Unix domain socket
for JSON requests from the search container. Never runs inside Docker.
"""

import json
import logging
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("keyring-agent")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SOCKET_PATH = os.environ.get("KEYRING_SOCKET", "/run/geographica/keyring.sock")
SECRETS_DIR = Path(os.environ.get("SECRETS_DIR", "/run/geographica/secrets"))

# Credential schema: type -> list of keys
CREDENTIAL_KEYS = {
    "m2m": ["username", "token"],
    "copernicus": ["username", "password"],
}


def _secret_tool_store(cred_type: str, key: str, value: str) -> bool:
    """Store a secret in GNOME Keyring."""
    label = f"Geographica {cred_type} {key}"
    try:
        proc = subprocess.run(
            ["secret-tool", "store", "--label", label,
             "application", "geographica",
             "credential_type", cred_type,
             "key", key],
            input=value, capture_output=True, text=True, timeout=10,
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _secret_tool_lookup(cred_type: str, key: str) -> str | None:
    """Look up a secret from GNOME Keyring. Returns None if not found."""
    try:
        proc = subprocess.run(
            ["secret-tool", "lookup",
             "application", "geographica",
             "credential_type", cred_type,
             "key", key],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout.rstrip("\n")
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _secret_tool_clear(cred_type: str, key: str) -> bool:
    """Remove a secret from GNOME Keyring."""
    try:
        proc = subprocess.run(
            ["secret-tool", "clear",
             "application", "geographica",
             "credential_type", cred_type,
             "key", key],
            capture_output=True, text=True, timeout=5,
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def handle_request(req: dict) -> dict:
    """Dispatch a JSON request to the appropriate handler."""
    action = req.get("action")

    if action == "store":
        cred_type = req.get("type")
        key = req.get("key")
        value = req.get("value")
        if not cred_type or not key or not value:
            return {"ok": False, "error": "missing fields: type, key, value required"}
        if cred_type not in CREDENTIAL_KEYS:
            return {"ok": False, "error": f"unknown credential type: {cred_type}"}
        ok = _secret_tool_store(cred_type, key, value)
        return {"ok": ok} if ok else {"ok": False, "error": "secret-tool store failed"}

    elif action == "lookup":
        cred_type = req.get("type")
        key = req.get("key")
        if not cred_type or not key:
            return {"ok": False, "error": "missing fields: type, key required"}
        value = _secret_tool_lookup(cred_type, key)
        if value is not None:
            return {"ok": True, "value": value}
        return {"ok": False, "error": "not_found"}

    elif action == "delete":
        cred_type = req.get("type")
        if not cred_type or cred_type not in CREDENTIAL_KEYS:
            return {"ok": False, "error": "missing or invalid type"}
        for key in CREDENTIAL_KEYS[cred_type]:
            _secret_tool_clear(cred_type, key)
        return {"ok": True}

    elif action == "status":
        try:
            m2m_ok = _secret_tool_lookup("m2m", "username") is not None
            cop_ok = _secret_tool_lookup("copernicus", "username") is not None
            return {"ok": True, "m2m_configured": m2m_ok,
                    "copernicus_configured": cop_ok, "keyring_available": True}
        except Exception:
            return {"ok": False, "error": "keyring_unavailable",
                    "m2m_configured": False, "copernicus_configured": False,
                    "keyring_available": False}

    elif action == "prepare_secrets":
        types = req.get("types", [])
        session_id = req.get("session_id")
        if not session_id or not types:
            return {"ok": False, "error": "missing session_id or types"}
        creds = {}
        for cred_type in types:
            if cred_type not in CREDENTIAL_KEYS:
                continue
            for key in CREDENTIAL_KEYS[cred_type]:
                val = _secret_tool_lookup(cred_type, key)
                if val is not None:
                    creds[f"{cred_type}_{key}"] = val
        SECRETS_DIR.mkdir(parents=True, exist_ok=True)
        secret_path = SECRETS_DIR / f"{session_id}.json"
        secret_path.write_text(json.dumps(creds))
        os.chmod(str(secret_path), 0o600)
        return {"ok": True, "path": str(secret_path)}

    elif action == "cleanup_secrets":
        session_id = req.get("session_id")
        if not session_id:
            return {"ok": False, "error": "missing session_id"}
        secret_path = SECRETS_DIR / f"{session_id}.json"
        if secret_path.exists():
            # Overwrite before delete (best-effort on tmpfs)
            size = secret_path.stat().st_size
            secret_path.write_bytes(b"\x00" * size)
            secret_path.unlink()
        return {"ok": True}

    else:
        return {"ok": False, "error": f"unknown action: {action}"}


def _migrate_json_credentials():
    """On startup, migrate .credentials.json to keyring if it exists."""
    # Check common locations
    for path in [Path("/srv/geographica/data/.credentials.json"),
                 Path("/data/.credentials.json")]:
        if not path.exists():
            continue
        try:
            creds = json.loads(path.read_text())
            migrated = False
            for cred_type, keys in CREDENTIAL_KEYS.items():
                for key in keys:
                    json_key = f"{cred_type}_{key}"
                    if json_key in creds and creds[json_key]:
                        _secret_tool_store(cred_type, key, creds[json_key])
                        migrated = True
            if migrated:
                log.info("Migrated credentials from %s to system keyring", path)
                # Overwrite then delete (best-effort on SSD)
                size = path.stat().st_size
                path.write_bytes(b"\x00" * size)
                path.unlink()
                log.info("Deleted old credentials file: %s", path)
        except Exception as e:
            log.warning("Migration failed for %s: %s", path, e)


def serve():
    """Main event loop — accept connections and handle requests."""
    _migrate_json_credentials()

    sock_path = Path(SOCKET_PATH)
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    if sock_path.exists():
        sock_path.unlink()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    os.chmod(str(sock_path), 0o660)
    server.listen(5)
    server.settimeout(1.0)  # Allow periodic signal checking

    log.info("Keyring agent listening on %s", sock_path)

    running = True

    def _shutdown(signum, frame):
        nonlocal running
        log.info("Shutting down (signal %d)", signum)
        running = False

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        while running:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            try:
                conn.settimeout(5.0)
                data = b""
                while b"\n" not in data:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                if data:
                    req = json.loads(data.strip())
                    resp = handle_request(req)
                    conn.sendall(json.dumps(resp).encode() + b"\n")
            except Exception as e:
                try:
                    conn.sendall(json.dumps({"ok": False, "error": str(e)}).encode() + b"\n")
                except Exception:
                    pass
            finally:
                conn.close()
    finally:
        server.close()
        if sock_path.exists():
            sock_path.unlink()
        log.info("Keyring agent stopped")


if __name__ == "__main__":
    serve()
```

- [ ] **Step 4: Create systemd service file**

Create `services/keyring-agent/geographica-keyring.service`:

```ini
[Unit]
Description=Geographica Keyring Agent
After=dbus.service
Requires=dbus.service

[Service]
Type=simple
User=administrator
ExecStart=/usr/bin/python3 /home/administrator/Code/geographica/services/keyring-agent/agent.py
RuntimeDirectory=geographica
RuntimeDirectoryMode=0750
Restart=on-failure
RestartSec=5
Environment=KEYRING_SOCKET=/run/geographica/keyring.sock
Environment=SECRETS_DIR=/run/geographica/secrets

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_keyring_agent.py -v`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add services/keyring-agent/ tests/test_keyring_agent.py
git commit -m "feat: keyring agent daemon with Unix socket protocol"
```

---

## Task 2: Search Service Keyring Client

**Files:**
- Create: `services/search/keyring_client.py`
- Create: `tests/test_keyring_client.py`

BEFORE starting work:
1. Read the spec — focus on "Search Service Client" and "Socket Protocol"
2. Read `dev/testing-pitfalls.md`
Follow TDD.

**Context:** The search container communicates with the host-side keyring agent via a Unix socket mounted into the container. This module provides typed functions that wrap the JSON protocol.

- [ ] **Step 1: Write client tests**

Create `tests/test_keyring_client.py`:

```python
"""Tests for keyring client — mock the socket layer."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))

import keyring_client


def _mock_request(response: dict):
    """Return a patch that makes _request return the given response."""
    return patch.object(keyring_client, "_request", return_value=response)


class TestStoreCredential:
    def test_store_sends_correct_request(self):
        with _mock_request({"ok": True}) as mock:
            result = keyring_client.store_credential("m2m", "username", "testuser")
        assert result is True
        mock.assert_called_once_with({
            "action": "store", "type": "m2m", "key": "username", "value": "testuser"
        })

    def test_store_returns_false_on_error(self):
        with _mock_request({"ok": False, "error": "failed"}):
            result = keyring_client.store_credential("m2m", "username", "x")
        assert result is False


class TestGetStatus:
    def test_status_returns_configured(self):
        with _mock_request({"ok": True, "m2m_configured": True,
                           "copernicus_configured": False, "keyring_available": True}):
            result = keyring_client.get_status()
        assert result["m2m_configured"] is True
        assert result["copernicus_configured"] is False
        assert result["keyring_available"] is True

    def test_status_agent_unavailable(self):
        with _mock_request({"ok": False, "error": "agent_unavailable"}):
            result = keyring_client.get_status()
        assert result["keyring_available"] is False


class TestPrepareSecrets:
    def test_prepare_returns_path(self):
        with _mock_request({"ok": True, "path": "/run/geographica/secrets/abc.json"}):
            path = keyring_client.prepare_secrets(["m2m"], "abc")
        assert path == "/run/geographica/secrets/abc.json"

    def test_prepare_returns_none_on_error(self):
        with _mock_request({"ok": False, "error": "no credentials"}):
            path = keyring_client.prepare_secrets(["m2m"], "abc")
        assert path is None


class TestCleanupSecrets:
    def test_cleanup_sends_correct_request(self):
        with _mock_request({"ok": True}) as mock:
            keyring_client.cleanup_secrets("abc")
        mock.assert_called_once_with({"action": "cleanup_secrets", "session_id": "abc"})


class TestDeleteCredentials:
    def test_delete_sends_correct_request(self):
        with _mock_request({"ok": True}) as mock:
            result = keyring_client.delete_credentials("m2m")
        assert result is True
        mock.assert_called_once_with({"action": "delete", "type": "m2m"})
```

- [ ] **Step 2: Implement keyring_client.py**

Create `services/search/keyring_client.py`:

```python
"""Client for the Geographica keyring agent.

Communicates with the host-side keyring agent via Unix domain socket.
The socket is bind-mounted into the container at /run/geographica/keyring.sock.
"""

import json
import os
import socket

SOCKET_PATH = os.environ.get("KEYRING_SOCKET", "/run/geographica/keyring.sock")


def _request(data: dict) -> dict:
    """Send a JSON request to the keyring agent and return the response."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect(SOCKET_PATH)
        sock.sendall(json.dumps(data).encode() + b"\n")
        response = b""
        while b"\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
        return json.loads(response.strip())
    except (ConnectionRefusedError, FileNotFoundError, TimeoutError, OSError):
        return {"ok": False, "error": "agent_unavailable"}
    finally:
        sock.close()


def store_credential(cred_type: str, key: str, value: str) -> bool:
    resp = _request({"action": "store", "type": cred_type, "key": key, "value": value})
    return resp.get("ok", False)


def lookup_credential(cred_type: str, key: str) -> str | None:
    resp = _request({"action": "lookup", "type": cred_type, "key": key})
    return resp.get("value") if resp.get("ok") else None


def delete_credentials(cred_type: str) -> bool:
    resp = _request({"action": "delete", "type": cred_type})
    return resp.get("ok", False)


def get_status() -> dict:
    resp = _request({"action": "status"})
    if resp.get("ok"):
        return resp
    return {"m2m_configured": False, "copernicus_configured": False,
            "keyring_available": False}


def prepare_secrets(types: list[str], session_id: str) -> str | None:
    resp = _request({"action": "prepare_secrets", "types": types, "session_id": session_id})
    return resp.get("path") if resp.get("ok") else None


def cleanup_secrets(session_id: str) -> None:
    _request({"action": "cleanup_secrets", "session_id": session_id})
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_keyring_client.py -v`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add services/search/keyring_client.py tests/test_keyring_client.py
git commit -m "feat: keyring client module for search service"
```

---

## Task 3: Refactor Credential Endpoints + Pipeline Start

**Files:**
- Modify: `services/search/main.py` (lines 31, 1035-1160, 1243-1296, 1411-1429)
- Modify: `docker-compose.yml` (search service volumes)

BEFORE starting work:
1. Read the spec — focus on "Credential Endpoints Refactored" and "Pipeline Start — tmpfs Secret Injection"
2. Read `services/search/keyring_client.py` (created in Task 2) — understand the API
3. Read `services/search/main.py` — find all `CREDENTIALS_PATH` references (line 31 and ~15 other locations)
4. Read `dev/testing-pitfalls.md`

**Context:** The credential endpoints currently read/write `/data/.credentials.json`. We're replacing all JSON file operations with calls to `keyring_client`. The pipeline start handler currently injects credentials as env vars — we're replacing that with tmpfs file requests via `prepare_secrets()`.

**WARNING:** Do NOT remove `CREDENTIALS_PATH` constant until ALL references are replaced. Search for `CREDENTIALS_PATH` and replace each one.

**WARNING:** The `_credential_lock` asyncio.Lock is no longer needed — the keyring agent handles concurrency. Remove it and the `async with _credential_lock` blocks.

**WARNING:** The credential status endpoint (`GET /admin/credentials/status`) must now return three states: configured, not configured, and keyring unavailable. The frontend checks `_m2mConfigured` and `_copernicusConfigured` — these booleans must still work. Add `keyring_available` as a new field.

- [ ] **Step 1: Add keyring socket mount to docker-compose.yml**

Add to the search service volumes:

```yaml
      - /run/geographica/keyring.sock:/run/geographica/keyring.sock:ro
      - /run/geographica/secrets:/run/geographica/secrets:ro
```

- [ ] **Step 2: Replace credential save endpoint**

Replace the `save_credentials` function body. Instead of JSON file I/O:
```python
import keyring_client

@app.post("/admin/credentials", dependencies=[Depends(require_config_source)])
async def save_credentials(body: CredentialBody):
    if body.m2m_username and body.m2m_token:
        keyring_client.store_credential("m2m", "username", body.m2m_username)
        keyring_client.store_credential("m2m", "token", body.m2m_token)
    if body.copernicus_username and body.copernicus_password:
        keyring_client.store_credential("copernicus", "username", body.copernicus_username)
        keyring_client.store_credential("copernicus", "password", body.copernicus_password)
    if not any([body.m2m_username, body.m2m_token, body.copernicus_username, body.copernicus_password]):
        raise HTTPException(status_code=422, detail="At least one credential field required")
    return {"status": "saved"}
```

- [ ] **Step 3: Replace credential status endpoint**

```python
@app.get("/admin/credentials/status")
async def credentials_status():
    status = keyring_client.get_status()
    return {
        "m2m_configured": status.get("m2m_configured", False),
        "copernicus_configured": status.get("copernicus_configured", False),
        "keyring_available": status.get("keyring_available", False),
    }
```

- [ ] **Step 4: Replace credential delete endpoints**

```python
@app.delete("/admin/credentials", dependencies=[Depends(require_config_source)])
async def delete_all_credentials():
    keyring_client.delete_credentials("m2m")
    keyring_client.delete_credentials("copernicus")
    return {"status": "deleted"}

@app.delete("/admin/credentials/m2m", dependencies=[Depends(require_config_source)])
async def delete_m2m_credentials():
    keyring_client.delete_credentials("m2m")
    return {"status": "deleted"}

@app.delete("/admin/credentials/copernicus", dependencies=[Depends(require_config_source)])
async def delete_copernicus_credentials():
    keyring_client.delete_credentials("copernicus")
    return {"status": "deleted"}
```

- [ ] **Step 5: Replace pipeline start credential injection**

Replace the env var injection block (lines ~1411-1429) with tmpfs secret preparation:

```python
            # Prepare credentials via keyring agent (tmpfs, never on disk)
            session_id = f"pipeline-{int(time.time())}"
            secret_types = []
            if body.mode == "m2m":
                secret_types.append("m2m")
            if is_sentinel:
                secret_types.append("copernicus")

            secret_path = None
            if secret_types:
                secret_path = keyring_client.prepare_secrets(secret_types, session_id)
                if not secret_path:
                    raise HTTPException(status_code=500, detail="Failed to prepare credentials from keyring")
```

In the volumes dict, add the secrets mount:
```python
            if secret_path:
                volumes['/run/geographica/secrets'] = {'bind': '/secrets', 'mode': 'ro'}
```

Remove the credential env vars (`USGS_M2M_USERNAME`, `USGS_M2M_TOKEN`, `COPERNICUS_USERNAME`, `COPERNICUS_PASSWORD`) from the `env` dict.

After `container.run()`, in a `finally` block:
```python
            finally:
                if secret_types and session_id:
                    keyring_client.cleanup_secrets(session_id)
```

- [ ] **Step 6: Remove dead code**

Remove: `CREDENTIALS_PATH` constant (line 31), `_credential_lock` (line 1035), `_remove_credential_keys` function (lines 1038-1065), all `CREDENTIALS_PATH.read_text()` / `CREDENTIALS_PATH.exists()` checks in the credential validation blocks (lines 1243-1296).

Replace credential validation in pipeline start with keyring status check:
```python
            if body.mode == "m2m":
                status = keyring_client.get_status()
                if not status.get("m2m_configured"):
                    raise HTTPException(status_code=422, detail="M2M credentials not configured")
            if is_sentinel:
                status = keyring_client.get_status()
                if not status.get("copernicus_configured"):
                    raise HTTPException(status_code=422, detail="Copernicus credentials not configured")
```

- [ ] **Step 7: Add `import time` if not present**

Check if `time` is already imported in main.py. If not, add `import time` to the imports.

- [ ] **Step 8: Run tests**

Run: `python -m pytest tests/ -v`
Expected: 497+ pass. Some credential tests may need updates if they mock `CREDENTIALS_PATH`.

- [ ] **Step 9: Commit**

```bash
git add services/search/main.py docker-compose.yml
git commit -m "feat: credential endpoints use keyring agent, pipeline uses tmpfs secrets"
```

---

## Task 4: Pipeline Scripts — Read from /secrets/

**Files:**
- Modify: `scripts/acquire_imagery.py` (lines 1366-1371, 1955-1964)
- Modify: `scripts/acquire_sentinel.py` (lines 470-476)

BEFORE starting work:
1. Read the spec — focus on "Pipeline Scripts — Read from /secrets/"
2. Read `dev/testing-pitfalls.md`

**Context:** Pipeline containers now receive credentials via a tmpfs-mounted JSON file at `/secrets/*.json` instead of environment variables. The scripts need to read from this file first, falling back to CLI args and env vars for development/manual use.

- [ ] **Step 1: Add _load_secrets helper to acquire_imagery.py**

Add near the top of the file (after imports):

```python
def _load_secrets() -> dict:
    """Load credentials from tmpfs secret file if available."""
    secrets_dir = Path("/secrets")
    if secrets_dir.exists():
        for f in secrets_dir.glob("*.json"):
            try:
                creds = json.loads(f.read_text())
                try:
                    f.unlink()
                except OSError:
                    pass  # read-only mount
                return creds
            except (json.JSONDecodeError, OSError):
                continue
    return {}
```

- [ ] **Step 2: Update M2M credential loading in acquire_imagery.py**

Replace the credential validation block (lines ~1366-1371):

```python
    # Load credentials: tmpfs secrets file > CLI args > env vars
    secrets = _load_secrets()
    username = args.m2m_username or secrets.get("m2m_username") or os.environ.get("USGS_M2M_USERNAME")
    token = args.m2m_token or secrets.get("m2m_token") or os.environ.get("USGS_M2M_TOKEN")
    if not username or not token:
        log.error("M2M mode requires credentials (via keyring, --m2m-username/--m2m-token, or env vars)")
        sys.exit(1)
```

- [ ] **Step 3: Add _load_secrets to acquire_sentinel.py and update credential loading**

Add the same `_load_secrets()` function. Then replace the credential block (lines 470-476):

```python
    secrets = _load_secrets()
    username = secrets.get("copernicus_username") or os.environ.get("COPERNICUS_USERNAME", "")
    password = secrets.get("copernicus_password") or os.environ.get("COPERNICUS_PASSWORD", "")
    if not username or not password:
        log.error("Copernicus credentials required (via keyring, or COPERNICUS_USERNAME/COPERNICUS_PASSWORD env vars)")
        update_progress(output, "authenticating", status="error",
                        error="Missing Copernicus credentials", bbox=args.bbox)
        return
```

- [ ] **Step 4: Commit**

```bash
git add scripts/acquire_imagery.py scripts/acquire_sentinel.py
git commit -m "feat: pipeline scripts read credentials from tmpfs secrets file"
```

---

## Task 5: Bootstrap + Gitignore + Repo Scan

**Files:**
- Modify: `bootstrap.sh`
- Modify: `.gitignore`

BEFORE starting work:
1. Read the spec — focus on "Bootstrap Dependencies" and "Repo Credential Scan"
2. Read `bootstrap.sh` — understand current structure

**Context:** The bootstrap script needs to install GNOME Keyring dependencies and configure PAM auto-unlock. The .gitignore needs credential file patterns.

- [ ] **Step 1: Add keyring dependencies to bootstrap.sh**

Add after the existing apt install block (after line 35):

```bash
echo "[2/6] Installing keyring dependencies..."
apt install -y gnome-keyring libsecret-tools dbus-x11

# Configure PAM auto-unlock for GNOME Keyring
if ! grep -q pam_gnome_keyring /etc/pam.d/common-auth 2>/dev/null; then
    echo "auth optional pam_gnome_keyring.so" >> /etc/pam.d/common-auth
    echo "  Added PAM auto-unlock to common-auth"
fi
if ! grep -q pam_gnome_keyring /etc/pam.d/common-session 2>/dev/null; then
    echo "session optional pam_gnome_keyring.so auto_start" >> /etc/pam.d/common-session
    echo "  Added PAM auto-start to common-session"
fi
```

Update the step numbering (current steps [1/5] through [5/5] become [1/6] through [6/6]).

Also add the keyring agent systemd service install:
```bash
echo "[6/6] Installing keyring agent service..."
cp "$REPO_DIR/services/keyring-agent/geographica-keyring.service" /etc/systemd/system/
# Update ExecStart path to match actual repo location
sed -i "s|/home/administrator/Code/geographica|$REPO_DIR|g" /etc/systemd/system/geographica-keyring.service
# Update User to match actual user
sed -i "s|User=administrator|User=$ACTUAL_USER|g" /etc/systemd/system/geographica-keyring.service
systemctl daemon-reload
systemctl enable geographica-keyring
systemctl start geographica-keyring
echo "  Keyring agent installed and started"
```

- [ ] **Step 2: Add credential patterns to .gitignore**

Add to `.gitignore`:
```
# Credential files (must never be committed)
.credentials.json
credentials.json
*.credentials.json
```

- [ ] **Step 3: Run one-time repo credential scan**

Run: `grep -rn "token\|password\|api_key\|secret" --include="*.json" --include="*.env" data/ .env* 2>/dev/null | grep -v node_modules | grep -v ".git/"`

Verify no actual credentials are present. Only template/placeholder values should appear.

- [ ] **Step 4: Commit**

```bash
git add bootstrap.sh .gitignore
git commit -m "feat: bootstrap installs keyring deps + PAM auto-unlock + agent service"
```

---

## Review Checkpoint

After all 5 tasks:
Carefully review the batch of work from multiple perspectives. Do a minimum of three review rounds. Specifically verify:

1. **Task 1:** Does the agent handle all protocol actions? Is `secret-tool` always called via `subprocess.run` with timeout? Does migration overwrite-then-delete the JSON file?
2. **Task 2:** Does the client handle agent-unavailable gracefully (return safe defaults)? Is the socket timeout set?
3. **Task 3:** Are ALL references to `CREDENTIALS_PATH` removed? Are credential env vars removed from the pipeline container? Is `cleanup_secrets` in a finally block?
4. **Task 4:** Do pipeline scripts fall back to env vars for dev use? Is `_load_secrets` identical in both files?
5. **Task 5:** Does bootstrap install the systemd service and start it? Does PAM config handle idempotent re-runs?
6. **Cross-task:** Does the socket path (`/run/geographica/keyring.sock`) match between agent, client, and docker-compose?
