#!/usr/bin/env python3
"""Download USDA NAIP county mosaics and convert to MBTiles.

Queries the USDA Geospatial Data Gateway for county-level NAIP mosaics,
downloads JPEG2000 files, converts to GeoTIFF via GDAL, then merges all
counties into a single MBTiles file.

Usage:
  python acquire_naip.py --bbox "-112.5,33.0,-111.5,33.8" \
      --output /srv/geographica/data/imagery_naip.mbtiles \
      --staging /srv/geographica/data/naip_staging \
      --counties-db /srv/geographica/data/counties.sqlite
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
from pathlib import Path

import aiohttp

from build_county_index import counties_for_bbox
from gdal_subprocess import run_gdal_subprocess
from pipeline_progress import update_progress as _generic_progress
from pipeline_security import safe_staging_path, sanitize_fips, validate_file_header

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
USDA_GATEWAY_URL = "https://datagateway.nrcs.usda.gov/GDGHome_DirectDownLoad.aspx"
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # seconds, doubled each attempt
MIN_FREE_SPACE_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB
MAX_JP2_SIZE_BYTES = 30 * 1024 * 1024 * 1024  # 30 GB

# GDAL environment for memory-safe operation on Pi 5
GDAL_ENV = {
    **os.environ,
    "GDAL_CACHEMAX": "256",
    "GDAL_NUM_THREADS": "2",
}

# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------
_cancel_requested = False
_child_pid: int | None = None  # set by run_gdal_subprocess while a child is running


def _handle_sigterm(signum, frame):
    """Handle SIGTERM for graceful shutdown (docker stop)."""
    global _cancel_requested
    log.info("SIGTERM received - cancelling and killing any GDAL child")
    _cancel_requested = True
    # B5 fix: forward SIGTERM to the GDAL child's process group so a
    # long-running gdaladdo doesn't block cancel for 30+ minutes.
    if _child_pid is not None:
        try:
            import os as _os
            _os.killpg(_os.getpgid(_child_pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass


signal.signal(signal.SIGTERM, _handle_sigterm)


# ---------------------------------------------------------------------------
# Progress helpers
# ---------------------------------------------------------------------------

def update_progress(state_path: Path, *, phase: str, status: str = "running",
                    items_done: int = 0, items_total: int = 0,
                    detail: str, error: str = None, bbox: str = None):
    """Write NAIP pipeline progress to state file."""
    _generic_progress(
        state_path,
        source="naip",
        status=status,
        phase=phase,
        items_done=items_done,
        items_total=items_total,
        item_unit="counties",
        detail=detail,
        error=error,
        bbox=bbox,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_bbox(s: str) -> tuple[float, float, float, float]:
    parts = [float(x.strip()) for x in s.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be west,south,east,north")
    return tuple(parts)  # type: ignore[return-value]


def check_gdal_jp2_support() -> bool:
    """Check that GDAL has JP2OpenJPEG driver available."""
    try:
        result = subprocess.run(
            ["gdalinfo", "--formats"],
            capture_output=True, text=True, timeout=30,
        )
        return "JP2OpenJPEG" in result.stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def check_disk_space(path: Path, min_bytes: int = MIN_FREE_SPACE_BYTES) -> None:
    """Raise RuntimeError if free disk space is below threshold."""
    usage = shutil.disk_usage(str(path))
    if usage.free < min_bytes:
        free_gb = usage.free / (1024 ** 3)
        min_gb = min_bytes / (1024 ** 3)
        raise RuntimeError(
            f"Insufficient disk space: {free_gb:.1f} GB free, need at least {min_gb:.1f} GB"
        )


async def fetch_with_retry(session: aiohttp.ClientSession, url: str,
                           retries: int = MAX_RETRIES,
                           timeout_s: int = 1200) -> bytes | None:
    """GET url with exponential-backoff retry. Returns bytes or None."""
    for attempt in range(retries):
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=timeout_s)
            ) as resp:
                if resp.status == 200:
                    return await resp.read()
                if resp.status in (429, 500, 502, 503, 504):
                    wait = RETRY_BACKOFF * (2 ** attempt)
                    log.warning("HTTP %s for %s - retrying in %ss", resp.status, url, wait)
                    await asyncio.sleep(wait)
                    continue
                log.error("HTTP %s for %s - skipping", resp.status, url)
                return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            wait = RETRY_BACKOFF * (2 ** attempt)
            log.warning("%s for %s - retrying in %ss", exc, url, wait)
            await asyncio.sleep(wait)
    log.error("All retries exhausted for %s", url)
    return None


async def fetch_to_file(session: aiohttp.ClientSession, url: str,
                        dest: Path, *,
                        retries: int = MAX_RETRIES,
                        timeout_s: int = 1200,
                        max_size: int = MAX_JP2_SIZE_BYTES) -> bool:
    """Stream-download url to dest file with retry. Returns True on success.

    Streams to disk via iter_chunked() to avoid loading large JP2 files
    (up to 30GB) into memory (B3 OOM fix).
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


def extract_download_urls(html: str) -> list[dict]:
    """Parse USDA Gateway HTML to extract download links.

    Returns list of dicts with keys: url, format ("jp2" or "sid"), filename.
    """
    import re
    links = []
    # Look for href links pointing to .jp2 or .sid files
    pattern = re.compile(
        r'href=["\']([^"\']*\.(?:jp2|sid))["\']',
        re.IGNORECASE,
    )
    for match in pattern.finditer(html):
        url = match.group(1)
        filename = url.rsplit("/", 1)[-1] if "/" in url else url
        ext = filename.rsplit(".", 1)[-1].lower()
        fmt = "jp2" if ext == "jp2" else "sid"
        links.append({"url": url, "format": fmt, "filename": filename})
    return links


def select_best_url(links: list[dict]) -> dict | None:
    """Select best download URL, preferring JP2 over MrSID.

    Returns the chosen link dict, or None if only MrSID available.
    """
    jp2_links = [l for l in links if l["format"] == "jp2"]
    if jp2_links:
        return jp2_links[0]
    # MrSID only - not supported on ARM64
    return None


# ---------------------------------------------------------------------------
# Checkpoint management
# ---------------------------------------------------------------------------

def load_checkpoint(staging_dir: Path) -> dict:
    """Load checkpoint from staging directory."""
    cp_path = staging_dir / "checkpoint.json"
    if cp_path.exists():
        try:
            return json.loads(cp_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"completed_counties": [], "skipped_counties": [], "discovered_urls": {}}


def save_checkpoint(staging_dir: Path, checkpoint: dict) -> None:
    """Save checkpoint atomically."""
    cp_path = staging_dir / "checkpoint.json"
    tmp_path = cp_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp_path), str(cp_path))


def save_discovered_urls(staging_dir: Path, urls: dict) -> None:
    """Save discovered URLs cache."""
    url_path = staging_dir / "discovered_urls.json"
    tmp_path = url_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(urls, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp_path), str(url_path))


def load_discovered_urls(staging_dir: Path) -> dict:
    """Load cached discovered URLs."""
    url_path = staging_dir / "discovered_urls.json"
    if url_path.exists():
        try:
            return json.loads(url_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


# ---------------------------------------------------------------------------
# USDA Gateway discovery
# ---------------------------------------------------------------------------

async def discover_county_urls(
    session: aiohttp.ClientSession,
    counties: list[tuple],
    staging_dir: Path,
    state_path: Path,
    bbox_str: str,
) -> dict:
    """Discover download URLs for each county from USDA Gateway.

    Returns dict mapping fips -> {url, format, filename} for downloadable counties.
    Also returns skipped_counties list in the checkpoint.
    """
    checkpoint = load_checkpoint(staging_dir)
    discovered = load_discovered_urls(staging_dir)
    skipped = checkpoint.get("skipped_counties", [])
    skipped_fips = {s["fips"] for s in skipped}

    for idx, (fips, name, state_abbr, area) in enumerate(counties):
        if fips in discovered or fips in skipped_fips:
            continue

        if _cancel_requested:
            break

        update_progress(
            state_path, phase="discovering",
            items_done=idx, items_total=len(counties),
            detail=f"Querying USDA Gateway for {name}, {state_abbr}",
            bbox=bbox_str,
        )

        # Query USDA Gateway for this county
        params = {"fips": fips, "state": state_abbr}
        try:
            async with session.get(
                USDA_GATEWAY_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    log.warning("HTTP %s querying USDA Gateway for %s %s", resp.status, fips, name)
                    continue
                html = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("Failed to query USDA Gateway for %s %s: %s", fips, name, exc)
            continue

        links = extract_download_urls(html)
        if not links:
            log.warning("No download links found for %s %s", fips, name)
            skipped.append({"fips": fips, "name": name, "reason": "no download links found"})
            continue

        best = select_best_url(links)
        if best is None:
            log.warning("Skipped: %s (%s) - MrSID only, unsupported on ARM64", name, fips)
            skipped.append({"fips": fips, "name": name, "reason": "MrSID only, unsupported on ARM64"})
            continue

        # Validate with HEAD request
        try:
            async with session.head(
                best["url"],
                timeout=aiohttp.ClientTimeout(total=30),
            ) as head_resp:
                content_length = head_resp.headers.get("Content-Length")
                if content_length:
                    best["content_length"] = int(content_length)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            log.warning("HEAD request failed for %s, proceeding anyway", best["url"])

        discovered[fips] = best
        save_discovered_urls(staging_dir, discovered)

    # Update checkpoint with skipped counties
    checkpoint["skipped_counties"] = skipped
    save_checkpoint(staging_dir, checkpoint)

    update_progress(
        state_path, phase="discovering",
        items_done=len(counties), items_total=len(counties),
        detail=f"Discovered {len(discovered)} counties, skipped {len(skipped)}",
        bbox=bbox_str,
    )

    return discovered


# ---------------------------------------------------------------------------
# Download + convert pipeline
# ---------------------------------------------------------------------------

async def download_county(
    session: aiohttp.ClientSession,
    fips: str,
    url_info: dict,
    staging_dir: Path,
) -> Path | None:
    """Download a county JP2 to staging directory. Returns path or None."""
    safe_fips = sanitize_fips(fips)
    filename = f"naip_{safe_fips}.jp2"
    dest = safe_staging_path(staging_dir, filename)

    # Skip if already downloaded
    if dest.exists() and dest.stat().st_size > 0:
        log.info("Using existing download: %s", dest)
        return dest

    log.info("Downloading %s -> %s", url_info["url"], dest)
    success = await fetch_to_file(session, url_info["url"], dest)
    if not success:
        return None

    return dest


def convert_jp2_to_geotiff(jp2_path: Path, staging_dir: Path, fips: str) -> Path | None:
    """Convert JP2 to GeoTIFF using GDAL. Returns GeoTIFF path or None."""
    safe_fips = sanitize_fips(fips)
    tif_filename = f"naip_{safe_fips}.tif"
    tif_path = safe_staging_path(staging_dir, tif_filename)

    # Skip if already converted
    if tif_path.exists() and tif_path.stat().st_size > 0:
        log.info("Using existing GeoTIFF: %s", tif_path)
        return tif_path

    inner_cmd = [
        "gdal_translate", "-of", "GTiff",
        "-co", "TILED=YES",
        "-co", "COMPRESS=DEFLATE",
        str(jp2_path), str(tif_path),
    ]

    def _set_pid(pid: int) -> None:
        global _child_pid
        _child_pid = pid

    def _clear_pid() -> None:
        global _child_pid
        _child_pid = None

    # B5 fix: use shared helper so SIGTERM kills the GDAL child immediately
    # instead of waiting up to 3600s for it to finish.
    try:
        run_gdal_subprocess(
            inner_cmd, timeout=3600,
            cancel_check=lambda: _cancel_requested,
            on_child_started=_set_pid,
            on_child_ended=_clear_pid,
        )
    except subprocess.CalledProcessError as exc:
        log.error("GDAL translate failed for %s: %s", jp2_path, exc.stderr)
        if tif_path.exists():
            tif_path.unlink()
        return None
    except subprocess.TimeoutExpired:
        log.error("GDAL translate timed out for %s", jp2_path)
        if tif_path.exists():
            tif_path.unlink()
        return None

    return tif_path


def merge_to_mbtiles(geotiff_paths: list[Path], output_path: Path) -> bool:
    """Build VRT from all GeoTIFFs, then convert to MBTiles."""
    if not geotiff_paths:
        log.error("No GeoTIFFs to merge")
        return False

    vrt_path = output_path.parent / "naip_merge.vrt"
    tif_list_path = output_path.parent / "naip_tifs.txt"

    # Write file list for gdalbuildvrt
    tif_list_path.write_text("\n".join(str(p) for p in geotiff_paths))

    def _set_pid(pid: int) -> None:
        global _child_pid
        _child_pid = pid

    def _clear_pid() -> None:
        global _child_pid
        _child_pid = None

    _cc = lambda: _cancel_requested

    try:
        # Build VRT
        run_gdal_subprocess(
            ["gdalbuildvrt",
             "-input_file_list", str(tif_list_path),
             str(vrt_path)],
            timeout=600,
            cancel_check=_cc,
            on_child_started=_set_pid, on_child_ended=_clear_pid,
        )

        # Convert VRT to MBTiles
        run_gdal_subprocess(
            ["gdal_translate",
             "-of", "MBTiles",
             "-co", "TILE_FORMAT=JPEG",
             "-co", "QUALITY=85",
             str(vrt_path), str(output_path)],
            timeout=7200,
            cancel_check=_cc,
            on_child_started=_set_pid, on_child_ended=_clear_pid,
        )

        # Build overview pyramids
        run_gdal_subprocess(
            ["gdaladdo",
             "-r", "average",
             str(output_path),
             "2", "4", "8", "16"],
            timeout=3600,
            cancel_check=_cc,
            on_child_started=_set_pid, on_child_ended=_clear_pid,
        )

        return True

    except subprocess.CalledProcessError as exc:
        log.error("MBTiles merge failed: %s", exc.stderr)
        return False
    finally:
        # Cleanup temp files
        if vrt_path.exists():
            vrt_path.unlink()
        if tif_list_path.exists():
            tif_list_path.unlink()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def run_pipeline(
    bbox_str: str,
    output_path: Path,
    staging_dir: Path,
    counties_db: str,
    concurrency: int = 2,
    county_fips: str | None = None,
) -> None:
    """Run the full NAIP acquisition pipeline."""
    global _cancel_requested

    state_path = output_path.parent / ".pipeline-state.json"
    staging_dir.mkdir(parents=True, exist_ok=True)

    west, south, east, north = parse_bbox(bbox_str)

    # --- GDAL self-check ---
    if not check_gdal_jp2_support():
        update_progress(
            state_path, phase="converting", status="error",
            detail="GDAL JP2OpenJPEG driver not found",
            error="GDAL JP2OpenJPEG driver not available. Install GDAL with OpenJPEG support.",
            bbox=bbox_str,
        )
        log.error("GDAL JP2OpenJPEG driver not available. Cannot process NAIP JP2 files.")
        sys.exit(1)

    # --- Phase: resolving ---
    update_progress(
        state_path, phase="resolving",
        detail="Looking up counties for bbox",
        bbox=bbox_str,
    )

    if county_fips:
        # User provided explicit FIPS list — filter the full bbox results to just those
        all_counties = counties_for_bbox(counties_db, west, south, east, north)
        allowed = {f.strip() for f in county_fips.split(",")}
        counties = [c for c in all_counties if c[0] in allowed]
        log.info("Using %d user-selected counties (from %d in bbox)", len(counties), len(all_counties))
    else:
        counties = counties_for_bbox(counties_db, west, south, east, north)

    if not counties:
        update_progress(
            state_path, phase="resolving", status="error",
            detail="No counties found for bbox",
            error="No counties intersect the given bounding box.",
            bbox=bbox_str,
        )
        log.error("No counties found for bbox %s", bbox_str)
        return

    total_counties = len(counties)
    log.info("Found %d counties for bbox %s", total_counties, bbox_str)

    update_progress(
        state_path, phase="resolving",
        items_done=total_counties, items_total=total_counties,
        detail=f"Found {total_counties} counties",
        bbox=bbox_str,
    )

    # --- Phase: discovering ---
    # SECURITY: Never set ssl=False or verify_ssl=False
    async with aiohttp.ClientSession() as session:
        discovered = await discover_county_urls(
            session, counties, staging_dir, state_path, bbox_str,
        )

        if not discovered:
            checkpoint = load_checkpoint(staging_dir)
            skipped = checkpoint.get("skipped_counties", [])
            update_progress(
                state_path, phase="discovering", status="error",
                detail=f"No downloadable counties found (skipped {len(skipped)})",
                error="No counties with JP2 downloads found.",
                bbox=bbox_str,
            )
            log.error("No downloadable counties found")
            return

        # --- Phase: downloading + converting (per-county) ---
        checkpoint = load_checkpoint(staging_dir)
        completed = set(checkpoint.get("completed_counties", []))
        geotiff_paths = []

        # Collect existing GeoTIFFs from completed counties
        for fips in completed:
            safe_fips = sanitize_fips(fips)
            tif_path = staging_dir / f"naip_{safe_fips}.tif"
            if tif_path.exists():
                geotiff_paths.append(tif_path)

        downloadable = [
            (fips, info) for fips, info in discovered.items()
            if fips not in completed
        ]

        download_sem = asyncio.Semaphore(concurrency)

        async def _process_county(fips: str, url_info: dict) -> Path | None:
            """Download, validate, and convert a single county."""
            if _cancel_requested:
                return None

            county_name = next(
                (f"{name}, {st}" for f, name, st, _ in counties if f == fips),
                fips,
            )

            # Check disk space before download
            check_disk_space(staging_dir)

            async with download_sem:
                if _cancel_requested:
                    return None

                update_progress(
                    state_path, phase="downloading",
                    items_done=len(completed), items_total=len(discovered),
                    detail=f"Downloading {county_name}",
                    bbox=bbox_str,
                )

                jp2_path = await download_county(session, fips, url_info, staging_dir)

            if jp2_path is None:
                log.warning("Failed to download %s, skipping", county_name)
                return None

            # Validate JP2 magic bytes
            if not validate_file_header(jp2_path, "jp2"):
                log.error("Invalid JP2 file for %s - removing", county_name)
                jp2_path.unlink()
                return None

            # Validate file size
            if jp2_path.stat().st_size > MAX_JP2_SIZE_BYTES:
                log.error("JP2 too large for %s (%d bytes) - removing",
                          county_name, jp2_path.stat().st_size)
                jp2_path.unlink()
                return None

            # Convert JP2 -> GeoTIFF (runs outside semaphore, one at a time)
            update_progress(
                state_path, phase="converting",
                items_done=len(completed), items_total=len(discovered),
                detail=f"Converting {county_name}",
                bbox=bbox_str,
            )

            tif_path = convert_jp2_to_geotiff(jp2_path, staging_dir, fips)

            # Delete JP2 immediately after conversion
            if jp2_path.exists():
                jp2_path.unlink()
                log.info("Deleted JP2: %s", jp2_path)

            if tif_path is None:
                log.warning("Failed to convert %s, skipping", county_name)
                return None

            return tif_path

        # B16 fix: run counties concurrently up to the `concurrency` cap.
        # _process_county already uses `async with download_sem:` which
        # bounds simultaneous downloads; the semaphore is created at
        # concurrency and only now wired via asyncio.gather.
        # Checkpoint writes need their own lock because multiple
        # _process_county completions finish concurrently.
        checkpoint_lock = asyncio.Lock()

        async def _process_and_checkpoint(fips: str, url_info: dict) -> Path | None:
            """Process one county, then serialize the checkpoint write."""
            tif_path = await _process_county(fips, url_info)
            if tif_path is None:
                return None
            async with checkpoint_lock:
                completed.add(fips)
                checkpoint["completed_counties"] = list(completed)
                save_checkpoint(staging_dir, checkpoint)
            return tif_path

        if _cancel_requested:
            update_progress(
                state_path, phase="downloading", status="cancelled",
                items_done=len(completed), items_total=len(discovered),
                detail="Cancelled by user",
                bbox=bbox_str,
            )
            log.info("Cancelled after %d counties", len(completed))
            return

        # Gather all county tasks concurrently. The `download_sem` inside
        # _process_county bounds active downloads to `concurrency`; gather
        # itself is unbounded but each task will block on the semaphore.
        results = await asyncio.gather(
            *[_process_and_checkpoint(fips, info) for fips, info in downloadable],
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                log.warning("County task raised: %s", result)
                continue
            if result is not None:
                geotiff_paths.append(result)

    # --- Phase: merging ---
    if not geotiff_paths:
        update_progress(
            state_path, phase="merging", status="error",
            detail="No GeoTIFFs to merge",
            error="No counties were successfully downloaded and converted.",
            bbox=bbox_str,
        )
        return

    update_progress(
        state_path, phase="merging",
        items_done=0, items_total=1,
        detail=f"Merging {len(geotiff_paths)} counties into MBTiles",
        bbox=bbox_str,
    )

    success = merge_to_mbtiles(geotiff_paths, output_path)

    if not success:
        update_progress(
            state_path, phase="merging", status="error",
            detail="MBTiles merge failed",
            error="Failed to merge GeoTIFFs into MBTiles.",
            bbox=bbox_str,
        )
        return

    # Cleanup GeoTIFFs after successful merge
    for tif in geotiff_paths:
        if tif.exists():
            tif.unlink()
            log.info("Deleted GeoTIFF: %s", tif)

    # --- Phase: completed ---
    checkpoint_data = load_checkpoint(staging_dir)
    skipped = checkpoint_data.get("skipped_counties", [])
    update_progress(
        state_path, phase="completed", status="completed",
        items_done=len(completed), items_total=len(discovered),
        detail=f"Completed: {len(completed)} counties, {len(skipped)} skipped",
        bbox=bbox_str,
    )

    log.info(
        "NAIP pipeline complete: %d counties downloaded, %d skipped",
        len(completed), len(skipped),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Download USDA NAIP county mosaics and convert to MBTiles."
    )
    parser.add_argument("--bbox", required=True, help="west,south,east,north")
    parser.add_argument("--output", required=True, help="Output MBTiles path")
    parser.add_argument("--staging", required=True, help="Staging directory for temp files")
    parser.add_argument("--counties-db", required=True, help="Path to counties.sqlite")
    parser.add_argument("--concurrency", type=int, default=2, help="Download concurrency (default: 2)")
    parser.add_argument("--counties", default=None, help="Comma-separated FIPS codes (overrides bbox county lookup)")

    args = parser.parse_args()
    output_path = Path(args.output)
    staging_dir = Path(args.staging)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    asyncio.run(run_pipeline(
        bbox_str=args.bbox,
        output_path=output_path,
        staging_dir=staging_dir,
        counties_db=args.counties_db,
        concurrency=args.concurrency,
        county_fips=args.counties,
    ))


if __name__ == "__main__":
    main()
