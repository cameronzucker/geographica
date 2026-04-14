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


def _handle_sigterm(signum, frame):
    """Handle SIGTERM for graceful shutdown (docker stop)."""
    global _cancel_requested
    log.info("SIGTERM received — finishing current batch and shutting down")
    _cancel_requested = True


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
                        max_size: int = 0) -> bool:
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
    """
    for attempt in range(retries):
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=timeout_s)
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
            wait = RETRY_BACKOFF * (2 ** attempt)
            log.warning("%s for %s -- retrying in %ss", exc, url, wait)
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download USGS orthoimagery and convert to MBTiles"
    )
    parser.add_argument(
        "--mode", choices=["tnmaccess", "direct", "m2m"], default="tnmaccess",
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

    args = parser.parse_args()

    if args.mode == "tnmaccess":
        asyncio.run(run_tnmaccess(args))
    elif args.mode == "m2m":
        asyncio.run(run_m2m(args))
    else:
        asyncio.run(run_direct(args))


if __name__ == "__main__":
    main()
