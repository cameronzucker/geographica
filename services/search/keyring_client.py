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
