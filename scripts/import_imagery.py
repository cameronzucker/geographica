#!/usr/bin/env python3
"""Import user-provided GeoTIFF files into MBTiles for Geographica.

Scans a drop directory, reprojects to Web Mercator, converts to MBTiles
in batches, and optionally cleans up source files.

Usage:
    python import_imagery.py --input /data/import --output /data/imagery_custom.mbtiles
    python import_imagery.py --input /data/import --name "phoenix drone" --output-dir /data
"""

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

from pipeline_security import sanitize_layer_name
from pipeline_progress import update_progress as _generic_progress
from tileserver_config import add_mbtiles_to_config

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Import shared conversion utilities
from acquire_imagery import convert_batch_to_mbtiles

BATCH_SIZE = 5
GDAL_ENV = {**os.environ, "GDAL_CACHEMAX": "512"}

OTHER_GEO_EXTENSIONS = {".jp2", ".sid", ".img", ".ecw", ".vrt"}


def scan_import_directory(import_dir: Path) -> dict:
    """Scan import directory for GeoTIFF files.

    Scans the directory and one level of subdirectories.
    Rejects symlinks.

    Returns dict with keys: tif_files, other_geo_files, total_bytes
    """
    tif_files = []
    other_geo_files = []
    total_bytes = 0

    dirs_to_scan = [import_dir]
    for item in import_dir.iterdir():
        if item.is_dir() and not item.is_symlink():
            dirs_to_scan.append(item)

    for scan_dir in dirs_to_scan:
        for item in scan_dir.iterdir():
            if item.is_symlink():
                continue
            if not item.is_file():
                continue
            ext = item.suffix.lower()
            if ext in (".tif", ".tiff"):
                tif_files.append(item)
                total_bytes += item.stat().st_size
            elif ext in OTHER_GEO_EXTENSIONS:
                other_geo_files.append(item)

    return {
        "tif_files": sorted(tif_files),
        "other_geo_files": sorted(other_geo_files),
        "total_bytes": total_bytes,
    }


def resolve_output_path(output_dir: Path, layer_name: str | None) -> Path:
    """Resolve output MBTiles path from optional layer name.

    None/empty -> imagery_custom.mbtiles
    Named -> imagery_{sanitized}.mbtiles
    """
    if not layer_name or not layer_name.strip():
        return output_dir / "imagery_custom.mbtiles"

    safe_name = sanitize_layer_name(layer_name)
    return output_dir / f"imagery_{safe_name}.mbtiles"


def reproject_geotiff(src: Path, dst: Path) -> bool:
    """Reproject a GeoTIFF to EPSG:3857 (Web Mercator). Returns True on success."""
    try:
        subprocess.run(
            [
                "gdalwarp", "-t_srs", "EPSG:3857",
                "-r", "lanczos",
                "-co", "TILED=YES",
                "-co", "COMPRESS=DEFLATE",
                str(src), str(dst),
            ],
            check=True, capture_output=True, text=True,
            timeout=3600, env=GDAL_ENV,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.error("gdalwarp failed for %s: %s", src.name, exc)
        if dst.exists():
            dst.unlink()
        return False


def run_import(
    import_dir: Path,
    output_path: Path,
    delete_after: bool = False,
    tileserver_config: Path | None = None,
) -> None:
    """Run the BYO import pipeline."""
    state_path = output_path.parent / ".import-state.json"

    scan = scan_import_directory(import_dir)
    tif_files = scan["tif_files"]

    if not tif_files:
        log.error("No GeoTIFF files found in %s", import_dir)
        _generic_progress(state_path, source="import", status="error",
                          detail="No GeoTIFF files found",
                          error="No .tif files in import directory")
        return

    log.info("Found %d GeoTIFFs (%.1f GB) in %s",
             len(tif_files), scan["total_bytes"] / 1e9, import_dir)

    if scan["other_geo_files"]:
        exts = set(f.suffix for f in scan["other_geo_files"])
        log.warning("Found %d unsupported files (%s) — only .tif/.tiff is imported",
                    len(scan["other_geo_files"]), ", ".join(exts))

    total = len(tif_files)
    staging_dir = output_path.parent / "import_staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    completed = 0
    for batch_start in range(0, total, BATCH_SIZE):
        batch = tif_files[batch_start:batch_start + BATCH_SIZE]
        warped_paths = []

        for tif in batch:
            _generic_progress(state_path, source="import", status="running",
                              phase="converting",
                              items_done=completed, items_total=total,
                              item_unit="files",
                              detail=f"Reprojecting {tif.name}")

            warped = staging_dir / f"warped_{tif.name}"
            if reproject_geotiff(tif, warped):
                warped_paths.append(warped)
            else:
                log.warning("Skipping %s (reproject failed)", tif.name)

        if warped_paths:
            _generic_progress(state_path, source="import", status="running",
                              phase="merging",
                              items_done=completed, items_total=total,
                              item_unit="files",
                              detail="Converting batch to MBTiles")

            success = convert_batch_to_mbtiles(
                warped_paths, output_path, f"import_{batch_start}"
            )
            if not success:
                log.error("Batch conversion failed at offset %d", batch_start)

        for wp in warped_paths:
            if wp.exists():
                wp.unlink()

        if delete_after:
            # Only delete source files whose reprojection succeeded
            for tif in batch:
                warped = staging_dir / f"warped_{tif.name}"
                # If the warped file was in our success list, the source is safe to delete
                if any(wp.name == f"warped_{tif.name}" for wp in warped_paths):
                    if tif.exists():
                        tif.unlink()
                        log.info("Deleted source: %s", tif)

        completed += len(batch)

    if tileserver_config and tileserver_config.exists():
        name = output_path.stem
        added = add_mbtiles_to_config(
            tileserver_config, name, f"/srv/data/{output_path.name}"
        )
        if added:
            log.info("Added %s to TileServer config.json", name)

    _generic_progress(state_path, source="import", status="completed",
                      items_done=total, items_total=total,
                      item_unit="files",
                      detail=f"Imported {total} files into {output_path.name}")
    log.info("Import complete: %d files -> %s", total, output_path)


def main():
    parser = argparse.ArgumentParser(description="Import GeoTIFF files into MBTiles")
    parser.add_argument("--input", required=True, help="Import directory path")
    parser.add_argument("--output", default=None, help="Output MBTiles path (overrides --name)")
    parser.add_argument("--output-dir", default="/data", help="Output directory (used with --name)")
    parser.add_argument("--name", default=None, help="Layer name (default: imagery_custom)")
    parser.add_argument("--delete-after", action="store_true", help="Delete source files after import")
    parser.add_argument("--tileserver-config", default=None, help="Path to tileserver/config.json")

    args = parser.parse_args()

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = resolve_output_path(Path(args.output_dir), args.name)

    run_import(
        import_dir=Path(args.input),
        output_path=output_path,
        delete_after=args.delete_after,
        tileserver_config=Path(args.tileserver_config) if args.tileserver_config else None,
    )


if __name__ == "__main__":
    main()
