"""Subprocess runner with checkpoint management for Geographica setup wizard."""
from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Checkpoint — resumable step tracking
# ---------------------------------------------------------------------------
class Checkpoint:
    """Track completed setup steps in a JSON file for resume support."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._completed: set[str] = set()
        if self._path.exists():
            data = json.loads(self._path.read_text())
            self._completed = set(data.get("completed", []))

    def is_completed(self, step: str) -> bool:
        return step in self._completed

    def mark_completed(self, step: str) -> None:
        self._completed.add(step)
        self._persist()

    def get_completed(self) -> list[str]:
        return sorted(self._completed)

    def reset(self) -> None:
        self._completed.clear()
        if self._path.exists():
            self._path.unlink()

    def _persist(self) -> None:
        self._path.write_text(json.dumps({"completed": sorted(self._completed)}))


# ---------------------------------------------------------------------------
# Command builders — return list[str], NEVER shell strings
# ---------------------------------------------------------------------------
def geofabrik_url(state_slug: str) -> str:
    """Return Geofabrik download URL for a US state slug."""
    return f"https://download.geofabrik.de/north-america/us/{state_slug}-latest.osm.pbf"


def planetiler_cmd(pbf_path: str, output_path: str, heap: str) -> list[str]:
    """Docker run command for Planetiler with volume mounts."""
    pbf = Path(pbf_path)
    output = Path(output_path)
    return [
        "docker", "run", "--rm",
        "-v", f"{pbf.parent}:/data/input",
        "-v", f"{output.parent}:/data/output",
        "-e", f"JAVA_TOOL_OPTIONS=-Xmx{heap}",
        "ghcr.io/onthegomap/planetiler:latest",
        "--force",
        f"--osm-path=/data/input/{pbf.name}",
        f"--output=/data/output/{output.name}",
    ]


def poi_build_cmd(bbox: str, states: str, output: str) -> list[str]:
    """Command to run build_poi_index.py."""
    return [
        "python3", "scripts/build_poi_index.py",
        "--bbox", bbox,
        "--states", states,
        "--output", output,
    ]


def osm_pois_cmd(pbf_path: str, output: str, bbox: str) -> list[str]:
    """Command to run build_osm_pois.py."""
    return [
        "python3", "scripts/build_osm_pois.py",
        "--pbf", pbf_path,
        "--output", output,
        "--bbox", bbox,
    ]


def elevation_cmd(bbox: str, output: str) -> list[str]:
    """Command to run download_elevation.py."""
    return [
        "python3", "scripts/download_elevation.py",
        "--bbox", bbox,
        "--output", output,
    ]


# ---------------------------------------------------------------------------
# Async executor
# ---------------------------------------------------------------------------
_active_processes: list[asyncio.subprocess.Process] = []


async def run_command(
    args: list[str],
    cwd: str,
    on_output: Callable[[str, bytes], None],
    env_extra: Optional[dict[str, str]] = None,
) -> int:
    """Spawn a subprocess and stream output via on_output callback.

    Uses asyncio.create_subprocess_exec (never shell=True).
    Sets PYTHONUNBUFFERED=1 in the subprocess environment.
    Drains stdout and stderr concurrently via separate asyncio tasks.
    Returns the process exit code.
    """
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if env_extra:
        env.update(env_extra)

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=env,
    )
    _active_processes.append(proc)

    async def drain(stream: asyncio.StreamReader, source: str) -> None:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            on_output(source, chunk)

    try:
        await asyncio.gather(
            drain(proc.stdout, "stdout"),
            drain(proc.stderr, "stderr"),
        )
        await proc.wait()
    finally:
        if proc in _active_processes:
            _active_processes.remove(proc)

    return proc.returncode


def shutdown_children() -> None:
    """Send SIGTERM to all active child processes."""
    for proc in list(_active_processes):
        try:
            proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            pass
