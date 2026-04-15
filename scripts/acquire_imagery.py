#!/usr/bin/env python3
"""Download USGS orthoimagery and convert to MBTiles.

Three modes:
  tnmaccess  - Query TNMAccess API for NAIP/Topo GeoTIFFs, then convert via GDAL.
  direct     - Scrape tiles from the USGS cached tile service into MBTiles.
  m2m        - Query USGS M2M API for NAIP scenes, download GeoTIFFs, convert via GDAL.

Usage examples:
  python acquire_imagery.py --mode tnmaccess --bbox "-124.6,31.2,-103.0,42.2" --output data/imagery.mbtiles
  python acquire_imagery.py --mode direct --bbox "-124.6,31.2,-103.0,42.2" --zoom 0-14 --output data/imagery.mbtiles
  python acquire_imagery.py --mode m2m --bbox "-124.8,31.3,-102.0,49.0" --m2m-username user --m2m-token token --output data/imagery_m2m.mbtiles
"""

import argparse
import asyncio
import hashlib
import json
import logging
import math
import os
import signal
import sqlite3
import struct
import subprocess
import sys
import time
from pathlib import Path

import aiohttp
import aiosqlite
from tqdm import tqdm
from pipeline_progress import update_progress as _generic_progress

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TNM_API = "https://tnmaccess.nationalmap.gov/api/v1/products"
M2M_API = "https://m2m.cr.usgs.gov/api/api/json/stable/"
DEFAULT_BBOX = "-124.8,31.3,-102.0,49.0"
DEFAULT_DATASET = "USDA National Agriculture Imagery Program (NAIP)"
USGS_TILE_URL = (
    "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/"
    "MapServer/tile/{z}/{y}/{x}"
)
NATIONALMAP_EXPORT_URL = (
    "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/"
    "ImageServer/exportImage"
)

# ---------------------------------------------------------------------------
# NOAA Digital Coast NAIP — catalog and helpers
# ---------------------------------------------------------------------------
NOAA_BLOB_BASE = "https://coastalimagery.blob.core.windows.net/digitalcoast"

NOAA_NAIP_CATALOG = {
    ("AZ", 2021): "AZ_NAIP_2021_9596",
    # Additional states to be populated via NOAA Data Access Viewer
}

NOAA_TILE_SIZE_MB = 486  # approximate size of each NAIP quad GeoTIFF


def noaa_blob_base_url(state: str, year: int) -> str:
    """Return the Azure blob base URL for a state/year NAIP dataset."""
    dir_name = NOAA_NAIP_CATALOG[(state, year)]
    return f"{NOAA_BLOB_BASE}/{dir_name}"


def noaa_cache_dir(data_dir: Path, state: str, year: int) -> Path:
    """Return the local cache directory for NOAA shapefiles."""
    return data_dir / "noaa_cache" / f"{state}_{year}"


def filter_tiles_by_bbox(
    shapefile_path: Path,
    west: float, south: float, east: float, north: float,
) -> list[str]:
    """Use ogr2ogr to spatially filter a tile index shapefile.

    Returns list of GeoTIFF filenames whose footprints intersect the bbox.
    """
    result = subprocess.run(
        [
            "ogr2ogr", "-f", "CSV", "/dev/stdout",
            str(shapefile_path),
            "-spat", str(west), str(south), str(east), str(north),
            "-select", "filename",
        ],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        log.error("ogr2ogr spatial filter failed: %s", result.stderr)
        return []

    lines = result.stdout.strip().split("\n")
    if len(lines) <= 1:
        return []

    # With -select filename, output is: "filename\nfile1.tif\nfile2.tif\n..."
    filenames = []
    for line in lines[1:]:
        fname = line.strip().strip('"')
        if fname.endswith(".tif"):
            filenames.append(fname)
    return filenames


def nationalmap_tile_url(z: int, x: int, y: int) -> str:
    """Convert z/x/y tile coordinates to an ImageServer exportImage URL.

    Computes the WGS84 bounding box for the given web mercator tile and
    returns a URL that requests a 256x256 JPEG from the USGS NAIP ImageServer.
    """
    n = 2 ** z
    west = x / n * 360 - 180
    east = (x + 1) / n * 360 - 180
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return (
        f"{NATIONALMAP_EXPORT_URL}?bbox={west},{south},{east},{north}"
        f"&bboxSR=4326&size=256,256&imageSR=4326&format=jpgpng&f=image"
    )


MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds, doubled each attempt

# ---------------------------------------------------------------------------
# Cancellation + Structured Progress
# ---------------------------------------------------------------------------
_cancel_requested = False
_child_pid = None  # Track subprocess PID for immediate cancellation


def _handle_sigterm(signum, frame):
    """Handle SIGTERM for graceful shutdown (docker stop).

    Kills any running child subprocess immediately so we don't have to
    wait for a 60-90s GDAL operation to finish before the signal handler
    can run.
    """
    global _cancel_requested
    log.info("SIGTERM received — cancelling immediately")
    _cancel_requested = True
    # Kill the child process if one is running
    if _child_pid:
        try:
            os.killpg(os.getpgid(_child_pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass


signal.signal(signal.SIGTERM, _handle_sigterm)


def write_pipeline_state(output_path: Path, state: dict):
    """Atomically merge pipeline state JSON for the admin monitor.

    Thin backward-compat wrapper: merges the given state dict into the
    existing .pipeline-state.json atomically.  New code should prefer
    calling update_progress() or _generic_progress() directly.
    """
    state_path = Path(output_path).parent / ".pipeline-state.json"
    tmp_path = state_path.with_suffix(".json.tmp")
    try:
        existing: dict = {}
        if state_path.exists():
            try:
                existing = json.loads(state_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        existing.update(state)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(existing, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(state_path))
    except Exception as exc:
        log.warning("Failed to write pipeline state: %s", exc)


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically via tmp + fsync + rename."""
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp), str(path))


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
    For M2M mode: phase + geotiffs fields are primary during downloading;
    tiles_done/tiles_total during converting phase.

    Delegates to the shared pipeline_progress module for the atomic write,
    then enriches the state file with backward-compat fields so that both
    old and new frontend/backend consumers can render progress correctly.
    """
    state_path = Path(output_path).parent / ".pipeline-state.json"

    # Map old params to generic format.
    # During M2M downloading phase, geotiffs are the primary unit of work.
    if phase == "downloading" and geotiffs_total is not None:
        items_done_val = geotiffs_downloaded or 0
        items_total_val = geotiffs_total or 0
        item_unit_val = "geotiffs"
    else:
        items_done_val = tiles_done
        items_total_val = tiles_total
        item_unit_val = "tiles"

    # Build a human-readable detail string from available context.
    if phase is not None:
        if phase == "downloading" and geotiffs_total is not None:
            detail = (
                f"{phase}: {geotiffs_downloaded or 0}/{geotiffs_total} geotiffs"
                + (f" (batch {current_batch}/{total_batches})" if current_batch is not None else "")
            )
        else:
            detail = f"{phase}: {tiles_done}/{tiles_total} tiles"
    elif status == "completed":
        detail = f"completed: {tiles_done}/{tiles_total} tiles"
    elif status == "error":
        detail = f"error: {error or 'unknown'}"
    elif status == "cancelled":
        detail = f"cancelled after {tiles_done} tiles"
    else:
        detail = f"{tiles_done}/{tiles_total} tiles at {round(rate, 1)}/s"

    # Determine source from mode
    source = mode if mode else "imagery"

    # Step 1: call shared module for the canonical atomic write
    _generic_progress(
        state_path,
        source=source,
        status=status,
        phase=phase,
        items_done=items_done_val,
        items_total=items_total_val,
        item_unit=item_unit_val,
        detail=detail,
        error=error,
        bbox=bbox,
        zoom=zoom if zoom != "n/a" else None,
    )

    # Step 2: re-read the written state and add backward-compat fields
    try:
        enriched: dict = json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError):
        enriched = {}

    enriched["mode"] = mode
    enriched["tiles_done"] = tiles_done
    enriched["tiles_total"] = tiles_total
    enriched["rate_per_sec"] = round(rate, 1)
    if getattr(update_progress, '_started_at', None) is not None:
        enriched.setdefault("started_at", update_progress._started_at)
    if error is None:
        enriched.pop("error", None)
    else:
        enriched["error"] = error
    if geotiffs_downloaded is not None:
        enriched["geotiffs_downloaded"] = geotiffs_downloaded
    if geotiffs_total is not None:
        enriched["geotiffs_total"] = geotiffs_total
    if geotiffs_bytes is not None:
        enriched["geotiffs_bytes"] = geotiffs_bytes
    if current_batch is not None:
        enriched["current_batch"] = current_batch
    if total_batches is not None:
        enriched["total_batches"] = total_batches
    if scenes_total is not None:
        enriched["scenes_total"] = scenes_total

    # Step 3: write enriched state back atomically
    write_pipeline_state(output_path, enriched)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_bbox(s: str) -> tuple[float, float, float, float]:
    parts = [float(x.strip()) for x in s.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be west,south,east,north")
    return tuple(parts)  # type: ignore[return-value]


def parse_zoom(s: str) -> tuple[int, int]:
    if "-" in s:
        lo, hi = s.split("-", 1)
        return int(lo), int(hi)
    z = int(s)
    return z, z


def deg2tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """Convert lat/lon to tile x, y at given zoom."""
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def tile_ranges(bbox: tuple[float, float, float, float], zoom: int):
    """Return (x_min, x_max, y_min, y_max) tile indices for a zoom level."""
    west, south, east, north = bbox
    x_min, y_min = deg2tile(north, west, zoom)  # NW corner
    x_max, y_max = deg2tile(south, east, zoom)  # SE corner
    return x_min, x_max, y_min, y_max


async def fetch_with_retry(session: aiohttp.ClientSession, url: str,
                           retries: int = MAX_RETRIES,
                           timeout_s: int = 1200) -> bytes | None:
    """GET *url* with exponential-backoff retry.  Returns bytes or None.

    Default timeout is 1200s (20 minutes) per USGS M2M guidance for
    large GeoTIFF downloads.
    """
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout_s)) as resp:
                if resp.status == 200:
                    return await resp.read()
                if resp.status in (429, 500, 502, 503, 504):
                    wait = RETRY_BACKOFF * (2 ** attempt)
                    log.warning("HTTP %s for %s – retrying in %ss", resp.status, url, wait)
                    await asyncio.sleep(wait)
                    continue
                log.error("HTTP %s for %s – skipping", resp.status, url)
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            wait = RETRY_BACKOFF * (2 ** attempt)
            log.warning("%s for %s – retrying in %ss", exc, url, wait)
            await asyncio.sleep(wait)
    log.error("All retries exhausted for %s", url)
    return None


async def fetch_to_file(session: aiohttp.ClientSession, url: str,
                        dest: Path, *,
                        retries: int = MAX_RETRIES,
                        timeout_s: int = 1200,
                        max_size: int = 0,
                        sock_read_s: int = 120) -> bool:
    """Stream-download url to dest file with retry. Returns True on success.

    Unlike fetch_with_retry, this streams to disk via iter_chunked() to
    avoid loading large files into memory (B3 OOM fix).

    Args:
        session: aiohttp client session.
        url: URL to download.
        dest: Destination file path.
        retries: Max retry attempts.
        timeout_s: Total timeout per attempt in seconds.
        max_size: Maximum file size in bytes (0 = unlimited).
        sock_read_s: Max seconds to wait between data chunks (detects stalled
                     connections from network outages). Default 120s — generous
                     enough for slow servers, short enough to recover from a
                     10-minute network outage in ~6 minutes (3 retries × 120s).
    """
    for attempt in range(retries):
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(
                    total=timeout_s, sock_read=sock_read_s)
            ) as resp:
                if resp.status == 200:
                    total = 0
                    with open(dest, "wb") as f:
                        async for chunk in resp.content.iter_chunked(64 * 1024):
                            total += len(chunk)
                            if max_size and total > max_size:
                                log.error("Download exceeded %d bytes for %s -- aborting",
                                          max_size, url)
                                f.close()
                                dest.unlink(missing_ok=True)
                                return False
                            f.write(chunk)
                    return True
                if resp.status in (429, 500, 502, 503, 504):
                    wait = RETRY_BACKOFF * (2 ** attempt)
                    log.warning("HTTP %s for %s -- retrying in %ss",
                                resp.status, url, wait)
                    await asyncio.sleep(wait)
                    continue
                log.error("HTTP %s for %s -- skipping", resp.status, url)
                return False
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            # Connection failures get longer backoff than HTTP errors — a network
            # outage lasts minutes, not seconds. Backoff: 30s, 60s, 120s, 240s, 480s
            # Total wait across 5 attempts: ~15 min, enough to survive a switch reboot.
            wait = 30 * (2 ** attempt)
            log.warning("%s for %s -- retrying in %ss (attempt %d/%d)",
                        exc, url, wait, attempt + 1, retries)
            # Clean up partial file before retry
            if dest.exists():
                dest.unlink(missing_ok=True)
            await asyncio.sleep(wait)
    log.error("All retries exhausted for %s", url)
    return False


# ---------------------------------------------------------------------------
# Token-bucket rate limiter
# ---------------------------------------------------------------------------

class TokenBucket:
    def __init__(self, burst: int = 50, sustained: float = 20.0):
        self._tokens = float(burst)
        self._max = float(burst)
        self._rate = sustained
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._last = now
            self._tokens = min(self._max, self._tokens + elapsed * self._rate)
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


# ===================================================================
# MODE 1 – TNMAccess API
# ===================================================================

async def query_tnm_products(bbox: str, dataset: str, max_per_page: int = 100):
    """Paginate through TNMAccess and yield download URLs."""
    offset = 0
    async with aiohttp.ClientSession() as session:
        while True:
            params = {
                "datasets": dataset,
                "bbox": bbox,
                "prodFormats": "GeoTIFF",
                "max": max_per_page,
                "offset": offset,
            }
            log.info("Querying TNMAccess offset=%d", offset)
            data = await fetch_with_retry(session, TNM_API + "?" + "&".join(
                f"{k}={v}" for k, v in params.items()
            ))
            if data is None:
                break
            payload = json.loads(data)
            items = payload.get("items", [])
            if not items:
                break
            for item in items:
                url = item.get("downloadURL") or item.get("previewGraphicURL")
                if url:
                    yield url
            # If we got fewer items than requested, we've reached the end
            if len(items) < max_per_page:
                break
            offset += max_per_page


async def download_geotiffs(urls: list[str], staging: Path, checkpoint_path: Path,
                            concurrency: int = 5, on_file_complete=None):
    """Download GeoTIFFs to *staging*, skipping already-downloaded ones."""
    # Load checkpoint
    done: dict[str, str] = {}
    if checkpoint_path.exists():
        done = json.loads(checkpoint_path.read_text())
    sem = asyncio.Semaphore(concurrency)
    files_completed = 0

    async def _get_one(session: aiohttp.ClientSession, url: str):
        nonlocal files_completed
        fname = hashlib.sha256(url.encode()).hexdigest()[:16] + ".tif"
        dest = staging / fname
        if url in done and dest.exists():
            files_completed += 1
            return
        async with sem:
            success = await fetch_to_file(session, url, dest)
        if not success:
            files_completed += 1
            return
        done[url] = str(dest)
        _atomic_write_json(checkpoint_path, done)
        files_completed += 1
        if on_file_complete:
            on_file_complete(files_completed, len(urls))

    async with aiohttp.ClientSession() as session:
        tasks = [_get_one(session, u) for u in urls]
        for coro in tqdm(asyncio.as_completed(tasks), total=len(tasks),
                         desc="Downloading GeoTIFFs", file=sys.stderr):
            await coro

    return [Path(p) for p in done.values() if Path(p).exists()]


def convert_geotiffs_to_mbtiles(tif_paths: list[Path], output: Path):
    """Merge GeoTIFFs and convert to MBTiles via GDAL CLI."""
    if not tif_paths:
        log.error("No GeoTIFF files to convert")
        return

    workdir = tif_paths[0].parent
    vrt_path = workdir / "mosaic.vrt"

    # Build VRT
    log.info("Building VRT from %d files", len(tif_paths))
    subprocess.run(
        ["gdalbuildvrt", str(vrt_path)] + [str(p) for p in tif_paths],
        check=True,
    )

    # Convert to MBTiles
    log.info("Converting VRT to MBTiles: %s", output)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "gdal_translate", "-of", "MBTiles",
            "-co", "TILE_FORMAT=JPEG",
            str(vrt_path), str(output),
        ],
        check=True,
    )

    # Build overview pyramids
    log.info("Building overview pyramids")
    subprocess.run(
        ["gdaladdo", "-r", "average", str(output), "2", "4", "8", "16"],
        check=True,
    )
    log.info("MBTiles written to %s", output)


def merge_mbtiles(src_path: Path, dst_path: Path) -> None:
    """Append tiles from src MBTiles into dst MBTiles.

    Creates dst tables if they don't exist (first batch).
    Later batches override overlapping tiles via INSERT OR REPLACE.
    """
    dst = sqlite3.connect(str(dst_path))
    try:
        dst.execute("ATTACH DATABASE ? AS src", (str(src_path),))
        # Create tables if they don't exist (first batch)
        dst.execute("""CREATE TABLE IF NOT EXISTS tiles (
            zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
            tile_data BLOB,
            PRIMARY KEY (zoom_level, tile_column, tile_row))""")
        dst.execute("""CREATE TABLE IF NOT EXISTS metadata (
            name TEXT PRIMARY KEY, value TEXT)""")
        # Insert or replace tiles (later batches override overlapping tiles)
        dst.execute("""INSERT OR REPLACE INTO tiles
            SELECT zoom_level, tile_column, tile_row, tile_data
            FROM src.tiles""")
        # Copy metadata from first batch only
        dst.execute("""INSERT OR IGNORE INTO metadata
            SELECT name, value FROM src.metadata""")
        dst.commit()
        dst.execute("DETACH DATABASE src")
    finally:
        dst.close()


def run_gdal_subprocess(cmd: list[str], timeout: int = 7200,
                        cancel_check=None) -> subprocess.CompletedProcess:
    """Run a GDAL CLI command with nice priority and optional cancel check.

    Uses Popen with a process group so SIGTERM can kill the child
    immediately (without waiting for it to finish).

    Args:
        cmd: Command and arguments (e.g., ["gdalbuildvrt", ...])
        timeout: Max seconds before killing the process.
        cancel_check: Optional callable returning True if cancellation requested.

    Returns:
        CompletedProcess on success.

    Raises:
        subprocess.CalledProcessError: If command fails or is cancelled.
        subprocess.TimeoutExpired: If timeout exceeded.
    """
    global _child_pid
    if cancel_check and cancel_check():
        raise subprocess.CalledProcessError(1, cmd, stderr="Cancelled before start")
    full_cmd = ["nice", "-n", "19"] + cmd
    gdal_env = {**os.environ, "GDAL_CACHEMAX": os.environ.get("GDAL_CACHEMAX", "1024")}
    proc = subprocess.Popen(
        full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=gdal_env,
        preexec_fn=os.setsid,  # new process group so we can kill it
    )
    _child_pid = proc.pid
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait()
        _child_pid = None
        raise
    _child_pid = None
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, full_cmd,
                                            output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(full_cmd, proc.returncode, stdout, stderr)


def _run_gdaladdo_with_metadata_fixup(output: Path) -> None:
    """Run gdaladdo on MBTiles output, then fix metadata to match actual tiles.

    Uses run_gdal_subprocess() for cancel support (not subprocess.run).
    After gdaladdo adds overview tiles at lower zoom levels, updates the
    metadata table so TileServer reports correct minzoom/maxzoom in TileJSON.
    """
    if _cancel_requested:
        return

    run_gdal_subprocess(
        ["gdaladdo", "-r", "average", str(output), "2", "4", "8", "16"],
        timeout=14400,  # 4 hours — full MBTiles overview can take 2+ hours
        cancel_check=lambda: _cancel_requested,
    )

    # Cancel guard: don't fixup metadata on partial overviews
    if _cancel_requested:
        return

    # Fix metadata to reflect actual tile zoom range
    conn = sqlite3.connect(str(output))
    try:
        conn.execute(
            "UPDATE metadata SET value = (SELECT MIN(zoom_level) FROM tiles) "
            "WHERE name = 'minzoom'"
        )
        conn.execute(
            "UPDATE metadata SET value = (SELECT MAX(zoom_level) FROM tiles) "
            "WHERE name = 'maxzoom'"
        )
        conn.commit()
    finally:
        conn.close()


def convert_batch_to_mbtiles(tif_paths: list[Path], output: Path,
                             batch_label: str = "batch") -> bool:
    """Convert a batch of GeoTIFFs to a temp MBTiles, then merge into output.

    1. Build VRT from the batch's GeoTIFFs
    2. Convert VRT to a temporary MBTiles file
    3. Merge temp MBTiles tiles into the main output via SQLite append
    4. Delete the temp MBTiles

    Returns True on success, False on failure.
    """
    if not tif_paths:
        log.error("No GeoTIFF files to convert")
        return False

    workdir = tif_paths[0].parent
    vrt_path = workdir / f"{batch_label}.vrt"
    temp_mbtiles = workdir / f"{batch_label}.mbtiles"

    try:
        # Build VRT from this batch
        log.info("%s: building VRT from %d files", batch_label, len(tif_paths))
        run_gdal_subprocess(
            ["gdalbuildvrt", str(vrt_path)] + [str(p) for p in tif_paths],
            timeout=600,
            cancel_check=lambda: _cancel_requested,
        )

        # Convert VRT to temp MBTiles
        log.info("%s: converting VRT to temp MBTiles", batch_label)
        run_gdal_subprocess(
            [
                "gdal_translate", "-of", "MBTiles",
                "-co", "TILE_FORMAT=JPEG",
                str(vrt_path), str(temp_mbtiles),
            ],
            timeout=7200,
            cancel_check=lambda: _cancel_requested,
        )

        # Merge temp MBTiles into the main output
        output.parent.mkdir(parents=True, exist_ok=True)
        log.info("%s: merging tiles into %s", batch_label, output)
        merge_mbtiles(temp_mbtiles, output)

        return True

    except subprocess.CalledProcessError as exc:
        log.error("%s: GDAL conversion failed: %s", batch_label,
                  exc.stderr if hasattr(exc, 'stderr') and exc.stderr else str(exc))
        return False
    except subprocess.TimeoutExpired:
        log.error("%s: GDAL conversion timed out", batch_label)
        return False
    finally:
        # Cleanup temp files
        if vrt_path.exists():
            vrt_path.unlink()
        if temp_mbtiles.exists():
            temp_mbtiles.unlink()


async def run_tnmaccess(args):
    bbox_str = args.bbox
    staging = Path(args.staging)
    staging.mkdir(parents=True, exist_ok=True)
    checkpoint = staging / "checkpoint.json"

    # Gather product URLs
    urls: list[str] = []
    async for url in query_tnm_products(bbox_str, args.dataset):
        urls.append(url)
    log.info("Found %d downloadable products", len(urls))
    if not urls:
        log.warning("No products found – try a different bbox or dataset")
        return

    # Download
    tif_paths = await download_geotiffs(
        urls, staging, checkpoint, concurrency=args.concurrency
    )

    # Convert
    output = Path(args.output)
    convert_geotiffs_to_mbtiles(tif_paths, output)


# ===================================================================
# MODE 2 – Direct tile scraping
# ===================================================================

async def init_mbtiles(db_path: Path, name: str = "usgs_imagery",
                       bbox: str = "", zoom: str = ""):
    """Create the MBTiles SQLite schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        # Fix for existing databases: deduplicate metadata rows from
        # prior runs that lacked the UNIQUE constraint.
        await db.execute(
            "CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT)"
        )
        await db.execute(
            "DELETE FROM metadata WHERE rowid NOT IN "
            "(SELECT MIN(rowid) FROM metadata GROUP BY name)"
        )
        # Recreate with UNIQUE constraint (MBTiles spec)
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_metadata_name ON metadata (name)"
        )
        await db.execute(
            "CREATE TABLE IF NOT EXISTS tiles "
            "(zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB, "
            "PRIMARY KEY (zoom_level, tile_column, tile_row))"
        )
        metadata = [
            ("name", name),
            ("format", "jpeg"),
            ("type", "baselayer"),
        ]
        if bbox:
            metadata.append(("bounds", bbox))
        if zoom:
            parts = zoom.split("-") if "-" in zoom else [zoom, zoom]
            metadata.append(("minzoom", parts[0]))
            metadata.append(("maxzoom", parts[1]))
        for k, v in metadata:
            await db.execute(
                "INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)",
                (k, v),
            )
        # Checkpoint table for resume
        await db.execute(
            "CREATE TABLE IF NOT EXISTS _checkpoint "
            "(zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, "
            "PRIMARY KEY (zoom_level, tile_column, tile_row))"
        )
        await db.commit()


async def tile_already_done(db: aiosqlite.Connection, z: int, x: int, y: int) -> bool:
    cur = await db.execute(
        "SELECT 1 FROM _checkpoint WHERE zoom_level=? AND tile_column=? AND tile_row=?",
        (z, x, y),
    )
    return (await cur.fetchone()) is not None


async def run_direct(args, url_fn=None):
    if url_fn is None:
        url_fn = lambda z, x, y: USGS_TILE_URL.format(z=z, x=x, y=y)
    bbox = parse_bbox(args.bbox)
    z_min, z_max = parse_zoom(args.zoom)
    output = Path(args.output)
    await init_mbtiles(output, bbox=args.bbox, zoom=args.zoom)
    # No artificial rate limit — USGS handles 100+ concurrent connections fine.
    # Tested at 123 tiles/sec with 100 concurrent, zero 429s.
    sem = asyncio.Semaphore(args.concurrency)

    # Build full tile list
    all_tiles: list[tuple[int, int, int]] = []
    for z in range(z_min, z_max + 1):
        x_min, x_max, y_min, y_max = tile_ranges(bbox, z)
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                all_tiles.append((z, x, y))
    log.info("Total tiles to fetch: %d (zoom %d-%d)", len(all_tiles), z_min, z_max)

    # Load all existing checkpoints into a set for O(1) lookup
    # instead of 5M+ individual SQL queries
    async with aiosqlite.connect(str(output)) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        done_set = set()
        async with db.execute("SELECT zoom_level, tile_column, tile_row FROM _checkpoint") as cur:
            async for row in cur:
                done_set.add((row[0], row[1], row[2]))
    log.info("Loaded %d checkpoints into memory", len(done_set))

    remaining = [t for t in all_tiles if t not in done_set]
    log.info("Remaining after checkpoint resume: %d", len(remaining))
    if not remaining:
        log.info("All tiles already downloaded")
        return

    pbar = tqdm(total=len(remaining), desc="Downloading tiles", file=sys.stderr)

    async def _fetch_tile(session: aiohttp.ClientSession, db: aiosqlite.Connection,
                          z: int, x: int, y: int):
        url = url_fn(z, x, y)
        async with sem:
            data = await fetch_with_retry(session, url)
        if data is None:
            pbar.update(1)
            return
        # MBTiles uses TMS y-flip
        tms_y = (2 ** z) - 1 - y
        await db.execute(
            "INSERT OR REPLACE INTO tiles (zoom_level, tile_column, tile_row, tile_data) "
            "VALUES (?, ?, ?, ?)",
            (z, x, tms_y, data),
        )
        await db.execute(
            "INSERT OR REPLACE INTO _checkpoint (zoom_level, tile_column, tile_row) "
            "VALUES (?, ?, ?)",
            (z, x, y),
        )
        pbar.update(1)

    total_tiles = len(all_tiles)
    done_before = total_tiles - len(remaining)
    import datetime
    update_progress._started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    batch_start_time = time.time()

    async with aiosqlite.connect(str(output)) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        async with aiohttp.ClientSession() as session:
            batch_size = 2000
            for i in range(0, len(remaining), batch_size):
                if _cancel_requested:
                    log.info("Cancellation requested — stopping after %d tiles",
                             done_before + i)
                    update_progress(output, args.mode, args.bbox, args.zoom,
                                    done_before + i, total_tiles,
                                    status="cancelled")
                    pbar.close()
                    return

                batch = remaining[i : i + batch_size]
                tasks = [_fetch_tile(session, db, z, x, y) for z, x, y in batch]
                await asyncio.gather(*tasks)
                await db.commit()

                # Update structured progress
                tiles_done = done_before + i + len(batch)
                elapsed = time.time() - batch_start_time
                rate = (i + len(batch)) / elapsed if elapsed > 0 else 0
                update_progress(output, args.mode, args.bbox, args.zoom,
                                tiles_done, total_tiles, rate)

    pbar.close()
    update_progress(output, args.mode, args.bbox, args.zoom,
                    total_tiles, total_tiles, status="completed")
    log.info("MBTiles written to %s", output)


# ===================================================================
# MODE 3 – USGS M2M API
# ===================================================================

M2M_POLL_INTERVAL = 30  # seconds between download-retrieve polls (USGS guidance)
M2M_POLL_MAX_ATTEMPTS = 360  # ~1 hour max wait


async def m2m_request(session: aiohttp.ClientSession, endpoint: str,
                      payload: dict, api_key: str | None = None) -> dict:
    """POST to M2M API endpoint and return the parsed response."""
    url = M2M_API + endpoint
    headers = {}
    if api_key:
        headers["X-Auth-Token"] = api_key
    for attempt in range(MAX_RETRIES):
        try:
            async with session.post(
                url, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                body = await resp.json()
                if resp.status == 429:
                    wait = RETRY_BACKOFF * (2 ** attempt)
                    log.warning("M2M rate limited – retrying in %ss", wait)
                    await asyncio.sleep(wait)
                    continue
                if resp.status != 200:
                    error_msg = body.get("errorMessage", resp.status)
                    raise RuntimeError(f"M2M {endpoint} failed: {error_msg}")
                error_code = body.get("errorCode")
                if error_code:
                    raise RuntimeError(
                        f"M2M {endpoint} error {error_code}: {body.get('errorMessage')}"
                    )
                return body
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            wait = RETRY_BACKOFF * (2 ** attempt)
            log.warning("%s for M2M %s – retrying in %ss", exc, endpoint, wait)
            await asyncio.sleep(wait)
    raise RuntimeError(f"All retries exhausted for M2M {endpoint}")


async def m2m_login(session: aiohttp.ClientSession,
                    username: str, token: str) -> str:
    """Authenticate with M2M login-token endpoint and return the API key."""
    log.info("Logging in to USGS M2M as %s", username)
    resp = await m2m_request(session, "login-token", {
        "username": username,
        "token": token,
    })
    api_key = resp.get("data")
    if not api_key:
        raise RuntimeError("M2M login-token returned no API key")
    log.info("M2M login successful")
    return api_key


async def m2m_logout(session: aiohttp.ClientSession, api_key: str):
    """Logout from M2M API."""
    try:
        await m2m_request(session, "logout", {}, api_key=api_key)
        log.info("M2M logout successful")
    except Exception as exc:
        log.warning("M2M logout failed (non-fatal): %s", exc)


async def m2m_find_naip_dataset(session: aiohttp.ClientSession,
                                api_key: str) -> str:
    """Find the exact NAIP dataset alias via dataset-search."""
    log.info("Searching for NAIP dataset alias")
    resp = await m2m_request(session, "dataset-search", {
        "datasetName": "naip",
    }, api_key=api_key)
    datasets = resp.get("data", [])
    if not datasets:
        raise RuntimeError("No NAIP datasets found via M2M dataset-search")
    # Pick the first matching dataset
    alias = datasets[0].get("datasetAlias", "")
    log.info("Using NAIP dataset alias: %s", alias)
    return alias


async def m2m_scene_search(session: aiohttp.ClientSession, api_key: str,
                           dataset_alias: str,
                           bbox: tuple[float, float, float, float],
                           ) -> list[dict]:
    """Search for NAIP scenes covering the bbox, with pagination."""
    west, south, east, north = bbox
    scenes = []
    starting_number = 1
    max_results = 100

    while True:
        log.info("Scene search starting at %d (found %d so far)",
                 starting_number, len(scenes))
        payload = {
            "datasetName": dataset_alias,
            "maxResults": max_results,
            "startingNumber": starting_number,
            "sceneFilter": {
                "spatialFilter": {
                    "filterType": "mbr",
                    "lowerLeft": {"latitude": south, "longitude": west},
                    "upperRight": {"latitude": north, "longitude": east},
                },
                "acquisitionFilter": {
                    "start": "2020-01-01",
                    "end": "2025-12-31",
                },
            },
        }
        resp = await m2m_request(session, "scene-search", payload,
                                 api_key=api_key)
        data = resp.get("data", {})
        results = data.get("results", [])
        if not results:
            break
        scenes.extend(results)
        total_hits = data.get("totalHits", 0)
        if len(scenes) >= total_hits or len(results) < max_results:
            break
        starting_number += max_results

    log.info("Found %d NAIP scenes", len(scenes))
    return scenes


M2M_BATCH_SIZE = 50  # scenes per batch — keeps URL lifetime short


def _select_best_products(options: list[dict]) -> list[dict]:
    """Pick one product per entity, preferring smaller downloads.

    Priority: compressed > geotiff/tif > full resolution.
    """
    entity_products: dict[str, dict] = {}
    for opt in options:
        if not opt.get("available"):
            continue
        product_name = (opt.get("productName", "") or "").lower()
        eid = opt["entityId"]
        if "compressed" in product_name:
            priority = 0  # best — smallest download
        elif "geotiff" in product_name or "tif" in product_name:
            priority = 1
        elif "full resolution" in product_name:
            priority = 2  # largest — fallback only
        else:
            continue
        existing = entity_products.get(eid)
        if existing is None or priority < existing["_priority"]:
            entity_products[eid] = {
                "entityId": eid,
                "productId": opt.get("id") or opt.get("productId", ""),
                "_productName": opt.get("productName", ""),
                "_priority": priority,
            }
    return list(entity_products.values())


async def _m2m_request_and_poll_urls(
    session: aiohttp.ClientSession, api_key: str,
    downloads: list[dict], batch_label: str,
) -> list[str]:
    """Request downloads for a batch and poll until URLs are ready.

    Follows the official USGS M2M example script pattern:
    1. download-request returns availableDownloads + preparingDownloads
    2. Use availableDownloads URLs immediately
    3. For preparingDownloads, poll download-retrieve every 30s
    4. Track by downloadId via newRecords to avoid duplicates
    """
    api_batch = [{"entityId": d["entityId"], "productId": d["productId"]}
                 for d in downloads]
    resp = await m2m_request(session, "download-request", {
        "downloads": api_batch,
        "label": batch_label,
    }, api_key=api_key)

    req_data = resp.get("data", {})
    available_now = req_data.get("availableDownloads", [])
    preparing = req_data.get("preparingDownloads", [])
    new_records = req_data.get("newRecords", {})
    failed = req_data.get("failed", [])

    requested_count = len(downloads) - len(failed)
    if failed:
        log.warning("  %d downloads failed in request", len(failed))

    # Collect URLs from immediately available downloads
    urls = []
    seen_ids: set[str] = set()
    if isinstance(available_now, list):
        for item in available_now:
            url = item.get("url")
            did = str(item.get("downloadId", ""))
            if url and did not in seen_ids:
                urls.append(url)
                seen_ids.add(did)

    # If some downloads are preparing, poll download-retrieve
    if preparing and len(preparing) > 0:
        log.info("  %d available immediately, %d preparing — polling...",
                 len(urls), len(preparing))

        for attempt in range(M2M_POLL_MAX_ATTEMPTS):
            await asyncio.sleep(M2M_POLL_INTERVAL)

            retrieve = await m2m_request(session, "download-retrieve", {
                "label": batch_label,
            }, api_key=api_key)
            ret_data = retrieve.get("data", {})

            for item in ret_data.get("available", []):
                did = str(item.get("downloadId", ""))
                # Only process downloads from this batch (check newRecords)
                if did in seen_ids:
                    continue
                if did in new_records or str(did) in new_records:
                    url = item.get("url")
                    if url:
                        urls.append(url)
                        seen_ids.add(did)

            for item in ret_data.get("requested", []):
                did = str(item.get("downloadId", ""))
                if did in seen_ids:
                    continue
                if did in new_records or str(did) in new_records:
                    url = item.get("url")
                    if url:
                        urls.append(url)
                        seen_ids.add(did)

            remaining = requested_count - len(seen_ids)
            if remaining <= 0:
                break

            log.info("  %d/%d downloads ready, %d remaining -- waiting %ds",
                     len(seen_ids), requested_count, remaining, M2M_POLL_INTERVAL)
        else:
            log.warning("Timed out waiting for downloads (label: %s). "
                        "Got %d/%d URLs.", batch_label, len(urls), requested_count)
    else:
        log.info("  All %d downloads available immediately", len(urls))

    return urls


async def m2m_download_batched(
    session: aiohttp.ClientSession, api_key: str,
    dataset_alias: str, scenes: list[dict],
    staging: Path, checkpoint_path: Path,
    concurrency: int = 3,
    on_batch_complete=None,
    output_path: Path = None,
) -> list[Path]:
    """Download scenes in batches: options → request → poll → download per chunk.

    Processes M2M_BATCH_SIZE scenes at a time through the full
    request→poll→download cycle. This keeps download URL lifetime
    short and avoids overwhelming USGS rate limits. Checkpoint file
    tracks completed downloads for resume across batches and restarts.
    """
    global _cancel_requested

    entity_ids = [s["entityId"] for s in scenes]

    # Load checkpoint to skip already-downloaded entities
    done: dict[str, str] = {}
    if checkpoint_path.exists():
        done = json.loads(checkpoint_path.read_text())
    downloaded_urls = set(done.keys())

    total_scenes = len(entity_ids)
    total_downloaded = len(done)
    log.info("M2M batched download: %d scenes, %d already downloaded, batch size %d",
             total_scenes, total_downloaded, M2M_BATCH_SIZE)

    product_names_logged = False

    # Pipelined batch processing: download batch N+1 while converting batch N.
    # A semaphore ensures only one conversion runs at a time (memory-bounded).
    # At most 2 batches of GeoTIFFs exist on disk simultaneously.
    convert_sem = asyncio.Semaphore(1)
    pending_conversion = None  # Task for the currently-running background conversion

    async def _convert_and_cleanup(paths, batch_label):
        """Convert GeoTIFFs to temp MBTiles, merge into output, delete originals."""
        async with convert_sem:
            log.info("%s: converting %d GeoTIFFs to MBTiles...",
                     batch_label, len(paths))
            try:
                success = await asyncio.get_event_loop().run_in_executor(
                    None, convert_batch_to_mbtiles, paths, output_path, batch_label
                )
                if success:
                    for tif_path in paths:
                        if tif_path.exists():
                            tif_path.unlink()
                    log.info("%s: converted, merged, and cleaned up %d GeoTIFFs",
                             batch_label, len(paths))
                else:
                    log.warning("%s: conversion failed -- keeping raw files",
                                batch_label)
            except Exception as exc:
                log.warning("%s: conversion failed (%s) -- keeping raw files",
                            batch_label, exc)

    for batch_start in range(0, total_scenes, M2M_BATCH_SIZE):
        if _cancel_requested:
            log.info("Cancellation requested between batches")
            break

        batch_ids = entity_ids[batch_start:batch_start + M2M_BATCH_SIZE]
        batch_num = batch_start // M2M_BATCH_SIZE + 1
        total_batches = (total_scenes + M2M_BATCH_SIZE - 1) // M2M_BATCH_SIZE
        log.info("=== Batch %d/%d: %d scenes (starting at %d) ===",
                 batch_num, total_batches, len(batch_ids), batch_start)

        # --- Download options for this batch ---
        resp = await m2m_request(session, "download-options", {
            "datasetName": dataset_alias,
            "entityIds": batch_ids,
        }, api_key=api_key)
        options = resp.get("data", [])

        # Log product names once for diagnosis
        if not product_names_logged:
            all_product_names = {opt.get("productName", "")
                                 for opt in options if opt.get("productName")}
            if all_product_names:
                log.info("Available product names: %s", sorted(all_product_names))
            product_names_logged = True

        products = _select_best_products(options)
        if not products:
            log.warning("Batch %d: no downloadable products, skipping", batch_num)
            continue

        # Skip products whose entity was already downloaded
        new_products = []
        for p in products:
            staging_files = list(staging.glob(f"*{p['entityId']}*"))
            if staging_files:
                log.debug("Skipping entity %s — already in staging", p["entityId"])
                continue
            new_products.append(p)

        if not new_products:
            log.info("Batch %d: all %d products already downloaded, skipping",
                     batch_num, len(products))
            continue

        log.info("Batch %d: requesting %d downloads (%d skipped as already done)",
                 batch_num, len(new_products), len(products) - len(new_products))

        # --- Request + poll for this batch ---
        label = f"geographica_m2m_{int(time.time())}_{batch_start}"
        urls = await _m2m_request_and_poll_urls(
            session, api_key, new_products, label
        )

        if not urls:
            log.warning("Batch %d: no download URLs obtained", batch_num)
            continue

        # Filter out already-downloaded URLs
        new_urls = [u for u in urls if u not in downloaded_urls]
        log.info("Batch %d: %d URLs (%d new, %d already downloaded)",
                 batch_num, len(urls), len(new_urls), len(urls) - len(new_urls))

        if not new_urls:
            continue

        # --- Wait for previous conversion to finish before downloading ---
        # This ensures at most 2 batches of GeoTIFFs on disk (one converting, one downloading)
        if pending_conversion and not pending_conversion.done():
            log.info("Batch %d: waiting for previous conversion to finish...", batch_num)
            await pending_conversion

        # --- Download this batch's files (with per-file progress updates) ---
        def _on_file(files_done, files_in_batch):
            # Update state file so admin panel shows live progress
            if on_batch_complete:
                on_batch_complete(
                    geotiffs_downloaded=total_downloaded + files_done,
                    geotiffs_total=total_scenes,
                    geotiffs_bytes=0,  # not tracked per-file
                    current_batch=batch_num,
                    total_batches=total_batches,
                )

        batch_paths = await download_geotiffs(
            new_urls, staging, checkpoint_path, concurrency=concurrency,
            on_file_complete=_on_file
        )

        # Reload checkpoint after download
        if checkpoint_path.exists():
            done = json.loads(checkpoint_path.read_text())
            downloaded_urls = set(done.keys())

        total_downloaded = len(done)
        log.info("Batch %d complete: %d files this batch, %d total downloaded",
                 batch_num, len(batch_paths), total_downloaded)

        # --- Start conversion in background (next batch downloads while this converts) ---
        if batch_paths and output_path:
            pending_conversion = asyncio.create_task(
                _convert_and_cleanup(batch_paths, f"Batch {batch_num}")
            )

        if on_batch_complete:
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

    # Wait for final conversion to complete
    if pending_conversion and not pending_conversion.done():
        log.info("Waiting for final conversion to complete...")
        await pending_conversion

    # Return any remaining unconverted files
    all_paths = [Path(p) for p in done.values() if Path(p).exists()]
    log.info("M2M batched download complete: %d batches processed, %d files remaining",
             (total_scenes + M2M_BATCH_SIZE - 1) // M2M_BATCH_SIZE, len(all_paths))
    return all_paths


async def run_m2m(args):
    """Run the M2M imagery acquisition pipeline."""
    global _cancel_requested

    username = args.m2m_username
    token = args.m2m_token
    if not username or not token:
        log.error("M2M mode requires --m2m-username and --m2m-token "
                  "(or USGS_M2M_USERNAME / USGS_M2M_TOKEN env vars)")
        sys.exit(1)

    bbox = parse_bbox(args.bbox)
    staging = Path(args.staging)
    staging.mkdir(parents=True, exist_ok=True)
    checkpoint = staging / "m2m_checkpoint.json"
    output = Path(args.output)

    # Cap M2M concurrency to prevent API abuse
    m2m_concurrency = min(args.concurrency, 5)
    if args.concurrency > 5:
        log.warning("Capping M2M concurrency from %d to %d (API rate limit safety)",
                     args.concurrency, m2m_concurrency)

    os.environ.setdefault("GDAL_CACHEMAX", "1024")

    import datetime
    update_progress._started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    async with aiohttp.ClientSession() as session:
        # --- Login ---
        try:
            api_key = await m2m_login(session, username, token)
        except Exception as exc:
            log.error("M2M login failed: %s", exc)
            update_progress(output, "m2m", args.bbox, "n/a",
                            0, 0, status="error", phase="error",
                            error=f"Login failed: {exc}")
            sys.exit(1)

        update_progress(output, "m2m", args.bbox, "n/a",
                        0, 0, status="running", phase="login")

        if _cancel_requested:
            log.info("Cancellation requested after login — logging out")
            await m2m_logout(session, api_key)
            update_progress(output, "m2m", args.bbox, "n/a",
                            0, 0, status="cancelled", phase="cancelled")
            return

        try:
            # --- Find NAIP dataset alias ---
            update_progress(output, "m2m", args.bbox, "n/a",
                            0, 0, phase="searching")
            dataset_alias = await m2m_find_naip_dataset(session, api_key)

            if _cancel_requested:
                log.info("Cancellation requested after dataset search — logging out")
                update_progress(output, "m2m", args.bbox, "n/a",
                                0, 0, status="cancelled", phase="cancelled")
                return

            # --- Search for scenes ---
            scenes = await m2m_scene_search(session, api_key, dataset_alias, bbox)
            if not scenes:
                log.error("No NAIP scenes found for bbox %s", args.bbox)
                update_progress(output, "m2m", args.bbox, "n/a",
                                0, 0, status="error", phase="error",
                                error=f"No NAIP scenes found for bbox {args.bbox}")
                sys.exit(1)

            total_batches = (len(scenes) + M2M_BATCH_SIZE - 1) // M2M_BATCH_SIZE
            update_progress(output, "m2m", args.bbox, "n/a",
                            0, 0, phase="downloading",
                            scenes_total=len(scenes),
                            geotiffs_downloaded=0, geotiffs_total=len(scenes),
                            geotiffs_bytes=0,
                            current_batch=0, total_batches=total_batches)

            if _cancel_requested:
                log.info("Cancellation requested after scene search — logging out")
                update_progress(output, "m2m", args.bbox, "n/a",
                                0, len(scenes), status="cancelled", phase="cancelled")
                return

            # --- Batched download: options → request → poll → download per chunk ---
            log.info("Starting batched download for %d scenes", len(scenes))
            tif_paths = []  # B4 fix: initialize before try so finally can't cause UnboundLocalError

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
                output_path=output,
            )

        finally:
            await m2m_logout(session, api_key)

    if _cancel_requested:
        log.info("Cancellation requested after downloads — skipping conversion")
        update_progress(output, "m2m", args.bbox, "n/a",
                        len(tif_paths), len(scenes), status="cancelled", phase="cancelled",
                        scenes_total=len(scenes),
                        geotiffs_downloaded=len(tif_paths), geotiffs_total=len(scenes))
        return

    if not tif_paths:
        log.error("No GeoTIFF files were downloaded successfully")
        update_progress(output, "m2m", args.bbox, "n/a",
                        0, len(scenes), status="error", phase="error",
                        error="All GeoTIFF downloads failed")
        sys.exit(1)

    # Conversion now happens per-batch inside m2m_download_batched.
    # Any remaining unconverted files (from failed batch conversions) get a final pass.
    remaining_tifs = [p for p in tif_paths if p.exists()]
    if remaining_tifs:
        log.info("Final conversion pass for %d remaining GeoTIFFs", len(remaining_tifs))
        update_progress(output, "m2m", args.bbox, "n/a",
                        0, 0, phase="converting",
                        scenes_total=len(scenes),
                        geotiffs_downloaded=len(tif_paths), geotiffs_total=len(scenes))
        try:
            success = convert_batch_to_mbtiles(remaining_tifs, output, "final_pass")
            if success:
                for p in remaining_tifs:
                    if p.exists():
                        p.unlink()
            else:
                log.error("Final GDAL conversion failed")
                update_progress(output, "m2m", args.bbox, "n/a",
                                0, 0, status="error", phase="error",
                                error="GDAL conversion failed")
                sys.exit(1)
        except Exception as exc:
            log.error("Final GDAL conversion failed: %s", exc)
            update_progress(output, "m2m", args.bbox, "n/a",
                            0, 0, status="error", phase="error",
                            error=f"GDAL conversion failed: {exc}")
            sys.exit(1)

    # Build overview pyramids ONCE at the very end (not per batch)
    if output.exists():
        log.info("Building overview pyramids for %s", output)
        update_progress(output, "m2m", args.bbox, "n/a",
                        0, 0, phase="overviews",
                        scenes_total=len(scenes),
                        geotiffs_downloaded=len(tif_paths), geotiffs_total=len(scenes))
        try:
            run_gdal_subprocess(
                ["gdaladdo", "-r", "average", str(output), "2", "4", "8", "16"],
                timeout=3600,
                cancel_check=lambda: _cancel_requested,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            log.warning("Overview generation failed: %s -- output is still usable", exc)

    update_progress(output, "m2m", args.bbox, "n/a",
                    0, len(scenes), status="completed", phase="complete",
                    scenes_total=len(scenes),
                    geotiffs_downloaded=len(tif_paths), geotiffs_total=len(scenes))
    log.info("M2M pipeline complete: %d scenes → %s", len(scenes), output)


# ===================================================================
# MODE 4 – NOAA Digital Coast NAIP
# ===================================================================

NOAA_MAX_GEOTIFF_SIZE = 600 * 1024 * 1024  # 600 MB safety limit per tile

# GDAL environment for memory-safe operation on Pi 5
_NOAA_GDAL_ENV = {
    **os.environ,
    "GDAL_CACHEMAX": "256",
    "GDAL_NUM_THREADS": "2",
}


async def _noaa_fetch_tile_index(
    session: aiohttp.ClientSession,
    blob_base: str,
    cache_dir: Path,
) -> Path | None:
    """Fetch and cache the NOAA tile index shapefile.

    NOAA distributes the tile index as a ZIP archive (e.g., tileindex_AZ_NAIP_2021.zip)
    containing .shp, .shx, .dbf, .prj files. This function finds the ZIP link in
    index.html, downloads it, extracts the shapefile components, and caches them.

    Returns the path to the .shp file, or None on failure.
    """
    import re
    import zipfile

    cache_dir.mkdir(parents=True, exist_ok=True)

    # Check if already cached
    shp_files = list(cache_dir.glob("*.shp"))
    if shp_files:
        log.info("Using cached tile index: %s", shp_files[0])
        return shp_files[0]

    # Fetch index.html to find the tile index ZIP link
    index_url = f"{blob_base}/index.html"
    log.info("Fetching NOAA tile index listing from %s", index_url)
    index_data = await fetch_with_retry(session, index_url, timeout_s=60)
    if index_data is None:
        log.error("Failed to fetch NOAA blob listing from %s", index_url)
        return None

    html = index_data.decode("utf-8", errors="replace")

    # Find the tile index ZIP link (pattern: tileindex_*.zip)
    zip_pattern = re.compile(r'href=["\']([^"\']*tileindex[^"\']*\.zip)["\']', re.IGNORECASE)
    zip_match = zip_pattern.search(html)
    if not zip_match:
        log.error("No tileindex ZIP found in NOAA blob listing at %s", index_url)
        return None

    zip_href = zip_match.group(1)
    if zip_href.startswith("http"):
        zip_url = zip_href
    else:
        zip_url = f"{blob_base}/{zip_href.lstrip('/')}"

    # Download the ZIP
    zip_dest = cache_dir / "tileindex.zip"
    log.info("Downloading tile index: %s", zip_url)
    success = await fetch_to_file(session, zip_url, zip_dest, timeout_s=120)
    if not success:
        log.error("Failed to download tile index ZIP from %s", zip_url)
        return None

    # Extract shapefile components
    try:
        with zipfile.ZipFile(str(zip_dest)) as zf:
            zf.extractall(str(cache_dir))
            log.info("Extracted tile index: %s", [n for n in zf.namelist()])
    except (zipfile.BadZipFile, OSError) as exc:
        log.error("Failed to extract tile index ZIP: %s", exc)
        zip_dest.unlink(missing_ok=True)
        return None

    # Clean up ZIP
    zip_dest.unlink(missing_ok=True)

    # Find the extracted .shp file
    shp_files = list(cache_dir.glob("*.shp"))
    if not shp_files:
        log.error("No .shp file found after extracting tile index ZIP")
        return None

    log.info("Tile index ready: %s", shp_files[0])
    return shp_files[0]


async def run_noaa(args):
    """Run the NOAA Digital Coast NAIP download pipeline.

    Downloads GeoTIFF tiles ONE AT A TIME from NOAA Azure blob storage,
    reprojects each to EPSG:3857, converts to MBTiles, then cleans up.
    """
    global _cancel_requested

    state = args.state
    year = args.year
    bbox = parse_bbox(args.bbox)
    west, south, east, north = bbox
    output = Path(args.output)
    data_dir = output.parent

    import datetime
    update_progress._started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Validate catalog entry
    if (state, year) not in NOAA_NAIP_CATALOG:
        log.error("No NOAA catalog entry for state=%s year=%d", state, year)
        update_progress(output, "noaa", args.bbox, "n/a",
                        0, 0, status="error", phase="error",
                        error=f"No NOAA catalog entry for {state} {year}")
        sys.exit(1)

    blob_base = noaa_blob_base_url(state, year)
    cache_dir = noaa_cache_dir(data_dir, state, year)
    staging = cache_dir / "staging"
    staging.mkdir(parents=True, exist_ok=True)

    log.info("NOAA NAIP pipeline: state=%s year=%d blob=%s", state, year, blob_base)

    # Phase 1: Validate blob URL with HEAD request
    update_progress(output, "noaa", args.bbox, "n/a",
                    0, 0, phase="validating")

    async with aiohttp.ClientSession() as session:
        try:
            async with session.head(
                blob_base + "/index.html",
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status >= 400:
                    log.error("NOAA blob HEAD returned HTTP %s for %s", resp.status, blob_base)
                    update_progress(output, "noaa", args.bbox, "n/a",
                                    0, 0, status="error", phase="error",
                                    error=f"NOAA blob not accessible (HTTP {resp.status})")
                    sys.exit(1)
                log.info("NOAA blob validated (HTTP %s)", resp.status)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.error("Failed to validate NOAA blob URL: %s", exc)
            update_progress(output, "noaa", args.bbox, "n/a",
                            0, 0, status="error", phase="error",
                            error=f"NOAA blob not accessible: {exc}")
            sys.exit(1)

        if _cancel_requested:
            log.info("Cancellation requested after validation")
            update_progress(output, "noaa", args.bbox, "n/a",
                            0, 0, status="cancelled", phase="cancelled")
            return

        # Phase 2: Fetch and cache tile index shapefile
        update_progress(output, "noaa", args.bbox, "n/a",
                        0, 0, phase="indexing")

        shp_path = await _noaa_fetch_tile_index(session, blob_base, cache_dir)
        if shp_path is None:
            update_progress(output, "noaa", args.bbox, "n/a",
                            0, 0, status="error", phase="error",
                            error="Failed to fetch NOAA tile index shapefile")
            sys.exit(1)

        if _cancel_requested:
            log.info("Cancellation requested after tile index fetch")
            update_progress(output, "noaa", args.bbox, "n/a",
                            0, 0, status="cancelled", phase="cancelled")
            return

        # Phase 3: Spatially filter tiles by bbox
        tile_filenames = filter_tiles_by_bbox(shp_path, west, south, east, north)
        if not tile_filenames:
            log.error("No NOAA tiles intersect bbox %s", args.bbox)
            update_progress(output, "noaa", args.bbox, "n/a",
                            0, 0, status="error", phase="error",
                            error=f"No NOAA tiles intersect bbox {args.bbox}")
            return

        total_tiles = len(tile_filenames)
        log.info("Found %d NOAA tiles intersecting bbox", total_tiles)

        update_progress(output, "noaa", args.bbox, "n/a",
                        0, total_tiles, phase="downloading",
                        geotiffs_downloaded=0, geotiffs_total=total_tiles)

        # Phase 4: Download, reproject, and convert ONE AT A TIME
        tiles_done = 0
        tiles_failed = 0

        from pipeline_security import validate_file_header

        # Concurrent pipeline: up to DOWNLOAD_CONCURRENCY tiles downloading
        # simultaneously, feeding a processing queue. GDAL processing runs
        # in a thread pool (one at a time — MBTiles merge is not thread-safe).
        # Pi 5 has 4 cores and 8+ GB free RAM; 3 concurrent downloads keep
        # the network saturated while CPU stays busy with reproject+convert.
        DOWNLOAD_CONCURRENCY = 3  # tiles downloading simultaneously
        download_sem = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)
        process_queue = asyncio.Queue(maxsize=DOWNLOAD_CONCURRENCY)
        loop = asyncio.get_event_loop()

        async def _download_tile(tile_fname):
            """Download and validate a single tile. Returns (fname, path) or (fname, None)."""
            url = f"{blob_base}/{tile_fname}"
            dest = staging / tile_fname
            async with download_sem:
                if _cancel_requested:
                    return (tile_fname, None)
                ok = await fetch_to_file(session, url, dest, timeout_s=3600,
                                         max_size=NOAA_MAX_GEOTIFF_SIZE,
                                         retries=5, sock_read_s=120)
            if not ok:
                return (tile_fname, None)
            if not validate_file_header(dest, "geotiff"):
                log.error("Invalid GeoTIFF header for %s — removing", tile_fname)
                dest.unlink(missing_ok=True)
                return (tile_fname, None)
            return (tile_fname, dest)

        def _process_tile(raw_path, tile_fname, idx):
            """Reproject + convert a downloaded tile. Returns True on success."""
            warped_path = staging / f"warped_{tile_fname}"
            try:
                run_gdal_subprocess(
                    ["gdalwarp", "-t_srs", "EPSG:3857", "-r", "lanczos",
                     "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
                     str(raw_path), str(warped_path)],
                    timeout=3600,
                    cancel_check=lambda: _cancel_requested,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                log.error("gdalwarp failed for %s: %s", tile_fname, exc)
                raw_path.unlink(missing_ok=True)
                warped_path.unlink(missing_ok=True)
                return False

            raw_path.unlink(missing_ok=True)

            # MBTiles merge is not thread-safe — must be serialized
            ok = convert_batch_to_mbtiles([warped_path], output, f"noaa_tile_{idx}")
            warped_path.unlink(missing_ok=True)
            return ok

        async def _producer():
            """Download tiles concurrently and feed into the process queue."""
            download_tasks = []
            for idx, fname in enumerate(tile_filenames):
                if _cancel_requested:
                    break
                log.info("[%d/%d] Downloading %s (~%d MB)",
                         idx + 1, total_tiles, fname, NOAA_TILE_SIZE_MB)
                task = asyncio.ensure_future(_download_tile(fname))
                download_tasks.append((idx, fname, task))

                # When we have DOWNLOAD_CONCURRENCY tasks in flight, wait for
                # the oldest to finish and push it to the process queue
                if len(download_tasks) >= DOWNLOAD_CONCURRENCY:
                    oldest_idx, oldest_fname, oldest_task = download_tasks.pop(0)
                    dl_fname, dl_path = await oldest_task
                    await process_queue.put((oldest_idx, dl_fname, dl_path))

            # Drain remaining downloads
            for idx, fname, task in download_tasks:
                if _cancel_requested:
                    task.cancel()
                    continue
                dl_fname, dl_path = await task
                await process_queue.put((idx, dl_fname, dl_path))

            # Signal end of downloads
            await process_queue.put(None)

        async def _consumer():
            """Process downloaded tiles sequentially (MBTiles merge not thread-safe)."""
            nonlocal tiles_done, tiles_failed
            while True:
                item = await process_queue.get()
                if item is None:
                    break
                idx, tile_fname, raw_path = item

                if _cancel_requested or raw_path is None:
                    if raw_path:
                        raw_path.unlink(missing_ok=True)
                    if raw_path is None:
                        tiles_failed += 1
                    continue

                log.info("[%d/%d] Reprojecting + converting %s",
                         idx + 1, total_tiles, tile_fname)
                update_progress(output, "noaa", args.bbox, "n/a",
                                tiles_done, total_tiles, phase="converting",
                                geotiffs_downloaded=tiles_done,
                                geotiffs_total=total_tiles)

                convert_ok = await loop.run_in_executor(
                    None, _process_tile, raw_path, tile_fname, idx
                )

                if convert_ok:
                    tiles_done += 1
                    log.info("[%d/%d] Tile %s done (%d/%d complete)",
                             idx + 1, total_tiles, tile_fname,
                             tiles_done, total_tiles)
                    update_progress(output, "noaa", args.bbox, "n/a",
                                    tiles_done, total_tiles, phase="downloading",
                                    geotiffs_downloaded=tiles_done,
                                    geotiffs_total=total_tiles)
                else:
                    tiles_failed += 1
                    if _cancel_requested:
                        break
                    log.warning("[%d/%d] Conversion failed for %s",
                                idx + 1, total_tiles, tile_fname)

        # Run producer and consumer concurrently
        update_progress(output, "noaa", args.bbox, "n/a",
                        0, total_tiles, phase="downloading",
                        geotiffs_downloaded=0, geotiffs_total=total_tiles)
        log.info("Starting concurrent pipeline: %d downloads, sequential processing",
                 DOWNLOAD_CONCURRENCY)
        await asyncio.gather(_producer(), _consumer())

        if _cancel_requested:
            update_progress(output, "noaa", args.bbox, "n/a",
                            tiles_done, total_tiles, status="cancelled",
                            phase="cancelled",
                            geotiffs_downloaded=tiles_done,
                            geotiffs_total=total_tiles)
            return

    # Phase 5: Build overview pyramids
    if output.exists() and tiles_done > 0:
        log.info("Building overview pyramids for %s", output)
        update_progress(output, "noaa", args.bbox, "n/a",
                        tiles_done, total_tiles, phase="overviews",
                        geotiffs_downloaded=tiles_done,
                        geotiffs_total=total_tiles)
        try:
            _run_gdaladdo_with_metadata_fixup(output)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            log.warning("Overview generation failed: %s — output is still usable", exc)

    # Phase 6: Update TileServer config if path is provided via env
    ts_config_path = os.environ.get("TILESERVER_CONFIG")
    if output.exists() and tiles_done > 0 and ts_config_path:
        ts_config = Path(ts_config_path)
        if ts_config.exists():
            try:
                from tileserver_config import add_mbtiles_to_config
                added = add_mbtiles_to_config(
                    ts_config, "imagery_noaa", f"/srv/data/{output.name}"
                )
                if added:
                    log.info("Added imagery_noaa to TileServer config.json")
                else:
                    log.info("imagery_noaa already in TileServer config")
            except Exception as exc:
                log.warning("Failed to update TileServer config (non-fatal): %s", exc)
        else:
            log.warning("TileServer config not found at %s", ts_config_path)

    # Final status
    if tiles_done == 0:
        update_progress(output, "noaa", args.bbox, "n/a",
                        0, total_tiles, status="error", phase="error",
                        error=f"All {total_tiles} tiles failed to process")
        log.error("NOAA pipeline failed: 0/%d tiles processed", total_tiles)
    else:
        update_progress(output, "noaa", args.bbox, "n/a",
                        tiles_done, total_tiles, status="completed",
                        phase="complete",
                        geotiffs_downloaded=tiles_done,
                        geotiffs_total=total_tiles)
        log.info("NOAA pipeline complete: %d/%d tiles processed (%d failed) → %s",
                 tiles_done, total_tiles, tiles_failed, output)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download USGS orthoimagery and convert to MBTiles"
    )
    parser.add_argument(
        "--mode", choices=["tnmaccess", "direct", "m2m", "nationalmap", "noaa"],
        default="tnmaccess",
        help="Download mode (default: tnmaccess)",
    )
    parser.add_argument(
        "--bbox", default=DEFAULT_BBOX,
        help="Bounding box as west,south,east,north (default: %(default)s)",
    )
    parser.add_argument(
        "--output", default="data/imagery.mbtiles",
        help="Output MBTiles path (default: %(default)s)",
    )
    parser.add_argument(
        "--zoom", default="0-14",
        help="Zoom range for direct mode, e.g. 0-14 (default: %(default)s)",
    )
    parser.add_argument(
        "--dataset", default=DEFAULT_DATASET,
        help="TNMAccess dataset name (default: %(default)s)",
    )
    parser.add_argument(
        "--staging", default="/data/staging_imagery",
        help="Staging directory for GeoTIFF downloads (default: %(default)s)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=80,
        help="Max simultaneous downloads (default: %(default)s)",
    )
    parser.add_argument(
        "--m2m-username",
        default=os.environ.get("USGS_M2M_USERNAME"),
        help="USGS M2M username (default: USGS_M2M_USERNAME env var)",
    )
    parser.add_argument(
        "--m2m-token",
        default=os.environ.get("USGS_M2M_TOKEN"),
        help="USGS M2M API token (default: USGS_M2M_TOKEN env var)",
    )
    parser.add_argument(
        "--state",
        help="State abbreviation for NOAA mode (e.g. AZ, CA)",
    )
    parser.add_argument(
        "--year", type=int, default=2021,
        help="NAIP year for NOAA mode (default: %(default)s)",
    )

    args = parser.parse_args()

    if args.mode == "noaa":
        if not args.state:
            log.error("NOAA mode requires --state (e.g. --state AZ)")
            sys.exit(1)
        asyncio.run(run_noaa(args))
    elif args.mode == "tnmaccess":
        asyncio.run(run_tnmaccess(args))
    elif args.mode == "m2m":
        asyncio.run(run_m2m(args))
    elif args.mode == "nationalmap":
        if not args.zoom or args.zoom == "0-14":
            args.zoom = "15-18"
        asyncio.run(run_direct(args, url_fn=nationalmap_tile_url))
    else:
        asyncio.run(run_direct(args))


if __name__ == "__main__":
    main()
