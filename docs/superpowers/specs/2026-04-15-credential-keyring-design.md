# Credential Management Overhaul — System Keyring

**Date:** 2026-04-15
**Scope:** Replace plaintext JSON credential storage with GNOME Keyring via a host-side agent, eliminate env var exposure in Docker containers, migrate existing credentials, scan repo for leaks.

## Problem

Credentials (USGS M2M API token, Copernicus username/password) are stored in `/data/.credentials.json` — a plaintext JSON file on disk. Even with 0600 permissions, this is readable by anyone with root access or physical access to the SSD. The pipeline injects credentials as Docker environment variables, which are visible via `docker inspect` and `/proc/<pid>/environ`. For a device that will be on display at DEF CON, this is unacceptable.

## Architectural Constraint

The search service runs inside a Docker container (`python:3.12-slim`). GNOME Keyring requires a host D-Bus session and `gnome-keyring-daemon` — neither exists inside the container. `secret-tool` cannot run in the container. Therefore, keyring operations must run on the **host**, not inside Docker.

## Architecture: Host-Side Keyring Agent

A lightweight Python daemon running on the host (systemd service) that:
1. Manages GNOME Keyring via `secret-tool` subprocess calls on the host D-Bus session
2. Listens on a Unix domain socket at `/run/geographica/keyring.sock`
3. Accepts simple JSON-over-socket requests from the search container
4. On pipeline start, writes credentials to host tmpfs (`/run/geographica/secrets/`) for container bind-mount

### Component Diagram

```
HOST (Raspberry Pi 5)
├── gnome-keyring-daemon (D-Bus, encrypted storage)
├── geographica-keyring-agent (systemd service)
│   ├── Listens on /run/geographica/keyring.sock
│   ├── Calls secret-tool store/lookup/clear
│   └── Writes /run/geographica/secrets/*.json (tmpfs)
│
├── Docker containers
│   ├── search (mounts keyring.sock + /run/geographica/secrets/)
│   │   ├── POST /admin/credentials → writes to agent socket
│   │   ├── GET /admin/credentials/status → reads from agent socket
│   │   └── POST /admin/pipeline/start → requests secret file from agent
│   │
│   └── pipeline (mounts /run/geographica/secrets/:ro)
│       └── Reads /secrets/credentials.json, deletes after loading
```

### Socket Protocol

Simple newline-delimited JSON over Unix socket. Request/response pairs.

**Store:**
```json
{"action": "store", "type": "m2m", "key": "username", "value": "my_user"}
→ {"ok": true}
```

**Lookup:**
```json
{"action": "lookup", "type": "m2m", "key": "username"}
→ {"ok": true, "value": "my_user"}
→ {"ok": false, "error": "not_found"}
```

**Delete:**
```json
{"action": "delete", "type": "m2m"}
→ {"ok": true}
```

**Status:**
```json
{"action": "status"}
→ {"ok": true, "m2m_configured": true, "copernicus_configured": false, "keyring_available": true}
```

**Prepare secrets (for pipeline start):**
```json
{"action": "prepare_secrets", "types": ["m2m"], "session_id": "pipeline-abc123"}
→ {"ok": true, "path": "/run/geographica/secrets/pipeline-abc123.json"}
```

**Cleanup secrets:**
```json
{"action": "cleanup_secrets", "session_id": "pipeline-abc123"}
→ {"ok": true}
```

### Secret Attributes

Stored in GNOME Keyring with these attributes for lookup:
- `application`: `geographica`
- `credential_type`: `m2m` or `copernicus`
- `key`: `username`, `token`, or `password`

Labels: `Geographica M2M Username`, `Geographica M2M Token`, `Geographica Copernicus Username`, `Geographica Copernicus Password`

### Keyring Unlock

GNOME Keyring auto-unlocks via PAM when the user logs in (console, SSH, or VNC). On a headless Pi:
- PAM module `pam_gnome_keyring.so` unlocks on login if the keyring password matches the login password
- `bootstrap.sh` configures PAM to auto-unlock the `login` keyring
- If the keyring is locked (e.g., password changed), the agent returns `{"ok": false, "error": "keyring_locked"}` and the search service surfaces this to the admin UI as a distinct state (not "no credentials configured")

### Credential Status States

The `/admin/credentials/status` endpoint now returns three states:

| State | Meaning | UI Display |
|-------|---------|------------|
| `{"m2m_configured": true, "keyring_available": true}` | Credentials stored and accessible | Green "Configured" |
| `{"m2m_configured": false, "keyring_available": true}` | No credentials stored | Show credential form |
| `{"keyring_available": false}` | Keyring locked or agent down | Orange "Keyring locked — log in to unlock" |

## Components

### 1. Keyring Agent (`services/keyring-agent/agent.py`)

Host-side daemon. ~150 lines. Systemd managed.

- Creates `/run/geographica/` directory (0700)
- Creates Unix socket at `/run/geographica/keyring.sock` (0660, group `docker`)
- Accepts connections, reads JSON requests, dispatches to handlers
- Each handler calls `subprocess.run(["secret-tool", ...], timeout=5)`
- `prepare_secrets` handler: reads credentials from keyring, writes JSON to `/run/geographica/secrets/{session_id}.json` (0600), returns path
- `cleanup_secrets` handler: deletes the file
- Signal handlers: SIGTERM gracefully shuts down, removes socket file
- Logging to stdout (journalctl captures it)

### 2. Systemd Service (`services/keyring-agent/geographica-keyring.service`)

```ini
[Unit]
Description=Geographica Keyring Agent
After=dbus.service
Requires=dbus.service

[Service]
Type=simple
User=administrator
ExecStart=/usr/bin/python3 /path/to/services/keyring-agent/agent.py
RuntimeDirectory=geographica
RuntimeDirectoryMode=0750
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`RuntimeDirectory=geographica` automatically creates `/run/geographica/` with the right permissions and cleans it up on stop.

### 3. Search Service Client (`services/search/keyring_client.py`)

Client module for the search container to communicate with the agent.

```python
import json
import socket

SOCKET_PATH = '/run/geographica/keyring.sock'

def _request(data: dict) -> dict:
    """Send a JSON request to the keyring agent and return the response."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect(SOCKET_PATH)
        sock.sendall(json.dumps(data).encode() + b'\n')
        response = b''
        while b'\n' not in response:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
        return json.loads(response.strip())
    except (ConnectionRefusedError, FileNotFoundError, TimeoutError):
        return {"ok": False, "error": "agent_unavailable"}
    finally:
        sock.close()
```

Functions: `store_credential()`, `lookup_credential()`, `delete_credentials()`, `get_status()`, `prepare_secrets()`, `cleanup_secrets()` — all thin wrappers around `_request()`.

### 4. Credential Endpoints Refactored

Modify: `services/search/main.py`

**POST /admin/credentials** — calls `keyring_client.store_credential()` for each key/value pair
**GET /admin/credentials/status** — calls `keyring_client.get_status()`, returns `m2m_configured`, `copernicus_configured`, `keyring_available`
**DELETE /admin/credentials/m2m** — calls `keyring_client.delete_credentials('m2m')`
**DELETE /admin/credentials/copernicus** — calls `keyring_client.delete_credentials('copernicus')`

Remove: `CREDENTIALS_PATH`, `_credential_lock`, `_remove_credential_keys()`, all JSON file I/O.

### 5. Pipeline Start — tmpfs Secret Injection

Modify: `services/search/main.py` pipeline start handler

1. Call `keyring_client.prepare_secrets(['m2m'], session_id)` or `prepare_secrets(['copernicus'], session_id)`
2. Agent writes credentials to `/run/geographica/secrets/{session_id}.json` on host tmpfs
3. Add bind mount: host `/run/geographica/secrets/` → container `/secrets/:ro`
4. Remove all credential env vars from container environment
5. After `container.run()` returns (or in a finally block), call `keyring_client.cleanup_secrets(session_id)`

### 6. Pipeline Scripts — Read from /secrets/

Modify: `scripts/acquire_imagery.py`, `scripts/acquire_sentinel.py`

```python
def _load_secrets() -> dict:
    """Load credentials from tmpfs secret file, then delete it."""
    secrets_dir = Path('/secrets')
    if secrets_dir.exists():
        for f in secrets_dir.glob('*.json'):
            creds = json.loads(f.read_text())
            try:
                f.unlink()
            except OSError:
                pass  # read-only mount, deletion is best-effort
            return creds
    return {}
```

Fallback to CLI args / env vars for development use (not in production containers).

### 7. Docker Compose Updates

```yaml
search:
  volumes:
    - /run/geographica/keyring.sock:/run/geographica/keyring.sock:ro
    - /run/geographica/secrets:/run/geographica/secrets:ro
```

Pipeline container (created dynamically via Docker API) gets:
```python
volumes['/run/geographica/secrets'] = {'bind': '/secrets', 'mode': 'ro'}
```

### 8. Migration

In the keyring agent startup:
1. Check for `/data/.credentials.json` (old location — agent has access since it runs on host)
2. If found, read credentials, store each in keyring via `secret-tool store`
3. Overwrite file contents with zeros, then delete: `f.write_bytes(b'\x00' * f.stat().st_size); f.unlink()`
4. Log: "Migrated credentials from JSON to system keyring"

Note: `shred` is ineffective on SSDs due to wear leveling. Overwrite + delete is best-effort. The real protection is that GNOME Keyring never writes plaintext to disk. Full-disk encryption (LUKS) is the ultimate mitigation for old data remnants.

### 9. Bootstrap Dependencies

Add to `bootstrap.sh`:
```bash
apt-get install -y gnome-keyring libsecret-tools dbus-x11

# Enable PAM auto-unlock for GNOME Keyring
# This makes the keyring unlock automatically on login
if ! grep -q pam_gnome_keyring /etc/pam.d/common-auth 2>/dev/null; then
    echo "auth optional pam_gnome_keyring.so" >> /etc/pam.d/common-auth
fi
if ! grep -q pam_gnome_keyring /etc/pam.d/common-session 2>/dev/null; then
    echo "session optional pam_gnome_keyring.so auto_start" >> /etc/pam.d/common-session
fi
```

Setup wizard pre-flight checks:
- `which secret-tool` — verify libsecret-tools installed
- `systemctl is-active geographica-keyring` — verify agent running
- Agent `status` request — verify keyring available and unlocked

### 10. Repo Credential Scan

- Add to `.gitignore`: `*.credentials.json`, `credentials.json`, `.credentials.json`
- One-time scan: `grep -rn "token\|password\|api_key\|secret" --include="*.json" --include="*.env" data/ .env* 2>/dev/null`
- Verify git history is clean (already confirmed by exploratory agent)

### 11. Testing Strategy

**Keyring agent tests:** Mock `subprocess.run` calls to `secret-tool`. Test the socket protocol, request dispatch, and error handling. No real keyring needed.

**Search service tests:** Mock `keyring_client._request()`. Test that credential endpoints call the right client functions with correct arguments.

**Integration test (manual):** On the Pi with keyring running, verify end-to-end: save credentials via admin UI → verify in keyring (`secret-tool lookup`) → start pipeline → verify tmpfs file created and deleted → verify pipeline loads credentials.

## Files

| File | Status | Purpose |
|------|--------|---------|
| `services/keyring-agent/agent.py` | New | Host-side keyring daemon |
| `services/keyring-agent/geographica-keyring.service` | New | Systemd unit file |
| `services/search/keyring_client.py` | New | Unix socket client for search container |
| `services/search/main.py` | Modify | Refactor credential endpoints + pipeline start |
| `scripts/acquire_imagery.py` | Modify | Read from /secrets/ tmpfs |
| `scripts/acquire_sentinel.py` | Modify | Read from /secrets/ tmpfs |
| `docker-compose.yml` | Modify | Mount keyring socket + secrets dir |
| `bootstrap.sh` | Modify | Install gnome-keyring + PAM config |
| `tests/test_keyring_agent.py` | New | Agent protocol tests |
| `tests/test_keyring_client.py` | New | Client mock tests |
| `.gitignore` | Modify | Add credential file patterns |

## Adversarial Review Findings (5 rounds: Opus, Opus, Sonnet, Sonnet, Sonnet)

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| F1 | secret-tool can't run inside Docker container (no D-Bus) | Blocker | Redesigned: host-side keyring agent with Unix socket |
| F2 | /run/ path confusion between host and container | Blocker | Agent runs on host, creates /run/geographica/; container bind-mounts socket + secrets dir |
| F3 | Keyring locked after reboot — blocks all operations | High | PAM auto-unlock configured in bootstrap.sh; agent returns distinct "keyring_locked" error; UI shows lock state |
| F4 | shred ineffective on SSD | Medium | Acknowledged; overwrite+delete is best-effort; GNOME Keyring never writes plaintext to disk; LUKS recommended for full protection |
| F5 | Race between secret file write and container start | Low | Acceptable: /run/ is tmpfs, cleared on reboot; cleanup in finally block |
| F6 | Credential status indistinguishable from locked keyring | Medium | Three-state response: configured, not configured, keyring unavailable |
| F7 | Testing requires real keyring | Medium | Mock subprocess.run for agent tests; mock _request for client tests |
| F8 | Pipeline container can't read host /run/ | High | Explicit bind-mount of /run/geographica/secrets/ in Docker API call |

## Security Properties

| Property | Current | After |
|----------|---------|-------|
| At-rest storage | Plaintext JSON (0600) | GNOME Keyring (encrypted with login password) |
| docker inspect exposure | Credentials in env vars | No credentials in env vars |
| /proc/pid/environ | Credentials visible | No credentials in environ |
| SSD stolen, mounted offline | Credentials readable | Encrypted in keyring file, requires login password |
| Container crash dump | Env vars in dump | tmpfs file already deleted |
| Keyring locked | N/A | Credentials inaccessible; UI shows lock state |
| In-transit to pipeline | Env var (persistent) | tmpfs file (RAM-only, deleted after read) |
| Repo history | Clean | Clean + .gitignore guard |

## What This Does NOT Change

- Frontend credential UI forms (same inputs, same API contract)
- Pipeline download/convert logic
- TileServer, NGINX, GPS, STT services
- Admin panel tabs (Dashboard, Pipelines, Inventory, Settings)
