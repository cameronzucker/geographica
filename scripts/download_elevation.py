#!/usr/bin/env python3
"""Download Terrain-RGB tiles from AWS Terrain Tiles into MBTiles.

Source: https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png

Usage:
  python download_elevation.py --bbox "-124.6,31.2,-103.0,42.2" --zoom 0-12 --output data/elevation.mbtiles
"""

import argparse
import asyncio
import json
import logging
import math
import os
import signal
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
TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
DEFAULT_BBOX = "-124.6,31.2,-103.0,42.2"
DEFAULT_ZOOM = "0-12"
MAX_RETRIES = 3
RETRY_BACKOFF = 2

# ---------------------------------------------------------------------------
# Cancellation + Structured Progress
# ---------------------------------------------------------------------------
_cancel_requested = False


def _handle_sigterm(signum, frame):
    global _cancel_requested
    log.info("SIGTERM received — finishing current batch and shutting down")
    _cancel_requested = True


signal.signal(signal.SIGTERM, _handle_sigterm)


def write_pipeline_state(output_path, state: dict):
    """Atomically write pipeline state JSON for the admin monitor."""
    from pathlib import Path
    state_path = Path(output_path).parent / ".elevation-state.json"
    tmp_path = state_path.with_suffix(".json.tmp")
    try:
        tmp_path.write_text(json.dumps(state))
        with open(tmp_path) as f:
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(state_path))
    except Exception as exc:
        log.warning("Failed to write state: %s", exc)


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
    y = int(
        (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
        / 2.0 * n
    )
    return x, y


def tile_ranges(bbox: tuple[float, float, float, float], zoom: int):
    """Return (x_min, x_max, y_min, y_max) tile indices for a zoom level."""
    west, south, east, north = bbox
    x_min, y_min = deg2tile(north, west, zoom)  # NW corner
    x_max, y_max = deg2tile(south, east, zoom)  # SE corner
    return x_min, x_max, y_min, y_max


async def fetch_with_retry(session: aiohttp.ClientSession, url: str,
                           retries: int = MAX_RETRIES) -> bytes | None:
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status == 200:
                    return await resp.read()
                if resp.status in (429, 500, 502, 503, 504):
                    wait = RETRY_BACKOFF * (2 ** attempt)
                    log.warning("HTTP %s for %s – retrying in %ss",
                                resp.status, url, wait)
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


# ---------------------------------------------------------------------------
# MBTiles management
# ---------------------------------------------------------------------------

async def init_mbtiles(db_path: Path):
    """Create the MBTiles SQLite schema with checkpoint table."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(db_path)) as db:
        # WAL mode allows concurrent readers while writing
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute(
            "CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT)"
        )
        await db.execute(
            "CREATE TABLE IF NOT EXISTS tiles "
            "(zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, "
            "tile_data BLOB, "
            "PRIMARY KEY (zoom_level, tile_column, tile_row))"
        )
        for k, v in [
            ("name", "elevation_terrarium"),
            ("format", "png"),
            ("type", "overlay"),
            ("description", "Terrain-RGB elevation tiles (Terrarium encoding)"),
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


async def tile_already_done(db: aiosqlite.Connection,
                            z: int, x: int, y: int) -> bool:
    cur = await db.execute(
        "SELECT 1 FROM _checkpoint "
        "WHERE zoom_level=? AND tile_column=? AND tile_row=?",
        (z, x, y),
    )
    return (await cur.fetchone()) is not None


# ---------------------------------------------------------------------------
# Download pipeline
# ---------------------------------------------------------------------------

async def run(args):
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

    # Load all existing checkpoints into a set for O(1) lookup
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

    pbar = tqdm(total=len(remaining), desc="Downloading elevation tiles",
                file=sys.stderr)

    async def _fetch_tile(session: aiohttp.ClientSession,
                          db: aiosqlite.Connection,
                          z: int, x: int, y: int):
        await bucket.acquire()
        url = TILE_URL.format(z=z, x=x, y=y)
        async with sem:
            data = await fetch_with_retry(session, url)
        if data is None:
            pbar.update(1)
            return
        # MBTiles uses TMS y-flip
        tms_y = (2 ** z) - 1 - y
        await db.execute(
            "INSERT OR REPLACE INTO tiles "
            "(zoom_level, tile_column, tile_row, tile_data) "
            "VALUES (?, ?, ?, ?)",
            (z, x, tms_y, data),
        )
        await db.execute(
            "INSERT OR REPLACE INTO _checkpoint "
            "(zoom_level, tile_column, tile_row) VALUES (?, ?, ?)",
            (z, x, y),
        )
        pbar.update(1)

    total_tiles = len(all_tiles)
    done_before = total_tiles - len(remaining)
    batch_start_time = time.time()

    async with aiosqlite.connect(str(output)) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        async with aiohttp.ClientSession() as session:
            batch_size = 500
            for i in range(0, len(remaining), batch_size):
                if _cancel_requested:
                    log.info("Cancellation requested — stopping")
                    write_pipeline_state(output, {
                        "status": "cancelled",
                        "tiles_done": done_before + i,
                        "tiles_total": total_tiles
                    })
                    pbar.close()
                    return

                batch = remaining[i : i + batch_size]
                tasks = [
                    _fetch_tile(session, db, z, x, y)
                    for z, x, y in batch
                ]
                await asyncio.gather(*tasks)
                await db.commit()

                # Write structured progress
                tiles_done = done_before + i + len(batch)
                elapsed = time.time() - batch_start_time
                rate = (i + len(batch)) / elapsed if elapsed > 0 else 0
                write_pipeline_state(output, {
                    "status": "running",
                    "tiles_done": tiles_done,
                    "tiles_total": total_tiles,
                    "rate_per_sec": round(rate, 1),
                })

    pbar.close()
    write_pipeline_state(output, {
        "status": "completed",
        "tiles_done": total_tiles,
        "tiles_total": total_tiles,
    })
    log.info("MBTiles written to %s", output)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download Terrain-RGB elevation tiles into MBTiles"
    )
    parser.add_argument(
        "--bbox", default=DEFAULT_BBOX,
        help="Bounding box as west,south,east,north (default: %(default)s)",
    )
    parser.add_argument(
        "--zoom", default=DEFAULT_ZOOM,
        help="Zoom range, e.g. 0-12 (default: %(default)s)",
    )
    parser.add_argument(
        "--output", default="data/elevation.mbtiles",
        help="Output MBTiles path (default: %(default)s)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=10,
        help="Max simultaneous downloads (default: %(default)s)",
    )

    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
