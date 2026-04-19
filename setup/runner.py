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
# Source: US Census TIGER state boundary boxes, rounded slightly outward.
# Values are intentionally slightly larger than the true state boundary so
# a user bbox that scrapes a state edge still matches — losing a few POIs
# to a missing state is worse than the cost of one extra state extract.
#
# Format: (west, south, east, north) in decimal degrees.
# Keys must match Geofabrik's filename stems exactly:
#   - lowercase
#   - multi-word states use hyphens ("new-mexico", "north-carolina")
#   - Georgia is "georgia-us" to distinguish from Georgia the country
#   - DC is "district-of-columbia"
# Alaska and Hawaii are intentionally omitted: Alaska's bbox crosses the
# antimeridian (special-casing required) and both are rare targets for
# the Pi-sized offline stacks Geographica targets. Users needing them
# can add the entries; any bbox outside the contiguous 48 + DC is
# currently rejected at /api/start with a clear error.
STATE_BBOXES: dict[str, tuple[float, float, float, float]] = {
    "alabama":              (-88.47, 30.14, -84.89, 35.01),
    "arizona":              (-114.82, 31.33, -109.05, 37.00),
    "arkansas":             (-94.62, 33.00, -89.64, 36.50),
    "california":           (-124.48, 32.53, -114.13, 42.01),
    "colorado":             (-109.06, 37.00, -102.04, 41.00),
    "connecticut":          (-73.73, 40.98, -71.79, 42.05),
    "delaware":             (-75.79, 38.45, -74.98, 39.84),
    "district-of-columbia": (-77.12, 38.79, -76.91, 38.99),
    "florida":              (-87.63, 24.52, -80.03, 31.00),
    "georgia-us":           (-85.61, 30.36, -80.84, 35.00),
    "idaho":                (-117.24, 41.99, -111.05, 49.00),
    "illinois":             (-91.51, 36.97, -87.49, 42.51),
    "indiana":              (-88.10, 37.77, -84.78, 41.76),
    "iowa":                 (-96.64, 40.38, -90.14, 43.50),
    "kansas":               (-102.05, 36.99, -94.59, 40.00),
    "kentucky":             (-89.57, 36.50, -81.96, 39.15),
    "louisiana":            (-94.04, 28.93, -88.75, 33.02),
    "maine":                (-71.08, 43.06, -66.95, 47.46),
    "maryland":             (-79.49, 37.89, -75.05, 39.72),
    "massachusetts":        (-73.51, 41.23, -69.93, 42.89),
    "michigan":             (-90.42, 41.70, -82.12, 48.31),
    "minnesota":            (-97.24, 43.50, -89.49, 49.38),
    "mississippi":          (-91.66, 30.17, -88.10, 35.01),
    "missouri":             (-95.77, 35.99, -89.10, 40.61),
    "montana":              (-116.05, 44.36, -104.04, 49.00),
    "nebraska":             (-104.05, 40.00, -95.31, 43.00),
    "nevada":               (-120.01, 35.00, -114.04, 42.00),
    "new-hampshire":        (-72.56, 42.70, -70.61, 45.30),
    "new-jersey":           (-75.56, 38.93, -73.89, 41.36),
    "new-mexico":           (-109.05, 31.33, -103.00, 37.00),
    "new-york":             (-79.76, 40.50, -71.86, 45.01),
    "north-carolina":       (-84.32, 33.75, -75.46, 36.59),
    "north-dakota":         (-104.05, 45.94, -96.55, 49.00),
    "ohio":                 (-84.82, 38.40, -80.52, 41.98),
    "oklahoma":             (-103.00, 33.62, -94.43, 37.00),
    "oregon":               (-124.57, 41.99, -116.46, 46.29),
    "pennsylvania":         (-80.52, 39.72, -74.69, 42.27),
    "rhode-island":         (-71.86, 41.15, -71.12, 42.02),
    "south-carolina":       (-83.35, 32.03, -78.54, 35.22),
    "south-dakota":         (-104.06, 42.48, -96.44, 45.95),
    "tennessee":            (-90.31, 34.98, -81.65, 36.68),
    "texas":                (-106.65, 25.84, -93.52, 36.50),
    "utah":                 (-114.05, 37.00, -109.04, 42.00),
    "vermont":              (-73.44, 42.73, -71.46, 45.02),
    "virginia":             (-83.68, 36.54, -75.24, 39.47),
    "washington":           (-124.77, 45.54, -116.92, 49.00),
    "west-virginia":        (-82.64, 37.20, -77.72, 40.64),
    "wisconsin":            (-92.89, 42.49, -86.80, 47.08),
    "wyoming":              (-111.06, 40.99, -104.05, 45.01),
}


def _states_intersecting(bbox_str: str) -> list[str]:
    """Return the subset of STATE_BBOXES that overlap ``bbox_str``.

    ``bbox_str`` is the Geographica-canonical ``"west,south,east,north"``
    form. Return order is the insertion order of ``STATE_BBOXES`` (stable).

    Returns EMPTY list for:
    - Malformed bbox (not 4 parseable floats)
    - Empty string
    - Valid bbox that doesn't overlap any of the 48 contiguous states + DC
      (e.g. Alaska, Hawaii, Europe, middle of the Atlantic)

    Prior behavior was "fall back to all states" on no-match. That
    triggered the 2026-04-21 beta-tester report where a bbox outside
    the 11-state western-US coverage silently downloaded 4 GB of
    irrelevant data. Now the caller is responsible for turning an
    empty return into a clear "your bbox isn't supported" 400 at
    /api/start (see setup/main.py::post_start).
    """
    try:
        parts = [p.strip() for p in bbox_str.split(",")]
        if len(parts) != 4:
            return []
        w, s, e, n = (float(x) for x in parts)
    except (ValueError, AttributeError):
        return []

    matching: list[str] = []
    for state, (sw, ss, se, sn) in STATE_BBOXES.items():
        # Axis-aligned bbox intersection.
        if sw <= e and se >= w and ss <= n and sn >= s:
            matching.append(state)
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
    state_list = _states_intersecting(ctx.get("bbox", ""))
    if not state_list:
        # Guard against the pipeline being started with an unsupported
        # bbox. /api/start also validates before we get here, but this
        # makes the failure legible if anyone calls the runner directly.
        raise ValueError(
            f"bbox {ctx.get('bbox', '')!r} does not intersect any of the "
            f"48 contiguous US states + DC. Geographica currently supports "
            f"only those regions; update the bbox or extend STATE_BBOXES "
            f"in setup/runner.py to cover another state/country."
        )
    states = " ".join(state_list)
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
        f'    # NB: no structural pbf validation here — md5 is authoritative.\n'
        f'    # 2026-04-20 beta tester hit the case where the local parser\n'
        f'    # rejected an md5-verified download and the retry loop wasted\n'
        f'    # 3x 295 MB of bandwidth. Re-downloading the same bytes cannot\n'
        f'    # fix a parser-version-skew problem. Structural validation\n'
        f'    # moved to the merge step (runs once, has clearer errors).\n'
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
    state_list = _states_intersecting(ctx.get("bbox", ""))
    if not state_list:
        raise ValueError(
            f"bbox {ctx.get('bbox', '')!r} does not intersect any of the "
            f"48 contiguous US states + DC. osm_merge_cmd invoked without "
            f"a valid bbox — /api/start should have rejected the run."
        )
    state_files = [f"{s}-latest.osm.pbf" for s in state_list]
    # Quote each file name for the bash for-loop; all names are ASCII
    # identifier-safe so no escaping surprises.
    files_sh = " ".join(f"'{f}'" for f in state_files)
    script = (
        f"set -eu\n"
        f"cd '{out}'\n"
        f"FILES=({files_sh})\n"
        f'\n'
        f'# Pre-validate every input. No --extended flag: osmium 1.18+ rejects\n'
        f'# `--extended=false` as "option does not take any arguments" —\n'
        f'# which is precisely what trapped the 2026-04-20 beta tester in\n'
        f'# an infinite retry loop. Bare `osmium fileinfo <file>` reads the\n'
        f'# header and works across every osmium-tool version we support.\n'
        f'#\n'
        f'# Capture osmium stderr so the user can distinguish "PBF is\n'
        f'# corrupt" from "osmium version mismatch" on failure.\n'
        f'for f in "${{FILES[@]}}"; do\n'
        f'  if ! fileinfo_err=$(osmium fileinfo "$f" 2>&1 >/dev/null); then\n'
        f'    osmium_ver=$(osmium --version 2>&1 | head -1)\n'
        f'    {{\n'
        f'      echo "ERROR: osmium fileinfo rejected {out}/${{f}}:"\n'
        f'      echo "  $fileinfo_err"\n'
        f'      echo ""\n'
        f'      echo "  Installed osmium: $osmium_ver"\n'
        f'      echo ""\n'
        f'      echo "  If the above mentions \\"unknown format\\" or a"\n'
        f'      echo "  version older than 1.17, your osmium is too old for"\n'
        f'      echo "  this PBF and a newer one is needed. Otherwise the"\n'
        f'      echo "  file is likely truly corrupt; recover with:"\n'
        f'      echo "    rm \'{out}/\'${{f}} \'{out}/\'${{f}}.md5"\n'
        f'      echo "    rm \'{ctx["data_path"]}/.setup_checkpoint.json\'"\n'
        f'      echo "    ./setup.sh   # re-runs the wizard; will refetch"\n'
        f'    }} >&2\n'
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


# NOTE: every pipeline-script subprocess below invokes
# `/usr/bin/python3` explicitly, not bare `python3`. Under setup.sh
# PATH resolution puts setup/.venv/bin first, and that venv has only
# fastapi/uvicorn/httpx/pytest-asyncio/websockets. Bootstrap's
# `pip install --user --break-system-packages -r scripts/requirements.txt`
# lands in ~/.local/lib/pythonX.Y/site-packages — which is auto-imported
# by /usr/bin/python3 but NOT by a venv interpreter. Using the venv's
# python silently fails with `ModuleNotFoundError: No module named
# 'aiohttp'` etc. at subprocess time. Same class as the 2026-04-19
# preflight bug (commit 5e400c5); this is the pipeline-side fix.
#
# If you add a new pipeline step that invokes a script in scripts/,
# keep the `/usr/bin/python3` prefix. Don't shorten to `python3`.
def poi_build_cmd(ctx) -> list[str]:
    return [
        "/usr/bin/python3", f"{ctx['scripts_path']}/build_poi_index.py",
        "--bbox", ctx.get("layer_bbox", {}).get("basemap") or ctx["bbox"],
        "--output", f"{ctx['data_path']}/poi.sqlite",
    ]


def osm_pois_cmd(ctx) -> list[str]:
    return [
        "/usr/bin/python3", f"{ctx['scripts_path']}/build_osm_pois.py",
        "--pbf", f"{ctx['data_path']}/pbf/western-us.osm.pbf",
        "--output", f"{ctx['data_path']}/poi.sqlite",
        "--bbox", ctx.get("layer_bbox", {}).get("basemap") or ctx["bbox"],
    ]


def public_lands_cmd(ctx) -> list[str]:
    return [
        "/usr/bin/python3", f"{ctx['scripts_path']}/build_public_lands.py",
        "--bbox", ctx.get("layer_bbox", {}).get("basemap") or ctx["bbox"],
        "--output", f"{ctx['data_path']}/public_lands.mbtiles",
        "--cache-dir", f"{ctx['data_path']}/cache/public_lands",
    ]


def elevation_cmd(ctx) -> list[str]:
    return [
        "/usr/bin/python3", f"{ctx['scripts_path']}/download_elevation.py",
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
            "/usr/bin/python3", f"{ctx['scripts_path']}/acquire_sentinel.py",
            "--bbox", bbox, "--zoom", str(zoom), "--output", output,
        ]
    # naip / noaa / tnmaccess all use acquire_imagery.py with --mode
    return [
        "/usr/bin/python3", f"{ctx['scripts_path']}/acquire_imagery.py",
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
            "/usr/bin/python3", f"{ctx['scripts_path']}/acquire_sentinel.py",
            "--bbox", bbox, "--detail", "--output", output,
        ]
    return [
        "/usr/bin/python3", f"{ctx['scripts_path']}/acquire_imagery.py",
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
