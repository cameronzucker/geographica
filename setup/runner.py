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
PLANETILER_VERSION = "0.10.2"


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
        f"ghcr.io/onthegomap/planetiler:{PLANETILER_VERSION}",
        "--force",
        f"--osm-path=/data/input/{pbf.name}",
        f"--output=/data/output/{output.name}",
    ]


def poi_build_cmd_v1(bbox: str, states: str, output: str) -> list[str]:
    """Legacy positional-arg command to run build_poi_index.py (pre-PipelineContext)."""
    return [
        "python3", "scripts/build_poi_index.py",
        "--bbox", bbox,
        "--states", states,
        "--output", output,
    ]


def osm_pois_cmd_v1(pbf_path: str, output: str, bbox: str) -> list[str]:
    """Legacy positional-arg command to run build_osm_pois.py (pre-PipelineContext)."""
    return [
        "python3", "scripts/build_osm_pois.py",
        "--pbf", pbf_path,
        "--output", output,
        "--bbox", bbox,
    ]


def elevation_cmd_v1(bbox: str, output: str) -> list[str]:
    """Legacy positional-arg command to run download_elevation.py (pre-PipelineContext)."""
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


# ---------------------------------------------------------------------------
# Pipeline step command builders (Task 25)
# Each takes ctx: PipelineContext (dict shape — see setup/pipeline_steps.py)
# and returns list[str] suitable for asyncio.create_subprocess_exec / run_command.
# ---------------------------------------------------------------------------

def osm_download_cmd(ctx) -> list[str]:
    """Download Geofabrik state PBFs via a wget for-loop.
    States are hardcoded to the 11 western US the project targets."""
    states = ("arizona california colorado idaho montana nevada "
              "new-mexico oregon utah washington wyoming")
    out = f"{ctx['data_path']}/pbf"
    script = (
        f"set -e; mkdir -p '{out}'; cd '{out}'; "
        f"for s in {states}; do "
        f"  wget -c --no-verbose "
        f"  \"https://download.geofabrik.de/north-america/us/${{s}}-latest.osm.pbf\"; "
        f"done"
    )
    return ["bash", "-c", script]


def osm_merge_cmd(ctx) -> list[str]:
    """Merge all state PBFs into western-us.osm.pbf."""
    out = f"{ctx['data_path']}/pbf"
    return [
        "bash", "-c",
        f"set -e; cd '{out}' && osmium merge *-latest.osm.pbf "
        f"-o western-us.osm.pbf --overwrite",
    ]


def osm_copy_cmd(ctx) -> list[str]:
    """Stage OSM PBF into valhalla/ subdir for the valhalla container."""
    src = f"{ctx['data_path']}/pbf/western-us.osm.pbf"
    dst_dir = f"{ctx['data_path']}/valhalla"
    return [
        "bash", "-c",
        f"set -e; mkdir -p '{dst_dir}' && cp '{src}' '{dst_dir}/western-us.osm.pbf'",
    ]


def planetiler_pull_cmd(ctx=None) -> list[str]:
    return ["docker", "pull", f"ghcr.io/onthegomap/planetiler:{PLANETILER_VERSION}"]


def planetiler_build_cmd(ctx) -> list[str]:
    return [
        "docker", "run", "--rm",
        "-v", f"{ctx['data_path']}:/data",
        f"ghcr.io/onthegomap/planetiler:{PLANETILER_VERSION}",
        "--area=custom",
        "--osm-path=/data/pbf/western-us.osm.pbf",
        "--output=/data/basemap.mbtiles",
        "--force",
    ]


def poi_build_cmd(ctx) -> list[str]:
    return [
        "python3", f"{ctx['scripts_path']}/build_poi_index.py",
        "--bbox", ctx.get("layer_bbox", {}).get("basemap") or ctx["bbox"],
        "--output", f"{ctx['data_path']}/poi.sqlite",
    ]


def osm_pois_cmd(ctx) -> list[str]:
    return [
        "python3", f"{ctx['scripts_path']}/build_osm_pois.py",
        "--pbf", f"{ctx['data_path']}/pbf/western-us.osm.pbf",
        "--output", f"{ctx['data_path']}/poi.sqlite",
        "--bbox", ctx.get("layer_bbox", {}).get("basemap") or ctx["bbox"],
    ]


def public_lands_cmd(ctx) -> list[str]:
    return [
        "python3", f"{ctx['scripts_path']}/build_public_lands.py",
        "--bbox", ctx.get("layer_bbox", {}).get("basemap") or ctx["bbox"],
        "--output", f"{ctx['data_path']}/public_lands.mbtiles",
        "--cache-dir", f"{ctx['data_path']}/cache/public_lands",
    ]


def elevation_cmd(ctx) -> list[str]:
    return [
        "python3", f"{ctx['scripts_path']}/download_elevation.py",
        "--bbox", ctx.get("layer_bbox", {}).get("basemap") or ctx["bbox"],
        "--zoom", "0-14",
        "--output", f"{ctx['data_path']}/elevation.mbtiles",
    ]


def base_imagery_cmd(ctx) -> list[str]:
    """Dispatch on ctx['layers']['base_imagery'] in {naip, sentinel, noaa, tnmaccess}."""
    source = ctx["layers"]["base_imagery"]
    if source == "skip":
        raise ValueError("base_imagery_cmd invoked with source='skip' — filter_active_steps should have removed this step")
    bbox = ctx.get("layer_bbox", {}).get("base_imagery") or ctx["bbox"]
    output = f"{ctx['data_path']}/imagery.mbtiles"
    zoom = ctx.get("base_imagery_zoom", 15)
    if source == "sentinel":
        return [
            "python3", f"{ctx['scripts_path']}/acquire_sentinel.py",
            "--bbox", bbox, "--zoom", str(zoom), "--output", output,
        ]
    # naip / noaa / tnmaccess all use acquire_imagery.py with --mode
    return [
        "python3", f"{ctx['scripts_path']}/acquire_imagery.py",
        "--mode", source, "--bbox", bbox,
        "--zoom", f"0-{zoom}", "--output", output,
    ]


def detail_imagery_cmd(ctx) -> list[str]:
    """Dispatch on ctx['layers']['detail_imagery'] in {m2m, copernicus}."""
    source = ctx["layers"]["detail_imagery"]
    if source == "skip":
        raise ValueError("detail_imagery_cmd invoked with source='skip' — filter_active_steps bug")
    bbox = ctx.get("layer_bbox", {}).get("detail_imagery") or ctx["bbox"]
    output = f"{ctx['data_path']}/imagery_detail.mbtiles"
    if source == "copernicus":
        return [
            "python3", f"{ctx['scripts_path']}/acquire_sentinel.py",
            "--bbox", bbox, "--detail", "--output", output,
        ]
    return [
        "python3", f"{ctx['scripts_path']}/acquire_imagery.py",
        "--mode", "m2m", "--bbox", bbox, "--output", output,
    ]


def fonts_cmd(ctx) -> list[str]:
    dst = "tileserver/fonts-served"
    return [
        "bash", "-c",
        f"set -e; mkdir -p '{dst}' && cd '{dst}' && "
        f"wget -q -O fonts.zip "
        f"'https://github.com/openmaptiles/fonts/releases/download/v2.0/fonts.zip' && "
        f"unzip -o -q fonts.zip && rm fonts.zip",
    ]


def styles_cmd(ctx) -> list[str]:
    return [
        "bash", "-c",
        "set -e; "
        "for style in positron dark-matter; do "
        "  mkdir -p tileserver/styles/$style/icons; "
        "  git clone --depth=1 "
        "    https://github.com/openmaptiles/$style-gl-style.git "
        "    /tmp/$style-style-$$; "
        "  cp -r /tmp/$style-style-$$/icons/* tileserver/styles/$style/icons/ || true; "
        "  rm -rf /tmp/$style-style-$$; "
        "done",
    ]


def docker_build_cmd(ctx=None) -> list[str]:
    return ["docker", "compose", "build"]
