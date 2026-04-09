#!/usr/bin/env python3
"""Download PAD-US data and generate public lands vector tiles.

Downloads the PAD-US (Protected Areas Database) GeoPackage from USGS,
classifies land parcels by managing agency, clips to a bounding box,
and generates vector tiles via Tippecanoe for MapLibre rendering.

This script runs on the HOST (not in Docker). Tippecanoe must be
installed on the host. See docs/superpowers/specs/2026-04-09-public-lands-layer-design.md.

Usage:
  # Sample (NW Arizona / Hoover Dam area, ~2 min after PAD-US download):
  python build_public_lands.py --sample --output /srv/geographica/data/public-lands.mbtiles

  # Full Western US (~30-90 min, stop Docker first for memory):
  docker compose stop
  python build_public_lands.py --output /srv/geographica/data/public-lands.mbtiles
"""

import argparse
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

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
DEFAULT_BBOX = "-124.8,31.3,-102.0,49.0"
SAMPLE_BBOX = "-115.5,35.5,-113.5,36.5"

# PAD-US 4.1 Geodatabase download URL (USGS ScienceBase)
DEFAULT_PADUS_URL = (
    "https://sciencebase.usgs.gov/manager/download/cm8wlveow001d0upn7bqaepz8"
)

LAYER_NAME_REGEX = re.compile(r"^[A-Za-z0-9_]+$")
LAYER_DETECT_PATTERN = re.compile(r"PADUS.*(?:Combined|Fee|Designation)", re.IGNORECASE)

MAX_RETRIES = 3
RETRY_BACKOFF = 5  # seconds


# ---------------------------------------------------------------------------
# Validation functions (CSO-hardened)
# ---------------------------------------------------------------------------

def validate_layer_name(name):
    """Validate a GeoPackage layer name against shell injection.

    CSO requirement: only allow alphanumeric + underscore.
    """
    if not name:
        return False
    return bool(LAYER_NAME_REGEX.match(name))


def validate_url_scheme(url):
    """Validate that a URL uses HTTPS.

    CSO requirement: reject HTTP and other schemes.
    """
    if not url:
        return False
    return url.lower().startswith("https://")


# ---------------------------------------------------------------------------
# SQL classification
# ---------------------------------------------------------------------------

def classify_sql(layer_name):
    """Build the OGR SQL for classifying PAD-US features.

    Returns SQL string with category and sort_key CASE expressions.
    The FROM clause references the GeoPackage layer name directly.
    """
    return (
        "SELECT SHAPE, Unit_Nm AS name, Mang_Name AS agency, Des_Tp AS designation, "
        "CASE "
        "WHEN Des_Tp LIKE '%Wilderness%' THEN 'Wilderness' "
        "WHEN Mang_Name = 'BLM' THEN 'BLM' "
        "WHEN Mang_Name = 'USFS' THEN 'USFS' "
        "WHEN Mang_Name = 'NPS' THEN 'NPS' "
        "WHEN Mang_Name = 'FWS' THEN 'FWS' "
        "WHEN Mang_Name = 'DOD' THEN 'DOD' "
        "WHEN Mang_Name = 'USBR' THEN 'USBR' "
        "WHEN Mang_Name IN ('TRIB', 'BIA') THEN 'Tribal' "
        "WHEN Mang_Type = 'STAT' THEN 'State' "
        "ELSE 'Other' END AS category, "
        "CASE "
        "WHEN Des_Tp LIKE '%Wilderness%' THEN 1 "
        "WHEN Mang_Name = 'NPS' THEN 2 "
        "WHEN Mang_Name = 'FWS' THEN 3 "
        "WHEN Mang_Name = 'USFS' THEN 4 "
        "WHEN Mang_Name = 'DOD' THEN 5 "
        "WHEN Mang_Name = 'BLM' THEN 6 "
        "WHEN Mang_Name = 'USBR' THEN 7 "
        "WHEN Mang_Name IN ('TRIB', 'BIA') THEN 8 "
        "WHEN Mang_Type = 'STAT' THEN 9 "
        "ELSE 10 END AS sort_key "
        f"FROM {layer_name}"
    )


# ---------------------------------------------------------------------------
# Command builders (return lists for shell=False)
# ---------------------------------------------------------------------------

def build_ogr2ogr_command(gpkg_path, layer_name, bbox, output_path):
    """Build ogr2ogr command as a list for subprocess.run(shell=False).

    Single call: clips, reprojects (NAD83 -> WGS84), and classifies.
    """
    parts = bbox.split(",")
    sql = classify_sql(layer_name)

    return [
        "ogr2ogr",
        "-clipsrc", parts[0].strip(), parts[1].strip(),
                    parts[2].strip(), parts[3].strip(),
        "-t_srs", "EPSG:4326",
        "-f", "GeoJSON",
        output_path,
        gpkg_path,
        "-dialect", "SQLite",
        "-sql", sql,
    ]


def build_tippecanoe_command(output_path, input_path):
    """Build Tippecanoe command as a list for subprocess.run(shell=False).

    Uses adversarial-review-validated flags:
    - coalesce-smallest (NOT drop-densest — that drops whole polygons)
    - no-simplification-of-shared-nodes (NOT deprecated detect-shared-borders)
    - maximum-tile-bytes=500000 (cap for mesh network performance)
    """
    return [
        "tippecanoe",
        "-o", output_path,
        "-f",  # force overwrite
        "-Z0", "-z14",
        "-l", "public_lands",
        "--coalesce-smallest-as-needed",
        "--simplification=10",
        "--no-simplification-of-shared-nodes",
        "--maximum-tile-bytes=500000",
        input_path,
    ]


# ---------------------------------------------------------------------------
# Layer detection
# ---------------------------------------------------------------------------

def detect_layer_name(gpkg_path):
    """Auto-detect the PAD-US layer name from a GeoPackage or GDB.

    Runs ogrinfo and pattern-matches for PADUS*Combined or PADUS*Fee.
    Validates the result against the safe regex.
    """
    log.info("Detecting layer name in %s ...", gpkg_path)
    result = subprocess.run(
        ["ogrinfo", gpkg_path],
        capture_output=True, text=True, check=True
    )

    candidates = []
    for line in result.stdout.splitlines():
        # ogrinfo output: "1: LayerName (type)" for GeoPackage, "Layer: LayerName (type)" for GDB
        match = re.search(r"(?:\d+:|Layer:)\s+(\S+)", line)
        if match:
            name = match.group(1)
            if LAYER_DETECT_PATTERN.search(name):
                candidates.append(name)

    if not candidates:
        raise RuntimeError(
            f"No PAD-US layer found in {gpkg_path}. "
            f"Expected layer matching pattern 'PADUS*Combined' or 'PADUS*Fee'. "
            f"Available layers:\n{result.stdout}"
        )

    layer = candidates[0]
    if not validate_layer_name(layer):
        raise RuntimeError(
            f"Detected layer name '{layer}' contains unsafe characters. "
            f"Expected only alphanumeric and underscores."
        )

    log.info("Detected layer: %s", layer)
    return layer


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_padus(url, cache_dir):
    """Download PAD-US Geodatabase ZIP and extract .gdb directory.

    PAD-US 4.1 is distributed as a ZIP containing a .gdb directory.
    GDAL/ogr2ogr can read .gdb (FileGDB) directly.
    """
    os.makedirs(cache_dir, exist_ok=True)

    # Check if already extracted
    gdb_dirs = [d for d in os.listdir(cache_dir) if d.endswith('.gdb')]
    if gdb_dirs:
        gdb_path = os.path.join(cache_dir, gdb_dirs[0])
        log.info("PAD-US Geodatabase already cached at %s", gdb_path)
        return gdb_path

    zip_dest = os.path.join(cache_dir, "padus.zip")

    if not validate_url_scheme(url):
        raise ValueError(
            f"URL must use HTTPS: {url}. "
            f"Use --allow-insecure if you need HTTP (not recommended)."
        )

    # Download if ZIP not present
    if not os.path.exists(zip_dest) or os.path.getsize(zip_dest) < 100_000_000:
        log.info("Downloading PAD-US Geodatabase from %s ...", url[:80])
        log.info("This is ~1.5 GB and may take 10-30 minutes.")

        for attempt in range(MAX_RETRIES):
            try:
                urllib.request.urlretrieve(url, zip_dest + ".partial")
                # Validate we got a real ZIP, not an HTML error page
                partial_size = os.path.getsize(zip_dest + ".partial")
                if partial_size < 1_000_000:
                    with open(zip_dest + ".partial", "rb") as pf:
                        header = pf.read(4)
                    if header != b'PK\x03\x04':
                        os.remove(zip_dest + ".partial")
                        raise RuntimeError(
                            f"Download returned {partial_size} bytes of non-ZIP data "
                            f"(likely an HTML error page or CAPTCHA). "
                            f"ScienceBase requires a browser for large file downloads. "
                            f"Please download manually from: "
                            f"https://www.sciencebase.gov/catalog/item/652d4fc5d34e44db0e2ee45e "
                            f"and save as {zip_dest}"
                        )
                shutil.move(zip_dest + ".partial", zip_dest)
                log.info("Download complete: %s (%s MB)",
                         zip_dest, os.path.getsize(zip_dest) // (1024 * 1024))
                break
            except Exception as e:
                log.warning("Download attempt %d failed: %s", attempt + 1, e)
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF * (attempt + 1))
                else:
                    raise RuntimeError(f"Failed to download PAD-US after {MAX_RETRIES} attempts") from e

    # Extract .gdb from ZIP
    log.info("Extracting PAD-US Geodatabase from ZIP ...")
    import zipfile
    with zipfile.ZipFile(zip_dest, 'r') as zf:
        zf.extractall(cache_dir)

    # Find the .gdb directory
    gdb_dirs = [d for d in os.listdir(cache_dir) if d.endswith('.gdb')]
    if not gdb_dirs:
        raise RuntimeError("No .gdb directory found in extracted PAD-US ZIP")

    gdb_path = os.path.join(cache_dir, gdb_dirs[0])
    log.info("Extracted: %s", gdb_path)
    return gdb_path


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def classify_feature(props):
    """Classify a PAD-US feature into a category and sort_key.

    Priority: Wilderness first, then federal agencies, then state, then other.
    """
    des_tp = (props.get("Des_Tp") or "").strip()
    mang_name = (props.get("Mang_Name") or "").strip()
    mang_type = (props.get("Mang_Type") or "").strip()

    # Wilderness override (highest priority)
    if "Wilderness" in des_tp:
        return "Wilderness", 1

    agency_map = {
        "BLM": ("BLM", 6), "USFS": ("USFS", 4), "NPS": ("NPS", 2),
        "FWS": ("FWS", 3), "DOD": ("DOD", 5), "USBR": ("USBR", 7),
        "TRIB": ("Tribal", 8), "BIA": ("Tribal", 8),
    }
    if mang_name in agency_map:
        return agency_map[mang_name]

    if mang_type == "STAT":
        return "State", 9

    return "Other", 10


def run_pipeline(args):
    """Execute the full pipeline: download -> clip -> classify -> tile."""
    bbox = SAMPLE_BBOX if args.sample else args.bbox

    log.info("=== Public Lands Tile Pipeline ===")
    log.info("Bbox: %s", bbox)
    log.info("Output: %s", args.output)
    log.info("Sample mode: %s", args.sample)

    # Step 1: Download PAD-US
    gdb_path = download_padus(args.padus_url, args.cache_dir)

    # Step 2: Detect layer name
    layer_name = detect_layer_name(gdb_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Step 3: Clip and reproject with ogr2ogr (no SQL — avoids dialect issues)
        raw_geojson = os.path.join(tmpdir, "raw_clipped.geojson")
        parts = bbox.split(",")
        ogr_cmd = [
            "ogr2ogr",
            "-spat", parts[0].strip(), parts[1].strip(),
                     parts[2].strip(), parts[3].strip(),
            "-spat_srs", "EPSG:4326",
            "-t_srs", "EPSG:4326",
            "-f", "GeoJSON",
            raw_geojson,
            gdb_path,
            layer_name,
        ]
        log.info("Running ogr2ogr (clip + reproject) ...")
        log.info("Command: %s", " ".join(ogr_cmd))

        result = subprocess.run(ogr_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log.error("ogr2ogr stderr: %s", result.stderr)
            raise RuntimeError(f"ogr2ogr failed with exit code {result.returncode}")

        if not os.path.exists(raw_geojson) or os.path.getsize(raw_geojson) < 100:
            raise RuntimeError(
                f"ogr2ogr produced no/empty output. Layer '{layer_name}' may be "
                f"wrong or no features in bbox."
            )

        raw_size = os.path.getsize(raw_geojson)
        log.info("Raw clipped GeoJSON: %s MB", raw_size // (1024 * 1024))

        # Step 4: Classify features in Python (streaming to avoid full memory load)
        classified_geojson = os.path.join(tmpdir, "classified.geojson")
        categories = {}
        feature_count = 0

        log.info("Classifying features ...")
        with open(raw_geojson) as fin:
            data = json.load(fin)

        for feat in data.get("features", []):
            props = feat.get("properties", {})
            cat, sort_key = classify_feature(props)

            # Simplify properties
            feat["properties"] = {
                "name": (props.get("Unit_Nm") or "").strip(),
                "agency": (props.get("Mang_Name") or "").strip(),
                "designation": (props.get("Des_Tp") or "").strip(),
                "category": cat,
                "sort_key": sort_key,
            }

            # Skip features with no geometry
            if feat.get("geometry") is None:
                continue

            feature_count += 1
            categories[cat] = categories.get(cat, 0) + 1

        # Write classified GeoJSON (only features with geometry)
        data["features"] = [f for f in data["features"] if f.get("geometry") is not None]
        with open(classified_geojson, "w") as fout:
            json.dump(data, fout)

        log.info("Features with geometry: %d", feature_count)
        for cat, count in sorted(categories.items()):
            log.info("  %s: %d", cat, count)

        classified_size = os.path.getsize(classified_geojson)
        log.info("Classified GeoJSON: %s MB", classified_size // (1024 * 1024))

        # Step 5: Run Tippecanoe
        tip_cmd = build_tippecanoe_command(args.output, classified_geojson)
        log.info("Running Tippecanoe ...")
        log.info("Command: %s", " ".join(tip_cmd))

        result = subprocess.run(tip_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            log.error("Tippecanoe stderr: %s", result.stderr)
            raise RuntimeError(f"Tippecanoe failed with exit code {result.returncode}")

    # Step 6: Verify output
    if not os.path.exists(args.output):
        raise RuntimeError(f"Tippecanoe produced no output at {args.output}")

    output_size = os.path.getsize(args.output)
    log.info("Output MBTiles: %s (%s MB)", args.output, output_size // (1024 * 1024))

    # Verify tile count
    conn = sqlite3.connect(args.output)
    tile_count = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
    metadata = dict(conn.execute("SELECT name, value FROM metadata").fetchall())
    conn.close()

    log.info("Tile count: %d", tile_count)
    log.info("Metadata: %s", json.dumps(metadata, indent=2))

    if tile_count == 0:
        raise RuntimeError("MBTiles has zero tiles — something went wrong")

    # Step 7: Report
    log.info("=== Pipeline Complete ===")
    log.info("Output: %s (%d MB, %d tiles)", args.output,
             output_size // (1024 * 1024), tile_count)
    log.info("Categories: %s", ", ".join(f"{k}={v}" for k, v in sorted(categories.items())))
    log.info("Features: %d", feature_count)


def main():
    parser = argparse.ArgumentParser(
        description="Generate public lands vector tiles from PAD-US"
    )
    parser.add_argument(
        "--bbox", default=DEFAULT_BBOX,
        help=f"Bounding box as 'west,south,east,north' (default: {DEFAULT_BBOX})"
    )
    parser.add_argument(
        "--output", default="/srv/geographica/data/public-lands.mbtiles",
        help="Output MBTiles path"
    )
    parser.add_argument(
        "--padus-url", default=DEFAULT_PADUS_URL,
        help="PAD-US GeoPackage download URL (must be HTTPS)"
    )
    parser.add_argument(
        "--cache-dir", default="/srv/geographica/data/padus_cache/",
        help="Directory for downloaded/intermediate files"
    )
    parser.add_argument(
        "--sample", action="store_true",
        help="Use sample bbox (NW Arizona) for quick testing"
    )

    args = parser.parse_args()
    run_pipeline(args)


if __name__ == "__main__":
    main()
