"""Tests for the pipeline-completion → TileServer restart handoff.

Fix for 2026-04-17 Bug 1 ("TileServer Never Restarted After Pipeline Completion").
The pipeline scripts write status="completed" to the state file before the
container exits. The old reconciliation guard only fired on crashes
(status in ("running", "cancelling")), which meant clean completions never
triggered the WAL checkpoint / TileServer restart. The map could not show
new tiles until the user manually reloaded services.

Fix: treat a (completed | completed_partial) state whose container has
exited and which has not yet been marked `tileserver_restarted_at` as a
pending handoff. Perform the handoff once and stamp the state file so
subsequent polls are no-ops.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def mock_docker_with_tileserver():
    """Docker client with a running tileserver and no running pipeline."""
    mock_client = MagicMock()

    # No pipeline container running
    def _list(all=False, filters=None):
        name_filter = (filters or {}).get("name", "")
        if "geographica-tileserver" in name_filter:
            ts = MagicMock()
            ts.status = "running"
            ts.restart = MagicMock()
            return [ts]
        return []  # no geographica-pipeline containers

    mock_client.containers.list.side_effect = _list
    mock_client.containers.get.side_effect = Exception("not found")
    mock_client.images.get.return_value = MagicMock()
    mock_client.close = MagicMock()
    mock_client.networks.list.return_value = []

    return mock_client


@pytest.fixture
def client(mock_docker_with_tileserver, tmp_path, monkeypatch):
    """TestClient with mocked Docker + tmp DATA_DIR."""
    if "main" in sys.modules:
        del sys.modules["main"]

    monkeypatch.setenv("POI_DB_PATH", str(tmp_path / "poi.sqlite"))
    monkeypatch.setenv("NOMINATIM_URL", "http://localhost:9999")
    monkeypatch.setenv("DATA_HOST_PATH", "/srv/geographica/data")
    monkeypatch.setenv("SCRIPTS_HOST_PATH", "/home/administrator/Code/geographica/scripts")

    import main

    main._get_docker_client = MagicMock(return_value=mock_docker_with_tileserver)
    main.DATA_DIR = tmp_path

    with TestClient(main.app) as c:
        yield c, main, tmp_path, mock_docker_with_tileserver


def _tileserver_restart_calls(mock_docker) -> int:
    """Count how many times any tileserver container .restart() was called."""
    total = 0
    for call in mock_docker.containers.list.call_args_list:
        filters = (call.kwargs.get("filters") or {}) if call.kwargs else (call[1].get("filters", {}) if len(call) > 1 else {})
        if "geographica-tileserver" not in filters.get("name", ""):
            continue
        ret = mock_docker.containers.list.side_effect(**call.kwargs) if call.kwargs else []
        for ts in ret:
            total += ts.restart.call_count
    return total


class TestCleanCompletionTriggersRestart:
    """Pipeline script wrote status='completed' cleanly → admin poll should restart TileServer."""

    def test_completed_state_with_dead_container_restarts_tileserver(self, client):
        c, main, tmp_path, mock_docker = client

        # Simulate a real, finished NOAA run — pipeline wrote "completed" itself
        # and exited before the admin was polled.
        state_file = tmp_path / ".pipeline-state.json"
        state_file.write_text(json.dumps({
            "status": "completed",
            "type": "imagery",
            "mode": "noaa",
            "source": "noaa",
            "bbox": "-113.4,32.7,-110.4,34.2",
            "zoom": "n/a",
            "items_done": 1200,
            "items_total": 1200,
            "started_at": "2026-04-18T06:19:14+00:00",
            "last_updated": "2026-04-19T02:58:40+00:00",
        }))

        resp = c.get("/admin/pipeline/status?type=imagery")
        assert resp.status_code == 200

        # The handoff should have restarted TileServer.
        ts_restart_calls = [
            call for call in mock_docker.containers.list.call_args_list
            if "geographica-tileserver" in (call.kwargs.get("filters", {}) or {}).get("name", "")
        ]
        assert ts_restart_calls, "TileServer list was never queried — restart block was skipped"

    def test_completed_state_stamps_tileserver_restarted_at(self, client):
        c, main, tmp_path, mock_docker = client

        state_file = tmp_path / ".pipeline-state.json"
        state_file.write_text(json.dumps({
            "status": "completed",
            "type": "imagery",
            "mode": "noaa",
            "source": "noaa",
            "bbox": "-113.4,32.7,-110.4,34.2",
        }))

        c.get("/admin/pipeline/status?type=imagery")

        # State file must now carry the idempotency stamp.
        updated = json.loads(state_file.read_text())
        assert "tileserver_restarted_at" in updated, (
            "state file should record tileserver_restarted_at after a successful handoff"
        )
        # Still terminal.
        assert updated["status"] == "completed"


class TestHandoffIsIdempotent:
    """Second poll after a successful handoff must NOT restart TileServer again."""

    def test_already_stamped_state_does_not_restart_again(self, client):
        c, main, tmp_path, mock_docker = client

        state_file = tmp_path / ".pipeline-state.json"
        state_file.write_text(json.dumps({
            "status": "completed",
            "type": "imagery",
            "mode": "noaa",
            "source": "noaa",
            "tileserver_restarted_at": "2026-04-19T03:00:00+00:00",
        }))

        resp = c.get("/admin/pipeline/status?type=imagery")
        assert resp.status_code == 200

        # No tileserver-filtered list call means the restart block didn't enter.
        ts_queries = [
            call for call in mock_docker.containers.list.call_args_list
            if "geographica-tileserver" in (call.kwargs.get("filters", {}) or {}).get("name", "")
        ]
        assert ts_queries == [], (
            "Second poll must be a no-op — the tileserver-restart block should not re-enter"
        )


class TestCompletedPartialAlsoTriggersRestart:
    """completed_partial (NOAA D2: some tiles succeeded, some failed) should also restart TileServer."""

    def test_completed_partial_restarts_tileserver(self, client):
        c, main, tmp_path, mock_docker = client

        state_file = tmp_path / ".pipeline-state.json"
        state_file.write_text(json.dumps({
            "status": "completed_partial",
            "type": "imagery",
            "mode": "noaa",
            "source": "noaa",
            "items_done": 950,
            "items_total": 1000,
            "error": "50 of 1000 tiles failed",
        }))

        resp = c.get("/admin/pipeline/status?type=imagery")
        assert resp.status_code == 200

        ts_queries = [
            call for call in mock_docker.containers.list.call_args_list
            if "geographica-tileserver" in (call.kwargs.get("filters", {}) or {}).get("name", "")
        ]
        assert ts_queries, (
            "completed_partial should also trigger the TileServer handoff "
            "— there are tiles available to serve, even if some failed"
        )

        updated = json.loads(state_file.read_text())
        assert "tileserver_restarted_at" in updated


class TestCrashPathStillHandled:
    """Regression: running→dead container (old guard path) must still fire the restart."""

    def test_running_status_with_dead_container_still_restarts(self, client):
        c, main, tmp_path, mock_docker = client

        # Pipeline crashed — state is still "running" but container is gone,
        # and logs contain the success marker.
        state_file = tmp_path / ".pipeline-state.json"
        state_file.write_text(json.dumps({
            "status": "running",
            "type": "imagery",
            "mode": "noaa",
            "source": "noaa",
            "bbox": "-113.4,32.7,-110.4,34.2",
            "container_id": "abc123",
            "started_at": "2026-04-18T06:19:14+00:00",
        }))

        dead_container = MagicMock()
        dead_container.logs.return_value = b"Processing...\nNOAA pipeline complete: 1200/1200 tiles\n"

        # Intercept containers.list to surface the dead pipeline container for log capture,
        # and still return a running tileserver.
        def _list(all=False, filters=None):
            name_filter = (filters or {}).get("name", "")
            if "geographica-tileserver" in name_filter:
                ts = MagicMock()
                ts.status = "running"
                ts.restart = MagicMock()
                return [ts]
            if "geographica-pipeline" in name_filter and all:
                return [dead_container]
            return []

        mock_docker.containers.list.side_effect = _list

        resp = c.get("/admin/pipeline/status?type=imagery")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        # Crash-recovery path should also stamp the state.
        updated = json.loads(state_file.read_text())
        assert "tileserver_restarted_at" in updated
