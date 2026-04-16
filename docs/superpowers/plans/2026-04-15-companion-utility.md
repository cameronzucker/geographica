# Geographica Companion Utility — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a cross-platform desktop companion tool that downloads geospatial imagery on a fast workstation and transfers results to a Geographica Pi over LAN.

**Architecture:** Separate repo (`geographica-companion`). FastAPI backend (127.0.0.1:9000) serves a browser UI with MapLibre minimap. Pipeline scripts adapted from main repo run as parallel subprocesses via an orchestrator. Transfer uses rsync (key auth) or paramiko SFTP (password auth). Post-transfer SSH exec registers sources in TileServer and restarts it.

**Tech Stack:** Python 3.10+, FastAPI, uvicorn, MapLibre GL JS, paramiko, aiohttp, aiosqlite, bundled GDAL binaries

**Spec:** `docs/superpowers/specs/2026-04-15-companion-utility-design.md`

**Main repo:** `/home/administrator/Code/geographica`

---

## File Structure

### New Repository: `geographica-companion/`

```
geographica-companion/
├── companion.py              # FastAPI app + entry point
├── companion.sh              # Linux launcher
├── companion.bat             # Windows launcher
├── companion.desktop         # Linux desktop entry
├── requirements.txt          # Python dependencies
├── transfer.py               # Rsync + paramiko SFTP transfer engine
├── deploy.py                 # Post-transfer deployment (SSH exec)
├── gdal_env.py               # GDAL binary detection + env setup
├── pipelines/
│   ├── __init__.py
│   ├── orchestrator.py       # Parallel subprocess coordinator
│   ├── acquire_imagery.py    # Adapted from main repo
│   ├── acquire_naip.py       # Adapted from main repo
│   ├── acquire_sentinel.py   # Adapted from main repo
│   ├── download_elevation.py # Adapted from main repo
│   ├── import_imagery.py     # Adapted from main repo
│   ├── pipeline_progress.py  # Copied from main repo (minimal changes)
│   └── build_county_index.py # Copied from main repo (minimal changes)
├── static/
│   ├── index.html            # Single-page app (4 tabs)
│   ├── companion.js          # UI logic
│   └── companion.css         # Catppuccin Mocha theme
├── bin/
│   ├── linux-x64/            # Bundled GDAL (populated separately)
│   └── windows-x64/          # Bundled GDAL (populated separately)
├── scripts/
│   └── sync_pipelines.sh     # Pipeline provenance documentation
├── tests/
│   ├── test_companion.py     # FastAPI endpoint tests
│   ├── test_orchestrator.py  # Orchestrator tests
│   ├── test_transfer.py      # Transfer engine tests
│   ├── test_deploy.py        # Deployment tests
│   └── test_gdal_env.py      # GDAL detection tests
└── .gitignore
```

### Main Repo Changes

```
geographica/
├── scripts/
│   └── tileserver_config.py  # ADD: CLI entry point (__main__ block)
└── tests/
    └── test_tileserver_config_cli.py  # ADD: CLI tests
```

---

## Task 1: Add CLI Entry Point to tileserver_config.py (Main Repo)

**Files:**
- Modify: `/home/administrator/Code/geographica/scripts/tileserver_config.py`
- Create: `/home/administrator/Code/geographica/tests/test_tileserver_config_cli.py`

This is a prerequisite — the companion's SSH deployment step calls `tileserver_config.py` as a CLI tool.

- [ ] **Step 1: Read current tileserver_config.py**

Read `/home/administrator/Code/geographica/scripts/tileserver_config.py` to understand the existing API.

- [ ] **Step 2: Write failing test for CLI `add` command**

Create `tests/test_tileserver_config_cli.py`:

```python
import json
import subprocess
import sys
from pathlib import Path
import pytest

SCRIPT = str(Path(__file__).parent.parent / "scripts" / "tileserver_config.py")


def make_config(tmp_path):
    config = {"options": {}, "data": {"basemap": {"mbtiles": "/srv/data/basemap.mbtiles"}}, "styles": {}}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    return config_path


class TestTileServerConfigCLI:
    def test_add_source(self, tmp_path):
        config_path = make_config(tmp_path)
        result = subprocess.run(
            [sys.executable, SCRIPT, "add", str(config_path), "imagery_noaa", "/srv/data/imagery_noaa.mbtiles"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        config = json.loads(config_path.read_text())
        assert "imagery_noaa" in config["data"]
        assert config["data"]["imagery_noaa"]["mbtiles"] == "/srv/data/imagery_noaa.mbtiles"

    def test_add_duplicate_exits_zero(self, tmp_path):
        config_path = make_config(tmp_path)
        # Add once
        subprocess.run([sys.executable, SCRIPT, "add", str(config_path), "basemap", "/srv/data/basemap.mbtiles"],
                       capture_output=True, text=True)
        # Add again — should succeed (already exists)
        result = subprocess.run(
            [sys.executable, SCRIPT, "add", str(config_path), "basemap", "/srv/data/basemap.mbtiles"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "already exists" in result.stdout.lower()

    def test_remove_source(self, tmp_path):
        config_path = make_config(tmp_path)
        result = subprocess.run(
            [sys.executable, SCRIPT, "remove", str(config_path), "basemap"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        config = json.loads(config_path.read_text())
        assert "basemap" not in config["data"]

    def test_remove_nonexistent_exits_zero(self, tmp_path):
        config_path = make_config(tmp_path)
        result = subprocess.run(
            [sys.executable, SCRIPT, "remove", str(config_path), "nonexistent"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_no_args_shows_usage(self):
        result = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True)
        assert result.returncode != 0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_tileserver_config_cli.py -v`
Expected: FAIL — no CLI entry point exists.

- [ ] **Step 4: Add CLI entry point to tileserver_config.py**

Append to the end of `scripts/tileserver_config.py`:

```python
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage TileServer GL config sources")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Add an MBTiles source")
    add_parser.add_argument("config_path", help="Path to tileserver config.json")
    add_parser.add_argument("name", help="Source name (e.g., imagery_noaa)")
    add_parser.add_argument("mbtiles_path", help="Container-internal MBTiles path (e.g., /srv/data/imagery_noaa.mbtiles)")

    remove_parser = subparsers.add_parser("remove", help="Remove an MBTiles source")
    remove_parser.add_argument("config_path", help="Path to tileserver config.json")
    remove_parser.add_argument("name", help="Source name to remove")

    args = parser.parse_args()

    if args.command == "add":
        added = add_mbtiles_to_config(args.config_path, args.name, args.mbtiles_path)
        if added:
            print(f"Added source '{args.name}' -> {args.mbtiles_path}")
        else:
            print(f"Source '{args.name}' already exists, skipped")
    elif args.command == "remove":
        removed = remove_mbtiles_from_config(args.config_path, args.name)
        if removed:
            print(f"Removed source '{args.name}'")
        else:
            print(f"Source '{args.name}' not found, skipped")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_tileserver_config_cli.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 6: Run full test suite to confirm no regressions**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/ -v --tb=short`
Expected: 540+ passed (535 existing + 5 new), 9 pre-existing errors.

- [ ] **Step 7: Commit**

```bash
cd /home/administrator/Code/geographica
git add scripts/tileserver_config.py tests/test_tileserver_config_cli.py
git commit -m "feat: add CLI entry point to tileserver_config.py — add/remove sources via command line"
```

---

## Task 2: Create Companion Repository Skeleton

**Files:**
- Create: `~/Code/geographica-companion/` — new repo with basic structure

- [ ] **Step 1: Create repo directory and initialize git**

```bash
mkdir -p ~/Code/geographica-companion
cd ~/Code/geographica-companion
git init
```

- [ ] **Step 2: Create .gitignore**

Create `.gitignore`:

```
__pycache__/
*.pyc
.venv/
venv/
geographica-data/
*.egg-info/
dist/
build/
.pytest_cache/
bin/linux-x64/
bin/windows-x64/
```

- [ ] **Step 3: Create requirements.txt**

Create `requirements.txt`:

```
fastapi>=0.100.0
uvicorn>=0.23.0
paramiko>=3.0.0
aiohttp>=3.9.0
aiofiles>=23.0.0
aiosqlite>=0.19.0
tqdm>=4.65.0
shapely>=2.0.0
```

- [ ] **Step 4: Create test requirements**

Create `requirements-test.txt`:

```
-r requirements.txt
pytest>=7.0.0
pytest-asyncio>=0.21.0
httpx>=0.24.0
```

- [ ] **Step 5: Create pipelines/__init__.py**

Create `pipelines/__init__.py`:

```python
"""Pipeline scripts adapted from geographica/scripts/ for workstation use."""
```

- [ ] **Step 6: Create directory structure**

```bash
mkdir -p pipelines static bin/linux-x64 bin/windows-x64 scripts tests
touch bin/linux-x64/.gitkeep bin/windows-x64/.gitkeep
```

- [ ] **Step 7: Create sync_pipelines.sh**

Create `scripts/sync_pipelines.sh`:

```bash
#!/bin/bash
# Pipeline script provenance — documents what was copied from the main Geographica repo
# and what workstation-specific changes were applied.
#
# This is documentation for manual sync, not an automated tool.
# When the main repo's pipeline scripts get bug fixes, review this file
# to determine which fixes apply to the companion fork.
#
# Source repo: geographica/scripts/
# Target dir:  pipelines/
#
# Files copied and adapted:
#   acquire_imagery.py   — removed os.setsid/killpg, nice, /dev/stdout->/vsistdout/,
#                          /secrets path, module globals, signal handlers, tileserver imports.
#                          Added unique state file name.
#   acquire_naip.py      — removed nice, module globals, signal handlers.
#                          Added unique state file name.
#   acquire_sentinel.py  — removed nice, /secrets path, module globals, signal handlers.
#                          Added unique state file name.
#   download_elevation.py — removed module globals, signal handlers.
#                          State file already unique (.elevation-state.json).
#   import_imagery.py    — removed /data default, tileserver imports.
#                          Added unique state file name.
#   pipeline_progress.py — copied as-is (no platform-specific code).
#   build_county_index.py — copied as-is (requires GDAL Python bindings).
#
# Files NOT copied (companion-only):
#   orchestrator.py      — parallel subprocess coordinator (new)
```

- [ ] **Step 8: Commit skeleton**

```bash
cd ~/Code/geographica-companion
git add -A
git commit -m "chore: initial project skeleton — directory structure, requirements, gitignore"
```

---

## Task 3: GDAL Environment Detection

**Files:**
- Create: `~/Code/geographica-companion/gdal_env.py`
- Create: `~/Code/geographica-companion/tests/test_gdal_env.py`

- [ ] **Step 1: Write failing tests for GDAL detection**

Create `tests/test_gdal_env.py`:

```python
import os
import sys
import platform
from pathlib import Path
from unittest.mock import patch
import pytest

from gdal_env import detect_gdal, get_gdal_env


class TestDetectGdal:
    def test_returns_bundled_path_when_exists(self, tmp_path):
        """Bundled GDAL takes priority over system PATH."""
        bin_dir = tmp_path / "bin" / "linux-x64"
        bin_dir.mkdir(parents=True)
        (bin_dir / "gdalwarp").write_text("#!/bin/sh\n")
        (bin_dir / "gdalwarp").chmod(0o755)

        with patch("gdal_env.COMPANION_DIR", tmp_path):
            with patch("platform.system", return_value="Linux"):
                result = detect_gdal()
        assert result is not None
        assert "linux-x64" in str(result)

    def test_returns_none_when_no_gdal(self, tmp_path):
        """Returns None when no GDAL found anywhere."""
        with patch("gdal_env.COMPANION_DIR", tmp_path):
            with patch("shutil.which", return_value=None):
                result = detect_gdal()
        assert result is None

    def test_env_var_override(self, tmp_path):
        """GDAL_BIN_DIR env var overrides everything."""
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        (custom_dir / "gdalwarp").write_text("#!/bin/sh\n")

        with patch.dict(os.environ, {"GDAL_BIN_DIR": str(custom_dir)}):
            result = detect_gdal()
        assert result == custom_dir

    def test_system_path_fallback(self, tmp_path):
        """Falls back to system PATH when no bundled GDAL."""
        with patch("gdal_env.COMPANION_DIR", tmp_path):
            with patch("shutil.which", return_value="/usr/bin/gdalwarp"):
                result = detect_gdal()
        assert result is None  # None means "use system PATH as-is"


class TestGetGdalEnv:
    def test_env_includes_path_and_proj(self, tmp_path):
        """Returns env dict with PATH, PROJ_LIB, GDAL_DATA."""
        bin_dir = tmp_path / "bin" / "linux-x64"
        share_proj = bin_dir / "share" / "proj"
        share_gdal = bin_dir / "share" / "gdal"
        share_proj.mkdir(parents=True)
        share_gdal.mkdir(parents=True)

        env = get_gdal_env(bin_dir, gdal_threads=4)
        assert str(bin_dir) in env["PATH"]
        assert env["PROJ_LIB"] == str(share_proj)
        assert env["GDAL_DATA"] == str(share_gdal)
        assert env["GDAL_NUM_THREADS"] == "4"

    def test_env_inherits_current(self, tmp_path):
        """Returned env includes current environment variables."""
        env = get_gdal_env(None, gdal_threads=2)
        assert "HOME" in env or "USERPROFILE" in env
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Code/geographica-companion && python -m pytest tests/test_gdal_env.py -v`
Expected: FAIL — `gdal_env` module not found.

- [ ] **Step 3: Implement gdal_env.py**

Create `gdal_env.py`:

```python
"""GDAL binary detection and environment setup for the companion utility."""

import os
import platform
import shutil
from pathlib import Path

COMPANION_DIR = Path(__file__).parent


def detect_gdal() -> Path | None:
    """Detect GDAL binaries. Returns bin directory path, or None for system PATH.

    Resolution order:
    1. GDAL_BIN_DIR env var (user override)
    2. Bundled bin/{platform}/ directory
    3. System PATH (returns None — caller uses PATH as-is)
    4. None with no system gdalwarp found (caller should error)
    """
    # 1. User override
    env_dir = os.environ.get("GDAL_BIN_DIR")
    if env_dir:
        return Path(env_dir)

    # 2. Bundled binaries
    system = platform.system()
    if system == "Linux":
        bundled = COMPANION_DIR / "bin" / "linux-x64"
    elif system == "Windows":
        bundled = COMPANION_DIR / "bin" / "windows-x64"
    else:
        bundled = None

    if bundled and bundled.is_dir():
        gdalwarp = bundled / ("gdalwarp.exe" if system == "Windows" else "gdalwarp")
        if gdalwarp.exists():
            return bundled

    # 3. System PATH fallback
    if shutil.which("gdalwarp"):
        return None  # None signals "system PATH is fine"

    # 4. Nothing found
    return None


def get_gdal_env(gdal_bin_dir: Path | None, gdal_threads: int = 0) -> dict:
    """Build environment dict for GDAL subprocess execution.

    Args:
        gdal_bin_dir: Path to GDAL binaries, or None for system PATH.
        gdal_threads: Number of GDAL threads (0 = ALL_CPUS).
    """
    env = os.environ.copy()

    if gdal_bin_dir:
        sep = ";" if platform.system() == "Windows" else ":"
        env["PATH"] = str(gdal_bin_dir) + sep + env.get("PATH", "")

        share_proj = gdal_bin_dir / "share" / "proj"
        share_gdal = gdal_bin_dir / "share" / "gdal"
        if share_proj.is_dir():
            env["PROJ_LIB"] = str(share_proj)
        if share_gdal.is_dir():
            env["GDAL_DATA"] = str(share_gdal)

    threads_str = str(gdal_threads) if gdal_threads > 0 else "ALL_CPUS"
    env["GDAL_NUM_THREADS"] = threads_str
    env["GDAL_CACHEMAX"] = "512"

    return env
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/Code/geographica-companion && python -m pytest tests/test_gdal_env.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/geographica-companion
git add gdal_env.py tests/test_gdal_env.py
git commit -m "feat: GDAL binary detection — bundled, env var, system PATH resolution"
```

---

## Task 4: Pipeline Orchestrator

**Files:**
- Create: `~/Code/geographica-companion/pipelines/orchestrator.py`
- Create: `~/Code/geographica-companion/tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests for orchestrator**

Create `tests/test_orchestrator.py`:

```python
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from pipelines.orchestrator import PipelineJob, Orchestrator


class TestPipelineJob:
    def test_job_creation(self):
        job = PipelineJob(
            pipeline="noaa",
            script="acquire_imagery.py",
            args=["--mode", "noaa", "--bbox", "-112,33,-111,34", "--output", "/tmp/test.mbtiles"],
        )
        assert job.pipeline == "noaa"
        assert job.status == "pending"
        assert job.process is None

    def test_state_file_name(self):
        job = PipelineJob(pipeline="noaa", script="acquire_imagery.py", args=[])
        assert job.state_filename == ".noaa-state.json"

    def test_different_pipelines_have_unique_state_files(self):
        job1 = PipelineJob(pipeline="noaa", script="acquire_imagery.py", args=[])
        job2 = PipelineJob(pipeline="elevation", script="download_elevation.py", args=[])
        assert job1.state_filename != job2.state_filename


class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_start_pipeline_creates_subprocess(self, tmp_path):
        """Starting a pipeline launches a subprocess."""
        orch = Orchestrator(
            pipelines_dir=Path(__file__).parent.parent / "pipelines",
            output_dir=tmp_path,
            env={},
        )
        script = tmp_path / "fake_pipeline.py"
        script.write_text(
            'import time, sys\n'
            'print("started", flush=True)\n'
            'time.sleep(10)\n'
        )

        job = PipelineJob(pipeline="test", script=str(script), args=[])
        await orch.start(job)

        assert job.status == "running"
        assert job.process is not None
        assert job.process.poll() is None  # still running

        await orch.cancel(job)

    @pytest.mark.asyncio
    async def test_cancel_pipeline_terminates_subprocess(self, tmp_path):
        """Cancelling a pipeline terminates the subprocess."""
        orch = Orchestrator(
            pipelines_dir=Path(__file__).parent.parent / "pipelines",
            output_dir=tmp_path,
            env={},
        )
        script = tmp_path / "slow_pipeline.py"
        script.write_text('import time\ntime.sleep(60)\n')

        job = PipelineJob(pipeline="test", script=str(script), args=[])
        await orch.start(job)
        await orch.cancel(job)

        await asyncio.sleep(0.5)
        assert job.process.poll() is not None  # process exited
        assert job.status == "cancelled"

    @pytest.mark.asyncio
    async def test_read_state_returns_json(self, tmp_path):
        """Orchestrator reads pipeline state files."""
        orch = Orchestrator(
            pipelines_dir=Path(__file__).parent.parent / "pipelines",
            output_dir=tmp_path,
            env={},
        )
        state = {"source": "noaa", "status": "running", "items_done": 5, "items_total": 10}
        (tmp_path / ".noaa-state.json").write_text(json.dumps(state))

        result = orch.read_state("noaa")
        assert result["items_done"] == 5
        assert result["status"] == "running"

    @pytest.mark.asyncio
    async def test_read_state_missing_file_returns_empty(self, tmp_path):
        """Missing state file returns empty dict."""
        orch = Orchestrator(
            pipelines_dir=Path(__file__).parent.parent / "pipelines",
            output_dir=tmp_path,
            env={},
        )
        result = orch.read_state("nonexistent")
        assert result == {}

    @pytest.mark.asyncio
    async def test_list_jobs(self, tmp_path):
        """Orchestrator tracks all jobs."""
        orch = Orchestrator(
            pipelines_dir=Path(__file__).parent.parent / "pipelines",
            output_dir=tmp_path,
            env={},
        )
        script = tmp_path / "noop.py"
        script.write_text('pass\n')

        job1 = PipelineJob(pipeline="a", script=str(script), args=[])
        job2 = PipelineJob(pipeline="b", script=str(script), args=[])
        await orch.start(job1)
        await orch.start(job2)

        jobs = orch.list_jobs()
        assert len(jobs) == 2

        await orch.cancel_all()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Code/geographica-companion && python -m pytest tests/test_orchestrator.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement orchestrator.py**

Create `pipelines/orchestrator.py`:

```python
"""Parallel pipeline subprocess coordinator.

Each pipeline runs as a separate Python subprocess, providing natural isolation
from module-level globals, signal handlers, and POSIX-specific code in the
pipeline scripts. The orchestrator manages child PIDs and state file reading.
"""

import asyncio
import json
import os
import platform
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PipelineJob:
    """Represents a single pipeline execution."""
    pipeline: str
    script: str
    args: list[str]
    status: str = "pending"
    process: subprocess.Popen | None = None
    error: str | None = None

    @property
    def state_filename(self) -> str:
        return f".{self.pipeline}-state.json"


class Orchestrator:
    """Manages parallel pipeline subprocess execution."""

    def __init__(self, pipelines_dir: Path, output_dir: Path, env: dict):
        self._pipelines_dir = pipelines_dir
        self._output_dir = output_dir
        self._env = env
        self._jobs: dict[str, PipelineJob] = {}

    async def start(self, job: PipelineJob) -> None:
        """Launch a pipeline as a subprocess."""
        script_path = job.script
        if not os.path.isabs(script_path):
            script_path = str(self._pipelines_dir / script_path)

        cmd = [sys.executable, script_path] + job.args
        kwargs = {
            "env": self._env if self._env else None,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }

        if platform.system() != "Windows":
            kwargs["preexec_fn"] = os.setsid
        else:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        job.process = subprocess.Popen(cmd, **kwargs)
        job.status = "running"
        self._jobs[job.pipeline] = job

    async def cancel(self, job: PipelineJob) -> None:
        """Terminate a running pipeline subprocess."""
        if job.process and job.process.poll() is None:
            if platform.system() != "Windows":
                try:
                    os.killpg(os.getpgid(job.process.pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                job.process.terminate()
            job.status = "cancelled"

    async def cancel_all(self) -> None:
        """Cancel all running pipelines."""
        for job in self._jobs.values():
            if job.status == "running":
                await self.cancel(job)

    def read_state(self, pipeline: str) -> dict:
        """Read a pipeline's JSON state file."""
        state_file = self._output_dir / f".{pipeline}-state.json"
        if not state_file.exists():
            return {}
        try:
            return json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def read_all_states(self) -> dict[str, dict]:
        """Read state files for all tracked jobs."""
        return {name: self.read_state(name) for name in self._jobs}

    def list_jobs(self) -> dict[str, PipelineJob]:
        """Return all tracked jobs."""
        return dict(self._jobs)

    def get_job(self, pipeline: str) -> PipelineJob | None:
        """Get a specific job by pipeline name."""
        return self._jobs.get(pipeline)

    async def wait_for(self, job: PipelineJob) -> int:
        """Wait for a pipeline to complete. Returns exit code."""
        if not job.process:
            return -1
        loop = asyncio.get_event_loop()
        returncode = await loop.run_in_executor(None, job.process.wait)
        job.status = "completed" if returncode == 0 else "failed"
        if returncode != 0:
            stderr = job.process.stderr.read().decode() if job.process.stderr else ""
            job.error = stderr[-500:] if stderr else f"Exit code {returncode}"
        return returncode
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/Code/geographica-companion && python -m pytest tests/test_orchestrator.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/geographica-companion
git add pipelines/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: pipeline orchestrator — parallel subprocess management with cancel support"
```

---

## Task 5: FastAPI Backend

**Files:**
- Create: `~/Code/geographica-companion/companion.py`
- Create: `~/Code/geographica-companion/tests/test_companion.py`

- [ ] **Step 1: Write failing tests for core endpoints**

Create `tests/test_companion.py`. Test CSRF enforcement (POST without token returns 403, with token succeeds), CORS headers, `/api/config` returns csrf_token, `/api/pipelines` returns pipeline definitions, `/api/pipelines/{name}/state` returns state, `/api/disk` returns file list.

Use `httpx.AsyncClient` with `ASGITransport(app=app)` for testing FastAPI.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Code/geographica-companion && python -m pytest tests/test_companion.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement companion.py**

Create `companion.py` with:

- FastAPI app bound to `127.0.0.1:9000`
- CORS middleware restricting to `http://127.0.0.1:9000`
- CSRF middleware checking `X-CSRF-Token` header on POST/PUT/DELETE/PATCH
- `CSRF_TOKEN = secrets.token_urlsafe(32)` generated at startup
- Pipeline definitions list (basemap, noaa, m2m, sentinel, elevation, import)
- Lazy-initialized orchestrator (imports `gdal_env` and `orchestrator`)
- Endpoints: `GET /api/config`, `GET /api/pipelines`, `GET /api/pipelines/{name}/state`, `POST /api/pipelines/start`, `POST /api/pipelines/{name}/cancel`, `GET /api/pipelines/states`, `GET /api/disk`
- `_build_cli_args()` helper that builds pipeline-specific CLI arguments from request body
- Static file mount for `static/` directory
- `main()` entry point that runs uvicorn and opens browser

- [ ] **Step 4: Create minimal static/index.html placeholder**

Create `static/index.html` with a simple "Geographica Companion — UI placeholder" page.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ~/Code/geographica-companion && python -m pytest tests/test_companion.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
cd ~/Code/geographica-companion
git add companion.py static/index.html tests/test_companion.py
git commit -m "feat: FastAPI backend — CSRF, CORS, pipeline start/cancel/state endpoints"
```

---

## Task 6: Transfer Engine

**Files:**
- Create: `~/Code/geographica-companion/transfer.py`
- Create: `~/Code/geographica-companion/tests/test_transfer.py`

- [ ] **Step 1: Write failing tests for transfer engine**

Create `tests/test_transfer.py`. Test `ConnectionTestResult` (rsync available vs not, transfer method selection), `detect_transfer_method()` (key→rsync, password→sftp, no rsync→sftp), `transfer_file_rsync()` command construction (mock subprocess).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Code/geographica-companion && python -m pytest tests/test_transfer.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement transfer.py**

Create `transfer.py` with:

- `ConnectionTestResult` dataclass (ssh_ok, rsync_available, data_dir_writable, docker_ok, disk_free_bytes, repo_path, transfer_method property)
- `detect_transfer_method(auth_type, rsync_available)` — key auth uses rsync, password uses sftp
- `test_connection()` — paramiko SSH, checks rsync availability, data dir write access, docker permissions, disk space, repo path discovery via `docker inspect`
- `transfer_file_rsync()` — `asyncio.create_subprocess_exec` with rsync `-avP`, SSH key via `-e "ssh -i key"`, progress parsing from stdout
- `transfer_file_sftp()` — paramiko `SFTPClient.put()` with progress callback
- `transfer_all()` — iterates files, dispatches to rsync or sftp based on auth type

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/Code/geographica-companion && python -m pytest tests/test_transfer.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/geographica-companion
git add transfer.py tests/test_transfer.py
git commit -m "feat: transfer engine — rsync (key auth) and paramiko SFTP (password auth)"
```

---

## Task 7: Post-Transfer Deployment

**Files:**
- Create: `~/Code/geographica-companion/deploy.py`
- Create: `~/Code/geographica-companion/tests/test_deploy.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_deploy.py`. Test `source_name_from_filename()` (strips .mbtiles), `build_register_command()` (uses container path /srv/data/, not host path), `generate_deploy_script()` (includes set -euo pipefail, registers each file, restarts tileserver).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/Code/geographica-companion && python -m pytest tests/test_deploy.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement deploy.py**

Create `deploy.py` with:

- `source_name_from_filename(filename)` — strips `.mbtiles` extension
- `build_register_command(repo_path, source_name, filename)` — builds SSH command using container-internal path `/srv/data/<filename>`, not host path
- `generate_deploy_script(filenames, repo_path)` — bash script with `set -euo pipefail`, registers each source, restarts tileserver
- `deploy_to_pi()` — paramiko SSH, registers each source via `tileserver_config.py` CLI, restarts tileserver, returns result dict with registered/skipped/error

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/Code/geographica-companion && python -m pytest tests/test_deploy.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/Code/geographica-companion
git add deploy.py tests/test_deploy.py
git commit -m "feat: post-transfer deployment — SSH source registration + TileServer restart"
```

---

## Task 8: Browser UI

**Files:**
- Create: `~/Code/geographica-companion/static/index.html`
- Create: `~/Code/geographica-companion/static/companion.js`
- Create: `~/Code/geographica-companion/static/companion.css`

- [ ] **Step 1: Create companion.css with Catppuccin Mocha theme**

Reference the admin panel CSS at `/home/administrator/Code/geographica/frontend/config/index.html` (inline styles section). Key colors: bg `#1e1e2e`, surface `#181825`, elevated `#313244`, text `#cdd6f4`, muted `#7a8299`, heading `#f5f5f5`, blue `#89b4fa`, green `#a6e3a1`, yellow `#f9e2af`, red `#f38ba8`, purple `#cba6f7`, border `#45475a`.

Include: tab bar, card grid (2-column, expand to full width), source cards, form inputs, buttons (primary green/secondary/danger red), progress bars, status indicators, file list, manual command block.

- [ ] **Step 2: Create index.html with 4-tab structure**

Single-page app with tabs: Connect, Pipelines, Transfer, Status. Tab switching via show/hide divs. Loads MapLibre GL JS (CDN with local fallback). Fetches CSRF token from `/api/config` on page load. All credential fields have `autocomplete="off"`.

- [ ] **Step 3: Implement Connect tab**

Left panel: Pi hostname input, Connect button, status indicator, CDN fallback, Skip Map. Right panel: MapLibre map container with bbox drawing (mousedown→drag→mouseup rectangle), bbox coordinate fields, output directory field. Map initialization tries Pi TileServer at port 8090 first, falls back to OSM CDN tiles.

- [ ] **Step 4: Implement Pipelines tab**

Top bar: GDAL threads and download concurrency inputs. 2-column card grid from pipeline definitions. Each card expandable with pipeline-specific config (NOAA: state chips, M2M: credentials, Sentinel: dates+credentials, Import: file drop). Start/Cancel/Estimate buttons. Progress bar (updates without DOM rebuild — only update existing elements).

- [ ] **Step 5: Implement progress polling**

Poll `GET /api/pipelines/states` every 2 seconds when any pipeline is active. Update card progress bars, percentages, and status text. Do NOT rebuild DOM on poll (learned from admin panel polling bug).

- [ ] **Step 6: Implement Transfer tab**

Left: SSH auth form (hostname pre-filled from Connect, username, password/key toggle, Test Connection button showing results). Transfer method indicator. Right: file list from `GET /api/disk`, total size, Transfer All button. Bottom: generated rsync and ssh deploy commands (copyable).

- [ ] **Step 7: Implement Status tab**

Per-pipeline status cards, disk usage bar, completed files list, scrolling log viewer.

- [ ] **Step 8: Add transfer and deploy API endpoints to companion.py**

Add `POST /api/transfer/test`, `POST /api/transfer/start`, `POST /api/deploy`, `GET /api/deploy/script` endpoints to `companion.py`, wiring to `transfer.py` and `deploy.py`.

- [ ] **Step 9: Commit**

```bash
cd ~/Code/geographica-companion
git add static/ companion.py
git commit -m "feat: browser UI — 4-tab SPA with Connect, Pipelines, Transfer, Status tabs"
```

---

## Task 9: Copy and Adapt Pipeline Scripts

**Files:**
- Create: `~/Code/geographica-companion/pipelines/acquire_imagery.py` (adapted)
- Create: `~/Code/geographica-companion/pipelines/acquire_naip.py` (adapted)
- Create: `~/Code/geographica-companion/pipelines/acquire_sentinel.py` (adapted)
- Create: `~/Code/geographica-companion/pipelines/download_elevation.py` (adapted)
- Create: `~/Code/geographica-companion/pipelines/import_imagery.py` (adapted)
- Create: `~/Code/geographica-companion/pipelines/pipeline_progress.py` (copied as-is)
- Create: `~/Code/geographica-companion/pipelines/build_county_index.py` (copied as-is)

- [ ] **Step 1: Copy pipeline_progress.py and build_county_index.py as-is**

```bash
cp /home/administrator/Code/geographica/scripts/pipeline_progress.py ~/Code/geographica-companion/pipelines/
cp /home/administrator/Code/geographica/scripts/build_county_index.py ~/Code/geographica-companion/pipelines/
```

- [ ] **Step 2: Adapt acquire_imagery.py**

Copy from main repo, then apply all required adaptations:

1. Remove `os.setsid` / `os.killpg` (orchestrator manages process lifecycle)
2. Remove `["nice", "-n", "19"] +` prefix from GDAL subprocess commands
3. Replace `/dev/stdout` with `/vsistdout/` in ogr2ogr calls
4. Remove `Path("/secrets")` credential loading
5. Remove `_cancel_requested` global and `_handle_sigterm` function
6. Remove `_child_pid` global
7. Remove `signal.signal(signal.SIGTERM, ...)` at module level
8. Change state file from `.pipeline-state.json` to `.{mode}-state.json`
9. Remove/guard `from tileserver_config import ...`
10. Change default `--staging` from `/data/staging_imagery` to `./staging_imagery`

- [ ] **Step 3: Adapt acquire_naip.py**

Copy and apply: remove `nice`, remove globals/signal handlers, unique state file `.naip-state.json`.

- [ ] **Step 4: Adapt acquire_sentinel.py**

Copy and apply: remove `nice`, remove `/secrets`, remove globals/signal handlers, unique state file `.sentinel-state.json`.

- [ ] **Step 5: Adapt download_elevation.py**

Copy and apply: remove globals/signal handlers. State file already unique (`.elevation-state.json`).

- [ ] **Step 6: Adapt import_imagery.py**

Copy and apply: remove `/data` default, remove tileserver imports, unique state file `.import-state.json`.

- [ ] **Step 7: Verify adapted scripts can import without error**

```bash
cd ~/Code/geographica-companion
python -c "
import importlib, sys
sys.path.insert(0, 'pipelines')
for mod in ['pipeline_progress', 'build_county_index', 'acquire_imagery', 'acquire_naip', 'acquire_sentinel', 'download_elevation', 'import_imagery']:
    try:
        importlib.import_module(mod)
        print(f'OK: {mod}')
    except Exception as e:
        print(f'FAIL: {mod}: {e}')
"
```

Expected: All modules import OK (some may warn about missing GDAL, acceptable).

- [ ] **Step 8: Commit**

```bash
cd ~/Code/geographica-companion
git add pipelines/
git commit -m "feat: adapted pipeline scripts — cross-platform, unique state files, no globals"
```

---

## Task 10: Launchers

**Files:**
- Create: `~/Code/geographica-companion/companion.sh`
- Create: `~/Code/geographica-companion/companion.bat`
- Create: `~/Code/geographica-companion/companion.desktop`

- [ ] **Step 1: Create companion.sh (Linux launcher)**

Bash script with `set -euo pipefail`. Checks Python 3.10+ via `python3 --version`, creates venv if needed, installs deps, sets GDAL env vars if bundled binaries exist, falls back to system GDAL, runs `python3 companion.py`.

- [ ] **Step 2: Create companion.bat (Windows launcher)**

Batch script. Checks `py -3 --version` first (Windows Python Launcher), falls back to `python --version`, validates 3.10+. Creates venv with `Scripts\activate.bat`. Sets `PATH`, `PROJ_LIB`, `GDAL_DATA` for bundled GDAL. Runs `python companion.py`.

- [ ] **Step 3: Create companion.desktop (Linux desktop entry)**

Freedesktop `.desktop` file that launches `companion.sh` in a terminal.

- [ ] **Step 4: Set execute permissions and commit**

```bash
cd ~/Code/geographica-companion
chmod +x companion.sh companion.desktop
git add companion.sh companion.bat companion.desktop
git commit -m "feat: cross-platform launchers — .sh, .bat, .desktop with Python/GDAL detection"
```

---

## Task 11: GitHub Repository and README

- [ ] **Step 1: Create GitHub repository**

```bash
cd ~/Code/geographica-companion
gh repo create cameronzucker/geographica-companion --public --source=. --push
```

- [ ] **Step 2: Write README.md**

Cover: project description, prerequisites (Python 3.10+), quick start (Linux/Windows), features, architecture, pipeline sources table, transfer methods, GDAL note, license (MIT).

- [ ] **Step 3: Commit and push**

```bash
cd ~/Code/geographica-companion
git add README.md
git commit -m "docs: README with quick start, features, architecture overview"
git push
```

---

## Task 12: Integration Testing and Final Wiring

- [ ] **Step 1: Add pipeline lifecycle integration test**

Add to `tests/test_companion.py`: start a pipeline, verify state endpoint returns data, cancel it.

- [ ] **Step 2: Add disk usage integration test**

Create fake `.mbtiles` file in output dir, verify `GET /api/disk` returns it.

- [ ] **Step 3: Run full test suite**

Run: `cd ~/Code/geographica-companion && python -m pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
cd ~/Code/geographica-companion
git add tests/
git commit -m "test: integration tests for pipeline lifecycle and disk usage"
git push
```

---

## Task 13: Push Main Repo Changes

- [ ] **Step 1: Push tileserver_config.py CLI to main**

```bash
cd /home/administrator/Code/geographica
git checkout main && git merge dev --no-edit && git push origin main && git checkout dev
```

- [ ] **Step 2: Write session handoff memory**

Document what was built in this session for future context.
