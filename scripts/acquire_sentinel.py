#!/usr/bin/env python3
"""Download Sentinel-2 imagery from Copernicus and convert to MBTiles.

Uses the Copernicus STAC API to search for Sentinel-2 L2A scenes, downloads
COG files, composites them with GDAL, and produces an MBTiles output.

Usage:
  python acquire_sentinel.py --bbox "-112.5,33.0,-111.5,34.0" \
      --output /srv/geographica/data/imagery_sentinel.mbtiles \
      --staging /srv/geographica/data/staging_sentinel
"""

import argparse
import asyncio
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
from pipeline_progress import update_progress as _generic_progress
from pipeline_security import safe_staging_path, sanitize_scene_id, validate_file_header

# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


def _load_secrets() -> dict:
    """Load credentials from tmpfs secret file if available."""
    secrets_dir = Path("/secrets")
    if secrets_dir.exists():
        for f in secrets_dir.glob("*.json"):
            try:
                creds = json.loads(f.read_text())
                try:
                    f.unlink()
                except OSError:
                    pass  # read-only mount
                return creds
            except (json.JSONDecodeError, OSError):
                continue
    return {}


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
# NOTE: Legacy endpoint catalogue.dataspace.copernicus.eu/stac was deprecated Nov 2025
STAC_SEARCH_URL = "https://stac.dataspace.copernicus.eu/v1/search"
OAUTH_TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
    "protocol/openid-connect/token"
)
MAX_PAGES = 100
MAX_FILE_SIZE = 5 * 1024 * 1024 * 1024  # 5 GB
MIN_FREE_DISK = 10 * 1024 * 1024 * 1024  # 10 GB
CHECKPOINT_MAX_AGE = 24 * 3600  # 24 hours in seconds
CHUNK_SIZE_DEG = 2.0
MAX_RETRIES = 3
RETRY_BACKOFF = 2

# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------
_cancel_requested = False


def _handle_sigterm(signum, frame):
    """Handle SIGTERM for graceful shutdown (docker stop)."""
    global _cancel_requested
    log.info("SIGTERM received — finishing current batch and shutting down")
    _cancel_requested = True


signal.signal(signal.SIGTERM, _handle_sigterm)


# ---------------------------------------------------------------------------
# Progress helper
# ---------------------------------------------------------------------------
def update_progress(output_path: Path, phase: str, status: str = "running",
                    items_done: int = 0, items_total: int = 0,
                    detail: str = "", error: str = None, bbox: str = None):
    """Write progress via the shared pipeline_progress module."""
    state_path = Path(output_path).parent / ".pipeline-state.json"
    _generic_progress(
        state_path,
        source="sentinel",
        status=status,
        phase=phase,
        items_done=items_done,
        items_total=items_total,
        item_unit="scenes",
        detail=detail or f"{phase}: {items_done}/{items_total} scenes",
        error=error,
        bbox=bbox,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Download Sentinel-2 imagery to MBTiles")
    p.add_argument("--bbox", required=True, help="west,south,east,north")
    p.add_argument("--output", required=True, help="Output MBTiles path")
    p.add_argument("--staging", required=True, help="Staging directory for downloads")
    p.add_argument("--start-date", default=None,
                   help="Start date YYYY-MM-DD (default: 6 months ago)")
    p.add_argument("--end-date", default=None,
                   help="End date YYYY-MM-DD (default: today)")
    p.add_argument("--max-cloud", type=int, default=20,
                   help="Max cloud cover %% (default: 20)")
    p.add_argument("--composite", dest="composite", action="store_true", default=True,
                   help="Composite multiple scenes (default)")
    p.add_argument("--single", dest="composite", action="store_false",
                   help="Use single best scene")
    p.add_argument("--concurrency", type=int, default=3,
                   help="Download concurrency (default: 3)")
    return p.parse_args(argv)


def parse_bbox(s: str) -> tuple:
    parts = [float(x.strip()) for x in s.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be west,south,east,north")
    return tuple(parts)


# ---------------------------------------------------------------------------
# Spatial chunking
# ---------------------------------------------------------------------------
def compute_chunks(bbox: tuple) -> list:
    """Split bbox into <= 2x2 degree chunks if it spans > 2 degrees."""
    west, south, east, north = bbox
    width = east - west
    height = north - south

    if width <= CHUNK_SIZE_DEG and height <= CHUNK_SIZE_DEG:
        return [bbox]

    chunks = []
    lon = west
    while lon < east:
        lon_end = min(lon + CHUNK_SIZE_DEG, east)
        lat = south
        while lat < north:
            lat_end = min(lat + CHUNK_SIZE_DEG, north)
            chunks.append((lon, lat, lon_end, lat_end))
            lat = lat_end
        lon = lon_end
    return chunks


# ---------------------------------------------------------------------------
# OAuth2
# ---------------------------------------------------------------------------
class CopernicusAuth:
    """OAuth2 authentication for Copernicus Data Space."""

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.expires_at: float = 0

    async def authenticate(self, session: aiohttp.ClientSession) -> str:
        """Obtain a fresh access token via password grant."""
        data = {
            "grant_type": "password",
            "client_id": "cdse-public",
            "username": self.username,
            "password": self.password,
        }
        async with session.post(OAUTH_TOKEN_URL, data=data) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"OAuth2 authentication failed ({resp.status}): {body}")
            payload = await resp.json()

        self.access_token = payload["access_token"]
        self.refresh_token = payload.get("refresh_token")
        self.expires_at = time.monotonic() + payload.get("expires_in", 600)
        log.info("Authenticated with Copernicus (expires in %ss)", payload.get("expires_in", 600))
        return self.access_token

    async def refresh(self, session: aiohttp.ClientSession) -> str:
        """Refresh the access token using the refresh token."""
        if not self.refresh_token:
            return await self.authenticate(session)

        data = {
            "grant_type": "refresh_token",
            "client_id": "cdse-public",
            "refresh_token": self.refresh_token,
        }
        try:
            async with session.post(OAUTH_TOKEN_URL, data=data) as resp:
                if resp.status != 200:
                    log.warning("Token refresh failed (%s), re-authenticating", resp.status)
                    return await self.authenticate(session)
                payload = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            log.warning("Token refresh error, re-authenticating from scratch")
            return await self.authenticate(session)

        self.access_token = payload["access_token"]
        self.refresh_token = payload.get("refresh_token", self.refresh_token)
        self.expires_at = time.monotonic() + payload.get("expires_in", 600)
        log.info("Token refreshed (expires in %ss)", payload.get("expires_in", 600))
        return self.access_token

    async def ensure_valid_token(self, session: aiohttp.ClientSession) -> str:
        """Return a valid access token, refreshing if within 60s of expiry."""
        if self.access_token is None:
            return await self.authenticate(session)
        if time.monotonic() >= self.expires_at - 60:
            return await self.refresh(session)
        return self.access_token

    @property
    def token_expiring_soon(self) -> bool:
        """True if token expires within 60 seconds."""
        return time.monotonic() >= self.expires_at - 60


# ---------------------------------------------------------------------------
# STAC search
# ---------------------------------------------------------------------------
def build_stac_query(bbox: tuple, start_date: str, end_date: str,
                     max_cloud: int, limit: int = 500) -> dict:
    """Build a STAC search request body."""
    return {
        "bbox": list(bbox),
        "datetime": f"{start_date}/{end_date}",
        "filter": {
            "op": "<=",
            "args": [{"property": "eo:cloud_cover"}, max_cloud],
        },
        "collections": ["sentinel-2-l2a"],
        "limit": limit,
    }


async def stac_search(session: aiohttp.ClientSession, bbox: tuple,
                       start_date: str, end_date: str, max_cloud: int) -> list:
    """Search the Copernicus STAC API, paginate up to MAX_PAGES."""
    query = build_stac_query(bbox, start_date, end_date, max_cloud)
    scenes = []
    page = 0
    url = STAC_SEARCH_URL

    while page < MAX_PAGES:
        if page == 0:
            async with session.post(url, json=query) as resp:
                if resp.status != 200:
                    log.error("STAC search failed: %s", resp.status)
                    break
                data = await resp.json()
        else:
            async with session.get(url) as resp:
                if resp.status != 200:
                    log.error("STAC pagination failed: %s", resp.status)
                    break
                data = await resp.json()

        features = data.get("features", [])
        for feat in features:
            cloud = feat.get("properties", {}).get("eo:cloud_cover", 100)
            if cloud <= max_cloud:
                scenes.append(feat)

        # Find next page link
        next_url = None
        for link in data.get("links", []):
            if link.get("rel") == "next":
                next_url = link.get("href")
                break

        if not next_url or not features:
            break

        url = next_url
        page += 1

    return scenes


def load_checkpoint(staging: Path) -> list | None:
    """Load searched_scenes.json if it exists and is < 24 hours old."""
    cp = staging / "searched_scenes.json"
    if not cp.exists():
        return None
    try:
        stat = cp.stat()
        age = time.time() - stat.st_mtime
        if age > CHECKPOINT_MAX_AGE:
            log.info("Checkpoint too old (%.0fh), re-searching", age / 3600)
            return None
        data = json.loads(cp.read_text())
        log.info("Loaded %d scenes from checkpoint", len(data))
        return data
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load checkpoint: %s", exc)
        return None


def save_checkpoint(staging: Path, scenes: list):
    """Write searched_scenes.json checkpoint."""
    cp = staging / "searched_scenes.json"
    tmp = cp.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(scenes, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp), str(cp))
    log.info("Saved %d scenes to checkpoint", len(scenes))


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def get_download_url(scene: dict) -> str | None:
    """Extract download URL from STAC assets."""
    assets = scene.get("assets", {})
    # Prefer 'visual' asset
    if "visual" in assets:
        return assets["visual"].get("href")
    # Fall back to first available
    for key, asset in assets.items():
        href = asset.get("href")
        if href:
            return href
    return None


async def download_scene(session: aiohttp.ClientSession, scene: dict,
                          staging: Path, auth: CopernicusAuth,
                          semaphore: asyncio.Semaphore) -> Path | None:
    """Download a single scene to staging directory."""
    scene_id = scene.get("id", "unknown")
    url = get_download_url(scene)
    if not url:
        log.warning("No download URL for scene %s", scene_id)
        return None

    filename = f"sentinel_{sanitize_scene_id(scene_id)}.tif"
    try:
        dest = safe_staging_path(staging, filename)
    except ValueError as exc:
        log.error("Unsafe filename for scene %s: %s", scene_id, exc)
        return None

    # Disk space check
    free = shutil.disk_usage(str(staging)).free
    if free < MIN_FREE_DISK:
        log.error("Insufficient disk space: %.1f GB free < 10 GB minimum",
                  free / (1024 ** 3))
        raise RuntimeError("Insufficient disk space")

    async with semaphore:
        for attempt in range(MAX_RETRIES):
            # Refresh token before each attempt (B5 fix: token may expire during retries)
            token = await auth.ensure_valid_token(session)
            headers = {"Authorization": f"Bearer {token}"}

            try:
                # SECURITY: Never set ssl=False or verify_ssl=False
                async with session.get(url, headers=headers,
                                       timeout=aiohttp.ClientTimeout(total=1200)) as resp:
                    if resp.status != 200:
                        if resp.status in (429, 500, 502, 503, 504):
                            wait = RETRY_BACKOFF * (2 ** attempt)
                            log.warning("HTTP %s for %s, retrying in %ss",
                                        resp.status, scene_id, wait)
                            await asyncio.sleep(wait)
                            continue
                        log.error("HTTP %s for scene %s — skipping", resp.status, scene_id)
                        return None

                    # Check content length
                    content_length = resp.content_length
                    if content_length and content_length > MAX_FILE_SIZE:
                        log.error("Scene %s too large (%.1f GB) — skipping",
                                  scene_id, content_length / (1024 ** 3))
                        return None

                    with open(dest, "wb") as f:
                        total = 0
                        async for chunk in resp.content.iter_chunked(1024 * 1024):
                            total += len(chunk)
                            if total > MAX_FILE_SIZE:
                                log.error("Scene %s exceeded 5 GB during download — aborting",
                                          scene_id)
                                f.close()
                                dest.unlink(missing_ok=True)
                                return None
                            f.write(chunk)

                    # Validate file header
                    if not validate_file_header(dest, "geotiff"):
                        log.error("Scene %s failed magic byte validation — removing", scene_id)
                        dest.unlink(missing_ok=True)
                        return None

                    log.info("Downloaded scene %s (%.1f MB)", scene_id,
                             dest.stat().st_size / (1024 * 1024))
                    return dest

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                wait = RETRY_BACKOFF * (2 ** attempt)
                log.warning("%s for scene %s — retrying in %ss", exc, scene_id, wait)
                await asyncio.sleep(wait)

        log.error("All retries exhausted for scene %s", scene_id)
        return None


# ---------------------------------------------------------------------------
# GDAL composite + convert
# ---------------------------------------------------------------------------
def run_gdal_composite(tif_files: list, output_path: Path, staging: Path):
    """Build VRT, translate to MBTiles, add overviews."""
    env = {
        **os.environ,
        "GDAL_CACHEMAX": "256",
        "GDAL_NUM_THREADS": "2",
    }

    vrt_path = staging / "composite.vrt"

    # Build VRT
    cmd_vrt = ["nice", "-n", "19", "gdalbuildvrt", str(vrt_path)] + [str(f) for f in tif_files]
    log.info("Building VRT from %d files", len(tif_files))
    subprocess.run(cmd_vrt, env=env, check=True, capture_output=True)

    # Translate to MBTiles
    cmd_translate = [
        "nice", "-n", "19",
        "gdal_translate", "-of", "MBTiles",
        "-co", "TILE_FORMAT=JPEG",
        "-co", "QUALITY=85",
        str(vrt_path), str(output_path),
    ]
    log.info("Converting VRT to MBTiles")
    subprocess.run(cmd_translate, env=env, check=True, capture_output=True)

    # Add overviews
    cmd_addo = [
        "nice", "-n", "19",
        "gdaladdo", "-r", "average", str(output_path),
        "2", "4", "8", "16",
    ]
    log.info("Adding overview pyramids")
    subprocess.run(cmd_addo, env=env, check=True, capture_output=True)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
async def run_pipeline(args):
    """Execute the full Sentinel-2 pipeline."""
    global _cancel_requested

    bbox = parse_bbox(args.bbox)
    output = Path(args.output)
    staging = Path(args.staging)
    staging.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc)
    end_date = args.end_date or today.strftime("%Y-%m-%d")
    start_date = args.start_date or (today - timedelta(days=180)).strftime("%Y-%m-%d")

    secrets = _load_secrets()
    username = secrets.get("copernicus_username") or os.environ.get("COPERNICUS_USERNAME", "")
    password = secrets.get("copernicus_password") or os.environ.get("COPERNICUS_PASSWORD", "")
    if not username or not password:
        log.error("Copernicus credentials required (via keyring or COPERNICUS_USERNAME/COPERNICUS_PASSWORD env vars)")
        update_progress(output, "authenticating", status="error",
                        error="Missing Copernicus credentials", bbox=args.bbox)
        return

    # --- Authenticate ---
    update_progress(output, "authenticating", bbox=args.bbox)
    auth = CopernicusAuth(username, password)

    async with aiohttp.ClientSession() as session:
        try:
            await auth.authenticate(session)
        except RuntimeError as exc:
            log.error("Authentication failed: %s", exc)
            update_progress(output, "authenticating", status="error",
                            error=str(exc), bbox=args.bbox)
            return

        if _cancel_requested:
            update_progress(output, "authenticating", status="cancelled", bbox=args.bbox)
            return

        # --- Search ---
        update_progress(output, "searching", bbox=args.bbox)
        scenes = load_checkpoint(staging)
        if scenes is None:
            chunks = compute_chunks(bbox)
            scenes = []
            for i, chunk in enumerate(chunks):
                if _cancel_requested:
                    update_progress(output, "searching", status="cancelled", bbox=args.bbox)
                    return
                log.info("Searching chunk %d/%d: %s", i + 1, len(chunks), chunk)
                chunk_scenes = await stac_search(session, chunk, start_date, end_date,
                                                  args.max_cloud)
                scenes.extend(chunk_scenes)
                update_progress(output, "searching", items_done=i + 1,
                                items_total=len(chunks),
                                detail=f"searching: chunk {i+1}/{len(chunks)}, {len(scenes)} scenes found",
                                bbox=args.bbox)

            save_checkpoint(staging, scenes)

        log.info("Total scenes to download: %d", len(scenes))

        if not scenes:
            log.warning("No scenes found matching criteria")
            update_progress(output, "completed", status="completed",
                            detail="No scenes found", bbox=args.bbox)
            return

        if _cancel_requested:
            update_progress(output, "searching", status="cancelled", bbox=args.bbox)
            return

        # --- Download ---
        update_progress(output, "downloading", items_total=len(scenes), bbox=args.bbox)
        semaphore = asyncio.Semaphore(args.concurrency)
        downloaded_files = []
        download_errors: list[str] = []
        completed_count = 0

        async def _download_one(scene: dict, index: int) -> Path | None:
            """Download a single scene, respecting cancellation."""
            nonlocal completed_count
            if _cancel_requested:
                return None
            try:
                result = await download_scene(session, scene, staging, auth, semaphore)
                completed_count += 1
                update_progress(output, "downloading",
                                items_done=completed_count, items_total=len(scenes),
                                detail=f"downloading: {completed_count}/{len(scenes)} scenes",
                                bbox=args.bbox)
                return result
            except RuntimeError as exc:
                download_errors.append(str(exc))
                return None

        results = await asyncio.gather(
            *[_download_one(scene, i) for i, scene in enumerate(scenes)],
            return_exceptions=False,
        )

        downloaded_files = [r for r in results if r is not None]

        if download_errors:
            log.error("Download errors: %s", "; ".join(download_errors))
            if not downloaded_files:
                update_progress(output, "downloading", status="error",
                                error=download_errors[0], bbox=args.bbox)
                return

        if _cancel_requested:
            update_progress(output, "downloading", status="cancelled",
                            items_done=len(downloaded_files), items_total=len(scenes),
                            bbox=args.bbox)
            return

    if not downloaded_files:
        log.warning("No files downloaded successfully")
        update_progress(output, "completed", status="completed",
                        detail="No files downloaded", bbox=args.bbox)
        return

    if _cancel_requested:
        update_progress(output, "downloading", status="cancelled", bbox=args.bbox)
        return

    # --- Composite ---
    update_progress(output, "compositing",
                    detail=f"compositing: {len(downloaded_files)} scenes",
                    bbox=args.bbox)

    if _cancel_requested:
        update_progress(output, "compositing", status="cancelled", bbox=args.bbox)
        return

    # --- Convert ---
    update_progress(output, "converting", detail="converting to MBTiles", bbox=args.bbox)
    try:
        run_gdal_composite(downloaded_files, output, staging)
    except subprocess.CalledProcessError as exc:
        log.error("GDAL processing failed: %s", exc)
        update_progress(output, "converting", status="error",
                        error=f"GDAL error: {exc}", bbox=args.bbox)
        return

    if _cancel_requested:
        update_progress(output, "converting", status="cancelled", bbox=args.bbox)
        return

    # --- Completed ---
    update_progress(output, "completed", status="completed",
                    items_done=len(downloaded_files), items_total=len(scenes),
                    detail=f"completed: {len(downloaded_files)} scenes",
                    bbox=args.bbox)
    log.info("Pipeline complete: %s (%d scenes)", output, len(downloaded_files))


def main():
    args = parse_args()
    asyncio.run(run_pipeline(args))


if __name__ == "__main__":
    main()
