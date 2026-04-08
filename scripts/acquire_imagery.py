#!/usr/bin/env python3
"""Download USGS orthoimagery and convert to MBTiles.

Two modes:
  tnmaccess  - Query TNMAccess API for NAIP/Topo GeoTIFFs, then convert via GDAL.
  direct     - Scrape tiles from the USGS cached tile service into MBTiles.

Usage examples:
  python acquire_imagery.py --mode tnmaccess --bbox "-124.6,31.2,-103.0,42.2" --output data/imagery.mbtiles
  python acquire_imagery.py --mode direct --bbox "-124.6,31.2,-103.0,42.2" --zoom 0-14 --output data/imagery.mbtiles
"""

import argparse
import asyncio
import hashlib
import json
import logging
import math
import os
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
DEFAULT_BBOX = "-124.8,31.3,-102.0,49.0"
DEFAULT_DATASET = "USDA National Agriculture Imagery Program (NAIP)"
USGS_TILE_URL = (
    "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/"
    "MapServer/tile/{z}/{y}/{x}"
)
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds, doubled each attempt


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

async def init_mbtiles(db_path: Path, name: str = "usgs_imagery"):
    """Create the MBTiles SQLite schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT)"
        )
        await db.execute(
            "CREATE TABLE IF NOT EXISTS tiles "
            "(zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB, "
            "PRIMARY KEY (zoom_level, tile_column, tile_row))"
        )
        for k, v in [
            ("name", name),
            ("format", "jpeg"),
            ("type", "baselayer"),
        ]:
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
    await init_mbtiles(output)
    bucket = TokenBucket(burst=50, sustained=20.0)
    sem = asyncio.Semaphore(args.concurrency)

    # Build full tile list
    all_tiles: list[tuple[int, int, int]] = []
    for z in range(z_min, z_max + 1):
        x_min, x_max, y_min, y_max = tile_ranges(bbox, z)
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                all_tiles.append((z, x, y))
    log.info("Total tiles to fetch: %d (zoom %d-%d)", len(all_tiles), z_min, z_max)

    # Filter already-done
    async with aiosqlite.connect(str(output)) as db:
        remaining = []
        for z, x, y in all_tiles:
            if not await tile_already_done(db, z, x, y):
                remaining.append((z, x, y))
    log.info("Remaining after checkpoint resume: %d", len(remaining))
    if not remaining:
        log.info("All tiles already downloaded")
        return

    pbar = tqdm(total=len(remaining), desc="Downloading tiles", file=sys.stderr)

    async def _fetch_tile(session: aiohttp.ClientSession, db: aiosqlite.Connection,
                          z: int, x: int, y: int):
        await bucket.acquire()
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

    async with aiosqlite.connect(str(output)) as db:
        async with aiohttp.ClientSession() as session:
            batch_size = 500
            for i in range(0, len(remaining), batch_size):
                batch = remaining[i : i + batch_size]
                tasks = [_fetch_tile(session, db, z, x, y) for z, x, y in batch]
                await asyncio.gather(*tasks)
                await db.commit()

    pbar.close()
    log.info("MBTiles written to %s", output)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download USGS orthoimagery and convert to MBTiles"
    )
    parser.add_argument(
        "--mode", choices=["tnmaccess", "direct"], default="tnmaccess",
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
        "--staging", default="data/staging_imagery",
        help="Staging directory for GeoTIFF downloads (default: %(default)s)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=5,
        help="Max simultaneous downloads (default: %(default)s)",
    )

    args = parser.parse_args()

    if args.mode == "tnmaccess":
        asyncio.run(run_tnmaccess(args))
    else:
        asyncio.run(run_direct(args))


if __name__ == "__main__":
    main()
