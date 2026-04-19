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
            try:
                data = json.loads(self._path.read_text())
                self._completed = set(data.get("completed", []))
            except (json.JSONDecodeError, OSError):
                # Corrupt or unreadable — start fresh rather than crash.
                self._completed = set()

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
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps({"completed": sorted(self._completed)}))
        os.replace(str(tmp), str(self._path))


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
        start_new_session=True,
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
    """Best-effort: send SIGTERM to each active child's process group.

    Using start_new_session=True on create_subprocess_exec means each child
    owns its own process group; killpg propagates SIGTERM to grandchildren too.
    Falls back to per-process kill if killpg fails (e.g. already reaped).
    """
    for proc in list(_active_processes):
        if proc.returncode is not None:
            continue
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass


# ---------------------------------------------------------------------------
# Pipeline step command builders (Task 25)
# Each takes ctx: PipelineContext (dict shape — see setup/pipeline_steps.py)
# and returns list[str] suitable for asyncio.create_subprocess_exec / run_command.
# ---------------------------------------------------------------------------

# Axis-aligned bboxes for each Geofabrik state extract the project supports.
# Source: US Census TIGER bboxes, rounded out. Values are intentionally
# slightly larger than the true state boundary so that a user bbox that
# scrapes a state edge still matches — losing a few POIs to a missing state
# is worse than the cost of one extra state download.
#
# Format: (west, south, east, north) in decimal degrees.
# Keys must match Geofabrik's filename stems (e.g., `new-mexico` not `new_mexico`).
STATE_BBOXES: dict[str, tuple[float, float, float, float]] = {
    "arizona":      (-114.82, 31.33, -109.05, 37.00),
    "california":   (-124.48, 32.53, -114.13, 42.01),
    "colorado":     (-109.06, 37.00, -102.04, 41.00),
    "idaho":        (-117.24, 41.99, -111.05, 49.00),
    "montana":      (-116.05, 44.36, -104.04, 49.00),
    "nevada":       (-120.01, 35.00, -114.04, 42.00),
    "new-mexico":   (-109.05, 31.33, -103.00, 37.00),
    "oregon":       (-124.57, 41.99, -116.46, 46.29),
    "utah":         (-114.05, 37.00, -109.04, 42.00),
    "washington":   (-124.77, 45.54, -116.92, 49.00),
    "wyoming":      (-111.06, 40.99, -104.05, 45.01),
}


def _states_intersecting(bbox_str: str) -> list[str]:
    """Return the subset of STATE_BBOXES that overlap ``bbox_str``.

    ``bbox_str`` is the Geographica-canonical ``"west,south,east,north"``
    form. Return order is the insertion order of ``STATE_BBOXES`` (stable).

    Behavior on pathological input:
    - Malformed bbox (not 4 parseable floats) → return ALL states.
    - Empty string → return ALL states.
    - Valid bbox that doesn't overlap any of the 11 western states
      (e.g. New York) → return ALL states.

    The fallback choice is deliberately conservative: a silent "downloaded
    nothing" would leave valhalla/planetiler with an empty PBF and fail
    opaquely further down. Downloading the full set and letting the user
    see the extra time lets them correct their bbox before the pipeline
    commits more minutes to downstream work.

    Context for the feature: the 2026-04-20 beta tester picked a tiny
    area in Phoenix and saw all 11 western-US state extracts download —
    ~4 GB of bandwidth for data the pipeline wouldn't use. Before the
    fix, osm_download_cmd had the state list hard-coded.
    """
    try:
        parts = [p.strip() for p in bbox_str.split(",")]
        if len(parts) != 4:
            return list(STATE_BBOXES.keys())
        w, s, e, n = (float(x) for x in parts)
    except (ValueError, AttributeError):
        return list(STATE_BBOXES.keys())

    matching: list[str] = []
    for state, (sw, ss, se, sn) in STATE_BBOXES.items():
        # Axis-aligned bbox intersection.
        if sw <= e and se >= w and ss <= n and sn >= s:
            matching.append(state)

    if not matching:
        return list(STATE_BBOXES.keys())
    return matching


def osm_download_cmd(ctx) -> list[str]:
    """Download Geofabrik state PBFs with MD5 + structural verification.

    Only downloads states whose bbox intersects ``ctx['bbox']`` (see
    ``_states_intersecting``). This makes a "tiny Phoenix" bbox pull
    ~800 MB (Arizona alone) instead of ~4 GB (all 11 western states) —
    the 2026-04-20 beta report.

    Each state's .pbf is checked against Geofabrik's published .md5 and
    structurally validated with `osmium fileinfo` before we move on. A
    truncated or corrupt download is deleted and retried, up to 3
    attempts per state. On persistent failure the error names the
    offending state so a beta tester can surgically recover.

    Context for why this isn't just `wget -c`: the 2026-04-19 beta
    report was `[ERROR] Merge OSM extracts: PBF error: invalid
    BlobHeader size (> max_blob_header_size)` — `wget -c` had resumed
    into a truncated file from a dropped connection and left a PBF
    that md5 would have flagged but the download step didn't check.
    The merge step then blew up with no indication of WHICH file was
    corrupt. Now: verify at download-time, name the state on failure.
    """
    states = " ".join(_states_intersecting(ctx.get("bbox", "")))
    out = f"{ctx['data_path']}/pbf"
    url_base = "https://download.geofabrik.de/north-america/us"
    script = (
        f"set -eu\n"
        f"mkdir -p '{out}'\n"
        f"cd '{out}'\n"
        f"URL_BASE='{url_base}'\n"
        f"STATES='{states}'\n"
        f"MAX_ATTEMPTS=3\n"
        f'\n'
        f'download_and_verify() {{\n'
        f'  local s=$1\n'
        f'  local pbf="${{s}}-latest.osm.pbf"\n'
        f'  local md5file="${{pbf}}.md5"\n'
        f'  local attempt\n'
        f'  for attempt in $(seq 1 $MAX_ATTEMPTS); do\n'
        f'    echo "${{s}}: download attempt ${{attempt}}/${{MAX_ATTEMPTS}}"\n'
        f'    if ! wget -c --no-verbose --tries=2 --timeout=60 '
        f'"${{URL_BASE}}/${{pbf}}"; then\n'
        f'      echo "${{s}}: wget failed, removing partial and retrying"\n'
        f'      rm -f "$pbf"\n'
        f'      continue\n'
        f'    fi\n'
        f'    # Always refetch the .md5 (it is small + must match the current .pbf)\n'
        f'    if ! wget -q -O "$md5file" "${{URL_BASE}}/${{pbf}}.md5"; then\n'
        f'      echo "${{s}}: .md5 fetch failed, retrying"\n'
        f'      rm -f "$md5file" "$pbf"\n'
        f'      continue\n'
        f'    fi\n'
        f'    # md5sum --check expects "<hash>  <filename>" format, which\n'
        f'    # geofabrik already provides. Run --status for quiet mode.\n'
        f'    if ! md5sum --check --status "$md5file" 2>/dev/null; then\n'
        f'      echo "${{s}}: md5 mismatch (attempt ${{attempt}}) — redownloading"\n'
        f'      rm -f "$pbf" "$md5file"\n'
        f'      continue\n'
        f'    fi\n'
        f'    # Structural backstop. Cheap; catches the rare "md5 matches a\n'
        f'    # file that osmium still cannot parse" case.\n'
        f'    if ! osmium fileinfo --extended=false "$pbf" >/dev/null 2>&1; then\n'
        f'      echo "${{s}}: fileinfo failed despite matching md5 — redownloading"\n'
        f'      rm -f "$pbf" "$md5file"\n'
        f'      continue\n'
        f'    fi\n'
        f'    echo "${{s}}: OK (attempt ${{attempt}})"\n'
        f'    return 0\n'
        f'  done\n'
        f'  echo "ERROR: ${{s}}: PBF integrity check failed after '
        f'${{MAX_ATTEMPTS}} attempts — check network / Geofabrik mirror" >&2\n'
        f'  return 1\n'
        f'}}\n'
        f'\n'
        f'for s in $STATES; do\n'
        f'  download_and_verify "$s" || exit 1\n'
        f'done\n'
    )
    return ["bash", "-c", script]


def osm_merge_cmd(ctx) -> list[str]:
    """Merge bbox-relevant state PBFs into western-us.osm.pbf.

    Uses the SAME bbox → state list as osm_download_cmd (see
    ``_states_intersecting``). This avoids a subtle footgun: if a prior
    run downloaded all 11 states and the current run only needs Arizona,
    a glob-based merge would drag 10 stale PBFs into the merged file and
    bloat the input for valhalla/planetiler downstream. Explicitly
    enumerating the current run's state files keeps the merge scoped
    to this run's bbox.

    Pre-validates each PBF with `osmium fileinfo` so the error message
    names the specific corrupt file + the exact `rm` command to recover.
    Without this, `osmium merge` fails with an opaque "invalid BlobHeader
    size" and the user has to delete all PBFs blind (the beta tester's
    2026-04-19 experience).
    """
    out = f"{ctx['data_path']}/pbf"
    state_files = [f"{s}-latest.osm.pbf"
                   for s in _states_intersecting(ctx.get("bbox", ""))]
    # Quote each file name for the bash for-loop; all names are ASCII
    # identifier-safe so no escaping surprises.
    files_sh = " ".join(f"'{f}'" for f in state_files)
    script = (
        f"set -eu\n"
        f"cd '{out}'\n"
        f"FILES=({files_sh})\n"
        f'\n'
        f'# Pre-validate every input so the error message is actionable.\n'
        f'for f in "${{FILES[@]}}"; do\n'
        f'  if ! osmium fileinfo --extended=false "$f" >/dev/null 2>&1; then\n'
        f'    echo "ERROR: corrupt PBF: {out}/${{f}}" >&2\n'
        f'    echo "  Recover with:" >&2\n'
        f'    echo "    rm \'{out}/\'${{f}} \'{out}/\'${{f}}.md5" >&2\n'
        f'    echo "    rm \'{ctx["data_path"]}/.setup_checkpoint.json\'" >&2\n'
        f'    echo "    ./setup.sh   # re-runs the wizard; download step will refetch" >&2\n'
        f'    exit 1\n'
        f'  fi\n'
        f'done\n'
        f'\n'
        f'osmium merge "${{FILES[@]}}" -o western-us.osm.pbf --overwrite\n'
    )
    return ["bash", "-c", script]


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
    """Build the basemap vector-tiles MBTiles via Planetiler/OpenMapTiles.

    `--download` is REQUIRED on any fresh Pi. Planetiler's OpenMapTiles
    profile depends on auxiliary shapefile sources (lake centerlines,
    water polygons, natural-earth) stored under `data/sources/` inside
    the Planetiler container. On first run these don't exist yet; with
    `--download`, Planetiler fetches them from OpenStreetMap / Natural
    Earth / OSMdata on demand (~1 GB) and caches them for subsequent
    runs. Without the flag it aborts with

        Exception in thread "main"
        java.io.FileNotFoundException:
        data/sources/lake_centerline.shp.zip does not exist.
        Run with --download to fetch it.

    2026-04-20 beta tester hit exactly that — the internal dev Pi had
    cached sources from an old run so the flag's absence wasn't
    observable internally.

    `--download-threads=4` is a conservative default; heavier machines
    can override via the PIPELINE tuning path, but the Pi's network is
    usually the bottleneck so more threads don't help.
    """
    return [
        "docker", "run", "--rm",
        "-v", f"{ctx['data_path']}:/data",
        f"ghcr.io/onthegomap/planetiler:{PLANETILER_VERSION}",
        "--area=custom",
        "--osm-path=/data/pbf/western-us.osm.pbf",
        "--output=/data/basemap.mbtiles",
        "--download",
        "--download-threads=4",
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
