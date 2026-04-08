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

    Merges new fields into existing state to preserve API metadata
    (bbox, zoom, type, estimated_tiles) written by the search service.
    """
    state_path = output_path.parent / ".pipeline-state.json"
    tmp_path = state_path.with_suffix(".json.tmp")
    try:
        existing = {}
        if state_path.exists():
            try:
                existing = json.loads(state_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        existing.update(state)
        tmp_path.write_text(json.dumps(existing))
        with open(tmp_path) as f:
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(state_path))
    except Exception as exc:
        log.warning("Failed to write pipeline state: %s", exc)


def update_progress(output_path: Path, mode: str, bbox: str, zoom: str,
                    tiles_done: int, tiles_total: int, rate: float = 0,
                    status: str = "running", error: str = None):
    """Write structured progress to the state file."""
    import datetime
    write_pipeline_state(output_path, {
        "status": status,
        "mode": mode,
        "bbox": bbox,
        "zoom": zoom,
        "tiles_done": tiles_done,
        "tiles_total": tiles_total,
        "rate_per_sec": round(rate, 1),
        "started_at": getattr(update_progress, '_started_at', None),
        "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "error": error,
    })


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
                           retries: int = MAX_RETRIES) -> bytes | None:
    """GET *url* with exponential-backoff retry.  Returns bytes or None."""
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
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
                            concurrency: int = 5):
    """Download GeoTIFFs to *staging*, skipping already-downloaded ones."""
    # Load checkpoint
    done: dict[str, str] = {}
    if checkpoint_path.exists():
        done = json.loads(checkpoint_path.read_text())
    sem = asyncio.Semaphore(concurrency)

    async def _get_one(session: aiohttp.ClientSession, url: str):
        fname = hashlib.sha256(url.encode()).hexdigest()[:16] + ".tif"
        dest = staging / fname
        if url in done and dest.exists():
            return
        async with sem:
            data = await fetch_with_retry(session, url)
        if data is None:
            return
        dest.write_bytes(data)
        done[url] = str(dest)
        checkpoint_path.write_text(json.dumps(done, indent=2))

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


async def run_direct(args):
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
        url = USGS_TILE_URL.format(z=z, x=x, y=y)
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
                    update_progress(output, "direct", args.bbox, args.zoom,
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
                update_progress(output, "direct", args.bbox, args.zoom,
                                tiles_done, total_tiles, rate)

    pbar.close()
    update_progress(output, "direct", args.bbox, args.zoom,
                    total_tiles, total_tiles, status="completed")
    log.info("MBTiles written to %s", output)


# ===================================================================
# MODE 3 – USGS M2M API
# ===================================================================

M2M_POLL_INTERVAL = 10  # seconds between download-retrieve polls
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


async def m2m_get_download_urls(session: aiohttp.ClientSession, api_key: str,
                                dataset_alias: str,
                                scenes: list[dict]) -> list[str]:
    """Get download URLs for scenes via download-options and download-request."""
    entity_ids = [s["entityId"] for s in scenes]

    # Get download options (batch in groups of 100)
    downloads_to_request = []
    for i in range(0, len(entity_ids), 100):
        batch = entity_ids[i:i + 100]
        log.info("Fetching download options for %d scenes", len(batch))
        resp = await m2m_request(session, "download-options", {
            "datasetName": dataset_alias,
            "entityIds": batch,
        }, api_key=api_key)
        options = resp.get("data", [])
        # Log ALL product names for diagnosis before filtering
        all_product_names = set()
        for opt in options:
            pn = opt.get("productName", "")
            if pn:
                all_product_names.add(pn)
        if all_product_names:
            log.info("Available product names: %s", sorted(all_product_names))

        # Pick one product per entity, preferring smaller downloads.
        # Priority: compressed > geotiff/tif > full resolution
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
        downloads_to_request.extend(entity_products.values())

    if not downloads_to_request:
        log.warning("No downloadable imagery products found")
        return []

    # Log what we selected
    for d in downloads_to_request:
        log.info("Selected product for %s: %s", d["entityId"], d.get("_productName", "?"))

    log.info("Requesting %d downloads", len(downloads_to_request))

    # Request downloads (batch in groups of 100)
    labels = []
    for i in range(0, len(downloads_to_request), 100):
        batch = [{"entityId": d["entityId"], "productId": d["productId"]}
                 for d in downloads_to_request[i:i + 100]]
        label = f"geographica_m2m_{int(time.time())}_{i}"
        resp = await m2m_request(session, "download-request", {
            "downloads": batch,
            "label": label,
        }, api_key=api_key)
        labels.append(label)

    # Poll download-retrieve until all URLs are available
    urls = []
    seen_urls: set[str] = set()
    for label in labels:
        log.info("Polling download-retrieve for label: %s", label)
        for attempt in range(M2M_POLL_MAX_ATTEMPTS):
            resp = await m2m_request(session, "download-retrieve", {
                "label": label,
            }, api_key=api_key)
            data = resp.get("data", {})
            available = data.get("available", [])
            requested = data.get("requested", [])

            for item in available:
                url = item.get("url")
                if url and url not in seen_urls:
                    urls.append(url)
                    seen_urls.add(url)

            if not requested:
                # All downloads for this label are ready
                break

            log.info("  %d available, %d still queued – waiting %ds",
                     len(available), len(requested), M2M_POLL_INTERVAL)
            await asyncio.sleep(M2M_POLL_INTERVAL)
        else:
            log.warning("Timed out waiting for downloads (label: %s). "
                        "Got %d URLs so far.", label, len(urls))

    log.info("Total download URLs: %d", len(urls))
    return urls


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
                            0, 0, status="error",
                            error=f"Login failed: {exc}")
            sys.exit(1)

        update_progress(output, "m2m", args.bbox, "n/a",
                        0, 0, status="running")

        if _cancel_requested:
            log.info("Cancellation requested after login — logging out")
            await m2m_logout(session, api_key)
            update_progress(output, "m2m", args.bbox, "n/a",
                            0, 0, status="cancelled")
            return

        try:
            # --- Find NAIP dataset alias ---
            dataset_alias = await m2m_find_naip_dataset(session, api_key)

            if _cancel_requested:
                log.info("Cancellation requested after dataset search — logging out")
                update_progress(output, "m2m", args.bbox, "n/a",
                                0, 0, status="cancelled")
                return

            # --- Search for scenes ---
            scenes = await m2m_scene_search(session, api_key, dataset_alias, bbox)
            if not scenes:
                log.error("No NAIP scenes found for bbox %s", args.bbox)
                update_progress(output, "m2m", args.bbox, "n/a",
                                0, 0, status="error",
                                error=f"No NAIP scenes found for bbox {args.bbox}")
                sys.exit(1)

            update_progress(output, "m2m", args.bbox, "n/a",
                            0, len(scenes), status="running")

            if _cancel_requested:
                log.info("Cancellation requested after scene search — logging out")
                update_progress(output, "m2m", args.bbox, "n/a",
                                0, len(scenes), status="cancelled")
                return

            # --- Get download URLs ---
            urls = await m2m_get_download_urls(
                session, api_key, dataset_alias, scenes
            )
            if not urls:
                log.error("No downloadable URLs obtained")
                update_progress(output, "m2m", args.bbox, "n/a",
                                0, len(scenes), status="error",
                                error="No downloadable GeoTIFF URLs obtained from M2M API")
                sys.exit(1)

            log.info("Got %d download URLs for %d scenes", len(urls), len(scenes))

        finally:
            await m2m_logout(session, api_key)

    if _cancel_requested:
        log.info("Cancellation requested before downloads — stopping")
        update_progress(output, "m2m", args.bbox, "n/a",
                        0, len(urls), status="cancelled")
        return

    # --- Download GeoTIFFs (reuse existing helper) ---
    update_progress(output, "m2m", args.bbox, "n/a",
                    0, len(urls), status="running")

    tif_paths = await download_geotiffs(
        urls, staging, checkpoint, concurrency=m2m_concurrency
    )

    if _cancel_requested:
        log.info("Cancellation requested after downloads — skipping conversion")
        update_progress(output, "m2m", args.bbox, "n/a",
                        len(tif_paths), len(urls), status="cancelled")
        return

    if not tif_paths:
        log.error("No GeoTIFF files were downloaded successfully")
        update_progress(output, "m2m", args.bbox, "n/a",
                        0, len(urls), status="error",
                        error="All GeoTIFF downloads failed")
        sys.exit(1)

    # --- Convert to MBTiles ---
    update_progress(output, "m2m", args.bbox, "n/a",
                    len(tif_paths), len(urls), status="running")

    try:
        convert_geotiffs_to_mbtiles(tif_paths, output)
    except Exception as exc:
        log.error("GDAL conversion failed: %s", exc)
        update_progress(output, "m2m", args.bbox, "n/a",
                        len(tif_paths), len(urls), status="error",
                        error=f"GDAL conversion failed: {exc}")
        sys.exit(1)

    update_progress(output, "m2m", args.bbox, "n/a",
                    len(urls), len(urls), status="completed")
    log.info("M2M pipeline complete: %s", output)


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
