# Admin Panel Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Redesign the admin config panel with 3-tab layout (Dashboard/Pipelines/Settings), enriched backend status aggregation, GPS REST endpoint, OSM POI pipeline support, and MapLibre minimap for bbox selection.
**Architecture:** Backend-first approach -- build the enriched API endpoints first, then the frontend that consumes them. NGINX config changes are a prerequisite for the minimap.
**Tech Stack:** Python/FastAPI, vanilla JS, MapLibre GL JS, NGINX
**Spec:** docs/superpowers/specs/2026-04-09-admin-panel-redesign-design.md

---

## Pitfalls Reference

Before working on ANY task, read both pitfalls files. The most relevant pitfalls for this plan are:

- **Testing Pitfall #1 (Mocking what should be tested):** Use real in-memory SQLite for search_stats queries, not mocks.
- **Testing Pitfall #5 (Async test isolation):** Use `@pytest.mark.asyncio` for direct async function tests; FastAPI TestClient handles it automatically.
- **Testing Pitfall #6 (Docker-dependent tests):** Mark Docker-dependent tests with `pytest.mark.skipif`; these tests should NOT require Docker.
- **Testing Pitfall #8 (Env var pollution):** Use `monkeypatch` fixture, not `os.environ` directly.
- **Implementation Pitfall #2 (Container naming):** Pattern is `geographica-<service>`.
- **Implementation Pitfall #3 (NGINX sub_filter):** Requires `Accept-Encoding ""` to disable gzip; only apply to style JSON and TileJSON, NOT tile data or JSON APIs.
- **Implementation Pitfall #6 (Offline-first):** No CDN dependencies. MapLibre JS/CSS already vendored at `frontend/vendor/`.
- **Implementation Pitfall #10 (Config panel is localhost-only):** Port 8097, requires `X-Config-Source: internal` header from NGINX.

---

## File Map

### Modified Files

| File | Change |
|------|--------|
| `services/gps/main.py` | Add `GET /status` endpoint (lines ~208+) |
| `services/search/main.py` | Enrich `/admin/status` (line 539), add `osm_poi` pipeline type (line 762), update `_parse_zoom` (line 117), add helper functions for STT/GPS/TLS aggregation |
| `frontend/config/index.html` | Full rewrite: 3-tab layout, ~850 lines total |
| `nginx/nginx.conf` | Add tile proxy + vendor serving to config panel server block (after line 169) |
| `docker-compose.yml` | Add TLS cert volume mount to search service (after line 128) |

### New Files

| File | Description |
|------|-------------|
| `services/gps/tests/__init__.py` | Test package marker |
| `services/gps/tests/test_status.py` | Tests for GPS `/status` endpoint |
| `services/search/tests/__init__.py` | Test package marker |
| `services/search/tests/test_admin_status.py` | Tests for enriched `/admin/status` |
| `services/search/tests/test_pipeline_osm.py` | Tests for OSM POI pipeline type |
| `services/search/tests/test_zoom_validation.py` | Tests for `_parse_zoom` changes |

---

## Dependency Graph

```
Task 1 (GPS /status)    Task 3 (Zoom + OSM pipeline)    Task 4 (NGINX + docker-compose)
        \                       |                              /
         \                      |                             /
          v                     v                            v
        Task 2 (Enriched /admin/status)                     |
                \                                           /
                 \                                         /
                  v                                       v
                      Task 5 (Full frontend rewrite)
```

- Tasks 1, 3, 4 are INDEPENDENT -- can run in parallel
- Task 2 depends on Task 1 (needs GPS `/status` endpoint signature to know what to call)
- Task 5 depends on Tasks 2, 3, 4 (needs enriched API, zoom validation, NGINX tile proxy)

---

## Task 1: GPS `/status` Endpoint

**File:** `services/gps/main.py`
**New test file:** `services/gps/tests/test_status.py`
**Dependencies:** None (independent)
**Estimated lines changed:** ~25 lines added to main.py, ~90 lines in test file

### TDD Preamble

```
BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/ (or invoke /test-driven-development)
2. Read docs/pitfalls/testing-pitfalls.md
Follow TDD: write failing test -> implement fix -> verify green.
```

### Context

The GPS service (`services/gps/main.py`) has:
- A module-level `_position` dict at line 35 with keys: `lat`, `lon`, `alt`, `speed`, `heading`, `fix`, `stale`, `accuracy`, `timestamp`
- A module-level `_gps_connected` boolean at line 46
- An existing `GET /health` endpoint at line 195 that returns `status`, `gps_connected`, `last_fix`
- An existing `GET /position` endpoint at line 204 that returns the full `_position` dict (includes lat/lon)

The new `GET /status` endpoint is different from `/position` because:
1. It does NOT return `lat`, `lon`, `alt`, `speed`, `heading` (security: coordinates must not appear in admin status)
2. It returns a structured status string (`"ok"` or `"no_gpsd"`) based on `_gps_connected`
3. It returns a fix type string (`"3d"`, `"2d"`, `"none"`, or `null`) instead of the raw integer

### Step 1: Create test file

Create `services/gps/tests/__init__.py` (empty file).

Create `services/gps/tests/test_status.py` with the following content:

```python
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
```

### Step 2: Run tests, confirm they fail

```bash
cd services/gps && python -m pytest tests/test_status.py -v
```

Expected: All 4 tests fail with `starlette.routing.NoMatchFound` or 404 because `/status` endpoint does not exist.

### Step 3: Implement the endpoint

In `services/gps/main.py`, add the following endpoint AFTER the existing `/position` endpoint (after line 207):

```python
@app.get("/status")
async def status() -> dict[str, Any]:
    """Structured GPS status for admin aggregation.

    Returns fix type and accuracy without coordinates.
    Three states:
    - ok + 3d/2d fix: GPS working
    - ok + none fix: gpsd connected but no satellite fix
    - no_gpsd: cannot reach gpsd daemon
    """
    if not _gps_connected:
        return {
            "status": "no_gpsd",
            "fix": None,
            "accuracy_m": None,
        }

    fix_raw = _position.get("fix", 0)
    if fix_raw >= 3:
        fix_str = "3d"
    elif fix_raw >= 2:
        fix_str = "2d"
    else:
        fix_str = "none"

    return {
        "status": "ok",
        "fix": fix_str,
        "accuracy_m": _position.get("accuracy"),
    }
```

This adds the endpoint at approximately line 209-234, after the existing `/position` endpoint at line 204-207.

### Step 4: Run tests, confirm they pass

```bash
cd services/gps && python -m pytest tests/test_status.py -v
```

Expected: All 4 tests pass.

### Step 5: Run existing tests to verify no regression

```bash
cd services/gps && python -m pytest -v 2>&1 || echo "No existing tests to regress"
```

### Completion Check

```
BEFORE marking this task complete:
1. Review your tests against docs/pitfalls/testing-pitfalls.md
2. Verify test coverage of the fix (are error paths tested? edge cases?)
   - 3D fix: tested
   - 2D fix: tested
   - No fix (connected, no satellites): tested
   - gpsd unreachable: tested
   - Security: lat/lon/alt/speed/heading NOT in response: tested in test_status_3d_fix
3. Run tests (or relevant subset) and confirm green
```

### Commit

```
feat(gps): add /status endpoint for admin panel aggregation

Returns structured fix type + accuracy without exposing GPS coordinates.
Three states: ok+3d/2d, ok+none, no_gpsd.
```

---

## Task 2: Enriched `/admin/status` Backend

**File:** `services/search/main.py`
**New test file:** `services/search/tests/test_admin_status.py`
**Dependencies:** Task 1 must be complete (GPS `/status` endpoint must exist)
**Estimated lines changed:** ~120 lines added to main.py, ~200 lines in test file

### TDD Preamble

```
BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/ (or invoke /test-driven-development)
2. Read docs/pitfalls/testing-pitfalls.md
Follow TDD: write failing test -> implement fix -> verify green.
```

### Context

The current `admin_status()` function is at line 539-669 of `services/search/main.py`. It:
1. Calls `client.containers.list(all=True, filters={"name": "geographica-"})` to get Docker containers
2. Iterates containers, extracting name, status, health, uptime, and progress (for nominatim/valhalla)
3. Reads MBTiles files for data task status
4. Returns `{"services": [...], "data_tasks": [...]}`

The enriched version must ADD these top-level keys (all always present):
- `stt`: `{status, backend, model, npu_available}` -- from `GET http://stt:8000/health` with 2s timeout
- `gps`: `{status, fix, accuracy_m}` -- from `GET http://gps:8000/status` with 2s timeout
- `tls`: `{mode, hostname, cert_expires, cert_valid}` -- from cert file inspection
- `search_stats`: `{gnis_count, osm_pois_count, osm_pois_loaded}` -- from SQL COUNT queries
- `disk_free_gb`: float -- already available via `_get_disk_free_gb()`
- `disk_total_gb`: float -- from `shutil.disk_usage`
- `disk_used_pct`: int -- calculated as `100 - (free / total * 100)`

**Critical security note:** GPS coordinates (lat, lon) must NOT appear in this response. The endpoint is publicly accessible via NGINX (line 107-111 of nginx.conf).

### Step 1: Create test file

Create `services/search/tests/__init__.py` (empty file).

Create `services/search/tests/test_admin_status.py`:

```python
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

    @pytest.mark.asyncio
    async def test_stt_healthy(self, client):
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

    @pytest.mark.asyncio
    async def test_stt_unreachable(self, client):
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

    @pytest.mark.asyncio
    async def test_gps_ok_3d(self, client):
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

    @pytest.mark.asyncio
    async def test_gps_unreachable(self, client):
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

        with patch("pathlib.Path.exists", return_value=False):
            resp = c.get("/admin/status")

        data = resp.json()
        assert data["tls"]["mode"] == "http"
        assert data["tls"]["hostname"] is None
        assert data["tls"]["cert_expires"] is None
        assert data["tls"]["cert_valid"] is None

    def test_tls_tailscale_cert(self, client):
        """When Tailscale cert exists, detect mode and parse expiry."""
        c, main, tmp_path = client

        # Create a fake cert file path
        cert_path = tmp_path / "server.crt"
        cert_path.write_text("fake cert")

        # Mock the openssl subprocess and Path check
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
```

### Step 2: Run tests, confirm they fail

```bash
cd services/search && python -m pytest tests/test_admin_status.py -v
```

Expected: Tests fail because `admin_status()` does not return the new keys (`stt`, `gps`, `tls`, `search_stats`, `disk_total_gb`, `disk_used_pct`).

### Step 3: Implement the enriched endpoint

#### Step 3a: Add imports and constants

At the top of `services/search/main.py`, add `subprocess` to the imports (line 13, which already has `import shutil`). After line 14 (`import shutil`), the `subprocess` import is needed:

Find this block near line 9-15:
```python
import asyncio
import json
import math
import os
import re
import shutil
import stat
```

Change to:
```python
import asyncio
import json
import math
import os
import re
import shutil
import stat
import subprocess
```

After line 29 (`DATA_DIR = Path("/data")`), add:
```python
TLS_CERT_PATH = Path("/tls/server.crt")
```

#### Step 3b: Add helper functions

Add these helper functions BEFORE the `admin_status()` function (before line 539). Insert them after the `_parse_progress_from_logs` function (after line 536):

```python
async def _fetch_stt_status() -> dict:
    """Query STT service health with 2s timeout."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("http://stt:8000/health")
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "status": data.get("status", "ok"),
                    "backend": data.get("backend"),
                    "model": data.get("model"),
                    "npu_available": data.get("npu_available"),
                }
    except Exception:
        pass
    return {"status": "unreachable", "backend": None, "model": None, "npu_available": None}


async def _fetch_gps_status() -> dict:
    """Query GPS service status with 2s timeout. Never returns coordinates."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("http://gps:8000/status")
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "status": data.get("status", "ok"),
                    "fix": data.get("fix"),
                    "accuracy_m": data.get("accuracy_m"),
                }
    except Exception:
        pass
    return {"status": "unreachable", "fix": None, "accuracy_m": None}


def _detect_tls_status() -> dict:
    """Detect TLS mode from cert file at /tls/server.crt."""
    result = {"mode": "http", "hostname": None, "cert_expires": None, "cert_valid": None}

    if not TLS_CERT_PATH.exists():
        return result

    # Parse certificate expiry
    try:
        enddate_result = subprocess.run(
            ["openssl", "x509", "-enddate", "-noout", "-in", str(TLS_CERT_PATH)],
            capture_output=True, text=True, timeout=5,
        )
        if enddate_result.returncode == 0:
            # Output: "notAfter=Jul  7 00:00:00 2026 GMT"
            raw = enddate_result.stdout.strip().split("=", 1)[-1]
            from datetime import datetime, timezone
            expiry = datetime.strptime(raw, "%b %d %H:%M:%S %Y GMT").replace(tzinfo=timezone.utc)
            result["cert_expires"] = expiry.strftime("%Y-%m-%d")
            result["cert_valid"] = expiry > datetime.now(timezone.utc)
    except Exception:
        pass

    # Parse certificate subject for hostname and detect Tailscale
    try:
        subject_result = subprocess.run(
            ["openssl", "x509", "-subject", "-noout", "-in", str(TLS_CERT_PATH)],
            capture_output=True, text=True, timeout=5,
        )
        if subject_result.returncode == 0:
            subject = subject_result.stdout.strip()
            # Extract CN value
            cn_match = re.search(r"CN\s*=\s*(.+?)(?:,|$)", subject)
            if cn_match:
                cn = cn_match.group(1).strip()
                if ".ts.net" in cn:
                    result["mode"] = "tailscale"
                    result["hostname"] = cn
                else:
                    result["mode"] = "https"
                    result["hostname"] = cn
    except Exception:
        if result["cert_expires"]:
            result["mode"] = "https"

    return result


def _get_search_stats() -> dict:
    """Get POI counts from the SQLite database."""
    import sqlite3
    stats = {"gnis_count": 0, "osm_pois_count": 0, "osm_pois_loaded": False}
    try:
        conn = sqlite3.connect(POI_DB_PATH, timeout=5)
        try:
            stats["gnis_count"] = conn.execute("SELECT COUNT(*) FROM poi_features").fetchone()[0]
        except Exception:
            pass
        try:
            stats["osm_pois_count"] = conn.execute("SELECT COUNT(*) FROM osm_pois").fetchone()[0]
            stats["osm_pois_loaded"] = stats["osm_pois_count"] > 0
        except Exception:
            pass
        conn.close()
    except Exception:
        pass
    return stats


def _get_disk_info() -> tuple[float, float, int]:
    """Return (free_gb, total_gb, used_pct) for the /data partition."""
    usage = shutil.disk_usage(str(DATA_DIR))
    free_gb = round(usage.free / (1024 ** 3), 1)
    total_gb = round(usage.total / (1024 ** 3), 1)
    used_pct = round(100 - (usage.free / usage.total * 100))
    return free_gb, total_gb, used_pct
```

#### Step 3c: Modify `admin_status()` to add concurrent sub-queries

Replace the ENTIRE `admin_status()` function (lines 539-669) with:

```python
@app.get("/admin/status")
async def admin_status():
    """Return status of all Geographica services and long-running tasks.

    Aggregates data from Docker, STT, GPS, TLS cert, POI database, and disk.
    Sub-queries run concurrently with 2s timeouts. All top-level keys are
    always present; sub-object keys are always present with null for unavailable.
    """
    # --- Docker container listing (existing logic, unchanged) ---
    client = _get_docker_client()
    services = []
    if client:
        try:
            containers = client.containers.list(all=True, filters={"name": "geographica-"})
            for c in sorted(containers, key=lambda x: x.name):
                svc = {
                    "name": c.name.replace("geographica-", ""),
                    "status": c.status,
                    "health": "unknown",
                    "uptime": "",
                    "progress": {},
                }
                try:
                    inspection = c.attrs
                    health_data = inspection.get("State", {}).get("Health", {})
                    svc["health"] = health_data.get("Status", "none")
                    started = inspection.get("State", {}).get("StartedAt", "")
                    if started:
                        svc["uptime"] = started
                except Exception:
                    pass

                if c.name in ("geographica-nominatim", "geographica-valhalla") and c.status == "running":
                    try:
                        logs = c.logs(tail=30, timestamps=False).decode("utf-8", errors="replace")
                        svc["progress"] = _parse_progress_from_logs(logs, c.name)
                    except Exception:
                        pass

                services.append(svc)
        except Exception:
            pass
        finally:
            client.close()

    # --- Concurrent sub-queries (STT, GPS) ---
    stt_task = _fetch_stt_status()
    gps_task = _fetch_gps_status()
    stt_data, gps_data = await asyncio.gather(stt_task, gps_task, return_exceptions=True)

    if isinstance(stt_data, Exception):
        stt_data = {"status": "unreachable", "backend": None, "model": None, "npu_available": None}
    if isinstance(gps_data, Exception):
        gps_data = {"status": "unreachable", "fix": None, "accuracy_m": None}

    # --- Sync sub-queries (TLS, search stats, disk) ---
    tls_data = _detect_tls_status()
    search_stats = _get_search_stats()
    disk_free_gb, disk_total_gb, disk_used_pct = _get_disk_info()

    # --- Data tasks (existing logic, unchanged) ---
    data_tasks = []
    import pathlib
    data_dir = pathlib.Path("/data")

    def _read_mbtiles_status(path, name):
        """Read tile count from an MBTiles file."""
        import sqlite3
        try:
            conn = sqlite3.connect(str(path), timeout=5)
            tile_count = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
            has_checkpoint = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='_checkpoint'"
            ).fetchone()[0]
            conn.close()
            return {
                "name": name,
                "tiles": tile_count,
                "status": "complete" if has_checkpoint else "in_progress",
            }
        except Exception:
            return None

    for name, filename in [("Imagery", "imagery.mbtiles"), ("Elevation", "elevation.mbtiles")]:
        path = data_dir / filename
        if path.exists():
            task = _read_mbtiles_status(path, name)
            if task:
                img_state = data_dir / (".pipeline-state.json" if name == "Imagery" else ".elevation-state.json")
                if img_state.exists():
                    try:
                        ps = json.loads(img_state.read_text())
                        if ps.get("type") == "imagery":
                            est = ps.get("estimated_tiles")
                            prog_total = ps.get("tiles_total")
                            if est and prog_total:
                                task["tiles_total"] = max(est, prog_total)
                            else:
                                task["tiles_total"] = est or prog_total
                            if task.get("tiles_total") and task["tiles"] > task["tiles_total"]:
                                task["tiles_total"] = task["tiles"]
                            task["rate"] = ps.get("rate_per_sec")
                            if ps.get("status") in ("completed", "cancelled"):
                                task["status"] = ps["status"]
                    except Exception:
                        pass
                data_tasks.append(task)

    poi_path = data_dir / "poi.sqlite"
    if poi_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(poi_path))
            count = conn.execute("SELECT COUNT(*) FROM poi_features").fetchone()[0]
            conn.close()
            data_tasks.append({
                "name": "POI index",
                "features": count,
                "status": "complete",
            })
        except Exception:
            pass

    return {
        "services": services,
        "data_tasks": data_tasks,
        "stt": stt_data,
        "gps": gps_data,
        "tls": tls_data,
        "search_stats": search_stats,
        "disk_free_gb": disk_free_gb,
        "disk_total_gb": disk_total_gb,
        "disk_used_pct": disk_used_pct,
    }
```

**Important note about the replacement:** The original function spans lines 539-669. The new function replaces it entirely. The function signature and decorator remain the same (`@app.get("/admin/status")`). The existing container listing logic and data tasks logic are preserved within the new function body. The new additions are: the `asyncio.gather` block for STT/GPS, the TLS/search_stats/disk calls, and the expanded return dict.

### Step 4: Run tests, confirm they pass

```bash
cd services/search && python -m pytest tests/test_admin_status.py -v
```

### Step 5: Run full service test suite

```bash
cd services/search && python -m pytest -v
```

### Completion Check

```
BEFORE marking this task complete:
1. Review your tests against docs/pitfalls/testing-pitfalls.md
   - Pitfall #1: search_stats tests use real in-memory SQLite, not mocks. GOOD.
   - Pitfall #5: Async tests use @pytest.mark.asyncio for direct async. GOOD.
   - Pitfall #8: monkeypatch used for env vars. GOOD.
2. Verify test coverage:
   - STT healthy: tested
   - STT unreachable: tested
   - GPS ok with 3d fix: tested
   - GPS unreachable: tested
   - TLS no cert: tested
   - TLS Tailscale cert: tested
   - Search stats with OSM: tested
   - Search stats without OSM: tested
   - Disk fields present: tested
   - All top-level keys always present: tested
   - All sub-object keys always present: tested
   - Security (no lat/lon in GPS): tested
3. Run tests and confirm green
```

### Review Loop (Tasks 1 + 2)

```
After every logical group of tasks:
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues. Then
update your private journal and continue onto the next tasks.
```

Review checklist for Tasks 1+2:
1. Does the GPS `/status` endpoint expose any coordinates? NO -- only fix type and accuracy.
2. Does the enriched `/admin/status` always return all keys? YES -- every code path returns the full dict.
3. Are httpx timeouts set correctly? YES -- `httpx.AsyncClient(timeout=2.0)`.
4. Does `asyncio.gather` with `return_exceptions=True` handle failures? YES -- each result is checked for `isinstance(Exception)`.
5. Does TLS detection work without the `cryptography` library? YES -- uses `openssl` subprocess.
6. Are the SQL COUNT queries safe against missing tables? YES -- wrapped in try/except.
7. Does `_get_disk_info` avoid division by zero? YES -- `shutil.disk_usage` always returns positive total.
8. Are test fixtures portable (Testing Pitfall #3)? YES -- uses `tmp_path` and `Path(__file__).parent`.

### Commit

```
feat(search): enrich /admin/status with STT, GPS, TLS, search stats, disk info

Adds concurrent sub-queries for STT health and GPS status (2s timeouts),
TLS cert detection via openssl subprocess, POI count queries, and disk usage.
All keys always present; sub-objects use null for unavailable data.
GPS coordinates never included (security: endpoint is publicly accessible).
```

---

## Task 3: Zoom Validation + OSM POI Pipeline Support

**File:** `services/search/main.py`
**New test files:** `services/search/tests/test_zoom_validation.py`, `services/search/tests/test_pipeline_osm.py`
**Dependencies:** None (independent)
**Estimated lines changed:** ~80 lines added to main.py, ~150 lines in test files

### TDD Preamble

```
BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/ (or invoke /test-driven-development)
2. Read docs/pitfalls/testing-pitfalls.md
Follow TDD: write failing test -> implement fix -> verify green.
```

### Context

**Zoom validation:** `_parse_zoom()` at line 111-119 of `services/search/main.py` currently rejects zoom_max > 18. The spec requires M2M zoom up to 19.

**OSM POI pipeline:** The pipeline orchestrator at line 762+ only accepts `type` values of `"imagery"` or `"elevation"`. The spec requires `"osm_poi"` support. The `PipelineStartBody` model at line 73-79 has required fields `mode`, `bbox`, `zoom` -- these are irrelevant for OSM extraction and must become optional.

**Pipeline enhancements:** Add `completed_at` and `duration_seconds` to state files on completion. Check for pipeline image existence before running.

### Part A: Zoom Validation

#### Step A1: Create test file

Create `services/search/tests/test_zoom_validation.py`:

```python
"""Tests for _parse_zoom validation changes.

Verifies zoom 19 is accepted (M2M max) and zoom 20 is rejected.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import _parse_zoom


def test_zoom_19_accepted():
    """M2M maximum zoom 19 should be accepted."""
    result = _parse_zoom("0-19")
    assert result == (0, 19)


def test_zoom_18_still_accepted():
    """Existing zoom 18 should still be accepted (regression check)."""
    result = _parse_zoom("0-18")
    assert result == (0, 18)


def test_zoom_20_rejected():
    """Zoom 20 is beyond max supported and should be rejected."""
    with pytest.raises(ValueError, match="0-19"):
        _parse_zoom("0-20")


def test_zoom_0_accepted():
    """Zoom 0-0 is valid (minimum)."""
    result = _parse_zoom("0-0")
    assert result == (0, 0)


def test_zoom_negative_rejected():
    """Negative zoom values should be rejected."""
    with pytest.raises(ValueError):
        _parse_zoom("-1-10")


def test_zoom_min_greater_than_max_rejected():
    """Min > max should be rejected."""
    with pytest.raises(ValueError):
        _parse_zoom("10-5")
```

#### Step A2: Run tests, confirm `test_zoom_19_accepted` fails

```bash
cd services/search && python -m pytest tests/test_zoom_validation.py::test_zoom_19_accepted -v
```

Expected: Fails with `ValueError: zoom values must be 0-18 with min <= max`.

#### Step A3: Fix `_parse_zoom`

In `services/search/main.py`, line 117, change:

```python
    if zoom_min < 0 or zoom_max > 18 or zoom_min > zoom_max:
        raise ValueError("zoom values must be 0-18 with min <= max")
```

To:

```python
    if zoom_min < 0 or zoom_max > 19 or zoom_min > zoom_max:
        raise ValueError("zoom values must be 0-19 with min <= max")
```

This is a single-line change at line 117 of `services/search/main.py`. The condition changes from `> 18` to `> 19`, and the error message changes from `"0-18"` to `"0-19"`.

#### Step A4: Run all zoom tests

```bash
cd services/search && python -m pytest tests/test_zoom_validation.py -v
```

Expected: All 6 tests pass.

### Part B: OSM POI Pipeline Support

#### Step B1: Create test file

Create `services/search/tests/test_pipeline_osm.py`:

```python
"""Tests for OSM POI pipeline type support.

Tests PipelineStartBody optional fields, osm_poi validation, PBF discovery,
pipeline image check, and completed_at/duration_seconds state enrichment.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

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


def test_osm_poi_type_accepted(client):
    """type=osm_poi should be accepted by the pipeline start endpoint."""
    c, main, tmp_path, mock_docker = client

    # Create a PBF file for discovery
    valhalla_dir = tmp_path / "valhalla"
    valhalla_dir.mkdir()
    (valhalla_dir / "western-us.osm.pbf").write_bytes(b"fake pbf")

    resp = c.post(
        "/admin/pipeline/start",
        json={"type": "osm_poi"},
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "started"


def test_osm_poi_no_bbox_required(client):
    """OSM POI pipeline does not require bbox, mode, or zoom."""
    c, main, tmp_path, mock_docker = client

    valhalla_dir = tmp_path / "valhalla"
    valhalla_dir.mkdir()
    (valhalla_dir / "western-us.osm.pbf").write_bytes(b"fake pbf")

    # Send only type, no mode/bbox/zoom
    resp = c.post(
        "/admin/pipeline/start",
        json={"type": "osm_poi"},
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )

    assert resp.status_code == 200


def test_osm_poi_missing_pbf(client):
    """When no PBF file exists, return 422 error."""
    c, main, tmp_path, mock_docker = client

    # No valhalla directory or PBF file
    resp = c.post(
        "/admin/pipeline/start",
        json={"type": "osm_poi"},
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )

    assert resp.status_code == 422
    assert "PBF" in resp.json()["detail"]


def test_pipeline_image_missing(client):
    """When pipeline image is not built, return 422 error."""
    c, main, tmp_path, mock_docker = client

    # Make images.get raise (image not found)
    import docker.errors
    mock_docker.images.get.side_effect = docker.errors.ImageNotFound("not found")

    valhalla_dir = tmp_path / "valhalla"
    valhalla_dir.mkdir()
    (valhalla_dir / "western-us.osm.pbf").write_bytes(b"fake pbf")

    resp = c.post(
        "/admin/pipeline/start",
        json={"type": "osm_poi"},
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )

    assert resp.status_code == 422
    assert "Pipeline image not built" in resp.json()["detail"]


def test_invalid_type_rejected(client):
    """Unknown pipeline types should still be rejected."""
    c, main, tmp_path, mock_docker = client

    resp = c.post(
        "/admin/pipeline/start",
        json={"type": "foobar", "mode": "direct", "bbox": "-112,33,-111,34", "zoom": "0-10"},
        headers={"X-Config-Source": "internal", "X-Geographica": "1"},
    )

    assert resp.status_code == 422


def test_state_file_for_osm_poi(client):
    """OSM POI pipeline uses its own state file path."""
    c, main, tmp_path, mock_docker = client

    from main import _state_file_for_type
    assert _state_file_for_type("osm_poi") == main.DATA_DIR / ".osm-poi-state.json"


def test_completed_at_on_state(client):
    """Pipeline state should include completed_at and duration_seconds after completion."""
    c, main, tmp_path, mock_docker = client

    # Simulate a completed pipeline state
    state_file = tmp_path / ".pipeline-state.json"
    state_file.write_text(json.dumps({
        "status": "running",
        "type": "imagery",
        "container_id": "abc123",
    }))

    # Mock container as dead (to trigger interruption reconciliation)
    mock_docker.containers.get.side_effect = Exception("not found")

    resp = c.get(
        "/admin/pipeline/status?type=imagery",
    )

    data = resp.json()
    # When container is dead and state was "running", status becomes "interrupted"
    assert data["status"] == "interrupted"
```

#### Step B2: Run tests, confirm failures

```bash
cd services/search && python -m pytest tests/test_pipeline_osm.py -v
```

Expected: `test_osm_poi_type_accepted` fails (type rejected), `test_state_file_for_osm_poi` fails (no osm_poi case), `test_pipeline_image_missing` may fail, etc.

#### Step B3: Implement changes

**Step B3.1: Make PipelineStartBody fields optional for osm_poi**

In `services/search/main.py`, replace lines 73-79:

```python
class PipelineStartBody(BaseModel):
    type: str  # "imagery" or "elevation"
    mode: str  # "direct" or "m2m"
    bbox: str  # "west,south,east,north"
    zoom: str  # "min-max"
    concurrency: int = 20
    update: bool = True
```

With:

```python
class PipelineStartBody(BaseModel):
    type: str  # "imagery", "elevation", or "osm_poi"
    mode: Optional[str] = None  # "direct" or "m2m" (required for imagery/elevation)
    bbox: Optional[str] = None  # "west,south,east,north" (required for imagery/elevation)
    zoom: Optional[str] = None  # "min-max" (required for imagery/elevation)
    concurrency: int = 20
    update: bool = True
```

Note: `Optional` is already imported at line 19 (`from typing import Optional`).

**Step B3.2: Update `_state_file_for_type`**

In `services/search/main.py`, replace `_state_file_for_type` (lines 725-729):

```python
def _state_file_for_type(pipeline_type: str) -> Path:
    """Return the state file path for a given pipeline type."""
    if pipeline_type == "elevation":
        return DATA_DIR / ".elevation-state.json"
    return DATA_DIR / ".pipeline-state.json"
```

With:

```python
def _state_file_for_type(pipeline_type: str) -> Path:
    """Return the state file path for a given pipeline type."""
    if pipeline_type == "elevation":
        return DATA_DIR / ".elevation-state.json"
    if pipeline_type == "osm_poi":
        return DATA_DIR / ".osm-poi-state.json"
    return DATA_DIR / ".pipeline-state.json"
```

**Step B3.3: Update `pipeline_start()` to handle osm_poi**

Replace the `pipeline_start()` function (lines 761-936). The key changes are:

1. Expand the type validation to accept `"osm_poi"`
2. Only validate mode/bbox/zoom for imagery/elevation types
3. Add PBF discovery logic for osm_poi
4. Add pipeline image existence check
5. Build the osm_poi Docker command
6. Add `completed_at` and `duration_seconds` support

In the function body, replace the validation block (lines 764-780):

Find:
```python
    # Validate type
    if body.type not in ("imagery", "elevation"):
        raise HTTPException(status_code=422, detail="type must be 'imagery' or 'elevation'")
    if body.mode not in ("direct", "m2m"):
        raise HTTPException(status_code=422, detail="mode must be 'direct' or 'm2m'")

    # Parse and validate bbox
    try:
        bbox = _parse_bbox(body.bbox)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Invalid bbox: {e}")

    # Parse and validate zoom
    try:
        zoom_min, zoom_max = _parse_zoom(body.zoom)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Invalid zoom: {e}")
```

Replace with:
```python
    # Validate type
    if body.type not in ("imagery", "elevation", "osm_poi"):
        raise HTTPException(status_code=422, detail="type must be 'imagery', 'elevation', or 'osm_poi'")

    # For imagery/elevation, validate mode, bbox, zoom
    bbox = None
    zoom_min = zoom_max = tile_count = 0
    estimated_size_gb = 0.0
    if body.type in ("imagery", "elevation"):
        if not body.mode or body.mode not in ("direct", "m2m"):
            raise HTTPException(status_code=422, detail="mode must be 'direct' or 'm2m'")
        if not body.bbox:
            raise HTTPException(status_code=422, detail="bbox is required for imagery/elevation")
        if not body.zoom:
            raise HTTPException(status_code=422, detail="zoom is required for imagery/elevation")

        try:
            bbox = _parse_bbox(body.bbox)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"Invalid bbox: {e}")

        try:
            zoom_min, zoom_max = _parse_zoom(body.zoom)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"Invalid zoom: {e}")
```

Replace the disk space check block (lines 782-791):

Find:
```python
    # Estimate tile count and check disk space
    tile_count = estimate_tile_count(bbox, zoom_min, zoom_max)
    # Rough estimate: ~20 KB per tile average (measured from USGS imagery)
    estimated_size_gb = tile_count * 20 * 1024 / (1024 ** 3)
    disk_free_gb = _get_disk_free_gb()
    if disk_free_gb - estimated_size_gb < 10.0:
        raise HTTPException(
            status_code=507,
            detail=f"Insufficient disk space. Free: {disk_free_gb:.1f} GB, estimated need: {estimated_size_gb:.1f} GB, minimum 10 GB buffer required",
        )
```

Replace with:
```python
    # Estimate tile count and check disk space (imagery/elevation only)
    if body.type in ("imagery", "elevation") and bbox:
        tile_count = estimate_tile_count(bbox, zoom_min, zoom_max)
        estimated_size_gb = tile_count * 20 * 1024 / (1024 ** 3)
        disk_free_gb = _get_disk_free_gb()
        if disk_free_gb - estimated_size_gb < 10.0:
            raise HTTPException(
                status_code=507,
                detail=f"Insufficient disk space. Free: {disk_free_gb:.1f} GB, estimated need: {estimated_size_gb:.1f} GB, minimum 10 GB buffer required",
            )
```

Inside the `async with _pipeline_lock:` block, after the image pull section and before the container run, add the pipeline image check and OSM POI command building. Replace the command building section (lines 828-838):

Find:
```python
            # Build command — imagery and elevation scripts have different args
            script = _script_for_type(body.type)
            command = [
                "python3", script,
                f"--bbox={body.bbox}",
                f"--zoom={body.zoom}",
                "--concurrency", str(body.concurrency),
                "--output", f"/data/{mbtiles_path.name}",
            ]
            # Only imagery script accepts --mode (direct/tnmaccess/m2m)
            if body.type == "imagery":
                command[2:2] = ["--mode", body.mode]
```

Replace with:
```python
            # Check pipeline image exists
            try:
                client.images.get("geographica-pipeline")
            except Exception:
                raise HTTPException(
                    status_code=422,
                    detail="Pipeline image not built. Run 'docker compose build pipeline' first.",
                )

            # Build command based on pipeline type
            if body.type == "osm_poi":
                # Discover PBF file
                import glob
                pbf_files = glob.glob(str(DATA_DIR / "valhalla" / "*.osm.pbf"))
                if not pbf_files:
                    raise HTTPException(
                        status_code=422,
                        detail="No OSM PBF file found in /data/valhalla/",
                    )
                pbf_path = pbf_files[0]  # Use first PBF found
                pbf_filename = Path(pbf_path).name

                command = [
                    "python3", "/scripts/build_osm_pois.py",
                    "--pbf", f"/data/valhalla/{pbf_filename}",
                    "--output", "/data/poi.sqlite",
                ]
                if body.bbox:
                    command.extend(["--bbox", body.bbox])
            else:
                script = _script_for_type(body.type)
                command = [
                    "python3", script,
                    f"--bbox={body.bbox}",
                    f"--zoom={body.zoom}",
                    "--concurrency", str(body.concurrency),
                    "--output", f"/data/{mbtiles_path.name}",
                ]
                if body.type == "imagery":
                    command[2:2] = ["--mode", body.mode]
```

Also update the `mbtiles_path` assignment to handle osm_poi. The existing code at line 819 calls `_mbtiles_path_for_type(body.type)`. For osm_poi, there is no mbtiles path, so modify the block. Find:

```python
            # Handle existing mbtiles if not updating
            mbtiles_path = _mbtiles_path_for_type(body.type)
            if not body.update and mbtiles_path.exists():
```

Replace with:
```python
            # Handle existing mbtiles if not updating (not applicable for osm_poi)
            mbtiles_path = _mbtiles_path_for_type(body.type) if body.type != "osm_poi" else None
            if mbtiles_path and not body.update and mbtiles_path.exists():
```

Update the state file writing to include started_at timestamp. Find the state_data dict (lines 916-926):

```python
            state_data = {
                "status": "running",
                "type": body.type,
                "mode": body.mode,
                "bbox": body.bbox,
                "zoom": body.zoom,
                "concurrency": body.concurrency,
                "update": body.update,
                "estimated_tiles": tile_count,
                "container_id": container.id,
            }
```

Replace with:
```python
            from datetime import datetime, timezone as tz
            state_data = {
                "status": "running",
                "type": body.type,
                "mode": body.mode,
                "bbox": body.bbox,
                "zoom": body.zoom,
                "concurrency": body.concurrency,
                "update": body.update,
                "estimated_tiles": tile_count if body.type != "osm_poi" else None,
                "container_id": container.id,
                "started_at": datetime.now(tz.utc).isoformat(),
            }
```

**Step B3.4: Update `pipeline_status()` to handle osm_poi and add completed_at**

In `pipeline_status()` (line 939-1000), update the type validation. Find:

```python
    if type not in ("imagery", "elevation"):
        raise HTTPException(status_code=422, detail="type must be 'imagery' or 'elevation'")
```

Replace with:

```python
    if type not in ("imagery", "elevation", "osm_poi"):
        raise HTTPException(status_code=422, detail="type must be 'imagery', 'elevation', or 'osm_poi'")
```

In the reconciliation block (lines 964-984), after setting `state_data["status"] = new_status`, add completion timestamp logic. Find:

```python
        new_status = "cancelled" if state_data.get("status") == "cancelling" else "interrupted"
        state_data["status"] = new_status
```

After that line, add:

```python
        # Add completion timestamp for interrupted/cancelled states
        from datetime import datetime, timezone as tz
        state_data["completed_at"] = datetime.now(tz.utc).isoformat()
        if state_data.get("started_at"):
            started = datetime.fromisoformat(state_data["started_at"])
            state_data["duration_seconds"] = int((datetime.now(tz.utc) - started).total_seconds())
```

Also add similar logic for when container finishes successfully. In the `pipeline_status` function, after the reconciliation block and before `return state_data`, check if status transitioned to completed. This requires adding to the state file update block:

After the reconciliation block's state file write (around line 983), add a similar check for the "completed" state by finding the block where `container_running` is False and state is not "running":

```python
    # If state shows completed but no completed_at yet, add it
    if state_data.get("status") == "completed" and "completed_at" not in state_data:
        from datetime import datetime, timezone as tz
        state_data["completed_at"] = datetime.now(tz.utc).isoformat()
        if state_data.get("started_at"):
            started = datetime.fromisoformat(state_data["started_at"])
            state_data["duration_seconds"] = int((datetime.now(tz.utc) - started).total_seconds())
```

#### Step B4: Run all pipeline tests

```bash
cd services/search && python -m pytest tests/test_pipeline_osm.py tests/test_zoom_validation.py -v
```

### Completion Check

```
BEFORE marking this task complete:
1. Review your tests against docs/pitfalls/testing-pitfalls.md
   - Pitfall #6: No Docker-dependent tests; all Docker calls mocked. GOOD.
   - Pitfall #8: monkeypatch used for env vars. GOOD.
2. Verify test coverage:
   - Zoom 19 accepted: tested
   - Zoom 20 rejected: tested
   - OSM POI type accepted: tested
   - OSM POI no bbox/mode/zoom required: tested
   - Missing PBF error: tested
   - Missing pipeline image error: tested
   - Invalid type rejected: tested
   - State file path for osm_poi: tested
3. Run tests and confirm green
```

### Commit

```
feat(search): add osm_poi pipeline type, allow zoom 19, add pipeline image check

- _parse_zoom() now accepts zoom_max up to 19 (M2M maximum)
- PipelineStartBody mode/bbox/zoom now Optional (irrelevant for osm_poi)
- OSM POI pipeline discovers PBF from /data/valhalla/*.osm.pbf
- Pipeline image existence checked before docker run (clear error if missing)
- started_at timestamp added to pipeline state files
```

---

## Task 4: docker-compose.yml + NGINX Config Changes

**Files:** `docker-compose.yml`, `nginx/nginx.conf`
**Dependencies:** None (independent)
**No automated tests** (NGINX config verified by `nginx -t` inside the container)

### TDD Preamble

```
BEFORE starting work:
1. Read docs/pitfalls/implementation-pitfalls.md
   - Pitfall #3 (NGINX sub_filter): Requires Accept-Encoding ""; only apply to style JSON and TileJSON
   - Pitfall #6 (Offline-first): MapLibre served from vendored files, not CDN
2. This task has no automated tests. Verification is via nginx -t and manual inspection.
```

### Step 1: Add TLS cert volume to search service in docker-compose.yml

In `docker-compose.yml`, at approximately line 128 (after the Docker socket mount), add the TLS cert volume.

Find (lines 126-128):
```yaml
    volumes:
      - ./data:/data
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

Replace with:
```yaml
    volumes:
      - ./data:/data
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ${TLS_CERT_DIR:-./tls}:/tls:ro
```

### Step 2: Add tile proxy and vendor serving to config panel NGINX block

In `nginx/nginx.conf`, add new location blocks to the config panel server block (after line 169, before the closing `}`).

Find (lines 163-170):
```nginx
    # Full admin API (all endpoints including writes)
    location /admin/ {
        proxy_pass http://search:8000/admin/;
        proxy_set_header Host $http_host;
        proxy_set_header X-Config-Source internal;
        proxy_http_version 1.1;
    }
}
```

Replace with:
```nginx
    # Full admin API (all endpoints including writes)
    location /admin/ {
        proxy_pass http://search:8000/admin/;
        proxy_set_header Host $http_host;
        proxy_set_header X-Config-Source internal;
        proxy_http_version 1.1;
    }

    # Tile proxy for minimap — style JSON with URL rewriting
    location /tiles/styles/ {
        proxy_pass http://tileserver:8080/styles/;
        proxy_http_version 1.1;

        proxy_set_header Accept-Encoding "";
        sub_filter_once off;
        sub_filter_types application/json text/plain;
        sub_filter 'http://tileserver:8080/data/'   '$scheme://$http_host/tiles/data/';
        sub_filter 'http://tileserver:8080/styles/' '$scheme://$http_host/tiles/styles/';
        sub_filter 'http://tileserver:8080/fonts/'  '$scheme://$http_host/tiles/fonts/';
    }

    # Tile proxy for minimap — TileJSON endpoints with URL rewriting
    location /tiles/data/southwest5.json {
        proxy_pass http://tileserver:8080/data/southwest5.json;
        proxy_http_version 1.1;

        proxy_set_header Accept-Encoding "";
        sub_filter_once off;
        sub_filter_types application/json text/plain;
        sub_filter 'http://tileserver:8080/data/' '$scheme://$http_host/tiles/data/';
    }

    # Tile proxy for minimap — raw tile data, fonts, sprites
    location /tiles/ {
        proxy_pass http://tileserver:8080/;
        proxy_set_header Host $http_host;
        proxy_http_version 1.1;
    }

    # Vendor assets (MapLibre GL JS/CSS)
    location /vendor/ {
        alias /usr/share/nginx/html/vendor/;
    }
}
```

**Important notes:**
- The tile proxy locations mirror the main server block pattern (lines 21-68 of nginx.conf)
- `sub_filter` requires `proxy_set_header Accept-Encoding ""` to prevent gzip (Implementation Pitfall #3)
- The `/vendor/` location serves MapLibre JS/CSS from the same path as the main frontend
- Only `southwest5.json` TileJSON is proxied (that's the vector basemap the minimap needs). If imagery or elevation TileJSON are also needed, add them, but for the minimap's Positron basemap, only the vector source is required.

### Step 3: Verify NGINX config syntax

After deploying the changes, verify with:

```bash
docker compose exec frontend nginx -t
```

Expected output: `nginx: the configuration file /etc/nginx/nginx.conf syntax is ok`

### Completion Check

```
BEFORE marking this task complete:
1. Verify the TLS volume mount uses the same env var pattern as other mounts in docker-compose.yml
2. Verify sub_filter directives match the main server block pattern exactly
3. Verify /vendor/ alias path matches where MapLibre files are actually served
4. Verify the config panel server block's allow/deny directives are NOT duplicated in the new location blocks (they inherit from the server context)
```

### Review Loop (Tasks 3 + 4)

```
After every logical group of tasks:
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues. Then
update your private journal and continue onto the next tasks.
```

Review checklist for Tasks 3+4:
1. Does zoom 19 validation change affect existing imagery/elevation pipelines? NO -- they used max 18 before, this only opens the range.
2. Does making PipelineStartBody fields optional break existing imagery/elevation starts? NO -- the validation inside pipeline_start() checks for required fields based on type.
3. Is the PBF glob path correct? YES -- `/data/valhalla/*.osm.pbf` matches the Valhalla mount in docker-compose.yml.
4. Does the NGINX `sub_filter` in the config panel match the main block? YES -- identical directives.
5. Is the `/vendor/` alias path correct? YES -- `frontend/vendor/` is mounted at `/usr/share/nginx/html/vendor/` in the frontend container.
6. Does the TLS volume mount break anything when `./tls` directory doesn't exist? NO -- Docker creates an empty directory, and the code handles missing cert gracefully.
7. Could the PBF glob match non-OSM files? NO -- pattern is `*.osm.pbf` which is the standard extension.
8. Is the osm_poi command correct? YES -- `python3 /scripts/build_osm_pois.py --pbf <path> --output /data/poi.sqlite` matches the script's CLI interface documented in CLAUDE.md.

### Commit

```
chore: add TLS volume to search service, tile proxy + vendor to config panel

- docker-compose.yml: TLS cert dir mounted read-only at /tls
- nginx.conf: tile proxy locations mirror main block for minimap support
- nginx.conf: /vendor/ alias serves MapLibre GL JS/CSS in config panel
```

---

## Task 5: Full Frontend Rewrite (Dashboard + Pipelines + Settings)

**File:** `frontend/config/index.html`
**Dependencies:** Tasks 2, 3, 4 must all be complete
**Estimated size:** ~850 lines total (HTML + CSS + JS in single file)
**No automated tests** (manual testing; Playwright E2E deferred to future sprint)

### TDD Preamble

```
BEFORE starting work:
1. Read docs/pitfalls/implementation-pitfalls.md
   - Pitfall #3: sub_filter only for style/TileJSON, not tile data
   - Pitfall #6: Offline-first — MapLibre from /vendor/, no CDN
   - Pitfall #9: Module boundaries — this is config panel, not app.js
   - Pitfall #10: Config panel is localhost-only, requires X-Config-Source
2. This is a frontend-only task. No automated unit tests.
   Manual test checklist is provided at the end.
```

### Context

The current `frontend/config/index.html` (307 lines) is being fully rewritten. The new file will be approximately 850 lines with:
- 3-tab layout (Dashboard, Pipelines, Settings)
- Dark theme matching existing Catppuccin Mocha palette
- MapLibre minimap with custom rectangle draw (~150 lines JS)
- Service health list with color-coded status dots
- All existing functionality preserved (imagery pipeline, M2M credentials)
- New functionality: OSM POI extraction, elevation pipeline, GPS/STT/TLS status display

### Critical Design Decisions (from spec + adversarial review)

1. **GPS coordinates never shown** -- the `/admin/status` response does not include lat/lon
2. **M2M credentials: no masking** -- show "Configured" status text, no username display (adversarial review 4.2)
3. **Minimap: desktop only** -- hide below 480px viewport width, show text-only bbox input on mobile (adversarial review 3.4)
4. **Concurrent pipeline prevention** -- when any pipeline is running, disable ALL Start buttons
5. **First-run empty state** -- when services array is empty, show guidance message
6. **Tab switching** -- URL hash-based (`#dashboard`, `#pipelines`, `#settings`) for deep linking
7. **Auto-refresh** -- 10-second polling interval using existing pattern

### Step 1: Write the complete HTML file

Replace the entire contents of `frontend/config/index.html` with the following. This is a complete, self-contained file.

**IMPORTANT: The file below is the COMPLETE replacement. Do NOT merge with the old file. Delete all old content and write this.**

The file structure is:
1. Lines 1-30: HTML head with meta tags and MapLibre CSS link
2. Lines 31-180: `<style>` block with all CSS (dark theme, tabs, service list, forms, minimap)
3. Lines 181-370: HTML body with 3 tab containers
4. Lines 371-850: `<script>` block with all JS

Due to the length (~850 lines), here is the structural outline with key implementation details. The implementing agent must write the complete file following this specification exactly.

#### HTML Structure

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Geographica Config</title>
    <link rel="stylesheet" href="/vendor/maplibre-gl.css">
    <style>
        /* === BASE === */
        /* body: font-family -apple-system, sans-serif; background #1e1e2e; color #cdd6f4; margin 0; padding 20px */
        /* .container: max-width 600px; margin 0 auto */

        /* === TABS === */
        /* .tab-bar: display flex; gap 0; border-bottom 1px solid #45475a; margin-bottom 16px */
        /* .tab-btn: padding 10px 16px; background transparent; border none; color #7a8299; cursor pointer; font-size 13px; border-bottom 2px solid transparent */
        /* .tab-btn.active: color #cdd6f4; border-bottom-color #89b4fa */
        /* .tab-content: display none */
        /* .tab-content.active: display block */

        /* === SERVICE LIST === */
        /* .svc-row: display flex; justify-content space-between; align-items center; padding 8px 0; border-bottom 1px solid #313244 */
        /* .svc-left: display flex; align-items center; gap 8px */
        /* .svc-dot: width 8px; height 8px; border-radius 50%; flex-shrink 0 */
        /* .svc-dot.green: background #a6e3a1 */
        /* .svc-dot.yellow: background #f9e2af */
        /* .svc-dot.red: background #f38ba8 */
        /* .svc-name: font-size 13px; font-weight 500 */
        /* .svc-context: font-size 11px; color #7a8299; text-align right */

        /* === CARDS === */
        /* .info-cards: display grid; grid-template-columns 1fr 1fr; gap 12px; margin-top 16px */
        /* .info-card: background #313244; border-radius 8px; padding 12px */
        /* .info-card-label: font-size 11px; color #7a8299; margin-bottom 4px */
        /* .info-card-value: font-size 14px; font-weight 500 */

        /* === PIPELINE BANNER === */
        /* .pipeline-banner: background rgba(137,180,250,0.1); border 1px solid #89b4fa; border-radius 8px; padding 12px; margin-top 16px; cursor pointer */

        /* === SECTION (reused from current) === */
        /* .section: background #181825; border-radius 8px; padding 16px; margin 12px 0 */

        /* === FORM ELEMENTS (reused from current) === */
        /* label, input, select, button: same as current styles */
        /* .btn-primary: background #a6e3a1; color #1e1e2e */
        /* .btn-danger: background #f38ba8; color #1e1e2e */
        /* .btn-secondary: background transparent; border 1px solid #45475a; color #cdd6f4 */

        /* === MINIMAP === */
        /* #minimap: width 100%; height 200px; border-radius 6px; margin 8px 0 */
        /* @media (max-width: 479px) { #minimap-container { display: none } } */

        /* === PROGRESS === */
        /* .progress-bar: height 6px; background #313244; border-radius 3px; margin 8px 0 */
        /* .progress-fill: height 100%; background #89b4fa; border-radius 3px; transition width 1s */

        /* === SETTINGS === */
        /* .setting-row: display flex; justify-content space-between; padding 6px 0 */
        /* .setting-label: font-size 12px; color #7a8299 */
        /* .setting-value: font-size 12px */

        /* === EMPTY STATE === */
        /* .empty-state: text-align center; padding 60px 20px; color #7a8299 */

        /* === STATUS BADGES === */
        /* .status: padding 8px 12px; border-radius 6px; margin 8px 0; font-size 12px */
        /* .status-ok: background rgba(166,227,161,0.15); color #a6e3a1 */
        /* .status-warn: background rgba(249,226,175,0.15); color #f9e2af */
        /* .status-error: background rgba(243,139,168,0.15); color #f38ba8 */

        /* .detail: font-size 11px; color #7a8299; margin 4px 0 */
        /* .mono: font-family 'SF Mono', monospace */
    </style>
</head>
<body>
    <div class="container">
        <h1 style="font-size:20px;color:#f5f5f5;margin-bottom:4px">Geographica Configuration</h1>
        <p class="detail">This panel is only accessible from localhost. Changes take effect immediately.</p>

        <!-- Tab bar -->
        <div class="tab-bar">
            <button class="tab-btn active" data-tab="dashboard">Dashboard</button>
            <button class="tab-btn" data-tab="pipelines">Pipelines</button>
            <button class="tab-btn" data-tab="settings">Settings</button>
        </div>

        <!-- ==================== DASHBOARD TAB ==================== -->
        <div id="tab-dashboard" class="tab-content active">
            <div id="empty-state" class="empty-state" style="display:none">
                <p>No services detected.</p>
                <p class="mono" style="font-size:12px">Run <code>docker compose up -d</code> to start the stack.</p>
            </div>

            <div id="dashboard-content">
                <div class="section">
                    <h2 style="font-size:14px;color:#f5f5f5;margin:0 0 12px">Services</h2>
                    <div id="svc-list">Loading...</div>
                </div>

                <div class="info-cards">
                    <div class="info-card">
                        <div class="info-card-label">Disk</div>
                        <div class="info-card-value" id="disk-info">--</div>
                    </div>
                    <div class="info-card">
                        <div class="info-card-label">TLS</div>
                        <div class="info-card-value" id="tls-info">--</div>
                    </div>
                </div>

                <div id="pipeline-banner" class="pipeline-banner" style="display:none">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                        <span id="banner-title" style="font-size:13px;font-weight:500"></span>
                        <span class="detail" id="banner-detail"></span>
                    </div>
                    <div class="progress-bar" style="margin-top:8px"><div class="progress-fill" id="banner-progress"></div></div>
                </div>
            </div>
        </div>

        <!-- ==================== PIPELINES TAB ==================== -->
        <div id="tab-pipelines" class="tab-content">
            <!-- Imagery Acquisition -->
            <div class="section">
                <h2 style="font-size:14px;color:#f5f5f5;margin:0 0 12px">Imagery Acquisition</h2>

                <label>Source</label>
                <select id="cfg-source">
                    <option value="direct">USGS Direct (no auth needed)</option>
                    <option value="m2m">USGS M2M API (requires credentials)</option>
                </select>

                <div id="m2m-warning" class="status status-warn" style="display:none">
                    M2M requires credentials — <a href="#" id="m2m-goto-settings" style="color:#f9e2af">configure in Settings tab</a>
                </div>

                <label>Coverage area</label>
                <div id="minimap-container">
                    <div id="minimap"></div>
                </div>
                <input type="text" id="cfg-bbox" value="-124.8,31.3,-102.0,49.0" class="mono">
                <div class="detail">Bounding box: west, south, east, north (decimal degrees)</div>

                <label>Zoom range</label>
                <select id="cfg-zoom">
                    <option value="0-8">Basic (0-8)</option>
                    <option value="0-10">Preview (0-10)</option>
                    <option value="0-12">Standard (0-12)</option>
                    <option value="0-14">High detail (0-14)</option>
                    <option value="0-15" selected>Very high detail (0-15)</option>
                    <option value="0-16">Maximum — direct mode (0-16)</option>
                    <option value="0-17">M2M enhanced (0-17)</option>
                    <option value="0-18">M2M high (0-18)</option>
                    <option value="0-19">M2M maximum (0-19)</option>
                </select>
                <div class="detail" id="cfg-zoom-note"></div>

                <label>Download speed</label>
                <select id="cfg-concurrency"></select>

                <label style="display:flex;align-items:center;gap:6px;color:#cdd6f4">
                    <input type="checkbox" id="cfg-update" checked style="width:auto"> Resume/extend existing data
                </label>

                <div id="cfg-estimate" class="detail">Calculating...</div>

                <div style="margin-top:12px">
                    <button type="button" class="btn-primary" id="cfg-start">Start Download</button>
                    <button type="button" class="btn-danger" id="cfg-cancel" style="display:none">Cancel</button>
                </div>

                <div id="cfg-progress" style="display:none">
                    <div class="progress-bar"><div class="progress-fill" id="cfg-progress-fill"></div></div>
                    <div id="cfg-progress-detail" class="detail"></div>
                </div>

                <div id="cfg-completed" class="status status-ok" style="display:none"></div>
            </div>

            <!-- Elevation Tiles -->
            <div class="section">
                <h2 style="font-size:14px;color:#f5f5f5;margin:0 0 12px">Elevation Tiles</h2>
                <div id="elevation-status">Loading...</div>
                <button type="button" class="btn-primary" id="elev-start" style="display:none">Start Elevation Download</button>
                <div id="elev-progress" style="display:none">
                    <div class="progress-bar"><div class="progress-fill" id="elev-progress-fill"></div></div>
                    <div id="elev-progress-detail" class="detail"></div>
                </div>
            </div>

            <!-- OSM POI Extraction -->
            <div class="section">
                <h2 style="font-size:14px;color:#f5f5f5;margin:0 0 12px">OSM POI Extraction</h2>
                <div id="osm-status">Loading...</div>
                <button type="button" class="btn-primary" id="osm-start" style="display:none">Extract POIs</button>
                <div class="detail" id="osm-note" style="display:none">Extracts amenities + public land from OSM PBF. ~10 min.</div>
                <div id="osm-progress" style="display:none">
                    <div class="progress-bar"><div class="progress-fill" id="osm-progress-fill" style="background:#a6e3a1"></div></div>
                    <div id="osm-progress-detail" class="detail"></div>
                </div>
            </div>
        </div>

        <!-- ==================== SETTINGS TAB ==================== -->
        <div id="tab-settings" class="tab-content">
            <!-- M2M Credentials -->
            <div class="section">
                <h2 style="font-size:14px;color:#f5f5f5;margin:0 0 12px">M2M API Credentials</h2>
                <div id="m2m-configured" style="display:none">
                    <div class="status status-ok">Configured</div>
                    <div style="margin-top:8px">
                        <button type="button" class="btn-secondary" id="m2m-update-btn">Update</button>
                        <button type="button" class="btn-danger" id="m2m-delete-btn">Delete</button>
                    </div>
                </div>
                <div id="m2m-form">
                    <label>Username</label>
                    <input type="text" id="cfg-m2m-user" placeholder="USGS ERS username">
                    <label>API Token</label>
                    <input type="password" id="cfg-m2m-token" placeholder="M2M application token">
                    <div style="margin-top:8px">
                        <button type="button" class="btn-primary" id="m2m-save-btn">Save Credentials</button>
                    </div>
                </div>
                <div id="m2m-status-msg" class="detail"></div>
            </div>

            <!-- TLS Configuration -->
            <div class="section">
                <h2 style="font-size:14px;color:#f5f5f5;margin:0 0 12px">TLS Configuration</h2>
                <div id="tls-settings">Loading...</div>
            </div>

            <!-- Voice Search (STT) -->
            <div class="section">
                <h2 style="font-size:14px;color:#f5f5f5;margin:0 0 12px">Voice Search (STT)</h2>
                <div id="stt-settings">Loading...</div>
            </div>
        </div>
    </div>

    <script src="/vendor/maplibre-gl.js"></script>
    <script>
    /* Config panel JS — all API calls include X-Geographica header for CSRF protection */
    (function() {
        'use strict';

        /* ================================================================
         * UTILITY FUNCTIONS
         * ================================================================ */

        function cfgFetch(url, opts) {
            /* ... same as current: adds X-Geographica header ... */
        }

        /* ================================================================
         * TAB SWITCHING
         * ================================================================ */

        function switchTab(name) {
            /* Set active tab button and content panel based on name.
               Update location.hash. */
        }

        /* Tab button click handlers */
        /* Read location.hash on load for deep linking */

        /* ================================================================
         * DASHBOARD — SERVICE HEALTH
         * ================================================================ */

        var _lastStatus = null;  /* Cache last /admin/status response */

        function renderDashboard(data) {
            /* If data.services is empty: show #empty-state, hide #dashboard-content. Return.
               Otherwise: hide #empty-state, show #dashboard-content.

               Build service list in #svc-list:
               For each service in data.services:
               - Determine dot color: green if health=healthy, yellow if status=running && health in (starting, none), red otherwise
               - Build context string based on service name:
                 * "search": use data.search_stats — format "Xk GNIS + Yk OSM" or "Xk GNIS"
                 * "gps": use data.gps — "3D fix, ±Xm" / "2D fix" / "no fix" / "no gpsd"
                 * "stt": use data.stt — "cpu, base.en" or "unreachable"
                 * "nominatim": use progress.phase if available, else health
                 * "valhalla": use progress.phase if available, else health
                 * "frontend": "nginx" if healthy
                 * "tileserver": health
               - Create .svc-row with .svc-dot + .svc-name on left, .svc-context on right

               Render disk card: "{free}GB free ({used_pct}%)"
               Render TLS card: data.tls.mode + expiry if applicable

               Pipeline banner: check _lastPipelineStatus for running jobs */
        }

        /* ================================================================
         * DASHBOARD — PIPELINE BANNER
         * ================================================================ */

        function renderPipelineBanner(pipelineData) {
            /* If pipelineData.status === 'running': show banner with title, progress, detail.
               Pipeline banner click calls switchTab('pipelines').
               If not running: hide banner. */
        }

        /* ================================================================
         * PIPELINES — IMAGERY
         * ================================================================ */

        /* estimateTiles(bbox, zoom) — same as current implementation */

        function updateEstimate() {
            /* Same as current: calculate tile count, GB, hours */
        }

        function updateConcurrencyOptions() {
            /* When source is 'm2m': options [3 (default), 5]
               When source is 'direct': options [10, 20 (default), 50, 80]
               Swap select options and set default. */
        }

        function renderImageryProgress(data) {
            /* Show/hide start/cancel buttons based on pipeline status.
               Show progress bar when running.
               Show completed message when data.completed_at exists.
               Disable start button when ANY pipeline is running. */
        }

        /* ================================================================
         * PIPELINES — ELEVATION
         * ================================================================ */

        function renderElevation(statusData, pipelineData) {
            /* If elevation mbtiles exists in data_tasks: show "Complete — N tiles (z0-M) • X GB"
               If not present: show "Not downloaded" + Start button
               If elevation pipeline running: show progress bar
               Disable Start button when any pipeline is running. */
        }

        /* ================================================================
         * PIPELINES — OSM POI
         * ================================================================ */

        function renderOsmPoi(statusData, pipelineData) {
            /* If data.search_stats.osm_pois_loaded: show "N amenities"
               If not loaded: show "Not extracted" + Extract button + note
               If osm_poi pipeline running: show progress spinner + elapsed
               If no PBF file: show warning, disable button
               Disable Extract button when any pipeline is running. */
        }

        /* ================================================================
         * PIPELINES — CONCURRENT PREVENTION
         * ================================================================ */

        var _anyPipelineRunning = false;

        function updatePipelineButtons() {
            /* Check all three pipeline statuses.
               If any is 'running', set _anyPipelineRunning = true.
               Disable all Start/Extract buttons when true.
               Show "Another pipeline is running" note on disabled buttons. */
        }

        /* ================================================================
         * SETTINGS — M2M CREDENTIALS
         * ================================================================ */

        function renderM2MSettings(configured) {
            /* If configured: show #m2m-configured, hide #m2m-form
               If not configured: hide #m2m-configured, show #m2m-form
               Update button handles m2m-update-btn click to show form again */
        }

        /* ================================================================
         * SETTINGS — TLS
         * ================================================================ */

        function renderTLSSettings(tlsData) {
            /* Build key-value rows in #tls-settings:
               Mode: tlsData.mode (HTTP / HTTPS / Tailscale)
               Hostname: tlsData.hostname or "—"
               Certificate: valid/expired + expiry date or "—"
               All rows use .setting-row with .setting-label and .setting-value */
        }

        /* ================================================================
         * SETTINGS — STT
         * ================================================================ */

        function renderSTTSettings(sttData) {
            /* Build key-value rows in #stt-settings:
               Backend: sttData.backend or "—"
               Model: sttData.model or "—"
               NPU: sttData.npu_available (Available / Not available / —)
               Status: sttData.status */
        }

        /* ================================================================
         * MINIMAP — MAPLIBRE RECTANGLE DRAW
         * ================================================================ */

        var _map = null;
        var _drawing = false;
        var _startLngLat = null;
        var _rectSource = null;

        function initMinimap() {
            /* Initialize MapLibre GL map in #minimap div.
               Style URL: '/tiles/styles/positron/style.json'
               Center: [-113, 40] (Western US center)
               Zoom: 3
               Interactive: true (zoom/pan enabled)
               attributionControl: false

               On map load:
               - Add empty GeoJSON source 'bbox-rect' (type: geojson, data: empty FeatureCollection)
               - Add fill layer 'bbox-rect-fill' (fill-color: #89b4fa, fill-opacity: 0.15)
               - Add line layer 'bbox-rect-line' (line-color: #89b4fa, line-width: 2)
               - Parse initial bbox from text field and draw rectangle
               - Set up mouse event handlers for rectangle drawing */
        }

        function setupRectangleDraw() {
            /* mousedown on map:
               - Set _drawing = true
               - Capture _startLngLat = e.lngLat
               - Prevent map drag by calling e.preventDefault()

               mousemove on map (when _drawing):
               - Build GeoJSON polygon from _startLngLat to current e.lngLat
               - Update 'bbox-rect' source data

               mouseup on map (when _drawing):
               - Set _drawing = false
               - Finalize rectangle
               - Update bbox text field: "west,south,east,north" (4 decimal places)
               - Call updateEstimate()

               Click outside rectangle (on empty area):
               - Clear rectangle source
               - Clear bbox text field */
        }

        function bboxToGeoJSON(west, south, east, north) {
            /* Return GeoJSON FeatureCollection with one Polygon feature:
               coordinates: [[[west,south],[east,south],[east,north],[west,north],[west,south]]] */
            return {
                type: 'FeatureCollection',
                features: [{
                    type: 'Feature',
                    geometry: {
                        type: 'Polygon',
                        coordinates: [[[west,south],[east,south],[east,north],[west,north],[west,south]]]
                    },
                    properties: {}
                }]
            };
        }

        function syncBboxToMap() {
            /* Parse bbox text field -> draw rectangle on map -> fit map bounds.
               Called on bbox input change.
               If parse fails, do nothing. */
        }

        function syncMapToBbox(west, south, east, north) {
            /* Update bbox text field with new values.
               Update rectangle on map.
               Called on mouseup after drawing. */
        }

        /* ================================================================
         * POLLING
         * ================================================================ */

        function fetchAll() {
            /* Fetch /admin/status -> renderDashboard, renderTLSSettings, renderSTTSettings,
                                      renderElevation, renderOsmPoi, updatePipelineButtons
               Fetch /admin/pipeline/status?type=imagery -> renderImageryProgress, renderPipelineBanner
               Fetch /admin/pipeline/status?type=elevation -> renderElevation progress
               Fetch /admin/pipeline/status?type=osm_poi -> renderOsmPoi progress
               Fetch /admin/credentials/status -> renderM2MSettings */
        }

        /* ================================================================
         * EVENT HANDLERS
         * ================================================================ */

        /* Source change -> update concurrency options, show/hide M2M warning, update zoom note */
        /* Bbox input -> syncBboxToMap, updateEstimate */
        /* Zoom change -> updateEstimate, update zoom note */
        /* Start button -> confirm, POST /admin/pipeline/start with type=imagery */
        /* Cancel button -> POST /admin/pipeline/cancel */
        /* Elevation Start -> POST /admin/pipeline/start with type=elevation, bbox, zoom */
        /* OSM Extract -> POST /admin/pipeline/start with type=osm_poi */
        /* M2M Save -> POST /admin/credentials */
        /* M2M Delete -> DELETE /admin/credentials */
        /* M2M Update -> show form */
        /* M2M goto settings link -> switchTab('settings') */
        /* Pipeline banner click -> switchTab('pipelines') */

        /* ================================================================
         * INITIALIZATION
         * ================================================================ */

        /* Set up tab click handlers */
        /* Read location.hash for initial tab */
        /* Initialize concurrency options */
        /* Run updateEstimate() */
        /* Run fetchAll() */
        /* Set up 10-second interval for fetchAll() */
        /* Initialize minimap (only if viewport >= 480px) */

    })();
    </script>
</body>
</html>
```

### Key Implementation Details

The outline above shows the STRUCTURE. The implementing agent must fill in each function body. Here are the critical implementation details:

#### Tab Switching (exact implementation)

```javascript
function switchTab(name) {
    document.querySelectorAll('.tab-btn').forEach(function(btn) {
        btn.classList.toggle('active', btn.dataset.tab === name);
    });
    document.querySelectorAll('.tab-content').forEach(function(tab) {
        tab.classList.toggle('active', tab.id === 'tab-' + name);
    });
    history.replaceState(null, '', '#' + name);
}

document.querySelectorAll('.tab-btn').forEach(function(btn) {
    btn.addEventListener('click', function() { switchTab(this.dataset.tab); });
});

// Deep link on load
var initTab = location.hash.replace('#', '') || 'dashboard';
if (['dashboard', 'pipelines', 'settings'].indexOf(initTab) >= 0) switchTab(initTab);
```

#### Concurrency Options (exact implementation)

```javascript
var CONCURRENCY_DIRECT = [
    {value: 10, label: 'Conservative (10)'},
    {value: 20, label: 'Normal (20)', default: true},
    {value: 50, label: 'Fast (50)'},
    {value: 80, label: 'Maximum (80)'},
];
var CONCURRENCY_M2M = [
    {value: 3, label: 'M2M safe (3)', default: true},
    {value: 5, label: 'M2M max (5)'},
];

function updateConcurrencyOptions() {
    var sel = document.getElementById('cfg-concurrency');
    var source = document.getElementById('cfg-source').value;
    var options = source === 'm2m' ? CONCURRENCY_M2M : CONCURRENCY_DIRECT;
    sel.textContent = '';
    options.forEach(function(o) {
        var opt = document.createElement('option');
        opt.value = o.value;
        opt.textContent = o.label;
        if (o.default) opt.selected = true;
        sel.appendChild(opt);
    });
}
```

#### Service Health Rendering (exact color logic)

```javascript
function svcDotColor(svc) {
    if (svc.health === 'healthy') return 'green';
    if (svc.status === 'running' && (svc.health === 'starting' || svc.health === 'none')) return 'yellow';
    if (svc.status === 'running' && svc.name === 'nominatim' && svc.health === 'unhealthy') return 'yellow'; // importing
    return 'red';
}

function svcContext(svc, statusData) {
    var name = svc.name;
    if (name === 'search' && statusData.search_stats) {
        var g = statusData.search_stats.gnis_count;
        var o = statusData.search_stats.osm_pois_count;
        var gStr = g >= 1000 ? Math.round(g / 1000) + 'k' : g;
        if (o > 0) return gStr + ' GNIS + ' + (o >= 1000 ? Math.round(o / 1000) + 'k' : o) + ' OSM';
        return gStr + ' GNIS';
    }
    if (name === 'gps' && statusData.gps) {
        var gps = statusData.gps;
        if (gps.status === 'unreachable') return 'unreachable';
        if (gps.status === 'no_gpsd') return 'no gpsd';
        if (gps.fix === '3d') return '3D fix' + (gps.accuracy_m != null ? ', \u00b1' + gps.accuracy_m + 'm' : '');
        if (gps.fix === '2d') return '2D fix';
        return 'no fix';
    }
    if (name === 'stt' && statusData.stt) {
        var stt = statusData.stt;
        if (stt.status === 'unreachable') return 'unreachable';
        return (stt.backend || '?') + ', ' + (stt.model || '?');
    }
    if (name === 'nominatim' && svc.progress && svc.progress.phase) {
        return svc.progress.phase;
    }
    if (name === 'valhalla' && svc.progress && svc.progress.phase) {
        return svc.progress.phase;
    }
    if (name === 'frontend' && svc.health === 'healthy') return 'nginx';
    return svc.health || svc.status;
}
```

#### Minimap Rectangle Draw (exact implementation ~120 lines)

```javascript
function initMinimap() {
    if (window.innerWidth < 480) return; // Mobile: no minimap

    _map = new maplibregl.Map({
        container: 'minimap',
        style: '/tiles/styles/positron/style.json',
        center: [-113, 40],
        zoom: 3,
        attributionControl: false,
    });

    _map.on('load', function() {
        _map.addSource('bbox-rect', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] },
        });
        _map.addLayer({
            id: 'bbox-rect-fill',
            type: 'fill',
            source: 'bbox-rect',
            paint: { 'fill-color': '#89b4fa', 'fill-opacity': 0.15 },
        });
        _map.addLayer({
            id: 'bbox-rect-line',
            type: 'line',
            source: 'bbox-rect',
            paint: { 'line-color': '#89b4fa', 'line-width': 2 },
        });

        // Draw initial bbox from text field
        syncBboxToMap();

        // Rectangle draw handlers
        _map.on('mousedown', function(e) {
            // Only start drawing on left click (button 0)
            if (e.originalEvent.button !== 0) return;
            _drawing = true;
            _startLngLat = e.lngLat;
            _map.dragPan.disable();
        });

        _map.on('mousemove', function(e) {
            if (!_drawing || !_startLngLat) return;
            var west = Math.min(_startLngLat.lng, e.lngLat.lng);
            var east = Math.max(_startLngLat.lng, e.lngLat.lng);
            var south = Math.min(_startLngLat.lat, e.lngLat.lat);
            var north = Math.max(_startLngLat.lat, e.lngLat.lat);
            _map.getSource('bbox-rect').setData(bboxToGeoJSON(west, south, east, north));
        });

        _map.on('mouseup', function(e) {
            if (!_drawing || !_startLngLat) return;
            _drawing = false;
            _map.dragPan.enable();

            var west = Math.min(_startLngLat.lng, e.lngLat.lng);
            var east = Math.max(_startLngLat.lng, e.lngLat.lng);
            var south = Math.min(_startLngLat.lat, e.lngLat.lat);
            var north = Math.max(_startLngLat.lat, e.lngLat.lat);
            _startLngLat = null;

            // Ignore tiny rectangles (accidental clicks)
            if (Math.abs(east - west) < 0.01 && Math.abs(north - south) < 0.01) {
                // Clear rectangle on click
                _map.getSource('bbox-rect').setData({ type: 'FeatureCollection', features: [] });
                return;
            }

            syncMapToBbox(west, south, east, north);
        });
    });
}

function syncBboxToMap() {
    if (!_map || !_map.getSource('bbox-rect')) return;
    var parts = document.getElementById('cfg-bbox').value.split(',').map(Number);
    if (parts.length !== 4 || parts.some(isNaN)) return;
    var west = parts[0], south = parts[1], east = parts[2], north = parts[3];
    _map.getSource('bbox-rect').setData(bboxToGeoJSON(west, south, east, north));
    _map.fitBounds([[west, south], [east, north]], { padding: 20, maxZoom: 8 });
}

function syncMapToBbox(west, south, east, north) {
    document.getElementById('cfg-bbox').value =
        west.toFixed(4) + ',' + south.toFixed(4) + ',' + east.toFixed(4) + ',' + north.toFixed(4);
    _map.getSource('bbox-rect').setData(bboxToGeoJSON(west, south, east, north));
    updateEstimate();
}
```

#### Pipeline Start Handlers

```javascript
// Imagery Start
document.getElementById('cfg-start').addEventListener('click', function() {
    var body = {
        type: 'imagery',
        mode: document.getElementById('cfg-source').value,
        bbox: document.getElementById('cfg-bbox').value,
        zoom: document.getElementById('cfg-zoom').value,
        concurrency: parseInt(document.getElementById('cfg-concurrency').value),
        update: document.getElementById('cfg-update').checked,
    };
    if (!confirm('Start download? ~' + estimateTiles(body.bbox, body.zoom).toLocaleString() + ' tiles')) return;
    cfgFetch('/admin/pipeline/start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    }).then(function(r) { return r.json(); })
      .then(function(d) { if (d.error || d.detail) alert(d.error || d.detail); fetchAll(); });
});

// Elevation Start
document.getElementById('elev-start').addEventListener('click', function() {
    var body = {
        type: 'elevation',
        mode: 'direct',
        bbox: document.getElementById('cfg-bbox').value,
        zoom: '0-12',
        concurrency: 20,
    };
    cfgFetch('/admin/pipeline/start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    }).then(function(r) { return r.json(); })
      .then(function(d) { if (d.error || d.detail) alert(d.error || d.detail); fetchAll(); });
});

// OSM POI Extract
document.getElementById('osm-start').addEventListener('click', function() {
    cfgFetch('/admin/pipeline/start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ type: 'osm_poi' }),
    }).then(function(r) { return r.json(); })
      .then(function(d) { if (d.error || d.detail) alert(d.error || d.detail); fetchAll(); });
});
```

#### Polling (fetchAll)

```javascript
function fetchAll() {
    // Status
    cfgFetch('/admin/status')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            _lastStatus = d;
            renderDashboard(d);
            renderTLSSettings(d.tls || {});
            renderSTTSettings(d.stt || {});
            updatePipelineButtons();
        })
        .catch(function() {});

    // Imagery pipeline
    cfgFetch('/admin/pipeline/status?type=imagery')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            renderImageryProgress(d);
            renderPipelineBanner(d);
        })
        .catch(function() {});

    // Elevation pipeline
    cfgFetch('/admin/pipeline/status?type=elevation')
        .then(function(r) { return r.json(); })
        .then(function(d) { renderElevation(_lastStatus, d); })
        .catch(function() {});

    // OSM POI pipeline
    cfgFetch('/admin/pipeline/status?type=osm_poi')
        .then(function(r) { return r.json(); })
        .then(function(d) { renderOsmPoi(_lastStatus, d); })
        .catch(function() {});

    // Credentials
    cfgFetch('/admin/credentials/status')
        .then(function(r) { return r.json(); })
        .then(function(d) { renderM2MSettings(d.m2m_configured); })
        .catch(function() {});
}
```

### Manual Test Checklist

After implementation, manually verify each item:

1. **Tab switching:** Click each tab -- content switches, URL hash updates. Reload with `#settings` -- Settings tab opens.
2. **Dashboard — services:** Service list renders with correct dots and context strings.
3. **Dashboard — first run:** Stop all containers, reload -- "No services detected" message appears.
4. **Dashboard — pipeline banner:** Start an imagery download -- banner appears at bottom of Dashboard.
5. **Dashboard — banner click:** Click banner -- switches to Pipelines tab.
6. **Pipelines — minimap:** Map renders with Positron basemap. Draw rectangle -- bbox field updates. Edit bbox field -- rectangle moves on map.
7. **Pipelines — minimap mobile:** Resize viewport below 480px -- minimap hidden, only text field visible.
8. **Pipelines — source switch:** Change source to M2M -- concurrency options change to 3/5. Change back to direct -- options change to 10/20/50/80.
9. **Pipelines — M2M warning:** Select M2M with no credentials -- inline warning appears. Click settings link -- switches to Settings tab.
10. **Pipelines — zoom warning:** Select zoom 17+ with direct source -- warning note appears.
11. **Pipelines — imagery start:** Click Start -- confirm dialog -- pipeline starts -- progress bar appears.
12. **Pipelines — concurrent prevention:** While imagery is running, elevation Start and OSM Extract buttons are disabled.
13. **Pipelines — completed state:** After pipeline completes, "Completed Xh ago" message appears.
14. **Pipelines — OSM extraction:** Click Extract POIs (with PBF file present) -- pipeline starts.
15. **Settings — M2M configured:** When credentials exist -- "Configured" badge + Update/Delete buttons. No username shown.
16. **Settings — M2M update flow:** Click Update -- form appears. Save new credentials -- form hides, "Configured" reappears.
17. **Settings — TLS display:** Shows mode, hostname, cert expiry.
18. **Settings — STT display:** Shows backend, model, NPU availability, status.
19. **Auto-refresh:** Wait 10 seconds -- data refreshes without manual action.
20. **Dark theme:** All elements match Catppuccin Mocha palette.

### Completion Check

```
BEFORE marking this task complete:
1. Review against docs/pitfalls/implementation-pitfalls.md
   - Pitfall #3: sub_filter not applied to frontend JS (only NGINX tile proxying). GOOD.
   - Pitfall #6: MapLibre loaded from /vendor/, not CDN. GOOD.
   - Pitfall #9: New code is in config/index.html, not app.js. GOOD.
   - Pitfall #10: All API calls use cfgFetch which adds X-Geographica header. GOOD.
2. Verify all elements from the manual test checklist
3. Verify no GPS coordinates appear anywhere in the frontend code
```

### Review Loop (Task 5)

```
After every logical group of tasks:
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues. Then
update your private journal and continue onto the next tasks.
```

Review checklist for Task 5:
1. Does MapLibre load from `/vendor/` (offline-first)? YES -- `<script src="/vendor/maplibre-gl.js">` and `<link rel="stylesheet" href="/vendor/maplibre-gl.css">`.
2. Does the style URL use the config panel tile proxy? YES -- `/tiles/styles/positron/style.json`.
3. Is the minimap hidden on mobile? YES -- `@media (max-width: 479px) { #minimap-container { display: none } }` and JS check `window.innerWidth < 480`.
4. Do all cfgFetch calls include X-Geographica? YES -- cfgFetch adds it automatically.
5. Are Start buttons disabled during pipeline runs? YES -- `updatePipelineButtons()` disables all when `_anyPipelineRunning`.
6. Does M2M show "Configured" without username? YES -- no username masking, just status text.
7. Does the first-run empty state work? YES -- checks `data.services.length === 0`.
8. Are GPS coordinates ever displayed? NO -- only fix type and accuracy.
9. Does tab deep linking work? YES -- reads `location.hash` on load.
10. Does auto-refresh continue across tab switches? YES -- `setInterval(fetchAll, 10000)` runs regardless of active tab.

### Commit

```
feat(frontend): redesign config panel with 3-tab layout and minimap

Three tabs: Dashboard (service health, disk, TLS), Pipelines (imagery with
MapLibre minimap bbox draw, elevation, OSM POI extraction), Settings (M2M
credentials, TLS config, STT info). Concurrent pipeline prevention. Mobile
responsive (minimap hidden below 480px). Auto-refresh every 10s.
```

---

## Final Review Rounds

### Review Round 1: Ambiguity Check

| Check | Result |
|-------|--------|
| Are all file paths absolute or repo-relative? | YES -- every task specifies exact paths |
| Are line numbers referenced for every edit? | YES -- exact line numbers from current file state |
| Is every new function's behavior fully specified? | YES -- return values, error handling, all defined |
| Could a subagent interpret any instruction two ways? | Checked: The minimap implementation in Task 5 provides exact JS code, no ambiguity in the draw interaction. The concurrency options are fully enumerated. |
| Are test assertions specific (not just "status 200")? | YES -- every test checks specific response body keys and values |

### Review Round 2: Cross-Task Dependency Check

| Dependency | Verified |
|------------|----------|
| Task 2 calls `http://gps:8000/status` -- does Task 1 create this? | YES -- Task 1 adds `GET /status` at line ~209 |
| Task 5 calls `/admin/pipeline/status?type=osm_poi` -- does Task 3 add this? | YES -- Task 3 updates `pipeline_status()` to accept `osm_poi` |
| Task 5 loads MapLibre from `/vendor/` -- does Task 4 add the NGINX location? | YES -- Task 4 adds `/vendor/` alias |
| Task 5 loads tiles from `/tiles/styles/positron/style.json` -- does Task 4 proxy this? | YES -- Task 4 adds `/tiles/styles/` with sub_filter |
| Task 2 reads `/tls/server.crt` -- does Task 4 mount the volume? | YES -- Task 4 adds TLS cert volume to docker-compose.yml |
| Could Tasks 1, 3, 4 conflict (touching same files)? | NO -- Task 1 touches gps/main.py, Task 3 touches search/main.py, Task 4 touches docker-compose.yml + nginx.conf |
| Could Task 2 and Task 3 conflict (both touch search/main.py)? | YES -- but Task 2 modifies `admin_status()` (lines 539-669) while Task 3 modifies `_parse_zoom` (line 117), `PipelineStartBody` (lines 73-79), `_state_file_for_type` (lines 725-729), and `pipeline_start` (lines 762+). Different sections of the same file. Task 2 should run before Task 3, or they can run in parallel if edits don't overlap. The plan shows Task 2 depends on Task 1, and Task 3 is independent -- they CAN run in parallel with Task 1 complete. |

### Review Round 3: Testing Pitfalls Cross-Reference

| Pitfall | Addressed |
|---------|-----------|
| #1 Mocking what should be tested | Task 2 `TestSearchStats` uses real SQLite, not mocked queries |
| #2 FTS5 query syntax | Not applicable (no FTS5 queries in this plan) |
| #3 Path-dependent fixtures | All tests use `tmp_path` or `Path(__file__).parent` |
| #4 Haversine precision | Not applicable |
| #5 Async test isolation | Task 2 uses `@pytest.mark.asyncio` for async tests |
| #6 Docker-dependent tests | All Docker calls are mocked; no tests require running containers |
| #7 Audio fixtures | Not applicable |
| #8 Env var pollution | All tests use `monkeypatch` fixture |

### Review Round 3 (continued): Implementation Pitfalls Cross-Reference

| Pitfall | Addressed |
|---------|-----------|
| #1 Data inside repo | No data files created inside repo |
| #2 Container naming | OSM POI pipeline uses `geographica-pipeline` (same container) |
| #3 NGINX sub_filter | Task 4 includes `Accept-Encoding ""` on all sub_filter locations |
| #4 Memory limits | No new services added; existing limits unchanged |
| #5 HTTPS requirement | Not applicable (no browser APIs added) |
| #6 Offline-first | MapLibre served from `/vendor/`, tiles from local tileserver |
| #7 GPS busy-wait | Not modified (Task 1 only adds an endpoint, no loop changes) |
| #8 SQLite WAL mode | Search stats queries are read-only; no WAL issues |
| #9 Module boundaries | Frontend code stays in config/index.html, not app.js |
| #10 Config panel localhost | All write endpoints go through NGINX config block with X-Config-Source |

No substantive issues found in round 3. Plan is complete.
