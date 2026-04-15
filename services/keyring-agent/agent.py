#!/usr/bin/env python3
"""Geographica Keyring Agent -- host-side daemon for credential management.

Manages GNOME Keyring via secret-tool CLI. Listens on a Unix domain socket
for JSON requests from the search container. Never runs inside Docker.

Stdlib only -- no pip dependencies required.
"""

import json
import logging
import os
import signal
import socket
import subprocess
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

# Migration paths checked on startup (overridable for testing)
_MIGRATION_PATHS = [
    Path("/srv/geographica/data/.credentials.json"),
    Path("/data/.credentials.json"),
]


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
    for path in _MIGRATION_PATHS:
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
    """Main event loop -- accept connections and handle requests."""
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
