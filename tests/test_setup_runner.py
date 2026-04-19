"""Tests for setup/runner.py — subprocess runner with checkpoint management."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "setup"))
from runner import (
    Checkpoint,
    geofabrik_url,
    planetiler_cmd,
    poi_build_cmd,
    osm_pois_cmd,
    elevation_cmd,
    run_command,
    shutdown_children,
)


# ---------------------------------------------------------------------------
# TestCheckpoint
# ---------------------------------------------------------------------------
class TestCheckpoint:
    def test_new_checkpoint_has_no_completed(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            os.unlink(path)  # ensure file doesn't exist
            cp = Checkpoint(path)
            assert cp.get_completed() == []
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_mark_completed_works(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            os.unlink(path)
            cp = Checkpoint(path)
            cp.mark_completed("download_pbf")
            assert cp.is_completed("download_pbf") is True
            assert cp.is_completed("build_tiles") is False
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_persistence_write_then_reread(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            os.unlink(path)
            cp1 = Checkpoint(path)
            cp1.mark_completed("step_a")
            cp1.mark_completed("step_b")

            # Re-read from same path
            cp2 = Checkpoint(path)
            assert cp2.is_completed("step_a") is True
            assert cp2.is_completed("step_b") is True
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_reset_clears_all(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            os.unlink(path)
            cp = Checkpoint(path)
            cp.mark_completed("step_x")
            cp.mark_completed("step_y")
            cp.reset()
            assert cp.get_completed() == []
            assert not os.path.exists(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_get_completed_returns_sorted(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            os.unlink(path)
            cp = Checkpoint(path)
            cp.mark_completed("charlie")
            cp.mark_completed("alpha")
            cp.mark_completed("bravo")
            assert cp.get_completed() == ["alpha", "bravo", "charlie"]
        finally:
            if os.path.exists(path):
                os.unlink(path)


# ---------------------------------------------------------------------------
# TestBuildCommandArgs
# ---------------------------------------------------------------------------
class TestBuildCommandArgs:
    def test_geofabrik_url_arizona(self):
        url = geofabrik_url("arizona")
        assert url == "https://download.geofabrik.de/north-america/us/arizona-latest.osm.pbf"

    def test_geofabrik_url_hyphenated(self):
        url = geofabrik_url("new-mexico")
        assert url == "https://download.geofabrik.de/north-america/us/new-mexico-latest.osm.pbf"

    def test_planetiler_cmd_contains_docker_force_heap(self):
        cmd = planetiler_cmd("/data/input.pbf", "/data/output.mbtiles", "8g")
        assert "docker" in cmd
        assert "--force" in cmd
        assert any("8g" in arg for arg in cmd)
        # Must be a list, not a string
        assert isinstance(cmd, list)

    def test_poi_build_cmd_contains_bbox(self):
        bbox = "-124.8,31.3,-102.0,49.0"
        cmd = poi_build_cmd(bbox, "AZ,CA", "/tmp/poi.sqlite")
        assert "--bbox" in cmd
        assert bbox in cmd
        assert "--states" in cmd
        assert "--output" in cmd
        assert isinstance(cmd, list)

    def test_osm_pois_cmd_structure(self):
        cmd = osm_pois_cmd("/data/west.osm.pbf", "/data/poi.sqlite", "-124.8,31.3,-102.0,49.0")
        assert "build_osm_pois.py" in " ".join(cmd)
        assert "--pbf" in cmd
        assert "--output" in cmd
        assert "--bbox" in cmd
        assert isinstance(cmd, list)

    def test_elevation_cmd_structure(self):
        cmd = elevation_cmd("-124.8,31.3,-102.0,49.0", "/data/elevation.mbtiles")
        assert "download_elevation.py" in " ".join(cmd)
        assert "--bbox" in cmd
        assert "--output" in cmd
        assert isinstance(cmd, list)


# ---------------------------------------------------------------------------
# TestRunCommand
# ---------------------------------------------------------------------------
class TestRunCommand:
    @pytest.mark.asyncio
    async def test_run_command_returns_exit_code(self):
        """Simple command that exits 0."""
        chunks = []

        def on_output(source, chunk):
            chunks.append((source, chunk))

        code = await run_command(
            ["python3", "-c", "print('hello')"],
            cwd="/tmp",
            on_output=on_output,
        )
        assert code == 0
        # Should have captured stdout
        stdout_chunks = [c for s, c in chunks if s == "stdout"]
        assert any(b"hello" in c for c in stdout_chunks)

    @pytest.mark.asyncio
    async def test_run_command_captures_stderr(self):
        """Command that writes to stderr."""
        chunks = []

        def on_output(source, chunk):
            chunks.append((source, chunk))

        code = await run_command(
            ["python3", "-c", "import sys; sys.stderr.write('err_msg\\n')"],
            cwd="/tmp",
            on_output=on_output,
        )
        assert code == 0
        stderr_chunks = [c for s, c in chunks if s == "stderr"]
        assert any(b"err_msg" in c for c in stderr_chunks)

    @pytest.mark.asyncio
    async def test_run_command_nonzero_exit(self):
        """Command that exits with non-zero."""
        code = await run_command(
            ["python3", "-c", "raise SystemExit(42)"],
            cwd="/tmp",
            on_output=lambda s, c: None,
        )
        assert code == 42

    @pytest.mark.asyncio
    async def test_run_command_env_extra(self):
        """env_extra variables are passed to subprocess."""
        chunks = []

        def on_output(source, chunk):
            chunks.append((source, chunk))

        code = await run_command(
            ["python3", "-c", "import os; print(os.environ.get('TEST_GEOGRAPHICA_VAR', ''))"],
            cwd="/tmp",
            on_output=on_output,
            env_extra={"TEST_GEOGRAPHICA_VAR": "runner_test_value"},
        )
        assert code == 0
        stdout_chunks = [c for s, c in chunks if s == "stdout"]
        assert any(b"runner_test_value" in c for c in stdout_chunks)

    @pytest.mark.asyncio
    async def test_pythonunbuffered_is_set(self):
        """PYTHONUNBUFFERED=1 is always set."""
        chunks = []

        def on_output(source, chunk):
            chunks.append((source, chunk))

        code = await run_command(
            ["python3", "-c", "import os; print(os.environ.get('PYTHONUNBUFFERED', ''))"],
            cwd="/tmp",
            on_output=on_output,
        )
        assert code == 0
        stdout_chunks = [c for s, c in chunks if s == "stdout"]
        assert any(b"1" in c for c in stdout_chunks)


# ---------------------------------------------------------------------------
# TestShutdownChildren
# ---------------------------------------------------------------------------
class TestShutdownChildren:
    @pytest.mark.asyncio
    async def test_shutdown_children_terminates_active(self):
        """Start a long-running process, then shut it down."""
        code_future = asyncio.ensure_future(
            run_command(
                ["python3", "-c", "import time; time.sleep(60)"],
                cwd="/tmp",
                on_output=lambda s, c: None,
            )
        )
        # Give the process a moment to start
        await asyncio.sleep(0.3)
        shutdown_children()
        code = await code_future
        # Process was terminated, exit code should be negative (signal)
        assert code != 0


# ---------------------------------------------------------------------------
# TestPlanetilerPin
# ---------------------------------------------------------------------------
class TestPlanetilerPin:
    def test_version_constant_is_pinned(self):
        from setup.runner import PLANETILER_VERSION
        assert PLANETILER_VERSION == "0.10.2"

    def test_docker_image_tag_matches_version(self):
        cmd = planetiler_cmd("/tmp/a.osm.pbf", "/tmp/out.mbtiles", "4g")
        image = [a for a in cmd if "planetiler" in a][-1]
        assert image.endswith(":0.10.2")
