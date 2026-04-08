#!/usr/bin/env python3
"""Download GNIS data and build a SQLite FTS5 database of place names.

Downloads pipe-delimited state gazetteer files from USGS, parses them,
filters to a bounding box, and creates a searchable SQLite database.

Usage:
  python build_poi_index.py --bbox "-124.6,31.2,-103.0,42.2" --output data/poi.sqlite
"""

import argparse
import asyncio
import io
import json
import logging
import sys
import zipfile
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
GNIS_BASE_URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/"
DEFAULT_BBOX = "-124.8,31.3,-102.0,49.0"
DEFAULT_STATES = ["AZ", "CA", "CO", "ID", "MT", "NV", "NM", "OR", "UT", "WA", "WY"]
MAX_RETRIES = 3
RETRY_BACKOFF = 2

# TNM S3 file naming pattern: DomesticNames_{ST}_Text.zip
STATE_FILE_TEMPLATE = "DomesticNames_{state}_Text.zip"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_bbox(s: str) -> tuple[float, float, float, float]:
    parts = [float(x.strip()) for x in s.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be west,south,east,north")
    return tuple(parts)  # type: ignore[return-value]


def in_bbox(lat: float, lon: float,
            bbox: tuple[float, float, float, float]) -> bool:
    west, south, east, north = bbox
    return south <= lat <= north and west <= lon <= east


async def fetch_with_retry(session: aiohttp.ClientSession, url: str,
                           retries: int = MAX_RETRIES) -> bytes | None:
    for attempt in range(retries):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=300)) as resp:
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
# GNIS parsing
# ---------------------------------------------------------------------------

def parse_gnis_text(raw: str, bbox: tuple[float, float, float, float]):
    """Yield dicts from a pipe-delimited GNIS file, filtered to *bbox*."""
    lines = raw.splitlines()
    if not lines:
        return
    # The first line is the header
    # Strip BOM if present
    header = [h.strip().lower().lstrip('\ufeff') for h in lines[0].split("|")]
    # Build index map — handle both old (state_alpha) and new (state_name) formats
    col = {}
    required = {
        "feature_name": ["feature_name"],
        "feature_class": ["feature_class"],
        "state": ["state_alpha", "state_name"],
        "county": ["county_name"],
        "lat": ["prim_lat_dec"],
        "lon": ["prim_long_dec"],
    }
    for key, candidates in required.items():
        for name in candidates:
            if name in header:
                col[key] = header.index(name)
                break
    if len(col) < 6:
        log.warning("Missing expected columns; found: %s", header)
        return

    for line in lines[1:]:
        parts = line.split("|")
        if len(parts) <= max(col.values()):
            continue
        try:
            lat = float(parts[col["lat"]])
            lon = float(parts[col["lon"]])
        except (ValueError, IndexError):
            continue
        if not in_bbox(lat, lon, bbox):
            continue
        yield {
            "name": parts[col["feature_name"]].strip(),
            "class": parts[col["feature_class"]].strip(),
            "state": parts[col["state"]].strip(),
            "county": parts[col["county"]].strip(),
            "lat": lat,
            "lon": lon,
        }


# ---------------------------------------------------------------------------
# Download + ingest
# ---------------------------------------------------------------------------

async def download_state(session: aiohttp.ClientSession, state: str,
                         checkpoint: dict) -> bytes | None:
    if state in checkpoint:
        log.info("Skipping %s (already in checkpoint)", state)
        return None  # caller should skip
    fname = STATE_FILE_TEMPLATE.format(state=state)
    url = GNIS_BASE_URL + fname
    log.info("Downloading %s", url)
    return await fetch_with_retry(session, url)


def extract_text_from_zip(data: bytes) -> str:
    """Extract the first .txt file from a zip archive."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if name.lower().endswith(".txt"):
                return zf.read(name).decode("utf-8", errors="replace")
    raise ValueError("No .txt file found in zip")


async def build_database(args):
    bbox = parse_bbox(args.bbox)
    states = [s.strip().upper() for s in args.states.split(",")]
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    checkpoint_path = output.with_suffix(".checkpoint.json")
    checkpoint: dict[str, bool] = {}
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text())

    # Create database schema
    async with aiosqlite.connect(str(output)) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS poi_features (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                class TEXT,
                state TEXT,
                county TEXT,
                lat REAL NOT NULL,
                lon REAL NOT NULL
            )
        """)
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS poi_fts USING fts5(
                name, class, state, county,
                content=poi_features,
                content_rowid=id
            )
        """)
        await db.commit()

    # Download and parse each state
    total_inserted = 0
    async with aiohttp.ClientSession() as session:
        for state in tqdm(states, desc="States", file=sys.stderr):
            if state in checkpoint:
                log.info("State %s already processed, skipping", state)
                continue

            data = await download_state(session, state, checkpoint)
            if data is None:
                continue

            try:
                text = extract_text_from_zip(data)
            except (zipfile.BadZipFile, ValueError) as exc:
                log.error("Failed to extract %s: %s", state, exc)
                continue

            features = list(parse_gnis_text(text, bbox))
            log.info("State %s: %d features in bbox", state, len(features))

            async with aiosqlite.connect(str(output)) as db:
                for feat in features:
                    cur = await db.execute(
                        "INSERT INTO poi_features (name, class, state, county, lat, lon) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (feat["name"], feat["class"], feat["state"],
                         feat["county"], feat["lat"], feat["lon"]),
                    )
                    rowid = cur.lastrowid
                    await db.execute(
                        "INSERT INTO poi_fts (rowid, name, class, state, county) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (rowid, feat["name"], feat["class"], feat["state"],
                         feat["county"]),
                    )
                await db.commit()

            total_inserted += len(features)
            checkpoint[state] = True
            checkpoint_path.write_text(json.dumps(checkpoint, indent=2))

    log.info("Done. Total features inserted: %d", total_inserted)
    log.info("Database written to %s", output)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build a POI search index from GNIS data"
    )
    parser.add_argument(
        "--bbox", default=DEFAULT_BBOX,
        help="Bounding box as west,south,east,north (default: %(default)s)",
    )
    parser.add_argument(
        "--states", default=",".join(DEFAULT_STATES),
        help="Comma-separated state abbreviations (default: %(default)s)",
    )
    parser.add_argument(
        "--output", default="data/poi.sqlite",
        help="Output SQLite path (default: %(default)s)",
    )

    args = parser.parse_args()
    asyncio.run(build_database(args))


if __name__ == "__main__":
    main()
