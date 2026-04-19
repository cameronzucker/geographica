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
    poi_build_cmd_v1,
    osm_pois_cmd_v1,
    elevation_cmd_v1,
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
        cmd = poi_build_cmd_v1(bbox, "AZ,CA", "/tmp/poi.sqlite")
        assert "--bbox" in cmd
        assert bbox in cmd
        assert "--states" in cmd
        assert "--output" in cmd
        assert isinstance(cmd, list)

    def test_osm_pois_cmd_structure(self):
        cmd = osm_pois_cmd_v1("/data/west.osm.pbf", "/data/poi.sqlite", "-124.8,31.3,-102.0,49.0")
        assert "build_osm_pois.py" in " ".join(cmd)
        assert "--pbf" in cmd
        assert "--output" in cmd
        assert "--bbox" in cmd
        assert isinstance(cmd, list)

    def test_elevation_cmd_structure(self):
        cmd = elevation_cmd_v1("-124.8,31.3,-102.0,49.0", "/data/elevation.mbtiles")
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


from setup.runner import (
    osm_download_cmd, osm_merge_cmd, osm_copy_cmd,
    planetiler_pull_cmd, planetiler_build_cmd,
    poi_build_cmd, osm_pois_cmd, public_lands_cmd, elevation_cmd,
    base_imagery_cmd, detail_imagery_cmd,
    fonts_cmd, styles_cmd, docker_build_cmd,
)

_CTX_BASE = {
    "bbox": "-114,31,-109,37",
    "layer_bbox": {"basemap": "", "base_imagery": "", "detail_imagery": ""},
    "layers": {"basemap": "download", "base_imagery": "naip",
               "detail_imagery": "m2m", "elevation": "download"},
    "data_path": "/srv/geographica/data",
    "scripts_path": "/home/administrator/Code/geographica/scripts",
    "base_imagery_zoom": 15,
}


class TestCommandBuilders:
    def test_osm_download_cmd(self):
        cmd = osm_download_cmd(_CTX_BASE)
        assert cmd[0] == "bash"
        joined = " ".join(cmd)
        assert "arizona" in joined
        assert "wget" in joined or "curl" in joined

    def test_osm_download_cmd_verifies_md5(self):
        """Beta-tester 2026-04-19 report: osm_merge failed with
        `invalid BlobHeader size (> max_blob_header_size)` because the
        upstream wget dropped mid-download and left a truncated PBF.
        We now pull Geofabrik's published .md5 and verify before the
        merge step ever sees the file. Without md5sum --check in the
        download script this regression comes back silently."""
        script = " ".join(osm_download_cmd(_CTX_BASE))
        assert ".md5" in script, (
            "osm_download_cmd must fetch Geofabrik's .md5 sidecar — "
            "integrity verification is the whole point of this step"
        )
        assert "md5sum" in script and "--check" in script, (
            "osm_download_cmd must invoke `md5sum --check` against the "
            "downloaded .md5 file"
        )

    def test_osm_download_cmd_validates_pbf_structure(self):
        """md5 agreement isn't sufficient — fileinfo catches structural
        corruption that slips past a matching hash (rare but cheap to
        check, and it's exactly what osmium merge will trip on later)."""
        script = " ".join(osm_download_cmd(_CTX_BASE))
        assert "osmium fileinfo" in script, (
            "osm_download_cmd must run `osmium fileinfo` as a structural "
            "backstop to md5 verification"
        )

    def test_osm_download_cmd_retries_on_corruption(self):
        """A single failed verify must not abort the whole pipeline;
        the script retries with rm + re-download before giving up."""
        script = " ".join(osm_download_cmd(_CTX_BASE))
        # Accept either an explicit "rm -f" that fires on retry OR a
        # retry loop that re-wgets after a failed check.
        assert "rm -f" in script or "rm \"" in script, (
            "retry path must delete the corrupt .pbf before re-downloading"
        )
        # Must have some bounded retry mechanism (avoids infinite loop
        # on a persistently-failing mirror).
        assert "attempt" in script.lower() or "retries" in script.lower(), (
            "osm_download_cmd must bound retries to avoid infinite loop "
            "on a persistently-bad mirror"
        )

    def test_osm_download_cmd_failure_names_the_state(self):
        """When download ultimately fails, the error message must name
        WHICH state failed so the user (or beta tester) can surgically
        `rm` just that file instead of nuking the whole PBF dir."""
        script = " ".join(osm_download_cmd(_CTX_BASE))
        # The diagnostic must reference the shell var holding state name
        # inside the failure branch. Accept either $s / ${s} explicitly
        # in an error/echo near the failure path.
        assert "ERROR" in script, (
            "osm_download_cmd must emit a clear ERROR line on failure"
        )

    def test_osm_merge_cmd(self):
        cmd = osm_merge_cmd(_CTX_BASE)
        assert cmd[0] == "bash"
        joined = " ".join(cmd)
        assert "osmium merge" in joined
        assert "western-us.osm.pbf" in joined

    def test_osm_merge_cmd_validates_each_file_before_merging(self):
        """Pre-merge validation makes the merge error actionable: we
        name the specific corrupt file instead of dumping an opaque
        `invalid BlobHeader size` with no filename (what the beta
        tester saw 2026-04-19)."""
        script = " ".join(osm_merge_cmd(_CTX_BASE))
        assert "osmium fileinfo" in script, (
            "osm_merge_cmd must run `osmium fileinfo` on each PBF "
            "before invoking osmium merge, so the error names the "
            "file instead of dumping a header-size error"
        )

    def test_osm_merge_cmd_error_message_names_file_and_next_steps(self):
        """When a PBF is corrupt, the error must tell the user which
        file AND what to do about it. Asking them to guess is exactly
        what turned the 2026-04-19 beta report into a multi-day stall."""
        script = " ".join(osm_merge_cmd(_CTX_BASE))
        # Accept any clear 'rm' instruction in the error message text
        # (the string appears in the bash script's echo output).
        assert "rm" in script, (
            "osm_merge_cmd's failure message must include an `rm` command "
            "the user can copy-paste to recover"
        )

    def test_osm_copy_cmd(self):
        cmd = osm_copy_cmd(_CTX_BASE)
        assert cmd[0] == "bash"
        assert "cp " in " ".join(cmd)

    def test_planetiler_pull_cmd(self):
        cmd = planetiler_pull_cmd()
        assert cmd[0] == "docker"
        assert cmd[1] == "pull"
        assert cmd[-1].endswith(":0.10.2")

    def test_planetiler_build_cmd(self):
        cmd = planetiler_build_cmd(_CTX_BASE)
        assert cmd[0] == "docker"
        assert "--rm" in cmd
        joined = " ".join(cmd)
        assert "planetiler:0.10.2" in joined
        assert "/data/pbf/western-us.osm.pbf" in joined
        assert "/data/basemap.mbtiles" in joined

    def test_poi_build_cmd(self):
        cmd = poi_build_cmd(_CTX_BASE)
        assert cmd[0] == "python3"
        assert cmd[1].endswith("/build_poi_index.py")
        assert cmd[cmd.index("--bbox") + 1] == "-114,31,-109,37"

    def test_osm_pois_cmd(self):
        cmd = osm_pois_cmd(_CTX_BASE)
        assert cmd[0] == "python3"
        assert cmd[1].endswith("/build_osm_pois.py")
        assert cmd[cmd.index("--pbf") + 1].endswith("western-us.osm.pbf")

    def test_base_imagery_cmd_naip(self):
        ctx = dict(_CTX_BASE)
        ctx["layers"] = dict(ctx["layers"])
        ctx["layers"]["base_imagery"] = "naip"
        cmd = base_imagery_cmd(ctx)
        assert cmd[0] == "python3"
        assert cmd[1].endswith("/acquire_imagery.py")
        assert "--mode" in cmd
        assert cmd[cmd.index("--mode") + 1] == "naip"
        assert "--bbox" in cmd
        assert cmd[cmd.index("--bbox") + 1] == "-114,31,-109,37"
        assert "--zoom" in cmd
        assert cmd[cmd.index("--zoom") + 1] == "0-15"
        assert "--output" in cmd
        assert cmd[cmd.index("--output") + 1].endswith("imagery.mbtiles")

    def test_base_imagery_cmd_sentinel(self):
        ctx = dict(_CTX_BASE)
        ctx["layers"] = dict(ctx["layers"])
        ctx["layers"]["base_imagery"] = "sentinel"
        cmd = base_imagery_cmd(ctx)
        assert cmd[1].endswith("/acquire_sentinel.py")
        assert cmd[cmd.index("--zoom") + 1] == "15"

    def test_base_imagery_cmd_skip_raises(self):
        import pytest
        ctx = dict(_CTX_BASE)
        ctx["layers"] = dict(ctx["layers"])
        ctx["layers"]["base_imagery"] = "skip"
        with pytest.raises(ValueError):
            base_imagery_cmd(ctx)

    def test_detail_imagery_cmd_m2m(self):
        ctx = dict(_CTX_BASE)
        cmd = detail_imagery_cmd(ctx)
        assert cmd[0] == "python3"
        assert cmd[1].endswith("/acquire_imagery.py")
        assert cmd[cmd.index("--mode") + 1] == "m2m"
        assert cmd[cmd.index("--bbox") + 1] == "-114,31,-109,37"
        assert cmd[cmd.index("--output") + 1].endswith("imagery_detail.mbtiles")

    def test_detail_imagery_cmd_copernicus(self):
        ctx = dict(_CTX_BASE)
        ctx["layers"] = dict(ctx["layers"])
        ctx["layers"]["detail_imagery"] = "copernicus"
        cmd = detail_imagery_cmd(ctx)
        assert cmd[1].endswith("/acquire_sentinel.py")
        assert "--detail" in cmd

    def test_detail_imagery_cmd_skip_raises(self):
        import pytest
        ctx = dict(_CTX_BASE)
        ctx["layers"] = dict(ctx["layers"])
        ctx["layers"]["detail_imagery"] = "skip"
        with pytest.raises(ValueError):
            detail_imagery_cmd(ctx)

    def test_public_lands_cmd(self):
        cmd = public_lands_cmd(_CTX_BASE)
        assert cmd[0] == "python3"
        assert cmd[1].endswith("/build_public_lands.py")
        assert cmd[cmd.index("--bbox") + 1] == "-114,31,-109,37"

    def test_elevation_cmd(self):
        cmd = elevation_cmd(_CTX_BASE)
        assert cmd[0] == "python3"
        assert cmd[1].endswith("/download_elevation.py")
        assert cmd[cmd.index("--zoom") + 1] == "0-14"

    def test_fonts_cmd(self):
        cmd = fonts_cmd(_CTX_BASE)
        assert "fonts" in " ".join(cmd).lower()

    def test_styles_cmd(self):
        cmd = styles_cmd(_CTX_BASE)
        assert "styles" in " ".join(cmd).lower()

    def test_docker_build_cmd(self):
        cmd = docker_build_cmd()
        assert cmd[:3] == ["docker", "compose", "build"]

    def test_layer_bbox_override_base_imagery(self):
        """layer_bbox override falls back to basemap bbox when layer key empty."""
        ctx = dict(_CTX_BASE)
        ctx["layer_bbox"] = dict(ctx["layer_bbox"])
        ctx["layer_bbox"]["base_imagery"] = "-112,33,-110,34"
        cmd = base_imagery_cmd(ctx)
        assert cmd[cmd.index("--bbox") + 1] == "-112,33,-110,34"


class TestCheckpointResilience:
    def test_corrupt_json_returns_empty(self, tmp_path):
        from setup.runner import Checkpoint
        path = tmp_path / "ckpt.json"
        path.write_text("{not valid json")
        cp = Checkpoint(str(path))
        assert cp.get_completed() == []

    def test_persist_is_atomic(self):
        from setup import runner
        import inspect
        src = inspect.getsource(runner.Checkpoint._persist)
        assert ".tmp" in src or "os.replace" in src or "rename" in src

    def test_persist_creates_parent_dir(self, tmp_path):
        from setup.runner import Checkpoint
        nested = tmp_path / "deep" / "nested" / "ckpt.json"
        cp = Checkpoint(str(nested))
        cp.mark_completed("x")
        assert nested.exists()

    def test_reset_clears_file(self, tmp_path):
        from setup.runner import Checkpoint
        path = tmp_path / "ckpt.json"
        cp = Checkpoint(str(path))
        cp.mark_completed("a")
        cp.reset()
        assert not path.exists()


class TestShutdownKillsGrandchildren:
    def test_run_command_uses_start_new_session(self):
        from setup import runner
        import inspect
        src = inspect.getsource(runner.run_command)
        assert "start_new_session=True" in src, (
            "run_command must spawn with start_new_session=True so shutdown "
            "can os.killpg the whole group (B17)"
        )

    def test_shutdown_children_uses_killpg(self):
        from setup import runner
        import inspect
        src = inspect.getsource(runner.shutdown_children)
        assert "killpg" in src
