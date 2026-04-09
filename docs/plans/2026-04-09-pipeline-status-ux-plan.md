# Pipeline Status UX Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix admin panel to accurately display M2M pipeline progress with phase-aware rendering, filter pipeline containers from the service list, and add a frontend healthcheck.
**Architecture:** Backend-first — script phase reporting, then search service filtering, then frontend rendering, then docker-compose healthcheck. Each task is independently testable.
**Tech Stack:** Python/FastAPI, vanilla JS, Docker Compose
**Spec:** docs/superpowers/specs/2026-04-09-pipeline-status-ux-design.md

---

## Pitfalls Reference

Before working on ANY task, read both pitfalls files:
- `docs/pitfalls/testing-pitfalls.md`
- `docs/pitfalls/implementation-pitfalls.md`

Most relevant pitfalls:
- **Testing #1:** Use real in-memory SQLite for search_stats queries, not mocks.
- **Testing #6:** Docker-dependent tests must be mocked; no real Docker required.
- **Testing #8:** Use `monkeypatch` fixture, not `os.environ` directly.
- **Implementation #2:** Container naming pattern is `geographica-<service>`.
- **Implementation #6:** Offline-first — no CDN dependencies.
- **Implementation #10:** Config panel is localhost-only, requires `X-Config-Source: internal` header.

---

## File Map

### Modified Files

| File | Change |
|------|--------|
| `scripts/acquire_imagery.py` | Phase-aware `update_progress()`, progress callback in `m2m_download_batched()`, phase transitions in `run_m2m()` |
| `services/search/main.py` | `KNOWN_SERVICES` filter in `_list_docker_services()`, M2M branch in `pipeline_start()` validation + command, reconciliation fix in `pipeline_status()`, skip tile estimation for M2M |
| `frontend/config/index.html` | M2M phase rendering in `renderImageryProgress()`, stale state time-ago, zoom disable for M2M, estimate hide for M2M, "Start Download" button, M2M banner, M2M start handler |
| `docker-compose.yml` | Frontend healthcheck |

### New Files

| File | Description |
|------|-------------|
| `services/search/tests/test_pipeline_status_m2m.py` | Tests for M2M pipeline status rendering |
| `tests/test_m2m_progress.py` | Tests for phase-aware `update_progress()` in acquire_imagery.py |

---

## Dependency Graph

```
Task 1 (Script phase reporting)    Task 2 (Service filtering + backend)    Task 4 (Docker healthcheck)
        \                                    |                                /
         \                                   |                               /
          v                                  v                              v
                    Task 3 (Frontend rendering)
```

- Tasks 1, 2, 4 are INDEPENDENT — can run in parallel
- Task 3 depends on Tasks 1 and 2 (needs phase fields in state file + filtered service list)

---

## Task 1: Phase-Aware M2M Progress in acquire_imagery.py

**Files:**
- Modify: `scripts/acquire_imagery.py` (lines 98-114: `update_progress`, lines 743-858: `m2m_download_batched`, lines 861-976: `run_m2m`)
- Create: `tests/test_m2m_progress.py`

**Dependencies:** None (independent)
**Estimated lines changed:** ~80 lines modified in acquire_imagery.py, ~120 lines in test file

### TDD Preamble

```
BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD: write failing test → implement fix → verify green.
```

### Context

The `update_progress()` function at line 98 writes a flat dict with `tiles_done/tiles_total`. For M2M, it needs phase-aware fields. The function is called from `run_m2m()` at multiple phase boundaries, and from `m2m_download_batched()` for per-batch progress.

The key insight: `update_progress()` calls `write_pipeline_state()` (line 74) which **merges** new fields into the existing state file. So we can add new fields incrementally without breaking old ones.

### Step 1: Create test file

Create `tests/test_m2m_progress.py`:

```python
"""Tests for phase-aware M2M progress reporting in acquire_imagery.py."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from acquire_imagery import update_progress, write_pipeline_state


@pytest.fixture
def output_path(tmp_path):
    """Create a fake output path for state file writing."""
    return tmp_path / "imagery.mbtiles"


class TestUpdateProgressM2M:
    """Test update_progress with M2M-specific phase fields."""

    def test_m2m_downloading_phase(self, output_path):
        """M2M downloading phase writes all GeoTIFF progress fields."""
        update_progress._started_at = "2026-04-09T02:45:24+00:00"
        update_progress(
            output_path, mode="m2m", bbox="-113,32,-111,34", zoom="n/a",
            tiles_done=0, tiles_total=0,
            phase="downloading",
            scenes_total=1022,
            geotiffs_downloaded=50, geotiffs_total=1022,
            geotiffs_bytes=14_926_643_200,
            current_batch=2, total_batches=21,
        )

        state_path = output_path.parent / ".pipeline-state.json"
        assert state_path.exists()
        data = json.loads(state_path.read_text())

        assert data["phase"] == "downloading"
        assert data["mode"] == "m2m"
        assert data["scenes_total"] == 1022
        assert data["geotiffs_downloaded"] == 50
        assert data["geotiffs_total"] == 1022
        assert data["geotiffs_bytes"] == 14_926_643_200
        assert data["current_batch"] == 2
        assert data["total_batches"] == 21
        assert data["zoom"] == "n/a"
        assert data["tiles_done"] == 0

    def test_m2m_converting_phase(self, output_path):
        """M2M converting phase writes phase without GeoTIFF fields."""
        update_progress._started_at = "2026-04-09T02:45:24+00:00"
        update_progress(
            output_path, mode="m2m", bbox="-113,32,-111,34", zoom="n/a",
            tiles_done=0, tiles_total=0,
            phase="converting",
            scenes_total=1022,
            geotiffs_downloaded=1022, geotiffs_total=1022,
        )

        data = json.loads((output_path.parent / ".pipeline-state.json").read_text())
        assert data["phase"] == "converting"
        assert data["geotiffs_downloaded"] == 1022

    def test_m2m_complete_phase(self, output_path):
        """M2M complete phase sets status to completed."""
        update_progress._started_at = "2026-04-09T02:45:24+00:00"
        update_progress(
            output_path, mode="m2m", bbox="-113,32,-111,34", zoom="n/a",
            tiles_done=1206388, tiles_total=1206388,
            status="completed", phase="complete",
            scenes_total=1022,
            geotiffs_downloaded=1022, geotiffs_total=1022,
        )

        data = json.loads((output_path.parent / ".pipeline-state.json").read_text())
        assert data["status"] == "completed"
        assert data["phase"] == "complete"
        assert data["tiles_done"] == 1206388

    def test_direct_mode_unchanged(self, output_path):
        """Direct mode callers that don't pass new args still work."""
        update_progress._started_at = "2026-04-09T02:45:24+00:00"
        update_progress(
            output_path, mode="direct", bbox="-124,31,-102,49", zoom="0-14",
            tiles_done=5000, tiles_total=100000, rate=200.5,
        )

        data = json.loads((output_path.parent / ".pipeline-state.json").read_text())
        assert data["mode"] == "direct"
        assert data["tiles_done"] == 5000
        assert data["tiles_total"] == 100000
        # M2M fields should be absent or null
        assert data.get("phase") is None
        assert data.get("scenes_total") is None

    def test_state_file_merges_not_overwrites(self, output_path):
        """Verify write_pipeline_state merges into existing state."""
        # Write initial state (simulating what pipeline_start writes)
        state_path = output_path.parent / ".pipeline-state.json"
        state_path.write_text(json.dumps({
            "status": "running",
            "type": "imagery",
            "container_id": "abc123",
        }))

        # Script writes progress
        update_progress._started_at = "2026-04-09T02:45:24+00:00"
        update_progress(
            output_path, mode="m2m", bbox="-113,32,-111,34", zoom="n/a",
            tiles_done=0, tiles_total=0,
            phase="downloading",
            geotiffs_downloaded=10, geotiffs_total=100,
        )

        data = json.loads(state_path.read_text())
        # Original fields preserved
        assert data["type"] == "imagery"
        assert data["container_id"] == "abc123"
        # New fields added
        assert data["phase"] == "downloading"
        assert data["geotiffs_downloaded"] == 10
```

### Step 2: Run tests, confirm they fail

```bash
cd /home/administrator/Code/geographica && python -m pytest tests/test_m2m_progress.py -v
```

Expected: Tests fail because `update_progress` doesn't accept the new keyword arguments.

### Step 3: Implement phase-aware `update_progress()`

In `scripts/acquire_imagery.py`, replace lines 98-114:

```python
def update_progress(output_path: Path, mode: str, bbox: str, zoom: str,
                    tiles_done: int, tiles_total: int, rate: float = 0,
                    status: str = "running", error: str = None,
                    # M2M phase-aware fields
                    phase: str = None,
                    scenes_total: int = None,
                    geotiffs_downloaded: int = None, geotiffs_total: int = None,
                    geotiffs_bytes: int = None,
                    current_batch: int = None, total_batches: int = None):
    """Write structured progress to the state file.

    For direct mode: tiles_done/tiles_total/rate are the primary fields.
    For M2M mode: phase + geotiffs_downloaded/geotiffs_total are primary during
    the downloading phase; tiles_done/tiles_total during the converting phase.
    """
    import datetime
    state = {
        "status": status,
        "mode": mode,
        "bbox": bbox,
        "zoom": zoom,
        "tiles_done": tiles_done,
        "tiles_total": tiles_total,
        "rate_per_sec": round(rate, 1),
        "started_at": getattr(update_progress, '_started_at', None),
        "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "error": error,
    }
    # M2M-specific fields (only written when provided)
    if phase is not None:
        state["phase"] = phase
    if scenes_total is not None:
        state["scenes_total"] = scenes_total
    if geotiffs_downloaded is not None:
        state["geotiffs_downloaded"] = geotiffs_downloaded
    if geotiffs_total is not None:
        state["geotiffs_total"] = geotiffs_total
    if geotiffs_bytes is not None:
        state["geotiffs_bytes"] = geotiffs_bytes
    if current_batch is not None:
        state["current_batch"] = current_batch
    if total_batches is not None:
        state["total_batches"] = total_batches
    write_pipeline_state(output_path, state)
```

### Step 4: Run tests, confirm they pass

```bash
python -m pytest tests/test_m2m_progress.py -v
```

### Step 5: Add phase transitions to `run_m2m()`

In `scripts/acquire_imagery.py`, modify `run_m2m()` (line 861+) to add phase-aware `update_progress()` calls at each boundary. The key changes:

**After login (line 889-901):** Change the existing call to include `phase="login"`:

Replace:
```python
        update_progress(output, "m2m", args.bbox, "n/a",
                        0, 0, status="running")
```

With:
```python
        update_progress(output, "m2m", args.bbox, "n/a",
                        0, 0, status="running", phase="login")
```

**Before scene search (line 920):** Add searching phase:

After the cancellation check at line 908, before `scenes = await m2m_scene_search(...)`, add:
```python
        update_progress(output, "m2m", args.bbox, "n/a",
                        0, 0, phase="searching")
```

**After scene search, before batch download (line 929-936):** Change to downloading phase with scene count:

Replace:
```python
            update_progress(output, "m2m", args.bbox, "n/a",
                            0, len(scenes), status="running")
```

With:
```python
            total_batches = (len(scenes) + M2M_BATCH_SIZE - 1) // M2M_BATCH_SIZE
            update_progress(output, "m2m", args.bbox, "n/a",
                            0, 0, phase="downloading",
                            scenes_total=len(scenes),
                            geotiffs_downloaded=0, geotiffs_total=len(scenes),
                            geotiffs_bytes=0,
                            current_batch=0, total_batches=total_batches)
```

**Before conversion (line 961-963):** Change to converting phase:

Replace:
```python
    update_progress(output, "m2m", args.bbox, "n/a",
                    len(tif_paths), len(scenes), status="running")
```

With:
```python
    update_progress(output, "m2m", args.bbox, "n/a",
                    0, 0, phase="converting",
                    scenes_total=len(scenes),
                    geotiffs_downloaded=len(tif_paths), geotiffs_total=len(scenes))
```

**After conversion (line 974-975):** Change to complete phase:

Replace:
```python
    update_progress(output, "m2m", args.bbox, "n/a",
                    len(tif_paths), len(scenes), status="completed")
```

With:
```python
    update_progress(output, "m2m", args.bbox, "n/a",
                    0, len(scenes), status="completed", phase="complete",
                    scenes_total=len(scenes),
                    geotiffs_downloaded=len(tif_paths), geotiffs_total=len(scenes))
```

**All error/cancel update_progress calls:** Add `phase="error"` or `phase="cancelled"` respectively. There are 5 such calls in `run_m2m()` — each one should include the phase field matching the status.

### Step 6: Add per-batch progress callback to `m2m_download_batched()`

In `scripts/acquire_imagery.py`, modify `m2m_download_batched()` (line 743) to accept and call a progress callback:

Change the function signature from:
```python
async def m2m_download_batched(
    session: aiohttp.ClientSession, api_key: str,
    dataset_alias: str, scenes: list[dict],
    staging: Path, checkpoint_path: Path,
    concurrency: int = 3,
) -> list[Path]:
```

To:
```python
async def m2m_download_batched(
    session: aiohttp.ClientSession, api_key: str,
    dataset_alias: str, scenes: list[dict],
    staging: Path, checkpoint_path: Path,
    concurrency: int = 3,
    on_batch_complete=None,
) -> list[Path]:
```

After the batch download completes (after line 852: `log.info("Batch %d complete: ...")`), call the callback:

```python
        total_downloaded = len(done)
        log.info("Batch %d complete: %d files this batch, %d total downloaded",
                 batch_num, len(batch_paths), total_downloaded)

        # Report progress to state file via callback
        if on_batch_complete:
            # Calculate total bytes from all downloaded files
            total_bytes = sum(
                Path(p).stat().st_size for p in done.values() if Path(p).exists()
            )
            on_batch_complete(
                geotiffs_downloaded=total_downloaded,
                geotiffs_total=total_scenes,
                geotiffs_bytes=total_bytes,
                current_batch=batch_num,
                total_batches=total_batches,
            )
```

In `run_m2m()`, when calling `m2m_download_batched` (line 940), add the callback:

```python
            def _on_batch(geotiffs_downloaded, geotiffs_total, geotiffs_bytes,
                          current_batch, total_batches):
                update_progress(output, "m2m", args.bbox, "n/a",
                                0, 0, phase="downloading",
                                scenes_total=len(scenes),
                                geotiffs_downloaded=geotiffs_downloaded,
                                geotiffs_total=geotiffs_total,
                                geotiffs_bytes=geotiffs_bytes,
                                current_batch=current_batch,
                                total_batches=total_batches)

            tif_paths = await m2m_download_batched(
                session, api_key, dataset_alias, scenes,
                staging, checkpoint, concurrency=m2m_concurrency,
                on_batch_complete=_on_batch,
            )
```

### Step 7: Run all tests

```bash
python -m pytest tests/test_m2m_progress.py tests/test_m2m_api.py -v
```

Verify the existing M2M API tests still pass (they test scene search/download/cancel logic).

### Completion Check

```
BEFORE marking this task complete:
1. Review your tests against docs/pitfalls/testing-pitfalls.md
2. Verify test coverage:
   - M2M downloading phase fields: tested
   - M2M converting phase fields: tested
   - M2M complete phase: tested
   - Direct mode backward compatibility: tested
   - State file merge behavior: tested
3. Run tests and confirm green
```

### Commit

```
feat(scripts): phase-aware M2M progress reporting in acquire_imagery.py

update_progress() gains optional kwargs for M2M phases: phase, scenes_total,
geotiffs_downloaded/total/bytes, current_batch/total_batches.
m2m_download_batched() gains on_batch_complete callback for per-batch progress.
run_m2m() reports phase transitions: login → searching → downloading → converting → complete.
Direct mode callers are unchanged (new args default to None).
```

---

## Task 2: Service List Filtering + M2M Backend Support

**Files:**
- Modify: `services/search/main.py` (lines 656-670: `_list_docker_services`, lines 927-1035: `pipeline_start`, lines 1174-1185: `pipeline_status`)
- Modify: `services/search/tests/test_admin_status.py` (add service filtering test)
- Create: `services/search/tests/test_pipeline_status_m2m.py`

**Dependencies:** None (independent of Task 1)
**Estimated lines changed:** ~60 lines in main.py, ~120 lines in test files

### TDD Preamble

```
BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD: write failing test → implement fix → verify green.
```

### Context

Three changes in the search service:
1. Filter `_list_docker_services()` to 7 known services (exclude pipeline containers)
2. Add M2M branch to `pipeline_start()` validation and command construction
3. Fix `pipeline_status()` to skip tile estimation for M2M and detect completed-but-exited

### Step 1: Create test file for M2M pipeline status

Create `services/search/tests/test_pipeline_status_m2m.py`:

```python
"""Tests for M2M pipeline status handling.

Tests that pipeline_status correctly handles M2M state files (null zoom,
phase fields), and that pipeline_start accepts M2M without zoom.
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
    mock_client.images.get.return_value = MagicMock()
    mock_client.close = MagicMock()
    mock_client.networks.list.return_value = [MagicMock(name="geographica_default")]
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


class TestM2MPipelineStatus:
    """Test pipeline_status with M2M state files."""

    def test_m2m_state_no_500(self, client):
        """M2M state with null zoom should NOT crash with 500."""
        c, main, tmp_path, _ = client
        state_file = tmp_path / ".pipeline-state.json"
        state_file.write_text(json.dumps({
            "status": "running",
            "type": "imagery",
            "mode": "m2m",
            "phase": "downloading",
            "bbox": "-113,32,-111,34",
            "zoom": "n/a",
            "geotiffs_downloaded": 50,
            "geotiffs_total": 1022,
            "container_id": "abc123",
        }))

        resp = c.get("/admin/pipeline/status?type=imagery")
        assert resp.status_code == 200
        data = resp.json()
        assert data["phase"] == "downloading"
        # estimated_tiles should NOT be computed for M2M
        assert "estimated_tiles" not in data or data.get("estimated_tiles") is None

    def test_m2m_state_zoom_na_no_tile_estimate(self, client):
        """zoom='n/a' should not trigger tile estimation."""
        c, main, tmp_path, _ = client
        state_file = tmp_path / ".pipeline-state.json"
        state_file.write_text(json.dumps({
            "status": "completed",
            "type": "imagery",
            "mode": "m2m",
            "phase": "complete",
            "bbox": "-113,32,-111,34",
            "zoom": "n/a",
        }))

        resp = c.get("/admin/pipeline/status?type=imagery")
        assert resp.status_code == 200

    def test_completed_but_exited_detected(self, client):
        """Container exited but logs show success → status is completed, not interrupted."""
        c, main, tmp_path, mock_docker = client
        state_file = tmp_path / ".pipeline-state.json"
        state_file.write_text(json.dumps({
            "status": "running",
            "type": "imagery",
            "mode": "m2m",
            "bbox": "-113,32,-111,34",
            "zoom": "n/a",
            "container_id": "abc123",
            "last_logs": "MBTiles written to /data/imagery.mbtiles\n",
        }))

        # Container is dead
        mock_docker.containers.get.side_effect = Exception("not found")

        resp = c.get("/admin/pipeline/status?type=imagery")
        data = resp.json()
        assert data["status"] == "completed"


class TestM2MPipelineStart:
    """Test pipeline_start with M2M mode (no zoom required)."""

    def test_m2m_start_no_zoom(self, client):
        """M2M imagery start should succeed without zoom field."""
        c, main, tmp_path, mock_docker = client

        # Write fake credentials
        creds_path = tmp_path / ".credentials.json"
        creds_path.write_text(json.dumps({
            "m2m_username": "test_user",
            "m2m_token": "test_token",
        }))
        main.CREDENTIALS_PATH = creds_path

        resp = c.post(
            "/admin/pipeline/start",
            json={"type": "imagery", "mode": "m2m", "bbox": "-113,32,-111,34", "concurrency": 3},
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"

    def test_m2m_start_requires_bbox(self, client):
        """M2M imagery start still requires bbox."""
        c, main, tmp_path, _ = client

        resp = c.post(
            "/admin/pipeline/start",
            json={"type": "imagery", "mode": "m2m", "concurrency": 3},
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
        assert resp.status_code == 422
        assert "bbox" in resp.json()["detail"].lower()

    def test_direct_start_still_requires_zoom(self, client):
        """Direct imagery start still requires zoom (regression check)."""
        c, main, tmp_path, _ = client

        resp = c.post(
            "/admin/pipeline/start",
            json={"type": "imagery", "mode": "direct", "bbox": "-113,32,-111,34"},
            headers={"X-Config-Source": "internal", "X-Geographica": "1"},
        )
        assert resp.status_code == 422
        assert "zoom" in resp.json()["detail"].lower()


class TestServiceFiltering:
    """Test that pipeline containers are filtered from service list."""

    def test_pipeline_containers_filtered(self, client):
        """Pipeline and pipeline-run-* containers should not appear in services."""
        c, main, tmp_path, mock_docker = client

        # Mock containers including pipeline ones
        def make_container(name, status="running", health="healthy"):
            c = MagicMock()
            c.name = f"geographica-{name}"
            c.status = status
            c.attrs = {"State": {"Health": {"Status": health}, "StartedAt": ""}}
            c.logs.return_value = b""
            return c

        mock_docker.containers.list.return_value = [
            make_container("frontend"),
            make_container("search"),
            make_container("pipeline", status="exited", health="none"),
            make_container("pipeline-run-60ff1b2c4a0c", health="none"),
        ]

        resp = c.get("/admin/status")
        data = resp.json()

        service_names = [s["name"] for s in data["services"]]
        assert "frontend" in service_names
        assert "search" in service_names
        assert "pipeline" not in service_names
        assert "pipeline-run-60ff1b2c4a0c" not in service_names
```

### Step 2: Run tests, confirm they fail

```bash
cd services/search && python -m pytest tests/test_pipeline_status_m2m.py -v
```

### Step 3: Implement service list filtering

In `services/search/main.py`, add a constant after `DATA_DIR` (line 30):

```python
KNOWN_SERVICES = frozenset({
    "frontend", "gps", "nominatim", "search", "stt", "tileserver", "valhalla"
})
```

In `_list_docker_services()` (line 664), after `svc_name = c.name.replace("geographica-", "")`, add a filter:

```python
        for c in sorted(containers, key=lambda x: x.name):
            svc_name = c.name.replace("geographica-", "")
            if svc_name not in KNOWN_SERVICES:
                continue
            svc = {
                "name": svc_name,
```

Also change the existing `"name": c.name.replace("geographica-", "")` to use the already-computed `svc_name`.

### Step 4: Implement M2M branch in `pipeline_start()` validation

In `services/search/main.py`, replace the validation block at lines 931-951:

```python
    # For imagery/elevation, validate required fields
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
```

With:

```python
    # Validate required fields based on type and mode
    bbox = None
    zoom_min = zoom_max = tile_count = 0
    estimated_size_gb = 0.0
    is_m2m = body.type == "imagery" and body.mode == "m2m"

    if body.type in ("imagery", "elevation"):
        if not body.mode or body.mode not in ("direct", "m2m"):
            raise HTTPException(status_code=422, detail="mode must be 'direct' or 'm2m'")
        if not body.bbox:
            raise HTTPException(status_code=422, detail="bbox is required for imagery/elevation")
        if not is_m2m and not body.zoom:
            raise HTTPException(status_code=422, detail="zoom is required for imagery/elevation (direct mode)")
```

### Step 5: Implement M2M command construction in `pipeline_start()`

In the command building block (lines 1014-1035), add an M2M branch. Replace the `else:` block:

```python
            else:
                # Handle existing mbtiles if not updating
                mbtiles_path = _mbtiles_path_for_type(body.type)
                if not body.update and mbtiles_path.exists():
                    ...

                if is_m2m:
                    # M2M command: no --zoom, add --staging
                    mbtiles_path = _mbtiles_path_for_type(body.type)
                    command = [
                        "python3", "/scripts/acquire_imagery.py",
                        "--mode", "m2m",
                        f"--bbox={body.bbox}",
                        "--output", f"/data/{mbtiles_path.name}",
                        "--staging", "/data/m2m_staging",
                        "--concurrency", str(body.concurrency),
                    ]
                else:
                    # Direct/elevation command (existing logic)
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

Update the state file writing to include M2M phase:

```python
            state_data = {
                "status": "running",
                "type": body.type,
                "mode": body.mode,
                "phase": "login" if is_m2m else None,
                "bbox": body.bbox,
                "zoom": body.zoom if not is_m2m else "n/a",
                "concurrency": body.concurrency,
                "update": body.update,
                "estimated_tiles": tile_count if body.type != "osm_poi" and not is_m2m else None,
                "container_id": container.id,
                "started_at": datetime.now(tz.utc).isoformat(),
            }
```

### Step 6: Fix `pipeline_status()` for M2M

In `pipeline_status()`, update the tile estimation check (line 1175):

Replace:
```python
    if state_data.get("bbox") and state_data.get("zoom"):
```

With:
```python
    if (state_data.get("bbox") and state_data.get("zoom")
            and state_data.get("zoom") != "n/a"):
```

Add reconciliation fix for completed-but-exited (in the reconciliation block, around line 1145):

Replace:
```python
        new_status = "cancelled" if state_data.get("status") == "cancelling" else "interrupted"
```

With:
```python
        if state_data.get("status") == "cancelling":
            new_status = "cancelled"
        elif "MBTiles written to" in (state_data.get("last_logs") or ""):
            new_status = "completed"
        else:
            new_status = "interrupted"
```

### Step 7: Run all tests

```bash
cd services/search && python -m pytest tests/ -v
```

### Completion Check

```
BEFORE marking this task complete:
1. Review tests against docs/pitfalls/testing-pitfalls.md
   - Pitfall #6: All Docker calls mocked. GOOD.
   - Pitfall #8: monkeypatch used for env vars. GOOD.
2. Verify test coverage:
   - M2M state no 500: tested
   - M2M zoom=n/a no tile estimate: tested
   - Completed-but-exited detection: tested
   - M2M start without zoom: tested
   - M2M start requires bbox: tested
   - Direct mode still requires zoom (regression): tested
   - Pipeline containers filtered from service list: tested
3. Run tests and confirm green
```

### Review Loop (Tasks 1 + 2)

```
After every logical group of tasks:
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues.
```

### Commit

```
feat(search): filter service list, M2M pipeline_start + pipeline_status fixes

- KNOWN_SERVICES whitelist filters pipeline containers from /admin/status
- pipeline_start accepts M2M imagery without zoom, builds correct command
  (--staging, no --zoom, --mode m2m)
- pipeline_status skips tile estimation for zoom="n/a"
- Reconciliation detects "MBTiles written" in logs as completed (not interrupted)
```

---

## Task 3: Frontend M2M Rendering

**Files:**
- Modify: `frontend/config/index.html` (~150 lines changed across multiple functions)

**Dependencies:** Tasks 1 and 2 (needs phase fields in state file + filtered service list)
**No automated tests** (manual testing; Playwright deferred)

### TDD Preamble

```
BEFORE starting work:
1. Read docs/pitfalls/implementation-pitfalls.md
   - Pitfall #6: Offline-first — MapLibre from /vendor/, no CDN
   - Pitfall #10: Config panel is localhost-only
2. This is a frontend-only task. No automated unit tests.
```

### Context

The frontend needs 6 changes:
1. `renderImageryProgress()` — branch on `data.mode` for M2M phase rendering
2. Source change handler — disable zoom selector and hide estimate for M2M
3. Imagery start handler — omit zoom for M2M, change confirmation text
4. `renderPipelineBanner()` — M2M-aware banner text and progress
5. Stale state rendering — time-ago badges, always "Start Download" button
6. Add `timeAgo()` utility function

### Step 1: Add `timeAgo()` utility function

In the UTILITY FUNCTIONS section (after `cfgFetch`), add:

```javascript
function timeAgo(isoString) {
    if (!isoString) return '';
    var then = new Date(isoString);
    var now = new Date();
    var diffMs = now - then;
    var diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return 'just now';
    if (diffMin < 60) return diffMin + 'm ago';
    var diffH = Math.floor(diffMin / 60);
    if (diffH < 24) return diffH + 'h ago';
    var diffD = Math.floor(diffH / 24);
    return diffD + 'd ago';
}
```

### Step 2: Rewrite `renderImageryProgress()` for M2M phase rendering

Replace the entire `renderImageryProgress()` function (lines 487-526) with:

```javascript
function renderImageryProgress(d) {
    var startBtn = document.getElementById('cfg-start');
    var cancelBtn = document.getElementById('cfg-cancel');
    var progressDiv = document.getElementById('cfg-progress');
    var progressFill = document.getElementById('cfg-progress-fill');
    var progressDetail = document.getElementById('cfg-progress-detail');
    var completedEl = document.getElementById('cfg-imagery-completed');

    if (d.status === 'running') {
        _imageryRunning = true;
        startBtn.style.display = 'none';
        cancelBtn.style.display = '';
        completedEl.style.display = 'none';

        if (d.mode === 'm2m') {
            // M2M phase-aware rendering
            progressDiv.style.display = '';
            var phase = d.phase || 'downloading';
            if (phase === 'login' || phase === 'searching') {
                progressFill.style.width = '0%';
                progressDetail.textContent = phase === 'login'
                    ? 'Logging in to USGS M2M API...'
                    : 'Searching for NAIP scenes...';
            } else if (phase === 'downloading') {
                var dl = d.geotiffs_downloaded || 0;
                var total = d.geotiffs_total || 1;
                var pct = total > 0 ? Math.min(100, dl / total * 100) : 0;
                progressFill.style.width = pct.toFixed(1) + '%';
                var bytes = d.geotiffs_bytes ? (d.geotiffs_bytes / 1e9).toFixed(1) + ' GB' : '';
                var batch = d.current_batch && d.total_batches
                    ? ' (batch ' + d.current_batch + '/' + d.total_batches + ')'
                    : '';
                progressDetail.textContent = 'Downloading GeoTIFFs: ' +
                    dl.toLocaleString() + '/' + total.toLocaleString() +
                    batch + (bytes ? ' \u2014 ' + bytes : '');
            } else if (phase === 'converting') {
                progressFill.style.width = '100%';
                progressFill.style.opacity = '0.6';
                progressDetail.textContent = 'Converting GeoTIFFs to tiles...';
            }
        } else {
            // Direct mode — existing tile progress
            progressDiv.style.display = '';
            progressFill.style.opacity = '1';
            var total = d.estimated_tiles || d.tiles_total || 1;
            var done = d.tiles_done || 0;
            var pct = Math.min(100, (done / total * 100)).toFixed(1);
            progressFill.style.width = pct + '%';
            var rate = d.rate_per_sec ? ' \u00b7 ' + Math.round(d.rate_per_sec) + ' tiles/sec' : '';
            progressDetail.textContent = done.toLocaleString() + ' / ' + total.toLocaleString() + ' (' + pct + '%)' + rate;
        }
    } else {
        _imageryRunning = false;
        cancelBtn.style.display = 'none';
        startBtn.style.display = '';
        progressFill.style.opacity = '1';

        // Terminal state rendering with time-ago
        var ago = timeAgo(d.completed_at);

        if (d.status === 'completed') {
            startBtn.textContent = 'Start Download';
            progressDiv.style.display = 'none';
            completedEl.style.display = '';
            completedEl.className = 'status status-ok';
            var tileInfo = d.tiles_done ? ' \u2014 ' + d.tiles_done.toLocaleString() + ' tiles' : '';
            completedEl.textContent = 'Completed' + (ago ? ' ' + ago : '') + tileInfo;
        } else if (d.status === 'interrupted') {
            startBtn.textContent = 'Start Download';
            progressDiv.style.display = 'none';
            completedEl.style.display = '';
            completedEl.className = 'status status-warn';
            completedEl.textContent = 'Interrupted' + (ago ? ' ' + ago : '');
        } else if (d.status === 'cancelled') {
            startBtn.textContent = 'Start Download';
            progressDiv.style.display = 'none';
            completedEl.style.display = '';
            completedEl.className = 'status status-warn';
            completedEl.textContent = 'Cancelled' + (ago ? ' ' + ago : '');
        } else if (d.status === 'error') {
            startBtn.textContent = 'Start Download';
            progressDiv.style.display = 'none';
            completedEl.style.display = '';
            completedEl.className = 'status status-error';
            completedEl.textContent = 'Failed' + (ago ? ' ' + ago : '') + (d.error ? ' \u2014 ' + d.error : '');
        } else {
            startBtn.textContent = 'Start Download';
            progressDiv.style.display = 'none';
            completedEl.style.display = 'none';
        }
    }
}
```

### Step 3: Modify source change handler for zoom disable + estimate hide

Replace the source change handler (line 839-843):

```javascript
document.getElementById('cfg-source').addEventListener('change', function() {
    var isM2M = this.value === 'm2m';
    var zoomEl = document.getElementById('cfg-zoom');
    var estimateEl = document.getElementById('cfg-estimate');

    // Disable zoom selector for M2M
    zoomEl.disabled = isM2M;

    // Update estimate or hide for M2M
    if (isM2M) {
        estimateEl.textContent = 'M2M: download size depends on source imagery coverage';
        estimateEl.style.color = '#7a8299';
    } else {
        estimateEl.style.color = '';
        updateEstimate();
    }

    updateConcurrencyOptions();
    updateM2MWarning();
    document.getElementById('cfg-zoom').dispatchEvent(new Event('change'));
});
```

### Step 4: Modify zoom change handler for M2M note

Replace the zoom change handler (lines 850-865):

```javascript
document.getElementById('cfg-zoom').addEventListener('change', function() {
    var source = document.getElementById('cfg-source').value;
    var note = document.getElementById('cfg-zoom-note');

    if (source === 'm2m') {
        note.textContent = 'M2M mode auto-detects zoom from source imagery (~z17-z19 for NAIP)';
        note.style.color = '#7a8299';
        // Don't update estimate for M2M
        return;
    }

    updateEstimate();
    var zoom = this.value;
    var maxZ = parseInt(zoom.split('-')[1]);
    if (maxZ > 16) {
        note.textContent = 'Zoom levels above 16 require M2M mode (NAIP GeoTIFF source).';
        note.style.color = '#f9e2af';
    } else {
        note.textContent = '';
    }
});
```

### Step 5: Modify imagery start handler for M2M

Replace the imagery start handler (lines 878-894):

```javascript
document.getElementById('cfg-start').addEventListener('click', function() {
    var source = document.getElementById('cfg-source').value;
    var isM2M = source === 'm2m';
    var body = {
        type: 'imagery',
        mode: source,
        bbox: document.getElementById('cfg-bbox').value,
        concurrency: parseInt(document.getElementById('cfg-concurrency').value),
        update: document.getElementById('cfg-update').checked
    };
    // Only include zoom for direct mode
    if (!isM2M) {
        body.zoom = document.getElementById('cfg-zoom').value;
    }

    var confirmMsg = isM2M
        ? 'Start M2M download for ' + body.bbox + '?'
        : 'Start download? ~' + estimateTiles(body.bbox, document.getElementById('cfg-zoom').value).toLocaleString() + ' tiles';
    if (!confirm(confirmMsg)) return;

    cfgFetch('/admin/pipeline/start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
    }).then(function(r) { return r.json(); })
      .then(function(d) { if (d.error || d.detail) alert(d.error || d.detail); fetchAll(); });
});
```

### Step 6: Update `renderPipelineBanner()` for M2M awareness

The banner function was already updated to accept `(imageryData, elevData, osmData)`. Modify the imagery branch to handle M2M phases:

Replace the `if (imageryData && imageryData.status === 'running')` block:

```javascript
if (imageryData && imageryData.status === 'running') {
    if (imageryData.mode === 'm2m') {
        var phase = imageryData.phase || 'downloading';
        if (phase === 'login' || phase === 'searching') {
            title = 'M2M imagery: Initializing...';
        } else if (phase === 'downloading') {
            var dl = imageryData.geotiffs_downloaded || 0;
            var gt = imageryData.geotiffs_total || 0;
            var batch = imageryData.current_batch && imageryData.total_batches
                ? ' (batch ' + imageryData.current_batch + '/' + imageryData.total_batches + ')'
                : '';
            title = 'M2M imagery: ' + dl + '/' + gt + ' GeoTIFFs' + batch;
            pct = gt > 0 ? Math.min(100, dl / gt * 100) : 0;
        } else if (phase === 'converting') {
            title = 'M2M imagery: Converting to tiles...';
            pct = 100;
        }
    } else {
        title = 'Imagery download in progress';
        var total = imageryData.estimated_tiles || imageryData.tiles_total || 1;
        var done = imageryData.tiles_done || 0;
        pct = Math.min(100, done / total * 100);
        var rate = imageryData.rate_per_sec ? Math.round(imageryData.rate_per_sec) + ' tiles/sec' : '';
        detail = done.toLocaleString() + ' / ' + total.toLocaleString() + (rate ? ' \u00b7 ' + rate : '');
    }
}
```

### Manual Test Checklist

1. **Service list:** Open admin panel → Dashboard shows only 7 services, no pipeline containers.
2. **Frontend green:** Frontend service shows green dot (after healthcheck passes, ~30s).
3. **M2M source select:** Switch to M2M → zoom disabled, estimate text changes to "M2M: download size depends...", zoom note shows auto-detect message.
4. **Direct source select:** Switch back to direct → zoom re-enabled, estimate recalculates.
5. **M2M start:** Click Start Download with M2M → confirm dialog says "Start M2M download for [bbox]?" → POST sends no zoom field.
6. **Stale state:** Existing completed/interrupted states show time-ago badge with "Start Download" button (not "Resume").
7. **M2M progress rendering:** (Requires running M2M download — test with mock state file if needed.) Phase transitions: login → searching → downloading (progress bar with GeoTIFF counts) → converting (indeterminate) → complete.
8. **Dashboard banner M2M:** During M2M download, banner shows "M2M imagery: X/Y GeoTIFFs (batch N/M)".

### Completion Check

```
BEFORE marking this task complete:
1. Review against docs/pitfalls/implementation-pitfalls.md
   - Pitfall #6: No CDN calls. GOOD.
   - Pitfall #10: All API calls use cfgFetch (X-Geographica header). GOOD.
2. Verify all manual test checklist items
3. No GPS coordinates anywhere in the frontend
4. No innerHTML with user data
```

### Commit

```
feat(frontend): M2M phase-aware progress rendering, zoom disable, stale state time-ago

- renderImageryProgress branches on mode=m2m for phase rendering
  (login → searching → downloading with GeoTIFF progress → converting → complete)
- Source=M2M disables zoom selector, hides tile estimate
- Start handler omits zoom for M2M, changes confirm dialog
- Pipeline banner shows M2M-specific text and progress
- Terminal states show time-ago badges, button always says "Start Download"
- timeAgo() utility for human-readable timestamps
```

---

## Task 4: Frontend Docker Healthcheck

**Files:**
- Modify: `docker-compose.yml` (frontend service, after line 187)

**Dependencies:** None (independent)
**No tests** (verified by `docker compose ps` after deploy)

### Step 1: Add healthcheck to frontend service

In `docker-compose.yml`, in the `frontend` service definition, after the `deploy:` block (after line 187), add:

```yaml
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8094/config/", "-o", "/dev/null"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

This goes at the same indentation level as `deploy:`, `volumes:`, `ports:`, etc. (4 spaces).

### Step 2: Verify

After deploying with `docker compose up -d --force-recreate frontend`, wait 30-40 seconds and run:

```bash
docker compose ps frontend
```

Expected: Shows `(healthy)` in the status column.

### Commit

```
chore: add healthcheck to frontend container (curl to config panel)

Frontend was the only service without a Docker healthcheck, causing
the admin panel to show it as yellow/none. Now checks NGINX is serving
the config panel every 30s.
```

---

## Review Loop (Tasks 3 + 4)

```
After every logical group of tasks:
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues.
```

Review checklist:
1. Does M2M command construction omit `--zoom`? YES.
2. Does M2M command include `--staging /data/m2m_staging`? YES.
3. Does the frontend send zoom for direct mode but not M2M? YES.
4. Does `renderImageryProgress` handle all 5 M2M phases? YES (login, searching, downloading, converting, complete).
5. Does the banner show M2M-specific text? YES.
6. Does the zoom selector disable for M2M and re-enable for direct? YES.
7. Does the estimate hide for M2M? YES.
8. Is the button always "Start Download"? YES.
9. Does the healthcheck use the correct port (8094)? YES.
10. Are pipeline containers filtered from the service list? YES.
